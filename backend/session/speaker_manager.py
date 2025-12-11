"""
話者識別・管理機能
SessionControllerから分離された話者関連の処理
"""

import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class SpeakerManager:
    """話者識別と管理を行うクラス"""
    
    def __init__(self):
        self.logger = logger
    
    def normalize_raw_label(self, raw_label: str | None) -> str:
        """話者ラベルを正規化する"""
        unknown_tokens = {"", "spk_unk", "__unknown__", "unknown", "unk", None}
        if raw_label in unknown_tokens:
            return "spk_unk"
        key_str = str(raw_label).strip()
        return key_str or "spk_unk"
    
    def get_speaker_name(self, session_data: dict, raw_label: str | None) -> str:
        """フレンドリーな話者名を取得（poc_satomin準拠）"""
        key = self.normalize_raw_label(raw_label)
        
        # 話者管理の初期化
        if "speaker_labels" not in session_data:
            session_data["speaker_labels"] = {"spk_unk": "判別中..."}
            session_data["next_speaker_index"] = 1
        
        # 不明話者の処理
        if key == "spk_unk":
            session_data["speaker_labels"].setdefault("spk_unk", "判別中...")
            return session_data["speaker_labels"]["spk_unk"]
        
        # 既知話者の処理
        if key not in session_data["speaker_labels"]:
            label = f"Speaker {session_data['next_speaker_index']}"
            session_data["speaker_labels"][key] = label
            session_data["next_speaker_index"] += 1
            self.logger.info(f"🧑 New speaker registered: {key} → {label}")
        
        return session_data["speaker_labels"][key]
    
    def is_unknown_label(self, raw_label: str | None) -> bool:
        """話者ラベルが不明かどうかをチェック"""
        normalized = self.normalize_raw_label(raw_label)
        return normalized == "spk_unk"
    
    def estimate_speaker_by_time(self, session_data: dict, transcript: str) -> str:
        """
        時間ベースで話者を推定する（話者識別がない場合のフォールバック）
        """
        import time
        
        # 話者推定の状態管理
        if "speaker_estimation" not in session_data:
            session_data["speaker_estimation"] = {
                "last_speaker": "Speaker 1",
                "last_change_time": time.time(),
                "speaker_durations": {"Speaker 1": 0, "Speaker 2": 0},
                "current_speaker_start": time.time()
            }
        
        estimation = session_data["speaker_estimation"]
        current_time = time.time()
        
        # 現在の話者の発言時間を更新
        duration_since_start = current_time - estimation["current_speaker_start"]
        estimation["speaker_durations"][estimation["last_speaker"]] += duration_since_start
        
        # 話者変更の判定（簡易的なルール）
        time_since_last_change = current_time - estimation["last_change_time"]
        
        # 5秒以上の沈黙があった場合、または一人が長時間話している場合は話者変更
        should_change_speaker = (
            time_since_last_change > 5.0 or  # 5秒以上の沈黙
            duration_since_start > 30.0      # 30秒以上連続発言
        )
        
        if should_change_speaker:
            # 話者を交代
            current_speaker = estimation["last_speaker"]
            if current_speaker == "Speaker 1":
                new_speaker = "Speaker 2"
            else:
                new_speaker = "Speaker 1"
            
            estimation["last_speaker"] = new_speaker
            estimation["last_change_time"] = current_time
            estimation["current_speaker_start"] = current_time
            
            self.logger.info(f"🔄 Speaker change estimated: {current_speaker} → {new_speaker}")
        
        return estimation["last_speaker"]