#!/usr/bin/env python3
"""
VonageClient の新しい実装をテストするスクリプト
"""

import sys
import logging
from pathlib import Path

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))

def test_vonage_client():
    """VonageClient の基本機能をテスト"""
    print("=" * 50)
    print("VonageClient テスト開始")
    print("=" * 50)
    
    try:
        # VonageClient をインポート
        from backend.services.vonage_client import VonageClient
        print("✅ VonageClient のインポート成功")
        
        # クライアントを初期化
        client = VonageClient()
        print("✅ VonageClient の初期化成功")
        
        # モードを確認
        is_real = client.is_real_mode()
        print(f"📊 動作モード: {'Real Vonage API' if is_real else 'Mock Mode'}")
        
        # セッション作成テスト
        print("\n--- セッション作成テスト ---")
        meeting_id = "test-meeting-123"
        session_result = client.create_session(meeting_id)
        print(f"✅ セッション作成成功: {session_result}")
        
        # トークン生成テスト
        print("\n--- トークン生成テスト ---")
        session_id = session_result["session_id"]
        token = client.generate_token(session_id, role="publisher")
        print(f"✅ トークン生成成功: {token[:50]}...")
        
        # セッション情報取得テスト
        print("\n--- セッション情報取得テスト ---")
        session_info = client.get_session_info(session_id)
        print(f"✅ セッション情報取得成功: {session_info}")
        
        print("\n" + "=" * 50)
        print("🎉 すべてのテストが成功しました！")
        print("=" * 50)
        
        return True
        
    except ImportError as e:
        print(f"❌ インポートエラー: {e}")
        return False
    except Exception as e:
        print(f"❌ テスト実行エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_settings_loading():
    """設定ファイルの読み込みテスト"""
    print("\n--- 設定ファイル読み込みテスト ---")
    
    try:
        from backend.services.vonage_client import get_settings
        settings = get_settings()
        
        print(f"Vonage Application ID: {getattr(settings, 'vonage_application_id', 'Not found')[:8]}...")
        print(f"Vonage API Key: {getattr(settings, 'vonage_api_key', 'Not found')[:8]}...")
        print(f"Private Key Path: {getattr(settings, 'vonage_private_key_path', 'Not found')}")
        
        return True
    except Exception as e:
        print(f"❌ 設定読み込みエラー: {e}")
        return False

if __name__ == "__main__":
    # 設定テスト
    settings_ok = test_settings_loading()
    
    # メインテスト
    test_ok = test_vonage_client()
    
    if test_ok and settings_ok:
        print("\n🎉 全体テスト成功！")
        sys.exit(0)
    else:
        print("\n❌ テストに失敗しました")
        sys.exit(1)