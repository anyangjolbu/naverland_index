"""Flask web app + APScheduler.

스케줄:
  - 매시간 02분 (KST): price_collector 만 실행 (가벼움, ~3분)
  - 매일 03:30 (KST):  complex_selector + price_collector + index_calculator (전체 갱신)

API:
  GET  /api/hourly?limit=720       → 시간봉 OHLC JSON
  GET  /api/daily?limit=365        → 일봉 OHLC JSON
  GET  /api/complexes              → 단지 목록 + 최신 호가
  GET  /api/district/hourly        → 자치구별 시간봉 평균
  GET  /api/status                 → 스케줄러 / 수집 상태
  POST /api/run                    → 수동 즉시 가격 수집
  POST /api/refresh                → 수동 단지 풀 + 가격 갱신 (느림)
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, render_template, request

from config import FLASK_DEBUG, FLASK_HOST, FLASK_PORT, LOGS_DIR
from database import get_complexes, get_daily_ohlc, get_hourly_ohlc, init_db

# ── Logging ────────────────────────────────────────────────────────────────
_log_file = LOGS_DIR / "app.log"
_handlers: list[logging.Handler] = [
    logging.StreamHandler(),
    RotatingFileHandler(_log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"),
]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# ── 수집 상태 ───────────────────────────────────────────────────────────────
_status: dict = {
    "last_run": None,
    "last_result": None,
    "is_running": False,
    "error": None,
}
_lock = threading.Lock()


def _acquire_run() -> bool:
    """is_running 플래그를 atomically 설정. 이미 실행 중이면 False."""
    with _lock:
        if _status["is_running"]:
            return False
        _status["is_running"] = True
        _status["error"] = None
        return True


def _release_run(error: str | None = None, result: dict | None = None) -> None:
    with _lock:
        _status["is_running"] = False
        if error is not None:
            _status["error"] = error
        if result is not None:
            _status["last_run"] = datetime.now(tz=KST).isoformat()
            _status["last_result"] = result


def _run_price_only() -> None:
    """가격 수집만 — selector 제외 (~2~3분)."""
    if not _acquire_run():
        logger.warning("이미 실행 중 — 가격 수집 건너뜀")
        return
    import index_calculator
    import price_collector
    try:
        logger.info("=== 가격 수집 시작 (selector 제외) ===")
        result = price_collector.run_collection()
        if result:
            index_calculator.update(result.get("ts"))
        _release_run(result=result)
        logger.info("=== 가격 수집 완료 ===")
    except Exception as e:
        logger.exception("수집 오류: %s", e)
        _release_run(error=str(e))


def _run_full_refresh() -> None:
    """단지 풀 갱신 + 가격 수집 + 지표 갱신 (~30~60분)."""
    if not _acquire_run():
        logger.warning("이미 실행 중 — 전체 갱신 건너뜀")
        return
    import complex_selector
    import index_calculator
    import price_collector
    try:
        logger.info("=== 전체 갱신 시작 ===")
        complex_selector.refresh()
        result = price_collector.run_collection()
        if result:
            index_calculator.update(result.get("ts"))
        _release_run(result=result)
        logger.info("=== 전체 갱신 완료 ===")
    except Exception as e:
        logger.exception("전체 갱신 오류: %s", e)
        _release_run(error=str(e))


# ── Scheduler ──────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone=KST)
scheduler.add_job(
    _run_price_only,
    trigger=CronTrigger(minute=2, timezone=KST),
    id="hourly_price",
    max_instances=1,
    replace_existing=True,
    coalesce=True,
    misfire_grace_time=300,
)
scheduler.add_job(
    _run_full_refresh,
    trigger=CronTrigger(hour=3, minute=30, timezone=KST),
    id="daily_full",
    max_instances=1,
    replace_existing=True,
    coalesce=True,
    misfire_grace_time=600,
)


# ── API routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/hourly")
def api_hourly():
    limit = request.args.get("limit", 720, type=int)
    return jsonify(get_hourly_ohlc(limit=limit))


@app.route("/api/daily")
def api_daily():
    limit = request.args.get("limit", 365, type=int)
    return jsonify(get_daily_ohlc(limit=limit))


@app.route("/api/complexes")
def api_complexes():
    from database import get_connection
    complexes = get_complexes()
    conn = get_connection()
    for cx in complexes:
        row = conn.execute(
            """
            SELECT min_price, collected_at
              FROM hourly_prices
             WHERE complex_no = ? AND min_price IS NOT NULL
             ORDER BY collected_at DESC LIMIT 1
            """,
            (cx["complex_no"],),
        ).fetchone()
        if row:
            from naver_api import price_to_eok
            cx["latest_price_eok"] = price_to_eok(row["min_price"])
            cx["latest_at"] = row["collected_at"]
        else:
            cx["latest_price_eok"] = None
            cx["latest_at"] = None
    conn.close()
    return jsonify(complexes)


@app.route("/api/status")
def api_status():
    with _lock:
        next_runs = {}
        for jid in ("hourly_price", "daily_full"):
            j = scheduler.get_job(jid)
            next_runs[jid] = j.next_run_time.isoformat() if j and j.next_run_time else None
        return jsonify({
            **_status,
            "scheduler_running": scheduler.running,
            "next_runs": next_runs,
            # 호환성: 단일 next_run 도 유지
            "next_run": next_runs.get("hourly_price"),
        })


@app.route("/api/run", methods=["POST"])
def api_run_now():
    """수동 즉시 가격 수집."""
    t = threading.Thread(target=_run_price_only, daemon=True, name="manual-price")
    t.start()
    return jsonify({"status": "started", "kind": "price_only"})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """수동 전체 갱신 (단지 풀 재선정 포함, 느림)."""
    t = threading.Thread(target=_run_full_refresh, daemon=True, name="manual-full")
    t.start()
    return jsonify({"status": "started", "kind": "full_refresh"})


@app.route("/api/debug/connectivity")
def api_debug_connectivity():
    """진단: Railway에서 네이버까지 어떻게 막히는지 단계별로 확인."""
    import socket
    import urllib.request
    import urllib.error
    from config import NAVER_HEADERS

    out: dict = {}

    # 1. DNS 해상
    try:
        out["1_dns"] = {"ip": socket.gethostbyname("new.land.naver.com")}
    except Exception as e:
        out["1_dns"] = {"error": str(e)}

    def _try(name: str, url: str, headers: dict | None = None):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read(500).decode("utf-8", errors="replace")
                out[name] = {"status": r.status, "len_first500": len(body), "head": body[:200]}
        except urllib.error.HTTPError as e:
            body = e.read(500).decode("utf-8", errors="replace") if e.fp else ""
            out[name] = {"status": e.code, "head": body[:200]}
        except Exception as e:
            out[name] = {"error": f"{type(e).__name__}: {e}"}

    # 2. 메인 페이지 HTTP (헤더 없음)
    _try("2_html_naked", "https://new.land.naver.com/complexes")
    # 3. 메인 페이지 HTTP (브라우저 헤더)
    _try("3_html_browser", "https://new.land.naver.com/complexes", NAVER_HEADERS)
    # 4. API 직접 (헤더 없음)
    _try("4_api_naked", "https://new.land.naver.com/api/regions/list?cortarNo=1168000000")
    # 5. API 직접 (브라우저 헤더)
    _try("5_api_browser",
         "https://new.land.naver.com/api/regions/list?cortarNo=1168000000",
         NAVER_HEADERS)
    # 6. 모바일 land
    _try("6_m_land", "https://m.land.naver.com/", NAVER_HEADERS)
    # 7. 일반 land
    _try("7_land", "https://land.naver.com/", NAVER_HEADERS)
    # 8. 다른 naver 도메인 (대조군 — 차단 아닌지 확인)
    _try("8_naver_main", "https://www.naver.com/", NAVER_HEADERS)
    # 9. 공개 CORS 프록시 통과 (allorigins.win)
    _try("9_via_allorigins",
         "https://api.allorigins.win/raw?url=https%3A%2F%2Fnew.land.naver.com%2Fapi%2Fregions%2Flist%3FcortarNo%3D1168000000",
         {"Accept": "application/json"})
    # 10. 다른 공개 프록시 (corsproxy.io)
    _try("10_via_corsproxy",
         "https://corsproxy.io/?https%3A%2F%2Fnew.land.naver.com%2Fapi%2Fregions%2Flist%3FcortarNo%3D1168000000",
         {"Accept": "application/json"})
    # 11~ : land.naver.com (구버전) 의 다양한 path 탐색
    for name, url in [
        ("11_land_api_regions", "https://land.naver.com/api/regions/list?cortarNo=1168000000"),
        ("12_land_complex", "https://land.naver.com/article/articleList.naver?rletTpCd=APT&tradTpCd=A1"),
        ("13_land_complex_search", "https://land.naver.com/complex/cluster"),
        ("14_fin_land", "https://fin.land.naver.com/"),
        ("15_realestate", "https://realestate.naver.com/"),
        # 새 land 시도하지만 Host 헤더만 land.naver.com
        ("16_land_complexes_path", "https://land.naver.com/complexes/108234"),
        # 또 다른 Naver 부동산 관련 (네이버 검색)
        ("17_search_realestate", "https://search.naver.com/search.naver?query=%EC%95%84%ED%8C%8C%ED%8A%B8"),
    ]:
        _try(name, url, NAVER_HEADERS)

    return jsonify(out)


@app.route("/api/district/hourly")
def api_district_hourly():
    """자치구별 시간봉 평균 최저호가.

    SQLite strftime 으로 정시 정규화해 마이크로초/포맷 차이 흡수.
    """
    from collections import defaultdict
    from database import get_connection
    limit = request.args.get("limit", 168, type=int)
    conn = get_connection()
    # 최근 N개 정시 buckets
    ts_rows = conn.execute(
        """
        SELECT DISTINCT strftime('%Y-%m-%d %H:00:00', collected_at) AS ts
          FROM hourly_prices
         ORDER BY ts DESC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not ts_rows:
        conn.close()
        return jsonify({})
    oldest_ts = ts_rows[-1]["ts"]
    rows = conn.execute(
        """
        SELECT strftime('%Y-%m-%d %H:00:00', hp.collected_at) AS ts,
               c.district,
               ROUND(AVG(CAST(hp.min_price AS REAL) / 10000.0), 2) AS avg_eok,
               COUNT(*) AS cnt
          FROM hourly_prices hp
          JOIN complexes c ON c.complex_no = hp.complex_no
         WHERE hp.min_price IS NOT NULL
           AND strftime('%Y-%m-%d %H:00:00', hp.collected_at) >= ?
         GROUP BY ts, c.district
         ORDER BY ts ASC
        """,
        (oldest_ts,),
    ).fetchall()
    conn.close()
    result: dict = defaultdict(list)
    for r in rows:
        result[r["district"]].append({
            "ts": r["ts"],
            "avg": r["avg_eok"],
            "count": r["cnt"],
        })
    return jsonify(dict(result))


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    scheduler.start()
    logger.info("스케줄러 시작 — 매시간 02분 가격 수집 + 매일 03:30 전체 갱신 (KST)")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG, use_reloader=False)
