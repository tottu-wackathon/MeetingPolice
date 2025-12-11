"""
警察出動機能のメイン管理クラス
SessionControllerから分離された警察出動関連の処理
"""

import asyncio
import logging
from typing import Dict, Any

from backend.services.lambda_client import LambdaClient
from backend.utils.time_utils import now_iso
from .police_dispatch_state import PoliceDispatchState
from .police_dispatch_filters import PoliceDispatchFilters

logger = logging.getLogger(__name__)


class PoliceDispatchManager:
    """警察出動の判定と実行を管理するメインクラス"""
    
    def __init__(self):
        self.logger = logger
        self.lambda_client = LambdaClient()
        self.state_manager = PoliceDispatchState()
        self.filters = PoliceDispatchFilters()
    
    async def check_and_trigger(
        self, 
        session_data: dict, 
        alignment_score: int, 
        text: str, 
        speaker: str, 
        category: str = None
    ) -> None:
        """
        警察出動の判定とトリガー実行
        
        Args:
            session_data: セッションデータ
            alignment_score: 一致度スコア（0-100）
            text: 発言内容
            speaker: 話者
            category: Bedrockで分類されたカテゴリ（オプション）
        """
        try:
            # フィルタリングチェック
            if self.filters.should_skip_police_dispatch_check(text, category):
                return
            
            meeting_id = session_data["meeting_id"]
            
            # 状態を初期化・取得
            state = self.state_manager.initialize_state(session_data, meeting_id)
            
            # 重複チェック
            if self.state_manager.is_duplicate_check(state, text, alignment_score):
                return
            
            self.logger.info(f"🚨 Police dispatch check: alignment={alignment_score}%, speaker={speaker}, text='{text[:50]}...'")
            
            # 警察出動トリガー: 一致度30%以下
            if alignment_score <= 30:
                self.logger.info(f"🚨 Alignment {alignment_score}% <= 30% - Triggering police dispatch check")
                await self._handle_police_dispatch_trigger(session_data, state, alignment_score, text, speaker, meeting_id)
            
            # 警察出動解除: 一致度50%以上
            elif alignment_score >= 50:
                await self._handle_police_dispatch_resolution(session_data, state, alignment_score, text, speaker, meeting_id)
            
            else:
                # 30% < alignment < 50% の場合は何もしない（現状維持）
                self.logger.info(f"🔍 Police dispatch check: alignment {alignment_score}% - no action needed")
        
        except Exception as e:
            self.logger.error(f"❌ Police dispatch check failed: {e}")
            self.logger.exception("Police dispatch check detailed error:")
    
    async def _handle_police_dispatch_trigger(
        self, 
        session_data: dict, 
        state: dict, 
        alignment_score: int, 
        text: str, 
        speaker: str, 
        meeting_id: str
    ) -> None:
        """警察出動のトリガー処理"""
        # 低一致度の開始時刻を記録
        self.state_manager.set_low_alignment_start(state, alignment_score)
        
        # トリガー判定
        should_trigger, reason = self.state_manager.should_trigger(state)
        self.logger.info(f"🔍 Police dispatch trigger check: {reason}, should_trigger={should_trigger}")
        
        if should_trigger:
            await self._execute_police_dispatch(session_data, state, alignment_score, text, speaker, meeting_id)
        else:
            self.logger.info(f"🚨 Police dispatch already active or too soon (last: {state['last_triggered_time']})")
    
    async def _handle_police_dispatch_resolution(
        self, 
        session_data: dict, 
        state: dict, 
        alignment_score: int, 
        text: str, 
        speaker: str, 
        meeting_id: str
    ) -> None:
        """警察出動の解除処理"""
        if state['is_active']:
            self.logger.info("🟢 POLICE DISPATCH RESOLVED!")
            
            # Lambda関数を呼び出し（LED消灯）
            meeting_data = self._create_meeting_data(meeting_id, speaker, alignment_score, text)
            asyncio.create_task(self._invoke_police_dispatch_off_async(meeting_data))
            
            # セッションキューに警察出動解除通知を送信
            await self._send_dispatch_notification(session_data, meeting_data, "dispatch_off")
            
            # 状態をリセット
            self.state_manager.deactivate(state)
            self.logger.info(f"🟢 Police dispatch resolved for meeting {meeting_id}")
        
        # 低一致度期間をリセット
        self.state_manager.clear_low_alignment_start(state)
    
    async def _execute_police_dispatch(
        self, 
        session_data: dict, 
        state: dict, 
        alignment_score: int, 
        text: str, 
        speaker: str, 
        meeting_id: str
    ) -> None:
        """警察出動を実行"""
        self.logger.info("🚨 POLICE DISPATCH TRIGGERED!")
        
        # Lambda関数を呼び出し（LED点灯 + 10秒後自動消灯）
        meeting_data = self._create_meeting_data(meeting_id, speaker, alignment_score, text)
        
        # バックグラウンドでLambda呼び出し
        self.logger.info(f"🚀 Creating Lambda task for police dispatch: {meeting_data}")
        try:
            task = asyncio.create_task(self._invoke_police_dispatch_async(meeting_data))
            self.logger.info(f"✅ Lambda task created successfully: {task}")
        except Exception as e:
            self.logger.error(f"❌ Failed to create Lambda task: {e}")
            self.logger.exception("Lambda task creation error:")
        
        # セッションキューに警察出動通知を送信
        await self._send_dispatch_notification(session_data, meeting_data, "dispatch_on")
        
        # 状態を更新
        self.state_manager.activate(state)
        self.logger.info(f"🚨 Police dispatch activated for meeting {meeting_id}")
    
    def _create_meeting_data(self, meeting_id: str, speaker: str, alignment_score: int, text: str) -> dict:
        """ミーティングデータを作成"""
        return {
            "meeting_id": meeting_id,
            "speaker": speaker,
            "alignment_score": alignment_score,
            "recent_transcript": text,
            "timestamp": now_iso()
        }
    
    async def _send_dispatch_notification(self, session_data: dict, meeting_data: dict, action: str) -> None:
        """セッションキューに通知を送信"""
        notification_type = "police_dispatch" if action == "dispatch_on" else "police_dispatch_off"
        
        await session_data["queue"].put({
            "type": notification_type,
            "payload": {
                **meeting_data,
                "action": action
            }
        })
    
    async def _invoke_police_dispatch_async(self, meeting_data: dict) -> None:
        """警察出動Lambda関数を非同期で呼び出し"""
        try:
            self.logger.info(f"🚀 Starting Lambda invocation for police dispatch: {meeting_data}")
            self.logger.info(f"🔧 Lambda client available: {self.lambda_client is not None}")
            result = await asyncio.to_thread(self.lambda_client.invoke_police_dispatch, meeting_data)
            self.logger.info(f"🚨 Police dispatch Lambda result: {result}")
        except Exception as e:
            self.logger.error(f"❌ Police dispatch Lambda failed: {e}")
            self.logger.exception("Police dispatch Lambda detailed error:")

    async def _invoke_police_dispatch_off_async(self, meeting_data: dict) -> None:
        """警察出動解除Lambda関数を非同期で呼び出し"""
        try:
            result = await asyncio.to_thread(self.lambda_client.invoke_police_dispatch_off, meeting_data)
            self.logger.info(f"🟢 Police dispatch OFF Lambda result: {result}")
        except Exception as e:
            self.logger.error(f"❌ Police dispatch OFF Lambda failed: {e}")