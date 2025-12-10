from __future__ import annotations

import asyncio
# audioop replacement for Python 3.13+
try:
    import audioop
except ImportError:
    # audioop was removed in Python 3.13, provide minimal replacement
    class AudioopReplacement:
        @staticmethod
        def lin2lin(fragment, width, newwidth):
            # Simple conversion between sample widths
            import struct
            if width == newwidth:
                return fragment
            if width == 1 and newwidth == 2:
                # 8-bit to 16-bit
                return b''.join(struct.pack('<h', (b - 128) * 256) for b in fragment)
            elif width == 2 and newwidth == 1:
                # 16-bit to 8-bit
                return bytes((struct.unpack('<h', fragment[i:i+2])[0] // 256 + 128) & 0xff 
                           for i in range(0, len(fragment), 2))
            return fragment
        
        @staticmethod
        def tomono(fragment, width, lfactor, rfactor):
            # Convert stereo to mono
            import struct
            if width == 2:
                samples = struct.unpack(f'<{len(fragment)//2}h', fragment)
                mono_samples = []
                for i in range(0, len(samples), 2):
                    if i + 1 < len(samples):
                        mono = int(samples[i] * lfactor + samples[i+1] * rfactor)
                        mono_samples.append(max(-32768, min(32767, mono)))
                    else:
                        mono_samples.append(samples[i])
                return struct.pack(f'<{len(mono_samples)}h', *mono_samples)
            return fragment
        
        @staticmethod
        def ratecv(fragment, width, nchannels, inrate, outrate, state):
            # Simple rate conversion (just return as-is for now)
            return fragment, state
    
    audioop = AudioopReplacement()
import io
import json
import re
import uuid
import wave
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amazon_transcribe.auth import StaticCredentialResolver
from amazon_transcribe.client import TranscribeStreamingClient

from backend.config import get_settings
from backend.services.bedrock_utils import classify_transcript_segments, summarize_transcript, _guess_category
from backend.services.comprehend_utils import analyze_sentiment
from backend.services.s3_storage import S3Storage
from backend.utils.auth_aws import get_session
from backend.utils.time_utils import now_iso


@dataclass
class PocJob:
    job_id: str
    agenda_text: str
    audio_filename: str
    created_at: str = field(default_factory=now_iso)
    status: str = "processing"
    transcripts: list[dict[str, Any]] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    speaker_labels: dict[str, str] = field(default_factory=dict)
    next_speaker_index: int = 1
    next_entry_index: int = 1
    pending_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    processed_result_ids: set[str] = field(default_factory=set)
    classified_segments: list[dict[str, Any]] = field(default_factory=list)
    # リアルタイム分析用の新しいフィールド
    accumulated_text: str = ""  # 蓄積されたテキスト
    accumulated_count: int = 0  # 蓄積文字数
    last_bedrock_time: float = 0  # 最後にBedrock送信した時刻
    current_speaker: str = ""  # 現在の話者
    threshold_chars: int = 30  # 暫定判定の文字数閾値（50→30に短縮）
    min_interval_seconds: int = 3  # 最小送信間隔（5→3秒に短縮）


class POCController:
    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = storage_dir or Path(__file__).resolve().parents[1] / "data" / "poc"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, PocJob] = {}
        self.settings = get_settings()
        self.logger = logging.getLogger(__name__)
        self.archive_storage = S3Storage(bucket="meetingpolice-test")

#文字起こしジョブの開始
    async def start_transcription(self, agenda_text: str, audio_filename: str, audio_bytes: bytes) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = PocJob(job_id=job_id, agenda_text=agenda_text, audio_filename=audio_filename)
        self.jobs[job_id] = job

        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "agenda.txt").write_text(agenda_text, encoding="utf-8")
        (job_dir / "audio.bin").write_bytes(audio_bytes)

        asyncio.create_task(self._process_audio(job, audio_bytes))
        return job_id

    def get_job(self, job_id: str) -> PocJob | None:
        return self.jobs.get(job_id)

    def get_job_payload(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "agenda_text": job.agenda_text,
            "audio_filename": job.audio_filename,
            "created_at": job.created_at,
            "transcripts": job.transcripts,
            "classified_segments": job.classified_segments,
        }

    async def analyze_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if not job.transcripts:
            raise ValueError("Transcription not ready yet")

        transcript_text = "\n".join(f"{item['speaker']}: {item['text']}" for item in job.transcripts)
        summary = summarize_transcript(job_id, transcript_text)
        sentiment = analyze_sentiment(transcript_text[:4000])

        guidance = [
            "Use the summarized transcript as input for Bedrock to draft meeting minutes or action items.",
            "Send the combined agenda text and transcript text to Comprehend for sentiment or entity detection.",
            "Persist agenda + transcript pairs so Bedrock can learn how discussions follow agenda items.",
        ]

        return {
            "job_id": job.job_id,
            "agenda_text": job.agenda_text,
            "summary": summary,
            "sentiment": sentiment,
            "transcript_sample": job.transcripts[:5],
            "guidance": guidance,
        }
#会議の文字起こし結果を自動で分類する.各発言が「質問」「報告」「提案」などのどれに当てはまるかをAI（Bedrock）に判定させる
    async def classify_job(self, job_id: str, refresh: bool = False) -> list[dict[str, Any]]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if not job.transcripts:
            raise ValueError("Transcription not ready yet")
        if job.classified_segments and not refresh:
            return job.classified_segments
        sentence_segments = self._sentence_segments(job)
        if not sentence_segments:
            raise ValueError("No transcript sentences available yet")
        classified = await asyncio.to_thread(classify_transcript_segments, sentence_segments, job.agenda_text)
        if not classified:
            raise RuntimeError("Bedrock classification returned no data")
        job.classified_segments = classified
        await job.queue.put({"type": "classification", "payload": classified})
        return classified
#最終結果が出たら分析開始する
async def classify_realtime(self, job_id: str, text: str, speaker: str, index: int) -> dict[str, Any]:
    """リアルタイムで1つの発言を簡易分析（改善版：文字数ベース）"""
    job = self.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    
    # ステップ1: キーワードベースの簡易分類（即座に返す）
    category_quick = _guess_category(text)
    alignment_quick = self._calculate_alignment(text, job.agenda_text)
    
    result_quick = {
        "index": index,
        "text": text,
        "speaker": speaker,
        "category": category_quick,
        "alignment": alignment_quick,
        "method": "keyword",  # キーワードベース
        "is_final": False  # まだ確定じゃない
    }
    
    # すぐにクライアントに通知
    await job.queue.put({"type": "realtime_classification", "payload": result_quick})
    
    # ステップ2: 文字数ベースの暫定判定ロジック
    await self._handle_accumulated_analysis(job, text, speaker, index)
    
    return result_quick

async def _handle_accumulated_analysis(self, job: PocJob, text: str, speaker: str, index: int) -> None:
    """文字数ベースの蓄積分析処理"""
    import time
    
    current_time = time.time()
    
    # 話者が変わったら蓄積をリセット
    if job.current_speaker and job.current_speaker != speaker:
        if job.accumulated_text.strip():
            # 前の話者の最終確定判定
            await self._send_final_bedrock_analysis(job, job.accumulated_text, job.current_speaker)
        job.accumulated_text = ""
        job.accumulated_count = 0
    
    # 現在の話者を更新
    job.current_speaker = speaker
    
    # テキストを蓄積
    job.accumulated_text += text + " "
    job.accumulated_count += len(text)
    
    # 暫定判定の条件チェック
    chars_ok = job.accumulated_count >= job.threshold_chars
    time_ok = (current_time - job.last_bedrock_time) >= job.min_interval_seconds
    should_send_interim = chars_ok and time_ok
    
    self.logger.info(
        f"蓄積状況: job_id={job.job_id}, speaker={speaker}, "
        f"chars={job.accumulated_count}/{job.threshold_chars}, "
        f"time_since_last={current_time - job.last_bedrock_time:.1f}s/{job.min_interval_seconds}s, "
        f"should_send={should_send_interim}"
    )
    
    if should_send_interim:
        # 暫定判定を送信
        await self._send_interim_bedrock_analysis(job, job.accumulated_text, speaker, index)
        job.last_bedrock_time = current_time
        
        self.logger.info(
            f"🚀 暫定判定送信: job_id={job.job_id}, speaker={speaker}, "
            f"chars={job.accumulated_count}, text_preview={job.accumulated_text[:30]}..."
        )

async def _send_interim_bedrock_analysis(self, job: PocJob, accumulated_text: str, speaker: str, index: int) -> None:
    """暫定判定用のBedrock分析"""
    try:
        # 蓄積されたテキストでBedrock分析
        segment = {
            "index": index,
            "speaker": speaker,
            "text": accumulated_text.strip(),
            "context_before": "",
            "context_after": "",
        }
        
        classified = await asyncio.to_thread(
            classify_transcript_segments,
            [segment],
            job.agenda_text
        )
        
        if classified and len(classified) > 0:
            result = classified[0]
            category_ai = result.get("category", _guess_category(accumulated_text))
            alignment_ai = result.get("alignment", 0)
            
            result_interim = {
                "index": index,
                "text": accumulated_text.strip(),
                "speaker": speaker,
                "category": category_ai,
                "alignment": alignment_ai,
                "method": "bedrock_interim",  # 暫定AI分析
                "is_final": False,  # まだ暫定
                "accumulated_chars": job.accumulated_count
            }
            
            # 暫定結果をクライアントに通知
            await job.queue.put({"type": "realtime_classification", "action": "interim", "payload": result_interim})
            
            self.logger.info(f"暫定Bedrock分析完了: {speaker} - [{category_ai}] {alignment_ai}% ({job.accumulated_count}文字)")
    
    except Exception as e:
        self.logger.exception(f"暫定Bedrock分析失敗: {e}")

async def _send_final_bedrock_analysis(self, job: PocJob, final_text: str, speaker: str) -> None:
    """最終確定判定用のBedrock分析"""
    try:
        segment = {
            "index": 0,  # 最終判定なのでindexは重要でない
            "speaker": speaker,
            "text": final_text.strip(),
            "context_before": "",
            "context_after": "",
        }
        
        classified = await asyncio.to_thread(
            classify_transcript_segments,
            [segment],
            job.agenda_text
        )
        
        if classified and len(classified) > 0:
            result = classified[0]
            category_ai = result.get("category", _guess_category(final_text))
            alignment_ai = result.get("alignment", 0)
            
            result_final = {
                "text": final_text.strip(),
                "speaker": speaker,
                "category": category_ai,
                "alignment": alignment_ai,
                "method": "bedrock_final",  # 最終AI分析
                "is_final": True,  # 確定
                "total_chars": len(final_text)
            }
            
            # 最終結果をクライアントに通知
            await job.queue.put({"type": "realtime_classification", "action": "final", "payload": result_final})
            
            self.logger.info(f"最終Bedrock分析完了: {speaker} - [{category_ai}] {alignment_ai}% ({len(final_text)}文字)")
    
    except Exception as e:
        self.logger.exception(f"最終Bedrock分析失敗: {e}")

#過去の会議記録の一覧を取得する機能
    def list_archived_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        keys = [key for key in self.archive_storage.list_objects("poc/") if key.endswith(".json")]
        items: list[dict[str, Any]] = []
        for key in sorted(keys, reverse=True):
            try:
                data = self._load_archived_job(key)
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            items.append(
                {
                    "job_id": data.get("job_id"),
                    "completed_at": data.get("completed_at"),
                    "archive_name": data.get("archive_name") or "",
                    "agenda_preview": (data.get("agenda_text") or "")[:80],
                    "transcript_count": len(data.get("transcripts") or []),
                }
            )
            if len(items) >= limit:
                break
        return items

    def get_archived_job(self, job_id: str) -> dict[str, Any]:
        data = self._load_archived_job(self._archive_key(job_id))
        if not data:
            raise KeyError(job_id)
        return data

    async def classify_archived_job(self, job_id: str) -> list[dict[str, Any]]:
        data = self.get_archived_job(job_id)
        transcripts = data.get("transcripts") or []
        agenda_text = data.get("agenda_text") or ""
        sentence_segments = _sentence_segments_from_transcripts(transcripts)
        if not sentence_segments:
            raise ValueError("No transcript sentences available yet")
        classified = await asyncio.to_thread(classify_transcript_segments, sentence_segments, agenda_text)
        if not classified:
            raise RuntimeError("Bedrock classification returned no data")
        return classified

    async def _process_audio(self, job: PocJob, audio_bytes: bytes) -> None:
        try:
            pcm_bytes, sample_rate = self._prepare_pcm(audio_bytes)
            await self._run_transcribe_stream(job, pcm_bytes, sample_rate)
        except Exception:
            self.logger.exception("Transcribe streaming failed for job %s, fallback to mock data", job.job_id)
            job.transcripts.clear()
            await self._simulate_stream(job)
#AWS Transcribeが失敗したとき
    async def _simulate_stream(self, job: PocJob) -> None:
        script = self._build_script(job)
        job_dir = self._job_dir(job.job_id)
        transcript_path = job_dir / "transcripts.json"
        for idx, line in enumerate(script, start=1):
            payload = {
                "index": idx,
                "speaker": "Speaker A" if idx % 2 else "Speaker B",
                "raw_speaker": "spk_mock_a" if idx % 2 else "spk_mock_b",
                "result_id": f"mock-{idx}",
                "text": line,
                "timestamp": now_iso(),
            }
            job.transcripts.append(payload)
            job.next_entry_index = max(job.next_entry_index, idx + 1)
            await job.queue.put({"type": "transcript", "action": "append", "payload": payload})
            await asyncio.sleep(1.2)
        job.status = "completed"
        transcript_path.write_text(json.dumps(job.transcripts, ensure_ascii=False, indent=2), encoding="utf-8")
        self._persist_transcripts(job)
        await job.queue.put({"type": "complete"})

    def _build_script(self, job: PocJob) -> list[str]:
        agenda_lines = [
            line.strip(" -*•\t")
            for line in job.agenda_text.splitlines()
            if line.strip(" -*•\t")
        ]
        script: list[str] = []
        if agenda_lines:
            for line in agenda_lines:
                script.append(f"Agenda topic: {line}")
                script.append(f"Discussion: Confirming action items for '{line}'.")

        if not script:
            script.append(f"Processing uploaded audio file '{job.audio_filename}'")

        fallback_segments = max(3, min(10, len(job.audio_filename) // 2))
        for idx in range(fallback_segments):
            script.append(f"Speaker {chr(65 + idx % 2)} shares update part {idx + 1}.")

        return script[:12]

    def _job_dir(self, job_id: str) -> Path:
        return self.storage_dir / job_id
#音声ファイルをAWS Transcribeが理解できる形式に変換する処理
    def _prepare_pcm(self, audio_bytes: bytes) -> tuple[bytes, int]:
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
                sample_width = wav.getsampwidth()
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
                raw = wav.readframes(wav.getnframes())
        except wave.Error:
            # assume already PCM (e.g. raw upload)
            return audio_bytes, 16000

        target_width = 2
        if sample_width != target_width:
            raw = audioop.lin2lin(raw, sample_width, target_width)
            sample_width = target_width

        if channels != 1:
            raw = audioop.tomono(raw, sample_width, 0.5, 0.5)
            channels = 1

        target_rate = 16000
        if sample_rate != target_rate:
            raw, _ = audioop.ratecv(raw, sample_width, channels, sample_rate, target_rate, None)
            sample_rate = target_rate

        return raw, sample_rate

# AWS Transcribe Streamingを使ったリアルタイム音声認識
    async def _run_transcribe_stream(self, job: PocJob, pcm_bytes: bytes, sample_rate: int) -> None:
        session = get_session()
        credentials = session.get_credentials()
        if not credentials:
            raise RuntimeError("Unable to resolve AWS credentials for Transcribe streaming")
        frozen = credentials.get_frozen_credentials()
        credential_resolver = StaticCredentialResolver(
            frozen.access_key,
            frozen.secret_key,
            frozen.token,
        )
        client = TranscribeStreamingClient(
            region=self.settings.aws_region,
            credential_resolver=credential_resolver,
        )
        chunk_ms = 50
        chunk_bytes = max(1, int(sample_rate * 2 * chunk_ms / 1000))

        self.logger.info(
            "Starting Transcribe stream job_id=%s sample_rate=%s chunk_bytes=%s",
            job.job_id,
            sample_rate,
            chunk_bytes,
        )
        stream = await client.start_stream_transcription(
            language_code="ja-JP",
            media_encoding="pcm",
            media_sample_rate_hz=sample_rate,
            show_speaker_label=True,
            enable_partial_results_stabilization=True,
            partial_results_stability="medium",
        )

        async def send_audio():
            chunk_delay = chunk_ms / 1000
            for chunk in self._chunk_pcm(pcm_bytes, chunk_bytes):
                await stream.input_stream.send_audio_event(audio_chunk=chunk)
                await asyncio.sleep(chunk_delay)
            await stream.input_stream.end_stream()

        async def consume_results():
            async for event in stream.output_stream:
                transcript = getattr(event, "transcript", None)
                if not transcript:
                    continue
                for result in getattr(transcript, "results", []) or []:
                    result_id = getattr(result, "result_id", None)
                    if not result_id:
                        continue
                    is_partial = getattr(result, "is_partial", False)
                    if not is_partial and result_id in job.processed_result_ids:
                        continue
                    alternatives = getattr(result, "alternatives", []) or []
                    if not alternatives:
                        continue
                    alternative = alternatives[0]
                    text = (getattr(alternative, "transcript", "") or "").strip()
                    if not text:
                        continue
                    speaker_label, raw_label = self._speaker_from_items(job, alternative)
                    await self._handle_result(job, result_id, speaker_label, raw_label, text, not is_partial)
                    if not is_partial:
                        job.processed_result_ids.add(result_id)

        success = False
        try:
            await asyncio.gather(send_audio(), consume_results())
            success = True
        finally:
            await self._finalize_pending_results(job)
            # 最後に残った蓄積テキストがあれば最終分析
            if job.accumulated_text.strip() and job.current_speaker:
                await self._send_final_bedrock_analysis(job, job.accumulated_text, job.current_speaker)
            if success:
                job.status = "completed"
                self._persist_transcripts(job)
                await job.queue.put({"type": "complete"})
                self.logger.info("Transcribe stream completed job_id=%s total_segments=%s", job.job_id, len(job.transcripts))

    def _chunk_pcm(self, pcm_bytes: bytes, chunk_size: int):
        for idx in range(0, len(pcm_bytes), chunk_size):
            yield pcm_bytes[idx : idx + chunk_size]

    def _speaker_name(self, job: PocJob, raw_label: str | None) -> str:
        key = raw_label or "__unknown__"
        if key not in job.speaker_labels:
            label = f"Speaker {job.next_speaker_index}"
            job.speaker_labels[key] = label
            job.next_speaker_index += 1
        return job.speaker_labels[key]

    def _speaker_from_items(self, job: PocJob, alternative: Any) -> tuple[str, str]:
        counts: dict[str, int] = {}
        for item in getattr(alternative, "items", []) or []:
            label = getattr(item, "speaker", None)
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
        raw_label = max(counts, key=counts.get) if counts else None
        friendly = self._speaker_name(job, raw_label)
        return friendly, (raw_label or "spk_unk")

    async def _handle_result(self, job: PocJob, result_id: str, speaker_label: str, raw_label: str, text: str, is_final: bool) -> None:
        entry = job.pending_results.get(result_id)
        if not entry:
            entry = {
                "index": job.next_entry_index,
                "speaker": speaker_label,
                "raw_speaker": raw_label,
                "result_id": result_id,
                "text": text,
                "timestamp": now_iso(),
            }
            job.next_entry_index += 1
            job.pending_results[result_id] = entry
            await job.queue.put({"type": "transcript", "action": "append", "payload": self._public_payload(entry)})
        else:
            if entry["text"] == text and entry["speaker"] == speaker_label:
                if is_final:
                    await self._finalize_result(job, result_id)
                    # 最終結果が出たら、すぐに分析開始
                    asyncio.create_task(self.classify_realtime(job.job_id, text, speaker_label, entry["index"]))
                return
            entry["text"] = text
            entry["speaker"] = speaker_label
            entry["raw_speaker"] = raw_label
            await job.queue.put({"type": "transcript", "action": "update", "payload": self._public_payload(entry)})
        if is_final:
            await self._finalize_result(job, result_id)
            # 最終結果が出たら、すぐに分析開始
            asyncio.create_task(self.classify_realtime(job.job_id, text, speaker_label, entry["index"]))

    async def _finalize_result(self, job: PocJob, result_id: str) -> None:
        entry = job.pending_results.pop(result_id, None)
        if not entry:
            return
        payload = self._public_payload(entry)
        job.transcripts.append(payload)
        await job.queue.put({"type": "transcript", "action": "update", "payload": payload})

    async def _finalize_pending_results(self, job: PocJob) -> None:
        for result_id in list(job.pending_results.keys()):
            await self._finalize_result(job, result_id)

    def _public_payload(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "index": entry["index"],
            "speaker": entry["speaker"],
            "raw_speaker": entry.get("raw_speaker", entry["speaker"]),
            "result_id": entry.get("result_id"),
            "text": entry["text"],
            "timestamp": entry["timestamp"],
        }

    def _sentence_segments(self, job: PocJob) -> list[dict[str, Any]]:
        return _sentence_segments_from_transcripts(job.transcripts)

    def _persist_transcripts(self, job: PocJob) -> None:
        try:
            archive_name = self._suggest_archive_slug(job)
            payload = {
                "job_id": job.job_id,
                "agenda_text": job.agenda_text,
                "completed_at": now_iso(),
                "transcripts": job.transcripts,
                "archive_name": archive_name,
            }
            key = self._build_archive_key(job.job_id, archive_name)
            self.archive_storage.write_json(key, payload)
        except Exception:
            self.logger.exception("Failed to archive transcripts for job %s", job.job_id)

    def _load_archived_job(self, key: str) -> dict[str, Any]:
        raw = self.archive_storage.read_text(key)
        return json.loads(raw)

    def _archive_key(self, job_id: str) -> str:
        suffix = f"{job_id}.json"
        for key in self.archive_storage.list_objects("poc/"):
            if key.endswith(suffix):
                return key
        return f"poc/{job_id}.json"

    def _build_archive_key(self, job_id: str, archive_name: str | None) -> str:
        slug = archive_name or ""
        if slug:
            slug = slug[:40]
            return f"poc/{slug}-{job_id}.json"
        return f"poc/{job_id}.json"

    def _suggest_archive_slug(self, job: PocJob) -> str:
        source = job.agenda_text or ""
        if not source.strip():
            for transcript in job.transcripts:
                text = transcript.get("text", "")
                if text.strip():
                    source = text
                    break
        if not source.strip():
            return ""
        first_line = source.splitlines()[0].strip()
        cleaned = re.sub(r"[\s　]+", "-", first_line)
        cleaned = re.sub(r"[^0-9A-Za-zぁ-んァ-ヶ一-龠ー_-]", "", cleaned)
        cleaned = cleaned.strip("-_")
        return cleaned[:40]



    def _calculate_alignment(self, text: str, agenda_text: str) -> int:
        """発言とアジェンダの一致度を0-100で計算（キーワードベース）"""
        if not agenda_text or not agenda_text.strip():
            return 0  # アジェンダがなければ0%
        
        # アジェンダから重要なキーワードを抽出（名詞っぽい単語）
        agenda_keywords = set()
        for line in agenda_text.splitlines():
            line = line.strip(" -*•\t0123456789.。")  # 箇条書き記号や番号を除去
            if not line:
                continue
            # 2文字以上の単語を抽出（簡易的）
            words = [w for w in re.findall(r'[ぁ-んァ-ヶ一-龠ー]+', line) if len(w) >= 2]
            agenda_keywords.update(words)
        
        if not agenda_keywords:
            return 0
        
        # 発言に含まれるキーワードの数をカウント
        text_lower = text.lower()
        matched_count = sum(1 for keyword in agenda_keywords if keyword in text_lower)
        
        # 一致率を計算（0-100%）
        alignment = min(100, int((matched_count / len(agenda_keywords)) * 100))
        
        # ボーナス：完全一致するキーワードがあれば+20%
        if matched_count > 0:
            alignment = min(100, alignment + 20)
        
        return alignment


SENTENCE_RE = re.compile(r"[^。！？!?]+[。！？!?]?")


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    matches = SENTENCE_RE.findall(text)
    sentences = [match.strip() for match in matches if match.strip()]
    if not sentences and text.strip():
        sentences = [text.strip()]
    return sentences


def _sentence_segments_from_transcripts(transcripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    idx = 1
    for transcript in transcripts:
        speaker = transcript.get("speaker", "")
        sentences = _split_sentences(transcript.get("text", ""))
        for sentence in sentences:
            segments.append(
                {
                    "index": idx,
                    "speaker": speaker,
                    "text": sentence,
                    "context_before": "",
                    "context_after": "",
                }
            )
            idx += 1
    for i, segment in enumerate(segments):
        if i > 0:
            segment["context_before"] = segments[i - 1]["text"]
        if i + 1 < len(segments):
            segment["context_after"] = segments[i + 1]["text"]
    return segments
