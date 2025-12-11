"""
リアルタイム分析機能
SessionControllerから分離された分析関連の処理
"""

import asyncio
import logging
import re
from typing import Dict, Any, List

from backend.services.bedrock_utils import classify_transcript_segments, _guess_category
from backend.session.police_dispatch import PoliceDispatchManager

logger = logging.getLogger(__name__)


class AnalysisHandler:
    """リアルタイム分析を管理するクラス"""
    
    def __init__(self):
        self.logger = logger
        self.police_dispatch = PoliceDispatchManager()
    
    async def classify_and_send_realtime(
        self, 
        session_data: dict, 
        text: str, 
        speaker: str, 
        index: int
    ) -> None:
        """
        リアルタイム分析を実行（poc_satomin準拠のハイブリッドアプローチ）
        """
        # bedrock_utils.pyの高度な分類ルールを使用して短いテキストをスキップ
        text_stripped = text.strip()
        if len(text_stripped) < 5:  # 最小長を5文字に調整
            self.logger.debug(f"非常に短いテキストをスキップ: '{text_stripped}' (len={len(text_stripped)})")
            return
        
        # bedrock_utils.pyの分類を使用して、分析不要な発言をスキップ
        guessed_category = _guess_category(text)
        if self._should_skip_analysis(text, guessed_category):
            self.logger.info(f"分析スキップ: '{text_stripped}' → カテゴリ: {guessed_category}")
            return
        
        # メタ情報をスキップ
        if text.startswith("Agenda topic:"):
            self.logger.info(f"Skipping meta info: {text[:50]}...")
            return
        
        # 「Discussion:」の後に続く内容をチェック
        if text.startswith("Discussion: Confirming action items for"):
            match = re.search(r"'([^']+)'", text)
            if match:
                content = match.group(1)
                meta_keywords = ["議題タイトル", "所要時間", "発表者", "分", "時間"]
                if len(content) < 10 or any(keyword in content for keyword in meta_keywords):
                    self.logger.info(f"Skipping meta content: {text[:50]}...")
                    return
        
        self.logger.info(f"📊 Real-time analysis start: {speaker} - {text[:30]}...")
        
        # Step 1: キーワードベースの簡易分類（即座に返す）
        category_quick = _guess_category(text)
        alignment_quick = self.calculate_alignment(text, session_data["agenda_text"])

        result_quick = {
            "index": index,
            "text": text,
            "speaker": speaker,
            "category": category_quick,
            "alignment": alignment_quick,
            "method": "keyword",  # キーワードベース
            "is_final": False  # まだ確定じゃない
        }

        # すぐにクライアントに通知
        await session_data["queue"].put({"type": "realtime_classification", "payload": result_quick})
        
        # Step 2: バックグラウンドでBedrockに送信（非同期）
        try:
            task = asyncio.create_task(self._classify_with_bedrock_session(session_data, text, speaker, index))
            session_data["pending_bedrock_tasks"].add(task)
            task.add_done_callback(lambda t: session_data["pending_bedrock_tasks"].discard(t))
        except Exception as e:
            self.logger.warning(f"Failed to create Bedrock task: {e}")
    
    async def _classify_with_bedrock_session(
        self, 
        session_data: dict, 
        text: str, 
        speaker: str, 
        index: int
    ) -> None:
        """Bedrock分析（バックグラウンド）"""
        self.logger.info(f"🔍 Bedrock analysis start: {speaker} - {text[:30]}...")
        try:
            # 文脈を取得（前後の発言）
            context_before = ""
            context_after = ""
            for transcript in session_data["transcripts"]:
                if transcript.get("index") == index - 1:
                    context_before = transcript.get("text", "")
                elif transcript.get("index") == index + 1:
                    context_after = transcript.get("text", "")
            
            # Bedrockで分析
            segment = {
                "index": index,
                "speaker": speaker,
                "text": text,
                "context_before": context_before,
                "context_after": context_after,
            }
            
            self.logger.info(f"  → Bedrockに送信中... segment={segment}")
            self.logger.info(f"  → agenda_text={session_data['agenda_text'][:100]}...")
            
            # classify_transcript_segmentsを使って分析
            classified = await asyncio.to_thread(
                classify_transcript_segments,
                [segment],
                session_data["agenda_text"]
            )
            
            self.logger.info(f"  → Bedrockから応答受信: {classified}")
            
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
                    "method": "bedrock",  # AI分析
                    "is_final": True  # 確定
                }
                
                # 更新をクライアントに通知
                await session_data["queue"].put({"type": "realtime_classification", "action": "update", "payload": result_ai})
                
                self.logger.info(f"✅ Bedrock analysis complete: {speaker} - {text[:30]}... → [{category_ai}] {alignment_ai}%")
                
                # 警察出動チェック（Bedrockで確定した結果のみ）
                await self.police_dispatch.check_and_trigger(
                    session_data, alignment_ai, text, speaker, category_ai
                )
            else:
                # Bedrockが失敗したら、キーワードベースの結果を「確定」として送る
                self.logger.warning("⚠️ Bedrockから結果なし、キーワードベースを確定として送信")
                category_fallback = _guess_category(text)
                alignment_fallback = self.calculate_alignment(text, session_data["agenda_text"])
                
                result_fallback = {
                    "index": index,
                    "text": text,
                    "speaker": speaker,
                    "category": category_fallback,
                    "alignment": alignment_fallback,
                    "method": "keyword",  # キーワードベース
                    "is_final": True  # 確定（Bedrockが失敗したので）
                }
                
                await session_data["queue"].put({"type": "realtime_classification", "action": "update", "payload": result_fallback})
                self.logger.info(f"✅ キーワード分析確定: {speaker} - {text[:30]}... → [{category_fallback}] {alignment_fallback}%")
                
                # 警察出動チェック（フォールバック結果）
                await self.police_dispatch.check_and_trigger(
                    session_data, alignment_fallback, text, speaker, category_fallback
                )
        
        except Exception as e:
            self.logger.error(f"❌ Bedrock分析失敗: {e}")
            self.logger.exception("詳細なエラー:")
    
    def calculate_alignment(self, text: str, agenda_text: str) -> int:
        """
        発言とアジェンダの一致度を0-100で計算（poc_satomin準拠）
        """
        if not agenda_text or not agenda_text.strip():
            return 50  # アジェンダがなければデフォルト50%
        
        # メタ情報の発言は一致度を計算しない
        meta_keywords = ["議題", "タイトル", "所要時間", "発表者", "検討事項", "目的", "背景"]
        if any(keyword in text for keyword in meta_keywords):
            return 50  # メタ情報はデフォルト50%
            
        # アジェンダから重要なキーワードを抽出（メタ情報を除外）
        agenda_keywords = set()
        skip_keywords = {"議題", "タイトル", "所要時間", "発表者", "検討事項", "目的", "背景"}
        
        for line in agenda_text.splitlines():
            line = line.strip(" -*•\t0123456789.。")  # 箇条書き記号や番号を除去
            if not line:
                continue
            # メタ情報の行をスキップ
            if any(skip in line for skip in skip_keywords):
                continue
            # 2文字以上の単語を抽出（簡易的）
            words = [w for w in re.findall(r'[ぁ-んァ-ヶ一-龠ー]+', line) if len(w) >= 2]
            # スキップキーワードを除外
            words = [w for w in words if w not in skip_keywords]
            agenda_keywords.update(words)
        
        if not agenda_keywords:
            return 50  # キーワードがなければデフォルト50%
            
        # 発言に含まれるキーワードの数をカウント
        text_lower = text.lower()
        matched_count = sum(1 for keyword in agenda_keywords if keyword in text_lower)
        
        # 一致率を計算（0-100%）
        if matched_count == 0:
            return 30  # 全く一致しなくても最低30%
            
        # マッチ率に基づいて計算（より寛容に）
        match_ratio = matched_count / len(agenda_keywords)
        alignment = min(100, int(30 + (match_ratio * 70)))  # 30%〜100%の範囲
        
        return alignment
    
    def split_long_text(self, text: str, max_length: int = 80, min_length: int = 25) -> List[str]:
        """長いテキストを句読点で分割（poc_satomin準拠）"""
        if len(text) <= max_length:
            return [text]
        
        # 句読点で分割（句読点を含める）
        parts = re.split(r'(。|！|？)', text)
        
        # 句読点を前の文に結合
        sentences = []
        for i in range(0, len(parts), 2):
            sentence = parts[i]
            if i + 1 < len(parts):
                sentence += parts[i + 1]  # 句読点を追加
            if sentence.strip():
                sentences.append(sentence.strip())
        
        # 長い文をさらに読点で分割
        result = []
        for sentence in sentences:
            if len(sentence) <= max_length:
                result.append(sentence)
            else:
                # 読点で分割
                sub_parts = re.split(r'(、|,)', sentence)
                buffer = ""
                for i in range(0, len(sub_parts)):
                    part = sub_parts[i]
                    if len(buffer + part) <= max_length:
                        buffer += part
                    else:
                        if buffer.strip():
                            result.append(buffer.strip())
                        buffer = part
                if buffer.strip():
                    result.append(buffer.strip())
        
        # 短い文を前の文と結合
        final_result = []
        for sentence in result:
            if final_result and len(sentence) < min_length:
                final_result[-1] += sentence
            else:
                final_result.append(sentence)
        
        return [s for s in final_result if s]
    
    def _should_skip_analysis(self, text: str, category: str) -> bool:
        """
        bedrock_utils.pyの高度な分類ルールを使用して分析をスキップすべきかを判定
        
        Args:
            text: 発言内容
            category: _guess_categoryで推定されたカテゴリ
            
        Returns:
            bool: 分析をスキップすべき場合はTrue
        """
        text_stripped = text.strip()
        
        # 非常に短い発言（5文字未満）
        if len(text_stripped) < 5:
            return True
        
        # 「コメント」カテゴリの短い発言をより詳細にチェック
        if category == "コメント" and len(text_stripped) <= 15:
            # bedrock_utils.pyで定義されている短い返答パターン
            short_responses = [
                "はい", "いいえ", "うん", "ええ", "そうです", "そうですね",
                "ありがとうございます", "すみません", "失礼しました", 
                "お疲れさまでした", "よろしくお願いします",
                "了解しました", "承知しました", "大丈夫です", "問題ありません",
                "なるほど", "確かに", "いいですね"
            ]
            
            # 完全一致または部分一致する短い返答
            for response in short_responses:
                if text_stripped == response or (len(text_stripped) <= 10 and response in text_stripped):
                    return True
        
        # 名前だけの自己紹介（例: "田中です"）は分析する（「報告」として重要）
        # ただし、非常に短い場合はスキップ
        if len(text_stripped) <= 4 and text_stripped.endswith("です"):
            return True
        
        return False

    async def classify_entry_with_splitting(
        self, 
        session_data: dict, 
        entry: dict
    ) -> None:
        """エントリを分割してリアルタイム分析を実行（poc_satomin準拠）"""
        split_texts = self.split_long_text(entry["text"])
        meeting_id = session_data["meeting_id"]
        
        for i, split_text in enumerate(split_texts):
            # 非常に短いテキストをスキップ
            if len(split_text.strip()) < 10:
                continue
                
            await self.classify_and_send_realtime(
                session_data, 
                split_text, 
                entry["speaker"], 
                entry["index"] * 1000 + i  # ユニークなインデックス
            )