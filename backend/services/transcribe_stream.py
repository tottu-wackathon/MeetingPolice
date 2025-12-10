from __future__ import annotations

import asyncio
import queue
from typing import Iterable, Iterator, Any, Callable

from botocore.exceptions import BotoCoreError, ClientError

from backend.utils.auth_aws import get_session
from backend.config import get_settings


class _AudioStream:
    def __init__(self, chunks: Iterable[bytes]):
        self._chunks = chunks

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for chunk in self._chunks:
            yield {"AudioEvent": {"AudioChunk": chunk}}


class _QueueAudioStream:
    """Blocking iterator that feeds AWS Transcribe from a queue.Queue of audio bytes."""

    def __init__(self, q: queue.Queue[bytes | None]):
        self._q = q

    def __iter__(self) -> Iterator[dict[str, Any]]:
        while True:
            chunk = self._q.get()
            if chunk is None:
                break
            yield {"AudioEvent": {"AudioChunk": chunk}}


class TranscribeStream:
    def __init__(self, client: Any | None = None):
        session = get_session()
        # `transcribe-streaming` is not a standalone boto3 service; streaming APIs live under the `transcribe` client.
        self.client = client or session.client("transcribe", region_name=get_settings().aws_region)

    async def start(self, audio_stream: Iterable[bytes] | None = None) -> str:
        chunks = audio_stream or self._silence_chunks()
        try:
            response = await asyncio.to_thread(
                self.client.start_stream_transcription,
                LanguageCode="ja-JP",
                MediaEncoding="pcm",
                MediaSampleRateHertz=16000,
                AudioStream=_AudioStream(chunks),
            )
            return response.get("SessionId", "transcribe_session_started")
        except (BotoCoreError, ClientError) as exc:
            return f"error: {exc}"

    def stream_audio(
        self,
        audio_queue: queue.Queue[bytes | None],
        on_transcript: Callable[[dict[str, Any]], None],
        language_code: str = "ja-JP",
    ) -> None:
        """Stream audio bytes from queue to AWS Transcribe and call back per transcript result."""
        if not self.client:
            on_transcript({"error": "transcribe client not configured"})
            return
        if not hasattr(self.client, "start_stream_transcription"):
            on_transcript({"error": "transcribe streaming not supported in current boto3/botocore; falling back"})
            return
        try:
            response = self.client.start_stream_transcription(
                LanguageCode=language_code,
                MediaEncoding="pcm",
                MediaSampleRateHertz=16000,
                AudioStream=_QueueAudioStream(audio_queue),
            )
            stream = response.get("TranscriptResultStream")
            if not stream:
                on_transcript({"error": "no transcript stream"})
                return

            for event in stream:
                transcript_event = event.get("TranscriptEvent")
                if not transcript_event:
                    continue
                results = transcript_event.get("Transcript", {}).get("Results", [])
                for result in results:
                    alternatives = result.get("Alternatives") or []
                    if not alternatives:
                        continue
                    text = (alternatives[0].get("Transcript") or "").strip()
                    if not text:
                        continue
                    payload = {
                        "transcript": text,
                        "is_partial": result.get("IsPartial", False),
                        "start_time": result.get("StartTime"),
                        "end_time": result.get("EndTime"),
                    }
                    on_transcript(payload)
        except (BotoCoreError, ClientError) as exc:
            on_transcript({"error": str(exc)})

    def _silence_chunks(self, seconds: int = 2, chunk_size: int = 3200) -> Iterator[bytes]:
        total_chunks = max(1, (seconds * 16000) // chunk_size)
        silence = b"\x00" * chunk_size
        for _ in range(total_chunks):
            yield silence
