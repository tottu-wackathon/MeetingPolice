"""
Lambda関数呼び出しサービス（指定のタイミングのみ）

呼び出しタイミング:
1. UIで「警察出動」が表示された直後にデバイス3754-4414をON
2. 1の5秒後に自動でOFFし、その後30秒間は再度ONを呼ばない
3. result画面に遷移し平均一致度60%以上のときにデバイス4378-7530をON
4. result画面から最初の画面へ戻る操作でデバイス4378-7530をOFF
"""

import json
import logging
import threading
import time
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

from backend.config import get_settings
from backend.utils.time_utils import now_iso


class LambdaClient:
    POLICE_DEVICE_ON_URL = "https://obniz.com/obniz/3754-4414/message?data=on"
    POLICE_DEVICE_OFF_URL = "https://obniz.com/obniz/3754-4414/message?data=off"
    RESULT_DEVICE_ON_URL = "https://obniz.com/obniz/4378-7530/message?data=on"
    RESULT_DEVICE_OFF_URL = "https://obniz.com/obniz/4378-7530/message?data=off"

    AUTO_OFF_DELAY_SECONDS = 5
    POLICE_COOLDOWN_SECONDS = 120

    def __init__(self):
        self.settings = get_settings()
        self.logger = logging.getLogger(__name__)
        self.function_name = "obniz2"

        try:
            self.lambda_client = boto3.client(
                "lambda",
                region_name=self.settings.aws_region,
                aws_access_key_id=self.settings.aws_access_key_id,
                aws_secret_access_key=self.settings.aws_secret_access_key,
            )
            self.logger.info("✅ Lambda client initialized successfully")
        except Exception as exc:
            self.logger.error("❌ Failed to initialize Lambda client: %s", exc)
            self.lambda_client = None

        # ①→②のクールダウン管理
        self._lock = threading.Lock()
        self._next_police_on_allowed_at = 0.0

    def trigger_police_dispatch(self) -> Dict[str, Any]:
        """
        ① UIで「警察出動」が表示された直後に呼び出す。
        すぐにONを送信し、5秒後にOFFを自動送信。OFF送信後30秒間は再度ONを呼ばない。
        """
        now_ts = time.time()
        with self._lock:
            remaining = self._next_police_on_allowed_at - now_ts
            if remaining > 0:
                cooldown_seconds = round(max(0.0, remaining), 2)
                self.logger.info("🚫 Police dispatch suppressed during cooldown (remaining=%ss)", cooldown_seconds)
                return {
                    "statusCode": 429,
                    "message": f"Police dispatch suppressed during cooldown ({cooldown_seconds}s remaining)",
                    "cooldown_seconds_remaining": cooldown_seconds,
                }

            self.logger.info(
                "🚨 Triggering police dispatch ON → OFF (auto in %ss, cooldown %ss)",
                self.AUTO_OFF_DELAY_SECONDS,
                self.POLICE_COOLDOWN_SECONDS,
            )

            on_result = self._invoke_obniz(self.POLICE_DEVICE_ON_URL, "police_dispatch_on")

            # OFFは別スレッドで5秒後に実行
            timer = threading.Timer(self.AUTO_OFF_DELAY_SECONDS, self._auto_off_police_dispatch)
            timer.daemon = True
            timer.start()

            return {
                **on_result,
                "auto_off_scheduled_seconds": self.AUTO_OFF_DELAY_SECONDS,
                "next_on_cooldown_seconds": self.POLICE_COOLDOWN_SECONDS,
            }

    def _auto_off_police_dispatch(self) -> None:
        """② ON送信後5秒でOFFを送信し、以後30秒は再度ONを送らない"""
        try:
            off_result = self._invoke_obniz(self.POLICE_DEVICE_OFF_URL, "police_dispatch_off_auto")
            self.logger.info("🟢 Police dispatch auto OFF sent: %s", off_result)
        finally:
            with self._lock:
                self._next_police_on_allowed_at = time.time() + self.POLICE_COOLDOWN_SECONDS
                self.logger.info(
                    "⏲️ Police dispatch cooldown started (%ss)", self.POLICE_COOLDOWN_SECONDS
                )

    def trigger_result_led(self, turn_on: bool) -> Dict[str, Any]:
        """
        ③/④ result画面用のLED制御。
        turn_on=True  -> 4378-7530 を ON
        turn_on=False -> 4378-7530 を OFF
        """
        url = self.RESULT_DEVICE_ON_URL if turn_on else self.RESULT_DEVICE_OFF_URL
        label = "result_led_on" if turn_on else "result_led_off"
        self.logger.info("🎉 Result LED control: %s", label)
        return self._invoke_obniz(url, label)

    # 互換用のエントリポイント（既存の呼び出し元を壊さないため）
    def invoke_police_dispatch(self, meeting_data: Dict[str, Any]) -> Dict[str, Any]:
        """既存の警察出動ON呼び出しを新ロジックに委譲"""
        self.logger.info(
            "🚨 invoke_police_dispatch (compat): meeting_id=%s speaker=%s",
            meeting_data.get("meeting_id"),
            meeting_data.get("speaker"),
        )
        result = self.trigger_police_dispatch()
        if result.get("statusCode") == 200:
            result.setdefault(
                "dispatchId",
                f"dispatch-{meeting_data.get('meeting_id', 'unknown')}-{int(time.time())}",
            )
            result.setdefault("led_status", "ON")
        return result

    def invoke_police_dispatch_off(self, meeting_data: Dict[str, Any]) -> Dict[str, Any]:
        """既存の警察出動OFF呼び出しを新ロジックに合わせて実行"""
        self.logger.info(
            "🟢 invoke_police_dispatch_off (compat): meeting_id=%s speaker=%s",
            meeting_data.get("meeting_id"),
            meeting_data.get("speaker"),
        )
        result = self._invoke_obniz(self.POLICE_DEVICE_OFF_URL, "police_dispatch_off_manual")
        if result.get("statusCode") == 200:
            result.setdefault(
                "dispatchId",
                f"dispatch-off-{meeting_data.get('meeting_id', 'unknown')}-{int(time.time())}",
            )
            result.setdefault("led_status", "OFF")
        return result

    def invoke_obniz_custom(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """任意URL指定の既存API互換ハンドラー"""
        url = payload.get("url")
        if not url:
            return {"statusCode": 400, "message": "url is required", "led_status": "ERROR"}
        label = payload.get("label", "custom_obniz")
        self.logger.info("🔔 invoke_obniz_custom: %s", url)
        return self._invoke_obniz(url, label)

    def invoke_alert_escalation(self, escalation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        旧アラートエスカレーション呼び出しの互換処理。
        Lambda存在有無に関わらず安全にレスポンスを返す。
        """
        function_name = "meeting-alert-escalation-handler"
        payload = {
            "action": "alert_escalation",
            "meeting_id": escalation_data.get("meeting_id"),
            "escalation_level": escalation_data.get("escalation_level", "MEDIUM"),
            "previous_alerts": escalation_data.get("previous_alerts", []),
            "current_alignment": escalation_data.get("current_alignment", 0),
            "duration_low_alignment": escalation_data.get("duration_low_alignment", 0),
            "timestamp": escalation_data.get("timestamp"),
        }

        if not self.lambda_client:
            self.logger.warning("⚠️ Lambda client unavailable; returning mock escalation response")
            return {
                "statusCode": 200,
                "message": "Mock alert escalation (client unavailable)",
                "escalationId": f"mock-escalation-{escalation_data.get('meeting_id', 'unknown')}",
                "payload": payload,
            }

        invocation_start = time.time()
        invocation_timestamp = now_iso()

        try:
            response = self.lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )
            execution_time_ms = round((time.time() - invocation_start) * 1000, 2)
            response_payload = {}
            if "Payload" in response and response["Payload"]:
                try:
                    response_payload = json.loads(response["Payload"].read())
                except Exception:
                    response_payload = {}

            result = {
                "statusCode": response.get("StatusCode"),
                "message": "Alert escalation processed",
                "escalationId": f"escalation-{escalation_data.get('meeting_id', 'unknown')}-{int(time.time())}",
                "response": response_payload,
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp,
            }
            self.logger.info("✅ Alert escalation invoked: %s", result["escalationId"])
            return result
        except ClientError as exc:
            execution_time_ms = round((time.time() - invocation_start) * 1000, 2)
            error_code = exc.response["Error"]["Code"]
            self.logger.error("❌ Alert escalation invocation failed: %s", error_code)
            return {
                "statusCode": 500,
                "error": error_code,
                "message": f"Failed to invoke alert escalation: {exc.response['Error']['Message']}",
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp,
            }
        except Exception as exc:  # pragma: no cover - 保険
            execution_time_ms = round((time.time() - invocation_start) * 1000, 2)
            self.logger.exception("❌ Unexpected error during alert escalation invocation")
            return {
                "statusCode": 500,
                "error": "UnexpectedError",
                "message": f"Unexpected error during alert escalation: {exc}",
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp,
            }

    def _invoke_obniz(self, url: str, label: str) -> Dict[str, Any]:
        """obniz2 Lambdaを非同期(Event)で呼び出す共通処理"""
        invocation_start = time.time()
        invocation_timestamp = now_iso()

        if not self.lambda_client:
            self.logger.warning("⚠️ Lambda client not available, returning mock response (%s)", label)
            return {
                "statusCode": 200,
                "message": f"Mock invocation for {label}",
                "url": url,
                "invocation_timestamp": invocation_timestamp,
            }

        payload = {"url": url}

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.function_name,
                InvocationType="Event",
                Payload=json.dumps(payload),
            )

            execution_time_ms = round((time.time() - invocation_start) * 1000, 2)

            return {
                "statusCode": response.get("StatusCode"),
                "message": f"{label} sent",
                "url": url,
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp,
                "response_metadata": response.get("ResponseMetadata", {}),
            }

        except ClientError as exc:
            execution_time_ms = round((time.time() - invocation_start) * 1000, 2)
            error_code = exc.response["Error"]["Code"]
            self.logger.error("❌ Lambda invocation failed (%s): %s", label, error_code)
            return {
                "statusCode": 500,
                "error": error_code,
                "message": f"Failed to invoke obniz2 for {label}: {exc.response['Error']['Message']}",
                "url": url,
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp,
            }

        except Exception as exc:  # pragma: no cover - 保険
            execution_time_ms = round((time.time() - invocation_start) * 1000, 2)
            self.logger.exception("❌ Unexpected error during Lambda invocation (%s)", label)
            return {
                "statusCode": 500,
                "error": "UnexpectedError",
                "message": f"Unexpected error for {label}: {exc}",
                "url": url,
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp,
            }
