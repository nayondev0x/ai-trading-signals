"""App configuration loaded from environment / .env file."""
import os
from pathlib import Path

# Minimal .env loader (no external dependency required).
BASE_DIR = Path(__file__).resolve().parent.parent
_env_path = BASE_DIR / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST", "crypto-signal-api.p.rapidapi.com")
SYMBOLS = [s.strip() for s in os.getenv(
    "SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT"
).split(",") if s.strip()]
USE_MOCK_FALLBACK = os.getenv("USE_MOCK_FALLBACK", "true").lower() == "true"

BASE_URL = f"https://{RAPIDAPI_HOST}"
