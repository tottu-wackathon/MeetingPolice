from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from backend.models.meeting_model import Meeting


class MeetingRepository:
    """JSON-file backed store for meeting metadata."""

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or Path(__file__).resolve().parents[1] / 'data' / 'meetings.json'
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

    def _read_raw(self) -> list[dict]:
        if not self.storage_path.exists():
            return []
        try:
            return json.loads(self.storage_path.read_text())
        except json.JSONDecodeError:
            return []

    def _write_raw(self, payload: list[dict]) -> None:
        self.storage_path.write_text(json.dumps(payload, indent=2))

    def _normalize(self, item: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "meeting_id": item.get("meeting_id"),
            "title": item.get("title", "Untitled meeting"),
            "status": item.get("status", "scheduled"),
            "scheduled_for": item.get("scheduled_for") or now,
            "created_at": item.get("created_at") or item.get("scheduled_for") or now,
            "summary_s3_key": item.get("summary_s3_key"),
            "session_id": item.get("session_id"),
        }

    def list_meetings(self) -> List[Meeting]:
        with self._lock:
            payload = self._read_raw()
        return [Meeting(**self._normalize(item)) for item in payload]

    def get_meeting(self, meeting_id: str) -> Meeting | None:
        self.logger.info("📋 Getting meeting: %s", meeting_id)
        with self._lock:
            for item in self._read_raw():
                if item.get("meeting_id") == meeting_id:
                    meeting = Meeting(**self._normalize(item))
                    self.logger.info("✅ Meeting found: %s (status: %s)", meeting.title, meeting.status)
                    return meeting
        self.logger.warning("❌ Meeting not found: %s", meeting_id)
        return None

    def _upsert(self, meeting: Meeting) -> None:
        with self._lock:
            data = self._read_raw()
            for idx, item in enumerate(data):
                if item.get("meeting_id") == meeting.meeting_id:
                    data[idx] = meeting.dict()
                    break
            else:
                data.append(meeting.dict())
            self._write_raw(data)

    def update_meeting(self, meeting_id: str, **updates) -> Meeting:
        self.logger.info("📝 Updating meeting: %s with %s", meeting_id, updates)
        current = self.get_meeting(meeting_id)
        if not current:
            self.logger.error("❌ Cannot update - meeting not found: %s", meeting_id)
            raise KeyError(f"Meeting {meeting_id} not found")
        updated = current.copy(update=updates)
        self._upsert(updated)
        self.logger.info("✅ Meeting updated successfully: %s", meeting_id)
        return updated

    def create_meeting(self, title: str, scheduled_for: str | None = None) -> Meeting:
        now = datetime.now(timezone.utc).isoformat()
        meeting_id = f"mtg-{int(datetime.now(timezone.utc).timestamp())}"
        self.logger.info("📝 Creating new meeting: %s (ID: %s)", title, meeting_id)
        
        meeting = Meeting(
            meeting_id=meeting_id,
            title=title,
            status='scheduled',
            scheduled_for=scheduled_for or now,
            created_at=now,
            session_id=None,
            summary_s3_key=None,
        )
        self._upsert(meeting)
        self.logger.info("✅ Meeting saved to database: %s", meeting_id)
        return meeting
