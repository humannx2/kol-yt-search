import os
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env", override=True)


def get_youtube_api_key() -> str:
    return os.getenv("YOUTUBE_API_KEY", "").strip().strip('"').strip("'")
