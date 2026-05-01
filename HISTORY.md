# History

프로젝트 진행 기록. 새 항목은 **위쪽**에 추가 (역순).

기록 형식:
```
## YYYY-MM-DD — <짧은 제목>
- 무엇을 했는지 / 왜 했는지
- 산출물 / 다음 행동
```

---

## 2026-05-01 — 새로고침하면 빈 화면 — CDN 의존 제거

- **증상**: 사용자가 웹 새로고침 시 헤더만 보이고 차트/표/단지 리스트 모두 비어 있음
- **원인 추적**: `logs/app.log` 06:36~37 분 액세스 패턴 분석
  - `GET /` → `style.css` → `chart.js` 까지는 정상 (200/304)
  - 이후 `/api/status` 만 1회 호출, `/api/hourly`·`/api/daily`·`/api/complexes`·`/api/district/hourly` 호출 0회
  - → `init()` 이 fetch 단계 도달 전에 throw
  - 가장 유력한 원인: `<script src="https://unpkg.com/lightweight-charts...">` CDN 차단 (방화벽/광고차단/오프라인) → `LightweightCharts` undefined → `initChart()` 의 `LightweightCharts.createChart()` 가 즉시 throw
- **수정**:
  - `lightweight-charts.standalone.production.js` (160KB) 를 [static/js/](static/js/) 에 다운로드해 로컬 서빙. CDN 의존 제거
  - [templates/index.html](templates/index.html) 의 `<script>` 태그를 로컬 경로로 교체 + `#js-error` 배너 + `window.error` 핸들러 추가 (앞으로 JS 오류는 화면 상단에 빨간 배너로 표시됨)
  - [static/js/chart.js](static/js/chart.js) `init()` 을 `safe()` 래퍼로 감싸서 한 단계 실패가 나머지를 막지 않도록 함. `LightweightCharts` 미로드 시 명시적 에러 메시지
  - [app.py](app.py) `TEMPLATES_AUTO_RELOAD=True` 추가 — 앞으로 템플릿 수정 시 Flask 재시작 불필요
- **사용자 액션**: **Flask 앱 재시작 필요** (현재 실행 중인 프로세스가 구 템플릿을 캐시 중 — Jinja2 env 가 `auto_reload=False` 로 부팅되었음). 재시작 후 새로고침하면 정상 표시되어야 함
- **다음 행동**: 재시작 후에도 빈 화면이면 브라우저 콘솔의 `#js-error` 배너 메시지를 확인 (이제 무엇이 실패했는지 보임)

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
  - 수정: dealPriceMin 사용 중단, list_articles 직접 사용 (사용자가 보는 데이터와 일치)
- **버그 4: Playwright 싱글턴 + threading**
  - APScheduler / Flask `/api/run` 다른 스레드에서 같은 브라우저 객체 사용 시 `greenlet.error: cannot switch to a different thread`
  - 02:00 첫 실패 후 `is_running=True` 영구 잠김 → 03:00~06:00 모든 정시 수집 스킵
  - 수정:
    - `_local = threading.local()` — 스레드별 브라우저 인스턴스
    - 각 수집 사이클이 자체 브라우저를 launch / close
    - `_acquire_run/_release_run` 헬퍼로 lock 누락 방지
- **스케줄 재구성**
  - 매시간 02분: 가격 수집만 (~3분, 가벼움)
  - 매일 03:30: 전체 갱신 (selector + 가격 + 지표). selector 매시간은 너무 무거워서 (30~60분)
- **CSV 저장**: `data/collections/{YYYY-MM-DD}.csv` 에 일자별 append (utf-8-sig BOM, Excel 호환)
- **API 추가**: `POST /api/refresh` (전체 갱신 수동 트리거)
- **차트**: 구별 라인 시리즈에서 정렬/dedup 강화로 Lightweight Charts 데이터 무결성 보장

## 2026-04-29 — Phase 1~5 코어 구현 완료

- 전체 파이프라인 코드 완성 및 E2E 검증:
  - [naver_api.py](naver_api.py) — Playwright 브라우저 세션 기반. 세션 쿠키 + Bearer 토큰 자동 캡처 → 429 우회 성공
  - [complex_selector.py](complex_selector.py) — 8개 자치구 순회, 1000세대↑ + 59㎡ 보유 필터, 세대수 Top 100 정렬
  - [price_collector.py](price_collector.py) — 단지별 59㎡ 최저호가 수집, naive KST datetime으로 DB 저장
  - [index_calculator.py](index_calculator.py) — avg/median (억 단위), 시간봉 OHLC (IQR spread), 일봉 OHLC (KST 00:00 기준)
  - [app.py](app.py) — Flask + APScheduler (매시간 정각 KST), REST API 6개
  - [templates/index.html](templates/index.html) + [static/js/chart.js](static/js/chart.js) + [static/css/style.css](static/css/style.css) — TradingView Lightweight Charts 봉차트 대시보드
- 검증된 동작:
  - Playwright로 강남구 59㎡ 단지 최저호가 26.5억 수집 성공
  - DB hourly_prices → hourly_index → hourly_ohlc → daily_ohlc 전체 흐름 OK
  - Flask API 응답 (/api/hourly, /api/daily, /api/complexes, /api/status) OK
- **다음 행동**: `python complex_selector.py` 실행으로 실제 Top 100 단지 선정 (8개 구 전체 순회, 30~60분 소요 예상)

## 2026-04-28 — 결정사항 반영 + Phase 1 착수

- 사용자 결정 4건 확정:
  1. Top 100 정렬 = **거래량 순** (세대수 → 거래량으로 변경)
  2. 일봉 기준 = **KST 00:00 시작**
  3. 결측 단지 = **제외 처리**
  4. 단지 풀 갱신 = **1시간 주기** (매 수집 사이클마다 재확인 + 재랭킹)
- 추가 확정 (genspark 기록 참고):
  - **Index 단위 = 가격값 자체 (억)**, 1000 base 정규화 안 함
  - **데이터 무제한 보존**
  - 시간봉/일봉만, 시간봉 OHLC spread는 단지간 IQR 기반
- README / ARCHITECTURE / ROADMAP 전면 업데이트.
  - Naver Land API 엔드포인트, 자치구 cortarNo, DB 스키마 명시
  - Render 무료 배포 전제 추가
- **다음 행동**: Phase 1 코드 — `requirements.txt`, `config.py`, `database.py`, `naver_api.py` 생성.

## 2026-04-28 — 프로젝트 셋업

- 빈 작업 폴더 `c:/Users/User/Desktop/네이버부동산` 에 다음 문서 생성:
  - [README.md](README.md) — 프로젝트 개요, Index 정의, 폴더 구조
  - [ARCHITECTURE.md](ARCHITECTURE.md) — 모듈 구조, 데이터 흐름, DB 스키마, 미정 사항
  - [ROADMAP.md](ROADMAP.md) — Phase 0~7 단계별 작업 계획
  - [HISTORY.md](HISTORY.md) — 본 파일
- 기술 스택 잠정 결정: Python + SQLite + plotly + APScheduler
- 미결정 사항 정리 → ARCHITECTURE.md "TBD" 섹션 참조
- **다음 행동**: Phase 0 사전 조사 — 네이버부동산 API 엔드포인트와 응답 스키마 확인.

## 2026-04-28 — 프로젝트 셋업

- 빈 작업 폴더 `c:/Users/User/Desktop/네이버부동산` 에 다음 문서 생성:
  - [README.md](README.md) — 프로젝트 개요, Index 정의, 폴더 구조
  - [ARCHITECTURE.md](ARCHITECTURE.md) — 모듈 구조, 데이터 흐름, DB 스키마, 미정 사항
  - [ROADMAP.md](ROADMAP.md) — Phase 0~7 단계별 작업 계획
  - [HISTORY.md](HISTORY.md) — 본 파일
- 기술 스택 잠정 결정: Python + SQLite + plotly + APScheduler
- 미결정 사항 정리 → ARCHITECTURE.md "TBD" 섹션 참조
- **다음 행동**: Phase 0 사전 조사 — 네이버부동산 API 엔드포인트와 응답 스키마 확인.
