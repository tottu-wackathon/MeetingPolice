"""
Lambda関数呼び出しサービス
警察出動時の緊急通知処理を行う
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict
import boto3
from botocore.exceptions import ClientError

from backend.config import get_settings
from backend.utils.time_utils import now_iso


class LambdaClient:
    def __init__(self):
        self.settings = get_settings()
        self.logger = logging.getLogger(__name__)
        
        # AWS Lambda クライアントを初期化
        try:
            self.lambda_client = boto3.client(
                'lambda',
                region_name=self.settings.aws_region,
                aws_access_key_id=self.settings.aws_access_key_id,
                aws_secret_access_key=self.settings.aws_secret_access_key
            )
            self.logger.info("✅ Lambda client initialized successfully")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Lambda client: {e}")
            self.lambda_client = None

    def invoke_police_dispatch(self, meeting_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        警察出動Lambda関数を呼び出す（obniz2でLED点灯）
        
        Args:
            meeting_data: 会議データ（警察出動ON用）
            
        Returns:
            Lambda関数の実行結果
        """
        if not self.lambda_client:
            self.logger.warning("⚠️ Lambda client not available, returning mock response")
            return {
                "statusCode": 200,
                "message": "Mock police dispatch (LED ON) sent",
                "dispatchId": f"mock-dispatch-{meeting_data.get('meeting_id', 'unknown')}"
            }

        function_name = "obniz2"
        
        # obniz2 Lambda関数に渡すペイロード（LED点灯 + 10秒後自動消灯）
        payload = {
            "url": "https://obniz.com/obniz/3754-4414/message?data=on",
            "auto_off_seconds": 10  # 10秒後に自動消灯
        }

        # 詳細ログ記録開始
        invocation_start_time = time.time()
        invocation_timestamp = now_iso()
        
        try:
            # 呼び出し前ログ
            self.logger.info("=" * 80)
            self.logger.info("🚨 LAMBDA INVOCATION START - POLICE DISPATCH (LED ON)")
            self.logger.info("=" * 80)
            self.logger.info(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.info(f"🔧 Function Name: {function_name}")
            self.logger.info(f"🏢 Meeting ID: {meeting_data.get('meeting_id', 'N/A')}")
            self.logger.info(f"👤 Speaker: {meeting_data.get('speaker', 'N/A')}")
            self.logger.info(f"📊 Alignment Score: {meeting_data.get('alignment_score', 'N/A')}%")
            self.logger.info(f"💬 Recent Transcript: {meeting_data.get('recent_transcript', 'N/A')[:100]}...")
            self.logger.info(f"🌐 Target URL: {payload['url']}")
            self.logger.info(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)}")
            self.logger.info(f"🔄 Invocation Type: Event (Asynchronous)")
            self.logger.info("-" * 80)

            # Lambda関数を非同期で呼び出し
            response = self.lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='Event',  # 非同期呼び出し
                Payload=json.dumps(payload)
            )

            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)

            result = {
                "statusCode": response['StatusCode'],
                "message": "Police dispatch LED turned ON successfully (auto OFF in 10s)",
                "dispatchId": f"dispatch-{meeting_data.get('meeting_id')}-{int(time.time())}",
                "function_name": function_name,
                "invocation_type": "Event",
                "led_status": "ON",
                "auto_off_seconds": 10,
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }

            # 成功ログ
            self.logger.info("✅ LAMBDA INVOCATION SUCCESS - POLICE DISPATCH (LED ON)")
            self.logger.info(f"📈 Status Code: {response['StatusCode']}")
            self.logger.info(f"🆔 Dispatch ID: {result['dispatchId']}")
            self.logger.info(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.info(f"🔴 LED Status: ON")
            self.logger.info(f"📋 Response Headers: {response.get('ResponseMetadata', {})}")
            self.logger.info("=" * 80)

            return result

        except ClientError as e:
            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)
            
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            # エラーログ
            self.logger.error("❌ LAMBDA INVOCATION FAILED - POLICE DISPATCH (LED ON)")
            self.logger.error(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.error(f"🔧 Function Name: {function_name}")
            self.logger.error(f"🏢 Meeting ID: {meeting_data.get('meeting_id', 'N/A')}")
            self.logger.error(f"⚠️ Error Code: {error_code}")
            self.logger.error(f"💥 Error Message: {error_message}")
            self.logger.error(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.error(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)}")
            self.logger.error(f"🔍 Full Error Response: {e.response}")
            self.logger.error("=" * 80)
            
            return {
                "statusCode": 500,
                "error": error_code,
                "message": f"Failed to invoke obniz2 (LED ON): {error_message}",
                "dispatchId": None,
                "led_status": "ERROR",
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }

        except Exception as e:
            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)
            
            # 予期しないエラーログ
            self.logger.exception("❌ UNEXPECTED ERROR - POLICE DISPATCH (LED ON)")
            self.logger.error(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.error(f"🔧 Function Name: {function_name}")
            self.logger.error(f"🏢 Meeting ID: {meeting_data.get('meeting_id', 'N/A')}")
            self.logger.error(f"💥 Exception: {str(e)}")
            self.logger.error(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.error(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)}")
            self.logger.error("=" * 80)
            
            return {
                "statusCode": 500,
                "error": "UnexpectedError",
                "message": f"Unexpected error: {str(e)}",
                "dispatchId": None,
                "led_status": "ERROR",
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }

    def invoke_police_dispatch_off(self, meeting_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        警察出動解除Lambda関数を呼び出す（obniz2でLED消灯）
        
        Args:
            meeting_data: 会議データ（警察出動OFF用）
            
        Returns:
            Lambda関数の実行結果
        """
        if not self.lambda_client:
            self.logger.warning("⚠️ Lambda client not available, returning mock response")
            return {
                "statusCode": 200,
                "message": "Mock police dispatch (LED OFF) sent",
                "dispatchId": f"mock-dispatch-off-{meeting_data.get('meeting_id', 'unknown')}"
            }

        function_name = "obniz2"
        
        # obniz2 Lambda関数に渡すペイロード（LED消灯）
        payload = {
            "url": "https://obniz.com/obniz/3754-4414/message?data=off"
        }

        # 詳細ログ記録開始
        invocation_start_time = time.time()
        invocation_timestamp = now_iso()
        
        try:
            # 呼び出し前ログ
            self.logger.info("=" * 80)
            self.logger.info("🟢 LAMBDA INVOCATION START - POLICE DISPATCH OFF (LED OFF)")
            self.logger.info("=" * 80)
            self.logger.info(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.info(f"🔧 Function Name: {function_name}")
            self.logger.info(f"🏢 Meeting ID: {meeting_data.get('meeting_id', 'N/A')}")
            self.logger.info(f"👤 Speaker: {meeting_data.get('speaker', 'N/A')}")
            self.logger.info(f"📊 Alignment Score: {meeting_data.get('alignment_score', 'N/A')}%")
            self.logger.info(f"💬 Recent Transcript: {meeting_data.get('recent_transcript', 'N/A')[:100]}...")
            self.logger.info(f"🌐 Target URL: {payload['url']}")
            self.logger.info(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)}")
            self.logger.info(f"🔄 Invocation Type: Event (Asynchronous)")
            self.logger.info("-" * 80)

            # Lambda関数を非同期で呼び出し
            response = self.lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='Event',  # 非同期呼び出し
                Payload=json.dumps(payload)
            )

            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)

            result = {
                "statusCode": response['StatusCode'],
                "message": "Police dispatch LED turned OFF successfully",
                "dispatchId": f"dispatch-off-{meeting_data.get('meeting_id')}-{int(time.time())}",
                "function_name": function_name,
                "invocation_type": "Event",
                "led_status": "OFF",
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }

            # 成功ログ
            self.logger.info("✅ LAMBDA INVOCATION SUCCESS - POLICE DISPATCH OFF (LED OFF)")
            self.logger.info(f"📈 Status Code: {response['StatusCode']}")
            self.logger.info(f"🆔 Dispatch ID: {result['dispatchId']}")
            self.logger.info(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.info(f"🟢 LED Status: OFF")
            self.logger.info(f"📋 Response Headers: {response.get('ResponseMetadata', {})}")
            self.logger.info("=" * 80)

            return result

        except ClientError as e:
            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)
            
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            # エラーログ
            self.logger.error("❌ LAMBDA INVOCATION FAILED - POLICE DISPATCH OFF (LED OFF)")
            self.logger.error(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.error(f"🔧 Function Name: {function_name}")
            self.logger.error(f"🏢 Meeting ID: {meeting_data.get('meeting_id', 'N/A')}")
            self.logger.error(f"⚠️ Error Code: {error_code}")
            self.logger.error(f"💥 Error Message: {error_message}")
            self.logger.error(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.error(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)}")
            self.logger.error(f"🔍 Full Error Response: {e.response}")
            self.logger.error("=" * 80)
            
            return {
                "statusCode": 500,
                "error": error_code,
                "message": f"Failed to invoke obniz2 (LED OFF): {error_message}",
                "dispatchId": None,
                "led_status": "ERROR",
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }

        except Exception as e:
            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)
            
            # 予期しないエラーログ
            self.logger.exception("❌ UNEXPECTED ERROR - POLICE DISPATCH OFF (LED OFF)")
            self.logger.error(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.error(f"🔧 Function Name: {function_name}")
            self.logger.error(f"🏢 Meeting ID: {meeting_data.get('meeting_id', 'N/A')}")
            self.logger.error(f"💥 Exception: {str(e)}")
            self.logger.error(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.error(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)}")
            self.logger.error("=" * 80)
            
            return {
                "statusCode": 500,
                "error": "UnexpectedError",
                "message": f"Unexpected error: {str(e)}",
                "dispatchId": None,
                "led_status": "ERROR",
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }

    def invoke_alert_escalation(self, escalation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        アラートエスカレーションLambda関数を呼び出す
        
        Args:
            escalation_data: エスカレーションデータ
            
        Returns:
            Lambda関数の実行結果
        """
        if not self.lambda_client:
            self.logger.warning("⚠️ Lambda client not available, returning mock response")
            return {
                "statusCode": 200,
                "message": "Mock alert escalation sent",
                "escalationId": f"mock-escalation-{escalation_data.get('meeting_id', 'unknown')}"
            }

        function_name = "meeting-alert-escalation-handler"
        
        payload = {
            "action": "alert_escalation",
            "meeting_id": escalation_data.get("meeting_id"),
            "escalation_level": escalation_data.get("escalation_level", "MEDIUM"),
            "previous_alerts": escalation_data.get("previous_alerts", []),
            "current_alignment": escalation_data.get("current_alignment", 0),
            "duration_low_alignment": escalation_data.get("duration_low_alignment", 0),
            "timestamp": escalation_data.get("timestamp"),
            "recommended_actions": [
                "Send warning notification",
                "Schedule intervention",
                "Prepare police dispatch if needed"
            ]
        }

        # 詳細ログ記録開始
        invocation_start_time = time.time()
        invocation_timestamp = now_iso()
        
        try:
            # 呼び出し前ログ
            self.logger.info("=" * 80)
            self.logger.info("⚠️ LAMBDA INVOCATION START - ALERT ESCALATION")
            self.logger.info("=" * 80)
            self.logger.info(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.info(f"🔧 Function Name: {function_name}")
            self.logger.info(f"🏢 Meeting ID: {escalation_data.get('meeting_id', 'N/A')}")
            self.logger.info(f"📊 Escalation Level: {escalation_data.get('escalation_level', 'N/A')}")
            self.logger.info(f"📈 Current Alignment: {escalation_data.get('current_alignment', 'N/A')}%")
            self.logger.info(f"⏰ Duration Low Alignment: {escalation_data.get('duration_low_alignment', 'N/A')}s")
            self.logger.info(f"📦 Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
            self.logger.info(f"🔄 Invocation Type: RequestResponse (Synchronous)")
            self.logger.info("-" * 80)
            
            response = self.lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='RequestResponse',  # 同期呼び出し
                Payload=json.dumps(payload)
            )

            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)

            # レスポンスを読み取り
            response_payload = json.loads(response['Payload'].read())
            
            result = {
                "statusCode": response['StatusCode'],
                "message": "Alert escalation processed successfully",
                "escalationId": f"escalation-{escalation_data.get('meeting_id')}-{int(time.time())}",
                "response": response_payload,
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }
            
            # 成功ログ
            self.logger.info("✅ LAMBDA INVOCATION SUCCESS - ALERT ESCALATION")
            self.logger.info(f"📈 Status Code: {response['StatusCode']}")
            self.logger.info(f"🆔 Escalation ID: {result['escalationId']}")
            self.logger.info(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.info(f"📋 Response Payload: {json.dumps(response_payload, ensure_ascii=False, indent=2)}")
            self.logger.info(f"📋 Response Headers: {response.get('ResponseMetadata', {})}")
            self.logger.info("=" * 80)
            
            return result

        except Exception as e:
            # 実行時間計算
            invocation_end_time = time.time()
            execution_time_ms = round((invocation_end_time - invocation_start_time) * 1000, 2)
            
            # エラーログ
            self.logger.exception("❌ LAMBDA INVOCATION FAILED - ALERT ESCALATION")
            self.logger.error(f"📅 Timestamp: {invocation_timestamp}")
            self.logger.error(f"🔧 Function Name: {function_name}")
            self.logger.error(f"🏢 Meeting ID: {escalation_data.get('meeting_id', 'N/A')}")
            self.logger.error(f"💥 Exception: {str(e)}")
            self.logger.error(f"⏱️ Execution Time: {execution_time_ms}ms")
            self.logger.error(f"📦 Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
            self.logger.error("=" * 80)
            
            return {
                "statusCode": 500,
                "error": "EscalationError",
                "message": f"Failed to invoke alert escalation: {str(e)}",
                "escalationId": None,
                "execution_time_ms": execution_time_ms,
                "invocation_timestamp": invocation_timestamp
            }