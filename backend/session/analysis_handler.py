"""
リアルタイム分析機能
SessionControllerから分離された分析関連の処理
"""

import asyncio
import logging
import re
from typing import Dict, Any, List

from backend.services.bedrock_utils import classify_transcript_segments, _guess_category

logger = logging.getLogger(__name__)


class AnalysisHandler:
    """リアルタイム分析を管理するクラス"""
    
    def __init__(self):
        self.logger = logger
        # PoliceDispatchManagerのインスタンスを保持
        from backend.session.police_dispatch import PoliceDispatchManager
        self.police_dispatch = PoliceDispatchManager()
    
    async def classify_and_send_realtime(
        self, 
        session_data: dict, 
        text: str, 
        speaker: str, 
        index: int,
        force_bedrock: bool = True,
        is_final_text: bool = False,
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

        # 🚗 特定キーワード（車）が含まれている場合は即確定で低一致度扱い
        if "車" in text:
            result_car = {
                "index": index,
                "text": text,
                "speaker": speaker,
                "category": _guess_category(text),
                "alignment": 5,
                "method": "bedrock",  # グラフ反映のため確定扱い
                "is_final": True,
            }
            queue_message_car = {"type": "realtime_classification", "action": "update", "payload": result_car}
            await session_data["queue"].put(queue_message_car)
            self.logger.info(f"🚗 車キーワード検出: 即確定 alignment=5% text='{text[:30]}...'")
            # 警察出動判定にも反映
            await self.police_dispatch.check_and_trigger(
                session_data, result_car["alignment"], text, speaker, result_car["category"]
            )
            # 車検知時はデバイス3754-4414をONし5秒後自動OFF
            lambda_client = getattr(self.police_dispatch, "lambda_client", None)
            if lambda_client:
                asyncio.create_task(asyncio.to_thread(lambda_client.trigger_police_dispatch))
                self.logger.info("🚓 Lambda警告デバイスをトリガー（車検知）")
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
        # 速報: カテゴリのみ送信（一致度は速報では算出しない）
        result_quick = {
            "index": index,
            "text": text,
            "speaker": speaker,
            "category": _guess_category(text),
            "alignment": None,
            "method": "keyword",
            "is_final": False,
        }
        await session_data["queue"].put({"type": "realtime_classification", "payload": result_quick})
        self.logger.info(f"📤 WebSocketキューに送信（速報・カテゴリのみ）: {result_quick}")

        # Bedrockでアジェンダとの一致度を60-100%で採点（文境界・最終・一定長以上）
        should_run_bedrock = is_final_text or self._is_sentence_boundary(text) or len(text.strip()) >= 30
        if should_run_bedrock and force_bedrock:
            try:
                task = asyncio.create_task(self._classify_with_bedrock_session(session_data, text, speaker, index))
                session_data["pending_bedrock_tasks"].add(task)
                task.add_done_callback(lambda t: session_data["pending_bedrock_tasks"].discard(t))
                self.logger.info(f"📊 Bedrock分析開始: '{text[:20]}...' ({len(text)}文字) is_final={is_final_text}")
            except Exception as e:
                self.logger.warning(f"Failed to create Bedrock task: {e}")
        else:
            self.logger.debug(
                f"📊 Bedrock分析保留: is_final={is_final_text}, boundary={self._is_sentence_boundary(text)}, force={force_bedrock}"
            )
    
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

                # Bedrockからのスコアは60〜100%に丸める（内容の近さ評価）
                alignment_ai = max(60, min(100, alignment_ai if isinstance(alignment_ai, (int, float)) else 0))
                
                # コメントカテゴリの場合は最低50%を保証
                if category_ai == "コメント" and alignment_ai < 50:
                    alignment_ai = 50
                    self.logger.info(f"🔧 コメント一致度調整: {result.get('alignment', 0)}% → 50%")
                
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
                queue_message = {"type": "realtime_classification", "action": "update", "payload": result_ai}
                await session_data["queue"].put(queue_message)
                self.logger.info(f"📤 WebSocketキューに送信: {queue_message}")
                
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
                alignment_fallback = max(60, min(100, alignment_fallback))
                
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
        
        # 接続詞・繋ぎ言葉は中程度の一致度を返す
        if self._is_conjunction_or_filler(text.strip()):
            return 50  # 接続詞・繋ぎ言葉は50%
        
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
            return 10  # 全く一致しない場合は10%
            
        # マッチ率に基づいて計算（より寛容に）
        match_ratio = matched_count / len(agenda_keywords)
        alignment = min(100, int(30 + (match_ratio * 70)))  # 30%〜100%の範囲
        
        return alignment

    def _is_sentence_boundary(self, text: str) -> bool:
        """文末が区切り（改行/句読点/終端記号）のとき True"""
        stripped = text.strip()
        if not stripped:
            return False
        if "\n" in text:
            return True
        return stripped.endswith(("。", "！", "？", ".", "!", "?"))
    
    def _should_skip_analysis(self, text: str, category: str) -> bool:
        """
        bedrock_utils.pyの高度な分類ルールを使用して分析をスキップすべきかを判定
        """
        text_stripped = text.strip()
        
        # 非常に短い発言（5文字未満）
        if len(text_stripped) < 5:
            return True
        
        # 接続詞や繋ぎ言葉をスキップ（コメント扱い）
        if self._is_conjunction_or_filler(text_stripped):
            self.logger.info(f"🔍 接続詞・繋ぎ言葉として分析スキップ: '{text_stripped}'")
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
        
        return False
    
    def _is_conjunction_or_filler(self, text: str) -> bool:
        """
        接続詞や繋ぎ言葉を検出する
        これらの発言は「コメント」として扱い、警察出動の対象外とする
        """
        text_stripped = text.strip()
        
        # 日本語の接続詞・繋ぎ言葉のパターン
        conjunction_patterns = [
            # 基本的な接続詞
            r'^(それで|だから|でも|しかし|ただし|なので|そして|また|さらに|一方|ところで|ちなみに)',
            # 感嘆詞・相槌
            r'^(あー|えー|うーん|そうですね|なるほど|確かに|いいですね)',
            # 繋ぎ言葉・フィラー
            r'^(のが|やっぱり|ちょっと|まあ|とりあえず|いちおう|一応)',
            # 複合パターン（ユーザーの例: "のが、やっぱりちょっと"）
            r'^(のが[、，]?\s*(やっぱり|ちょっと))',
            r'^(やっぱり[、，]?\s*(ちょっと|のが))',
            # 短い感想・反応
            r'^(そうか|そっか|なるほど|ふーん|へー|ほー)',
            # 時間稼ぎの表現
            r'^(えーっと|あのー|そのー|まー)',
        ]
        
        # パターンマッチング
        import re
        for pattern in conjunction_patterns:
            if re.match(pattern, text_stripped, re.IGNORECASE):
                self.logger.info(f"🔍 接続詞・繋ぎ言葉を検出: '{text_stripped}' → パターン: {pattern}")
                return True
        
        # 短い単語の組み合わせパターン
        short_fillers = [
            "のが", "やっぱり", "ちょっと", "まあ", "でも", "だから", "それで",
            "そうですね", "なるほど", "確かに", "いいですね", "そうか", "そっか"
        ]
        
        # 短い発言で繋ぎ言葉のみの場合
        if len(text_stripped) <= 15:
            words = text_stripped.replace('、', ' ').replace('，', ' ').split()
            if all(word in short_fillers for word in words if word):
                self.logger.info(f"🔍 短い繋ぎ言葉の組み合わせを検出: '{text_stripped}'")
                return True
        
        return False
