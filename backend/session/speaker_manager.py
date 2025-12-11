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