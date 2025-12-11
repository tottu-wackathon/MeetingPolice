from __future__ import annotations

import time
from typing import Any
import logging

from opentok import OpenTok, MediaModes

from backend.config import get_settings


class VonageClient:
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.vonage_api_key
        self.api_secret = self.settings.vonage_api_secret
        self.logger = logging.getLogger(__name__)
        self.client = (
            OpenTok(self.api_key, self.api_secret) if self.api_key and self.api_secret else None
        )

    def create_session(self, meeting_id: str) -> dict[str, Any]:
        if not self.client:
            session_id = f"session-{meeting_id}"
            self.logger.info("Vonage backend client disabled; returning mock session_id=%s", session_id)
            return {"session_id": session_id}
        try:
            session = self.client.create_session(media_mode=MediaModes.routed)
            self.logger.info("Vonage session created session_id=%s meeting_id=%s", session.session_id, meeting_id)
            return {"session_id": session.session_id}
        except Exception as exc:
            self.logger.exception("Vonage session creation failed meeting_id=%s", meeting_id)
            raise

    def generate_token(self, session_id: str, ttl_seconds: int = 300) -> str:
        if not self.client:
            token = f"mock-token-{session_id}"
            self.logger.info("Vonage backend client disabled; returning mock token for session_id=%s", session_id)
            return token
        expire_time = int(time.time()) + ttl_seconds
        try:
            token = self.client.generate_token(session_id, expire_time=expire_time)
            self.logger.info("Vonage token generated session_id=%s", session_id)
            return token
        except Exception:
            self.logger.exception("Vonage token generation failed session_id=%s", session_id)
            raise
