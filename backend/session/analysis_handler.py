"""
リアルタイム分析機能
SessionControllerから分離された分析関連の処理
"""

import asyncio
import logging
import re

from backend.services.bedrock_utils import classify_transcript_segments, _guess_category

logger = logging.getLogger(__name__)


class AnalysisHandler:
    """リアルタイム分析を管理するクラス"""
    
    def __init__(self):
        self.logger = logger
        # Bedrock分析結果のキャッシュ（重複分析を防ぐ）
        self.bedrock_cache = {}
    
    async def classify_and_send_realtime(
        self, 
        session_data: dict, 
        text: str, 
        speaker: str, 
        index: int,
        force_bedrock: bool = True
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
        
        # コメント・相槌の場合は一致度を50%に設定
        if category_quick == "コメント":
            alignment_quick = 50  # コメントは50%
        elif category_quick == "感想・意見":
            alignment_quick = 40  # 感想・意見は40%（議題に関連する可能性あり）
        elif category_quick == "無関係な雑談":
            alignment_quick = 5  # 無関係な雑談は5%

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
        queue_message_quick = {"type": "realtime_classification", "payload": result_quick}
        await session_data["queue"].put(queue_message_quick)
        self.logger.info(f"📤 WebSocketキューに送信（キーワード）: {queue_message_quick}")
        
        # Step 2: バックグラウンドでBedrockに送信（条件付き）
        if force_bedrock:
            try:
                task = asyncio.create_task(self._classify_with_bedrock_session(session_data, text, speaker, index))
                session_data["pending_bedrock_tasks"].add(task)
                task.add_done_callback(lambda t: session_data["pending_bedrock_tasks"].discard(t))
                self.logger.info(f"📊 Bedrock分析開始: '{text[:20]}...' ({len(text)}文字)")
            except Exception as e:
                self.logger.warning(f"Failed to create Bedrock task: {e}")
        else:
            self.logger.debug(f"📊 Bedrock分析スキップ: '{text[:20]}...' ({len(text)}文字)")
    
    async def _classify_with_bedrock_session(
        self, 
        session_data: dict, 
        text: str, 
        speaker: str, 
        index: int
    ) -> None:
        """Bedrock分析（バックグラウンド）"""
        # テキストの正規化（空白や句読点の違いを吸収）
        normalized_text = self._normalize_text_for_cache(text)
        cache_key = f"{normalized_text}_{session_data['meeting_id']}"
        
        # キャッシュチェック
        if cache_key in self.bedrock_cache:
            cached_result = self.bedrock_cache[cache_key]
            self.logger.info(f"🔄 Bedrock結果をキャッシュから取得: {speaker} - {text[:30]}... → [{cached_result['category']}] {cached_result['alignment']}%")
            
            # キャッシュ結果を使用して更新
            result_cached = {
                "index": index,
                "text": text,
                "speaker": speaker,
                "category": cached_result['category'],
                "alignment": cached_result['alignment'],
                "method": "bedrock_cached",  # キャッシュ使用
                "is_final": True
            }
            
            await session_data["queue"].put({"type": "realtime_classification", "action": "update", "payload": result_cached})
            return
        
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
                
                # コメントカテゴリの場合は最低50%を保証
                if category_ai == "コメント" and alignment_ai < 50:
                    alignment_ai = 50
                    self.logger.info(f"🔧 コメント一致度調整: {result.get('alignment', 0)}% → 50%")
                
                # 重要キーワードが含まれる場合の一致度調整
                alignment_ai = self._adjust_alignment_for_keywords(text, alignment_ai)
                if alignment_ai != result.get('alignment', 0):
                    self.logger.info(f"🎯 重要キーワード一致度調整: {result.get('alignment', 0)}% → {alignment_ai}%")
                
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
                
                # 結果をキャッシュに保存
                normalized_text = self._normalize_text_for_cache(text)
                cache_key = f"{normalized_text}_{session_data['meeting_id']}"
                self.bedrock_cache[cache_key] = {
                    'category': category_ai,
                    'alignment': alignment_ai
                }
                
                # 定期的にキャッシュクリーンアップ
                if len(self.bedrock_cache) % 20 == 0:  # 20件ごとにチェック
                    self._cleanup_bedrock_cache()
                
                # 警察出動チェック（Bedrockで確定した結果のみ）
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
            
        # 重要キーワードの定義（アジェンダに基づく）
        high_priority_keywords = {
            "仕事", "面倒", "ワッカソン", "効率", "改善", "課題", "問題", "解決", "検討", "議論"
        }
        
        # 発言に含まれるキーワードの数をカウント（重み付きスコア）
        text_lower = text.lower()
        weighted_score = 0
        total_possible_score = 0
        
        for keyword in agenda_keywords:
            # 重要キーワードは3倍の重み
            weight = 3 if keyword in high_priority_keywords else 1
            total_possible_score += weight
            
            if keyword in text_lower:
                weighted_score += weight
                self.logger.debug(f"🎯 キーワードマッチ: '{keyword}' (重み: {weight})")
        
        # 一致率を計算（0-100%）
        if weighted_score == 0:
            return 10  # 全く一致しない場合は10%
        
        # 重み付きスコアに基づいて計算
        if total_possible_score > 0:
            match_ratio = weighted_score / total_possible_score
            # 重要キーワードが含まれる場合は最低50%を保証
            has_high_priority = any(keyword in text_lower for keyword in high_priority_keywords)
            base_score = 50 if has_high_priority else 30
            alignment = min(100, int(base_score + (match_ratio * (100 - base_score))))
        else:
            alignment = 30
        
        self.logger.debug(f"🎯 一致度計算: weighted_score={weighted_score}, total={total_possible_score}, ratio={match_ratio:.2f}, alignment={alignment}%")
        return alignment
    
    def _should_skip_analysis(self, text: str, category: str) -> bool:
        """
        bedrock_utils.pyの高度な分類ルールを使用して分析をスキップすべきかを判定
        """
        text_stripped = text.strip()
        
        # 非常に短い発言（5文字未満）
        if len(text_stripped) < 5:
            return True
        
        # 接続詞や繋ぎ言葉をスキップ（ただし重要キーワードがある場合は継続）
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
        ただし、重要キーワードが含まれる場合や長い文章の場合は分析を継続する
        """
        text_stripped = text.strip()
        
        # 重要キーワードが含まれる場合は接続詞で始まっていても分析する
        important_keywords = {
            "仕事", "面倒", "しんどい", "大変", "困る", "問題", "課題", "改善", "効率",
            "ワッカソン", "解決", "検討", "議論", "提案", "意見", "考え", "思う"
        }
        
        # 重要キーワードチェック
        text_lower = text.lower()
        has_important_keywords = any(keyword in text_lower for keyword in important_keywords)
        
        if has_important_keywords:
            self.logger.info(f"🎯 重要キーワード検出により接続詞フィルタを回避: '{text_stripped[:30]}...'")
            return False
        
        # 長い文章（20文字以上）の場合は内容を重視
        if len(text_stripped) >= 20:
            self.logger.info(f"📝 長い文章により接続詞フィルタを回避: '{text_stripped[:30]}...' (len={len(text_stripped)})")
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
        import re
        for pattern in conjunction_patterns:
            if re.match(pattern, text_stripped, re.IGNORECASE):
                self.logger.info(f"🔍 短い接続詞・繋ぎ言葉を検出: '{text_stripped}' → パターン: {pattern}")
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
                self.logger.info(f"🔍 短い繋ぎ言葉の組み合わせを検出: '{text_stripped}'")
                return True
        
        return False
    
    def _normalize_text_for_cache(self, text: str) -> str:
        """
        キャッシュ用にテキストを正規化
        空白、句読点、語尾の違いを吸収して同じ内容を識別
        """
        import re
        
        # 小文字に変換
        normalized = text.lower()
        
        # 句読点・記号を除去
        normalized = re.sub(r'[。、！？.,!?]', '', normalized)
        
        # 連続する空白を単一空白に
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # 前後の空白を除去
        normalized = normalized.strip()
        
        # 語尾の揺れを統一（「です」「だ」「である」等）
        normalized = re.sub(r'(です|だ|である|ます|だよ|だね|ですね)$', '', normalized)
        
        return normalized
    
    def _cleanup_bedrock_cache(self, max_entries: int = 100):
        """
        Bedrockキャッシュのクリーンアップ
        メモリ使用量を制限するため古いエントリを削除
        """
        if len(self.bedrock_cache) > max_entries:
            # 古いエントリを削除（簡易的にランダムに半分削除）
            import random
            keys_to_remove = random.sample(list(self.bedrock_cache.keys()), len(self.bedrock_cache) // 2)
            for key in keys_to_remove:
                del self.bedrock_cache[key]
            self.logger.info(f"🧹 Bedrockキャッシュクリーンアップ: {len(keys_to_remove)}件削除, 残り{len(self.bedrock_cache)}件")
    
    def _adjust_alignment_for_keywords(self, text: str, current_alignment: int) -> int:
        """
        重要キーワードが含まれる場合の一致度調整
        """
        high_priority_keywords = {
            "仕事", "面倒", "ワッカソン", "効率", "改善", "課題", "問題", "解決", "検討", "議論"
        }
        
        text_lower = text.lower()
        matched_keywords = [kw for kw in high_priority_keywords if kw in text_lower]
        
        if matched_keywords:
            # 重要キーワードが含まれる場合は最低50%を保証
            adjusted_alignment = max(current_alignment, 50)
            
            # 複数の重要キーワードがある場合はさらにボーナス
            if len(matched_keywords) >= 2:
                adjusted_alignment = min(100, adjusted_alignment + 20)
            
            if adjusted_alignment != current_alignment:
                self.logger.debug(f"🎯 重要キーワード検出: {matched_keywords} → 一致度調整 {current_alignment}% → {adjusted_alignment}%")
            
            return adjusted_alignment
        
        return current_alignment
