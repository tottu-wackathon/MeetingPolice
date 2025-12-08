from __future__ import annotations

import asyncio
import audioop
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
from backend.services.bedrock_utils import classify_transcript_segments, _guess_category
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
    pending_bedrock_tasks: set[asyncio.Task] = field(default_factory=set)


class POCController:
    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = storage_dir or Path(__file__).resolve().parents[1] / "data" / "poc"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, PocJob] = {}
        self.settings = get_settings()
        self.logger = logging.getLogger(__name__)
        self.archive_storage = S3Storage(bucket="meetingpolice-test")

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

    #最終結果が出たら分析開始する
    async def classify_realtime(self, job_id: str, text: str, speaker: str, index: int) -> dict[str, Any]:
        """リアルタイムで1つの発言を簡易分析（ハイブリッド方式）"""
        # 10文字未満の短い発言は分析しない
        text_stripped = text.strip()
        print(f"🔍 文字数チェック: '{text_stripped}' → len={len(text_stripped)}")
        if len(text_stripped) < 10:
            print(f"  ✋ 10文字未満のためスキップ！")
            return {}
        
        print(f"📊 リアルタイム分析開始: {speaker} - {text[:30]}...")
        self.logger.info(f"📊 リアルタイム分析開始: {speaker} - {text[:30]}...")
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        
        # メタ情報（議題、所要時間、発表者など）の発言はスキップ
        # 「Agenda topic:」で始まる発言は全てスキップ
        if text.startswith("Agenda topic:"):
            print(f"  → メタ情報のためスキップ: {text[:30]}...")
            return {}
        
        # 「Discussion:」の後に続く内容をチェック
        if text.startswith("Discussion: Confirming action items for"):
            # シングルクォートで囲まれた部分を抽出
            import re
            match = re.search(r"'([^']+)'", text)
            if match:
                content = match.group(1)
                # メタ情報キーワードをチェック
                meta_keywords = ["議題タイトル", "所要時間", "発表者", "分", "時間"]
                # 短い単語（10文字未満）で、メタ情報キーワードを含む場合はスキップ
                if len(content) < 10 or any(keyword in content for keyword in meta_keywords):
                    print(f"  → メタ情報のためスキップ: {text[:50]}...")
                    return {}
        
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
        
        # ステップ2: バックグラウンドでBedrockに送信（非同期）
        task = asyncio.create_task(self._classify_with_bedrock(job, text, speaker, index))
        job.pending_bedrock_tasks.add(task)
        task.add_done_callback(lambda t: job.pending_bedrock_tasks.discard(t))
        
        return result_quick

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



    async def _process_audio(self, job: PocJob, audio_bytes: bytes) -> None:
        try:
            pcm_bytes, sample_rate = self._prepare_pcm(audio_bytes)
            await self._run_transcribe_stream(job, pcm_bytes, sample_rate)
        except Exception:
            self.logger.exception("Transcribe streaming failed for job %s, fallback to mock data", job.job_id)
            job.transcripts.clear()
            await self._simulate_stream(job)

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
            # リアルタイム分析を実行
            asyncio.create_task(self.classify_realtime(job.job_id, line, payload["speaker"], idx))
            await asyncio.sleep(1.2)
        
        # 全てのBedrock分析タスクが完了するまで待つ
        print(f"⏳ Bedrock分析タスク待機中... 残り: {len(job.pending_bedrock_tasks)}件")
        while job.pending_bedrock_tasks:
            await asyncio.sleep(0.5)
            print(f"⏳ まだ待機中... 残り: {len(job.pending_bedrock_tasks)}件")
        print(f"✅ 全てのBedrock分析が完了しました！")
        
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
        
        # リアルな会議の発言を生成
        if agenda_lines:
            # メタ情報の行（議題タイトル、発表者、所要時間など）
            for line in agenda_lines:
                script.append(f"Agenda topic: {line}")
            
            # 実際の議論内容を追加
            script.append("現在の離脱率は約30%で、特にプロフィール登録画面で多く発生しています。")
            script.append("ユーザーテストの結果、入力項目が多すぎるという意見が多かったです。")
            script.append("入力項目を必須項目だけに絞ることを提案します。")
            script.append("それは良いアイデアですね。具体的にどの項目を残しますか？")
            script.append("メールアドレスとパスワードだけにして、他は後から入力できるようにします。")
            script.append("了解しました。その方向で実装を進めましょう。")
            script.append("実装期間はどのくらいを見込んでいますか？")
            script.append("2週間程度で完了できると思います。")
        
        if not script:
            script.append(f"Processing uploaded audio file '{job.audio_filename}'")
            script.append("Let's discuss the main topics for today's meeting.")
            script.append("I agree, we should focus on the key action items.")

        return script[:15]  # 最大15件

    def _job_dir(self, job_id: str) -> Path:
        return self.storage_dir / job_id

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

    def _split_long_text(self, text: str, max_length: int = 80, min_length: int = 25) -> list[str]:
        """長い文を句読点で分割する（短すぎる文は結合）"""
        if len(text) <= max_length:
            return [text]
        
        import re
        
        # 句読点で分割（句読点も含める）
        parts = re.split(r'(。|！|？)', text)
        
        # 句読点を前の文に結合
        sentences = []
        for i in range(0, len(parts), 2):
            sentence = parts[i]
            if i + 1 < len(parts):
                sentence += parts[i + 1]  # 句読点を追加
            if sentence.strip():
                sentences.append(sentence.strip())
        
        # 長い文は読点でさらに分割
        result = []
        for sentence in sentences:
            if len(sentence) <= max_length:
                result.append(sentence)
            else:
                # 読点で分割
                sub_parts = re.split(r'(、|,)', sentence)
                buffer = ""
                for i in range(0, len(sub_parts)):
                    part = sub_parts[i]
                    if len(buffer + part) <= max_length:
                        buffer += part
                    else:
                        if buffer.strip():
                            result.append(buffer.strip())
                        buffer = part
                if buffer.strip():
                    result.append(buffer.strip())
        
        # 短すぎる文を前の文と結合
        final_result = []
        for sentence in result:
            if final_result and len(sentence) < min_length:
                final_result[-1] += sentence
            else:
                final_result.append(sentence)
        
        return [s for s in final_result if s]

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
            # すでに表示した発話の話者ラベルは基本的に固定し、Transcribe の途中でラベルが揺れても変えない。
            # ただし「不明(spk_unk)」から「具体的な raw_label」に更新できる場合のみ、一度だけ生ラベルを保持する。
            current_raw = entry.get("raw_speaker", "spk_unk")
            if current_raw in {"spk_unk", "__unknown__"} and raw_label not in {"spk_unk", "__unknown__"}:
                entry["raw_speaker"] = raw_label

            if entry["text"] == text and entry["speaker"] == speaker_label:
                if is_final:
                    await self._finalize_result(job, result_id)
                    # 最終結果が出たら、長い文を分割して分析（全文を分析）
                    split_texts = self._split_long_text(text)
                    print(f"📝 元の文: {text}")
                    print(f"✂️ 分割結果: {split_texts}")
                    for i, split_text in enumerate(split_texts):
                        # 各分割文に一意のindexを割り当て
                        unique_index = entry["index"] * 1000 + i
                        asyncio.create_task(self.classify_realtime(job.job_id, split_text, speaker_label, unique_index))
                return
            entry["text"] = text
            await job.queue.put({"type": "transcript", "action": "update", "payload": self._public_payload(entry)})
        
        # 最終結果が出たら、必ず分析を実行（全文を分析）
        if is_final:
            await self._finalize_result(job, result_id)
            # 長い文を分割してリアルタイム分析を開始
            split_texts = self._split_long_text(entry["text"])
            print(f"📝 元の文: {entry['text']}")
            print(f"✂️ 分割結果: {split_texts}")
            for i, split_text in enumerate(split_texts):
                # 各分割文に一意のindexを割り当て（元のindex * 1000 + 分割番号）
                unique_index = entry["index"] * 1000 + i
                asyncio.create_task(self.classify_realtime(job.job_id, split_text, entry["speaker"], unique_index))

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
        
        # アジェンダから議題タイトルを抽出
        lines = source.splitlines()
        title_line = ""
        for i, line in enumerate(lines):
            # 「・議題タイトル」の次の行を取得
            if "議題タイトル" in line and i + 1 < len(lines):
                title_line = lines[i + 1].strip()
                break
        
        # 議題タイトルが見つからない場合は最初の行を使用
        if not title_line:
            title_line = lines[0].strip()
        
        cleaned = re.sub(r"[\s　]+", "-", title_line)
        cleaned = re.sub(r"[^0-9A-Za-zぁ-んァ-ヶ一-龠ー_-]", "", cleaned)
        cleaned = cleaned.strip("-_")
        return cleaned[:40]




    async def _classify_with_bedrock(self, job: PocJob, text: str, speaker: str, index: int) -> None:
        """Bedrockで高精度な分析を実行（バックグラウンド）"""
        print(f"🔍 Bedrock分析開始: {speaker} - {text[:30]}...")
        self.logger.info(f"🔍 Bedrock分析開始: {speaker} - {text[:30]}...")
        try:
            # 文脈を取得（前後の発言）
            context_before = ""
            context_after = ""
            for transcript in job.transcripts:
                if transcript.get("index") == index - 1:
                    context_before = transcript.get("text", "")
                elif transcript.get("index") == index + 1:
                    context_after = transcript.get("text", "")
            
            # Bedrockで分析
            segment = {
                "index": index,
                "speaker": speaker,
                "text": text,
                "context_before": context_before,
                "context_after": context_after,
            }
            
            # classify_transcript_segmentsを使って分析
            print(f"  → Bedrockに送信中... segment={segment}")
            print(f"  → agenda_text={job.agenda_text[:100]}...")
            classified = await asyncio.to_thread(
                classify_transcript_segments,
                [segment],
                job.agenda_text
            )
            print(f"  → Bedrockから応答受信: {classified}")
            print(f"  → classified type: {type(classified)}, len: {len(classified) if isinstance(classified, list) else 'N/A'}")
            
            if classified and len(classified) > 0:
                result = classified[0]
                category_ai = result.get("category", _guess_category(text))
                alignment_ai = result.get("alignment", 0)
                
                result_ai = {
                    "index": index,
                    "text": text,
                    "speaker": speaker,
                    "category": category_ai,
                    "alignment": alignment_ai,
                    "method": "bedrock",  # AI分析
                    "is_final": True  # 確定
                }
                
                # 更新をクライアントに通知
                await job.queue.put({"type": "realtime_classification", "action": "update", "payload": result_ai})
                
                print(f"✅ Bedrock分析完了: {speaker} - {text[:30]}... → [{category_ai}] {alignment_ai}%")
                self.logger.info(f"Bedrock分析完了: {speaker} - {text} → [{category_ai}] {alignment_ai}%")
            else:
                # Bedrockが失敗したら、キーワードベースの結果を「確定」として送る
                print(f"⚠️ Bedrockから結果なし、キーワードベースを確定として送信")
                category_fallback = _guess_category(text)
                alignment_fallback = self._calculate_alignment(text, job.agenda_text)
                
                result_fallback = {
                    "index": index,
                    "text": text,
                    "speaker": speaker,
                    "category": category_fallback,
                    "alignment": alignment_fallback,
                    "method": "keyword",  # キーワードベース
                    "is_final": True  # 確定（Bedrockが失敗したので）
                }
                
                await job.queue.put({"type": "realtime_classification", "action": "update", "payload": result_fallback})
                print(f"✅ キーワード分析確定: {speaker} - {text[:30]}... → [{category_fallback}] {alignment_fallback}%")
        
        except Exception as e:
            print(f"❌ Bedrock分析失敗: {e}")
            print(f"詳細: {type(e).__name__}: {str(e)}")
            self.logger.error(f"❌ Bedrock分析失敗: {e}")
            self.logger.exception("詳細なエラー:")
            # エラーが出てもキーワードベースの結果は残るので問題なし

    def _calculate_alignment(self, text: str, agenda_text: str) -> int:
        """発言とアジェンダの一致度を0-100で計算（キーワードベース）"""
        if not agenda_text or not agenda_text.strip():
            return 50  # アジェンダがなければデフォルト50%
        
        # メタ情報（議題、所要時間、発表者など）の発言は一致度を計算しない
        meta_keywords = ["議題", "タイトル", "所要時間", "発表者", "Agenda topic:", "分", "時間"]
        if any(keyword in text for keyword in meta_keywords):
            return 50  # メタ情報はデフォルト50%
        
        # アジェンダから重要なキーワードを抽出（メタ情報を除外）
        agenda_keywords = set()
        skip_keywords = {"議題", "タイトル", "所要時間", "発表者", "検討事項", "目的", "背景"}
        
        for line in agenda_text.splitlines():
            line = line.strip(" -*•\t0123456789.。")  # 箇条書き記号や番号を除去
            if not line:
                continue
            # メタ情報の行をスキップ
            if any(skip in line for skip in skip_keywords):
                continue
            # 2文字以上の単語を抽出（簡易的）
            words = [w for w in re.findall(r'[ぁ-んァ-ヶ一-龠ー]+', line) if len(w) >= 2]
            # スキップキーワードを除外
            words = [w for w in words if w not in skip_keywords]
            agenda_keywords.update(words)
        
        if not agenda_keywords:
            return 50  # キーワードがなければデフォルト50%
        
        # 発言に含まれるキーワードの数をカウント
        text_lower = text.lower()
        matched_count = sum(1 for keyword in agenda_keywords if keyword in text_lower)
        
        # 一致率を計算（0-100%）
        if matched_count == 0:
            return 30  # 全く一致しなくても最低30%
        
        # マッチ率に基づいて計算（より寛容に）
        match_ratio = matched_count / len(agenda_keywords)
        alignment = min(100, int(30 + (match_ratio * 70)))  # 30%〜100%の範囲
        
        return alignment
