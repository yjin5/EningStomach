import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

def _get(key: str, default: str = "") -> str:
    # Try st.secrets first (Streamlit Cloud), fall back to env var
    try:
        import streamlit as st
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

GOOGLE_PLACES_API_KEY = _get("GOOGLE_PLACES_API_KEY")
GEMINI_API_KEY        = _get("GEMINI_API_KEY")
GROQ_API_KEY          = _get("GROQ_API_KEY")
DATABASE_URL          = _get("DATABASE_URL")
