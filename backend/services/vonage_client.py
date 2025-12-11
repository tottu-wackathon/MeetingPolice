import logging
import uuid
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# プロジェクトルートをパスに追加して設定を読み込み
project_root = Path(__file__).resolve().parents[2]
sys.path.append(str(project_root / "backend"))

try:
    from config import get_settings
except ImportError:
    # 設定ファイルが見つからない場合の代替手段
    import os
    from dotenv import load_dotenv
    
    # .envファイルを直接読み込み
    env_path = project_root / ".env"
    load_dotenv(env_path)
    
    class MockSettings:
        def __init__(self):
            self.vonage_application_id = os.getenv("VONAGE_APPLICATION_ID", "")
            self.vonage_api_key = os.getenv("VONAGE_API_KEY", "")
            self.vonage_api_secret = os.getenv("VONAGE_API_SECRET", "")
            self.vonage_private_key_path = os.getenv("VONAGE_PRIVATE_KEY_PATH", "secrets/private.key")
    
    def get_settings():
        return MockSettings()

logger = logging.getLogger(__name__)


class VonageClient:
    """Vonage Video API client with fallback to mock mode"""
    
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        self.video = None
        self.private_key = None
        self._initialize_client()
    
    @property
    def api_key(self):
        """Backward compatibility property for API key access"""
        return self.settings.vonage_api_key
    
    def _initialize_client(self):
        """Initialize Vonage client with proper error handling"""
        try:
            # Validate configuration
            if not self.settings.vonage_application_id:
                logger.warning("Vonage Application ID is empty")
                logger.info("Running in mock mode")
                return
                
            # 設定値をログ出力（デバッグ用）
            logger.info(f"Vonage Application ID: {self.settings.vonage_application_id[:8]}...")
            logger.info(f"Private Key Path: {self.settings.vonage_private_key_path}")
            
            # Load private key
            key_path = Path(self.settings.vonage_private_key_path)
            if not key_path.exists():
                # 絶対パスで再試行
                key_path = project_root / self.settings.vonage_private_key_path
                
            if not key_path.exists():
                logger.warning(f"Private key file not found: {key_path}")
                logger.info("Running in mock mode")
                return
            
            self.private_key = key_path.read_text().strip()
            
            # Validate private key format
            if not self.private_key.startswith("-----BEGIN PRIVATE KEY-----"):
                logger.warning("Private key does not appear to be in correct PEM format")
                logger.info("Running in mock mode")
                return
                
            logger.info(f"Private key loaded successfully ({len(self.private_key)} characters)")
            
            # Import Vonage modules
            try:
                import vonage_video
                from vonage_http_client import HttpClient
                logger.info("Vonage modules imported successfully")
            except ImportError as e:
                logger.warning(f"Vonage modules not available: {e}")
                logger.info("Running in mock mode")
                return
            
            # Initialize HTTP client
            try:
                # Try different initialization methods
                http_client = None
                
                # Method 1: Using Auth object (recommended)
                try:
                    from vonage import Auth
                    auth = Auth(
                        application_id=self.settings.vonage_application_id,
                        private_key=self.private_key
                    )
                    http_client = HttpClient(auth)
                    logger.info("HttpClient initialized with Auth object")
                except Exception as e1:
                    logger.debug(f"HttpClient Auth object failed: {e1}")
                
                # Method 2: Direct parameters
                if not http_client:
                    try:
                        http_client = HttpClient(
                            application_id=self.settings.vonage_application_id,
                            private_key=self.private_key
                        )
                        logger.info("HttpClient initialized with direct params")
                    except Exception as e2:
                        logger.debug(f"HttpClient direct params failed: {e2}")
                
                if not http_client:
                    logger.warning("Failed to initialize HttpClient")
                    return
                
                # Initialize Video client
                self.video = vonage_video.Video(http_client)
                logger.info("✅ Vonage Video API initialized successfully")
                
            except Exception as e:
                logger.warning(f"Failed to initialize Vonage Video client: {e}")
                logger.info("Running in mock mode")
                
        except Exception as e:
            logger.warning(f"Vonage initialization error: {e}")
            logger.info("Running in mock mode")
    
    def create_session(self, meeting_id: str, media_mode: str = "routed", archive_mode: str = "manual", location: Optional[str] = None) -> Dict[str, Any]:
        """Create a new video session"""
        if self.video:
            try:
                # Real Vonage API call following official documentation
                from vonage_video.models import SessionOptions, VideoSession
                
                # Create session options following Vonage documentation
                # https://developer.vonage.com/en/video/server-sdks/python/sessions
                session_options_params = {
                    "media_mode": media_mode,  # "routed" or "relayed"
                    "archive_mode": archive_mode  # "manual" or "always"
                }
                
                # Add location hint if provided (for geographic routing optimization)
                if location:
                    session_options_params["location"] = location
                
                session_options = SessionOptions(**session_options_params)
                
                # Create session and get VideoSession object
                session_info: VideoSession = self.video.create_session(session_options)
                
                # Extract session ID as recommended by Vonage docs
                session_id = session_info.session_id
                
                logger.info(f"Created real Vonage session {session_id} for meeting {meeting_id}")
                
                return {
                    "session_id": session_id,
                    "meeting_id": meeting_id,
                    "created_at": getattr(session_info, 'created_at', None),
                    "status": "active",
                    "media_mode": session_options.media_mode,
                    "archive_mode": session_options.archive_mode
                }
            except Exception as e:
                logger.error(f"Failed to create real Vonage session: {e}")
                # Fall back to mock
                return self._create_mock_session(meeting_id)
        else:
            # Mock mode
            return self._create_mock_session(meeting_id)
    
    def _create_mock_session(self, meeting_id: str) -> Dict[str, Any]:
        """Create a mock session for testing"""
        session_id = f"session-{uuid.uuid4().hex[:16]}"
        logger.info(f"Created mock session: {session_id}")
        return {
            "session_id": session_id,
            "meeting_id": meeting_id,
            "created_at": None,
            "status": "mock"
        }
    
    def generate_token(self, session_id: str, role: str = "publisher", connection_data: Optional[str] = None, ttl_seconds: int = 300) -> str:
        """Generate a client token for the session following Vonage documentation"""
        if self.video:
            try:
                # Real Vonage API call following official documentation
                # https://developer.vonage.com/en/video/server-sdks/python/tokens
                import time
                from vonage_video.models import TokenOptions
                
                # Calculate expiration time (Unix timestamp)
                expire_time = int(time.time()) + ttl_seconds
                
                # Create token options following Vonage documentation
                # Valid roles: "publisher", "subscriber", "moderator"
                token_options_params = {
                    "session_id": session_id,  # Required by Vonage API
                    "role": role,
                    "expire_time": expire_time
                }
                
                # Add connection data if provided (optional metadata)
                if connection_data:
                    token_options_params["connection_data"] = connection_data
                
                token_options = TokenOptions(**token_options_params)
                
                # Generate token with token_options only
                # The session_id is included in token_options
                token = self.video.generate_client_token(token_options)
                
                # Convert bytes to string if necessary
                if isinstance(token, bytes):
                    token = token.decode('utf-8')
                
                logger.info(f"Generated real Vonage token for session {session_id}, role={role}, expires in {ttl_seconds}s")
                return token
            except Exception as e:
                logger.error(f"Failed to generate real Vonage token: {e}")
                # Fall back to mock
                return self._generate_mock_token(session_id, role)
        else:
            # Mock mode
            return self._generate_mock_token(session_id, role)
    
    def _generate_mock_token(self, session_id: str, role: str) -> str:
        """Generate a mock token for testing"""
        token = f"mock-token-{role}-{uuid.uuid4().hex[:16]}"
        logger.info(f"Generated mock token for session {session_id}")
        return token
    
    def get_session_info(self, session_id: str) -> Dict[str, Any]:
        """Get session information"""
        if self.video:
            try:
                # Real Vonage API call - Vonage Video APIには直接的なget_sessionメソッドがない場合があります
                # 代わりに、セッション作成時の情報を返すか、利用可能なメソッドを使用
                return {
                    "session_id": session_id,
                    "status": "active",
                    "created_at": None,  # 実際のAPIから取得する場合は適切なメソッドを使用
                    "connection_count": 0  # 実際のAPIから取得する場合は適切なメソッドを使用
                }
            except Exception as e:
                logger.error(f"Failed to get real session info: {e}")
                # Fall back to mock
                return self._get_mock_session_info(session_id)
        else:
            # Mock mode
            return self._get_mock_session_info(session_id)
    
    def _get_mock_session_info(self, session_id: str) -> Dict[str, Any]:
        """Get mock session information"""
        return {
            "session_id": session_id,
            "status": "mock",
            "created_at": None,
            "connection_count": 0
        }
    
    def is_real_mode(self) -> bool:
        """Check if running in real Vonage mode"""
        return self.video is not None
