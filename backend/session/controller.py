from __future__ import annotations

import asyncio
from contextlib import suppress
import queue
import threading
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState



from backend.services.vonage_client import VonageClient
from backend.services.transcribe_stream import TranscribeStream
from backend.services.comprehend_utils import analyze_sentiment
from backend.services.bedrock_utils import classify_transcript_segments, _guess_category
from backend.services.repository import MeetingRepository
from backend.services.lambda_client import LambdaClient
from backend.utils.auth_aws import get_session
from backend.utils.time_utils import now_iso
from backend.config import get_settings


class SessionController:
    def __init__(self, repository: MeetingRepository | None = None):
        self.vonage = VonageClient()
        self.transcribe = TranscribeStream()
        self.repository = repository or MeetingRepository()
        self.lambda_client = LambdaClient()
        self.logger = logging.getLogger(__name__)
        self.settings = get_settings()
        self._classification_index = 1
        # Session用のデータ構造
        self.session_data = {}  # meeting_id -> session data

    def _build_session_payload(self, meeting, session_id: str, token: str) -> dict:
        return {
            "meeting_id": meeting.meeting_id,
            "title": meeting.title,
            "status": meeting.status,
            "session_id": session_id,
            "token": token,
            "api_key": self.vonage.settings.vonage_api_key,
        }

    def create_meeting(self, title: str, scheduled_for: str | None = None) -> dict:
        if not title or not title.strip():
            raise ValueError("title is required")

        meeting = self.repository.create_meeting(title=title.strip(), scheduled_for=scheduled_for)
        self.logger.info("Creating meeting meeting_id=%s title=%s", meeting.meeting_id, meeting.title)
        session = self.vonage.create_session(meeting.meeting_id)
        session_id = session["session_id"]
        meeting = self.repository.update_meeting(
            meeting.meeting_id, session_id=session_id, status="live"
        )

        token = self.vonage.generate_token(session_id=session_id)
        self.logger.info("Vonage credentials issued meeting_id=%s session_id=%s", meeting.meeting_id, session_id)
        return self._build_session_payload(meeting, session_id, token)

    def create_session_token(self, meeting_id: str) -> dict:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            self.logger.warning("Join requested for missing meeting_id=%s", meeting_id)
            raise ValueError("Meeting not found")

        session_id = meeting.session_id
        if not session_id:
            session = self.vonage.create_session(meeting_id)
            session_id = session["session_id"]
            meeting = self.repository.update_meeting(meeting_id, session_id=session_id, status="live")

        token = self.vonage.generate_token(session_id=session_id)
        self.logger.info("Join token issued meeting_id=%s session_id=%s", meeting_id, session_id)
        return self._build_session_payload(meeting, session_id, token)

    def validate_meeting(self, meeting_id: str) -> dict:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            self.logger.warning("Validation failed missing meeting_id=%s", meeting_id)
            raise ValueError("Meeting not found")
        self.logger.info("Validation success meeting_id=%s", meeting_id)
        return {"meeting_id": meeting.meeting_id, "status": meeting.status, "title": meeting.title}

    async def stream_transcripts(self, websocket: WebSocket, meeting_id: str) -> None:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            await websocket.close(code=4404)
            return

        await websocket.accept()
        
        # Initialize session data
        session_data = {
            "meeting_id": meeting_id,
            "transcripts": [],
            "queue": asyncio.Queue(),
            "speaker_labels": {"spk_unk": "判別中..."},
            "next_speaker_index": 1,
            "next_entry_index": 1,
            "pending_results": {},
            "processed_result_ids": set(),
            "pending_bedrock_tasks": set(),
            "agenda_text": meeting.title or "",  # Use meeting title as agenda
        }
        self.session_data[meeting_id] = session_data

        # Start real-time transcription
        try:
            await self._start_realtime_transcription(session_data, websocket)
        except Exception as e:
            self.logger.error("Transcription failed for meeting_id=%s: %s", meeting_id, e)
            await websocket.send_json({"error": f"Transcription failed: {e}"})
        finally:
            # Cleanup
            if meeting_id in self.session_data:
                del self.session_data[meeting_id]

    async def _start_realtime_transcription(self, session_data: dict, websocket: WebSocket) -> None:
        """Start real-time transcription using simple queue-based approach."""
        meeting_id = session_data["meeting_id"]
        
        try:
            # Use the existing TranscribeStream service with queue
            import queue
            import threading
            
            audio_queue = queue.Queue()
            
            def on_transcript_result(result):
                """Callback for transcription results."""
                try:
                    transcript = result.get("transcript", "").strip()
                    if not transcript:
                        return
                        
                    is_partial = result.get("is_partial", False)
                    speaker_label = result.get("speaker_label")
                    result_id = result.get("result_id", f"result_{len(session_data['pending_results'])}")
                    
                    # Get friendly speaker name
                    # If no speaker label, use time-based estimation
                    if not speaker_label:
                        speaker_label = self._estimate_speaker_by_time(session_data, transcript)
                    
                    raw_speaker = self._normalize_raw_label(speaker_label)
                    friendly_speaker = self._speaker_name(session_data, raw_speaker)
                    
                    # Log speaker information for debugging
                    self.logger.debug(f"Processing transcript:")
                    self.logger.debug(f"  - Raw speaker_label: {speaker_label}")
                    self.logger.debug(f"  - Normalized raw_speaker: {raw_speaker}")
                    self.logger.debug(f"  - Friendly speaker: {friendly_speaker}")
                    self.logger.debug(f"  - Is partial: {is_partial}")
                    self.logger.debug(f"  - Text: {transcript[:50]}...")
                    
                    # Handle result with speaker continuity
                    asyncio.create_task(self._handle_result(
                        session_data, result_id, friendly_speaker, raw_speaker, 
                        transcript, not is_partial, websocket
                    ))
                        
                except Exception as e:
                    self.logger.error("Error processing transcript result: %s", e)
            
            # Start transcription in background thread
            def run_transcription():
                try:
                    self.transcribe.stream_audio(audio_queue, on_transcript_result)
                except Exception as e:
                    self.logger.error("Transcription thread error: %s", e)
            
            transcription_thread = threading.Thread(target=run_transcription, daemon=True)
            transcription_thread.start()
            
            # Handle WebSocket audio data
            await self._handle_websocket_audio_simple(websocket, audio_queue, session_data)
            
        except Exception as e:
            self.logger.error("Real-time transcription failed: %s", e)
            # Fallback to mock transcription
            await self._start_mock_transcription(session_data, websocket)

    async def _handle_websocket_audio_simple(self, websocket: WebSocket, audio_queue, session_data: dict) -> None:
        """Handle audio data from WebSocket and put into queue."""
        audio_count = 0
        
        try:
            while True:
                message = await websocket.receive()
                
                if message.get("type") == "websocket.disconnect":
                    break
                
                data = message.get("bytes")
                if data and len(data) > 0:
                    # Put audio data into queue for transcription
                    audio_queue.put(data)
                    audio_count += 1
                    
                    if audio_count % 100 == 0:
                        self.logger.debug(f"Queued {audio_count} audio chunks")
                        
                elif message.get("text"):
                    if message["text"] == "close":
                        break
                        
        except WebSocketDisconnect:
            self.logger.info("WebSocket disconnected during audio handling")
        except Exception as e:
            self.logger.error(f"Error handling WebSocket audio: {e}")
        finally:
            # Signal end of audio stream
            audio_queue.put(None)
            self.logger.info(f"Audio handling ended, processed {audio_count} chunks")



    async def _start_mock_transcription(self, session_data: dict, websocket: WebSocket) -> None:
        """Fallback mock transcription for testing."""
        meeting_id = session_data["meeting_id"]
        self.logger.info("Starting mock transcription for meeting_id=%s", meeting_id)
        
        mock_phrases = [
            "こんにちは、テストです",
            "音声認識のテストを行っています", 
            "マイクの音声が正常に送信されています",
            "文字起こし機能が動作しています",
            "リアルタイム分析のテストです"
        ]
        
        phrase_index = 0
        
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                    
                data = message.get("bytes")
                if data:
                    # Simulate transcription every 3 seconds
                    await asyncio.sleep(3)
                    phrase = mock_phrases[phrase_index % len(mock_phrases)]
                    
                    # Send transcript
                    await websocket.send_json({
                        "type": "transcript",
                        "meeting_id": meeting_id,
                        "timestamp": now_iso(),
                        "transcript": phrase,
                        "sentiment": "NEUTRAL",
                        "is_partial": False,
                    })
                    
                    # Send classification
                    await self._classify_and_send_realtime(websocket, meeting_id, phrase, "Speaker 1", phrase_index + 1)
                    phrase_index += 1
                    
        except WebSocketDisconnect:
            pass

    def _speaker_from_items(self, session_data: dict, alternative: Any) -> tuple[str, str]:
        """Extract speaker information from transcribe alternative."""
        counts: dict[str, int] = {}
        for item in getattr(alternative, "items", []) or []:
            label = getattr(item, "speaker", None)
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
            
        raw_label = max(counts, key=counts.get) if counts else None
        normalized = self._normalize_raw_label(raw_label)
        friendly = self._speaker_name(session_data, normalized)
        return friendly, normalized

    def _normalize_raw_label(self, raw_label: str | None) -> str:
        """Normalize speaker label."""
        unknown_tokens = {"", "spk_unk", "__unknown__", "unknown", "unk", None}
        if raw_label in unknown_tokens:
            return "spk_unk"
        
        # Convert to string and clean up
        key_str = str(raw_label).strip() if raw_label is not None else ""
        
        # Handle common AWS Transcribe speaker label formats
        if key_str.startswith("spk_"):
            return key_str  # Keep AWS format as-is (e.g., "spk_0", "spk_1")
        elif key_str.isdigit():
            return f"spk_{key_str}"  # Convert numeric to AWS format
        elif key_str:
            return key_str  # Keep other formats as-is
        else:
            return "spk_unk"

    def _speaker_name(self, session_data: dict, raw_label: str | None) -> str:
        """Get friendly speaker name."""
        key = self._normalize_raw_label(raw_label)
        
        # Handle unknown speaker
        if key == "spk_unk":
            session_data["speaker_labels"].setdefault("spk_unk", "判別中...")
            return session_data["speaker_labels"]["spk_unk"]
        
        # Create new speaker label if not exists
        if key not in session_data["speaker_labels"]:
            # Extract speaker number from AWS format if possible
            if key.startswith("spk_") and key[4:].isdigit():
                speaker_num = int(key[4:]) + 1  # Convert 0-based to 1-based
                label = f"Speaker {speaker_num}"
            else:
                label = f"Speaker {session_data['next_speaker_index']}"
                session_data['next_speaker_index'] += 1
            
            session_data["speaker_labels"][key] = label
            self.logger.info(f"👤 New speaker registered: {key} → {label}")
            
        return session_data["speaker_labels"][key]

    async def _handle_result(self, session_data: dict, result_id: str, speaker_label: str, raw_label: str, text: str, is_final: bool, websocket: WebSocket) -> None:
        """Handle transcription result with speaker continuity."""
        
        # Initialize current_transcript if not exists
        if "current_transcript" not in session_data:
            session_data["current_transcript"] = None
        
        current_transcript = session_data["current_transcript"]
        
        # Check if this is a continuation of the same speaker
        # Consider both raw_label and normalized speaker comparison
        is_same_speaker = (
            current_transcript is not None and 
            not current_transcript.get("is_finalized", False) and
            (
                # Same raw speaker label (most reliable)
                (raw_label and current_transcript["raw_speaker"] == raw_label) or
                # Same normalized speaker (fallback)
                (not raw_label and current_transcript["speaker"] == speaker_label)
            )
        )
        
        # Log speaker change detection for debugging
        if current_transcript:
            self.logger.debug(f"Speaker continuity check:")
            self.logger.debug(f"  - Current raw_speaker: {current_transcript.get('raw_speaker')}")
            self.logger.debug(f"  - New raw_label: {raw_label}")
            self.logger.debug(f"  - Current speaker: {current_transcript.get('speaker')}")
            self.logger.debug(f"  - New speaker_label: {speaker_label}")
            self.logger.debug(f"  - Is same speaker: {is_same_speaker}")
            self.logger.debug(f"  - Is finalized: {current_transcript.get('is_finalized', False)}")
        else:
            self.logger.debug(f"No current transcript, creating new entry for speaker: {speaker_label} (raw: {raw_label})")
        
        if is_same_speaker:
            # Update existing transcript for the same speaker
            current_transcript["text"] = text
            current_transcript["result_id"] = result_id
            current_transcript["is_partial"] = not is_final
            
            # Send updated transcript (same entry, updated text)
            await websocket.send_json({
                "type": "transcript",
                "action": "update",  # Indicate this is an update
                "meeting_id": session_data["meeting_id"],
                "timestamp": current_transcript["timestamp"],
                "transcript": text,
                "sentiment": analyze_sentiment(text).get("Sentiment", "NEUTRAL"),
                "is_partial": not is_final,
                "speaker": speaker_label,
                "index": current_transcript["index"],
            })
            
        else:
            # Speaker has changed - finalize previous transcript if exists
            if current_transcript and not current_transcript.get("is_finalized", False):
                self.logger.info(f"🔄 Speaker changed: {current_transcript.get('speaker')} → {speaker_label}")
                self.logger.info(f"   Raw labels: {current_transcript.get('raw_speaker')} → {raw_label}")
                await self._finalize_current_transcript(session_data, websocket)
            
            # Create new transcript entry for new speaker or first transcript
            new_entry = {
                "index": session_data["next_entry_index"],
                "speaker": speaker_label,
                "raw_speaker": raw_label,
                "result_id": result_id,
                "text": text,
                "timestamp": now_iso(),
                "is_partial": not is_final,
                "is_finalized": False,
            }
            
            session_data["next_entry_index"] += 1
            session_data["current_transcript"] = new_entry
            
            self.logger.info(f"📝 New transcript entry created for {speaker_label} (index: {new_entry['index']})")
            
            # Send new transcript
            await websocket.send_json({
                "type": "transcript",
                "action": "new",  # Indicate this is a new entry
                "meeting_id": session_data["meeting_id"],
                "timestamp": new_entry["timestamp"],
                "transcript": text,
                "sentiment": analyze_sentiment(text).get("Sentiment", "NEUTRAL"),
                "is_partial": not is_final,
                "speaker": speaker_label,
                "index": new_entry["index"],
            })
        
        # If this is a final result, finalize the transcript
        if is_final:
            await self._finalize_current_transcript(session_data, websocket)

    async def _finalize_current_transcript(self, session_data: dict, websocket: WebSocket) -> None:
        """Finalize the current transcript and trigger classification."""
        current_transcript = session_data.get("current_transcript")
        if not current_transcript or current_transcript.get("is_finalized", False):
            return
        
        # Mark as finalized
        current_transcript["is_finalized"] = True
        
        # Add to transcripts history
        session_data["transcripts"].append(current_transcript.copy())
        
        # Send finalized transcript
        await websocket.send_json({
            "type": "transcript",
            "action": "finalize",
            "meeting_id": session_data["meeting_id"],
            "timestamp": current_transcript["timestamp"],
            "transcript": current_transcript["text"],
            "sentiment": analyze_sentiment(current_transcript["text"]).get("Sentiment", "NEUTRAL"),
            "is_partial": False,
            "speaker": current_transcript["speaker"],
            "index": current_transcript["index"],
        })
        
        # Trigger classification for final result
        await self._classify_and_send_realtime(
            websocket, 
            session_data["meeting_id"], 
            current_transcript["text"], 
            current_transcript["speaker"], 
            current_transcript["index"]
        )



    async def _classify_and_send_realtime(self, websocket: WebSocket, meeting_id: str, text: str, speaker: str, index: int) -> None:
        """Perform real-time classification like poc_satomin."""
        # Skip short texts
        text_stripped = text.strip()
        if len(text_stripped) < 10:
            return
            
        session_data = self.session_data.get(meeting_id)
        if not session_data:
            return
            
        # Skip meta information
        if text.startswith("Agenda topic:") or text.startswith("Discussion: Confirming action items for"):
            return
            
        # Step 1: Quick keyword-based classification
        category_quick = _guess_category(text)
        alignment_quick = self._calculate_alignment(text, session_data["agenda_text"])
        
        result_quick = {
            "index": index,
            "text": text,
            "speaker": speaker,
            "category": category_quick,
            "alignment": alignment_quick,
            "method": "keyword",
            "is_final": False
        }
        
        # Send quick result
        await websocket.send_json({
            "type": "realtime_classification",
            "payload": result_quick
        })
        
        # Check for police dispatch trigger (low alignment)
        await self._check_police_dispatch_trigger(session_data, alignment_quick, text, speaker, websocket)
        
        # Step 2: Background Bedrock analysis
        task = asyncio.create_task(self._classify_with_bedrock(session_data, text, speaker, index, websocket))
        session_data["pending_bedrock_tasks"].add(task)
        task.add_done_callback(lambda t: session_data["pending_bedrock_tasks"].discard(t))

    async def _classify_with_bedrock(self, session_data: dict, text: str, speaker: str, index: int, websocket: WebSocket) -> None:
        """Bedrock classification in background."""
        try:
            # Get context
            context_before = ""
            context_after = ""
            for transcript in session_data["transcripts"]:
                if transcript.get("index") == index - 1:
                    context_before = transcript.get("text", "")
                elif transcript.get("index") == index + 1:
                    context_after = transcript.get("text", "")
            
            # Bedrock analysis
            segment = {
                "index": index,
                "speaker": speaker,
                "text": text,
                "context_before": context_before,
                "context_after": context_after,
            }
            
            classified = await asyncio.to_thread(
                classify_transcript_segments,
                [segment],
                session_data["agenda_text"]
            )
            
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
                    "method": "bedrock",
                    "is_final": True
                }
                
                # Send AI result
                await websocket.send_json({
                    "type": "realtime_classification",
                    "action": "update",
                    "payload": result_ai
                })
                
                # Check for police dispatch trigger with AI result
                await self._check_police_dispatch_trigger(session_data, alignment_ai, text, speaker, websocket)
                
                self.logger.info(f"Bedrock分析完了: {speaker} - {text} → [{category_ai}] {alignment_ai}%")
            else:
                # Fallback to keyword
                category_fallback = _guess_category(text)
                alignment_fallback = self._calculate_alignment(text, session_data["agenda_text"])
                
                result_fallback = {
                    "index": index,
                    "text": text,
                    "speaker": speaker,
                    "category": category_fallback,
                    "alignment": alignment_fallback,
                    "method": "keyword",
                    "is_final": True
                }
                
                await websocket.send_json({
                    "type": "realtime_classification",
                    "action": "update", 
                    "payload": result_fallback
                })
        
        except Exception as e:
            self.logger.error(f"Bedrock分析失敗: {e}")

    def _calculate_alignment(self, text: str, agenda_text: str) -> int:
        """Calculate alignment with agenda."""
        if not agenda_text or not agenda_text.strip():
            return 50
            
        # Skip meta information
        meta_keywords = ["議題", "タイトル", "所要時間", "発表者", "検討事項", "目的", "背景"]
        if any(keyword in text for keyword in meta_keywords):
            return 50
            
        # Extract keywords from agenda
        agenda_keywords = set()
        skip_keywords = {"議題", "タイトル", "所要時間", "発表者", "検討事項", "目的", "背景"}
        
        for line in agenda_text.splitlines():
            line = line.strip(" -*•\t0123456789.。")
            if not line:
                continue
            if any(skip in line for skip in skip_keywords):
                continue
            import re
            words = [w for w in re.findall(r'[ぁ-んァ-ヶ一-龠ー]+', line) if len(w) >= 2]
            words = [w for w in words if w not in skip_keywords]
            agenda_keywords.update(words)
        
        if not agenda_keywords:
            return 50
            
        # Count matches
        text_lower = text.lower()
        matched_count = sum(1 for keyword in agenda_keywords if keyword in text_lower)
        
        if matched_count == 0:
            return 30
            
        match_ratio = matched_count / len(agenda_keywords)
        alignment = min(100, int(30 + (match_ratio * 70)))
        
        return alignment

    async def _check_police_dispatch_trigger(self, session_data: dict, alignment_score: int, text: str, speaker: str, websocket: WebSocket) -> None:
        """
        警察出動のトリガーをチェックし、必要に応じてLambda関数を呼び出す
        
        Args:
            session_data: セッションデータ
            alignment_score: アライメントスコア
            text: 発言内容
            speaker: 発言者
            websocket: WebSocketコネクション
        """
        meeting_id = session_data["meeting_id"]
        
        # 警察出動の閾値設定
        POLICE_DISPATCH_THRESHOLD = 20  # アライメントスコアが20%以下で警察出動
        LOW_ALIGNMENT_THRESHOLD = 30    # 低アライメントの閾値
        
        # セッションデータに警告履歴を初期化
        if "alert_history" not in session_data:
            session_data["alert_history"] = []
        if "low_alignment_count" not in session_data:
            session_data["low_alignment_count"] = 0
        if "police_dispatched" not in session_data:
            session_data["police_dispatched"] = False
        
        # 低アライメントの発言をカウント
        if alignment_score <= LOW_ALIGNMENT_THRESHOLD:
            session_data["low_alignment_count"] += 1
            
            # 警告履歴に追加
            alert_entry = {
                "timestamp": now_iso(),
                "alignment_score": alignment_score,
                "text": text,
                "speaker": speaker,
                "alert_level": "WARNING" if alignment_score > POLICE_DISPATCH_THRESHOLD else "CRITICAL"
            }
            session_data["alert_history"].append(alert_entry)
        
        # 警察出動の条件チェック
        should_dispatch = (
            alignment_score <= POLICE_DISPATCH_THRESHOLD and 
            not session_data["police_dispatched"] and
            session_data["low_alignment_count"] >= 3  # 3回以上の低アライメント発言
        )
        
        if should_dispatch:
            self.logger.warning("🚨 警察出動トリガー発動！")
            self.logger.warning(f"  - Meeting ID: {meeting_id}")
            self.logger.warning(f"  - Alignment Score: {alignment_score}%")
            self.logger.warning(f"  - Low Alignment Count: {session_data['low_alignment_count']}")
            self.logger.warning(f"  - Speaker: {speaker}")
            self.logger.warning(f"  - Text: {text}")
            
            # 警察出動フラグを設定
            session_data["police_dispatched"] = True
            
            # Lambda関数呼び出し用のデータを準備
            meeting_data = {
                "meeting_id": meeting_id,
                "meeting_title": session_data.get("agenda_text", "Unknown Meeting"),
                "participant_count": len(session_data.get("speaker_labels", {})),
                "alert_level": "CRITICAL",
                "alert_reason": f"Alignment score dropped to {alignment_score}% (threshold: {POLICE_DISPATCH_THRESHOLD}%)",
                "timestamp": now_iso(),
                "duration_minutes": self._calculate_meeting_duration(session_data),
                "alignment_score": alignment_score,
                "recent_transcript": text,
                "speaker": speaker,
                "low_alignment_count": session_data["low_alignment_count"],
                "alert_history": session_data["alert_history"][-5:]  # 直近5件の警告履歴
            }
            
            # Lambda関数を非同期で呼び出し
            try:
                # 呼び出し前のコンテキストログ
                self.logger.info("🚨 SESSION CONTROLLER - Initiating Police Dispatch Lambda Call")
                self.logger.info(f"📋 Meeting Context:")
                self.logger.info(f"  - Meeting ID: {meeting_id}")
                self.logger.info(f"  - Trigger Speaker: {speaker}")
                self.logger.info(f"  - Alignment Score: {alignment_score}%")
                self.logger.info(f"  - Low Alignment Count: {session_data['low_alignment_count']}")
                self.logger.info(f"  - Trigger Text: {text[:100]}...")
                self.logger.info(f"  - Meeting Duration: {meeting_data['duration_minutes']} minutes")
                
                dispatch_result = await asyncio.to_thread(
                    self.lambda_client.invoke_police_dispatch,
                    meeting_data
                )
                
                # 成功ログ
                self.logger.info("✅ SESSION CONTROLLER - Police Dispatch Lambda Call Completed")
                self.logger.info(f"📊 Result Summary:")
                self.logger.info(f"  - Status Code: {dispatch_result.get('statusCode')}")
                self.logger.info(f"  - Dispatch ID: {dispatch_result.get('dispatchId')}")
                self.logger.info(f"  - LED Status: {dispatch_result.get('led_status')}")
                self.logger.info(f"  - Execution Time: {dispatch_result.get('execution_time_ms')}ms")
                self.logger.info(f"  - Message: {dispatch_result.get('message')}")
                
                # WebSocketで警察出動通知を送信
                await websocket.send_json({
                    "type": "police_dispatch",
                    "meeting_id": meeting_id,
                    "timestamp": now_iso(),
                    "alert_level": "CRITICAL",
                    "alignment_score": alignment_score,
                    "message": "🚨 警察出動が要請されました！会議の進行を確認してください。",
                    "dispatch_id": dispatch_result.get("dispatchId"),
                    "lambda_status": dispatch_result.get("statusCode"),
                    "execution_time_ms": dispatch_result.get("execution_time_ms"),
                    "details": {
                        "trigger_text": text,
                        "trigger_speaker": speaker,
                        "low_alignment_count": session_data["low_alignment_count"],
                        "threshold": POLICE_DISPATCH_THRESHOLD
                    }
                })
                
            except Exception as e:
                # エラーログ
                self.logger.error("❌ SESSION CONTROLLER - Police Dispatch Lambda Call Failed")
                self.logger.error(f"📋 Error Context:")
                self.logger.error(f"  - Meeting ID: {meeting_id}")
                self.logger.error(f"  - Trigger Speaker: {speaker}")
                self.logger.error(f"  - Alignment Score: {alignment_score}%")
                self.logger.error(f"  - Exception: {str(e)}")
                self.logger.exception("Full exception details:")
                
                # エラーでもWebSocketで通知
                await websocket.send_json({
                    "type": "police_dispatch",
                    "meeting_id": meeting_id,
                    "timestamp": now_iso(),
                    "alert_level": "CRITICAL",
                    "alignment_score": alignment_score,
                    "message": "🚨 警察出動が要請されましたが、通知システムでエラーが発生しました。",
                    "error": str(e),
                    "details": {
                        "trigger_text": text,
                        "trigger_speaker": speaker,
                        "low_alignment_count": session_data["low_alignment_count"],
                        "threshold": POLICE_DISPATCH_THRESHOLD
                    }
                })
        
        # 警察出動解除の条件チェック（アライメントスコアが改善された場合）
        POLICE_DISPATCH_OFF_THRESHOLD = 50  # アライメントスコアが50%以上で警察出動解除
        should_dispatch_off = (
            alignment_score >= POLICE_DISPATCH_OFF_THRESHOLD and 
            session_data["police_dispatched"]  # 現在警察出動中の場合のみ
        )
        
        if should_dispatch_off:
            self.logger.info("🟢 警察出動解除トリガー発動！")
            self.logger.info(f"  - Meeting ID: {meeting_id}")
            self.logger.info(f"  - Alignment Score: {alignment_score}%")
            self.logger.info(f"  - Speaker: {speaker}")
            self.logger.info(f"  - Text: {text}")
            
            # 警察出動フラグを解除
            session_data["police_dispatched"] = False
            session_data["low_alignment_count"] = 0  # カウントもリセット
            
            # Lambda関数呼び出し用のデータを準備
            meeting_data = {
                "meeting_id": meeting_id,
                "meeting_title": session_data.get("agenda_text", "Unknown Meeting"),
                "timestamp": now_iso(),
                "alignment_score": alignment_score,
                "recent_transcript": text,
                "speaker": speaker,
            }
            
            # Lambda関数を非同期で呼び出し（LED消灯）
            try:
                # 呼び出し前のコンテキストログ
                self.logger.info("🟢 SESSION CONTROLLER - Initiating Police Dispatch OFF Lambda Call")
                self.logger.info(f"📋 Meeting Context:")
                self.logger.info(f"  - Meeting ID: {meeting_id}")
                self.logger.info(f"  - Recovery Speaker: {speaker}")
                self.logger.info(f"  - Improved Alignment Score: {alignment_score}%")
                self.logger.info(f"  - Recovery Text: {text[:100]}...")
                self.logger.info(f"  - OFF Threshold: {POLICE_DISPATCH_OFF_THRESHOLD}%")
                
                dispatch_off_result = await asyncio.to_thread(
                    self.lambda_client.invoke_police_dispatch_off,
                    meeting_data
                )
                
                # 成功ログ
                self.logger.info("✅ SESSION CONTROLLER - Police Dispatch OFF Lambda Call Completed")
                self.logger.info(f"📊 Result Summary:")
                self.logger.info(f"  - Status Code: {dispatch_off_result.get('statusCode')}")
                self.logger.info(f"  - Dispatch ID: {dispatch_off_result.get('dispatchId')}")
                self.logger.info(f"  - LED Status: {dispatch_off_result.get('led_status')}")
                self.logger.info(f"  - Execution Time: {dispatch_off_result.get('execution_time_ms')}ms")
                self.logger.info(f"  - Message: {dispatch_off_result.get('message')}")
                
                # WebSocketで警察出動解除通知を送信
                await websocket.send_json({
                    "type": "police_dispatch_off",
                    "meeting_id": meeting_id,
                    "timestamp": now_iso(),
                    "alert_level": "INFO",
                    "alignment_score": alignment_score,
                    "message": "🟢 警察出動が解除されました。会議が正常に進行しています。",
                    "dispatch_id": dispatch_off_result.get("dispatchId"),
                    "lambda_status": dispatch_off_result.get("statusCode"),
                    "execution_time_ms": dispatch_off_result.get("execution_time_ms"),
                    "led_status": "OFF",
                    "details": {
                        "trigger_text": text,
                        "trigger_speaker": speaker,
                        "threshold": POLICE_DISPATCH_OFF_THRESHOLD
                    }
                })
                
            except Exception as e:
                # エラーログ
                self.logger.error("❌ SESSION CONTROLLER - Police Dispatch OFF Lambda Call Failed")
                self.logger.error(f"📋 Error Context:")
                self.logger.error(f"  - Meeting ID: {meeting_id}")
                self.logger.error(f"  - Recovery Speaker: {speaker}")
                self.logger.error(f"  - Alignment Score: {alignment_score}%")
                self.logger.error(f"  - Exception: {str(e)}")
                self.logger.exception("Full exception details:")
                
                # エラーでもWebSocketで通知
                await websocket.send_json({
                    "type": "police_dispatch_off",
                    "meeting_id": meeting_id,
                    "timestamp": now_iso(),
                    "alert_level": "INFO",
                    "alignment_score": alignment_score,
                    "message": "🟢 警察出動解除が要請されましたが、システムでエラーが発生しました。",
                    "error": str(e),
                    "led_status": "ERROR",
                    "details": {
                        "trigger_text": text,
                        "trigger_speaker": speaker,
                        "threshold": POLICE_DISPATCH_OFF_THRESHOLD
                    }
                })
        
        # 警告レベルの通知（警察出動には至らないが注意が必要）
        elif alignment_score <= LOW_ALIGNMENT_THRESHOLD and session_data["low_alignment_count"] % 2 == 0:
            await websocket.send_json({
                "type": "alignment_warning",
                "meeting_id": meeting_id,
                "timestamp": now_iso(),
                "alert_level": "WARNING",
                "alignment_score": alignment_score,
                "message": f"⚠️ 議題から逸脱した発言が続いています（{session_data['low_alignment_count']}回目）",
                "details": {
                    "trigger_text": text,
                    "trigger_speaker": speaker,
                    "low_alignment_count": session_data["low_alignment_count"],
                    "threshold": LOW_ALIGNMENT_THRESHOLD
                }
            })

    def _calculate_meeting_duration(self, session_data: dict) -> int:
        """
        会議の継続時間を計算（分単位）
        
        Args:
            session_data: セッションデータ
            
        Returns:
            会議の継続時間（分）
        """
        if not session_data.get("transcripts"):
            return 0
            
        try:
            from datetime import datetime
            
            # 最初と最後の発言のタイムスタンプを取得
            first_transcript = session_data["transcripts"][0]
            last_transcript = session_data["transcripts"][-1]
            
            first_time = datetime.fromisoformat(first_transcript["timestamp"].replace("Z", "+00:00"))
            last_time = datetime.fromisoformat(last_transcript["timestamp"].replace("Z", "+00:00"))
            
            duration = (last_time - first_time).total_seconds() / 60
            return max(1, int(duration))  # 最低1分
            
        except Exception as e:
            self.logger.error(f"会議時間計算エラー: {e}")
            return 1

    def _estimate_speaker_by_time(self, session_data: dict, transcript: str) -> str:
        """
        時間ベースで話者を推定する（話者識別がない場合のフォールバック）
        
        Args:
            session_data: セッションデータ
            transcript: 発言内容
            
        Returns:
            推定された話者ラベル
        """
        import time
        
        # 話者推定用の状態を初期化
        if "speaker_estimation" not in session_data:
            session_data["speaker_estimation"] = {
                "last_speaker": "spk_0",
                "last_speech_time": time.time(),
                "silence_threshold": 2.0,  # 2秒以上の沈黙で話者変更と推定
                "speaker_count": 1
            }
        
        estimation = session_data["speaker_estimation"]
        current_time = time.time()
        
        # 前回の発言から一定時間経過している場合は話者変更と推定
        time_since_last = current_time - estimation["last_speech_time"]
        
        if time_since_last > estimation["silence_threshold"]:
            # 話者を切り替え
            if estimation["last_speaker"] == "spk_0":
                estimation["last_speaker"] = "spk_1"
            else:
                estimation["last_speaker"] = "spk_0"
            
            self.logger.debug(f"Time-based speaker change: silence for {time_since_last:.1f}s, switching to {estimation['last_speaker']}")
        
        # 最後の発言時刻を更新
        estimation["last_speech_time"] = current_time
        
        return estimation["last_speaker"]


