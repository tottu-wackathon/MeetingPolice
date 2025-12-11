from __future__ import annotations

import time
import jwt
import json
from pathlib import Path
from typing import Any
import logging
import requests

from backend.config import get_settings


class VonageClient:
    def __init__(self):
        self.settings = get_settings()
        self.application_id = self.settings.vonage_application_id
        self.api_key = self.settings.vonage_api_key
        self.private_key_path = self.settings.vonage_private_key_path
        self.logger = logging.getLogger(__name__)
        
        # Load private key
        self.private_key_content = None
        if self._load_private_key():
            self.logger.info("Vonage Video API client initialized successfully")
        else:
            self.logger.warning("Vonage client not available - missing private key")

    def _load_private_key(self) -> bool:
        """Load private key from file."""
        try:
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

    def _generate_jwt_token(self) -> str:
        """Generate JWT token for Vonage API authentication."""
        if not self.application_id or not self.private_key_content:
            raise ValueError("Missing application_id or private_key for JWT generation")
        
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 3600,  # 1 hour expiration
            "jti": f"{self.application_id}-{now}",
            "application_id": self.application_id
        }
        
        return jwt.encode(payload, self.private_key_content, algorithm="RS256")

    def create_session(self, meeting_id: str) -> dict[str, Any]:
        if not self.private_key_content or not self.application_id:
            session_id = f"session-{meeting_id}"
            self.logger.info("Vonage Video client disabled; returning mock session_id=%s", session_id)
            return {"session_id": session_id}
        
        try:
            # Generate JWT token
            jwt_token = self._generate_jwt_token()
            
            # Create session using Vonage Video API v2
            url = "https://video.api.vonage.com/v2/project/{}/session".format(self.application_id)
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json"
            }
            
            session_data = {
                "media_mode": "routed",
                "archive_mode": "manual"
            }
            
            response = requests.post(url, headers=headers, json=session_data)
            response.raise_for_status()
            
            result = response.json()
            session_id = result.get("session_id")
            
            self.logger.info("Vonage session created session_id=%s meeting_id=%s", session_id, meeting_id)
            return {"session_id": session_id}
        except Exception as exc:
            self.logger.exception("Vonage session creation failed meeting_id=%s", meeting_id)
            raise

    def generate_token(self, session_id: str, ttl_seconds: int = 300) -> str:
        if not self.private_key_content or not self.application_id:
            token = f"mock-token-{session_id}"
            self.logger.info("Vonage Video client disabled; returning mock token for session_id=%s", session_id)
            return token
        
        try:
            # Generate JWT token
            jwt_token = self._generate_jwt_token()
            
            # Generate session token using Vonage Video API v2
            url = f"https://video.api.vonage.com/v2/project/{self.application_id}/session/{session_id}/token"
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json"
            }
            
            expire_time = int(time.time()) + ttl_seconds
            token_data = {
                "role": "publisher",
                "expire_time": expire_time,
                "data": f"meeting_session_{session_id}"
            }
            
            response = requests.post(url, headers=headers, json=token_data)
            response.raise_for_status()
            
            result = response.json()
            token = result.get("token")
            
            self.logger.info("Vonage token generated session_id=%s", session_id)
            return token
        except Exception as exc:
            self.logger.exception("Vonage token generation failed session_id=%s", session_id)
            raise
