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
    """
    Result画面でのみ使用するLED制御エンドポイント。
    許可するのは4378-7530デバイスのON/OFFだけ。
    """
    turn_on = payload.get("turn_on")
    if not isinstance(turn_on, bool):
        raise HTTPException(status_code=400, detail="turn_on must be a boolean")

    try:
        return lambda_client.trigger_result_led(turn_on)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
