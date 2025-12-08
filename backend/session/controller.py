from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from backend.services.vonage_client import VonageClient
from backend.services.transcribe_stream import TranscribeStream
from backend.services.comprehend_utils import analyze_sentiment
from backend.services.repository import MeetingRepository
from backend.utils.time_utils import now_iso


class SessionController:
    def __init__(self, repository: MeetingRepository | None = None):
        self.vonage = VonageClient()
        self.transcribe = TranscribeStream()
        self.repository = repository or MeetingRepository()

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
        session = self.vonage.create_session(meeting.meeting_id)
        session_id = session["session_id"]
        meeting = self.repository.update_meeting(
            meeting.meeting_id, session_id=session_id, status="live"
        )

        token = self.vonage.generate_token(session_id=session_id)
        return self._build_session_payload(meeting, session_id, token)

    def create_session_token(self, meeting_id: str) -> dict:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            raise ValueError("Meeting not found")

        session_id = meeting.session_id
        if not session_id:
            session = self.vonage.create_session(meeting_id)
            session_id = session["session_id"]
            meeting = self.repository.update_meeting(meeting_id, session_id=session_id, status="live")

        token = self.vonage.generate_token(session_id=session_id)
        return self._build_session_payload(meeting, session_id, token)

    async def stream_transcripts(self, websocket: WebSocket, meeting_id: str) -> None:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            await websocket.close(code=4404)
            return

        await websocket.accept()
        await self.transcribe.start()
        try:
            for idx in range(10):
                text = f"Sample utterance {idx} for {meeting_id}"
                sentiment = analyze_sentiment(text)
                payload = {
                    "meeting_id": meeting_id,
                    "timestamp": now_iso(),
                    "transcript": text,
                    "sentiment": sentiment.get("Sentiment", "NEUTRAL"),
                }
                await websocket.send_json(payload)
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return
        finally:
            if websocket.application_state == WebSocketState.CONNECTED:
                with suppress(RuntimeError):
                    await websocket.close(code=1000)
