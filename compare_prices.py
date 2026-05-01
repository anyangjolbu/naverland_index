"""마이그레이션 전후 가격 비교 — 다중 pyeong 지원으로 얼마나 정확해졌는지."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from config import DB_PATH


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 마이그레이션 전 마지막 (2026-04-30 01:00) vs 새 수집 (2026-04-30 21:00 등)
    rows = conn.execute(
        """
        WITH old_p AS (
            SELECT complex_no, min_price
              FROM hourly_prices
             WHERE collected_at = '2026-04-30 01:00:00'
        ),
        new_p AS (
            SELECT complex_no, min_price
              FROM hourly_prices
             WHERE collected_at = (SELECT MAX(collected_at) FROM hourly_prices)
        )
        SELECT c.complex_no, c.complex_name, c.district, c.area_no_59,
               o.min_price AS old_p, n.min_price AS new_p
          FROM complexes c
          LEFT JOIN old_p o ON o.complex_no = c.complex_no
          LEFT JOIN new_p n ON n.complex_no = c.complex_no
         WHERE o.min_price IS NOT NULL AND n.min_price IS NOT NULL
         ORDER BY (o.min_price - n.min_price) DESC
        """
    ).fetchall()
    conn.close()

    if not rows:
        print("비교할 데이터 없음")
        return

    diffs = []
    for r in rows:
        old_eok = r["old_p"] / 10000
        new_eok = r["new_p"] / 10000
        delta = old_eok - new_eok
        diffs.append((delta, dict(r), old_eok, new_eok))

    print(f"\n=== 비교 대상: {len(diffs)} 단지 ===\n")
    print("** 새 수집이 기존보다 더 낮은 호가를 잡은 (다중 pyeong 효과) Top 20 **")
    print(f"{'단지명':<26s}  {'구':>6s}  {'평형':>16s}  {'기존':>7s}  {'신규':>7s}  {'차이':>7s}")
    print("-" * 100)
    for delta, r, old_eok, new_eok in diffs[:20]:
        if delta <= 0:
            break
        print(f"{r['complex_name']:<26s}  {r['district']:>6s}  "
              f"{r['area_no_59']:>16s}  "
              f"{old_eok:>6.2f}억  {new_eok:>6.2f}억  -{delta:>6.2f}억")

    # 통계
    lower_count = sum(1 for d, _, _, _ in diffs if d > 0)
    same_count  = sum(1 for d, _, _, _ in diffs if d == 0)
    higher_count = sum(1 for d, _, _, _ in diffs if d < 0)
    avg_drop = sum(d for d, _, _, _ in diffs if d > 0) / lower_count if lower_count else 0

    print()
    print(f"  더 낮게 잡힘 (이전이 틀림):  {lower_count} 단지 (평균 -{avg_drop:.2f}억)")
    print(f"  동일:                          {same_count} 단지")
    print(f"  더 높게 잡힘 (시세 자체 상승): {higher_count} 단지")


if __name__ == "__main__":
    main()
