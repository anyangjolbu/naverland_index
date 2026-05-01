"""Configuration constants for the Seoul APT 59㎡ Index project."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "index.db"
COMPLEXES_CACHE_PATH = DATA_DIR / "complexes.json"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ── Timezone ───────────────────────────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")

# ── Districts (sggBjdCode = Naver cortarNo와 동일 10자리) ──────────────────
DISTRICTS = {
    "강남구": "1168000000",
    "서초구": "1165000000",
    "용산구": "1117000000",
    "송파구": "1171000000",
    "마포구": "1144000000",
    "성동구": "1120000000",
    "동작구": "1159000000",
    "강동구": "1174000000",
}

# ── Selection criteria ─────────────────────────────────────────────────────
# Richgo 의 pyeongType=24 가 59㎡ 전용 (~79㎡ 공급) 평형
TARGET_PYEONG_TYPE = 24
TOP_N_COMPLEXES = 100        # listingTotalCount(매물 수) 내림차순 Top N

# ── Flask ──────────────────────────────────────────────────────────────────
FLASK_HOST = "0.0.0.0"
FLASK_PORT = int(os.environ.get("PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
