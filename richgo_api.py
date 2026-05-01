"""Richgo API client.

Naver의 IP 차단을 우회하기 위해 Richgo (richgo.ai) 의 공개 API 를 사용한다.
Richgo는 인증 없이 호출 가능하며 Railway 클라우드 IP 도 차단하지 않음.

가격 단위: 만원 (Naver 와 동일).
평형: pyeongType=24 가 59㎡ 전용 (= ~79㎡ 공급) 에 해당.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api-m.richgo.ai"
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

REQUEST_DELAY_SEC = 0.5
TIMEOUT_SEC = 15
MAX_RETRIES = 3
BACKOFF_BASE_SEC = 2


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(DEFAULT_HEADERS)
    return _session


def _get(path: str, params: dict[str, Any]) -> Any:
    """Richgo GET. 200 → JSON.result; 그 외 → None (이미 로그됨)."""
    url = f"{API_BASE}{path}"
    session = _get_session()
    last_err: str | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT_SEC)
            if r.status_code == 200:
                payload = r.json()
                # Richgo 응답 wrapper: {result, isError, statusCode, ...}
                if isinstance(payload, dict) and payload.get("isError"):
                    logger.warning("Richgo API isError=True: %s", payload.get("responseException"))
                    return None
                return payload.get("result") if isinstance(payload, dict) else payload
            if r.status_code == 429:
                wait = BACKOFF_BASE_SEC * (2 ** attempt)
                logger.warning("429 (attempt %d), wait %ds: %s", attempt, wait, path)
                time.sleep(wait)
                continue
            logger.warning("HTTP %d: %s %s", r.status_code, path, params)
            return None
        except requests.RequestException as e:
            last_err = str(e)
            wait = BACKOFF_BASE_SEC * (2 ** attempt)
            logger.warning("요청 오류 (attempt %d), wait %ds: %s", attempt, wait, e)
            time.sleep(wait)
    logger.error("요청 포기: %s (last err: %s)", url, last_err)
    return None


def pace() -> None:
    time.sleep(REQUEST_DELAY_SEC)


# ── Endpoints ──────────────────────────────────────────────────────────────

def list_opengoods_by_sgg(
    sgg_bjd_code: str,
    *,
    trade_type: str = "Meme",          # 매매
    building_type: str = "APT",
    limit: int = 200,
    only_today: bool = False,
    only_leaders: bool = False,
    except_low_floor: bool = False,
) -> list[dict]:
    """자치구(시군구 코드) 단위로 매물 가격 정보 가져오기.

    Returns danji 별 1행 (lowestListingPrice 기준).
    실제 응답은 약 50건으로 캡되는 듯.
    """
    params = {
        "limit": limit,
        "bjdCode": sgg_bjd_code,
        "tradeType": trade_type,
        "isOnlyToday": str(only_today).lower(),
        "isOnlyLeaders": str(only_leaders).lower(),
        "buildingTypeCode": building_type,
        "isExceptLowFloor": str(except_low_floor).lower(),
    }
    result = _get("/api/data/danji/price/opengoods", params)
    return result if isinstance(result, list) else []


def get_danji_onepage(danji_id: str) -> dict | None:
    """단일 단지 종합 정보 (현재 minOfferPrice, totalPostCount 등)."""
    result = _get("/api/data/danji/onepage", {"danjiId": danji_id})
    return result if isinstance(result, dict) else None


# ── Helpers ────────────────────────────────────────────────────────────────

def price_to_eok(manwon: int | None) -> float | None:
    if manwon is None:
        return None
    return round(manwon / 10_000, 4)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    print("=== 강남구 24평 단지 (Richgo) ===")
    rows = list_opengoods_by_sgg("1168000000")
    twentyfours = [r for r in rows if r.get("pyeongType") == 24]
    print(f"전체 {len(rows)}건, 24평 {len(twentyfours)}건")
    for r in twentyfours[:10]:
        print(f"  {r['danjiId']:>10s}  {r['danji']:<22s}  "
              f"{price_to_eok(r['lowestListingPrice'])}억  "
              f"매물{r['listingTotalCount']}개")
