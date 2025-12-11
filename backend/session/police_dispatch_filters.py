"""
警察出動のテキストフィルタリング機能
"""

import logging
import re
from backend.services.bedrock_utils import _guess_category

logger = logging.getLogger(__name__)


class PoliceDispatchFilters:
    """警察出動のテキストフィルタリングクラス"""
    
    def __init__(self):
        self.logger = logger
    
    def should_skip_police_dispatch_check(self, text: str, category: str = None) -> bool:
        """
        bedrock_utils.pyの高度な分類ルールを使用して短い返答や相槌をスキップ
        
        Args:
            text: テキスト
            category: Bedrockで分類されたカテゴリ（オプション）
            
        Returns:
            bool: スキップすべき場合True
        """
        text_stripped = text.strip()
        
        # 非常に短いテキストをスキップ
        if len(text_stripped) < 3:
            self.logger.info(f"🔍 短すぎる発言をスキップ: '{text_stripped}' (len={len(text_stripped)})")
            return True
        
        # 接続詞や繋ぎ言葉をスキップ（コメント扱い）
        if self._is_conjunction_or_filler(text_stripped):
            self.logger.info(f"🔍 接続詞・繋ぎ言葉として警察出動チェックスキップ: '{text_stripped}'")
            return True
        
        # bedrock_utils.pyの_guess_categoryを使用して高度な分類
        guessed_category = _guess_category(text)
        
        # 「コメント」カテゴリの場合、さらに詳細チェック
        if guessed_category == "コメント" or category == "コメント":
            if self._is_short_response(text_stripped):
                return True
        
        # 名前だけの発言をスキップ
        if self._is_name_only_statement(text_stripped):
            return True
        
        return False
    
    def _is_conjunction_or_filler(self, text: str) -> bool:
        """
        接続詞や繋ぎ言葉を検出する
        ただし、重要キーワードが含まれる場合や長い文章の場合は警察出動チェックを継続する
        
        Args:
            text: テキスト
            
        Returns:
            bool: 接続詞・繋ぎ言葉の場合True（ただし重要キーワードがある場合はFalse）
        """
        text_stripped = text.strip()
        
        # 重要キーワードが含まれる場合は接続詞で始まっていても警察出動チェックを継続
        important_keywords = {
            "仕事", "面倒", "しんどい", "大変", "困る", "問題", "課題", "改善", "効率",
            "ワッカソン", "解決", "検討", "議論", "提案", "意見", "考え", "思う"
        }
        
        # 重要キーワードチェック
        text_lower = text.lower()
        has_important_keywords = any(keyword in text_lower for keyword in important_keywords)
        
        if has_important_keywords:
            self.logger.info(f"🎯 重要キーワード検出により接続詞フィルタを回避（警察出動チェック継続）: '{text_stripped[:30]}...'")
            return False
        
        # 長い文章（20文字以上）の場合は内容を重視
        if len(text_stripped) >= 20:
            self.logger.info(f"📝 長い文章により接続詞フィルタを回避（警察出動チェック継続）: '{text_stripped[:30]}...' (len={len(text_stripped)})")
            return False
        
        # 日本語の接続詞・繋ぎ言葉のパターン（短い発言のみ対象）
        conjunction_patterns = [
            # 基本的な接続詞（短い場合のみ）
            r'^(それで|だから|でも|しかし|ただし|なので|そして|また|さらに|一方|ところで|ちなみに)$',
            # 感嘆詞・相槌
            r'^(あー|えー|うーん|そうですね|なるほど|確かに|いいですね)$',
            # 繋ぎ言葉・フィラー
            r'^(のが|やっぱり|ちょっと|まあ|とりあえず|いちおう|一応)$',
            # 複合パターン（短い組み合わせのみ）
            r'^(のが[、，]?\s*(やっぱり|ちょっと))$',
            r'^(やっぱり[、，]?\s*(ちょっと|のが))$',
            # 短い感想・反応
            r'^(そうか|そっか|なるほど|ふーん|へー|ほー)$',
            # 時間稼ぎの表現
            r'^(えーっと|あのー|そのー|まー)$',
        ]
        
        # パターンマッチング（短い発言のみ）
        for pattern in conjunction_patterns:
            if re.match(pattern, text_stripped, re.IGNORECASE):
                return True
        
        # 短い単語の組み合わせパターン（15文字以下のみ）
        short_fillers = [
            "のが", "やっぱり", "ちょっと", "まあ", "でも", "だから", "それで",
            "そうですね", "なるほど", "確かに", "いいですね", "そうか", "そっか"
        ]
        
        # 短い発言で繋ぎ言葉のみの場合
        if len(text_stripped) <= 15:
            words = text_stripped.replace('、', ' ').replace('，', ' ').split()
            if all(word in short_fillers for word in words if word):
                return True
        
        return False
    
    def _is_short_response(self, text_stripped: str) -> bool:
        """
        短い返答パターンを検出
        
        Args:
            text_stripped: トリムされたテキスト
            
        Returns:
            bool: 短い返答の場合True
        """
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
        
        return False
    
    def _is_name_only_statement(self, text_stripped: str) -> bool:
        """
        名前だけの発言を検出（例: "田中です", "サトウです"）
        
        Args:
            text_stripped: トリムされたテキスト
            
        Returns:
            bool: 名前だけの発言の場合True
        """
        if len(text_stripped) <= 8 and text_stripped.endswith("です"):
            # カタカナ・ひらがな・漢字のみで構成され、「です」で終わる短い発言
            name_pattern = re.match(r'^[ぁ-んァ-ヶ一-龠ー]+です$', text_stripped)
            if name_pattern:
                self.logger.info(f"🔍 名前の発言をスキップ: '{text_stripped}'")
                return True
        
        return False