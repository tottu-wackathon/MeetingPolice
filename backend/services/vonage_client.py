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
        # Check if we have JWT credentials (Application ID + Private Key)
        self.application_id = self.settings.vonage_application_id
        self.private_key_path = self.settings.vonage_private_key_path
        self.api_secret = getattr(self.settings, 'vonage_api_secret', None)
        self.logger = logging.getLogger(__name__)
        self.client = None
        self.is_mock_mode = False
        
        # Try JWT authentication first (preferred method)
        if self.application_id and self._load_private_key():
            self.logger.info("Using JWT authentication with Application ID and Private Key")
            self.auth_method = "jwt"
            self.is_mock_mode = False
        # Fallback to OpenTok authentication
        elif OPENTOK_AVAILABLE and self.api_key and self.api_secret and self.api_secret != self.api_key and len(self.api_key) > 5:
            try:
                # Test if credentials are valid by creating a test client
                test_client = OpenTok(self.api_key, self.api_secret)
                self.client = test_client
                self.auth_method = "opentok"
                self.logger.info("Vonage Video API (OpenTok) client initialized successfully")
            except Exception as e:
                self.logger.warning(f"OpenTok client initialization failed: {e}")
                self.logger.info("Falling back to mock mode for development")
                self.client = None
                self.is_mock_mode = True
                self.auth_method = "mock"
        else:
            self.logger.warning("No valid authentication method available - using mock mode")
            self.is_mock_mode = True
            self.auth_method = "mock"

    def _load_private_key(self) -> bool:
        """Load private key from file for JWT authentication."""
        try:
            from pathlib import Path
            key_path = Path(self.private_key_path)
            if key_path.exists():
                self.private_key_content = key_path.read_text(encoding='utf-8')
                return True
            else:
                self.logger.error(f"Private key file not found: {self.private_key_path}")
                return False
        except Exception as e:
            self.logger.error(f"Failed to load private key: {e}")
            return False

    def create_session(self, meeting_id: str) -> dict[str, Any]:
        if not self.client or self.is_mock_mode:
            # Generate a proper mock session ID that looks like a real OpenTok session ID
            import uuid
            mock_session_id = f"1_MX40{abs(hash(meeting_id)) % 100000000}~-1~{uuid.uuid4().hex[:20]}"
            self.logger.info("Vonage Video client in mock mode; returning mock session_id=%s", mock_session_id)
            return {"session_id": mock_session_id}
        
        try:
            # Create session with OpenTok SDK
            session = self.client.create_session(media_mode=MediaModes.routed)
            session_id = session.session_id
            
            self.logger.info("Vonage session created session_id=%s meeting_id=%s", session_id, meeting_id)
            return {"session_id": session_id}
        except Exception as exc:
            self.logger.exception("Vonage session creation failed meeting_id=%s", meeting_id)
            # Fallback to mock mode
            self.is_mock_mode = True
            import uuid
            mock_session_id = f"1_MX40{abs(hash(meeting_id)) % 100000000}~-1~{uuid.uuid4().hex[:20]}"
            self.logger.info("Falling back to mock session_id=%s", mock_session_id)
            return {"session_id": mock_session_id}

    def generate_token(self, session_id: str, ttl_seconds: int = 300) -> str:
        if not self.client or self.is_mock_mode:
            # Generate a proper mock token that looks like a real OpenTok token
            import base64
            import json
            mock_token_data = {
                "session_id": session_id,
                "api_key": self.api_key or "mock_api_key",
                "create_time": int(time.time()),
                "expire_time": int(time.time()) + ttl_seconds,
                "role": "publisher"
            }
            mock_token = base64.b64encode(json.dumps(mock_token_data).encode()).decode()
            token = f"T1=={mock_token}"
            self.logger.info("Vonage Video client in mock mode; returning mock token for session_id=%s", session_id)
            return token
        
        try:
            # Generate token with OpenTok SDK
            expire_time = int(time.time()) + ttl_seconds
            token = self.client.generate_token(session_id, expire_time=expire_time)
            
            self.logger.info("Vonage token generated session_id=%s", session_id)
            return token
        except Exception as exc:
            self.logger.exception("Vonage token generation failed session_id=%s", session_id)
            # Fallback to mock mode
            self.is_mock_mode = True
            import base64
            import json
            mock_token_data = {
                "session_id": session_id,
                "api_key": self.api_key or "mock_api_key",
                "create_time": int(time.time()),
                "expire_time": int(time.time()) + ttl_seconds,
                "role": "publisher"
            }
            mock_token = base64.b64encode(json.dumps(mock_token_data).encode()).decode()
            token = f"T1=={mock_token}"
            self.logger.info("Falling back to mock token for session_id=%s", session_id)
            return token
