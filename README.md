# MeetingPolice

# MeetingPolice

MeetingPolice は、会議のライブ文字起こし・分類・要約を行い、参加者向けの UI と管理者向けの UI をまとめて提供するデモ実装です。フロントエンドは Vite + React、バックエンドは FastAPI。AWS（Transcribe / Comprehend / Bedrock / S3）と Vonage Video を前提にしていますが、各サービスにはフォールバックを用意し、ネットワークなしでも動作を確認できます。

## 全体構成

- `backend/`: FastAPI アプリ。`main.py` がルータを束ね、`config.py` が環境変数を管理。
  - `session/`: 参加者向け API。Vonage JWT を払い出し、WebSocket `/api/session/ws/{meeting_id}` で Transcribe 文字起こし＋ Comprehend 感情判定を配信。
  - `admin/`: 管理者向け API。会議の作成・一覧と、S3 上の transcript を Bedrock で要約する `/summary` を提供。
  - `poc/`: アジェンダ + 音声を受け取り、Amazon Transcribe Streaming で文字起こし。Bedrock 要約/分類と Comprehend 感情分析、S3 へのアーカイブ、履歴取得・再分類 API を実装。
  - `poc_satomin/`: リアルタイム分類強化版。話者ラベルが未判別の間は「判別中...」に固定しつつ、確定発話ごとに Bedrock/キーワードのハイブリッドで分類し、アジェンダとの一致度低下を検知して警告を出せる。
  - `services/`: AWS / Vonage ラッパー。`bedrock_utils.py`（分類・要約・埋め込み）、`transcribe_stream.py`、`s3_storage.py`（S3 失敗時は `backend/data/s3/` 保存）、`repository.py`（`backend/data/meetings.json` を JSON ストアとして使用）など。
  - `models/`: Meeting / Transcript / Summary などの Pydantic モデル。
  - `utils/`: AWS/Boto 認証ヘルパー、Vonage 認証、ログ設定、時刻ユーティリティ。
  - `data/`: ローカル永続化の保存先。`poc/` 配下にジョブデータ、`s3/poc/` にアーカイブ済み JSON がたまります（リポジトリには一部サンプルが含まれます）。
- `frontend/`
  - `session-app/`: 参加者 UI。`SessionPage` で Vonage 参加・文字起こし・メトリクス表示を提供。`PocPage` は `/api/poc` と接続し、アップロード→WebSocket 文字起こし→Bedrock/Comprehend 分析→履歴閲覧までを 1 画面で体験可能。`PocSatominPage` はリアルタイム分類と一致度モニタリング、音声アラート/警告バナー、発話ボリューム集計や予定時間カウントダウンを備える。
  - `admin-app/`: 管理者 UI。ミーティング作成・一覧・要約生成の 1 ページ構成 (`MeetingsPage`) で、最新 Meeting ID の共有カードや Bedrock 要約表示を搭載。
  - 共通で `src/components`, `src/hooks`, `src/services/api.ts` を持ち、`frontend/README.md` に構成メモがあります。
- `docs/`: EC2 構築手順 (`MeetingPoliceEC2-SetupGuide.md`)、CloudFormation テンプレート (`MeetingPoliceEC2-t3small.yaml`)、PoC 分析フロー (`POC_ANALYSIS.md`)、サンプル SSML (`meeting_part1.ssml`)。
- `scripts/`: 開発・デプロイ補助。`start_dev.sh`（FastAPI + 2 つの Vite dev server 起動）、`start_backend.sh`、`start_frontend.sh`（Nginx 反映付きビルド）、`.env` テンプレート生成、S3 同期など。
- `nginx/`: `default.conf` にフロントの静的配信と FastAPI へのプロキシを定義。
- `tests/`: pytest。`test_api_session.py` / `test_api_admin.py` にルータのスモーク、`test_bedrock.py` / `test_s3_storage.py` / `test_transcribe.py` / `test_comprehend.py` で AWS 連携ラッパーのフォールバックを検証。
- `secrets/`: Vonage RSA 秘密鍵等の配置先（`.gitignore` 済み）。

## 主要機能の流れ

- **参加者フロー (`session`)**: 管理者が発行した Meeting ID を入力して Vonage セッションへ参加。WebSocket で音声を送ると Transcribe 文字起こしと Comprehend 感情が即時返却され、UI に表示されます（資格情報がない場合はモックが返る）。
- **管理者フロー (`admin`)**: ミーティングを作成すると JSON ストアに保存。必要に応じて S3 の transcript を Bedrock で要約し、結果キーをメタデータに保存。
- **PoC 一括分析 (`poc`)**: `/api/poc/start` でアジェンダ＋音声をアップロード → Transcribe Streaming で発話単位に確定 → Bedrock で要約・分類、Comprehend で感情判定 → S3/ローカルへアーカイブ。履歴一覧・詳細・再分類 API を備え、フロントの履歴パネルから呼び出します。
- **PoC リアルタイム分析 (`poc_satomin`)**: 確定発話を受けるたびにキーワード即時分類＋バックグラウンド Bedrock 再判定を実施。話者ラベルの安定化（`spk_unk` は固定）、長文の分割、アジェンダとの一致度算出を行い、一致度低下時は警告/「警察出動」バナーや音声アラートをトリガー。タイマーで予定時間超過も可視化。

## 開発手順

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`（`amazon-transcribe` などストリーミングに必要な依存も含む）
3. `cp .env.example .env` で環境変数を用意し、AWS/Vonage の値を設定（IAM ロール利用時も `AWS_REGION` は必須）。
4. `secrets/vonage_private.key` に RSA 秘密鍵を置く（未設定ならモックトークンで動作確認可）。
5. `./scripts/start_dev.sh` で FastAPI + 2 つの Vite Dev Server をまとめて起動。
   - API だけ確認する場合は `./scripts/start_backend.sh`、ビルドと Nginx 配置まで行う場合は `./scripts/start_frontend.sh` を使用。
6. テスト実行は `pytest`。AWS 呼び出しは Stub/ローカルフォールバックでカバーされるためネットワーク不要。

> `docs/MeetingPoliceEC2-t3small.yaml` の user-data では Node.js 20 導入・依存インストール・両フロントビルドまで自動実行します。CloudFormation で t3.small を立てるだけでデモ環境を再現できます。

## 参考資料

- `/docs/POC_ANALYSIS.md`: `/poc` ジョブを Bedrock/Comprehend に渡す推奨フロー。
- `/docs/MeetingPoliceEC2-SetupGuide.md`: EC2 での構築手順。
- `/frontend/README.md`: 両 Vite アプリのフォルダ構成メモ。
