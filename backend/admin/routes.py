from fastapi import APIRouter, HTTPException

from .controller import AdminController
from backend.services.lambda_client import LambdaClient

router = APIRouter()
controller = AdminController()
lambda_client = LambdaClient()


@router.get("/meetings")
def list_meetings():
    return controller.list_meetings()


@router.post("/meetings")
def create_meeting(payload: dict):
    try:
        return controller.create_meeting(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/meetings/{meeting_id}/summary")
def summarize_meeting(meeting_id: str):
    return controller.generate_summary(meeting_id)

@router.post("/obniz2")
def invoke_obniz(payload: dict):
    try:
        # payloadにresult_ledフラグがあれば結果画面用LEDを制御、それ以外は警察出動LEDを点灯
        if "result_led" in payload:
            turn_on = bool(payload.get("result_led"))
            return lambda_client.trigger_result_led(turn_on=turn_on)
        return lambda_client.trigger_police_dispatch()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
