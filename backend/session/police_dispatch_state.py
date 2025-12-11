"""
警察出動の状態管理
"""

import asyncio
import logging
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)


class PoliceDispatchState:
    """警察出動の状態管理クラス"""
    
    def __init__(self):
        self.logger = logger
    
    def initialize_state(self, session_data: dict, meeting_id: str) -> dict:
        """
        警察出動状態を初期化
        
        Args:
            session_data: セッションデータ
            meeting_id: ミーティングID
            
        Returns:
            dict: 初期化された状態辞書
        """
        if 'police_dispatch_state' not in session_data:
            session_data['police_dispatch_state'] = {
                'is_active': False,
                'last_triggered_time': None,
                'low_alignment_start_time': None,
                'recent_checks': {}  # 最近のチェック記録
            }
            self.logger.info(f"🔧 Police dispatch state initialized for meeting {meeting_id}")
        else:
            state = session_data['police_dispatch_state']
            self.logger.info(f"🔧 Police dispatch state exists: is_active={state['is_active']}, last_triggered={state['last_triggered_time']}")
        
        return session_data['police_dispatch_state']
    
    def is_duplicate_check(self, state: dict, text: str, alignment_score: int) -> bool:
        """
        重複チェックを判定
        
        Args:
            state: 状態辞書
            text: テキスト
            alignment_score: 一致度スコア
            
        Returns:
            bool: 重複の場合True
        """
        current_time = time.time()
        text_key = f"{text.strip()[:50]}_{alignment_score}"  # テキスト（最初50文字）+一致度で識別
        
        if 'recent_checks' not in state:
            state['recent_checks'] = {}
        
        # 同じテキスト+一致度の組み合わせを10秒間記録
        if text_key in state['recent_checks']:
            time_diff = current_time - state['recent_checks'][text_key]
            if time_diff < 10:  # 10秒以内の重複をスキップ
                self.logger.debug(f"🔍 Recent duplicate check, skipping: '{text[:30]}...' (alignment: {alignment_score}%, {time_diff:.1f}s ago)")
                return True
        
        state['recent_checks'][text_key] = current_time
        
        # 古いチェック記録をクリーンアップ（30秒以上前のものを削除）
        cleanup_keys = [k for k, t in state['recent_checks'].items() if current_time - t > 30]
        for k in cleanup_keys:
            del state['recent_checks'][k]
        
        return False
    
    def should_trigger(self, state: dict) -> tuple[bool, str]:
        """
        警察出動をトリガーすべきかを判定
        
        Args:
            state: 状態辞書
            
        Returns:
            tuple[bool, str]: (トリガーすべきか, 理由)
        """
        current_time = time.time()
        time_since_last = (current_time - state['last_triggered_time']) if state['last_triggered_time'] else None
        
        should_trigger = (
            not state['is_active'] or 
            (state['last_triggered_time'] is not None and 
             current_time - state['last_triggered_time'] >= 30)  # 30秒間隔
        )
        
        time_since_last_str = f"{time_since_last:.1f}s" if time_since_last is not None else "None"
        reason = f"is_active={state['is_active']}, last_triggered={state['last_triggered_time']}, time_since_last={time_since_last_str}"
        
        return should_trigger, reason
    
    def activate(self, state: dict) -> None:
        """
        警察出動を有効化
        
        Args:
            state: 状態辞書
        """
        current_time = time.time()
        state['is_active'] = True
        state['last_triggered_time'] = current_time
        
        # 10秒後に自動的にis_activeをFalseにするタスクを作成
        asyncio.create_task(self._auto_deactivate_after_delay(state, 10))
    
    def deactivate(self, state: dict) -> None:
        """
        警察出動を無効化
        
        Args:
            state: 状態辞書
        """
        state['is_active'] = False
        state['low_alignment_start_time'] = None
    
    def set_low_alignment_start(self, state: dict, alignment_score: int) -> None:
        """
        低一致度期間の開始を記録
        
        Args:
            state: 状態辞書
            alignment_score: 一致度スコア
        """
        if state['low_alignment_start_time'] is None:
            state['low_alignment_start_time'] = time.time()
            self.logger.info(f"🚨 Low alignment period started: {alignment_score}%")
    
    def clear_low_alignment_start(self, state: dict) -> None:
        """
        低一致度期間をクリア
        
        Args:
            state: 状態辞書
        """
        state['low_alignment_start_time'] = None
    
    async def _auto_deactivate_after_delay(self, state: dict, delay_seconds: int) -> None:
        """
        指定秒数後に自動的にis_activeをFalseにする
        
        Args:
            state: 状態辞書
            delay_seconds: 遅延秒数
        """
        try:
            await asyncio.sleep(delay_seconds)
            if state['is_active']:
                state['is_active'] = False
                self.logger.info(f"🔄 Police dispatch auto-deactivated after {delay_seconds}s")
        except Exception as e:
            self.logger.error(f"❌ Auto-deactivate failed: {e}")