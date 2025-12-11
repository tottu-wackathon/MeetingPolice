from fastapi import APIRouter, HTTPException

from .controller import AdminController

router = APIRouter()
controller = AdminController()


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


@router.get("/vonage/status")
def get_vonage_status():
    """Get Vonage API connection status."""
    return controller.get_vonage_status()


@router.get("/meetings/with-status")
def list_meetings_with_status():
    """List meetings with Vonage connection status."""
    return controller.list_meetings_with_vonage_status()
