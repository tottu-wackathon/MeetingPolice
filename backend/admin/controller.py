from backend.models.meeting_model import Meeting
from backend.services.repository import MeetingRepository
from backend.services.s3_storage import S3Storage
from backend.services.bedrock_utils import summarize_transcript


class AdminController:
    def __init__(self, repository: MeetingRepository | None = None):
        self.repository = repository or MeetingRepository()
        self.storage = S3Storage()

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
