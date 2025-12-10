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
        import logging
        logger = logging.getLogger(__name__)
        
        if not self.client:
            logger.error("Transcribe client not configured")
            on_transcript({"error": "transcribe client not configured"})
            return
            
        # Try new amazon-transcribe streaming API first
        try:
            self._stream_with_amazon_transcribe(audio_queue, on_transcript, language_code)
            return
        except ImportError:
            logger.warning("amazon-transcribe package not available, trying boto3 API")
        except Exception as e:
            logger.error("amazon-transcribe streaming failed: %s", e)
        
        # Fallback to boto3 API
        try:
            self._stream_with_boto3(audio_queue, on_transcript, language_code)
        except (BotoCoreError, ClientError) as exc:
            logger.error("boto3 transcribe failed: %s", exc)
            on_transcript({"error": str(exc)})
        except Exception as exc:
            logger.error("Transcribe streaming failed: %s", exc)
            on_transcript({"error": str(exc)})

    def _stream_with_amazon_transcribe(
        self,
        audio_queue: queue.Queue[bytes | None],
        on_transcript: Callable[[dict[str, Any]], None],
        language_code: str = "ja-JP",
    ) -> None:
        """Use amazon-transcribe streaming client."""
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler
        from amazon_transcribe.model import TranscriptEvent
        import asyncio
        import logging
        
        logger = logging.getLogger(__name__)
        logger.info("Starting amazon-transcribe streaming...")
        
        class MyEventHandler(TranscriptResultStreamHandler):
            def __init__(self, transcript_callback):
                super().__init__()
                self.callback = transcript_callback
                
            async def handle_transcript_event(self, transcript_event: TranscriptEvent):
                results = transcript_event.transcript.results
                for result in results:
                    if result.alternatives:
                        transcript = result.alternatives[0].transcript
                        if transcript.strip():
                            self.callback({
                                "transcript": transcript,
                                "is_partial": result.is_partial,
                                "start_time": getattr(result, 'start_time', None),
                                "end_time": getattr(result, 'end_time', None),
                            })
        
        async def stream_audio():
            # Get AWS credentials
            session = get_session()
            credentials = session.get_credentials()
            if not credentials:
                raise RuntimeError("AWS credentials not found")
                
            frozen = credentials.get_frozen_credentials()
            
            client = TranscribeStreamingClient(region=get_settings().aws_region)
            
            # Create audio stream generator
            async def audio_generator():
                while True:
                    chunk = audio_queue.get()
                    if chunk is None:
                        break
                    yield chunk
            
            # Start streaming
            stream = await client.start_stream_transcription(
                language_code=language_code,
                media_sample_rate_hz=16000,
                media_encoding="pcm",
            )
            
            handler = MyEventHandler(on_transcript)
            
            # Process audio and results concurrently
            await asyncio.gather(
                self._write_chunks(stream, audio_generator()),
                handler.handle_events(stream.output_stream)
            )
        
        # Run the async streaming
        asyncio.run(stream_audio())
    
    async def _write_chunks(self, stream, audio_generator):
        """Write audio chunks to the stream."""
        async for chunk in audio_generator:
            await stream.input_stream.send_audio_event(audio_chunk=chunk)
        await stream.input_stream.end_stream()

    def _stream_with_boto3(
        self,
        audio_queue: queue.Queue[bytes | None],
        on_transcript: Callable[[dict[str, Any]], None],
        language_code: str = "ja-JP",
    ) -> None:
        """Fallback to boto3 API."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Using boto3 transcribe API...")
        
        if not hasattr(self.client, "start_stream_transcription"):
            raise RuntimeError("transcribe streaming not supported in current boto3/botocore")
            
        response = self.client.start_stream_transcription(
            LanguageCode=language_code,
            MediaEncoding="pcm",
            MediaSampleRateHertz=16000,
            AudioStream=_QueueAudioStream(audio_queue),
        )
        stream = response.get("TranscriptResultStream")
        if not stream:
            raise RuntimeError("no transcript stream")

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

    def _silence_chunks(self, seconds: int = 2, chunk_size: int = 3200) -> Iterator[bytes]:
        total_chunks = max(1, (seconds * 16000) // chunk_size)
        silence = b"\x00" * chunk_size
        for _ in range(total_chunks):
            yield silence
