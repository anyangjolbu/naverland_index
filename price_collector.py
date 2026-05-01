"""시간 단위 최저호가 수집기 (Richgo 기반).

DB complexes 에 저장된 단지를 읽어
sgg(자치구) 단위로 한 번씩만 Richgo opengoods 조회 → 매핑 → DB/CSV 저장.

총 API 호출 = 자치구 수 (보통 8회). 단지별 호출하지 않음.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import richgo_api as api
from config import DATA_DIR, DISTRICTS, TARGET_PYEONG_TYPE
from database import get_complexes, insert_hourly_prices

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

CSV_DIR = DATA_DIR / "collections"
CSV_DIR.mkdir(parents=True, exist_ok=True)


def _floor_to_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0, tzinfo=None)


def _save_csv(ts: datetime, rows: list[dict], complexes: list[dict]) -> Path:
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
            ts_str = (
                r["collected_at"].strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(r["collected_at"], datetime) else str(r["collected_at"])
            )
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


def _fetch_prices_by_district() -> dict[str, dict]:
    """자치구별로 한 번씩 Richgo 호출 → {danjiId: row} 통합 맵.

    rows 는 Richgo opengoods 원본 dict (lowestListingPrice, listingTotalCount 포함).
    """
    aggregate: dict[str, dict] = {}
    for district_name, sgg_code in DISTRICTS.items():
        rows = api.list_opengoods_by_sgg(sgg_code)
        api.pace()
        matched = [r for r in rows if r.get("pyeongType") == TARGET_PYEONG_TYPE]
        for r in matched:
            danji_id = str(r.get("danjiId") or "")
            if danji_id:
                aggregate[danji_id] = r
        logger.info("[%s] %d평 %d건 수집", district_name, TARGET_PYEONG_TYPE, len(matched))
    return aggregate


def run_collection() -> dict:
    complexes = get_complexes()
    if not complexes:
        logger.warning("complexes 비어있음 — complex_selector 먼저 실행 필요")
        return {}

    now_kst = datetime.now(tz=KST)
    ts = _floor_to_hour(now_kst)

    logger.info("=== 호가 수집 시작: %s (%d개 단지) ===", ts.isoformat(), len(complexes))

    # 1) 자치구별로 한 번씩만 Richgo 호출
    price_map = _fetch_prices_by_district()
    logger.info("Richgo 가격 맵: %d개 danjiId", len(price_map))

    # 2) DB 단지 목록 순회하며 매핑
    rows: list[dict] = []
    prices_eok: list[float] = []
    by_district_count: dict[str, int] = defaultdict(int)

    for cx in complexes:
        cx_no = cx["complex_no"]
        rg = price_map.get(cx_no)
        min_price = rg.get("lowestListingPrice") if rg else None
        article_count = int(rg.get("listingTotalCount") or 0) if rg else 0
        rows.append({
            "collected_at": ts,
            "complex_no": cx_no,
            "min_price": min_price,
            "article_count": article_count,
        })
        if min_price is not None:
            prices_eok.append(api.price_to_eok(min_price))
            by_district_count[cx.get("district", "?")] += 1

    saved = insert_hourly_prices(rows)
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
        valid_count, missing_count, avg_eok or 0, median_eok or 0,
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
