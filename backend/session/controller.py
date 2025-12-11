from __future__ import annotations

import asyncio
from contextlib import suppress
import queue
import threading
import logging
import time
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
        
        # Initialize session data (same structure as poc_satomin)
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
            "agenda_text": meeting.title or "",
        }
        self.session_data[meeting_id] = session_data

        # Start real-time transcription with queue processing
        try:
            # Start transcription in background
            transcription_task = asyncio.create_task(
                self._start_realtime_transcription(session_data, websocket)
            )
            
            # Process queue messages (same as poc_satomin WebSocket handling)
            queue_task = asyncio.create_task(
                self._process_queue_messages(session_data, websocket)
            )
            
            # Wait for either task to complete
            done, pending = await asyncio.wait(
                [transcription_task, queue_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel remaining tasks safely
            for task in pending:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        self.logger.warning(f"Task cleanup error: {e}")
                
        except Exception as e:
            self.logger.error("Transcription failed for meeting_id=%s: %s", meeting_id, e)
            await websocket.send_json({"error": f"Transcription failed: {e}"})
        finally:
            # Wait for all Bedrock tasks to complete (same as poc_satomin)
            if session_data["pending_bedrock_tasks"]:
                self.logger.info(f"Waiting for {len(session_data['pending_bedrock_tasks'])} Bedrock tasks...")
                # Safely wait for tasks with proper exception handling
                for task in list(session_data["pending_bedrock_tasks"]):
                    try:
                        if not task.done():
                            await task
                    except Exception as e:
                        self.logger.warning(f"Bedrock task failed during cleanup: {e}")
                session_data["pending_bedrock_tasks"].clear()
            
            # Cleanup
            if meeting_id in self.session_data:
                del self.session_data[meeting_id]

    async def _start_realtime_transcription(self, session_data: dict, websocket: WebSocket) -> None:
        """Start real-time transcription using TranscribeStream service with improved logic."""
        meeting_id = session_data["meeting_id"]
        
        try:
            # Use the existing TranscribeStream service with queue
            import queue
            import threading
            
            audio_queue = queue.Queue()
            
            def on_transcript_result(result):
                """Callback for transcription results with simple utterance tracking."""
                try:
                    transcript = result.get("transcript", "").strip()
                    if not transcript:
                        return
                        
                    is_partial = result.get("is_partial", False)
                    
                    # Simple utterance tracking based on partial/final status
                    if not hasattr(session_data, 'current_utterance_id'):
                        session_data['current_utterance_id'] = None
                    
                    # Debug: Log the raw result structure
                    self.logger.info(f"Raw transcribe result: {result}")
                    
                    # Use result_id from the transcription service if available
                    aws_result_id = result.get("result_id") or result.get("ResultId")
                    
                    if aws_result_id:
                        result_id = f"aws_{aws_result_id}"
                        self.logger.info(f"Using AWS result_id: {aws_result_id}")
                    else:
                        # Simple fallback: one utterance ID until final result
                        if is_partial:
                            # For partial results, maintain current utterance ID
                            if session_data.get('current_utterance_id') is None:
                                session_data['current_utterance_id'] = f"session_{session_data['next_entry_index']}"
                                self.logger.info(f"Created new utterance ID: {session_data['current_utterance_id']}")
                            result_id = session_data['current_utterance_id']
                            self.logger.info(f"Using existing utterance ID: {result_id}")
                        else:
                            # For final results, use current ID and reset
                            if session_data.get('current_utterance_id') is not None:
                                result_id = session_data['current_utterance_id']
                                session_data['current_utterance_id'] = None  # Reset for next utterance
                                self.logger.info(f"Final result, using and resetting ID: {result_id}")
                            else:
                                result_id = f"session_{session_data['next_entry_index']}"
                                self.logger.info(f"No current ID, creating new: {result_id}")
                    
                    self.logger.info(f"TranscribeStream result: is_partial={is_partial}, text='{transcript}', result_id={result_id}")
                    
                    # Extract speaker information from transcribe result
                    raw_speaker = result.get("speaker_label")
                    self.logger.info(f"=== TRANSCRIBE CALLBACK DEBUG ===")
                    self.logger.info(f"Full result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                    self.logger.info(f"Raw speaker from result: '{raw_speaker}'")
                    
                    if not raw_speaker:
                        # Enhanced speaker change detection based on speech patterns
                        if not hasattr(session_data, 'speaker_detection_state'):
                            session_data['speaker_detection_state'] = {
                                'current_speaker_id': 0,
                                'last_final_time': 0,
                                'last_text_length': 0,
                                'silence_count': 0,
                                'utterance_count': 0
                            }
                        
                        state = session_data['speaker_detection_state']
                        current_time = time.time()
                        
                        if not is_partial:  # Only process final results for speaker change
                            state['utterance_count'] += 1
                            time_gap = current_time - state['last_final_time']
                            
                            # Detect speaker change based on multiple factors:
                            # 1. Long silence (>2 seconds)
                            # 2. Significant change in text length pattern
                            # 3. Every 4-6 utterances (natural conversation flow)
                            
                            should_change_speaker = False
                            change_reason = ""
                            
                            if time_gap > 2.5 and state['last_final_time'] > 0:
                                should_change_speaker = True
                                change_reason = f"silence_gap_{time_gap:.1f}s"
                            elif state['utterance_count'] % 5 == 0:  # Every 5 utterances
                                should_change_speaker = True
                                change_reason = f"utterance_count_{state['utterance_count']}"
                            
                            if should_change_speaker:
                                state['current_speaker_id'] = (state['current_speaker_id'] + 1) % 4  # Cycle through 4 speakers
                                self.logger.info(f"SPEAKER CHANGE DETECTED: {change_reason} -> spk_{state['current_speaker_id']}")
                            
                            state['last_final_time'] = current_time
                            state['last_text_length'] = len(transcript)
                        
                        raw_speaker = f"spk_{state['current_speaker_id']}"
                        self.logger.info(f"Enhanced speaker detection: {raw_speaker} (reason: speech pattern analysis)")
                    else:
                        self.logger.info(f"Raw speaker label from Transcribe: {raw_speaker}")
                    
                    speaker_label = self._speaker_name(session_data, raw_speaker)
                    self.logger.info(f"FINAL SPEAKER MAPPING: {raw_speaker} -> {speaker_label}")
                    
                    # Integrated transcription and analysis handling (use queue instead of websocket)
                    asyncio.create_task(self._handle_integrated_result(
                        session_data, result_id, speaker_label, raw_speaker, transcript, is_partial
                    ))
                        
                except Exception as e:
                    self.logger.error("Error processing transcript result: %s", e)
            
            # Start transcription in background thread
            def run_transcription():
                try:
                    self.transcribe.stream_audio(audio_queue, on_transcript_result)
                except Exception as e:
                    self.logger.error("Transcription thread error: %s", e)
            
            transcription_thread = threading.Thread(target=run_transcription, daemon=True)
            transcription_thread.start()
            
            # Handle WebSocket audio data
            await self._handle_websocket_audio_simple(websocket, audio_queue, session_data)
            
        except Exception as e:
            self.logger.error("Real-time transcription failed: %s", e)
            # Fallback to mock transcription
            await self._start_mock_transcription(session_data, websocket)

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
                    
                    # Send transcript to queue
                    await session_data["queue"].put({
                        "type": "transcript",
                        "action": "append",
                        "payload": {
                            "index": phrase_index + 1,
                            "speaker": "Speaker A" if phrase_index % 2 else "Speaker B",
                            "raw_speaker": "spk_mock_a" if phrase_index % 2 else "spk_mock_b",
                            "result_id": f"mock-{phrase_index + 1}",
                            "text": phrase,
                            "timestamp": now_iso(),
                        }
                    })
                    
                    # Send classification to queue
                    await self._classify_realtime_hybrid(session_data, phrase, "Speaker A" if phrase_index % 2 else "Speaker B", phrase_index + 1)
                    phrase_index += 1
                    
        except WebSocketDisconnect:
            pass

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
        """Get friendly speaker name with poc_satomin-style dynamic mapping."""
        key = self._normalize_raw_label(raw_label)
        
        # Initialize speaker management if not exists (same as poc_satomin)
        if "speaker_labels" not in session_data:
            session_data["speaker_labels"] = {"spk_unk": "判別中..."}
            session_data["next_speaker_index"] = 1
        
        # Handle unknown speakers (same as poc_satomin)
        if key == "spk_unk":
            session_data["speaker_labels"].setdefault("spk_unk", "判別中...")
            return session_data["speaker_labels"]["spk_unk"]
        
        # Handle known speakers (same as poc_satomin)
        if key not in session_data["speaker_labels"]:
            label = f"Speaker {session_data['next_speaker_index']}"
            session_data["speaker_labels"][key] = label
            session_data["next_speaker_index"] += 1
            self.logger.info(f"NEW SPEAKER DETECTED: {key} -> {label}")
        
        return session_data["speaker_labels"][key]

    async def _handle_integrated_result(self, session_data: dict, result_id: str, speaker_label: str, raw_label: str, text: str, is_partial: bool) -> None:
        """Handle transcription result with poc_satomin-style integrated analysis."""
        is_final = not is_partial
        
        # Handle transcription first (use queue instead of websocket)
        await self._handle_result_streaming(session_data, result_id, speaker_label, raw_label, text, is_final)
        
        # poc_satomin-style analysis: only analyze final results
        if is_final:
            # Split long text like poc_satomin
            split_texts = self._split_long_text(text)
            for i, split_text in enumerate(split_texts):
                unique_index = session_data["next_entry_index"] * 1000 + i
                # Run hybrid analysis for each split
                asyncio.create_task(self._classify_realtime_hybrid(
                    session_data, split_text, speaker_label, unique_index
                ))

    async def _handle_result_streaming(self, session_data: dict, result_id: str, speaker_label: str, raw_label: str, text: str, is_final: bool) -> None:
        """Handle transcription result with poc_satomin-style speaker stability."""
        
        entry = session_data["pending_results"].get(result_id)
        
        if not entry:
            # Create new entry (same as poc_satomin)
            entry = {
                "index": session_data["next_entry_index"],
                "speaker": speaker_label,
                "raw_speaker": raw_label,
                "result_id": result_id,
                "text": text,
                "timestamp": now_iso(),
            }
            session_data["next_entry_index"] += 1
            session_data["pending_results"][result_id] = entry
            
            # Send append message to queue
            await session_data["queue"].put({
                "type": "transcript",
                "action": "append",
                "payload": self._public_payload(entry)
            })
        else:
            # poc_satomin-style speaker label stability
            # Only update speaker if unknown -> known (one-time update)
            current_raw = entry.get("raw_speaker", "spk_unk")
            if self._is_unknown_label(current_raw) and not self._is_unknown_label(raw_label):
                entry["raw_speaker"] = raw_label
                stable_alias = self._speaker_name(session_data, raw_label)
                entry["speaker"] = stable_alias
                await session_data["queue"].put({
                    "type": "transcript",
                    "action": "update",
                    "payload": self._public_payload(entry)
                })

            # Check if text and speaker are the same (early return like poc_satomin)
            if entry["text"] == text and entry["speaker"] == speaker_label:
                if is_final:
                    await self._finalize_result_streaming(session_data, result_id)
                return
            
            # Update text
            entry["text"] = text
            await session_data["queue"].put({
                "type": "transcript",
                "action": "update",
                "payload": self._public_payload(entry)
            })
        
        # Handle final result
        if is_final:
            await self._finalize_result_streaming(session_data, result_id)

    async def _finalize_result_streaming(self, session_data: dict, result_id: str) -> None:
        """Finalize a transcription result."""
        if result_id in session_data["pending_results"]:
            entry = session_data["pending_results"].pop(result_id)
            payload = self._public_payload(entry)
            session_data["transcripts"].append(payload)
            
            # Send final update to queue
            await session_data["queue"].put({
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

    async def _classify_realtime_hybrid(self, session_data: dict, text: str, speaker: str, index: int) -> None:
        """poc_satomin-style hybrid real-time classification."""
        # Skip very short texts (same as poc_satomin)
        text_stripped = text.strip()
        if len(text_stripped) < 10:
            self.logger.info(f"Skipping short text: '{text_stripped}' (len={len(text_stripped)})")
            return
            
        # Skip meta information (same as poc_satomin)
        if text.startswith("Agenda topic:") or text.startswith("Discussion: Confirming action items for"):
            self.logger.info(f"Skipping meta info: {text[:50]}...")
            return
        
        # Check for meta keywords in Discussion content
        if text.startswith("Discussion: Confirming action items for"):
            import re
            match = re.search(r"'([^']+)'", text)
            if match:
                content = match.group(1)
                meta_keywords = ["議題タイトル", "所要時間", "発表者", "分", "時間"]
                if len(content) < 10 or any(keyword in content for keyword in meta_keywords):
                    self.logger.info(f"Skipping meta content: {text[:50]}...")
                    return
        
        self.logger.info(f"Starting hybrid analysis: {speaker} - {text[:30]}...")
        
        # Step 1: Immediate keyword-based classification (same as poc_satomin)
        from backend.services.bedrock_utils import _guess_category
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

        # Send immediate result to queue
        await session_data["queue"].put({"type": "realtime_classification", "payload": result_quick})
        
        # Step 2: Background Bedrock analysis (same as poc_satomin)
        try:
            task = asyncio.create_task(self._classify_with_bedrock_session(session_data, text, speaker, index))
            session_data["pending_bedrock_tasks"].add(task)
            task.add_done_callback(lambda t: session_data["pending_bedrock_tasks"].discard(t))
        except Exception as e:
            self.logger.warning(f"Failed to create Bedrock task: {e}")

    async def _classify_with_bedrock_session(self, session_data: dict, text: str, speaker: str, index: int) -> None:
        """poc_satomin-style Bedrock analysis in background."""
        self.logger.info(f"Bedrock analysis started: {speaker} - {text[:30]}...")
        try:
            # Get context from transcripts (same as poc_satomin)
            context_before = ""
            context_after = ""
            for transcript in session_data["transcripts"]:
                if transcript.get("index") == index - 1:
                    context_before = transcript.get("text", "")
                elif transcript.get("index") == index + 1:
                    context_after = transcript.get("text", "")
            
            # Bedrock analysis (same structure as poc_satomin)
            segment = {
                "index": index,
                "speaker": speaker,
                "text": text,
                "context_before": context_before,
                "context_after": context_after,
            }
            
            self.logger.info(f"Sending to Bedrock... segment={segment}")
            self.logger.info(f"agenda_text={session_data['agenda_text'][:100]}...")
            
            classified = await asyncio.to_thread(
                classify_transcript_segments,
                [segment],
                session_data["agenda_text"]
            )
            
            self.logger.info(f"Bedrock response received: {classified}")
            
            if classified and len(classified) > 0:
                result = classified[0]
                from backend.services.bedrock_utils import _guess_category
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
                
                # Send update to queue (same as poc_satomin)
                await session_data["queue"].put({"type": "realtime_classification", "action": "update", "payload": result_ai})
                
                self.logger.info(f"Bedrock analysis completed: {speaker} - {text[:30]}... → [{category_ai}] {alignment_ai}%")
            else:
                # Fallback to keyword-based result (same as poc_satomin)
                self.logger.warning("No Bedrock result, using keyword fallback")
                from backend.services.bedrock_utils import _guess_category
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
                
                await session_data["queue"].put({"type": "realtime_classification", "action": "update", "payload": result_fallback})
                self.logger.info(f"Keyword analysis finalized: {speaker} - {text[:30]}... → [{category_fallback}] {alignment_fallback}%")
        
        except Exception as e:
            self.logger.error(f"Bedrock analysis failed: {e}")
            self.logger.exception("Detailed error:")

    def _fast_guess_category(self, text: str) -> str:
        """Ultra-fast category guessing with minimal processing."""
        text_lower = text.lower()
        
        # Simple keyword matching
        if any(word in text_lower for word in ["提案", "案", "アイデア", "考え"]):
            return "提案"
        elif any(word in text_lower for word in ["質問", "？", "?"]):
            return "質問"
        elif any(word in text_lower for word in ["反対", "問題", "課題", "懸念"]):
            return "反対"
        elif any(word in text_lower for word in ["賛成", "同意", "いいね", "良い"]):
            return "賛成"
        else:
            return "コメント"
    
    async def _send_analysis_update(self, websocket: WebSocket, session_data: dict, is_partial: bool) -> None:
        """Send analysis update for current utterance."""
        if not session_data.get('current_analysis_entry'):
            return
        
        entry = session_data['current_analysis_entry']
        text = entry['text']
        speaker = entry['speaker']
        index = entry['index']
        
        # Skip meta information
        if text.startswith("Agenda topic:") or text.startswith("Discussion: Confirming action items for"):
            return
        
        # Fast analysis
        category = self._fast_guess_category(text)
        alignment = self._fast_calculate_alignment(text, session_data["agenda_text"])
        
        result = {
            "index": index,
            "text": text,
            "speaker": speaker,
            "category": category,
            "alignment": alignment,
            "method": "keyword",
            "is_final": not is_partial,
            "is_partial": is_partial,
            "ai_status": entry['ai_status'],
            "result_id": f"utterance_{index}"
        }

        try:
            await websocket.send_json({
                "type": "realtime_classification",
                "payload": result
            })
        except Exception as e:
            self.logger.error(f"Failed to send analysis update: {e}")

    async def _finalize_analysis_with_bedrock(self, session_data: dict, websocket: WebSocket) -> None:
        """Finalize current analysis with Bedrock and mark as AI確定."""
        if not session_data.get('current_analysis_entry'):
            return
        
        entry = session_data['current_analysis_entry']
        text = entry['text']
        speaker = entry['speaker']
        index = entry['index']
        
        try:
            # Bedrock analysis
            segment = {
                "index": index,
                "speaker": speaker,
                "text": text,
                "context_before": "",
                "context_after": "",
            }
            
            classified = await asyncio.to_thread(
                classify_transcript_segments,
                [segment],
                session_data["agenda_text"]
            )
            
            if classified and len(classified) > 0:
                result = classified[0]
                category_ai = result.get("category", self._fast_guess_category(text))
                alignment_ai = result.get("alignment", 0)
            else:
                category_ai = self._fast_guess_category(text)
                alignment_ai = self._fast_calculate_alignment(text, session_data["agenda_text"])
            
            # Send final AI確定 result
            final_result = {
                "index": index,
                "text": text,
                "speaker": speaker,
                "category": category_ai,
                "alignment": alignment_ai,
                "method": "bedrock",
                "is_final": True,
                "is_partial": False,
                "ai_status": "AI確定",
                "result_id": f"utterance_{index}"
            }
            
            await websocket.send_json({
                "type": "realtime_classification",
                "payload": final_result
            })
            
            self.logger.info(f"Analysis finalized: {speaker} - {text[:30]}... → [{category_ai}] {alignment_ai}% (AI確定)")
            
        except Exception as e:
            self.logger.error(f"Bedrock finalization failed: {e}")

    async def _send_integrated_analysis(self, websocket: WebSocket, meeting_id: str, text: str, speaker: str, index: int, is_partial: bool, ai_status: str) -> None:
        """Send integrated analysis with consistent indexing."""
        session_data = self.session_data.get(meeting_id)
        if not session_data:
            return
        
        # Skip meta information
        if text.startswith("Agenda topic:") or text.startswith("Discussion: Confirming action items for"):
            return
        
        # Ultra-fast analysis
        category = self._fast_guess_category(text)
        alignment = self._fast_calculate_alignment(text, session_data["agenda_text"])
        
        result = {
            "index": index,
            "text": text,
            "speaker": speaker,
            "category": category,
            "alignment": alignment,
            "method": "keyword",
            "is_final": not is_partial,
            "is_partial": is_partial,
            "ai_status": ai_status,
            "result_id": f"analysis_{index}"  # Consistent result_id for frontend
        }

        try:
            await websocket.send_json({
                "type": "realtime_classification",
                "payload": result
            })
        except Exception as e:
            self.logger.error(f"Failed to send integrated analysis: {e}")

    async def _send_immediate_analysis(self, websocket: WebSocket, meeting_id: str, text: str, speaker: str, index: int, is_partial: bool) -> None:
        """Send immediate keyword-based analysis."""
        session_data = self.session_data.get(meeting_id)
        if not session_data:
            return
        
        # Skip meta information
        if text.startswith("Agenda topic:") or text.startswith("Discussion: Confirming action items for"):
            return
        
        # Ultra-fast analysis
        category = self._fast_guess_category(text)
        alignment = self._fast_calculate_alignment(text, session_data["agenda_text"])
        
        result = {
            "index": index,
            "text": text,
            "speaker": speaker,
            "category": category,
            "alignment": alignment,
            "method": "keyword",
            "is_final": not is_partial,
            "is_partial": is_partial,
            "ai_status": "AI暫定" if not is_partial else "部分"
        }

        try:
            await websocket.send_json({
                "type": "realtime_classification",
                "payload": result
            })
        except Exception as e:
            self.logger.error(f"Failed to send immediate analysis: {e}")

    def _is_sentence_complete(self, text: str) -> bool:
        """Check if sentence is complete (ends with punctuation)."""
        text = text.strip()
        if len(text) < 5:
            return False
        
        # Japanese sentence endings
        sentence_endings = ["。", "！", "？", ".", "!", "?"]
        return any(text.endswith(ending) for ending in sentence_endings)

    async def _classify_with_bedrock_integrated(self, session_data: dict, text: str, speaker: str, index: int, websocket: WebSocket, reason: str) -> None:
        """Bedrock analysis with integrated status management."""
        try:
            self.logger.info(f"Bedrock分析開始 ({reason}): {speaker} - {text[:30]}...")
            
            # Get context
            context_before = ""
            context_after = ""
            for transcript in session_data["transcripts"][-5:]:  # Last 5 for context
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
                category_ai = result.get("category", self._fast_guess_category(text))
                alignment_ai = result.get("alignment", 0)
                
                # Determine AI status based on reason
                ai_status = "AI確定" if reason == "speaker_change" else "AI暫定"
                
                result_ai = {
                    "index": index,
                    "text": text,
                    "speaker": speaker,
                    "category": category_ai,
                    "alignment": alignment_ai,
                    "method": "bedrock",
                    "is_final": reason == "speaker_change",
                    "is_partial": False,
                    "ai_status": "AI確定",  # Bedrock analysis always results in AI確定
                    "result_id": f"analysis_{index}"  # Consistent result_id
                }
                
                # Send AI result
                await websocket.send_json({
                    "type": "realtime_classification",
                    "action": "update",
                    "payload": result_ai
                })
                
                self.logger.info(f"Bedrock分析完了 ({reason}): {speaker} - {text[:30]}... → [{category_ai}] {alignment_ai}% ({ai_status})")
            
        except Exception as e:
            self.logger.error(f"Bedrock分析失敗 ({reason}): {e}")

    def _fast_calculate_alignment(self, text: str, agenda_text: str) -> int:
        """Ultra-fast alignment calculation."""
        if not agenda_text or len(text) < 5:
            return 50
        
        # Simple word matching
        agenda_words = set(agenda_text.lower().split())
        text_words = set(text.lower().split())
        
        if not agenda_words:
            return 50
        
        # Calculate simple overlap
        overlap = len(agenda_words & text_words)
        total = len(agenda_words)
        
        if overlap == 0:
            return 30
        
        alignment = min(100, int(30 + (overlap / total) * 70))
        return alignment

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

    async def _process_queue_messages(self, session_data: dict, websocket: WebSocket) -> None:
        """Process queue messages like poc_satomin WebSocket handler."""
        try:
            while True:
                message = await session_data["queue"].get()
                await websocket.send_json(message)
                if message.get("type") == "complete":
                    break
        except Exception as e:
            self.logger.error(f"Queue processing error: {e}")

    def _split_long_text(self, text: str, max_length: int = 80, min_length: int = 25) -> list[str]:
        """Split long text like poc_satomin."""
        if len(text) <= max_length:
            return [text]
        
        import re
        
        # Split by punctuation (include punctuation)
        parts = re.split(r'(。|！|？)', text)
        
        # Combine punctuation with previous sentence
        sentences = []
        for i in range(0, len(parts), 2):
            sentence = parts[i]
            if i + 1 < len(parts):
                sentence += parts[i + 1]  # Add punctuation
            if sentence.strip():
                sentences.append(sentence.strip())
        
        # Further split long sentences by commas
        result = []
        for sentence in sentences:
            if len(sentence) <= max_length:
                result.append(sentence)
            else:
                # Split by commas
                sub_parts = re.split(r'(、|,)', sentence)
                buffer = ""
                for i in range(0, len(sub_parts)):
                    part = sub_parts[i]
                    if len(buffer + part) <= max_length:
                        buffer += part
                    else:
                        if buffer.strip():
                            result.append(buffer.strip())
                        buffer = part
                if buffer.strip():
                    result.append(buffer.strip())
        
        # Merge short sentences with previous ones
        final_result = []
        for sentence in result:
            if final_result and len(sentence) < min_length:
                final_result[-1] += sentence
            else:
                final_result.append(sentence)
        
        return [s for s in final_result if s]


