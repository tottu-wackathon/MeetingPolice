from __future__ import annotations

import asyncio
from contextlib import suppress
import queue
import threading
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from amazon_transcribe.auth import StaticCredentialResolver
from amazon_transcribe.client import TranscribeStreamingClient



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
        """Start real-time transcription using amazon-transcribe streaming like poc_satomin."""
        meeting_id = session_data["meeting_id"]
        
        try:
            # Get AWS credentials
            session = get_session()
            credentials = session.get_credentials()
            if not credentials:
                raise RuntimeError("Unable to resolve AWS credentials for Transcribe streaming")
            
            frozen = credentials.get_frozen_credentials()
            credential_resolver = StaticCredentialResolver(
                frozen.access_key,
                frozen.secret_key,
                frozen.token,
            )
            
            client = TranscribeStreamingClient(
                region=self.settings.aws_region,
                credential_resolver=credential_resolver,
            )
            
            self.logger.info("Starting Transcribe stream for meeting_id=%s", meeting_id)
            
            stream = await client.start_stream_transcription(
                language_code="ja-JP",
                media_encoding="pcm",
                media_sample_rate_hz=16000,
                show_speaker_label=True,
                enable_partial_results_stabilization=True,
                partial_results_stability="medium",
            )
            
            # Start audio processing and result handling concurrently
            await asyncio.gather(
                self._handle_websocket_audio_streaming(websocket, stream, session_data),
                self._handle_transcribe_results_streaming(stream, session_data, websocket),
            )
            
        except Exception as e:
            self.logger.error("Real-time transcription failed: %s", e)
            # Fallback to mock transcription
            await self._start_mock_transcription(session_data, websocket)

    async def _handle_websocket_audio_streaming(self, websocket: WebSocket, stream, session_data: dict) -> None:
        """Handle audio data from WebSocket and send to Transcribe stream."""
        audio_count = 0
        
        try:
            while True:
                message = await websocket.receive()
                
                if message.get("type") == "websocket.disconnect":
                    break
                
                data = message.get("bytes")
                if data and len(data) > 0:
                    await stream.input_stream.send_audio_event(audio_chunk=data)
                    audio_count += 1
                    
                    if audio_count % 100 == 0:
                        self.logger.debug(f"Sent {audio_count} audio chunks to Transcribe")
                        
                elif message.get("text"):
                    if message["text"] == "close":
                        break
                        
        except WebSocketDisconnect:
            self.logger.info("WebSocket disconnected during audio handling")
        except Exception as e:
            self.logger.error(f"Error handling WebSocket audio: {e}")
        finally:
            try:
                await stream.input_stream.end_stream()
                self.logger.info(f"Audio stream ended, processed {audio_count} chunks")
            except Exception as e:
                self.logger.error(f"Error ending audio stream: {e}")

    async def _handle_transcribe_results_streaming(self, stream, session_data: dict, websocket: WebSocket) -> None:
        """Handle transcription results from AWS Transcribe with poc_satomin-like logic."""
        try:
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
                    await self._handle_result_streaming(session_data, result_id, speaker_label, raw_label, text, not is_partial, websocket)
                    
                    if not is_partial:
                        session_data["processed_result_ids"].add(result_id)
                        
        except Exception as e:
            self.logger.error("Error handling transcribe results: %s", e)



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
        """Handle a single transcription result with poc_satomin-like logic."""
        entry = session_data["pending_results"].get(result_id)
        
        if not entry:
            # New entry - append
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
            
            # Send append message
            await websocket.send_json({
                "type": "transcript",
                "action": "append",
                "payload": self._public_payload(entry)
            })
        else:
            # Update existing entry
            # Update speaker if we got better information
            current_raw = entry.get("raw_speaker", "spk_unk")
            if self._is_unknown_label(current_raw) and not self._is_unknown_label(raw_label):
                entry["raw_speaker"] = raw_label
                entry["speaker"] = self._speaker_name(session_data, raw_label)
                
                # Send update for speaker change
                await websocket.send_json({
                    "type": "transcript", 
                    "action": "update",
                    "payload": self._public_payload(entry)
                })
            
            # Check if text changed
            if entry["text"] != text:
                entry["text"] = text
                
                # Send update for text change
                await websocket.send_json({
                    "type": "transcript",
                    "action": "update", 
                    "payload": self._public_payload(entry)
                })
        
        # Handle final result
        if is_final:
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


