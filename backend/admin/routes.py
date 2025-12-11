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
        return lambda_client.invoke_obniz_custom(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
