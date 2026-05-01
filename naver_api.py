"""Naver Land API client — Playwright 브라우저 세션 기반.

직접 requests 로 호출하면 IP 차단(429)이 발생하므로,
Playwright Chromium 브라우저를 열어 new.land.naver.com 을 로드한 뒤
브라우저 안에서 page.evaluate(fetch(...)) 로 모든 API를 호출한다.

브라우저 세션은 threading.local() 로 스레드별 분리.
Playwright sync API 는 생성 스레드 외에서 사용 시 greenlet error 발생.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from config import (
    BACKOFF_BASE_SEC,
    BACKOFF_MAX_RETRIES,
    NAVER_API_BASE,
    NAVER_HEADERS,
    REQUEST_DELAY_SEC,
)

logger = logging.getLogger(__name__)

# ── 스레드별 브라우저 세션 ──────────────────────────────────────────────────

_local = threading.local()


def _get_state() -> dict:
    """현재 스레드의 브라우저 세션 상태."""
    if not hasattr(_local, "state"):
        _local.state = {
            "playwright": None,
            "browser": None,
            "context": None,
            "page": None,
            "auth_token": "",
        }
    return _local.state


def _launch_browser() -> None:
    """현재 스레드 전용 헤드리스 Chromium 을 열고 Naver Land 로드."""
    from playwright.sync_api import sync_playwright

    state = _get_state()
    logger.info("브라우저 시작 중 (thread=%s)...", threading.current_thread().name)
    state["playwright"] = sync_playwright().start()
    state["browser"] = state["playwright"].chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    state["context"] = state["browser"].new_context(
        user_agent=NAVER_HEADERS["User-Agent"],
        viewport={"width": 1366, "height": 768},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
    )
    state["context"].add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});"
    )
    state["page"] = state["context"].new_page()

    # 페이지 요청에서 Authorization 토큰 인터셉트
    def _on_request(req):
        if "new.land.naver.com/api/" in req.url and not state["auth_token"]:
            auth = req.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                state["auth_token"] = auth.split(" ", 1)[1]
                logger.info("Bearer 토큰 캡처 (len=%d)", len(state["auth_token"]))

    state["page"].on("request", _on_request)

    logger.info("Naver Land 초기 로드 중...")
    state["page"].goto(
        "https://new.land.naver.com/complexes",
        wait_until="networkidle",
        timeout=30_000,
    )
    state["page"].wait_for_timeout(2_000)

    if not state["auth_token"]:
        token = state["page"].evaluate(r"""
            () => {
                const m = document.body.innerHTML.match(/"token"\s*:\s*"(eyJ[^"]+)"/);
                return m ? m[1] : '';
            }
        """) or ""
        if token:
            state["auth_token"] = token
            logger.info("토큰 HTML 파싱 추출 (len=%d)", len(token))

    logger.info("브라우저 세션 준비 완료 (token=%s)", bool(state["auth_token"]))


def get_page():
    """현재 스레드 page 반환. 미초기화 시 launch."""
    state = _get_state()
    if state["page"] is None:
        _launch_browser()
    return state["page"]


def close_browser() -> None:
    """현재 스레드 브라우저 정리."""
    state = _get_state()
    for key in ("page", "context", "browser"):
        try:
            obj = state.get(key)
            if obj is not None:
                obj.close()
        except Exception:
            pass
    try:
        if state.get("playwright") is not None:
            state["playwright"].stop()
    except Exception:
        pass
    state["page"] = None
    state["context"] = None
    state["browser"] = None
    state["playwright"] = None
    state["auth_token"] = ""


def ensure_auth() -> bool:
    try:
        get_page()
        return True
    except Exception as e:
        logger.error("ensure_auth 실패: %s", e)
        return False


# ── 브라우저 내 fetch ───────────────────────────────────────────────────────

def _fetch(path: str, params: dict[str, Any] | None = None) -> Any:
    """브라우저 컨텍스트 안에서 Naver API 를 fetch 하고 JSON 반환."""
    qs = ""
    if params:
        # urlencode 대신 콜론 등 그대로 보존 (Naver areaNos 콜론 구분 지원)
        from urllib.parse import quote
        qs = "?" + "&".join(f"{k}={quote(str(v), safe=':,')}" for k, v in params.items())
    url = f"{NAVER_API_BASE}{path}{qs}"

    page = get_page()
    state = _get_state()
    for attempt in range(BACKOFF_MAX_RETRIES):
        try:
            result = page.evaluate(
                """async ([url, token]) => {
                    const headers = {'Accept': 'application/json'};
                    if (token) headers['Authorization'] = 'Bearer ' + token;
                    const r = await fetch(url, {credentials: 'include', headers});
                    return {status: r.status, body: await r.text()};
                }""",
                [url, state["auth_token"]],
            )
            status = result["status"]
            if status == 200:
                return json.loads(result["body"])
            if status == 429:
                wait = BACKOFF_BASE_SEC * (2 ** attempt)
                logger.warning("429 (attempt %d), wait %ds: %s", attempt, wait, path)
                time.sleep(wait)
                continue
            if status in (403, 404):
                logger.debug("HTTP %d: %s", status, url)
                return None
            logger.warning("HTTP %d: %s", status, url)
            return None
        except Exception as e:
            wait = BACKOFF_BASE_SEC * (2 ** attempt)
            logger.warning("fetch 오류 (attempt %d), wait %ds: %s", attempt, wait, e)
            time.sleep(wait)
    logger.error("요청 포기: %s", url)
    return None


# ── Endpoints ──────────────────────────────────────────────────────────────

def list_regions(cortar_no: str) -> list[dict]:
    data = _fetch("/api/regions/list", {"cortarNo": cortar_no})
    return (data or {}).get("regionList", [])


def list_complexes_in_dong(dong_cortar_no: str) -> list[dict]:
    data = _fetch("/api/regions/complexes",
                  {"cortarNo": dong_cortar_no, "realEstateType": "APT"})
    return (data or {}).get("complexList", [])


def get_complex_detail(complex_no: str) -> dict | None:
    return _fetch(f"/api/complexes/{complex_no}", {"sameAddressGroup": "false"})


def get_complex_overview(complex_no: str) -> dict | None:
    return _fetch(f"/api/complexes/overview/{complex_no}")


def list_articles(
    complex_no: str,
    area_no: str,
    page: int = 1,
    order: str = "prc",
) -> list[dict]:
    """매매(A1) 매물 목록.

    area_no: 단일 pyeongNo 또는 콜론 구분 다중 pyeongNo (예: '1:2:3').
    order:   'prc' (가격 오름차순, 기본), 'rank', 'date' 등.
    """
    data = _fetch(
        f"/api/articles/complex/{complex_no}",
        {
            "realEstateType": "APT",
            "tradeType": "A1",
            "areaNos": area_no,
            "page": page,
            "order": order,
        },
    )
    return (data or {}).get("articleList", [])


def get_min_price(complex_no: str, area_no: str) -> tuple[int | None, int]:
    """59㎡ 매매 최저호가 (만원), 매물 수.

    Naver Land 웹사이트와 동일하게 list_articles(order=prc) 의 page=1 결과에서
    최저가를 추출. area_no 가 콜론 구분 다중 pyeongNo 면 모든 subtype 포함.
    매물 없으면 (None, 0).
    """
    arts = list_articles(complex_no, area_no, page=1, order="prc")
    if not arts:
        return None, 0
    prices: list[int] = []
    for a in arts:
        raw = a.get("dealOrWarrantPrc") or ""
        # 매매(A1) 만 보장됐지만 한 번 더 필터
        trade_type = (a.get("tradeTypeName") or "").strip()
        if trade_type and "매매" not in trade_type:
            continue
        parsed = parse_price(raw)
        if parsed is not None:
            prices.append(parsed)
    if not prices:
        return None, len(arts)
    return min(prices), len(arts)


# ── Price parsing ──────────────────────────────────────────────────────────

_RE_NUM = re.compile(r"\d[\d,]*")


def parse_price(text: str | None) -> int | None:
    """네이버 호가 문자열 → 만원 정수.

    "18억 5,000"  → 185000
    "9억"         →  90000
    "5,500"       →   5500
    """
    if not text:
        return None
    s = str(text).strip()
    eok_part, man_part = 0, 0
    if "억" in s:
        before, _, after = s.partition("억")
        m = _RE_NUM.search(before)
        if m:
            eok_part = int(m.group().replace(",", ""))
        m = _RE_NUM.search(after)
        if m:
            man_part = int(m.group().replace(",", ""))
    else:
        m = _RE_NUM.search(s)
        if m:
            man_part = int(m.group().replace(",", ""))
    return eok_part * 10_000 + man_part


def price_to_eok(manwon: int | None) -> float | None:
    if manwon is None:
        return None
    return round(manwon / 10_000, 4)


# ── Pacing ─────────────────────────────────────────────────────────────────

def pace() -> None:
    time.sleep(REQUEST_DELAY_SEC)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    print("=== 가격 파서 테스트 ===")
    samples = ["18억 5,000", "9억", "5,500", "12억", "23억 3,000", "15억5000"]
    for s in samples:
        p = parse_price(s)
        print(f"  {s!r:>15s}  →  {p:>8} 만원  =  {price_to_eok(p)} 억")

    print()
    print("=== Naver API 연결 테스트 (강남구 동 목록) ===")
    dongs = list_regions("1168000000")
    print(f"강남구 동 수: {len(dongs)}")
    for d in dongs[:5]:
        print(f"  {d.get('cortarNo')} - {d.get('cortarName')}")
    close_browser()
