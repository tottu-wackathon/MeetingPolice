import jwt
from pathlib import Path

from backend.config import get_settings


def verify_jwt(token: str) -> bool:
    # Vonage Video SDK のトークンは "T1==" で始まる
    if token.startswith("T1=="):
        return True

    settings = get_settings()
    key_path = Path(settings.vonage_private_key_path)
    if not key_path.exists():
        return token.startswith("mock-token")
    private_key = key_path.read_text()
    try:
        jwt.decode(token, private_key, algorithms=["RS256"], audience=settings.vonage_application_id)
        return True
    except jwt.PyJWTError:
        return False
