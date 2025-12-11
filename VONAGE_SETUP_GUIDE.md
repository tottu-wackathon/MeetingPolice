# Vonage Video API Real Mode セットアップガイド

## 1. Vonage Dashboardでの設定

### Application作成
1. [Vonage Dashboard](https://dashboard.nexmo.com/) にログイン
2. **Applications** → **Create a new application**
3. **Video** capabilityを有効化
4. Application IDをコピー（例: `12345678-1234-1234-1234-123456789abc`）

### Private Key取得
1. Applicationページで **Generate public and private key**
2. `private.key` ファイルをダウンロード
3. プロジェクトの `secrets/vonage_private.key` に配置

## 2. 環境変数の設定

`.env` ファイルに以下を設定：

```bash
# Vonage Video API設定
VONAGE_APPLICATION_ID=your_application_id_here
VONAGE_API_KEY=your_api_key_here  # 通常はApplication IDと同じ
VONAGE_PRIVATE_KEY_PATH=secrets/vonage_private.key
```

## 3. Private Keyファイルの配置

```bash
# secretsディレクトリを作成（存在しない場合）
mkdir -p secrets

# private.keyファイルを配置
# ファイル内容は以下の形式：
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...
（実際のキー内容）
-----END PRIVATE KEY-----
```

## 4. 動作確認

```python
from backend.services.vonage_client import VonageClient

client = VonageClient()
print("Real Mode:", client.is_real_mode())  # True になるはず

# セッション作成テスト
session = client.create_session("test-meeting")
print("Session:", session)

# トークン生成テスト
token = client.generate_token(session["session_id"])
print("Token:", token[:50] + "...")
```

## 5. トラブルシューティング

### Mock Modeから抜けられない場合
- `VONAGE_APPLICATION_ID` が設定されているか確認
- `secrets/vonage_private.key` ファイルが存在するか確認
- Private keyが正しいPEM形式か確認（`-----BEGIN PRIVATE KEY-----` で始まる）

### エラーが発生する場合
- Vonage Dashboardでアプリケーションが正しく作成されているか確認
- Video capabilityが有効になっているか確認
- Private keyファイルの権限を確認

## 6. 新機能のテスト

Real Modeが有効になったら、以下の新機能をテストできます：

```python
# 異なるメディアモード
session_routed = client.create_session("meeting1", media_mode="routed")
session_relayed = client.create_session("meeting2", media_mode="relayed")

# 自動アーカイブ
session_archived = client.create_session("meeting3", archive_mode="always")

# 地理的ヒント
session_location = client.create_session("meeting4", location="12.34.56.78")

# 異なるロールのトークン
publisher_token = client.generate_token(session_id, role="publisher")
subscriber_token = client.generate_token(session_id, role="subscriber")
moderator_token = client.generate_token(session_id, role="moderator")
```

## 7. セキュリティ注意事項

- Private keyファイルは `.gitignore` に追加
- 本番環境では環境変数で管理
- トークンのTTLを適切に設定（デフォルト5分）