from fastapi import APIRouter, WebSocket, HTTPException, UploadFile, File

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
async def upload_agenda(meeting_id: str, file: UploadFile = File(...)):
    try:
        if not file.content_type or not file.content_type.startswith('text/'):
            raise HTTPException(status_code=400, detail="テキストファイルのみアップロード可能です")
        
        content = await file.read()
        agenda_text = content.decode('utf-8')
        
        # コントローラーにアジェンダを設定
        result = controller.set_meeting_agenda(meeting_id, agenda_text)
        return {"message": "アジェンダが設定されました", "filename": file.filename, **result}
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="ファイルの文字エンコーディングが正しくありません")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.websocket("/ws/{meeting_id}")
async def ws_proxy(websocket: WebSocket, meeting_id: str):
    await controller.stream_transcripts(websocket, meeting_id)
