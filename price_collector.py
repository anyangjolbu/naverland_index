"""시간 단위 최저호가 수집기.

DB complexes 에 저장된 Top 100 단지를 읽어
각 단지의 전용 59㎡ 매물 최저호가를 조회하고 hourly_prices 에 적재한다.
수집 결과는 동시에 CSV 파일 (data/collections/{date}.csv) 에도 append.
수집 완료 후 index_calculator.update() 를 호출해 hourly_index / OHLC 를 갱신한다.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import naver_api as api
from config import DATA_DIR
from database import get_complexes, insert_hourly_prices

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

CSV_DIR = DATA_DIR / "collections"
CSV_DIR.mkdir(parents=True, exist_ok=True)


def _floor_to_hour(dt: datetime) -> datetime:
    """분/초를 0으로 내려 시간 정각으로 정규화. timezone 제거해 naive KST로 저장."""
    return dt.replace(minute=0, second=0, microsecond=0, tzinfo=None)


def _save_csv(ts: datetime, rows: list[dict], complexes: list[dict]) -> Path:
    """수집 결과를 일자별 CSV 파일에 append.

    파일명: data/collections/{YYYY-MM-DD}.csv
    헤더가 없으면 첫 행에 헤더 추가.
    """
    cx_by_no = {c["complex_no"]: c for c in complexes}
    csv_path = CSV_DIR / f"{ts.date().isoformat()}.csv"
    is_new = not csv_path.exists()

    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow([
                "ts", "complex_no", "complex_name", "district",
                "household_cnt", "area_no_59",
                "min_price_manwon", "min_price_eok", "article_count",
            ])
        for r in rows:
            cx = cx_by_no.get(r["complex_no"], {})
            mp = r.get("min_price")
            ts_str = r["collected_at"].strftime("%Y-%m-%d %H:%M:%S") \
                if isinstance(r["collected_at"], datetime) else str(r["collected_at"])
            w.writerow([
                ts_str,
                r["complex_no"],
                cx.get("complex_name", ""),
                cx.get("district", ""),
                cx.get("household_cnt", ""),
                cx.get("area_no_59", ""),
                mp if mp is not None else "",
                f"{mp/10000:.4f}" if mp else "",
                r.get("article_count", 0),
            ])
    return csv_path


def run_collection() -> dict:
    """단지 100개에 대해 59㎡ 최저호가 수집 → DB + CSV 저장."""
    complexes = get_complexes()
    if not complexes:
        logger.warning("complexes 비어있음 — complex_selector 먼저 실행 필요")
        return {}

    now_kst = datetime.now(tz=KST)
    ts = _floor_to_hour(now_kst)

    logger.info("=== 호가 수집 시작: %s (%d개 단지) ===", ts.isoformat(), len(complexes))

    rows: list[dict] = []
    prices_eok: list[float] = []

    try:
        api.ensure_auth()

        for i, cx in enumerate(complexes):
            cx_no = cx["complex_no"]
            area_no = cx.get("area_no_59") or ""

            if not area_no:
                logger.warning("[%d] %s — area_no_59 없음, 건너뜀",
                               cx.get("rank", 0), cx["complex_name"])
                rows.append({
                    "collected_at": ts,
                    "complex_no": cx_no,
                    "min_price": None,
                    "article_count": 0,
                })
                continue

            try:
                min_price, article_count = api.get_min_price(cx_no, area_no)
            except Exception as e:
                logger.warning("[%s] get_min_price 오류: %s", cx_no, e)
                min_price, article_count = None, 0

            rows.append({
                "collected_at": ts,
                "complex_no": cx_no,
                "min_price": min_price,
                "article_count": article_count,
            })

            if min_price is not None:
                prices_eok.append(api.price_to_eok(min_price))

            logger.info(
                "[%d/%d] %s (%s): %s억 (%d건)",
                i + 1, len(complexes), cx["complex_name"], cx["district"],
                f"{api.price_to_eok(min_price):.2f}" if min_price else "N/A",
                article_count,
            )
            api.pace()
    finally:
        # 스레드별 브라우저는 다음 사이클을 위해 정리
        api.close_browser()

    # DB 저장
    saved = insert_hourly_prices(rows)

    # CSV 저장 (DB와 동일 데이터)
    try:
        csv_path = _save_csv(ts, rows, complexes)
        logger.info("CSV 저장: %s", csv_path)
    except Exception as e:
        logger.exception("CSV 저장 실패: %s", e)

    valid_count = len(prices_eok)
    missing_count = len(complexes) - valid_count

    avg_eok = sum(prices_eok) / valid_count if prices_eok else None
    sorted_p = sorted(prices_eok)
    n = len(sorted_p)
    median_eok = (
        (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2 if n % 2 == 0 else sorted_p[n // 2]
    ) if sorted_p else None

    logger.info(
        "=== 수집 완료: valid=%d, missing=%d, avg=%.2f억, median=%.2f억 ===",
        valid_count, missing_count,
        avg_eok or 0, median_eok or 0,
    )

    return {
        "ts": ts,
        "saved": saved,
        "valid": valid_count,
        "missing": missing_count,
        "avg_eok": avg_eok,
        "median_eok": median_eok,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    result = run_collection()
    if result:
        print(f"\n수집 결과:")
        print(f"  시각:    {result['ts']}")
        print(f"  저장:    {result['saved']}행")
        print(f"  유효:    {result['valid']}개 단지")
        print(f"  결측:    {result['missing']}개 단지")
        print(f"  평균:    {result['avg_eok']:.2f}억" if result['avg_eok'] else "  평균:    N/A")
        print(f"  중위:    {result['median_eok']:.2f}억" if result['median_eok'] else "  중위:    N/A")
