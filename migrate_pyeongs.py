"""기존 complexes 테이블의 area_no_59 를 다중 pyeongNo 콜론 구분 형식으로 업데이트.

전체 selector 재실행 없이 빠르게 마이그레이션.
"""
from __future__ import annotations

import logging
import sqlite3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

import naver_api as api
from complex_selector import _find_59_pyeongs
from config import DB_PATH


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT complex_no, complex_name, district, area_no_59 FROM complexes ORDER BY rank"
    ).fetchall()
    conn.close()

    api.ensure_auth()

    updates: list[tuple[str, str]] = []
    try:
        for i, r in enumerate(rows, 1):
            cx_no = r["complex_no"]
            old_area = r["area_no_59"] or ""
            detail = api.get_complex_detail(cx_no)
            if not detail:
                logger.warning("[%d/%d] %s: detail 없음", i, len(rows), r["complex_name"])
                api.pace()
                continue
            pyeongs = _find_59_pyeongs(detail)
            new_area = ":".join(pyeongs) if pyeongs else old_area
            mark = "(unchanged)" if new_area == old_area else f"<<< CHANGED from {old_area!r}"
            logger.info("[%d/%d] %s (%s): area_no_59=%r %s",
                        i, len(rows), r["complex_name"], r["district"], new_area, mark)
            updates.append((new_area, cx_no))
            api.pace()
    finally:
        api.close_browser()

    # 일괄 update
    conn = sqlite3.connect(str(DB_PATH))
    conn.executemany(
        "UPDATE complexes SET area_no_59 = ?, pyeong_no = ? WHERE complex_no = ?",
        [(area, area, cx_no) for area, cx_no in updates],
    )
    conn.commit()
    conn.close()
    logger.info("=== %d개 단지 area_no_59 업데이트 완료 ===", len(updates))

    # 요약: 변경된 단지만 출력
    print("\n=== 변경 요약 ===")
    changed = 0
    for r, (new_area, _) in zip(rows, updates):
        old = r["area_no_59"] or ""
        if old != new_area:
            print(f"  {r['complex_name']:<28s} {old!r:>10s} → {new_area!r}")
            changed += 1
    print(f"\n총 {changed}/{len(updates)} 단지 변경됨")


if __name__ == "__main__":
    main()
