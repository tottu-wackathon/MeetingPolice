from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.session.routes import router as session_router
from backend.admin.routes import router as admin_router
from backend.poc import router as poc_router
from backend.poc_satomin import router as poc_satomin_router

settings = get_settings()

app = FastAPI(title="MeetingPolice API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router, prefix="/api/session", tags=["session"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(poc_router, prefix="/api/poc", tags=["poc"])
app.include_router(poc_satomin_router, prefix="/api/poc_satomin", tags=["poc_satomin"])


@app.get("/health")
def health_check():
    return {"status": "ok"}
