from __future__ import annotations

import time
from typing import Any
import logging
from pathlib import Path

try:
    from vonage import Vonage, Auth
    from vonage_video.models import TokenOptions
    VONAGE_AVAILABLE = True
except ImportError:
    VONAGE_AVAILABLE = False
    Vonage = None
    Auth = None
    TokenOptions = None

from backend.config import get_settings


class VonageClient:
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.vonage_api_key
        self.application_id = self.settings.vonage_application_id
        self.private_key_path = self.settings.vonage_private_key_path
        self.logger = logging.getLogger(__name__)
        self.client = None
        self.video_client = None
        self.is_mock_mode = False
        
        self.logger.info("🚀 VonageClient initializing...")
        self.logger.info("📋 Config: api_key=%s, app_id=%s, key_path=%s", 
                         "***" if self.api_key else "None",
                         "***" if self.application_id else "None", 
                         self.private_key_path)
        
        # Initialize Vonage Video API with JWT authentication
        self.logger.info("🔍 Checking initialization requirements...")
        self.logger.info("VONAGE_AVAILABLE=%s, has_app_id=%s, has_api_key=%s, private_key_loaded=%s", 
                         VONAGE_AVAILABLE, bool(self.application_id), bool(self.api_key), self._load_private_key())
        
        if VONAGE_AVAILABLE and self.application_id and self.api_key and self._load_private_key():
            try:
                self.logger.info("🔧 Creating Vonage Auth object...")
                # Initialize Vonage client with JWT authentication
                auth = Auth(
                    application_id=self.application_id,
                    private_key=self.private_key_content
                )
                self.logger.info("🔧 Creating Vonage client...")
                self.client = Vonage(auth=auth)
                self.logger.info("🔧 Getting video client...")
                self.video_client = self.client.video
                self.auth_method = "jwt"
                self.is_mock_mode = False
                self.logger.info("✅ Vonage Video API initialized with Python Server SDK v4.7.2 and JWT authentication")
            except Exception as e:
                self.logger.error(f"❌ Vonage Video API initialization failed: {e}")
                self.logger.exception("Full error details:")
                self.logger.info("🔄 Falling back to mock mode for development")
                self.client = None
                self.video_client = None
                self.is_mock_mode = True
                self.auth_method = "mock"
        else:
            missing = []
            if not VONAGE_AVAILABLE:
                missing.append("Vonage SDK")
            if not self.application_id:
                missing.append("VONAGE_APPLICATION_ID")
            if not self.api_key:
                missing.append("VONAGE_API_KEY")
            if not self._load_private_key():
                missing.append("Private Key")
            
            self.logger.warning(f"Missing required credentials: {', '.join(missing)} - using mock mode")
            self.is_mock_mode = True
            self.auth_method = "mock"

    def _load_private_key(self) -> bool:
        """Load private key from file for JWT authentication."""
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

    def create_session(self, meeting_id: str) -> dict[str, Any]:
        self.logger.info("🔄 VonageClient.create_session() called for meeting_id=%s", meeting_id)
        self.logger.info("📊 Vonage client state: is_mock_mode=%s, has_video_client=%s, auth_method=%s", 
                         self.is_mock_mode, bool(self.video_client), getattr(self, 'auth_method', 'unknown'))
        
        if not self.video_client or self.is_mock_mode:
            # Generate a proper mock session ID that looks like a real Vonage session ID
            import uuid
            mock_session_id = f"1_MX40{abs(hash(meeting_id)) % 100000000}~-1~{uuid.uuid4().hex[:20]}"
            self.logger.warning("⚠️ Vonage Video client in mock mode; returning mock session_id=%s", mock_session_id)
            self.logger.warning("🔧 This means participants won't see each other - check Vonage API credentials")
            return {"session_id": mock_session_id}
        
        try:
            # Create session with Vonage Video Python Server SDK v4.7.2
            self.logger.info("🚀 Creating real Vonage session with Python Server SDK v4.7.2...")
            
            # Create session with new SDK API
            session = self.video_client.create_session()
            session_id = session.session_id
            
            self.logger.info("✅ Real Vonage session created successfully!")
            self.logger.info("📋 Session details: session_id=%s, meeting_id=%s, media_mode=routed", session_id, meeting_id)
            return {"session_id": session_id}
        except Exception as exc:
            self.logger.exception("❌ Vonage session creation failed for meeting_id=%s", meeting_id)
            self.logger.error("🔧 Error details: %s", str(exc))
            # Fallback to mock mode
            self.is_mock_mode = True
            import uuid
            mock_session_id = f"1_MX40{abs(hash(meeting_id)) % 100000000}~-1~{uuid.uuid4().hex[:20]}"
            self.logger.warning("🔄 Falling back to mock session_id=%s", mock_session_id)
            return {"session_id": mock_session_id}

    def generate_token(self, session_id: str, ttl_seconds: int = 300) -> str:
        self.logger.info("🎫 VonageClient.generate_token() called for session_id=%s, ttl=%d seconds", session_id[:20] + "...", ttl_seconds)
        
        if not self.video_client or self.is_mock_mode:
            # Generate a proper mock token that looks like a real Vonage token
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
            self.logger.warning("⚠️ Vonage Video client in mock mode; returning mock token")
            self.logger.warning("🔧 Mock tokens won't work for real video sessions")
            return token
        
        try:
            # Generate token with Vonage Video Python Server SDK v4.7.2
            expire_time = int(time.time()) + ttl_seconds
            
            # Create TokenOptions object
            token_options = TokenOptions(
                session_id=session_id,
                role='publisher',  # Can publish and subscribe
                expire_time=expire_time,
                data=f'meeting_session_{session_id[:8]}'  # Optional connection data
            )
            
            token = self.video_client.generate_client_token(token_options)
            
            self.logger.info("✅ Vonage token generated successfully for session_id=%s", session_id[:20] + "...")
            return token
        except Exception as exc:
            self.logger.exception("❌ Vonage token generation failed for session_id=%s", session_id)
            self.logger.error("🔧 Error details: %s", str(exc))
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
            self.logger.warning("🔄 Falling back to mock token for session_id=%s", session_id)
            return token
