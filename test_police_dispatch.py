#!/usr/bin/env python3
"""
警察出動Lambda関数呼び出しのテストスクリプト
"""

import asyncio
import logging
from datetime import datetime

from backend.services.lambda_client import LambdaClient
from backend.utils.time_utils import now_iso

# ログ設定を強化
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('test_lambda_calls.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Lambda関数呼び出し専用のログレベルを設定
lambda_logger = logging.getLogger('backend.services.lambda_client')
lambda_logger.setLevel(logging.INFO)


async def test_police_dispatch():
    """警察出動Lambda関数のテスト（obniz2 LED ON）"""
    logger.info("🚨 警察出動Lambda関数テスト開始（obniz2 LED ON）")
    
    # LambdaClientを初期化
    lambda_client = LambdaClient()
    
    # テスト用の会議データ（簡略化）
    test_meeting_data = {
        "meeting_id": "test-meeting-001",
        "timestamp": now_iso(),
        "alignment_score": 15,
        "recent_transcript": "今日の天気はいいですね。ところで昨日のサッカーの試合見ましたか？",
        "speaker": "Speaker 2",
    }
    
    try:
        # Lambda関数を呼び出し
        logger.info("Lambda関数を呼び出し中...")
        result = await asyncio.to_thread(
            lambda_client.invoke_police_dispatch,
            test_meeting_data
        )
        
        logger.info("✅ Lambda関数呼び出し完了")
        logger.info(f"結果: {result}")
        
        # 結果の詳細を表示
        if result.get("statusCode") == 200:
            logger.info("🎉 obniz2 LED ONが正常に送信されました")
            logger.info(f"  - 出動ID: {result.get('dispatchId')}")
            logger.info(f"  - メッセージ: {result.get('message')}")
            logger.info(f"  - LED状態: {result.get('led_status')}")
        else:
            logger.warning("⚠️ obniz2 LED ONでエラーが発生しました")
            logger.warning(f"  - エラー: {result.get('error')}")
            logger.warning(f"  - メッセージ: {result.get('message')}")
            
    except Exception as e:
        logger.error(f"❌ テスト実行中にエラーが発生: {e}")


async def test_police_dispatch_off():
    """警察出動解除Lambda関数のテスト（obniz2 LED OFF）"""
    logger.info("🟢 警察出動解除Lambda関数テスト開始（obniz2 LED OFF）")
    
    # LambdaClientを初期化
    lambda_client = LambdaClient()
    
    # テスト用の会議データ（簡略化）
    test_meeting_data = {
        "meeting_id": "test-meeting-001",
        "timestamp": now_iso(),
        "alignment_score": 65,
        "recent_transcript": "それでは議題に戻りまして、今四半期の売上について報告いたします。",
        "speaker": "Speaker 1",
    }
    
    try:
        # Lambda関数を呼び出し
        logger.info("Lambda関数を呼び出し中...")
        result = await asyncio.to_thread(
            lambda_client.invoke_police_dispatch_off,
            test_meeting_data
        )
        
        logger.info("✅ Lambda関数呼び出し完了")
        logger.info(f"結果: {result}")
        
        # 結果の詳細を表示
        if result.get("statusCode") == 200:
            logger.info("🎉 obniz2 LED OFFが正常に送信されました")
            logger.info(f"  - 出動ID: {result.get('dispatchId')}")
            logger.info(f"  - メッセージ: {result.get('message')}")
            logger.info(f"  - LED状態: {result.get('led_status')}")
        else:
            logger.warning("⚠️ obniz2 LED OFFでエラーが発生しました")
            logger.warning(f"  - エラー: {result.get('error')}")
            logger.warning(f"  - メッセージ: {result.get('message')}")
            
    except Exception as e:
        logger.error(f"❌ テスト実行中にエラーが発生: {e}")


async def test_alert_escalation():
    """アラートエスカレーションLambda関数のテスト"""
    logger.info("⚠️ アラートエスカレーションLambda関数テスト開始")
    
    # LambdaClientを初期化
    lambda_client = LambdaClient()
    
    # テスト用のエスカレーションデータ
    test_escalation_data = {
        "meeting_id": "test-meeting-001",
        "escalation_level": "MEDIUM",
        "previous_alerts": [
            {"timestamp": now_iso(), "level": "LOW", "alignment": 45},
            {"timestamp": now_iso(), "level": "MEDIUM", "alignment": 35}
        ],
        "current_alignment": 30,
        "duration_low_alignment": 180,  # 3分間
        "timestamp": now_iso()
    }
    
    try:
        # Lambda関数を呼び出し
        logger.info("アラートエスカレーションLambda関数を呼び出し中...")
        result = await asyncio.to_thread(
            lambda_client.invoke_alert_escalation,
            test_escalation_data
        )
        
        logger.info("✅ アラートエスカレーションLambda関数呼び出し完了")
        logger.info(f"結果: {result}")
        
        # 結果の詳細を表示
        if result.get("statusCode") == 200:
            logger.info("🎉 アラートエスカレーションが正常に処理されました")
            logger.info(f"  - エスカレーションID: {result.get('escalationId')}")
            logger.info(f"  - メッセージ: {result.get('message')}")
        else:
            logger.warning("⚠️ アラートエスカレーションでエラーが発生しました")
            logger.warning(f"  - エラー: {result.get('error')}")
            logger.warning(f"  - メッセージ: {result.get('message')}")
            
    except Exception as e:
        logger.error(f"❌ テスト実行中にエラーが発生: {e}")


async def main():
    """メインテスト関数"""
    logger.info("=" * 60)
    logger.info("obniz2警察出動システム テストスイート")
    logger.info("=" * 60)
    
    # 警察出動テスト（LED ON）
    await test_police_dispatch()
    
    logger.info("-" * 40)
    
    # 警察出動解除テスト（LED OFF）
    await test_police_dispatch_off()
    
    logger.info("-" * 40)
    
    # アラートエスカレーションテスト
    await test_alert_escalation()
    
    logger.info("=" * 60)
    logger.info("テスト完了")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())