"""Naver complex_no ↔ Richgo danjiId 매핑 빌더 (1회성, 로컬 실행).

방식: Richgo 의 통합 검색 endpoint 를 단지명 그대로 호출 → 동일 자치구의
첫 결과를 매핑.

  GET https://api-m.richgo.ai/api/data/search?s=<name>&danji=true&limit=10
  → result.apartList[*].danjiId, .danji, .bjdInfo.sgg

이전엔 sgg+emd opengoods 를 snowball 로 1042개 풀을 만든 뒤 fuzzy 매칭
했는데, search API 가 직접 키워드 매칭을 해주므로 더 단순/정확하고
**현재 매물 0건 단지도 발견** (snowball 은 opengoods 라 매물 있는 것만 잡힘).

100 단지 = ~30초 (0.3s pacing).
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests


COMPLEXES_JSON = Path("data/complexes.json")
MAPPING_OUT = Path("richgo_mapping.json")

API_BASE = "https://api-m.richgo.ai"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
PACING_SEC = 0.3


def search(session: requests.Session, keyword: str) -> list[dict]:
    qs = urllib.parse.urlencode({"s": keyword, "danji": "true", "limit": "10"})
    r = session.get(f"{API_BASE}/api/data/search?{qs}", timeout=15)
    if r.status_code != 200:
        return []
    payload = r.json() or {}
    result = payload.get("result") or {}
    return result.get("apartList") or []


def pick(naver_district: str, candidates: list[dict]) -> dict | None:
    """동일 자치구 후보 우선; 없으면 첫 결과 (이름이 정확 매칭이면 안전)."""
    same_sgg = [c for c in candidates
                if (c.get("bjdInfo") or {}).get("sgg") == naver_district]
    if same_sgg:
        return same_sgg[0]
    return candidates[0] if candidates else None


def main() -> int:
    if not COMPLEXES_JSON.exists():
        print(f"ERROR: {COMPLEXES_JSON} 없음", file=sys.stderr)
        return 1

    with COMPLEXES_JSON.open(encoding="utf-8") as f:
        naver_complexes = json.load(f)
    print(f"Naver 단지 {len(naver_complexes)}개 로드")

    session = requests.Session()
    session.headers.update(HEADERS)

    mapping: dict[str, dict] = {}
    unmatched: list[dict] = []
    other_district: list[dict] = []  # 검색됐지만 자치구 다른 케이스 (수동 검토)

    def strip_parens(s: str) -> str:
        return re.sub(r"\([^)]*\)", "", s).strip()

    def try_search(keyword: str, district: str) -> dict | None:
        """검색 + 동일 자치구 후보만 채택 (mismatch 면 None 반환)."""
        cands = search(session, keyword)
        time.sleep(PACING_SEC)
        same = [c for c in cands if (c.get("bjdInfo") or {}).get("sgg") == district]
        return same[0] if same else None

    for nc in naver_complexes:
        name = nc["complex_name"]
        district = nc["district"]

        # 1) 원본 이름 + 동일 자치구
        chosen = try_search(name, district)

        # 2) 괄호 제거 (예: "디에이치아너힐즈S-클래스(주상복)" → "디에이치아너힐즈S-클래스")
        if not chosen:
            stripped = strip_parens(name)
            if stripped and stripped != name:
                chosen = try_search(stripped, district)

        # 3) "자치구명 + 단지명" 으로 재검색 (예: "서초구 우성")
        if not chosen:
            chosen = try_search(f"{district} {name}", district)

        # 4) 자치구 명시 + 괄호 제거
        if not chosen:
            stripped = strip_parens(name)
            if stripped and stripped != name:
                chosen = try_search(f"{district} {stripped}", district)

        if chosen is None:
            unmatched.append(nc)
            print(f"  [NG] [{district}] {name}")
        else:
            mapping[nc["complex_no"]] = {
                "danjiId": chosen["danjiId"],
                "richgo_name": chosen["danji"],
                "match_type": "search-api",
                "score": 1.0,
            }
            print(f"  [OK] [{district}] {name} -> {chosen['danji']} ({chosen['danjiId']})")

    print(f"\n매칭 {len(mapping)}/{len(naver_complexes)}, 미매칭 {len(unmatched)}")
    if other_district:
        print(f"\n자치구 mismatch (수동 검토 권장) {len(other_district)}건:")
        for o in other_district:
            print(f"  - {o['complex_name']}: naver={o['naver_district']} vs richgo={o['richgo_district']}")
    if unmatched:
        print(f"\n검색 실패 {len(unmatched)}건:")
        for u in unmatched:
            print(f"  - rank={u.get('rank')} [{u['district']}] {u['complex_name']} ({u['complex_no']})")

    out = {
        "mapping": mapping,
        "unmatched": [
            {"complex_no": u["complex_no"], "complex_name": u["complex_name"],
             "district": u["district"], "rank": u.get("rank")}
            for u in unmatched
        ],
    }
    MAPPING_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {MAPPING_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
