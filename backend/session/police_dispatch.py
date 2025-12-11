"""
警察出動機能
SessionControllerから分離された警察出動関連の処理
"""

import asyncio
import logging
import time
from typing import Dict, Any

from backend.services.lambda_client import LambdaClient
from backend.services.bedrock_utils import _guess_category
from backend.utils.time_utils import now_iso

logger = logging.getLogger(__name__)


class PoliceDispatchManager:
    """警察出動の判定と実行を管理するクラス"""
    
    def __init__(self):
        self.logger = logger
        self.lambda_client = LambdaClient()
    
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
            # bedrock_utils.pyの高度な分類ルールを使用して短い返答をスキップ
            if self._should_skip_police_dispatch_check(text, category):
                return
            
            meeting_id = session_data["meeting_id"]
            
            # 警察出動状態の管理
            if not hasattr(session_data, 'police_dispatch_state'):
                session_data['police_dispatch_state'] = {
                    'is_active': False,
                    'last_triggered_time': None,
                    'low_alignment_start_time': None,
                    'recent_checks': {}  # 最近のチェック記録
                }
            
            state = session_data['police_dispatch_state']
            current_time = time.time()
            
            # 短時間での同じテキストの重複処理を防止（より緩い制限）
            text_key = f"{text.strip()}_{alignment_score}"  # テキスト+一致度で識別
            current_minute = int(current_time / 60)  # 分単位でグループ化
            
            if 'recent_checks' not in state:
                state['recent_checks'] = {}
            
            # 同じ分内での同じテキスト+一致度の組み合わせをチェック
            minute_key = f"{current_minute}_{text_key}"
            if minute_key in state['recent_checks']:
                self.logger.debug(f"🔍 Recent duplicate check, skipping: '{text[:30]}...' (alignment: {alignment_score}%)")
                return
            
            state['recent_checks'][minute_key] = current_time
            
            # 古いチェック記録をクリーンアップ（2分以上前のものを削除）
            cleanup_keys = [k for k, t in state['recent_checks'].items() if current_time - t > 120]
            for k in cleanup_keys:
                del state['recent_checks'][k]
            
            self.logger.info(f"🚨 Police dispatch check: alignment={alignment_score}%, speaker={speaker}, text='{text[:50]}...'")
            
            # 警察出動トリガー: 一致度30%以下
            if alignment_score <= 30:
                await self._handle_police_dispatch_trigger(session_data, state, current_time, alignment_score, text, speaker, meeting_id)
            
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
        current_time: float, 
        alignment_score: int, 
        text: str, 
        speaker: str, 
        meeting_id: str
    ) -> None:
        """警察出動のトリガー処理"""
        # 低一致度の開始時刻を記録
        if state['low_alignment_start_time'] is None:
            state['low_alignment_start_time'] = current_time
            self.logger.info(f"🚨 Low alignment period started: {alignment_score}%")
        
        # 警察出動がまだアクティブでない場合、または前回から5分以上経過している場合
        should_trigger = (
            not state['is_active'] or 
            (state['last_triggered_time'] is not None and 
             current_time - state['last_triggered_time'] >= 5 * 60)  # 5分間隔
        )
        
        if should_trigger:
            self.logger.info("🚨 POLICE DISPATCH TRIGGERED!")
            
            # Lambda関数を呼び出し（LED点灯 + 10秒後自動消灯）
            meeting_data = {
                "meeting_id": meeting_id,
                "speaker": speaker,
                "alignment_score": alignment_score,
                "recent_transcript": text,
                "timestamp": now_iso()
            }
            
            # バックグラウンドでLambda呼び出し
            asyncio.create_task(self._invoke_police_dispatch_async(meeting_data))
            
            # セッションキューに警察出動通知を送信
            await session_data["queue"].put({
                "type": "police_dispatch",
                "payload": {
                    "meeting_id": meeting_id,
                    "alignment_score": alignment_score,
                    "speaker": speaker,
                    "text": text,
                    "timestamp": now_iso(),
                    "action": "dispatch_on"
                }
            })
            
            # 状態を更新
            state['is_active'] = True
            state['last_triggered_time'] = current_time
            
            self.logger.info(f"🚨 Police dispatch activated for meeting {meeting_id}")
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
            meeting_data = {
                "meeting_id": meeting_id,
                "speaker": speaker,
                "alignment_score": alignment_score,
                "recent_transcript": text,
                "timestamp": now_iso()
            }
            
            # バックグラウンドでLambda呼び出し
            asyncio.create_task(self._invoke_police_dispatch_off_async(meeting_data))
            
            # セッションキューに警察出動解除通知を送信
            await session_data["queue"].put({
                "type": "police_dispatch_off",
                "payload": {
                    "meeting_id": meeting_id,
                    "alignment_score": alignment_score,
                    "speaker": speaker,
                    "text": text,
                    "timestamp": now_iso(),
                    "action": "dispatch_off"
                }
            })
            
            # 状態をリセット
            state['is_active'] = False
            state['low_alignment_start_time'] = None
            
            self.logger.info(f"🟢 Police dispatch resolved for meeting {meeting_id}")
        
        # 低一致度期間をリセット
        state['low_alignment_start_time'] = None
    
    async def _invoke_police_dispatch_async(self, meeting_data: dict) -> None:
        """警察出動Lambda関数を非同期で呼び出し"""
        try:
            result = await asyncio.to_thread(self.lambda_client.invoke_police_dispatch, meeting_data)
            self.logger.info(f"🚨 Police dispatch Lambda result: {result}")
        except Exception as e:
            self.logger.error(f"❌ Police dispatch Lambda failed: {e}")

    async def _invoke_police_dispatch_off_async(self, meeting_data: dict) -> None:
        """警察出動解除Lambda関数を非同期で呼び出し"""
        try:
            result = await asyncio.to_thread(self.lambda_client.invoke_police_dispatch_off, meeting_data)
            self.logger.info(f"🟢 Police dispatch OFF Lambda result: {result}")
        except Exception as e:
            self.logger.error(f"❌ Police dispatch OFF Lambda failed: {e}")
    
    def _should_skip_police_dispatch_check(self, text: str, category: str = None) -> bool:
        """
        bedrock_utils.pyの高度な分類ルールを使用して短い返答や相槌をスキップ
        """
        text_stripped = text.strip()
        
        # 非常に短いテキストをスキップ
        if len(text_stripped) < 3:
            self.logger.info(f"🔍 短すぎる発言をスキップ: '{text_stripped}' (len={len(text_stripped)})")
            return True
        
        # bedrock_utils.pyの_guess_categoryを使用して高度な分類
        guessed_category = _guess_category(text)
        
        # 「コメント」カテゴリの場合、さらに詳細チェック
        if guessed_category == "コメント" or category == "コメント":
            # bedrock_utils.pyで定義されている短い返答パターン
            short_responses = [
                "はい", "いいえ", "うん", "ええ", "そうです", "そうですね",
                "ありがとうございます", "すみません", "失礼しました", 
                "お疲れさまでした", "よろしくお願いします",
                "了解しました", "承知しました", "大丈夫です", "問題ありません",
                "そうですね", "なるほど", "確かに", "いいですね"
            ]
            
            # 完全一致または非常に類似した短い返答をスキップ
            for response in short_responses:
                if text_stripped == response or (len(text_stripped) <= 10 and response in text_stripped):
                    self.logger.info(f"🔍 短い返答をスキップ: '{text_stripped}' → '{response}'パターン")
                    return True
        
        # 名前だけの発言（例: "田中です", "サトウです"）
        if len(text_stripped) <= 8 and text_stripped.endswith("です"):
            # カタカナ・ひらがな・漢字のみで構成され、「です」で終わる短い発言
            import re
            name_pattern = re.match(r'^[ぁ-んァ-ヶ一-龠ー]+です$', text_stripped)
            if name_pattern:
                self.logger.info(f"🔍 名前の発言をスキップ: '{text_stripped}'")
                return True
        
        return False