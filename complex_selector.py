"""Top N 단지 선정기 (Richgo 기반).

8개 자치구 sgg-level opengoods 호출 → pyeongType=24(59㎡) 필터
→ listingTotalCount 내림차순 Top N → DB upsert.

Richgo 의 sgg 단위 응답은 ~50건으로 캡되므로,
실제 24평 단지는 자치구당 5~15개 정도. 8개 합쳐 보통 40~80개 단지가 모임.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import richgo_api as api
from config import COMPLEXES_CACHE_PATH, DISTRICTS, TARGET_PYEONG_TYPE, TOP_N_COMPLEXES
from database import upsert_complexes

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _collect_for_district(district_name: str, sgg_code: str) -> list[dict]:
    """sgg 단위 조회 → pyeongType=24 필터 → 단지 dict 리스트."""
    rows = api.list_opengoods_by_sgg(sgg_code)
    api.pace()
    matched = [r for r in rows if r.get("pyeongType") == TARGET_PYEONG_TYPE]
    logger.info("[%s] 전체 %d건, %d평 %d건",
                district_name, len(rows), TARGET_PYEONG_TYPE, len(matched))

    out: list[dict] = []
    for r in matched:
        danji_id = str(r.get("danjiId") or "")
        if not danji_id:
            continue
        out.append({
            "complex_no": danji_id,
            "complex_name": r.get("danji") or "",
            "district": district_name,
            # Richgo opengoods 응답에 세대수가 없어, 매물 수를 인기 지표로 사용
            "household_cnt": int(r.get("listingTotalCount") or 0),
            "trade_volume": None,
            "area_no_59": r.get("supplyAreaRep") or "",
            "pyeong_no": str(r.get("pyeongType") or ""),
        })
    return out


def run_selection(save_to_db: bool = True) -> list[dict]:
    """8개 자치구 순회 → Top N 단지(매물 수 기준) 선정 + DB upsert."""
    all_candidates: list[dict] = []
    for district_name, sgg_code in DISTRICTS.items():
        try:
            cands = _collect_for_district(district_name, sgg_code)
            all_candidates.extend(cands)
        except Exception as e:
            logger.exception("[%s] 수집 오류: %s", district_name, e)

    if not all_candidates:
        logger.error("후보 단지 0개 — 선정 실패")
        return []

    # danjiId 중복 제거 (있을 리 없지만 방어)
    seen: set[str] = set()
    unique: list[dict] = []
    for c in all_candidates:
        if c["complex_no"] not in seen:
            seen.add(c["complex_no"])
            unique.append(c)

    # listingTotalCount 내림차순 → Top N
    unique.sort(key=lambda x: x["household_cnt"], reverse=True)
    selected = unique[:TOP_N_COMPLEXES]
    for rank, c in enumerate(selected, start=1):
        c["rank"] = rank

    logger.info(
        "Top %d 선정 완료 (전체 후보 %d개, 매물 %d~%d)",
        len(selected),
        len(unique),
        selected[-1]["household_cnt"] if selected else 0,
        selected[0]["household_cnt"] if selected else 0,
    )

    try:
        COMPLEXES_CACHE_PATH.write_text(
            json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    if save_to_db:
        now = datetime.now(tz=KST)
        upsert_complexes(selected, selected_at=now)
        logger.info("DB upsert 완료 (%d개)", len(selected))

    return selected


def refresh() -> list[dict]:
    logger.info("=== 단지 풀 갱신 (Richgo) ===")
    result = run_selection()
    logger.info("=== 갱신 완료: %d개 ===", len(result))
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    selected = run_selection()
    print(f"\n선정 결과: {len(selected)}개\n")
    print(f"{'순위':>4}  {'단지명':<22}  {'구':>6}  {'매물':>6}  공급면적")
    print("-" * 60)
    for c in selected[:20]:
        print(
            f"{c['rank']:>4}  {c['complex_name']:<22}  {c['district']:>6}  "
            f"{c['household_cnt']:>6}  {c['area_no_59']}"
        )
    if len(selected) > 20:
        print(f"  ... 외 {len(selected) - 20}개")
