from backend.models.meeting_model import Meeting
from backend.services.repository import MeetingRepository
from backend.services.s3_storage import S3Storage
from backend.services.bedrock_utils import summarize_transcript
from backend.services.vonage_client import VonageClient


class AdminController:
    def __init__(self, repository: MeetingRepository | None = None):
        self.repository = repository or MeetingRepository()
        self.storage = S3Storage()
        self.vonage = VonageClient()

    def list_meetings(self) -> list[Meeting]:
        return self.repository.list_meetings()

    def create_meeting(self, payload: dict) -> Meeting:
        title = payload.get("title")
        if not title:
            raise ValueError("title is required")
        scheduled_for = payload.get("scheduled_for")
        meeting = self.repository.create_meeting(title=title, scheduled_for=scheduled_for)
        return meeting

    def generate_summary(self, meeting_id: str) -> dict:
        """Fetch transcript from storage and summarize via Bedrock."""
        transcript_key = f"transcripts/{meeting_id}.txt"
        try:
            transcript_text = self.storage.read_text(transcript_key)
        except FileNotFoundError:
            transcript_text = "Transcript not available yet."
        summary = summarize_transcript(meeting_id, transcript_text)
        summary_key = f"summaries/{meeting_id}.json"
        self.storage.write_json(summary_key, summary)
        self.repository.update_meeting(meeting_id, summary_s3_key=summary_key, status="completed")
        return summary

    def get_vonage_status(self) -> dict:
        """Get Vonage API connection status and authentication method."""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            logger.info("🔍 ADMIN: Testing Vonage connection status...")
            # Test session creation to verify connection
            test_session = self.vonage.create_session("test-connection")
            session_id = test_session.get("session_id", "")
            logger.info(f"🔍 ADMIN: Test session created: {session_id[:30]}...")
            
            # Determine connection status based on actual Vonage session ID format
            is_real_session = (session_id.startswith("1_MX") or session_id.startswith("2_MX")) and len(session_id) > 50
            is_mock_mode = getattr(self.vonage, 'is_mock_mode', False)
            has_video_client = bool(getattr(self.vonage, 'video_client', None))
            auth_method = getattr(self.vonage, 'auth_method', 'unknown')
            
            logger.info(f"🔍 ADMIN: Session analysis:")
            logger.info(f"  - Session ID format: {session_id[:20]}... (length: {len(session_id)})")
            logger.info(f"  - Is real session format: {is_real_session}")
            logger.info(f"  - Is mock mode: {is_mock_mode}")
            logger.info(f"  - Has video client: {has_video_client}")
            logger.info(f"  - Auth method: {auth_method}")
            
            if is_real_session and not is_mock_mode and has_video_client:
                # Real Vonage session ID format and not in mock mode
                status = "connected"
                logger.info("✅ ADMIN: Status determined as CONNECTED")
            elif is_real_session and (is_mock_mode or not has_video_client):
                # Real format but mock mode enabled or no client
                status = "mock"
                logger.info("⚠️ ADMIN: Status determined as MOCK")
            else:
                # Simple mock session or error
                status = "disconnected"
                logger.info("❌ ADMIN: Status determined as DISCONNECTED")
            
            return {
                "status": status,
                "auth_method": auth_method,
                "api_key": self.vonage.api_key[:8] + "..." if self.vonage.api_key else "Not set",
                "application_id": self.vonage.application_id[:8] + "..." if self.vonage.application_id else "Not set",
                "has_private_key": hasattr(self.vonage, 'private_key_content') and bool(self.vonage.private_key_content),
                "test_session_id": session_id[:20] + "..." if len(session_id) > 20 else session_id
            }
        except Exception as e:
            return {
                "status": "error",
                "auth_method": "unknown",
                "error": str(e),
                "api_key": self.vonage.api_key[:8] + "..." if self.vonage.api_key else "Not set",
                "application_id": self.vonage.application_id[:8] + "..." if self.vonage.application_id else "Not set",
                "has_private_key": False
            }

    def test_session_creation(self) -> dict:
        """Test Vonage session creation with detailed logging."""
        try:
            import uuid
            test_meeting_id = f"test-{uuid.uuid4().hex[:8]}"
            
            # Create test session
            result = self.vonage.create_session(test_meeting_id)
            session_id = result.get("session_id", "")
            
            # Generate test token
            token = self.vonage.generate_token(session_id)
            
            # Determine if it's a real session (correct Vonage session ID format)
            is_real_session = (session_id.startswith("1_MX") or session_id.startswith("2_MX")) and len(session_id) > 50
            is_mock_mode = getattr(self.vonage, 'is_mock_mode', False)
            has_real_client = bool(getattr(self.vonage, 'video_client', None))
            
            is_real = is_real_session and not is_mock_mode and has_real_client
            
            return {
                "success": True,
                "session_id": session_id,
                "token": token[:20] + "..." if len(token) > 20 else token,
                "is_real": is_real,
                "auth_method": getattr(self.vonage, 'auth_method', 'unknown'),
                "test_meeting_id": test_meeting_id
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "is_real": False
            }

    def list_meetings_with_vonage_status(self) -> dict:
        """List meetings with Vonage connection status."""
        meetings = self.list_meetings()
        vonage_status = self.get_vonage_status()
        
        return {
            "meetings": [meeting.model_dump() for meeting in meetings],
            "vonage_status": vonage_status
        }
