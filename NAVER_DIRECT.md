# Naver Land 직접 크롤링 노트

이 프로젝트는 현재 [Richgo API](README.md#데이터-소스) 를 데이터 소스로 사용하지만,
원래 Naver Land (`new.land.naver.com`) 를 직접 크롤링했었다. Naver 가 클라우드 IP 를
**silent drop** 으로 차단해서 Railway 같은 호스팅 환경에선 못 쓰지만, **본인 집 IP
(주거용 회선) 에선 그대로 작동**한다.

이 문서는 그 직접 크롤링 기법을 미래 재사용 (로컬 분석 / 백업 수집기 / 다른 평형 확장 등)
용으로 보존한다.

> ⚠️ Railway, Render, Fly.io 등 모든 클라우드 IP 에선 **TCP 연결은 잡히지만 TLS read 가
> silent timeout** 으로 막힘. 헤더/UA/토큰/path 어떤 트릭도 무용. 자세한 진단 결과는
> [HISTORY.md 의 2026-05-02 항목](HISTORY.md#2026-05-02--naver--richgo-데이터-소스-전환-naver-ip-차단-우회) 참조.

## 1. API 엔드포인트

베이스: `https://new.land.naver.com`

| Endpoint | 용도 |
|---|---|
| `GET /api/regions/list?cortarNo={code}` | 시/도 → 구 → 동 계층 (cortarNo 10자리) |
| `GET /api/regions/complexes?cortarNo={dongCode}&realEstateType=APT` | 동 단위 단지 목록 |
| `GET /api/complexes/{complexNo}?sameAddressGroup=false` | 단지 상세 (totalHouseHoldCount, complexPyeongDetailList) |
| `GET /api/complexes/overview/{complexNo}` | 단지 overview (실거래가 포함) |
| `GET /api/articles/complex/{complexNo}?realEstateType=APT&tradeType=A1&areaNos={areaNo}&page={n}&order=prc` | **매매(A1) 매물 리스트** |

### 자치구 cortarNo (서울 핵심 8개)
config.py 의 DISTRICTS 와 동일 (10자리, sggBjdCode 와 호환):

| 자치구 | cortarNo |
|---|---|
| 강남구 | 1168000000 |
| 서초구 | 1165000000 |
| 용산구 | 1117000000 |
| 송파구 | 1171000000 |
| 마포구 | 1144000000 |
| 성동구 | 1120000000 |
| 동작구 | 1159000000 |
| 강동구 | 1174000000 |

## 2. 인증 — Bearer 토큰

`/api/*` 호출은 **Authorization: Bearer <JWT>** 가 필요. 토큰 payload:
```json
{"id":"REALESTATE","iat":..., "exp":...}
```
**유효기간 ≈ 3시간**. 정적 환경변수로 박을 수 없음. 페이지 세션에서 동적으로 받아야 함.

### 토큰 획득 방법 (3가지)

1. **수동 1회 (실험/디버깅)**: 크롬 → https://new.land.naver.com/complexes → F12 Network → 아무 `/api/` 요청 → Headers → Authorization → "Bearer " 뒤 문자열 복사
2. **Playwright 자동 캡처 (운영)**: 페이지 로드 중 outgoing request 의 Authorization 헤더를 인터셉트
3. **HTML 폴백**: `<script>` 태그 안의 `"token":"eyJ..."` 정규식 추출

## 3. Playwright 셋업 (anti-detection)

```python
from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
browser = pw.chromium.launch(
    headless=True,
    args=[
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
    ],
)
context = browser.new_context(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    viewport={"width": 1366, "height": 768},
    locale="ko-KR",
    timezone_id="Asia/Seoul",
)
context.add_init_script(
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});"
)
page = context.new_page()

# Bearer 토큰 인터셉트
captured_token = ""
def on_request(req):
    nonlocal captured_token
    if "new.land.naver.com/api/" in req.url and not captured_token:
        auth = req.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            captured_token = auth.split(" ", 1)[1]
page.on("request", on_request)

page.goto("https://new.land.naver.com/complexes",
          wait_until="networkidle", timeout=30_000)
page.wait_for_timeout(2_000)

# 페이지가 자체적으로 호출 안 했으면 HTML 에서 추출
if not captured_token:
    captured_token = page.evaluate("""
        () => {
            const m = document.body.innerHTML.match(/"token"\\s*:\\s*"(eyJ[^"]+)"/);
            return m ? m[1] : '';
        }
    """) or ""
```

## 4. 페이지 내 fetch 로 API 호출

직접 `requests.get(...)` 하면 봇 탐지에 걸리기 쉬움. **브라우저 컨텍스트 안에서
`page.evaluate(fetch(...))`** 하면 same-origin + cookie + referer 자동 처리됨:

```python
result = page.evaluate("""
    async ([url, token]) => {
        const headers = {'Accept': 'application/json'};
        if (token) headers['Authorization'] = 'Bearer ' + token;
        const r = await fetch(url, {credentials: 'include', headers});
        return {status: r.status, body: await r.text()};
    }
""", [url, captured_token])

if result["status"] == 200:
    data = json.loads(result["body"])
elif result["status"] == 429:
    # Exponential backoff: 5s → 10s → 20s → 40s
    pass
```

## 5. ⚠️ 자주 빠지는 함정 (2026-04-30 해결)

### 5.1 다중 평형 (subtype) 누락
한 단지에 59A / 59B / 59C 등 여러 59㎡ 평형이 있으면 첫 pyeongNo 만 보면 다른 subtype 의
더 낮은 호가는 영원히 못 봄. **모든 56~62㎡ pyeongNo 를 콜론 구분으로 합쳐 호출.**

```python
def find_59_pyeongs(complex_detail):
    pyeong_list = complex_detail.get("complexPyeongDetailList") or []
    matches = []
    for p in pyeong_list:
        try:
            area = float(p.get("exclusiveArea") or 0)
        except (ValueError, TypeError):
            continue
        if 56 <= area <= 62:
            pno = str(p.get("pyeongNo", "") or "")
            if pno and pno not in matches:
                matches.append(pno)
    return ":".join(matches)   # 예: "3:4:2"

# 호출
articles = fetch(f"/api/articles/complex/{cx_no}", {
    "realEstateType": "APT",
    "tradeType": "A1",
    "areaNos": "3:4:2",   # 콜론 다중 지원!
    "page": 1,
    "order": "prc",
})
```

검증: 헬리오시티 [22675] — pyeongNo=3 만 보면 26.5억, "3:4:2" 보면 25.25억 (1.25억 차이).

### 5.2 정렬 안 하면 page=1 에 최저가 누락
`/api/articles/complex/...` 무정렬 호출 시 페이지 1 은 랭킹/최신 순이라 최저가가 page 2~9
에 묻힘. **반드시 `order=prc`** (가격 오름차순) — page=1 에 보장된 최저가 20건.

### 5.3 `articleStatistics.dealPriceMin` 은 stale cache
`/api/complexes/{no}` 의 `articleStatistics.dealPriceMin` 은 집계 캐시라 실제 매물 리스트와
괴리 발생. **반드시 `list_articles` 직접 호출** 후 그 매물의 가격을 사용 (Naver 사이트가
사용자에게 보여주는 데이터와 일치).

### 5.4 Playwright 싱글턴 + threading 충돌
APScheduler / Flask 의 다른 스레드에서 같은 브라우저 객체 사용 시:
```
greenlet.error: cannot switch to a different thread
```
**`threading.local()` 로 스레드별 브라우저 인스턴스 관리.** 각 수집 사이클이 자체
브라우저를 launch / close 하도록.

```python
import threading
_local = threading.local()

def get_browser():
    if not hasattr(_local, 'state'):
        _local.state = launch_browser()  # 스레드 첫 호출 시
    return _local.state
```

## 6. Pacing / 백오프

- 단지당 호출 간격: **1.5초** sleep
- 429 응답 시 exponential backoff: **5s → 10s → 20s → 40s** (4회 retry)
- 단지 100개 풀 수집 ≈ 3~5 분
- 단지 풀 갱신 (8 자치구 × 동 × 단지 트래버스) ≈ 30~60 분

## 7. 가격 파싱

Naver 호가 문자열 → 만원 정수:
```python
import re
_RE_NUM = re.compile(r"\d[\d,]*")

def parse_price(text: str) -> int | None:
    """
    "18억 5,000"  → 185000
    "9억"         →  90000
    "5,500"       →   5500
    "15억5000"    → 155000
    """
    if not text:
        return None
    s = str(text).strip()
    eok_part, man_part = 0, 0
    if "억" in s:
        before, _, after = s.partition("억")
        m = _RE_NUM.search(before)
        if m:
            eok_part = int(m.group().replace(",", ""))
        m = _RE_NUM.search(after)
        if m:
            man_part = int(m.group().replace(",", ""))
    else:
        m = _RE_NUM.search(s)
        if m:
            man_part = int(m.group().replace(",", ""))
    return eok_part * 10_000 + man_part
```

## 8. 단지 선정 알고리즘 (Top 100 by 세대수)

```python
candidates = []
for district_name, sgg in DISTRICTS.items():
    dongs = list_regions(sgg)                        # /api/regions/list
    for dong in dongs:
        complexes = list_complexes_in_dong(dong['cortarNo'])  # /api/regions/complexes
        for cx in complexes:
            quick_households = int(cx.get('totalHouseholdCount') or 0)
            if 0 < quick_households < 500:           # 빠른 컷
                continue
            detail = get_complex_detail(cx['complexNo'])      # /api/complexes/{no}
            cd = detail.get('complexDetail') or {}
            households = int(cd.get('totalHouseholdCount') or quick_households)
            if households < 500:
                continue
            pyeong_nos = find_59_pyeongs(detail)     # 5.1 참조
            if not pyeong_nos:
                continue
            candidates.append({
                'complex_no': cx['complexNo'],
                'complex_name': cx['complexName'],
                'district': district_name,
                'household_cnt': households,
                'area_no_59': pyeong_nos,             # "3:4:2" 형식
            })

# 중복 제거 + 세대수 내림차순 + Top 100
seen = set()
unique = [c for c in candidates if c['complex_no'] not in seen and not seen.add(c['complex_no'])]
unique.sort(key=lambda x: x['household_cnt'], reverse=True)
top100 = unique[:100]
```

## 9. 가격 수집 (단지별)

```python
def get_min_price(complex_no, area_no):
    """
    Returns: (min_price_manwon, article_count)
    매물 0건이면 (None, 0).
    """
    arts = list_articles(complex_no, area_no, page=1, order='prc')
    if not arts:
        return None, 0
    prices = []
    for a in arts:
        # 매매(A1) 한번 더 필터
        ttype = (a.get('tradeTypeName') or '').strip()
        if ttype and '매매' not in ttype:
            continue
        parsed = parse_price(a.get('dealOrWarrantPrc') or '')
        if parsed is not None:
            prices.append(parsed)
    return (min(prices) if prices else None), len(arts)
```

## 10. 언제 다시 쓸까

- **로컬 분석**: 클라우드 차단 무관, 정확한 호가 필요할 때
- **canonical 100 단지 갱신**: 분기/년 1회 정도 새 단지 편입/이탈 반영 → 결과를
  `complexes.json` 으로 export 후 repo commit (build_mapping.py 재실행으로 mapping 갱신)
- **Richgo API 변경 / 폐쇄 시 백업**: 집 PC + Cloudflare Tunnel 로 Naver 직접 크롤러를
  외부 노출 → Railway 가 호출하는 구조 (월 0원, 단 PC 항상 가동 필요)
- **다른 평형 / 다른 자치구 확장**: 84㎡, 114㎡ 인덱스 추가, 25개 자치구 전체 등

## 11. 참고 — 코드 위치 (git history)

이 모듈들은 현재 repo 에서 삭제됐지만 git log 에서 복구 가능:
```bash
git log --all --oneline -- naver_api.py
git show <commit>:naver_api.py > naver_api.py
```

원본 (Richgo 전환 직전 마지막 커밋): `8ac93f5` — "Initial commit: Flask app + APScheduler + Railway deploy config"
