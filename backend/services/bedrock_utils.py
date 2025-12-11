from __future__ import annotations

import json
import re
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from backend.config import get_settings
from backend.utils.auth_aws import get_session

CLASSIFICATION_LABELS = ["議事進行", "報告", "提案", "相談", "質問", "回答", "決定", "コメント", "無関係な雑談"]


def _bedrock_client(client: Any | None = None):
    if client:
        return client
    session = get_session()
    return session.client("bedrock-runtime", region_name=get_settings().aws_region)


def _load_json_body(response: dict[str, Any]) -> dict[str, Any]:
    body = response.get("body")
    if hasattr(body, "read"):
        raw = body.read()
    elif isinstance(body, (bytes, bytearray)):
        raw = body
    elif body is None:
        return {}
    else:
        raw = str(body).encode("utf-8")
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {"outputText": raw.decode("utf-8")}


def _model_uses_messages(model_id: str) -> bool:
    return "claude-3" in (model_id or "").lower()


def _invoke_text_model(prompt: str, max_tokens: int, temperature: float, client: Any | None = None) -> dict[str, Any]:
    settings = get_settings()
    model_id = settings.bedrock_model_id
    if _model_uses_messages(model_id):
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        }
    else:
        payload = {
            "prompt": prompt,
            "maxTokens": max_tokens,
            "temperature": temperature,
        }

    response = _bedrock_client(client).invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )
    return _load_json_body(response)


def _extract_text_from_content(content: dict[str, Any]) -> str:
    for key in ("outputText", "completion", "response"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    message_content = content.get("content")
    if isinstance(message_content, list):
        pieces: list[str] = []
        for item in message_content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                pieces.append(text.strip())
        if pieces:
            return "\n".join(pieces)
    return ""


def create_embedding(text: str, client: Any | None = None) -> list[float]:
    settings = get_settings()
    payload = {"inputText": text}
    try:
        response = _bedrock_client(client).invoke_model(
            modelId=settings.bedrock_model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload).encode("utf-8"),
        )
        content = _load_json_body(response)
        embedding = content.get("embedding") or content.get("embeddings")
        if isinstance(embedding, list):
            # flatten nested arrays if needed
            return embedding[0] if embedding and isinstance(embedding[0], list) else embedding
        return [0.0]
    except (BotoCoreError, ClientError):
        return [hash(text) % 100 / 100 for _ in range(16)]


def summarize_transcript(meeting_id: str, transcript_text: str, client: Any | None = None) -> dict[str, Any]:
    prompt = f"以下は会議ID {meeting_id} の議事録です。日本語で簡潔に要約してください。\n{transcript_text[:4000]}"
    try:
        content = _invoke_text_model(prompt, max_tokens=256, temperature=0.3, client=client)
        summary_text = _extract_text_from_content(content) or json.dumps(content)
    except (BotoCoreError, ClientError):
        summary_text = f"[mock-summary] {prompt[:200]}"

    return {"meeting_id": meeting_id, "summary": summary_text}


def classify_transcript_segments(
    segments: list[dict[str, Any]],
    agenda_text: str = "",
    client: Any | None = None,
) -> list[dict[str, Any]]:
    clean_segments = []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        clean_segments.append(
            {
                "index": segment.get("index"),
                "speaker": segment.get("speaker") or "",
                "text": text,
                "context_before": (segment.get("context_before") or "").strip(),
                "context_after": (segment.get("context_after") or "").strip(),
            }
        )
    if not clean_segments:
        return []

    category_guidance = (
        "議事進行=会議の段取りや進め方/次の議題の指示、開始・終了宣言、アジェンダの提示\n"
        "報告=進捗や結果、現状共有。担当や出欠の自己紹介（「ヤマモトです」「開発の田中です」など）も含む\n"
        "提案=新しい案や改善点の持ちかけ。「〜してはどうでしょうか」「〜しませんか」など\n"
        "相談=協力依頼や迷いの吐露。「どうしたらいいか迷っています」「相談させてください」など\n"
        "質問=情報を求める発言。「〜ですか？」「〜でしょうか」「教えてください」「〜いただけますか」など\n"
        "回答=質問への答え・説明、または依頼への承諾/却下。「はい、〜します」「大丈夫です」など\n"
        "決定=意思決定や合意事項の明言。「〜で決定します」「この方針で行きましょう」「〜という流れで進めましょう」など\n"
        "コメント=議題や業務に関連するが、新しい情報・指示・決定を含まない短い感想/謝罪/お礼/あいさつ。\n"
        "          例:「それは心強いですね」「ありがとうございます」「すみません」「失礼しました」「お疲れさまでした」など\n"
        "無関係な雑談=業務や会議の議題と直接関係しない雑談（カフェ・天気・プライベートな話題など）。\n"
        "               雑談内容に提案や質問が含まれていても、内容が明らかに雑談ならこのカテゴリを優先する。\n"
        "               会議の開始時挨拶や自己紹介、了解の返事などはここに含めない。\n"
        "               ただし、「例えば」「たとえば」で始まる例え話や比喩は、アジェンダに関連する内容であれば雑談ではない。"
    )


    prompt = (
        "あなたは日本語の議事録を文単位で分類するアシスタントです。\n"
        "必ず同じ基準で安定した判断を行い、文脈(context_before/context_after)も考慮してください。\n"
        "\n"
        "【重要】一致度（alignment）の判定基準:\n"
        "- 80-100%: アジェンダの中心的な話題に直接言及している（例: アジェンダが「離脱率改善」なら「離脱率」「改善案」など）\n"
        "- 50-79%: アジェンダに関連するが、周辺的な話題（例: 「ユーザーテスト結果」「入力項目」など）\n"
        "- 30-49%: アジェンダと間接的に関連する話題（例: 「アプリ全体のレビュー」「他の画面の問題」など）\n"
        "- 0-29%: アジェンダとほぼ無関係、または雑談\n"
        "\n"
        "カテゴリ定義:\n"
        f"{category_guidance}\n"
        "\n"
        "判定ルール:\n"
        "1. 名乗り・自己紹介（例:「サトウです」「高橋です」）は、会議参加や担当を示す発言として「報告」とする。\n"
        "   特に、文全体が「固有名詞 + です。」の形になっている場合は「報告」を優先する。\n"
        "\n"
        "2. 「はい」「了解しました」「大丈夫です」「お願いします」など、固有名詞を含まない短い返事は、\n"
        "   直前の質問や依頼に対する「回答」として扱う。\n"
        "   「ありがとうございます」「すみません」「失礼しました」「お疲れさまでした」などは「コメント」とする。\n"
        "   また、「〜ありがとう」「〜分かりやすかった」「〜助かりました」など、感謝や感想を述べる文も「コメント」とする。\n"
        "\n"
        "3. アジェンダや議題の提示（例:「本日は〜がテーマです」「今日のアジェンダは〜です」）は「議事進行」とする。\n"
        "   「ランチの話は後でにして、まず〜の確認を優先します」など議題の優先順位を示す発言も「議事進行」とする。\n"
        "\n"
        "4. 進捗や状況に関する説明・見込み（例:「実装は完了していて〜」「夕方までには結果を出せる見込みです」）は、\n"
        "   質問に対する答えであれば「回答」、そうでなければ「報告」とする。\n"
        "\n"
        "5. 会議内容に対する感想・共感・軽い相づち（例:「それは心強いですね」「いいですね」「分かりやすかったです」）は、\n"
        "   新しい情報や方針・決定を含まない限り「コメント」として分類する。\n"
        "   特に、「〜ありがとう」「〜助かりました」「〜良かったです」など、感謝や評価を述べる文は「コメント」とする。\n" "5. 会議内容に対する感想・共感・軽い相づち（例:「それは心強いですね」「いいですね」「分かりやすかったです」）は、\n"
        "   新しい情報や方針・決定を含まない限り「コメント」として分類する。\n"
        "   特に、「〜ありがとう」「〜助かりました」「〜良かったです」など、感謝や評価を述べる文は「コメント」とする。\n"
        "\n"
        "6. 文末が「〜でしょうか」「〜ですか」「〜ませんか」「〜いただけますか」など「か」で終わる文、\n"
        "   または「〜してください」「〜教えてください」など情報や行動を求める文は、\n"
        "   原則として「質問」として分類する。\n"
        "   これらの条件に当てはまらない文を「質問」として分類してはならない。\n"
        "\n"
        "7. 「〜したいと考えています」「〜してはどうでしょうか」「〜できればと思います」など、\n"
        "   新しい行動・方針を持ちかけている文は「提案」とする。\n"
        "   ただし、内容がカフェ・趣味など明らかな雑談の場合は「無関係な雑談」を優先する。\n"
        "\n"
        "8. 直前の質問「〜でよいですか？」「〜で大丈夫でしょうか？」に対して、\n"
        "   「はい、そのつもりで準備しています」「キャプチャは〜共有します」などと答える文は「回答」とする。\n"
        "\n"
        "9. 「〜で行きましょう」「〜という流れで進めましょう」「この方針で進めます」など、\n"
        "   方針やスケジュールを確定する発言は「決定」とする。\n"
        "\n"
        "10. 呼びかけだけの文（例:「スズキさん。」など氏名のみ）は、次の質問や発言のための準備として「議事進行」とする。\n"
        "\n"
        "11. 「コメント」と「無関係な雑談」の違い:\n"
        "    - 議題や業務内容に関する感想・謝罪・お礼・あいさつ → 「コメント」\n"
        "    - カフェ・天気・プライベートな話題など議題と無関係な内容 → 「無関係な雑談」\n"
        "\n"
        "12. どのカテゴリにも当てはまらないからといって安易に「無関係な雑談」を選ばない。\n"
        "    明らかに業務や議題と無関係な話題のみを「無関係な雑談」とする。\n"
        "\n"
        "13. 例え話・比喩・具体例の判定:\n"
        "    「例えば」「たとえば」「〜のような」で始まる発言は、内容がアジェンダに関連していれば適切なカテゴリを選ぶ。\n"
        "    例: アジェンダが「業務の面倒な場面」の場合\n"
        "    - 「例えば、毎日の日報作成が面倒で...」 → 報告（業務に関連）\n"
        "    - 「例えば、朝のコーヒーを淹れるのが...」 → 無関係な雑談（業務と無関係）\n"
        "    アジェンダとの関連性を重視し、表現方法（例え話かどうか）ではなく内容で判断する。\n"
        "\n"
        "【分類例】（これは出力ではなく、ルール理解のための例です）\n"
        "・「ありがとうございます。」 → コメント\n"
        "・「スズキさん。」 → 議事進行\n"
        "・「テスト完了の目安はいつになりそうですか。」 → 質問\n"
        "・「大きな問題がなければ、きょうの夕方までには一通り結果を出せる見込みです。」 → 回答\n"
        "・「ケーキがとてもおいしくて、つい長居してしまいました。」 → 無関係な雑談\n"
        "・「リリースが無事に終わったご褒美にみんなで行きましょうか。」 → 無関係な雑談（雑談としての提案）\n"
        "・「まずは、リリース準備の確認を優先させたいと思います。」 → 議事進行\n"
        "・「他に不安な点がなければ、きょうのミーティングはここまでにします。」 → 議事進行 または 決定\n"
        "・「お疲れさまでした。」 → コメント\n"
        "\n"
        "出力形式は JSON 配列のみで、各要素は {\"index\":番号,\"category\":\"分類名\"} です。\n"
        "未知のカテゴリは使わず、必ず上記ラベルのいずれか1つを割り当ててください。\n"
        "各文が議題(アジェンダ)にどれだけ沿っているかも 0〜100% の整数で評価し、\"alignment\" として JSON に含めてください。\n"
        "アジェンダ概要:\n"
        f"{(agenda_text or '（アジェンダ未指定）')[:2000]}\n"
        "\n"
        "最後の出力には JSON 以外の文字は一切含めないでください。\n"
        "\n"
        "以下の文一覧を分類してください:\n"
        f"{json.dumps(clean_segments, ensure_ascii=False)}"
    )


    try:
        content = _invoke_text_model(prompt, max_tokens=512, temperature=0.2, client=client)
        print(f"[DEBUG] Bedrock生応答: {content}")
        parsed = _coerce_classifications(content)
        print(f"[DEBUG] パース結果: {parsed}")
        if parsed:
            return _merge_classifications(clean_segments, parsed)
    except (BotoCoreError, ClientError) as e:
        print(f"[DEBUG] Bedrockエラー: {e}")
        pass

    return []


def _coerce_classifications(content: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = content.get("classifications")
    if isinstance(candidates, list):
        return candidates
    raw = _extract_text_from_content(content)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and isinstance(parsed.get("classifications"), list):
                return parsed["classifications"]
        except json.JSONDecodeError:
            matches = re.findall(r'\{[^}]*"category"\s*:\s*"[^"]+"[^}]*\}', raw)
            if matches:
                try:
                    return [json.loads(match) for match in matches]
                except json.JSONDecodeError:
                    pass
    return []


def _merge_classifications(segments: list[dict[str, Any]], classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index_to_result: dict[int, tuple[str, int]] = {}
    for item in classified:
        idx = item.get("index")
        cat = item.get("category")
        alignment = item.get("alignment")
        if isinstance(idx, int) and isinstance(cat, str):
            score = int(alignment) if isinstance(alignment, (int, float)) else 0
            index_to_result[idx] = (cat, max(0, min(100, score)))

    merged: list[dict[str, Any]] = []
    for segment in segments:
        idx = segment["index"]
        category, alignment = index_to_result.get(idx, (_guess_category(segment["text"]), 0))
        if category not in CLASSIFICATION_LABELS:
            category = "無関係な雑談"
        merged.append({**segment, "category": category, "alignment": alignment})
    return merged


def _fallback_classification(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**segment, "category": _guess_category(segment["text"])}
        for segment in segments
    ]


def _guess_category(text: str) -> str:
    lowered = text.lower()
    
    # 例え話の場合は、内容を重視
    if any(word in lowered for word in ["例えば", "たとえば", "のような", "みたいな"]):
        # 業務関連キーワードがあれば報告として扱う
        business_keywords = ["業務", "仕事", "作業", "タスク", "プロジェクト", "会議", "資料", "システム", "ツール", "面倒", "効率", "時間"]
        if any(keyword in lowered for keyword in business_keywords):
            return "報告"  # 例え話だが業務関連
    
    cues = [
        ("議事進行", ["議題", "進行", "次に", "本題", "開始", "終了"]),
        ("報告", ["報告", "共有", "アップデート", "結果", "進捗", "ステータス", "面倒", "課題"]),
        ("提案", ["提案", "アイデア", "案", "どうでしょう", "検討", "改善"]),
        ("相談", ["相談", "一緒に", "助け", "サポート", "悩んで"]),
        ("質問", ["?", "か?", "教えて", "でしょうか", "質問"]),
        ("回答", ["回答", "説明します", "対応します", "お答え", "承知"]),
        ("決定", ["決定", "合意", "確定", "承認", "決めましょう"]),
        ("コメント", ["ありがとうございます", "すみません", "助かります", "うれしい", "心強い"]),
        ("無関係な雑談", ["雑談", "世間話", "余談", "週末", "天気", "ランチ", "コーヒー", "カフェ"]),
    ]
    for label, keywords in cues:
        if any(keyword in text for keyword in keywords) or any(keyword in lowered for keyword in keywords):
            return label
    return "無関係な雑談"  # デフォルトは無関係な雑談
