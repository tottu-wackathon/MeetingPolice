from __future__ import annotations

import time
from typing import Any

from opentok import OpenTok

from backend.config import get_settings


class VonageClient:
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.vonage_api_key
        self.api_secret = self.settings.vonage_api_secret
        self.client = (
            OpenTok(self.api_key, self.api_secret) if self.api_key and self.api_secret else None
        )

    def create_session(self, meeting_id: str) -> dict[str, Any]:
        if not self.client:
            return {"session_id": f"session-{meeting_id}"}
        session = self.client.create_session(media_mode="routed")
        return {"session_id": session.session_id}

    def generate_token(self, session_id: str, ttl_seconds: int = 300) -> str:
        if not self.client:
            return f"mock-token-{session_id}"
        expire_time = int(time.time()) + ttl_seconds
        return self.client.generate_token(session_id, expire_time=expire_time)
