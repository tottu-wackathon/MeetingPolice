from fastapi import APIRouter, WebSocket, HTTPException

from .controller import SessionController

router = APIRouter()
controller = SessionController()


@router.post("/meetings")
def create_meeting(payload: dict):
    try:
        title = payload.get("title")
        scheduled_for = payload.get("scheduled_for")
        return controller.create_meeting(title=title, scheduled_for=scheduled_for)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/meetings/{meeting_id}/join")
def join_meeting(meeting_id: str):
    try:
        return controller.create_session_token(meeting_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="入力されたIDのミーティングは開催されていません"
        ) from exc


@router.get("/meetings/{meeting_id}/validate")
def validate_meeting(meeting_id: str):
    try:
        return controller.validate_meeting(meeting_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="入力されたIDのミーティングは開催されていません"
        ) from exc


@router.websocket("/ws/{meeting_id}")
async def ws_proxy(websocket: WebSocket, meeting_id: str):
    await controller.stream_transcripts(websocket, meeting_id)
