"""Naver complex_no ↔ Richgo danjiId 매핑 빌더 (1회성, 로컬 실행).

전략:
  1. sgg-level opengoods 호출 → 첫 단지 풀 + emd 코드 수집
  2. emd-level opengoods 추가 호출 → 단지 풀 확장 (snowball)
  3. complexes.json 의 (district, complex_name) 와 fuzzy 매칭
  4. richgo_mapping.json 로 저장

매칭 우선순위:
  - 정규화 후 정확 일치
  - 정규화 후 substring (긴 쪽이 짧은 쪽 포함)
  - 정규화 후 토큰 기반 자카드 유사도 (≥0.5)
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import richgo_api as rg
from config import DISTRICTS


COMPLEXES_JSON = Path("data/complexes.json")
MAPPING_OUT = Path("richgo_mapping.json")


def normalize(s: str) -> str:
    """단지명 정규화 — 괄호 내용 제거 + 한글/영숫자 외 제거 + 소문자."""
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^가-힣a-zA-Z0-9]", "", s)
    return s.lower()


def jaccard(a: str, b: str) -> float:
    """문자 단위 자카드 (한글 단지명에 효과적)."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def collect_richgo_pool() -> dict[str, list[dict]]:
    """자치구별 모든 가능한 단지 + 평형 row 모음 (snowball: sgg → emd)."""
    pool_by_district: dict[str, dict[str, dict]] = defaultdict(dict)

    for district, sgg_code in DISTRICTS.items():
        # 1) sgg-level
        rows = rg.list_opengoods_by_sgg(sgg_code, limit=200)
        rg.pace()
        emd_codes: set[str] = set()
        for r in rows:
            danji_id = r.get("danjiId")
            if danji_id:
                pool_by_district[district][danji_id] = r
            emd = r.get("danjiBjdCode")
            if emd and emd != sgg_code:
                emd_codes.add(emd)
        print(f"  [{district}] sgg → {len(rows)} rows, {len(emd_codes)} emd codes 발견")

        # 2) emd-level (snowball)
        for emd in emd_codes:
            rows = rg.list_opengoods_by_sgg(emd, limit=200)
            rg.pace()
            for r in rows:
                danji_id = r.get("danjiId")
                if danji_id and danji_id not in pool_by_district[district]:
                    pool_by_district[district][danji_id] = r

        # 3) leader-only 추가 (다른 set 일 가능성)
        rows = rg.list_opengoods_by_sgg(sgg_code, limit=200, only_leaders=True)
        rg.pace()
        for r in rows:
            danji_id = r.get("danjiId")
            if danji_id and danji_id not in pool_by_district[district]:
                pool_by_district[district][danji_id] = r

        print(f"  [{district}] 최종 pool: {len(pool_by_district[district])} unique danji")

    return {d: list(v.values()) for d, v in pool_by_district.items()}


def match_one(naver_name: str, candidates: list[dict]) -> tuple[dict | None, str, float]:
    """후보 중 하나를 매칭. (best_row, match_type, score)."""
    n_norm = normalize(naver_name)
    if not n_norm:
        return None, "empty", 0.0

    # 1. exact normalized
    for c in candidates:
        if normalize(c.get("danji", "")) == n_norm:
            return c, "exact", 1.0

    # 2. substring (양방향)
    sub_matches = []
    for c in candidates:
        rn = normalize(c.get("danji", ""))
        if not rn:
            continue
        if n_norm in rn or rn in n_norm:
            # 길이 가까울수록 좋음
            score = min(len(n_norm), len(rn)) / max(len(n_norm), len(rn))
            sub_matches.append((c, score))
    if sub_matches:
        sub_matches.sort(key=lambda x: -x[1])
        return sub_matches[0][0], "substring", sub_matches[0][1]

    # 3. Jaccard 유사도 (≥0.5)
    jac_matches = [(c, jaccard(n_norm, normalize(c.get("danji", "")))) for c in candidates]
    jac_matches = [(c, s) for c, s in jac_matches if s >= 0.5]
    if jac_matches:
        jac_matches.sort(key=lambda x: -x[1])
        return jac_matches[0][0], "jaccard", jac_matches[0][1]

    return None, "none", 0.0


def main() -> int:
    if not COMPLEXES_JSON.exists():
        print(f"ERROR: {COMPLEXES_JSON} 없음", file=sys.stderr)
        return 1

    with COMPLEXES_JSON.open(encoding="utf-8") as f:
        naver_complexes = json.load(f)
    print(f"Naver 단지 {len(naver_complexes)}개 로드")

    print("\n=== Richgo 단지 풀 수집 (snowball) ===")
    pool = collect_richgo_pool()
    total_pool = sum(len(v) for v in pool.values())
    print(f"\n총 Richgo 풀: {total_pool} unique danji")

    print("\n=== 매칭 ===")
    mapping: dict[str, dict] = {}
    unmatched: list[dict] = []

    for nc in naver_complexes:
        district = nc["district"]
        candidates = pool.get(district, [])
        best, mtype, score = match_one(nc["complex_name"], candidates)
        if best:
            mapping[nc["complex_no"]] = {
                "danjiId": best["danjiId"],
                "richgo_name": best.get("danji", ""),
                "match_type": mtype,
                "score": round(score, 3),
            }
            tag = "[OK]" if mtype == "exact" else f"[~{mtype} {score:.2f}]"
            print(f"  {tag} [{district}] {nc['complex_name']} -> {best.get('danji')}")
        else:
            unmatched.append(nc)
            print(f"  [NG] [{district}] {nc['complex_name']} (rank={nc.get('rank')})")

    print(f"\n매칭: {len(mapping)}/{len(naver_complexes)}")
    print(f"미매칭: {len(unmatched)}")
    if unmatched:
        print("\n미매칭 단지 (수동 확인 필요):")
        for nc in unmatched:
            print(f"  - rank={nc.get('rank')} [{nc['district']}] {nc['complex_name']} ({nc['complex_no']})")

    out = {
        "mapping": mapping,
        "unmatched": [
            {"complex_no": nc["complex_no"], "complex_name": nc["complex_name"],
             "district": nc["district"], "rank": nc.get("rank")}
            for nc in unmatched
        ],
    }
    MAPPING_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {MAPPING_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
