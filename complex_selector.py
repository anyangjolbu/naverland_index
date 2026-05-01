"""단지 풀 부트스트랩 (Naver 정적 데이터 + Richgo 매핑).

이전엔 Naver 사이트를 크롤링해서 100개 단지를 동적 선정했지만
Naver 가 클라우드 IP 를 차단해서 Railway 에선 불가능.

대신:
  1. complexes.json (이전 로컬 Naver 크롤링으로 만든 100개 단지 정보 — 세대수 등)
  2. richgo_mapping.json (Naver complex_no → Richgo danjiId 매핑)
이 두 파일을 repo 에 박아넣고, 부트스트랩 시 DB 에 upsert 한다.

세대수, rank, complex_name 같은 정적 정보는 영원히 안 변하므로 한 번만 등록.
가격은 price_collector 가 매시간 Richgo 에서 lookup.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import BASE_DIR
from database import transaction, upsert_complexes

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

COMPLEXES_FILE = BASE_DIR / "complexes.json"
MAPPING_FILE = BASE_DIR / "richgo_mapping.json"


def _load() -> tuple[list[dict], dict[str, dict]]:
    """(naver_complexes_100, mapping_by_complex_no) 로드."""
    with COMPLEXES_FILE.open(encoding="utf-8") as f:
        complexes = json.load(f)
    with MAPPING_FILE.open(encoding="utf-8") as f:
        mapping_doc = json.load(f)
    mapping = mapping_doc.get("mapping", {})
    return complexes, mapping


def run_selection(save_to_db: bool = True) -> list[dict]:
    """canonical 100개 단지를 DB upsert. 매번 같은 결과 반환 (정적)."""
    complexes, mapping = _load()
    logger.info("canonical 단지 %d개, Richgo 매핑 %d개",
                len(complexes), len(mapping))

    rows: list[dict] = []
    mapped_n = 0
    for c in complexes:
        cx_no = c["complex_no"]
        m = mapping.get(cx_no)
        danji_id = m["danjiId"] if m else None
        if danji_id:
            mapped_n += 1
        rows.append({
            "complex_no": cx_no,
            "complex_name": c["complex_name"],
            "district": c["district"],
            "household_cnt": c["household_cnt"],
            "trade_volume": c.get("trade_volume"),
            "area_no_59": c.get("area_no_59", ""),
            "pyeong_no": c.get("pyeong_no", ""),
            "rank": c.get("rank"),
            "richgo_danji_id": danji_id,
        })

    if save_to_db:
        now = datetime.now(tz=KST)
        # 이전 스키마/identity 잔재 정리: complex_no 가 digits 가 아닌 행 제거.
        # (이전 시도는 Richgo 의 danjiId 를 complex_no 로 썼었음 — "a"로 시작.)
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM complexes WHERE complex_no NOT GLOB '[0-9]*'"
            )
            n_legacy = cur.rowcount
            if n_legacy:
                logger.info("legacy(non-digit complex_no) 제거: %d행", n_legacy)
                # 해당 hourly_prices 도 cascade 정리
                conn.execute(
                    "DELETE FROM hourly_prices WHERE complex_no NOT GLOB '[0-9]*'"
                )
                # 잘못된 시각의 집계도 폐기 (모든 시각 다 wipe — 새로 채워질 것)
                conn.execute("DELETE FROM hourly_index")
                conn.execute("DELETE FROM hourly_ohlc")
                conn.execute("DELETE FROM daily_ohlc")
        upsert_complexes(rows, selected_at=now)
        logger.info("DB upsert 완료 (%d/%d 매핑됨)", mapped_n, len(rows))

    return rows


def refresh() -> list[dict]:
    logger.info("=== 단지 풀 부트스트랩 (정적) ===")
    result = run_selection()
    logger.info("=== 부트스트랩 완료: %d개 ===", len(result))
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    rows = run_selection()
    mapped = [r for r in rows if r["richgo_danji_id"]]
    print(f"\n{len(rows)}개 단지 중 {len(mapped)}개 Richgo 매핑됨")
    print(f"{'순위':>4}  {'단지명':<22}  {'구':>6}  {'세대':>6}  Richgo")
    print("-" * 70)
    for c in rows[:20]:
        marker = c["richgo_danji_id"] or "-"
        print(f"{c['rank']:>4}  {c['complex_name']:<22}  {c['district']:>6}  "
              f"{c['household_cnt']:>6}  {marker}")
