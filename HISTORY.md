# History

프로젝트 진행 기록. 새 항목은 **위쪽**에 추가 (역순).

기록 형식:
```
## YYYY-MM-DD — <짧은 제목>
- 무엇을 했는지 / 왜 했는지
- 산출물 / 다음 행동
```

---

## 2026-05-02 — Naver → Richgo 데이터 소스 전환 (Naver IP 차단 우회)

배포 후 처음 데이터 안 들어와서 원인 추적 → **Naver 가 클라우드 IP 의 부동산 도메인 접근을 silent drop** 함을 확인 → 우회 시도 → 모두 실패 → Richgo 로 이전.

### 진단 (`/api/debug/connectivity` 엔드포인트로 검증)
- DNS OK, www.naver.com / land.naver.com / search.naver.com / finance.naver.com OK (200)
- new.land.naver.com / m.land.naver.com / api.land.naver.com / land.naver.com/article/* → **silent timeout** (TCP 는 잡히지만 응답 0)
- 모바일 앱 UA, iPhone UA, Bearer 토큰 모두 무용 — 순수 IP 기반 차단
- 공개 CORS proxy (allorigins, corsproxy.io) → 그것들도 차단되거나 Cloudflare 1010 거부

### 우회 시도 (전부 실패)
- subdomain 변경, path 변경, header trickery, Bearer 토큰 (사용자 직접 추출 후 테스트) → 다 막힘
- 결론: Naver 부동산은 Railway 같은 DC IP 에서 어떤 방법으로도 직접 접근 불가

### Richgo 발견 (사용자 아이디어)
- richgo.ai 가 Naver 데이터 가공해서 서비스 중 — Railway 에서 도달 가능 (404 응답 = host live)
- Next.js SPA 분석 → API 호스트 `api-m.richgo.ai`, 인증 불필요
- 핵심 endpoint:
  - `GET /api/data/danji/price/opengoods?bjdCode=X&tradeType=Meme&...` — 행정구역별 매물
  - `GET /api/data/danji/onepage?danjiId=X` — 단지 종합 정보 (pyeongInfos 에 평형별 가격 다중 소스)

### 1차 구현 (단순 sgg-level)
- naver_api.py 삭제, richgo_api.py 신규
- complex_selector / price_collector 가 자치구 sgg opengoods 호출 → 24평 (=59㎡) 필터
- Dockerfile: Playwright 베이스 → python:3.11-slim (~1GB → ~150MB)
- 결과: 29개 단지만 잡힘 (sgg 응답이 ~50건으로 캡, 24평은 자치구당 5~7개)

### 2차 — canonical Naver 100 + Richgo 매핑 (사용자 지적)
사용자: "세대수는 불변, 100개 리스트 그대로 활용. 가격만 최신화. 어떻게든 100개 다 확보해라."

- 로컬 `data/complexes.json` (이전 Naver 크롤링으로 만든 Top 100, 진짜 세대수 보유) 를 repo 에 commit
- `build_mapping.py` 작성 — snowball (sgg → 발견된 emd → leaders) 로 1042개 unique danji 풀 형성 → fuzzy 매칭 (정규화 + substring + 자카드)
- 결과: 94/100 매핑 완료
- 6개 미매칭 (도곡렉슬, 강남자곡힐스테이트, 강남한양수자인, 서초더샵포레, 래미안원페를라, 서초힐스) — Richgo opengoods 풀에 안 잡힘 (현재 매물 0건 추정)
- DB 스키마: `complexes.richgo_danji_id TEXT` 컬럼 추가 + ALTER TABLE 마이그레이션
- complex_selector → 정적 부트스트랩으로 변경 (라이브 크롤링 X)

### 3차 — 가격 100% 커버리지 (per-danji onepage)
- 2차 구현은 sgg snowball 로 가격 수집 → 32/100 hit (opengoods 는 현재 매물 있는 단지만 노출)
- 전환: per-danji `/api/data/danji/onepage` 호출 → `pyeongInfos[24].danjiPriceInfo.memePriceDict` 에서 가격 추출
- 가격 우선순위: **OFFER.minPrice (호가)** → **RICHGO_SISE.price (시세)** → **KB.price**
- 호가 없는 단지도 시세로 fallback → 매핑된 94 단지 모두 가격 확보
- 결과: 가격 94/100 (6개는 매핑 자체가 없음), 평균 21.48억, 중위 19.56억, 수집 시간 ~25초

### 부수 처리
- legacy 잔재 정리: 1차 구현이 Richgo danjiId 를 complex_no 로 박았던 데이터 → 부트스트랩 시 자동 정리 (FK 순서 주의: hourly_prices 먼저 삭제 후 complexes 삭제)
- naver_api.py / compare_prices.py / migrate_pyeongs.py / test_new_api.py 삭제
- requirements.txt 에서 playwright 제거

### 최종
- **Live**: https://naverlandindex-production.up.railway.app/
- 100 단지 등록, 94 단지 가격 수집중
- 매시간 02분 자동 갱신, 매일 03:30 부트스트랩 + 갱신

---

## 2026-05-01 — Railway 배포 + Naver IP 차단 발견

- 사용자가 Railway Hobby ($5/월) 가입 + GitHub repo 연결
- Dockerfile (Playwright python 베이스), railway.toml (헬스체크), .gitignore 작성, 첫 commit + push
- Railway Volume 마운트 (`/app/data`) + 도메인 생성
- 첫 데이터 수집 시도: `/api/refresh` → "Failed to fetch" 에러 → 진단 → IP 차단 확인 (위 2026-05-02 항목으로 이어짐)

## 2026-05-01 — 새로고침하면 빈 화면 — CDN 의존 제거

- **증상**: 사용자가 웹 새로고침 시 헤더만 보이고 차트/표/단지 리스트 모두 비어 있음
- **원인 추적**: `logs/app.log` 06:36~37 분 액세스 패턴 분석
  - `GET /` → `style.css` → `chart.js` 까지는 정상 (200/304)
  - 이후 `/api/status` 만 1회 호출, `/api/hourly`·`/api/daily`·`/api/complexes`·`/api/district/hourly` 호출 0회
  - → `init()` 이 fetch 단계 도달 전에 throw
  - 가장 유력한 원인: `<script src="https://unpkg.com/lightweight-charts...">` CDN 차단
- **수정**:
  - `lightweight-charts.standalone.production.js` (160KB) 를 [static/js/](static/js/) 에 다운로드해 로컬 서빙
  - [templates/index.html](templates/index.html) 의 `<script>` 태그를 로컬 경로로 교체 + `#js-error` 배너 + `window.error` 핸들러 추가
  - [static/js/chart.js](static/js/chart.js) `init()` 을 `safe()` 래퍼로 감싸서 한 단계 실패가 나머지를 막지 않도록 함
  - [app.py](app.py) `TEMPLATES_AUTO_RELOAD=True` 추가

## 2026-04-30 — 가격 정확도 + 안정성 대수술

- **버그 1: 다중 59㎡ subtype 누락**
  - 한 단지에 59A/59B/59C 등 여러 평형이 있을 때 첫 번째 pyeongNo 만 저장 → 다른 subtype 의 더 낮은 호가는 영원히 못 봄
  - 검증: 헬리오시티 [22675] — pyeongNo=3 만 보면 26.5억, 3:4:2 다중 보면 25.25억 (1.25억 차이)
  - 수정: `_find_59_pyeongs()` 가 모든 56~62㎡ pyeongNo 를 콜론 구분으로 반환 (예: "3:4:2"). Naver `areaNos` 파라미터가 콜론 다중을 지원
- **버그 2: 정렬 안 함 → page=1에 최저가 누락**
  - 기존: `list_articles()` 무정렬 호출 → 페이지 1엔 랭킹/최신 순. 가장 싼 매물이 page 2~9 에 있을 수 있음
  - 수정: `order=prc` 파라미터 추가 (가격 오름차순). page=1에 보장된 최저가 20건
- **버그 3: `dealPriceMin` 캐시 stale**
  - `articleStatistics.dealPriceMin` 은 집계 캐시. Naver 웹사이트가 사용자에게 보여주는 매물 리스트와 분리됨
  - 수정: dealPriceMin 사용 중단, list_articles 직접 사용
- **버그 4: Playwright 싱글턴 + threading**
  - APScheduler / Flask `/api/run` 다른 스레드에서 같은 브라우저 객체 사용 시 `greenlet.error: cannot switch to a different thread`
  - 수정: `_local = threading.local()` — 스레드별 브라우저 인스턴스, 각 수집 사이클이 자체 브라우저 launch / close
- **스케줄 재구성**
  - 매시간 02분: 가격 수집만 (~3분)
  - 매일 03:30: 전체 갱신 (selector + 가격 + 지표)
- **CSV 저장**: `data/collections/{YYYY-MM-DD}.csv` 일자별 append
- **API 추가**: `POST /api/refresh` 수동 트리거

## 2026-04-29 — Phase 1~5 코어 구현 완료

- 전체 파이프라인 코드 완성 및 E2E 검증:
  - naver_api.py — Playwright 브라우저 세션 기반. 세션 쿠키 + Bearer 토큰 자동 캡처 → 429 우회 성공
  - complex_selector.py — 8개 자치구 순회, 1000세대↑ + 59㎡ 보유 필터, 세대수 Top 100 정렬
  - price_collector.py — 단지별 59㎡ 최저호가 수집
  - index_calculator.py — avg/median (억 단위), 시간봉 OHLC (IQR spread), 일봉 OHLC (KST 00:00 기준)
  - app.py — Flask + APScheduler (매시간 정각 KST), REST API 6개
  - 프론트엔드 — TradingView Lightweight Charts 봉차트 대시보드
- 검증된 동작:
  - Playwright 로 강남구 59㎡ 단지 최저호가 26.5억 수집 성공
  - DB hourly_prices → hourly_index → hourly_ohlc → daily_ohlc 전체 흐름 OK
  - Flask API 응답 OK
- **다음 행동**: `python complex_selector.py` 실행으로 실제 Top 100 단지 선정 (8개 구 전체 순회, 30~60분 소요)

## 2026-04-28 — 결정사항 반영 + Phase 1 착수

- 사용자 결정 4건 확정:
  1. Top 100 정렬 = **거래량 순** (이후 세대수로 fallback, Richgo 전환 후 매물수로 변경)
  2. 일봉 기준 = **KST 00:00 시작**
  3. 결측 단지 = **제외 처리**
  4. 단지 풀 갱신 = **1시간 주기**
- 추가 확정:
  - Index 단위 = 가격값 자체 (억), 1000 base 정규화 안 함
  - 데이터 무제한 보존
  - 시간봉/일봉만, 시간봉 OHLC spread는 단지간 IQR 기반
- README / ARCHITECTURE / ROADMAP 전면 업데이트

## 2026-04-28 — 프로젝트 셋업

- 빈 작업 폴더에 README / ARCHITECTURE / ROADMAP / HISTORY 생성
- 기술 스택 잠정 결정: Python + SQLite + plotly + APScheduler (이후 Lightweight Charts 로 변경)
- **다음 행동**: Phase 0 사전 조사 — 네이버부동산 API 엔드포인트와 응답 스키마 확인
