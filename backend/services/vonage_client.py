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
        
        self.logger.info("=" * 60)
        self.logger.info("🚀 VONAGE CLIENT INITIALIZATION STARTED")
        self.logger.info("=" * 60)
        self.logger.info("📋 Step 1: Configuration Check")
        self.logger.info("   - API Key: %s", "✅ Set" if self.api_key else "❌ Missing")
        self.logger.info("   - Application ID: %s", "✅ Set" if self.application_id else "❌ Missing")
        self.logger.info("   - Private Key Path: %s", self.private_key_path)
        self.logger.info("   - Mock Mode Setting: %s", getattr(self.settings, 'vonage_mock_mode', False))
        
        self.logger.info("📋 Step 2: Mock Mode Check")
        # Check if mock mode is explicitly enabled
        if getattr(self.settings, 'vonage_mock_mode', False):
            self.logger.info("   ⚠️  Mock mode explicitly enabled in configuration")
            self.is_mock_mode = True
            self.auth_method = "mock"
            self._log_initialization_result()
            return

        self.logger.info("📋 Step 3: SDK and Credentials Validation")
        self.logger.info("   - Vonage SDK Available: %s", "✅ Yes" if VONAGE_AVAILABLE else "❌ No")
        
        # Check for placeholder values
        if (self.application_id in ["your_application_id_here", ""] or 
            self.api_key in ["your_api_key_here", ""]):
            self.logger.warning("   ⚠️  Placeholder values detected in configuration")
            self.logger.warning("   - Application ID: %s", self.application_id)
            self.logger.warning("   - API Key: %s", self.api_key)
            self.is_mock_mode = True
            self.auth_method = "mock"
            self._log_initialization_result()
            return

        # Load private key
        private_key_loaded = self._load_private_key()
        self.logger.info("   - Private Key Loaded: %s", "✅ Yes" if private_key_loaded else "❌ No")
        
        if VONAGE_AVAILABLE and self.application_id and self.api_key and private_key_loaded:
            self.logger.info("📋 Step 4: Vonage Client Initialization")
            try:
                self.logger.info("   🔧 Creating Vonage Auth object...")
                # Initialize Vonage client with JWT authentication
                auth = Auth(
                    application_id=self.application_id,
                    private_key=self.private_key_content
                )
                self.logger.info("   ✅ Auth object created successfully")
                
                self.logger.info("   🔧 Creating Vonage client...")
                self.client = Vonage(auth=auth)
                self.logger.info("   ✅ Vonage client created successfully")
                
                self.logger.info("   🔧 Getting video client...")
                self.video_client = self.client.video
                self.logger.info("   ✅ Video client obtained successfully")
                
                self.auth_method = "jwt"
                self.is_mock_mode = False
                self.logger.info("📋 Step 5: Initialization Complete")
                self.logger.info("   ✅ Vonage Video API initialized with Python Server SDK v4.7.2 and JWT authentication")
            except Exception as e:
                self.logger.error("📋 Step 4: Initialization Failed")
                self.logger.error(f"   ❌ Vonage Video API initialization failed: {e}")
                self.logger.exception("   Full error details:")
                self.logger.info("   🔄 Falling back to mock mode for development")
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
            if not private_key_loaded:
                missing.append("Private Key")
            
            self.logger.warning("📋 Step 4: Requirements Not Met")
            self.logger.warning(f"   ❌ Missing required credentials: {', '.join(missing)}")
            self.logger.warning("   🔄 Using mock mode for development")
            self.is_mock_mode = True
            self.auth_method = "mock"
        
        self._log_initialization_result()

    def _load_private_key(self) -> bool:
        """Load private key from file for JWT authentication."""
        try:
            key_path = Path(self.private_key_path)
            if key_path.exists():
                self.private_key_content = key_path.read_text(encoding='utf-8')
                # Check if it's a placeholder
                if "ここにあなたの実際の秘密鍵" in self.private_key_content:
                    self.logger.error(f"Private key file contains placeholder content: {self.private_key_path}")
                    return False
                return True
            else:
                self.logger.error(f"Private key file not found: {self.private_key_path}")
                return False
        except Exception as e:
            self.logger.error(f"Failed to load private key: {e}")
            return False

    def _log_initialization_result(self):
        """Log the final initialization result."""
        self.logger.info("=" * 60)
        self.logger.info("🏁 VONAGE CLIENT INITIALIZATION RESULT")
        self.logger.info("=" * 60)
        self.logger.info("Mode: %s", "🔧 MOCK MODE" if self.is_mock_mode else "🚀 PRODUCTION MODE")
        self.logger.info("Auth Method: %s", getattr(self, 'auth_method', 'unknown'))
        self.logger.info("Video Client: %s", "✅ Available" if self.video_client else "❌ Not Available")
        if self.is_mock_mode:
            self.logger.warning("⚠️  WARNING: Running in mock mode - video sessions will not work!")
            self.logger.warning("⚠️  To enable real video sessions:")
            self.logger.warning("   1. Set valid VONAGE_APPLICATION_ID in .env")
            self.logger.warning("   2. Set valid VONAGE_API_KEY in .env")
            self.logger.warning("   3. Place valid private key in secrets/vonage_private.key")
        else:
            self.logger.info("✅ Ready for real video sessions!")
        self.logger.info("=" * 60)

    def create_session(self, meeting_id: str) -> dict[str, Any]:
        self.logger.info("=" * 50)
        self.logger.info("🎬 CREATE SESSION REQUEST")
        self.logger.info("=" * 50)
        self.logger.info("Meeting ID: %s", meeting_id)
        self.logger.info("Client State:")
        self.logger.info("  - Mock Mode: %s", self.is_mock_mode)
        self.logger.info("  - Video Client: %s", "Available" if self.video_client else "Not Available")
        self.logger.info("  - Auth Method: %s", getattr(self, 'auth_method', 'unknown'))
        
        if not self.video_client or self.is_mock_mode:
            self.logger.warning("🔧 MOCK MODE: Creating mock session")
            # Generate a proper mock session ID that looks like a real Vonage session ID
            import uuid
            mock_session_id = f"1_MX40{abs(hash(meeting_id)) % 100000000}~-1~{uuid.uuid4().hex[:20]}"
            self.logger.warning("   Mock Session ID: %s", mock_session_id)
            self.logger.warning("   ⚠️  This is a mock session - real video will not work!")
            return {"session_id": mock_session_id}
        
        try:
            self.logger.info("🚀 PRODUCTION MODE: Creating real Vonage session")
            self.logger.info("   Using Vonage Video Python Server SDK v4.7.2...")
            
            # Create session with new SDK API
            session = self.video_client.create_session()
            session_id = session.session_id
            
            self.logger.info("✅ SUCCESS: Real Vonage session created!")
            self.logger.info("   Session ID: %s", session_id)
            self.logger.info("   Meeting ID: %s", meeting_id)
            self.logger.info("   Media Mode: routed")
            return {"session_id": session_id}
        except Exception as exc:
            self.logger.error("❌ FAILED: Vonage session creation failed")
            self.logger.error("   Meeting ID: %s", meeting_id)
            self.logger.error("   Error: %s", str(exc))
            self.logger.exception("   Full traceback:")
            
            # Fallback to mock mode
            self.logger.warning("🔄 FALLBACK: Switching to mock mode")
            self.is_mock_mode = True
            import uuid
            mock_session_id = f"1_MX40{abs(hash(meeting_id)) % 100000000}~-1~{uuid.uuid4().hex[:20]}"
            self.logger.warning("   Fallback Session ID: %s", mock_session_id)
            return {"session_id": mock_session_id}

    def generate_token(self, session_id: str, ttl_seconds: int = 300) -> str:
        self.logger.info("=" * 50)
        self.logger.info("🎫 GENERATE TOKEN REQUEST")
        self.logger.info("=" * 50)
        self.logger.info("Session ID: %s...", session_id[:20])
        self.logger.info("TTL: %d seconds", ttl_seconds)
        self.logger.info("Client State:")
        self.logger.info("  - Mock Mode: %s", self.is_mock_mode)
        self.logger.info("  - Video Client: %s", "Available" if self.video_client else "Not Available")
        
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
            self.logger.info("🔧 Using Vonage Video SDK for token generation")
            expire_time = int(time.time()) + ttl_seconds
            
            # Create TokenOptions object
            token_options = TokenOptions(
                session_id=session_id,
                role='publisher',  # Can publish and subscribe
                expire_time=expire_time,
                data=f'meeting_session_{session_id[:8]}'  # Optional connection data
            )
            
            token = self.video_client.generate_client_token(token_options)
            
            # トークンがbytesの場合は文字列に変換
            if isinstance(token, bytes):
                token = token.decode('utf-8')
                self.logger.info("🔧 Token was bytes, converted to string")
            
            self.logger.info("✅ Vonage token generated successfully for session_id=%s", session_id[:20] + "...")
            self.logger.info("🔍 Generated token details: length=%d, type=%s, starts_with=%s, contains_dots=%s", 
                           len(token), type(token).__name__, 
                           token[:10] + "..." if len(token) > 10 else token, "." in token)
            
            # JWTの場合、ペイロードをデコードして確認
            if isinstance(token, str) and "." in token:
                try:
                    import base64
                    import json
                    parts = token.split(".")
                    if len(parts) >= 2:
                        # Base64デコード（パディング調整）
                        payload_b64 = parts[1]
                        payload_b64 += "=" * (4 - len(payload_b64) % 4)  # パディング調整
                        payload = json.loads(base64.b64decode(payload_b64))
                        self.logger.info("🔍 JWT payload: %s", payload)
                except Exception as e:
                    self.logger.warning("Failed to decode JWT payload: %s", e)
            
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
