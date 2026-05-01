# Architecture

## 1. 데이터 흐름

```
[자치구 cortarNo] ─┐
                   │ (시드)
                   ▼
            ┌──────────────┐
            │ complex_     │  매시간 재확인:
            │ selector     │  · 1000세대 이상 + 59㎡ 보유 필터
            └──────┬───────┘  · 거래량 순 Top 100 재랭킹
                   │
                   ▼
            ┌──────────────┐
            │ complexes    │ ← Naver: /api/regions/list
            │ (DB)         │ ← Naver: /api/regions/complexes
            └──────┬───────┘ ← Naver: /api/complexes/{id}
                   │           ← MOLIT 실거래가 (거래량)
                   ▼
            ┌──────────────┐
            │ price_       │
            │ collector    │  매시간 정각:
            └──────┬───────┘  · 단지 100개 × 59㎡ 매물 조회
                   │           · 단지별 최저호가 추출
                   ▼
            ┌──────────────┐
            │ hourly_      │ ← Naver: /api/articles/complex/{id}
            │ prices (DB)  │
            └──────┬───────┘
                   │
                   ▼
            ┌──────────────┐
            │ index_       │  매시간 (수집 직후):
            │ calculator   │  · avg/median 산출 (억 단위)
            └──────┬───────┘  · 일봉 OHLC 갱신 (KST 00:00 기준)
                   │
                   ▼
       ┌───────────┴───────────┐
       ▼                       ▼
┌──────────────┐       ┌──────────────┐
│ hourly_index │       │ daily_ohlc   │
│ (DB)         │       │ (DB)         │
└──────┬───────┘       └──────┬───────┘
       │                       │
       └───────────┬───────────┘
                   ▼
            ┌──────────────┐
            │ Flask app +  │  /api/hourly  → 시간봉
            │ Lightweight  │  /api/daily   → 일봉
            │ Charts       │  /api/complexes
            └──────────────┘
```

## 2. 모듈

### 2.1 `naver_api.py`
- 베이스 URL: `https://new.land.naver.com`
- 엔드포인트:
  - `GET /api/regions/list?cortarNo={code}` — 시/도 → 구 → 동 계층 코드
  - `GET /api/regions/complexes?cortarNo={dongCode}&realEstateType=APT` — 동 단위 단지 목록
  - `GET /api/complexes/{complexNo}?sameAddressGroup=false` — 단지 상세 (totalHouseHoldCount, complexPyeongDetailList)
  - `GET /api/articles/complex/{complexNo}?realEstateType=APT&tradeType=A1&areaNos={areaNo}&page={n}` — 매매 매물 리스트
- 헤더:
  - `User-Agent: Mozilla/5.0 ...` (실제 브라우저 UA)
  - `Referer: https://new.land.naver.com/complexes`
  - `Authorization: Bearer <JWT>` — 토큰은 페이지 내 `REALESTATE` payload, 주기 갱신
- Rate limit: 단지당 1~2초 sleep, 429 응답 시 exponential backoff
- 가격 파싱: `"18억 5,000"` → `185000` (만원)
- IP 차단 우회 fallback: Playwright 브라우저로 페이지 내 API 인터셉트 (Phase 2 이후)

### 2.2 `complex_selector.py`
1. 8개 자치구 cortarNo로 동 목록 조회
2. 각 동의 단지 목록 → `세대수 ≥ 1000` 필터
3. 단지 상세에서 `complexPyeongDetailList`에 `exclusiveArea ≈ 59m²` 존재 여부 확인 (areaNo 기록)
4. **거래량 순** 정렬 → Top 100 (거래량 데이터 미확보 시 세대수로 대체 + 로그 경고)
5. 매시간 재실행 — 신규 단지 편입/이탈을 자동 반영
6. 변경 시 `complexes` 테이블 upsert + `selected_at` 갱신

> **거래량 데이터 소스 (TBD)**:
> - 1순위: MOLIT 실거래가 공개시스템 API (`apis.data.go.kr/1613000/RTMSDataSvcAptTrade`) — 월 단위 거래 건수 집계
> - 2순위: Naver 단지 상세의 `realPriceTradeList` 등 내부 필드
> - 미해결 시: 세대수 fallback + 매뉴얼 시드(`complexes_data.py`)

### 2.3 `price_collector.py`
- 입력: DB의 100개 단지 + 각 단지 59㎡ areaNos
- 매시간 정각 (KST) 단지별 매물 조회 → 최저호가 추출
- 매물 0건 단지는 NULL min_price로 기록 (집계 단계에서 제외됨)
- 호출 간격: 단지당 1~2초

### 2.4 `index_calculator.py`
- 시간 단위:
  - `Avg(t) = mean(P_i)` (NULL 단지 제외)
  - `Med(t) = median(P_i)` (NULL 단지 제외)
  - 단위: 억 (= 만원 / 10000)
- **시간봉 OHLC** (1H):
  - Open  = 직전 시간의 close (없으면 현재값)
  - Close = 현재 시간의 평균 (또는 중위값)
  - High  = max(Open, Close, 현재 단지가격 75th percentile)
  - Low   = min(Open, Close, 현재 단지가격 25th percentile)
  - 1시간에 1회만 수집되므로 단지간 가격 분포(IQR)를 high/low spread로 활용
- **일봉 OHLC** (KST 00:00 기준):
  - 그 날의 시간봉들을 모아: O=첫 시간봉의 open, H=max(high), L=min(low), C=마지막 시간봉의 close
  - 평균/중위 각각 계산

### 2.5 `app.py`
- Flask + APScheduler:
  - 매시간 정각: `complex_selector.refresh()` → `price_collector.run()` → `index_calculator.update()`
- 엔드포인트:
  - `GET /` → 대시보드
  - `GET /api/hourly?limit=720` → 시간봉 OHLC JSON
  - `GET /api/daily?limit=365` → 일봉 OHLC JSON
  - `GET /api/complexes` → 단지 목록 + 최신 호가
  - `GET /api/status` → 스케줄러/수집 상태

### 2.6 Frontend
- TradingView Lightweight Charts (캔들스틱)
- 탭: [시간봉] [일봉]
- 토글: [평균 ◉ / 중위 ○]
- 단지 리스트 테이블 (정렬 가능)

## 3. DB 스키마 (SQLite, `data/index.db`)

```sql
-- 선정된 단지 마스터 (매시간 upsert)
CREATE TABLE complexes (
  complex_no       TEXT PRIMARY KEY,
  complex_name     TEXT NOT NULL,
  district         TEXT NOT NULL,
  household_cnt    INTEGER NOT NULL,
  trade_volume     INTEGER,           -- 최근 N개월 누적 거래 건수 (랭킹 기준)
  area_no_59       TEXT,              -- 59㎡ 평형의 areaNos 파라미터값
  pyeong_no        TEXT,
  rank             INTEGER,           -- 1..100, 거래량 정렬 순위
  selected_at      TIMESTAMP NOT NULL
);

-- 단지별 시간 단위 최저호가 (raw)
CREATE TABLE hourly_prices (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  collected_at     TIMESTAMP NOT NULL,    -- KST, 시간 정각 정규화
  complex_no       TEXT NOT NULL,
  min_price        INTEGER,                -- 만원, NULL = 매물 없음(결측)
  article_count    INTEGER DEFAULT 0,
  FOREIGN KEY (complex_no) REFERENCES complexes(complex_no)
);
CREATE UNIQUE INDEX ux_hourly_prices ON hourly_prices(collected_at, complex_no);

-- 시간 단위 집계 (가격값 자체, 단위 억)
CREATE TABLE hourly_index (
  collected_at     TIMESTAMP PRIMARY KEY,
  avg_price        REAL,           -- 억
  median_price     REAL,           -- 억
  sample_count     INTEGER,        -- 100 (대상 단지 수)
  valid_count      INTEGER         -- 매물 존재 단지 수 (sample_count - 결측)
);

-- 시간봉 OHLC (1H)
CREATE TABLE hourly_ohlc (
  ts               TIMESTAMP PRIMARY KEY,
  avg_open         REAL,
  avg_high         REAL,
  avg_low          REAL,
  avg_close        REAL,
  median_open      REAL,
  median_high      REAL,
  median_low       REAL,
  median_close     REAL,
  valid_count      INTEGER
);

-- 일봉 OHLC (KST 00:00 기준)
CREATE TABLE daily_ohlc (
  date             DATE PRIMARY KEY,
  avg_open         REAL,
  avg_high         REAL,
  avg_low          REAL,
  avg_close        REAL,
  median_open      REAL,
  median_high      REAL,
  median_low       REAL,
  median_close     REAL,
  hour_count       INTEGER          -- 그 날 집계된 시간봉 개수
);

-- 메타 (가변 설정)
CREATE TABLE meta (
  key              TEXT PRIMARY KEY,
  value            TEXT NOT NULL,
  updated_at       TIMESTAMP NOT NULL
);
```

## 4. 자치구 cortarNo

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

## 5. 운영 / 배포

- 1차: 로컬 (Windows). Naver IP 차단 시 직접 실행.
- 2차: **Render 무료 티어** 배포.
  - `Procfile`: `web: python app.py`
  - 환경변수 `PORT` 사용 (Flask 자동 바인딩).
  - Free tier 디스크는 비영속 → SQLite 파일 손실 주의. 장기 운영 시 외부 PostgreSQL/볼륨 검토.
  - Free tier 슬립 → 외부 cron-ping 또는 UptimeRobot 으로 깨우기.
- 단지 100개 × 호출 1~2초 ≈ 3~5분/시간 → free tier 1코어로 충분.

## 6. 미정 사항

| 항목 | 상태 |
|---|---|
| 거래량 데이터 소스 (MOLIT API vs Naver 내부) | TBD — Phase 1 진행 중 결정 |
| Naver IP 차단 시 fallback (Playwright) | Phase 2-1 에서 결정 |
| Render free tier DB 영속화 방안 | Phase 6 에서 결정 |
| 봉차트 단지간 spread 표현 | IQR 기반으로 잠정 결정 (운영하며 조정) |
