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


@router.post("/meetings/{meeting_id}/agenda")
async def upload_agenda(meeting_id: str, payload: dict):
    try:
        agenda_text = payload.get("agenda_text")
        filename = payload.get("filename", "agenda.txt")
        
        if not agenda_text or not agenda_text.strip():
            raise HTTPException(status_code=400, detail="アジェンダテキストが空です")
        
        # コントローラーにアジェンダを設定
        result = controller.set_meeting_agenda(meeting_id, agenda_text.strip())
        return {"message": "アジェンダが設定されました", "filename": filename, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"アジェンダ設定エラー: {str(exc)}") from exc


@router.websocket("/ws/{meeting_id}")
async def ws_proxy(websocket: WebSocket, meeting_id: str):
    await controller.stream_transcripts(websocket, meeting_id)
