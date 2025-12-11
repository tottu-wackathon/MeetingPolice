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
        try:
            # Test session creation to verify connection
            test_session = self.vonage.create_session("test-connection")
            session_id = test_session.get("session_id", "")
            
            # Determine connection status
            if session_id.startswith("1_MX40") and not session_id.startswith("session-"):
                # Real Vonage session ID format
                status = "connected"
                auth_method = getattr(self.vonage, 'auth_method', 'unknown')
            elif session_id.startswith("1_MX40"):
                # Mock session but proper format
                status = "mock"
                auth_method = "mock"
            else:
                # Simple mock session
                status = "disconnected"
                auth_method = "mock"
            
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
            
            # Determine if it's a real session
            is_real = (
                session_id.startswith("1_MX40") and 
                not getattr(self.vonage, 'is_mock_mode', True) and
                bool(self.vonage.client)
            )
            
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
