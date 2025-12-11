"""
警察出動機能 - 後方互換性のためのエントリーポイント
新しい分割された構造への移行用
"""

# 後方互換性のために新しいクラスをインポート
from .police_dispatch_manager import PoliceDispatchManager

# 既存のコードが動作するように、元のクラス名でエクスポート
__all__ = ['PoliceDispatchManager']