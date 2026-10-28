"""Configuration shared by Streamlit frontend and FastAPI backend."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def get_setting(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value not in (None, ""):
        return value
    # Streamlit secrets are available on Community Cloud. Keep this optional so
    # the REST API can also run outside Streamlit.
    try:
        import streamlit as st  # type: ignore
        value = st.secrets.get(name, None)
        if value not in (None, ""):
            return str(value)
    except Exception:
        pass
    return default


APP_ENV = (get_setting("APP_ENV", "development") or "development").lower()
DATABASE_URL_SETTING = get_setting("DATABASE_URL")
if DATABASE_URL_SETTING:
    DATABASE_URL = DATABASE_URL_SETTING.strip()
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
    elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]
    DEMO_DEFAULT = "false"
else:
    DATA_DIR = ROOT / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{(DATA_DIR / 'swasthyagrid.db').as_posix()}"
    DEMO_DEFAULT = "false" if APP_ENV == "production" else "true"

ALLOW_DEMO_LOGIN = (get_setting("ALLOW_DEMO_LOGIN", DEMO_DEFAULT) or DEMO_DEFAULT).lower() in {"1", "true", "yes", "on"}
if APP_ENV == "production":
    ALLOW_DEMO_LOGIN = False
BOOTSTRAP_ADMIN_PASSWORD = get_setting("BOOTSTRAP_ADMIN_PASSWORD")
TOKEN_SECRET = get_setting("TOKEN_SECRET", "local-development-token-secret-change-before-deploy") or "local-development-token-secret-change-before-deploy"
GEMINI_API_KEY = get_setting("GEMINI_API_KEY")
GEMINI_MODEL = get_setting("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
GROQ_API_KEY = get_setting("GROQ_API_KEY")
GROQ_MODEL = get_setting("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct") or "meta-llama/llama-4-scout-17b-16e-instruct"
MAX_UPLOAD_MB = int(get_setting("MAX_UPLOAD_MB", "10") or "10")
CORS_ORIGINS = [x.strip() for x in (get_setting("CORS_ORIGINS", "http://localhost:5173,http://localhost:8501") or "").split(",") if x.strip()]
