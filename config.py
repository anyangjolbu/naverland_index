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

# ── Districts (cortarNo) ───────────────────────────────────────────────────
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
MIN_HOUSEHOLD_COUNT = 500
TARGET_AREA_M2 = 59          # 전용면적 기준
AREA_TOLERANCE = 3.0         # 56 ~ 62㎡ 까지 59㎡ 평형으로 인정
TOP_N_COMPLEXES = 100

# ── Naver Land API ─────────────────────────────────────────────────────────
NAVER_API_BASE = "https://new.land.naver.com"
NAVER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://new.land.naver.com/complexes",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}
# Naver Land 페이지에서 발급되는 고정 JWT (REALESTATE payload).
# 만료 시 naver_api.refresh_auth_token() 으로 갱신.
NAVER_AUTH_TOKEN = os.environ.get("NAVER_AUTH_TOKEN", "")

# Per-complex request spacing (seconds)
REQUEST_DELAY_SEC = 1.5
# Exponential backoff base for 429
BACKOFF_BASE_SEC = 5
BACKOFF_MAX_RETRIES = 4

# ── Scheduling ─────────────────────────────────────────────────────────────
COLLECT_CRON_MINUTE = 0      # 매시간 정각 (KST)
SELECTOR_REFRESH_HOURS = 1   # 단지 풀 재확인 주기 (사용자 결정: 1시간)

# ── Flask ──────────────────────────────────────────────────────────────────
FLASK_HOST = "0.0.0.0"
FLASK_PORT = int(os.environ.get("PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
