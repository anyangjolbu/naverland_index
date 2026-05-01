"""Top 100 단지 선정기.

8개 자치구 → 동 → 단지 트래버스 후
  · 세대수 ≥ 1000
  · 전용 59㎡ 평형 보유 (exclusiveArea 56~62㎡ 허용)
조건 통과 단지를 세대수 내림차순 → Top 100.

결과를 DB complexes 테이블에 upsert.
매시간 1회 호출(APScheduler).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import naver_api as api
from config import (
    AREA_TOLERANCE,
    COMPLEXES_CACHE_PATH,
    DISTRICTS,
    MIN_HOUSEHOLD_COUNT,
    TARGET_AREA_M2,
    TOP_N_COMPLEXES,
)
from database import upsert_complexes

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


# ── 59㎡ 평형 탐색 ──────────────────────────────────────────────────────────

def _find_59_pyeongs(complex_detail: dict) -> list[str]:
    """단지 상세에서 56~62㎡ 범위의 모든 pyeongNo 리스트 반환.

    A/B/C 등 여러 59㎡ subtype 이 있을 경우 모두 수집해
    list_articles 호출 시 콜론 구분으로 한 번에 조회하기 위함.
    """
    pyeong_list = complex_detail.get("complexPyeongDetailList") or []
    lo = TARGET_AREA_M2 - AREA_TOLERANCE   # 56
    hi = TARGET_AREA_M2 + AREA_TOLERANCE   # 62
    matches: list[str] = []
    for p in pyeong_list:
        try:
            area_f = float(p.get("exclusiveArea") or 0)
        except (ValueError, TypeError):
            continue
        if lo <= area_f <= hi:
            pyeong_no = str(p.get("pyeongNo", "") or "")
            if pyeong_no and pyeong_no not in matches:
                matches.append(pyeong_no)
    return matches


# ── 자치구 단위 후보 수집 ───────────────────────────────────────────────────

def _collect_candidates_for_district(district_name: str, cortar_no: str) -> list[dict]:
    candidates: list[dict] = []

    logger.info("[%s] 동 목록 조회...", district_name)
    dongs = api.list_regions(cortar_no)
    logger.info("[%s] 동 %d개", district_name, len(dongs))

    for dong in dongs:
        dong_code = dong.get("cortarNo", "")
        if not dong_code:
            continue

        complexes = api.list_complexes_in_dong(dong_code)
        api.pace()

        for cx in complexes:
            cx_no = str(cx.get("complexNo", ""))
            cx_name = cx.get("complexName", "")
            # 목록에서 세대수 1차 필터 (상세 조회 전 빠른 컷)
            quick_households = int(cx.get("totalHouseholdCount") or 0)
            if quick_households > 0 and quick_households < MIN_HOUSEHOLD_COUNT:
                continue

            detail = api.get_complex_detail(cx_no)
            api.pace()
            if not detail:
                continue

            # complexDetail 중첩 구조에서 세대수 확인
            cd = detail.get("complexDetail") or {}
            households = int(cd.get("totalHouseholdCount") or quick_households)
            if households < MIN_HOUSEHOLD_COUNT:
                continue

            pyeong_nos = _find_59_pyeongs(detail)
            if not pyeong_nos:
                continue

            # 콜론 구분 다중 pyeongNo (예: '1:2:3') — Naver areaNos 다중 지원 형식
            area_no_combined = ":".join(pyeong_nos)

            candidates.append({
                "complex_no": cx_no,
                "complex_name": cx_name,
                "district": district_name,
                "household_cnt": households,
                "trade_volume": None,
                "pyeong_no": area_no_combined,
                "area_no_59": area_no_combined,
            })
            logger.debug("  후보: %s (%s) %d세대 [pyeongs=%s]",
                         cx_name, district_name, households, area_no_combined)

    logger.info("[%s] 후보 %d개", district_name, len(candidates))
    return candidates


# ── 메인 선정 ──────────────────────────────────────────────────────────────

def run_selection(save_to_db: bool = True) -> list[dict]:
    """8개 자치구 전체를 순회해 Top 100 단지(세대수 순)를 선정하고 DB upsert.

    Returns:
        선정된 단지 목록 (rank 포함).
    """
    api.ensure_auth()

    all_candidates: list[dict] = []
    for district_name, cortar_no in DISTRICTS.items():
        try:
            cands = _collect_candidates_for_district(district_name, cortar_no)
            all_candidates.extend(cands)
        except Exception as e:
            logger.exception("[%s] 수집 오류: %s", district_name, e)

    if not all_candidates:
        logger.error("후보 단지 0개 — 선정 실패")
        return []

    # complexNo 중복 제거
    seen: set[str] = set()
    unique: list[dict] = []
    for c in all_candidates:
        if c["complex_no"] not in seen:
            seen.add(c["complex_no"])
            unique.append(c)

    # 세대수 내림차순 → Top 100
    unique.sort(key=lambda x: x["household_cnt"], reverse=True)
    selected = unique[:TOP_N_COMPLEXES]
    for rank, c in enumerate(selected, start=1):
        c["rank"] = rank

    logger.info(
        "Top %d 선정 완료 (전체 후보 %d개, 세대수 %d~%d)",
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
    """스케줄러 호출용."""
    logger.info("=== 단지 풀 갱신 ===")
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
    print(f"{'순위':>4}  {'단지명':<22}  {'구':>6}  {'세대':>6}  areaNos")
    print("-" * 60)
    for c in selected[:20]:
        print(
            f"{c['rank']:>4}  {c['complex_name']:<22}  {c['district']:>6}  "
            f"{c['household_cnt']:>6}  {c['area_no_59']}"
        )
    if len(selected) > 20:
        print(f"  ... 외 {len(selected) - 20}개")
    api.close_browser()
