from __future__ import annotations

import asyncio
from contextlib import suppress
import queue
import threading
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState





from backend.services.vonage_client import VonageClient
from backend.services.transcribe_stream import TranscribeStream
from backend.services.comprehend_utils import analyze_sentiment
from backend.services.bedrock_utils import classify_transcript_segments, _guess_category
from backend.services.repository import MeetingRepository
from backend.utils.auth_aws import get_session
from backend.utils.time_utils import now_iso
from backend.config import get_settings


class SessionController:
    def __init__(self, repository: MeetingRepository | None = None):
        self.vonage = VonageClient()
        self.transcribe = TranscribeStream()
        self.repository = repository or MeetingRepository()
        self.logger = logging.getLogger(__name__)
        self.settings = get_settings()
        self._classification_index = 1
        # Session用のデータ構造
        self.session_data = {}  # meeting_id -> session data

    def _build_session_payload(self, meeting, session_id: str, token: str) -> dict:
        return {
            "meeting_id": meeting.meeting_id,
            "title": meeting.title,
            "status": meeting.status,
            "session_id": session_id,
            "token": token,
            "api_key": self.vonage.settings.vonage_api_key,
        }

    def create_meeting(self, title: str, scheduled_for: str | None = None) -> dict:
        if not title or not title.strip():
            raise ValueError("title is required")

        meeting = self.repository.create_meeting(title=title.strip(), scheduled_for=scheduled_for)
        self.logger.info("Creating meeting meeting_id=%s title=%s", meeting.meeting_id, meeting.title)
        session = self.vonage.create_session(meeting.meeting_id)
        session_id = session["session_id"]
        meeting = self.repository.update_meeting(
            meeting.meeting_id, session_id=session_id, status="live"
        )

        token = self.vonage.generate_token(session_id=session_id)
        self.logger.info("Vonage credentials issued meeting_id=%s session_id=%s", meeting.meeting_id, session_id)
        return self._build_session_payload(meeting, session_id, token)

    def create_session_token(self, meeting_id: str) -> dict:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            self.logger.warning("Join requested for missing meeting_id=%s", meeting_id)
            raise ValueError("Meeting not found")

        session_id = meeting.session_id
        if not session_id:
            session = self.vonage.create_session(meeting_id)
            session_id = session["session_id"]
            meeting = self.repository.update_meeting(meeting_id, session_id=session_id, status="live")

        token = self.vonage.generate_token(session_id=session_id)
        self.logger.info("Join token issued meeting_id=%s session_id=%s", meeting_id, session_id)
        return self._build_session_payload(meeting, session_id, token)

    def validate_meeting(self, meeting_id: str) -> dict:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            self.logger.warning("Validation failed missing meeting_id=%s", meeting_id)
            raise ValueError("Meeting not found")
        self.logger.info("Validation success meeting_id=%s", meeting_id)
        return {"meeting_id": meeting.meeting_id, "status": meeting.status, "title": meeting.title}

    async def stream_transcripts(self, websocket: WebSocket, meeting_id: str) -> None:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            await websocket.close(code=4404)
            return

        await websocket.accept()
        
        # Initialize session data
        session_data = {
            "meeting_id": meeting_id,
            "transcripts": [],
            "queue": asyncio.Queue(),
            "speaker_labels": {"spk_unk": "判別中..."},
            "next_speaker_index": 1,
            "next_entry_index": 1,
            "pending_results": {},
            "processed_result_ids": set(),
            "pending_bedrock_tasks": set(),
            "agenda_text": meeting.title or "",  # Use meeting title as agenda
        }
        self.session_data[meeting_id] = session_data

        # Start real-time transcription
        try:
            await self._start_realtime_transcription(session_data, websocket)
        except Exception as e:
            self.logger.error("Transcription failed for meeting_id=%s: %s", meeting_id, e)
            await websocket.send_json({"error": f"Transcription failed: {e}"})
        finally:
            # Cleanup
            if meeting_id in self.session_data:
                del self.session_data[meeting_id]

    async def _start_realtime_transcription(self, session_data: dict, websocket: WebSocket) -> None:
        """Start real-time transcription using AWS Transcribe streaming directly."""
        meeting_id = session_data["meeting_id"]
        
        try:
            # Try AWS Transcribe streaming first
            await self._start_aws_transcribe_streaming(session_data, websocket)
            
        except Exception as e:
            self.logger.error("AWS Transcribe streaming failed: %s", e)
            # Fallback to TranscribeStream service
            try:
                await self._start_transcribe_service_fallback(session_data, websocket)
            except Exception as e2:
                self.logger.error("TranscribeStream service also failed: %s", e2)
                # Final fallback to mock transcription
                await self._start_mock_transcription(session_data, websocket)

    async def _start_transcribe_service_fallback(self, session_data: dict, websocket: WebSocket) -> None:
        """Fallback to TranscribeStream service with proper result handling."""
        meeting_id = session_data["meeting_id"]
        
        import queue
        import threading
        
        audio_queue = queue.Queue()
        
        def on_transcript_result(result):
            """Handle transcript results from TranscribeStream service."""
            try:
                transcript = result.get("transcript", "").strip()
                if not transcript:
                    return
                    
                is_partial = result.get("is_partial", False)
                
                # Generate a simple result_id for TranscribeStream service
                # Use timestamp-based ID to ensure uniqueness
                import time
                if not hasattr(session_data, 'current_utterance_start') or not is_partial:
                    session_data['current_utterance_start'] = int(time.time() * 1000)
                
                result_id = f"ts-{session_data['current_utterance_start']}"
                
                self.logger.info(f"TranscribeStream result: is_partial={is_partial}, result_id={result_id}, text='{transcript[:50]}...'")
                
                # Handle result with proper streaming logic
                asyncio.create_task(self._handle_result_streaming(
                    session_data, result_id, "Speaker 1", "spk_1", transcript, not is_partial, websocket
                ))
                    
            except Exception as e:
                self.logger.error("Error processing TranscribeStream result: %s", e)
        
        # Start transcription in background thread
        def run_transcription():
            try:
                self.transcribe.stream_audio(audio_queue, on_transcript_result)
            except Exception as e:
                self.logger.error("TranscribeStream thread error: %s", e)
        
        transcription_thread = threading.Thread(target=run_transcription, daemon=True)
        transcription_thread.start()
        
        # Handle WebSocket audio data
        await self._handle_websocket_audio_simple(websocket, audio_queue, session_data)

    async def _handle_websocket_audio_simple(self, websocket: WebSocket, audio_queue, session_data: dict) -> None:
        """Handle audio data from WebSocket and put into queue."""
        audio_count = 0
        
        try:
            while True:
                message = await websocket.receive()
                
                if message.get("type") == "websocket.disconnect":
                    break
                
                data = message.get("bytes")
                if data and len(data) > 0:
                    # Put audio data into queue for transcription
                    audio_queue.put(data)
                    audio_count += 1
                    
                    if audio_count % 100 == 0:
                        self.logger.debug(f"Queued {audio_count} audio chunks")
                        
                elif message.get("text"):
                    if message["text"] == "close":
                        break
                        
        except WebSocketDisconnect:
            self.logger.info("WebSocket disconnected during audio handling")
        except Exception as e:
            self.logger.error(f"Error handling WebSocket audio: {e}")
        finally:
            # Signal end of audio stream
            audio_queue.put(None)
            self.logger.info(f"Audio handling ended, processed {audio_count} chunks")



    async def _start_mock_transcription(self, session_data: dict, websocket: WebSocket) -> None:
        """Fallback mock transcription for testing."""
        meeting_id = session_data["meeting_id"]
        self.logger.info("Starting mock transcription for meeting_id=%s", meeting_id)
        
        mock_phrases = [
            "こんにちは、テストです",
            "音声認識のテストを行っています", 
            "マイクの音声が正常に送信されています",
            "文字起こし機能が動作しています",
            "リアルタイム分析のテストです"
        ]
        
        phrase_index = 0
        
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                    
                data = message.get("bytes")
                if data:
                    # Simulate transcription every 3 seconds
                    await asyncio.sleep(3)
                    phrase = mock_phrases[phrase_index % len(mock_phrases)]
                    
                    # Send transcript
                    await websocket.send_json({
                        "type": "transcript",
                        "meeting_id": meeting_id,
                        "timestamp": now_iso(),
                        "transcript": phrase,
                        "sentiment": "NEUTRAL",
                        "is_partial": False,
                    })
                    
                    # Send classification
                    await self._classify_and_send_realtime(websocket, meeting_id, phrase, "Speaker 1", phrase_index + 1)
                    phrase_index += 1
                    
        except WebSocketDisconnect:
            pass

    async def _start_aws_transcribe_streaming(self, session_data: dict, websocket: WebSocket) -> None:
        """Start AWS Transcribe streaming with proper result handling."""
        meeting_id = session_data["meeting_id"]
        self.logger.info("Starting AWS Transcribe streaming for meeting_id=%s", meeting_id)
        
        try:
            # Use the same approach as poc_satomin
            import queue
            import threading
            from amazon_transcribe.auth import StaticCredentialResolver
            from amazon_transcribe.client import TranscribeStreamingClient
            
            audio_queue = queue.Queue()
            
            # Start AWS Transcribe streaming in background
            def run_aws_transcription():
                try:
                    self._run_aws_transcribe_stream(session_data, audio_queue, websocket)
                except Exception as e:
                    self.logger.error("AWS Transcribe stream error: %s", e)
            
            transcription_thread = threading.Thread(target=run_aws_transcription, daemon=True)
            transcription_thread.start()
            
            # Handle WebSocket audio data
            await self._handle_websocket_audio_simple(websocket, audio_queue, session_data)
            
        except ImportError:
            self.logger.error("amazon-transcribe package not available")
            raise
        except Exception as e:
            self.logger.error("AWS Transcribe streaming setup failed: %s", e)
            raise

    def _run_aws_transcribe_stream(self, session_data: dict, audio_queue: queue.Queue, websocket: WebSocket) -> None:
        """Run AWS Transcribe streaming synchronously."""
        import asyncio
        
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self._async_aws_transcribe_stream(session_data, audio_queue, websocket))
        finally:
            loop.close()

    async def _async_aws_transcribe_stream(self, session_data: dict, audio_queue: queue.Queue, websocket: WebSocket) -> None:
        """Async AWS Transcribe streaming implementation."""
        from amazon_transcribe.auth import StaticCredentialResolver
        from amazon_transcribe.client import TranscribeStreamingClient
        
        # Get AWS credentials
        session = get_session()
        credentials = session.get_credentials()
        if not credentials:
            raise RuntimeError("AWS credentials not found")
            
        frozen = credentials.get_frozen_credentials()
        
        # Create credential resolver
        credential_resolver = StaticCredentialResolver(
            access_key_id=frozen.access_key,
            secret_access_key=frozen.secret_key,
            session_token=frozen.token,
        )
        
        # Create client
        client = TranscribeStreamingClient(
            region=self.settings.aws_region,
            credential_resolver=credential_resolver,
        )
        
        # Prepare PCM audio data
        pcm_data = []
        
        # Collect audio data from queue
        def collect_audio():
            while True:
                chunk = audio_queue.get()
                if chunk is None:
                    break
                pcm_data.append(chunk)
        
        # Start audio collection in background
        import threading
        audio_thread = threading.Thread(target=collect_audio, daemon=True)
        audio_thread.start()
        
        # Wait a bit for some audio data
        await asyncio.sleep(2)
        
        if not pcm_data:
            self.logger.warning("No audio data collected for transcription")
            return
        
        # Combine all PCM data
        combined_pcm = b''.join(pcm_data)
        
        # Start streaming
        stream = await client.start_stream_transcription(
            language_code="ja-JP",
            media_encoding="pcm",
            media_sample_rate_hz=16000,
            show_speaker_label=True,
            enable_partial_results_stabilization=True,
            partial_results_stability="medium",
        )
        
        # Send audio and process results
        async def send_audio():
            chunk_size = 3200  # 100ms chunks at 16kHz
            for i in range(0, len(combined_pcm), chunk_size):
                chunk = combined_pcm[i:i + chunk_size]
                await stream.input_stream.send_audio_event(audio_chunk=chunk)
                await asyncio.sleep(0.1)  # 100ms delay
            await stream.input_stream.end_stream()
        
        async def process_results():
            async for event in stream.output_stream:
                transcript = getattr(event, "transcript", None)
                if not transcript:
                    continue
                    
                for result in getattr(transcript, "results", []) or []:
                    result_id = getattr(result, "result_id", None)
                    if not result_id:
                        continue
                        
                    is_partial = getattr(result, "is_partial", False)
                    if not is_partial and result_id in session_data["processed_result_ids"]:
                        continue
                        
                    alternatives = getattr(result, "alternatives", []) or []
                    if not alternatives:
                        continue
                        
                    alternative = alternatives[0]
                    text = (getattr(alternative, "transcript", "") or "").strip()
                    if not text:
                        continue
                        
                    speaker_label, raw_label = self._speaker_from_items(session_data, alternative)
                    
                    self.logger.info(f"AWS Transcribe result: result_id={result_id}, is_partial={is_partial}, text='{text[:50]}...'")
                    
                    # Handle result with proper streaming logic using AWS result_id
                    await self._handle_result_streaming(
                        session_data, result_id, speaker_label, raw_label, text, not is_partial, websocket
                    )
                    
                    if not is_partial:
                        session_data["processed_result_ids"].add(result_id)
        
        # Run both tasks concurrently
        await asyncio.gather(send_audio(), process_results())

    def _speaker_from_items(self, session_data: dict, alternative: Any) -> tuple[str, str]:
        """Extract speaker information from transcribe alternative."""
        counts: dict[str, int] = {}
        for item in getattr(alternative, "items", []) or []:
            label = getattr(item, "speaker", None)
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
            
        raw_label = max(counts, key=counts.get) if counts else None
        normalized = self._normalize_raw_label(raw_label)
        friendly = self._speaker_name(session_data, normalized)
        return friendly, normalized

    def _normalize_raw_label(self, raw_label: str | None) -> str:
        """Normalize speaker label."""
        unknown_tokens = {"", "spk_unk", "__unknown__", "unknown", "unk", None}
        if raw_label in unknown_tokens:
            return "spk_unk"
        key_str = str(raw_label).strip()
        return key_str or "spk_unk"

    def _speaker_name(self, session_data: dict, raw_label: str | None) -> str:
        """Get friendly speaker name."""
        key = self._normalize_raw_label(raw_label)
        if key == "spk_unk":
            session_data["speaker_labels"].setdefault("spk_unk", "判別中...")
            return session_data["speaker_labels"]["spk_unk"]
            
        if key not in session_data["speaker_labels"]:
            label = f"Speaker {session_data['next_speaker_index']}"
            session_data["speaker_labels"][key] = label
            session_data["next_speaker_index"] += 1
            
        return session_data["speaker_labels"][key]

    async def _handle_result_streaming(self, session_data: dict, result_id: str, speaker_label: str, raw_label: str, text: str, is_final: bool, websocket: WebSocket) -> None:
        """Handle a single transcription result with proper partial update logic."""
        entry = session_data["pending_results"].get(result_id)
        
        if not entry:
            # New utterance - create new entry
            entry = {
                "index": session_data["next_entry_index"],
                "speaker": speaker_label,
                "raw_speaker": raw_label,
                "result_id": result_id,
                "text": text,
                "timestamp": now_iso(),
                "is_partial": not is_final,
            }
            
            session_data["pending_results"][result_id] = entry
            
            # Send append message for new utterance
            self.logger.info(f"📝 NEW utterance: result_id={result_id}, index={entry['index']}, is_final={is_final}, text='{text}'")
            await websocket.send_json({
                "type": "transcript",
                "action": "append",
                "payload": self._public_payload(entry)
            })
        else:
            # Existing utterance - update in place (same line)
            old_text = entry["text"]
            
            # Update speaker if we got better information
            current_raw = entry.get("raw_speaker", "spk_unk")
            if self._is_unknown_label(current_raw) and not self._is_unknown_label(raw_label):
                entry["raw_speaker"] = raw_label
                entry["speaker"] = self._speaker_name(session_data, raw_label)
            
            # Update text and partial status
            entry["text"] = text
            entry["is_partial"] = not is_final
            
            # Always send update for continuing utterance
            self.logger.info(f"🔄 UPDATE utterance: result_id={result_id}, is_final={is_final}, old='{old_text}' -> new='{text}'")
            await websocket.send_json({
                "type": "transcript",
                "action": "update",
                "payload": self._public_payload(entry)
            })
        
        # Handle final result - move to transcripts and start classification
        if is_final:
            self.logger.info(f"✅ FINAL result: result_id={result_id}, text='{text}'")
            
            # Increment index only when finalizing (creating new line)
            session_data["next_entry_index"] += 1
            
            await self._finalize_result_streaming(session_data, result_id, websocket)
            # Start classification for final results
            await self._classify_and_send_realtime(websocket, session_data["meeting_id"], text, speaker_label, entry["index"])

    async def _finalize_result_streaming(self, session_data: dict, result_id: str, websocket: WebSocket) -> None:
        """Finalize a transcription result."""
        if result_id in session_data["pending_results"]:
            entry = session_data["pending_results"].pop(result_id)
            payload = self._public_payload(entry)
            session_data["transcripts"].append(payload)
            
            # Send final update
            await websocket.send_json({
                "type": "transcript",
                "action": "update",
                "payload": payload
            })

    def _public_payload(self, entry: dict) -> dict:
        """Create public payload for WebSocket transmission."""
        return {
            "index": entry["index"],
            "speaker": entry["speaker"],
            "raw_speaker": entry.get("raw_speaker"),
            "result_id": entry.get("result_id"),
            "text": entry["text"],
            "timestamp": entry["timestamp"],
            "is_partial": entry.get("is_partial", False),
        }

    def _is_unknown_label(self, label: str) -> bool:
        """Check if speaker label is unknown."""
        unknown_tokens = {"", "spk_unk", "__unknown__", "unknown", "unk", None}
        return label in unknown_tokens

    def _speaker_name(self, session_data: dict, raw_label: str) -> str:
        """Get or create speaker name."""
        if self._is_unknown_label(raw_label):
            return "発話中..."
        
        if raw_label not in session_data["speaker_labels"]:
            speaker_num = session_data["next_speaker_index"]
            session_data["speaker_labels"][raw_label] = f"Speaker {speaker_num}"
            session_data["next_speaker_index"] += 1
        
        return session_data["speaker_labels"][raw_label]

    async def _classify_and_send_realtime(self, websocket: WebSocket, meeting_id: str, text: str, speaker: str, index: int) -> None:
        """Perform real-time classification like poc_satomin."""
        # Skip short texts
        text_stripped = text.strip()
        if len(text_stripped) < 10:
            return
            
        session_data = self.session_data.get(meeting_id)
        if not session_data:
            return
            
        # Skip meta information
        if text.startswith("Agenda topic:") or text.startswith("Discussion: Confirming action items for"):
            return
            
        # Step 1: Quick keyword-based classification
        category_quick = _guess_category(text)
        alignment_quick = self._calculate_alignment(text, session_data["agenda_text"])
        
        result_quick = {
            "index": index,
            "text": text,
            "speaker": speaker,
            "category": category_quick,
            "alignment": alignment_quick,
            "method": "keyword",
            "is_final": False
        }
        
        # Send quick result
        await websocket.send_json({
            "type": "realtime_classification",
            "payload": result_quick
        })
        
        # Step 2: Background Bedrock analysis
        task = asyncio.create_task(self._classify_with_bedrock(session_data, text, speaker, index, websocket))
        session_data["pending_bedrock_tasks"].add(task)
        task.add_done_callback(lambda t: session_data["pending_bedrock_tasks"].discard(t))

    async def _classify_with_bedrock(self, session_data: dict, text: str, speaker: str, index: int, websocket: WebSocket) -> None:
        """Bedrock classification in background."""
        try:
            # Get context
            context_before = ""
            context_after = ""
            for transcript in session_data["transcripts"]:
                if transcript.get("index") == index - 1:
                    context_before = transcript.get("text", "")
                elif transcript.get("index") == index + 1:
                    context_after = transcript.get("text", "")
            
            # Bedrock analysis
            segment = {
                "index": index,
                "speaker": speaker,
                "text": text,
                "context_before": context_before,
                "context_after": context_after,
            }
            
            classified = await asyncio.to_thread(
                classify_transcript_segments,
                [segment],
                session_data["agenda_text"]
            )
            
            if classified and len(classified) > 0:
                result = classified[0]
                category_ai = result.get("category", _guess_category(text))
                alignment_ai = result.get("alignment", 0)
                
                result_ai = {
                    "index": index,
                    "text": text,
                    "speaker": speaker,
                    "category": category_ai,
                    "alignment": alignment_ai,
                    "method": "bedrock",
                    "is_final": True
                }
                
                # Send AI result
                await websocket.send_json({
                    "type": "realtime_classification",
                    "action": "update",
                    "payload": result_ai
                })
                
                self.logger.info(f"Bedrock分析完了: {speaker} - {text} → [{category_ai}] {alignment_ai}%")
            else:
                # Fallback to keyword
                category_fallback = _guess_category(text)
                alignment_fallback = self._calculate_alignment(text, session_data["agenda_text"])
                
                result_fallback = {
                    "index": index,
                    "text": text,
                    "speaker": speaker,
                    "category": category_fallback,
                    "alignment": alignment_fallback,
                    "method": "keyword",
                    "is_final": True
                }
                
                await websocket.send_json({
                    "type": "realtime_classification",
                    "action": "update", 
                    "payload": result_fallback
                })
        
        except Exception as e:
            self.logger.error(f"Bedrock分析失敗: {e}")

    def _calculate_alignment(self, text: str, agenda_text: str) -> int:
        """Calculate alignment with agenda."""
        if not agenda_text or not agenda_text.strip():
            return 50
            
        # Skip meta information
        meta_keywords = ["議題", "タイトル", "所要時間", "発表者", "検討事項", "目的", "背景"]
        if any(keyword in text for keyword in meta_keywords):
            return 50
            
        # Extract keywords from agenda
        agenda_keywords = set()
        skip_keywords = {"議題", "タイトル", "所要時間", "発表者", "検討事項", "目的", "背景"}
        
        for line in agenda_text.splitlines():
            line = line.strip(" -*•\t0123456789.。")
            if not line:
                continue
            if any(skip in line for skip in skip_keywords):
                continue
            import re
            words = [w for w in re.findall(r'[ぁ-んァ-ヶ一-龠ー]+', line) if len(w) >= 2]
            words = [w for w in words if w not in skip_keywords]
            agenda_keywords.update(words)
        
        if not agenda_keywords:
            return 50
            
        # Count matches
        text_lower = text.lower()
        matched_count = sum(1 for keyword in agenda_keywords if keyword in text_lower)
        
        if matched_count == 0:
            return 30
            
        match_ratio = matched_count / len(agenda_keywords)
        alignment = min(100, int(30 + (match_ratio * 70)))
        
        return alignment


