from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from backend.services.vonage_client import VonageClient
from backend.services.repository import MeetingRepository
from backend.services.bedrock_utils import classify_transcript_segments
from backend.utils.time_utils import now_iso
from backend.config import get_settings

# 新しいモジュラーコンポーネント
from backend.session.speaker_manager import SpeakerManager
from backend.session.police_dispatch import PoliceDispatchManager
from backend.session.analysis_handler import AnalysisHandler
from backend.session.transcription_handler import TranscriptionHandler


class SessionController:
    def __init__(self, repository: MeetingRepository | None = None):
        self.vonage = VonageClient()
        self.repository = repository or MeetingRepository()
        self.logger = logging.getLogger(__name__)
        self.settings = get_settings()
        
        # モジュラーコンポーネント
        self.speaker_manager = SpeakerManager()
        self.police_dispatch = PoliceDispatchManager()
        self.analysis_handler = AnalysisHandler()
        self.transcription_handler = TranscriptionHandler()
        
        # Session用のデータ構造
        self.session_data = {}  # meeting_id -> session data

    def _build_session_payload(self, meeting, session_id: str, token: str) -> dict:
        payload = {
            "meeting_id": meeting.meeting_id,
            "title": meeting.title,
            "status": meeting.status,
            "session_id": session_id,
            "token": token,
            "api_key": self.vonage.settings.vonage_api_key,
        }
        self.logger.info("📦 Session payload built: meeting_id=%s, session_id=%s, has_token=%s, has_api_key=%s", 
                         payload["meeting_id"], payload["session_id"][:20] + "...", 
                         bool(payload["token"]), bool(payload["api_key"]))
        return payload

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

    def set_meeting_agenda(self, meeting_id: str, agenda_text: str) -> dict:
        """ミーティングにアジェンダを設定する"""
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            self.logger.warning("Agenda setting failed missing meeting_id=%s", meeting_id)
            raise ValueError("Meeting not found")
        
        # セッションデータが既に存在する場合はアジェンダを更新
        if meeting_id in self.session_data:
            self.session_data[meeting_id]["agenda_text"] = agenda_text
            self.logger.info("Updated agenda for active session meeting_id=%s", meeting_id)
        
        # 今後のセッション用にアジェンダを保存（簡易実装）
        if not hasattr(self, '_meeting_agendas'):
            self._meeting_agendas = {}
        self._meeting_agendas[meeting_id] = agenda_text
        
        self.logger.info("Agenda set for meeting_id=%s, length=%d chars", meeting_id, len(agenda_text))
        return {
            "meeting_id": meeting_id,
            "agenda_length": len(agenda_text),
            "agenda_preview": agenda_text[:100] + "..." if len(agenda_text) > 100 else agenda_text
        }

    async def stream_transcripts(self, websocket: WebSocket, meeting_id: str) -> None:
        meeting = self.repository.get_meeting(meeting_id)
        if not meeting:
            await websocket.close(code=4404)
            return

        await websocket.accept()
        
        # アジェンダテキストを取得
        agenda_text = ""
        if hasattr(self, '_meeting_agendas') and meeting_id in self._meeting_agendas:
            agenda_text = self._meeting_agendas[meeting_id]
            self.logger.info("アップロードされたアジェンダを使用 meeting_id=%s", meeting_id)
        else:
            agenda_text = meeting.title or ""
            self.logger.info("会議タイトルをアジェンダとして使用 meeting_id=%s", meeting_id)
        
        # セッションデータを初期化（poc_satomin準拠）
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
            "agenda_text": agenda_text,
            "session_start_time": time.time(),  # 警察出動用
        }
        self.session_data[meeting_id] = session_data

        # 音声認識結果のコールバック関数
        async def on_transcript_callback(result):
            await self.transcription_handler.handle_transcript_result(
                session_data, result, self.speaker_manager, self.analysis_handler
            )

        try:
            # バックグラウンドで音声認識を開始
            transcription_task = asyncio.create_task(
                self.transcription_handler.start_realtime_transcription(
                    session_data, websocket, on_transcript_callback
                )
            )
            
            # キューメッセージを処理（poc_satomin準拠のWebSocket処理）
            queue_task = asyncio.create_task(
                self._process_queue_messages(session_data, websocket)
            )
            
            # いずれかのタスクが完了するまで待機
            done, pending = await asyncio.wait(
                [transcription_task, queue_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 残りのタスクを安全にキャンセル
            for task in pending:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        self.logger.warning(f"タスククリーンアップエラー: {e}")
                
        except Exception as e:
            self.logger.error("音声認識失敗 meeting_id=%s: %s", meeting_id, e)
            await websocket.send_json({"error": f"音声認識失敗: {e}"})
        finally:
            # 全てのBedrockタスクの完了を待機（poc_satomin準拠）
            if session_data["pending_bedrock_tasks"]:
                self.logger.info(f"{len(session_data['pending_bedrock_tasks'])} Bedrockタスクの完了を待機中...")
                for task in list(session_data["pending_bedrock_tasks"]):
                    try:
                        if not task.done():
                            await task
                    except Exception as e:
                        self.logger.warning(f"クリーンアップ中のBedrockタスク失敗: {e}")
                session_data["pending_bedrock_tasks"].clear()
            
            # クリーンアップ
            if meeting_id in self.session_data:
                del self.session_data[meeting_id]

    async def _process_queue_messages(self, session_data: dict, websocket: WebSocket) -> None:
        """キューメッセージを処理（poc_satomin WebSocketハンドラー準拠）"""
        try:
            while True:
                message = await session_data["queue"].get()
                await websocket.send_json(message)
                if message.get("type") == "complete":
                    break
        except Exception as e:
            self.logger.error(f"キュー処理エラー: {e}")

    # 後方互換性のためのレガシーメソッド（モジュラーコンポーネントに移行済み）
    # これらのメソッドは将来削除予定
    
    async def _classify_realtime_hybrid(self, session_data: dict, text: str, speaker: str, index: int) -> None:
        """レガシー: analysis_handlerに移行済み"""
        await self.analysis_handler.classify_and_send_realtime(session_data, text, speaker, index, force_bedrock=True)
    
    async def _check_police_dispatch_trigger(self, session_data: dict, alignment_score: int, text: str, speaker: str, websocket: WebSocket | None) -> None:
        """レガシー: police_dispatchに移行済み"""
        await self.police_dispatch.check_and_trigger(session_data, alignment_score, text, speaker)