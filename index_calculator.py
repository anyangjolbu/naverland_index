"""Index 및 OHLC 계산기.

hourly_prices → hourly_index (avg/median, 억 단위) → hourly_ohlc → daily_ohlc

시간봉 OHLC:
  - open  = 직전 시간 close (없으면 현재값)
  - close = 현재 avg (또는 median)
  - high  = max(open, close, 75th-pct of individual prices)
  - low   = min(open, close, 25th-pct of individual prices)

일봉 OHLC (KST 00:00 ~ 23:59):
  - open  = 당일 첫 시간봉 open
  - high  = 당일 시간봉 high 의 max
  - low   = 당일 시간봉 low 의 min
  - close = 당일 마지막 시간봉 close
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from database import (
    get_connection,
    upsert_daily_ohlc,
    upsert_hourly_index,
    upsert_hourly_ohlc,
)

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


# ── 통계 헬퍼 ──────────────────────────────────────────────────────────────

def _percentile(sorted_vals: list[float], pct: float) -> float | None:
    if not sorted_vals:
        return None
    idx = (len(sorted_vals) - 1) * pct
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return (s[n // 2 - 1] + s[n // 2]) / 2 if n % 2 == 0 else s[n // 2]


def _mean(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


# ── 시간 단위 집계 ─────────────────────────────────────────────────────────

def update_hourly(ts: datetime) -> dict | None:
    """ts 시각의 hourly_prices → hourly_index + hourly_ohlc 갱신.

    Returns computed stats dict, or None if no data.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT hp.min_price, hp.complex_no
          FROM hourly_prices hp
         WHERE hp.collected_at = ?
           AND hp.min_price IS NOT NULL
        """,
        (ts,),
    ).fetchall()
    conn.close()

    if not rows:
        logger.warning("update_hourly(%s): 데이터 없음", ts)
        return None

    # 가격 배열 (억 단위)
    prices_eok = sorted(r["min_price"] / 10_000 for r in rows)
    valid_count = len(prices_eok)

    avg = _mean(prices_eok)
    med = _median(prices_eok)
    p25 = _percentile(prices_eok, 0.25)
    p75 = _percentile(prices_eok, 0.75)

    # hourly_index 갱신
    conn2 = get_connection()
    total = conn2.execute(
        "SELECT COUNT(*) as cnt FROM hourly_prices WHERE collected_at = ?", (ts,)
    ).fetchone()["cnt"]
    conn2.close()

    upsert_hourly_index(ts, avg, med, total, valid_count)

    # hourly_ohlc 갱신 — 직전 시간 close 조회
    prev_ts = ts - timedelta(hours=1)
    conn3 = get_connection()
    prev = conn3.execute(
        "SELECT avg_close, median_close FROM hourly_ohlc WHERE ts = ?", (prev_ts,)
    ).fetchone()
    conn3.close()

    if prev:
        avg_open = prev["avg_close"] or avg
        med_open = prev["median_close"] or med
    else:
        avg_open = avg
        med_open = med

    def _ohlc(open_: float, close_: float, p25_: float, p75_: float):
        high = max(open_ or 0, close_ or 0, p75_ or 0)
        low  = min(x for x in [open_, close_, p25_] if x is not None)
        return round(open_, 4), round(high, 4), round(low, 4), round(close_, 4)

    if avg is not None and avg_open is not None:
        ao, ah, al, ac = _ohlc(avg_open, avg, p25 or avg, p75 or avg)
    else:
        ao = ah = al = ac = None

    if med is not None and med_open is not None:
        mo, mh, ml, mc = _ohlc(med_open, med, p25 or med, p75 or med)
    else:
        mo = mh = ml = mc = None

    ohlc_row = {
        "ts": ts,
        "avg_open": ao, "avg_high": ah, "avg_low": al, "avg_close": ac,
        "median_open": mo, "median_high": mh, "median_low": ml, "median_close": mc,
        "valid_count": valid_count,
    }
    upsert_hourly_ohlc(ohlc_row)

    logger.info(
        "hourly(%s): avg=%.2f억(O%.2f H%.2f L%.2f C%.2f) valid=%d",
        ts, avg or 0, ao or 0, ah or 0, al or 0, ac or 0, valid_count,
    )
    return {"ts": ts, "avg": avg, "median": med, "valid": valid_count}


# ── 일봉 갱신 ──────────────────────────────────────────────────────────────

def update_daily(kst_date: date) -> None:
    """KST 날짜의 hourly_ohlc 를 집계해 daily_ohlc 갱신.

    해당 날짜 = KST 00:00:00 ~ 23:59:59.
    """
    day_start = datetime(kst_date.year, kst_date.month, kst_date.day, 0, 0, 0)
    day_end   = datetime(kst_date.year, kst_date.month, kst_date.day, 23, 59, 59)

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM hourly_ohlc
         WHERE ts >= ? AND ts <= ?
         ORDER BY ts ASC
        """,
        (day_start, day_end),
    ).fetchall()
    conn.close()

    if not rows:
        return

    rows = [dict(r) for r in rows]
    hour_count = len(rows)

    # avg OHLC
    avg_opens  = [r["avg_open"]  for r in rows if r["avg_open"]  is not None]
    avg_highs  = [r["avg_high"]  for r in rows if r["avg_high"]  is not None]
    avg_lows   = [r["avg_low"]   for r in rows if r["avg_low"]   is not None]
    avg_closes = [r["avg_close"] for r in rows if r["avg_close"] is not None]

    med_opens  = [r["median_open"]  for r in rows if r["median_open"]  is not None]
    med_highs  = [r["median_high"]  for r in rows if r["median_high"]  is not None]
    med_lows   = [r["median_low"]   for r in rows if r["median_low"]   is not None]
    med_closes = [r["median_close"] for r in rows if r["median_close"] is not None]

    daily_row = {
        "date": kst_date.isoformat(),
        "avg_open":   round(avg_opens[0],  4) if avg_opens  else None,
        "avg_high":   round(max(avg_highs), 4) if avg_highs else None,
        "avg_low":    round(min(avg_lows),  4) if avg_lows  else None,
        "avg_close":  round(avg_closes[-1], 4) if avg_closes else None,
        "median_open":  round(med_opens[0],   4) if med_opens  else None,
        "median_high":  round(max(med_highs),  4) if med_highs else None,
        "median_low":   round(min(med_lows),   4) if med_lows  else None,
        "median_close": round(med_closes[-1],  4) if med_closes else None,
        "hour_count": hour_count,
    }
    upsert_daily_ohlc(daily_row)
    logger.info(
        "daily(%s): avg O%.2f H%.2f L%.2f C%.2f  hours=%d",
        kst_date,
        daily_row["avg_open"] or 0, daily_row["avg_high"] or 0,
        daily_row["avg_low"] or 0,  daily_row["avg_close"] or 0,
        hour_count,
    )


def update(ts: datetime | None = None) -> None:
    """수집 완료 직후 호출: hourly + 해당 날짜 daily 갱신."""
    if ts is None:
        now = datetime.now(tz=KST).replace(minute=0, second=0, microsecond=0, tzinfo=None)
        ts = now
    update_hourly(ts)
    update_daily(ts.date())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    from database import init_db
    init_db()
    update()
