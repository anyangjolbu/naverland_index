"""새 naver_api.get_min_price() 동작 검증 + 단지별 가격 비교."""
from __future__ import annotations

import logging
import sqlite3
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

import naver_api as api
from config import DB_PATH


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT complex_no, complex_name, district, area_no_59 FROM complexes ORDER BY rank LIMIT 5"
    ).fetchall()
    conn.close()

    print("=== 새 get_min_price 동작 검증 ===\n")
    api.ensure_auth()
    try:
        for r in rows:
            cx_no = r["complex_no"]
            old_area = r["area_no_59"]
            print(f"단지: {r['complex_name']} ({r['district']}) [{cx_no}]")
            print(f"  기존 area_no_59: {old_area!r}")

            # 1) 기존 single pyeongNo 로 조회
            min_old, cnt_old = api.get_min_price(cx_no, old_area)
            print(f"  → list_articles(order=prc) min: "
                  f"{api.price_to_eok(min_old) if min_old else 'N/A'}억 ({cnt_old}건)")

            # 2) 모든 59㎡ pyeongNo 발견 (다중)
            detail = api.get_complex_detail(cx_no)
            if detail:
                pyeongs = []
                for p in detail.get("complexPyeongDetailList", []):
                    try:
                        ea = float(p.get("exclusiveArea") or 0)
                    except Exception:
                        continue
                    if 56 <= ea <= 62:
                        pn = str(p.get("pyeongNo") or "")
                        if pn:
                            pyeongs.append((pn, ea, p.get("articleStatistics", {}).get("dealPriceMin")))
                print(f"  발견된 59㎡ pyeongs: {pyeongs}")

                if pyeongs:
                    multi_areas = ":".join(p[0] for p in pyeongs)
                    if multi_areas != old_area:
                        min_multi, cnt_multi = api.get_min_price(cx_no, multi_areas)
                        print(f"  → 다중 areas={multi_areas} min: "
                              f"{api.price_to_eok(min_multi) if min_multi else 'N/A'}억 ({cnt_multi}건)")
            print()
            api.pace()
    finally:
        api.close_browser()


if __name__ == "__main__":
    main()
