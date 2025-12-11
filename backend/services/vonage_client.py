from __future__ import annotations

import time
from typing import Any
import logging

try:
    from opentok import OpenTok, MediaModes
    OPENTOK_AVAILABLE = True
except ImportError:
    OPENTOK_AVAILABLE = False
    OpenTok = None
    MediaModes = None

from backend.config import get_settings


class VonageClient:
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.vonage_api_key
        # For OpenTok compatibility, we'll use API key as both key and secret
        # This is a temporary solution until proper API secret is available
        self.api_secret = self.api_key  # Use API key as secret for now
        self.logger = logging.getLogger(__name__)
        
        if OPENTOK_AVAILABLE and self.api_key:
            try:
                self.client = OpenTok(self.api_key, self.api_secret)
                self.logger.info("Vonage Video API (OpenTok) client initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize OpenTok client: {e}")
                self.client = None
        else:
            self.client = None
            self.logger.warning("OpenTok SDK not available or missing API key")

    def create_session(self, meeting_id: str) -> dict[str, Any]:
        if not self.client:
            session_id = f"session-{meeting_id}"
            self.logger.info("Vonage Video client disabled; returning mock session_id=%s", session_id)
            return {"session_id": session_id}
        
        try:
            # Create session with OpenTok SDK
            session = self.client.create_session(media_mode=MediaModes.routed)
            session_id = session.session_id
            
            self.logger.info("Vonage session created session_id=%s meeting_id=%s", session_id, meeting_id)
            return {"session_id": session_id}
        except Exception as exc:
            self.logger.exception("Vonage session creation failed meeting_id=%s", meeting_id)
            # Return mock session for development
            session_id = f"session-{meeting_id}"
            self.logger.info("Returning mock session_id=%s", session_id)
            return {"session_id": session_id}

    def generate_token(self, session_id: str, ttl_seconds: int = 300) -> str:
        if not self.client:
            token = f"mock-token-{session_id}"
            self.logger.info("Vonage Video client disabled; returning mock token for session_id=%s", session_id)
            return token
        
        try:
            # Generate token with OpenTok SDK
            expire_time = int(time.time()) + ttl_seconds
            token = self.client.generate_token(session_id, expire_time=expire_time)
            
            self.logger.info("Vonage token generated session_id=%s", session_id)
            return token
        except Exception as exc:
            self.logger.exception("Vonage token generation failed session_id=%s", session_id)
            # Return mock token for development
            token = f"mock-token-{session_id}"
            self.logger.info("Returning mock token for session_id=%s", session_id)
            return token
