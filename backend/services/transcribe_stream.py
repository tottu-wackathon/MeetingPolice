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
            
        # Try boto3 API first for better speaker identification support
        logger.info("Prioritizing boto3 API for speaker identification support")
        try:
            self._stream_with_boto3(audio_queue, on_transcript, language_code)
            return
        except (BotoCoreError, ClientError) as exc:
            logger.error("boto3 transcribe failed: %s", exc)
        except Exception as exc:
            logger.error("boto3 transcribe streaming failed: %s", exc)
        
        # Fallback to amazon-transcribe streaming API
        try:
            logger.warning("Falling back to amazon-transcribe library")
            self._stream_with_amazon_transcribe(audio_queue, on_transcript, language_code)
        except ImportError:
            logger.error("amazon-transcribe package not available")
            on_transcript({"error": "Both boto3 and amazon-transcribe failed"})
        except Exception as e:
            logger.error("amazon-transcribe streaming failed: %s", e)
            on_transcript({"error": str(e)})

    def _stream_with_amazon_transcribe(
        self,
        audio_queue: queue.Queue[bytes | None],
        on_transcript: Callable[[dict[str, Any]], None],
        language_code: str = "ja-JP",
    ) -> None:
        """Use amazon-transcribe streaming client."""
        import asyncio
        import logging
        import threading
        
        logger = logging.getLogger(__name__)
        logger.info("Starting amazon-transcribe streaming...")
        
        def run_async_transcribe():
            try:
                asyncio.run(self._async_transcribe_stream(audio_queue, on_transcript, language_code))
            except Exception as e:
                logger.error("Async transcribe failed: %s", e)
                raise
        
        # Run in a separate thread to avoid blocking
        thread = threading.Thread(target=run_async_transcribe, daemon=True)
        thread.start()
        thread.join()  # Wait for completion
    
    async def _async_transcribe_stream(
        self,
        audio_queue: queue.Queue[bytes | None],
        on_transcript: Callable[[dict[str, Any]], None],
        language_code: str = "ja-JP",
    ):
        """Async transcribe streaming implementation."""
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler
        from amazon_transcribe.model import TranscriptEvent
        from amazon_transcribe.auth import StaticCredentialResolver
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Get AWS credentials
        session = get_session()
        credentials = session.get_credentials()
        if not credentials:
            raise RuntimeError("AWS credentials not found")
            
        frozen = credentials.get_frozen_credentials()
        
        # Create credential resolver
        credential_resolver = StaticCredentialResolver(
            access_key_id=frozen.access_key,
            secret_access_key=frozen.secret_key,
            session_token=frozen.token,
        )
        
        # Create client
        client = TranscribeStreamingClient(
            region=get_settings().aws_region,
            credential_resolver=credential_resolver,
        )
        
        # Create audio stream generator
        async def audio_generator():
            import asyncio
            import time
            last_chunk_time = time.time()
            silence_chunk = b'\x00' * 320  # 10ms of silence at 16kHz
            
            while True:
                try:
                    # Use asyncio to avoid blocking
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, audio_queue.get, True, 0.5  # 0.5 second timeout
                    )
                    if chunk is None:
                        logger.info("Audio stream ended")
                        break
                    last_chunk_time = time.time()
                    yield chunk
                except:
                    # Timeout or queue empty, send silence to prevent timeout
                    current_time = time.time()
                    if current_time - last_chunk_time > 10:  # Send silence every 10 seconds
                        logger.debug("Sending silence chunk to prevent timeout")
                        yield silence_chunk
                        last_chunk_time = current_time
                    await asyncio.sleep(0.1)
        
        # Start streaming with speaker identification attempt
        logger.info("Starting transcribe stream with speaker identification attempt...")
        try:
            # Try with speaker identification parameters
            stream = await client.start_stream_transcription(
                language_code=language_code,
                media_sample_rate_hz=16000,
                media_encoding="pcm",
                enable_speaker_identification=True,
                number_of_speakers=5,
            )
            logger.info("✅ Speaker identification enabled in amazon-transcribe")
        except Exception as e:
            logger.warning(f"⚠️ Speaker identification not supported in amazon-transcribe: {e}")
            # Fallback without speaker identification
            stream = await client.start_stream_transcription(
                language_code=language_code,
                media_sample_rate_hz=16000,
                media_encoding="pcm",
            )
            logger.info("Fallback to transcription without speaker identification")
        
        # Create event handler
        class MyEventHandler(TranscriptResultStreamHandler):
            def __init__(self, output_stream, callback):
                super().__init__(output_stream)
                self.callback = callback
                
            async def handle_transcript_event(self, transcript_event: TranscriptEvent):
                try:
                    results = transcript_event.transcript.results
                    for result in results:
                        # Debug: Log result structure to understand speaker information
                        logger.debug(f"Result attributes: {[attr for attr in dir(result) if not attr.startswith('_')]}")
                        
                        if result.alternatives:
                            alternative = result.alternatives[0]
                            transcript = alternative.transcript
                            if transcript and transcript.strip():
                                # Debug: Log alternative structure
                                logger.debug(f"Alternative attributes: {[attr for attr in dir(alternative) if not attr.startswith('_')]}")
                                
                                # Extract speaker information from the result
                                speaker_label = None
                                
                                # Check if result has speaker attribute directly
                                if hasattr(result, 'speaker') and result.speaker:
                                    speaker_label = result.speaker
                                    logger.debug(f"Found speaker in result: {speaker_label}")
                                
                                # If not found in result, check alternative
                                elif hasattr(alternative, 'speaker') and alternative.speaker:
                                    speaker_label = alternative.speaker
                                    logger.debug(f"Found speaker in alternative: {speaker_label}")
                                
                                # If still not found, check items for speaker information
                                elif hasattr(alternative, 'items') and alternative.items:
                                    logger.debug(f"Checking {len(alternative.items)} items for speaker info")
                                    speaker_counts = {}
                                    for i, item in enumerate(alternative.items):
                                        # Debug: Log item structure
                                        if i == 0:  # Only log first item to avoid spam
                                            logger.debug(f"Item attributes: {[attr for attr in dir(item) if not attr.startswith('_')]}")
                                        
                                        # Try different attribute names for speaker
                                        label = None
                                        if hasattr(item, 'speaker') and item.speaker:
                                            label = item.speaker
                                        elif hasattr(item, 'speaker_label') and item.speaker_label:
                                            label = item.speaker_label
                                        elif hasattr(item, 'content') and hasattr(item, 'speaker_id'):
                                            label = getattr(item, 'speaker_id', None)
                                        
                                        if label:
                                            speaker_counts[label] = speaker_counts.get(label, 0) + 1
                                    
                                    # Use the most frequent speaker label
                                    if speaker_counts:
                                        speaker_label = max(speaker_counts, key=speaker_counts.get)
                                        logger.debug(f"Found speaker in items: {speaker_label} (counts: {speaker_counts})")
                                
                                # If no speaker found, use simple time-based speaker estimation
                                if not speaker_label:
                                    logger.debug("No speaker information found, will use time-based estimation")
                                
                                logger.info("Transcribe result: %s (partial: %s, speaker: %s)", 
                                          transcript, result.is_partial, speaker_label)
                                
                                self.callback({
                                    "transcript": transcript.strip(),
                                    "is_partial": result.is_partial,
                                    "speaker_label": speaker_label,
                                    "start_time": getattr(result, 'start_time', None),
                                    "end_time": getattr(result, 'end_time', None),
                                    "result_id": getattr(result, 'result_id', None),
                                })
                except Exception as e:
                    logger.error("Error handling transcript event: %s", e)
        
        handler = MyEventHandler(stream.output_stream, on_transcript)
        
        # Process audio and results concurrently
        try:
            await asyncio.gather(
                self._write_audio_chunks(stream, audio_generator()),
                handler.handle_events()
            )
        except Exception as e:
            logger.error("Transcribe streaming error: %s", e)
            raise
        finally:
            logger.info("Transcribe streaming completed")
    
    async def _write_audio_chunks(self, stream, audio_generator):
        """Write audio chunks to the stream."""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            chunk_count = 0
            async for chunk in audio_generator:
                await stream.input_stream.send_audio_event(audio_chunk=chunk)
                chunk_count += 1
                if chunk_count % 50 == 0:
                    logger.debug("Sent %d audio chunks to Transcribe", chunk_count)
            
            logger.info("Finished sending audio chunks (%d total)", chunk_count)
            await stream.input_stream.end_stream()
        except Exception as e:
            logger.error("Error writing audio chunks: %s", e)
            raise

    def _stream_with_amazon_transcribe_no_speaker(
        self,
        audio_queue: queue.Queue[bytes | None],
        on_transcript: Callable[[dict[str, Any]], None],
        language_code: str = "ja-JP",
    ) -> None:
        """Use amazon-transcribe streaming client without speaker identification."""
        import asyncio
        import logging
        import threading
        
        logger = logging.getLogger(__name__)
        logger.info("Starting amazon-transcribe streaming without speaker identification...")
        
        def run_async_transcribe():
            try:
                asyncio.run(self._async_transcribe_stream_no_speaker(audio_queue, on_transcript, language_code))
            except Exception as e:
                logger.error("Async transcribe failed: %s", e)
                raise
        
        # Run in a separate thread to avoid blocking
        thread = threading.Thread(target=run_async_transcribe, daemon=True)
        thread.start()
        thread.join()  # Wait for completion

    async def _async_transcribe_stream_no_speaker(
        self,
        audio_queue: queue.Queue[bytes | None],
        on_transcript: Callable[[dict[str, Any]], None],
        language_code: str = "ja-JP",
    ):
        """Async transcribe streaming implementation without speaker identification."""
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler
        from amazon_transcribe.model import TranscriptEvent
        from amazon_transcribe.auth import StaticCredentialResolver
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Get AWS credentials
        session = get_session()
        credentials = session.get_credentials()
        if not credentials:
            raise RuntimeError("AWS credentials not found")
            
        frozen = credentials.get_frozen_credentials()
        
        # Create credential resolver
        credential_resolver = StaticCredentialResolver(
            access_key_id=frozen.access_key,
            secret_access_key=frozen.secret_key,
            session_token=frozen.token,
        )
        
        # Create client
        client = TranscribeStreamingClient(
            region=get_settings().aws_region,
            credential_resolver=credential_resolver,
        )
        
        # Create audio stream generator
        async def audio_generator():
            import asyncio
            import time
            last_chunk_time = time.time()
            silence_chunk = b'\x00' * 320  # 10ms of silence at 16kHz
            
            while True:
                try:
                    # Use asyncio to avoid blocking
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, audio_queue.get, True, 0.5  # 0.5 second timeout
                    )
                    if chunk is None:
                        logger.info("Audio stream ended")
                        break
                    last_chunk_time = time.time()
                    yield chunk
                except:
                    # Timeout or queue empty, send silence to prevent timeout
                    current_time = time.time()
                    if current_time - last_chunk_time > 10:  # Send silence every 10 seconds
                        logger.debug("Sending silence chunk to prevent timeout")
                        yield silence_chunk
                        last_chunk_time = current_time
                    await asyncio.sleep(0.1)
        
        # Start streaming (no speaker identification)
        logger.info("Starting transcribe stream (no speaker identification)...")
        stream = await client.start_stream_transcription(
            language_code=language_code,
            media_sample_rate_hz=16000,
            media_encoding="pcm",
        )
        
        # Create event handler
        class MyEventHandler(TranscriptResultStreamHandler):
            def __init__(self, output_stream, callback):
                super().__init__(output_stream)
                self.callback = callback
                
            async def handle_transcript_event(self, transcript_event: TranscriptEvent):
                try:
                    results = transcript_event.transcript.results
                    for result in results:
                        if result.alternatives:
                            alternative = result.alternatives[0]
                            transcript = alternative.transcript
                            if transcript and transcript.strip():
                                logger.info("Transcribe result: %s (partial: %s, no speaker)", 
                                          transcript, result.is_partial)
                                
                                self.callback({
                                    "transcript": transcript.strip(),
                                    "is_partial": result.is_partial,
                                    "speaker_label": None,  # No speaker identification
                                    "start_time": getattr(result, 'start_time', None),
                                    "end_time": getattr(result, 'end_time', None),
                                    "result_id": getattr(result, 'result_id', None),
                                })
                except Exception as e:
                    logger.error("Error handling transcript event: %s", e)
        
        handler = MyEventHandler(stream.output_stream, on_transcript)
        
        # Process audio and results concurrently
        try:
            await asyncio.gather(
                self._write_audio_chunks(stream, audio_generator()),
                handler.handle_events()
            )
        except Exception as e:
            logger.error("Transcribe streaming error: %s", e)
            raise
        finally:
            logger.info("Transcribe streaming completed")

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
        
        # Check if streaming is supported
        try:
            # Test if the method exists and is callable
            if not hasattr(self.client, "start_stream_transcription"):
                raise RuntimeError("start_stream_transcription method not available")
            
            # Try to call the method with a test to see if it's properly supported
            logger.info("Testing boto3 transcribe streaming capability...")
            
            response = self.client.start_stream_transcription(
                LanguageCode=language_code,
                MediaEncoding="pcm",
                MediaSampleRateHertz=16000,
                AudioStream=_QueueAudioStream(audio_queue),
                Settings={
                    'ShowSpeakerLabels': True,
                    'MaxSpeakerLabels': 5
                }
            )
            
            stream = response.get("TranscriptResultStream")
            if not stream:
                raise RuntimeError("no transcript stream returned")

            logger.info("boto3 transcribe streaming started successfully")
            
            for event in stream:
                transcript_event = event.get("TranscriptEvent")
                if not transcript_event:
                    continue
                results = transcript_event.get("Transcript", {}).get("Results", [])
                for result in results:
                    alternatives = result.get("Alternatives") or []
                    if not alternatives:
                        continue
                    
                    alternative = alternatives[0]
                    text = (alternative.get("Transcript") or "").strip()
                    if not text:
                        continue
                    
                    # Extract speaker information from items
                    speaker_label = None
                    speaker_counts = {}
                    items = alternative.get("Items", [])
                    
                    # Debug: Log items structure for first result
                    if len(items) > 0:
                        first_item = items[0]
                        logger.debug(f"First item structure: {list(first_item.keys())}")
                        if "SpeakerLabel" in first_item:
                            logger.debug(f"SpeakerLabel found: {first_item['SpeakerLabel']}")
                    
                    for item in items:
                        # Try different keys for speaker label
                        label = item.get("SpeakerLabel") or item.get("Speaker") or item.get("speaker_label")
                        if label:
                            speaker_counts[label] = speaker_counts.get(label, 0) + 1
                    
                    # Use the most frequent speaker label
                    if speaker_counts:
                        speaker_label = max(speaker_counts, key=speaker_counts.get)
                        logger.debug(f"Speaker counts: {speaker_counts}, selected: {speaker_label}")
                    else:
                        logger.debug("No speaker labels found in items")
                    
                    logger.info("boto3 transcribe result: %s (partial: %s, speaker: %s)", 
                              text, result.get("IsPartial", False), speaker_label)
                    
                    payload = {
                        "transcript": text,
                        "is_partial": result.get("IsPartial", False),
                        "speaker_label": speaker_label,
                        "start_time": result.get("StartTime"),
                        "end_time": result.get("EndTime"),
                        "result_id": result.get("ResultId"),
                    }
                    on_transcript(payload)
                    
        except Exception as e:
            logger.error("boto3 transcribe streaming failed: %s", e)
            # Re-raise with more specific error message
            if "not supported" in str(e).lower() or "not available" in str(e).lower():
                raise RuntimeError(f"boto3 transcribe streaming not supported: {e}")
            else:
                raise RuntimeError(f"boto3 transcribe error: {e}")

    def _silence_chunks(self, seconds: int = 2, chunk_size: int = 3200) -> Iterator[bytes]:
        total_chunks = max(1, (seconds * 16000) // chunk_size)
        silence = b"\x00" * chunk_size
        for _ in range(total_chunks):
            yield silence
