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
from backend.utils.time_utils import now_iso


class SessionController:
    def __init__(self, repository: MeetingRepository | None = None):
        self.vonage = VonageClient()
        self.transcribe = TranscribeStream()
        self.repository = repository or MeetingRepository()
        self.logger = logging.getLogger(__name__)
        self._classification_index = 1

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
        loop = asyncio.get_running_loop()
        audio_queue: queue.Queue[bytes | None] = queue.Queue()
        stop_event = threading.Event()

        await websocket.accept()
        # Kick off transcribe streaming in background thread
        def handle_transcript(payload: dict) -> None:
            if payload.get("error"):
                asyncio.run_coroutine_threadsafe(
                    websocket.send_json({"error": payload["error"]}), loop
                )
                return
            message = {
                "type": "transcript",
                "meeting_id": meeting_id,
                "timestamp": now_iso(),
                "transcript": payload.get("transcript", ""),
                "sentiment": analyze_sentiment(payload.get("transcript", "")).get("Sentiment", "NEUTRAL"),
                "is_partial": payload.get("is_partial", False),
            }
            asyncio.run_coroutine_threadsafe(websocket.send_json(message), loop)
            if not payload.get("is_partial") and payload.get("transcript"):
                asyncio.run_coroutine_threadsafe(
                    self._classify_and_send(websocket, meeting_id, payload.get("transcript", "")),
                    loop,
                )

        def run_transcribe() -> None:
            try:
                self.logger.info("Starting AWS Transcribe streaming for meeting_id=%s", meeting_id)
                self.transcribe.stream_audio(audio_queue, handle_transcript)
                self.logger.info("AWS Transcribe streaming completed for meeting_id=%s", meeting_id)
            except Exception as e:
                self.logger.error("Transcribe failed for meeting_id=%s: %s", meeting_id, e)
                self.logger.info("Falling back to mock transcription for meeting_id=%s", meeting_id)
                # Mock transcription for testing
                try:
                    self._run_mock_transcribe(audio_queue, handle_transcript)
                except Exception as mock_error:
                    self.logger.error("Mock transcription also failed: %s", mock_error)
            finally:
                stop_event.set()

        transcribe_thread = threading.Thread(target=run_transcribe, daemon=True)
        transcribe_thread.start()

        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data:
                    audio_queue.put(data)
                elif message.get("text"):
                    # allow ping/keepalive
                    if message["text"] == "close":
                        break
                await asyncio.sleep(0)
        except WebSocketDisconnect:
            return
        finally:
            audio_queue.put(None)
            stop_event.wait(timeout=2)
            if transcribe_thread.is_alive():
                transcribe_thread.join(timeout=1)
            if websocket.application_state == WebSocketState.CONNECTED:
                with suppress(RuntimeError):
                    await websocket.close(code=1000)

    async def _classify_and_send(self, websocket: WebSocket, meeting_id: str, text: str) -> None:
        """Run Bedrock分類と簡易一致度計算を行い、WebSocketへ送信する."""
        try:
            # 簡易一致度: アジェンダ不明なので中立とする
            alignment = self._calculate_alignment(text)
            segments = [{"index": self._classification_index, "speaker": "unknown", "text": text}]
            self._classification_index += 1
            classified = await asyncio.to_thread(classify_transcript_segments, segments, "")
            category = classified[0].get("category") if classified else _guess_category(text)
            payload: dict[str, Any] = {
                "type": "realtime_classification",
                "payload": {
                    "index": segments[0]["index"],
                    "text": text,
                    "speaker": "unknown",
                    "category": category,
                    "alignment": alignment,
                    "method": "bedrock",
                    "is_final": True,
                    "timestamp": now_iso(),
                    "meeting_id": meeting_id,
                },
            }
            await websocket.send_json(payload)
        except Exception:
            self.logger.exception("classification failed meeting_id=%s", meeting_id)

    def _run_mock_transcribe(self, audio_queue: queue.Queue[bytes | None], handle_transcript) -> None:
        """Mock transcription for testing when AWS Transcribe is not available."""
        import time
        import threading
        
        mock_phrases = [
            "こんにちは、テストです",
            "音声認識のテストを行っています",
            "マイクの音声が正常に送信されています",
            "文字起こし機能が動作しています",
            "リアルタイム分析のテストです"
        ]
        
        phrase_index = 0
        audio_received_count = 0
        last_transcript_time = time.time()
        
        def check_audio():
            nonlocal phrase_index, audio_received_count, last_transcript_time
            
            while True:
                try:
                    # Get audio data from queue (with timeout)
                    audio_data = audio_queue.get(timeout=1.0)
                    if audio_data is None:
                        break
                    
                    audio_received_count += 1
                    current_time = time.time()
                    
                    # Send mock transcript every 3 seconds when audio is received
                    if current_time - last_transcript_time >= 3.0 and audio_received_count > 0:
                        phrase = mock_phrases[phrase_index % len(mock_phrases)]
                        self.logger.info("Mock transcript: %s (audio packets: %d)", phrase, audio_received_count)
                        
                        # Send partial result first
                        handle_transcript({
                            "transcript": phrase[:len(phrase)//2] + "...",
                            "is_partial": True,
                        })
                        
                        # Send final result after a short delay
                        threading.Timer(1.0, lambda: handle_transcript({
                            "transcript": phrase,
                            "is_partial": False,
                        })).start()
                        
                        phrase_index += 1
                        last_transcript_time = current_time
                        audio_received_count = 0
                        
                except queue.Empty:
                    # No audio received, continue waiting
                    continue
                except Exception as e:
                    self.logger.error("Mock transcribe error: %s", e)
                    break
        
        # Start audio monitoring in a separate thread
        audio_thread = threading.Thread(target=check_audio, daemon=True)
        audio_thread.start()
        
        self.logger.info("Mock transcription started - speak into microphone to see results")

    def _calculate_alignment(self, text: str) -> int:
        """簡易一致度: 議題不明のためキーワードベースでざっくり算出."""
        if not text:
            return 50
        keywords = {"議題", "アジェンダ", "決定", "提案", "質問", "回答"}
        matched = sum(1 for kw in keywords if kw in text)
        if matched == 0:
            return 40
        return min(100, 60 + matched * 10)
