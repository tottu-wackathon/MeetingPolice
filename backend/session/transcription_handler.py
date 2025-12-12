"""
音声認識・文字起こし機能
SessionControllerから分離された音声認識関連の処理
"""

import asyncio
import logging
import queue
import threading
import time
from typing import Dict, Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from backend.services.transcribe_stream import TranscribeStream
from backend.utils.time_utils import now_iso

logger = logging.getLogger(__name__)


class TranscriptionHandler:
    """音声認識と文字起こしを管理するクラス"""
    
    def __init__(self):
        self.logger = logger
        self.transcribe = TranscribeStream()
    
    async def start_realtime_transcription(
        self, 
        session_data: dict, 
        websocket: WebSocket,
        on_transcript_callback
    ) -> None:
        """リアルタイム音声認識を開始"""
        meeting_id = session_data["meeting_id"]
        
        try:
            # 音声キューを作成
            audio_queue = queue.Queue()
            
            # 🔍 音声認識ヘルスモニタリング
            last_transcript_time = time.time()
            transcript_count = 0
            
            def on_transcript_result(result):
                """音声認識結果のコールバック（詳細ログ付き）"""
                nonlocal last_transcript_time, transcript_count
                try:
                    transcript = result.get("transcript", "").strip()
                    is_partial = result.get("is_partial", False)
                    
                    transcript_count += 1
                    current_time = time.time()
                    gap_since_last = current_time - last_transcript_time
                    last_transcript_time = current_time
                    
                    # 🔍 詳細な音声認識ログ
                    self.logger.info(f"🎯 音声認識 #{transcript_count}: partial={is_partial}, gap={gap_since_last:.1f}s, text='{transcript[:50]}{'...' if len(transcript) > 50 else ''}'")
                    
                    # 🕒 自動確定デバッグ: 部分結果パターンを追跡
                    if is_partial:
                        self.logger.info(f"⏰ 部分結果受信 - 自動確定タイマーがアクティブになる予定")
                    else:
                        self.logger.info(f"✅ 最終結果をAWSから受信 - 自動確定タイマーをキャンセルする予定")
                    
                    if not transcript:
                        self.logger.debug("空の音声認識結果、スキップ")
                        return
                    
                    # 外部コールバックを呼び出し
                    asyncio.create_task(on_transcript_callback(result))
                        
                except Exception as e:
                    self.logger.error("音声認識結果処理エラー: %s", e)
            
            # バックグラウンドスレッドで音声認識を開始
            def run_transcription():
                try:
                    start_time = time.time()
                    self.logger.info("🎙️ 音声認識スレッド開始...")
                    self.transcribe.stream_audio(audio_queue, on_transcript_result)
                    elapsed = time.time() - start_time
                    self.logger.info(f"🎙️ 音声認識スレッド完了 {elapsed:.1f}秒後")
                except Exception as e:
                    elapsed = time.time() - start_time
                    self.logger.error(f"❌ 音声認識スレッドエラー {elapsed:.1f}秒後: %s", e)
                    self.logger.exception("詳細な音声認識エラー:")
            
            transcription_thread = threading.Thread(target=run_transcription, daemon=True)
            transcription_thread.start()
            self.logger.info("🚀 音声認識スレッド開始")
            
            # WebSocket音声データを処理
            await self._handle_websocket_audio(websocket, audio_queue, session_data)
            
        except Exception as e:
            self.logger.error("リアルタイム音声認識失敗: %s", e)
            # フォールバックとしてモック音声認識を開始
            await self._start_mock_transcription(session_data, websocket, on_transcript_callback)

    async def _handle_websocket_audio(
        self, 
        websocket: WebSocket, 
        audio_queue: queue.Queue, 
        session_data: dict
    ) -> None:
        """WebSocketから音声データを受信してキューに追加"""
        audio_count = 0
        last_audio_time = time.time()
        start_time = time.time()
        
        # 🔍 接続ヘルスモニタリング
        self.logger.info(f"🚀 WebSocket音声ハンドラー開始 meeting: {session_data['meeting_id']}")
        
        try:
            while True:
                try:
                    # タイムアウトで接続の詰まりを検出
                    message = await asyncio.wait_for(websocket.receive(), timeout=30.0)
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time
                    self.logger.warning(f"⏰ WebSocket受信タイムアウト 30秒後 (総実行時間: {elapsed:.1f}s)")
                    break
                
                if message.get("type") == "websocket.disconnect":
                    elapsed = time.time() - start_time
                    self.logger.info(f"🔌 WebSocket切断メッセージ受信 (実行時間: {elapsed:.1f}s)")
                    break
                
                data = message.get("bytes")
                if data and len(data) > 0:
                    # 音声データをキューに追加
                    audio_queue.put(data)
                    audio_count += 1
                    last_audio_time = time.time()
                    
                    # 🔍 デバッグ用詳細ログ
                    if audio_count % 100 == 0:  # 100チャンクごと
                        elapsed = time.time() - start_time
                        self.logger.info(f"🎤 音声ヘルスチェック: {audio_count} チャンク, {elapsed:.1f}s実行時間, キューサイズ: {audio_queue.qsize()}")
                        
                elif message.get("text"):
                    self.logger.info(f"📝 テキストメッセージ受信: {message['text']}")
                    if message["text"] == "close":
                        break
                else:
                    # 予期しないメッセージタイプをログ
                    self.logger.debug(f"予期しないメッセージタイプ: {message}")
                
                # 🔍 無音検出（より頻繁にチェック）
                current_time = time.time()
                silence_duration = current_time - last_audio_time
                if silence_duration > 30:  # 60秒ではなく30秒ごとにチェック
                    elapsed = current_time - start_time
                    self.logger.warning(f"⚠️ 音声無音検出: {silence_duration:.1f}s (総実行時間: {elapsed:.1f}s)")
                        
        except WebSocketDisconnect:
            elapsed = time.time() - start_time
            self.logger.info(f"🔌 音声処理中にWebSocket切断 (実行時間: {elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(f"❌ WebSocket音声処理エラー {elapsed:.1f}s後: {e}")
            self.logger.exception("詳細エラー:")
        finally:
            # 音声ストリーム終了を通知
            audio_queue.put(None)
            elapsed = time.time() - start_time
            self.logger.info(f"🔚 音声処理終了: {audio_count} チャンク処理 {elapsed:.1f}s")

    async def _start_mock_transcription(
        self, 
        session_data: dict, 
        websocket: WebSocket,
        on_transcript_callback
    ) -> None:
        """テスト用のモック音声認識"""
        meeting_id = session_data["meeting_id"]
        self.logger.info("モック音声認識開始 meeting_id=%s", meeting_id)
        
        mock_phrases = [
            "こんにちは、テストです",
            "音声認識のテストを行っています", 
            "マイクの音声が正常に送信されています",
            "文字起こし機能が動作しています",
            "リアルタイム分析のテストです"
        ]
        
        phrase_index = 0
        
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                    
                data = message.get("bytes")
                if data:
                    # 3秒ごとに音声認識をシミュレート
                    await asyncio.sleep(3)
                    phrase = mock_phrases[phrase_index % len(mock_phrases)]
                    
                    # モック結果を作成
                    mock_result = {
                        "transcript": phrase,
                        "is_partial": False,
                        "speaker_label": "spk_mock_a" if phrase_index % 2 else "spk_mock_b",
                        "result_id": f"mock-{phrase_index + 1}"
                    }
                    
                    # コールバックを呼び出し
                    await on_transcript_callback(mock_result)
                    phrase_index += 1
                    
        except WebSocketDisconnect:
            pass

    def estimate_speaker_by_patterns(self, session_data: dict, transcript: str, is_final: bool) -> str:
        """
        音声パターンに基づく話者推定（話者識別がない場合のフォールバック）
        """
        # 話者推定の状態管理
        if "speaker_detection_state" not in session_data:
            session_data["speaker_detection_state"] = {
                "current_speaker_id": 0,
                "last_final_time": 0,
                "last_text_length": 0,
                "silence_count": 0,
                "utterance_count": 0
            }
        
        state = session_data["speaker_detection_state"]
        current_time = time.time()
        
        if not is_final:  # 部分結果では話者変更しない
            return f"spk_{state['current_speaker_id']}"
        
        # 最終結果のみで話者変更を判定
        state["utterance_count"] += 1
        time_gap = current_time - state["last_final_time"]
        
        # 話者変更の判定（複数要因）:
        # 1. 長い沈黙（>2秒）
        # 2. テキスト長パターンの大幅変化
        # 3. 4-6発言ごと（自然な会話フロー）
        
        should_change_speaker = False
        change_reason = ""
        
        if time_gap > 2.5 and state["last_final_time"] > 0:
            should_change_speaker = True
            change_reason = f"silence_gap_{time_gap:.1f}s"
        elif state["utterance_count"] % 5 == 0:  # 5発言ごと
            should_change_speaker = True
            change_reason = f"utterance_count_{state['utterance_count']}"
        
        if should_change_speaker:
            state["current_speaker_id"] = (state["current_speaker_id"] + 1) % 4  # 4話者でサイクル
            self.logger.info(f"話者変更検出: {change_reason} -> spk_{state['current_speaker_id']}")
        
        state["last_final_time"] = current_time
        state["last_text_length"] = len(transcript)
        
        return f"spk_{state['current_speaker_id']}"

    async def handle_transcript_result(
        self, 
        session_data: dict, 
        result: dict,
        speaker_manager,
        analysis_handler
    ) -> None:
        """
        音声認識結果を処理（話者識別、自動確定、分析を統合）
        """
        transcript = result.get("transcript", "").strip()
        is_partial = result.get("is_partial", False)
        
        # 誤字修正を適用
        transcript = self._apply_typo_corrections(transcript)
        
        if not transcript:
            self.logger.debug("空の音声認識結果、スキップ")
            return
        
        # 話者情報を取得
        raw_speaker = result.get("speaker_label")
        if not raw_speaker:
            # 話者識別がない場合はパターンベースで推定
            raw_speaker = self.estimate_speaker_by_patterns(session_data, transcript, not is_partial)
            self.logger.info(f"パターンベース話者推定: {raw_speaker}")
        else:
            self.logger.info(f"AWS話者ラベル: {raw_speaker}")
        
        speaker_label = speaker_manager.get_speaker_name(session_data, raw_speaker)
        self.logger.info(f"最終話者マッピング: {raw_speaker} -> {speaker_label}")
        
        # 結果IDを生成
        aws_result_id = result.get("result_id") or result.get("ResultId")
        if aws_result_id:
            result_id = f"aws_{aws_result_id}"
        else:
            # 簡易フォールバック: 最終結果まで同じ発話ID
            if is_partial:
                if session_data.get('current_utterance_id') is None:
                    session_data['current_utterance_id'] = f"session_{session_data['next_entry_index']}"
                result_id = session_data['current_utterance_id']
            else:
                if session_data.get('current_utterance_id') is not None:
                    result_id = session_data['current_utterance_id']
                    session_data['current_utterance_id'] = None  # 次の発話用にリセット
                else:
                    result_id = f"session_{session_data['next_entry_index']}"
        
        # 音声認識結果を処理（自動確定付き）
        await self._handle_result_with_auto_finalize(
            session_data, result_id, speaker_label, raw_speaker, transcript, not is_partial, speaker_manager
        )
        
        # 🚀 リアルタイム分析: 5文字以上の場合に分析
        if len(transcript.strip()) >= 5:
            unique_index = session_data["next_entry_index"] * 1000
            
            # 意味のある更新のみBedrock送信（案3）
            should_send_bedrock = self._should_send_to_bedrock(
                session_data, result_id, transcript
            )
            
            # 即座に分析を実行（キーワードベースは常に実行）
            asyncio.create_task(analysis_handler.classify_and_send_realtime(
                session_data, transcript, speaker_label, unique_index, 
                force_bedrock=should_send_bedrock
            ))
            


    async def _handle_result_with_auto_finalize(
        self, 
        session_data: dict, 
        result_id: str, 
        speaker_label: str, 
        raw_label: str, 
        text: str, 
        is_final: bool,
        speaker_manager
    ) -> None:
        """時間ベース自動確定付きの音声認識結果処理"""
        
        entry = session_data["pending_results"].get(result_id)
        current_time = time.time()
        
        if not entry:
            # 新しいエントリを作成
            entry = {
                "index": session_data["next_entry_index"],
                "speaker": speaker_label,
                "raw_speaker": raw_label,
                "result_id": result_id,
                "text": text,
                "timestamp": now_iso(),
                "last_update_time": current_time,  # 🕒 最終更新時刻を追跡
                "auto_finalize_task": None,  # 🕒 自動確定タスクを追跡
            }
            session_data["next_entry_index"] += 1
            session_data["pending_results"][result_id] = entry
            
            # キューに追加メッセージを送信
            await session_data["queue"].put({
                "type": "transcript",
                "action": "append",
                "payload": self._create_public_payload(entry)
            })
            
            # 🕒 自動確定タイマーを開始（文の区切りを考慮）
            delay = self._calculate_auto_finalize_delay(text)
            entry["auto_finalize_task"] = asyncio.create_task(
                self._auto_finalize_after_delay(session_data, result_id, delay)
            )
            self.logger.info(f"⏰ 新エントリの自動確定タイマー作成: {result_id}")
        else:
            # 既存エントリを更新
            entry["text"] = text
            entry["last_update_time"] = current_time
            
            # 🕒 更新があったので自動確定タイマーをリセット
            if entry.get("auto_finalize_task") and not entry["auto_finalize_task"].done():
                entry["auto_finalize_task"].cancel()
                self.logger.info(f"⏰ 更新により自動確定タイマーキャンセル: {result_id}")
            
            # poc_satomin準拠の話者ラベル安定性
            # 不明 -> 既知への一回限りの更新のみ
            current_raw = entry.get("raw_speaker", "spk_unk")
            if speaker_manager.is_unknown_label(current_raw) and not speaker_manager.is_unknown_label(raw_label):
                entry["raw_speaker"] = raw_label
                entry["speaker"] = speaker_label
                await session_data["queue"].put({
                    "type": "transcript",
                    "action": "update",
                    "payload": self._create_public_payload(entry)
                })

            # テキストと話者が同じかチェック（早期リターン）
            if entry["text"] == text and entry["speaker"] == speaker_label:
                if is_final:
                    await self._finalize_result(session_data, result_id)
                return
            
            # キューに更新を送信
            await session_data["queue"].put({
                "type": "transcript",
                "action": "update",
                "payload": self._create_public_payload(entry)
            })
            
            # 🚨 200字を超えた場合は即座に確定
            if len(text.strip()) >= 200:
                self.logger.info(f"📏 200字超過により強制確定: '{text[:50]}...' ({len(text)}文字)")
                # 既存のタイマーをキャンセル
                if entry.get("auto_finalize_task") and not entry["auto_finalize_task"].done():
                    entry["auto_finalize_task"].cancel()
                # 即座に確定
                await self._finalize_result(session_data, result_id, auto_finalized=True)
                return
            
            # 🕒 更新されたエントリの自動確定タイマーを再開（文の区切りを考慮）
            if not is_final:
                delay = self._calculate_auto_finalize_delay(text)
                entry["auto_finalize_task"] = asyncio.create_task(
                    self._auto_finalize_after_delay(session_data, result_id, delay)
                )
                self.logger.info(f"⏰ 更新エントリの自動確定タイマー再開: {result_id} (遅延: {delay}s)")
        
        # 最終結果の処理
        if is_final:
            # 自動確定タイマーが存在する場合はキャンセル
            if entry.get("auto_finalize_task") and not entry["auto_finalize_task"].done():
                entry["auto_finalize_task"].cancel()
                self.logger.info(f"⏰ AWS最終結果により自動確定タイマーキャンセル: {result_id}")
            await self._finalize_result(session_data, result_id)

    async def _auto_finalize_after_delay(self, session_data: dict, result_id: str, delay_seconds: float) -> None:
        """🕒 指定遅延後に音声認識エントリを自動確定"""
        try:
            self.logger.info(f"⏰ 自動確定タイマー開始 result_id: {result_id}, 遅延: {delay_seconds}s")
            await asyncio.sleep(delay_seconds)
            
            # エントリがまだ存在し、確定されていないかチェック
            if result_id in session_data["pending_results"]:
                entry = session_data["pending_results"][result_id]
                self.logger.info(f"⏰ {delay_seconds}s後に音声認識を自動確定: '{entry['text'][:50]}...'")
                
                # このエントリを強制確定
                await self._finalize_result(session_data, result_id, auto_finalized=True)
            else:
                self.logger.info(f"⏰ 自動確定タイマー期限切れだが result_id {result_id} は既に確定済み")
                
        except asyncio.CancelledError:
            # タイマーがキャンセルされた（AWSが最終結果を送信した場合は正常）
            self.logger.info(f"⏰ 自動確定タイマーキャンセル result_id: {result_id} (正常 - AWS最終結果送信)")
        except Exception as e:
            self.logger.error(f"⏰ 自動確定エラー result_id {result_id}: {e}")
            self.logger.exception("自動確定詳細エラー:")

    async def _finalize_result(self, session_data: dict, result_id: str, auto_finalized: bool = False) -> None:
        """音声認識結果を確定"""
        if result_id in session_data["pending_results"]:
            entry = session_data["pending_results"].pop(result_id)
            
            # 自動確定タイマーが存在する場合はキャンセル
            if entry.get("auto_finalize_task") and not entry["auto_finalize_task"].done():
                entry["auto_finalize_task"].cancel()
            
            payload = self._create_public_payload(entry)
            
            # デバッグ用の自動確定フラグを追加
            if auto_finalized:
                payload["auto_finalized"] = True
                self.logger.info(f"✅ 自動確定: '{payload['text'][:50]}...'")
            
            session_data["transcripts"].append(payload)
            
            # キューに確定メッセージを送信
            await session_data["queue"].put({
                "type": "transcript",
                "action": "finalize",
                "payload": payload
            })

    def _should_send_to_bedrock(self, session_data: dict, result_id: str, current_text: str) -> bool:
        """段階的な発言で長さが大幅に増加した場合のみBedrockに送信"""
        
        # Bedrock送信履歴を管理
        if 'bedrock_history' not in session_data:
            session_data['bedrock_history'] = {}
        
        history = session_data['bedrock_history']
        last_sent_text = history.get(result_id, "")
        
        # 1. 最初の送信（10文字以上になった時点）
        if not last_sent_text and len(current_text) >= 10:
            history[result_id] = current_text
            self.logger.info(f"📊 Bedrock送信: 初回送信 ({len(current_text)}文字)")
            return True
        
        # 2. 長さが50%以上増加した場合
        if last_sent_text and len(last_sent_text) > 0:
            length_ratio = len(current_text) / len(last_sent_text)
            if length_ratio >= 1.5:  # 50%以上増加
                history[result_id] = current_text
                self.logger.info(f"📊 Bedrock送信: 長さ大幅増加 {len(last_sent_text)} → {len(current_text)}文字")
                return True
        
        self.logger.debug(f"📊 Bedrock送信スキップ: {len(last_sent_text)} → {len(current_text)}文字 (増加率: {len(current_text)/max(len(last_sent_text), 1):.1f}倍)")
        return False

    def _calculate_auto_finalize_delay(self, text: str) -> float:
        """文の区切りを考慮した自動確定遅延時間を計算"""
        text_stripped = text.strip()
        
        # 200字を超えた場合は即座に確定
        if len(text_stripped) >= 200:
            return 1.0  # 1秒で強制確定
        
        # 句読点で終わっている場合は短めに確定
        elif text_stripped.endswith(('。', '！', '？', '.')):
            return 4.0  # 4秒で確定
        
        # 読点で終わっている場合は中程度
        elif text_stripped.endswith(('、', ',')):
            return 6.0  # 6秒で確定
        
        # 文の途中の場合は長めに待機
        else:
            return 10.0  # 10秒で確定
    
    def _create_public_payload(self, entry: dict) -> dict:
        """WebSocket送信用の公開ペイロードを作成"""
        return {
            "index": entry["index"],
            "speaker": entry["speaker"],
            "raw_speaker": entry.get("raw_speaker"),
            "result_id": entry.get("result_id"),
            "text": entry["text"],
            "timestamp": entry["timestamp"],
        }

    # _is_unknown_labelメソッドはspeaker_manager.pyに統合済み
    def _apply_typo_corrections(self, text: str) -> str:
        """
        音声認識の誤字を修正する
        """
        if not text:
            return text
        
        # 誤字修正辞書
        corrections = {
            # ワッカソン関連
            "マッカさん": "ワッカソン",
            "マッカ": "ワッカ",
            "まっか": "ワッカ",
            "わっか": "ワッカ",
            "ワッカさん": "ワッカソン",
            "ワッカーソン": "ワッカソン",
            
            # 一般的な音声認識誤字
            "1個ですか": "いかがですか",
            "一個ですか": "いかがですか",
            "いっこですか": "いかがですか",
            "内田せ": "打合せ",
            "内田": "打合",  # 「内田会議」→「打合会議」等
            "4五歳": "仕事",
            "四五歳": "仕事",
            
        }
        
        corrected_text = text
        for typo, correction in corrections.items():
            corrected_text = corrected_text.replace(typo, correction)
        
        # 修正があった場合はログ出力
        if corrected_text != text:
            self.logger.info(f"🔧 誤字修正: '{text}' → '{corrected_text}'")
        
        return corrected_text