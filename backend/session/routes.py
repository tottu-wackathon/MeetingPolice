from fastapi import APIRouter, WebSocket, HTTPException

from .controller import SessionController

router = APIRouter()
controller = SessionController()


@router.post("/meetings")
def create_meeting(payload: dict):
    import logging
    logger = logging.getLogger(__name__)
    logger.info("🎬 API: Creating new meeting with payload: %s", payload)
    try:
        title = payload.get("title")
        scheduled_for = payload.get("scheduled_for")
        result = controller.create_meeting(title=title, scheduled_for=scheduled_for)
        logger.info("✅ API: Meeting created successfully: %s", result.get("meeting_id"))
        return result
    except ValueError as exc:
        logger.error("❌ API: Meeting creation failed: %s", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/meetings/{meeting_id}/join")
def join_meeting(meeting_id: str):
    import logging
    logger = logging.getLogger(__name__)
    logger.info("🎫 API: Join meeting request for: %s", meeting_id)
    try:
        result = controller.create_session_token(meeting_id)
        logger.info("✅ API: Session token created successfully for: %s", meeting_id)
        return result
    except ValueError as exc:
        logger.error("❌ API: Join meeting failed for %s: %s", meeting_id, str(exc))
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
