#!/usr/bin/env python3
"""
警察出動Lambda関数呼び出しのテストスクリプト
"""

import asyncio
import logging

from backend.services.lambda_client import LambdaClient

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
    """警察出動Lambda関数のテスト（obniz2 LED ON→5秒後に自動OFF）"""
    logger.info("🚨 警察出動Lambda関数テスト開始（obniz2 LED ON→自動OFF）")

    lambda_client = LambdaClient()

    try:
        logger.info("Lambda関数を呼び出し中...")
        result = await asyncio.to_thread(lambda_client.trigger_police_dispatch)

        logger.info("✅ Lambda関数呼び出し完了: %s", result)

        if result.get("statusCode") == 200:
            logger.info("🎉 obniz2 LED ONが正常に送信されました（OFFは自動処理）")
        else:
            logger.warning("⚠️ obniz2 LED ONでエラーが発生しました: %s", result)
    except Exception as e:
        logger.error(f"❌ テスト実行中にエラーが発生: {e}")


async def test_result_led():
    """結果画面用LED（4378-7530）のON/OFFテスト"""
    logger.info("🎉 結果LEDテスト開始（ON→OFF）")

    lambda_client = LambdaClient()

    try:
        logger.info("結果LEDをONにします...")
        on_result = await asyncio.to_thread(lambda_client.trigger_result_led, True)
        logger.info("✅ 結果LED ON送信完了: %s", on_result)

        logger.info("結果LEDをOFFにします...")
        off_result = await asyncio.to_thread(lambda_client.trigger_result_led, False)
        logger.info("✅ 結果LED OFF送信完了: %s", off_result)
    except Exception as e:
        logger.error(f"❌ 結果LEDテストでエラーが発生: {e}")


async def main():
    """メインテスト関数"""
    logger.info("=" * 60)
    logger.info("obniz2警察出動システム テストスイート")
    logger.info("=" * 60)
    
    # 警察出動テスト（LED ON）
    await test_police_dispatch()
    
    logger.info("-" * 40)
    
    # 結果LEDテスト（ON/OFF）
    await test_result_led()
    
    logger.info("=" * 60)
    logger.info("テスト完了")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
