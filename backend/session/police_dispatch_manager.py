"""
警察出動機能のメイン管理クラス（無効化済みのプレースホルダー）

自動判定による警察出動は廃止されたため、このクラスはログを出して即時リターンします。
"""

import logging

logger = logging.getLogger(__name__)


class PoliceDispatchManager:
    """自動警察出動判定のプレースホルダー"""

    def __init__(self):
        self.logger = logger

    async def check_and_trigger(
        self,
        session_data: dict,
        alignment_score: int,
        text: str,
        speaker: str,
        category: str | None = None,
    ) -> dict:
        """自動判定はdeprecatedのため何も実行しない"""
        self.logger.info("🚫 PoliceDispatchManager.check_and_trigger is deprecated; skipping dispatch check")
        return {"status": "deprecated", "alignment_score": alignment_score, "category": category}
