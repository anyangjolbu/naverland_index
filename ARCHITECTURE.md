# Architecture

## 1. 데이터 흐름

```
[정적 자산 — repo 에 commit 됨]
  complexes.json          ← 과거 Naver 크롤링으로 만든 Top 100 단지 (세대수, rank 등)
  richgo_mapping.json     ← Naver complex_no → Richgo danjiId 매핑 (94/100)
        │
        │ 부트스트랩 (앱 시작 시 + /api/refresh + 매일 03:30)
        ▼
  ┌─────────────────────┐
  │  complex_selector   │  · complexes.json + mapping 로드
  │  (정적 bootstrap)   │  · DB complexes 테이블 upsert
  │                     │  · legacy 잔재(non-digit complex_no) 정리
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │  complexes (DB)     │  · 100개 row, 영구
  │  · complex_no       │
  │  · richgo_danji_id  │  ← lookup 키
  │  · household_cnt    │  ← 불변
  │  · rank             │  ← 불변
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐  매시간 02분 (KST):
  │  price_collector    │  for each mapped danji:
  │                     │    GET /api/data/danji/onepage?danjiId=...
  └──────────┬──────────┘    parse pyeongInfos[24].danjiPriceInfo
             │                price = OFFER → RICHGO_SISE → KB
             ▼
  ┌─────────────────────┐
  │  hourly_prices (DB) │  단지별 시간 단위 가격 (만원)
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │  index_calculator   │  · avg/median (억)
  │                     │  · 시간봉 OHLC (전 시간 close → 현 시간 close, IQR spread)
  │                     │  · 일봉 OHLC (KST 00:00 기준)
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐    ┌──────────────────┐
  │  hourly_ohlc (DB)   │    │  daily_ohlc (DB) │
  └──────────┬──────────┘    └─────────┬────────┘
             │                          │
             └────────────┬─────────────┘
                          ▼
                ┌──────────────────────┐
                │  Flask app           │
                │  + Lightweight Charts│
                └──────────────────────┘
```

## 2. 모듈

### 2.1 `richgo_api.py` (← naver_api.py 대체)

Base URL: `https://api-m.richgo.ai`. 인증 없음, requests 기반 단순 GET.

| Endpoint | 용도 |
|---|---|
| `GET /api/data/danji/onepage?danjiId=X` | 단지 종합 정보 + pyeongInfos (가격 소스 다중) |
| `GET /api/data/danji/price/opengoods?bjdCode=X&tradeType=Meme&...` | 행정구역별 매물 리스트 (snowball 매핑 빌드 시 사용) |

핵심 함수:

- `get_pyeong24_price(danji_id) → (price_manwon, source, count)`
  - pyeongInfos 의 24평 (없으면 25, 23, 26, 22, 27, 21 순으로 fallback) 선택
  - `memePriceDict.OFFER.minPrice` → `RICHGO_SISE.price` → `KB.price` 우선순위
  - source ∈ {'OFFER', 'RICHGO_SISE', 'KB', None}

- `list_opengoods_by_sgg(bjd_code)` — opengoods 호출 (build_mapping.py 와 정적 fallback 용)

Pacing: 0.2초 / 호출. 100 단지 = ~20초.

### 2.2 `complex_selector.py` — 정적 부트스트랩

이전엔 라이브 크롤링이었지만 Naver 차단으로 불가 → **canonical JSON 두 파일을 DB 에 박는 작업**으로 변경.

1. `complexes.json` 로드 (100 단지: complex_no, name, district, household_cnt, rank, area_no_59, pyeong_no)
2. `richgo_mapping.json` 로드 (mapping: complex_no → {danjiId, richgo_name, match_type, score})
3. 두 데이터 join → DB `complexes` upsert (94개는 richgo_danji_id 채워짐, 6개는 NULL)
4. legacy 정리: 이전에 Richgo danjiId 를 complex_no 로 직접 박았던 잔재 (non-digit complex_no) 와 그 hourly_prices 정리

매번 같은 100개를 upsert → 멱등.

### 2.3 `price_collector.py`

매시간 호출되는 핵심 루프:

1. `get_complexes()` → DB 100 단지
2. `richgo_danji_id` 추출 → 94개
3. 각 danji 에 대해 `richgo_api.get_pyeong24_price(danji_id)` 호출
4. `(complex_no, collected_at, min_price, article_count)` 행 생성 → `insert_hourly_prices`
5. CSV 백업 (`data/collections/{date}.csv`) 도 동시 append

매핑 안 된 6개 단지는 가격 NULL 로 저장 (집계에서 자동 제외).

### 2.4 `index_calculator.py`

수정 없음 (Richgo 도입과 무관).

- `update(ts)` — 해당 시각의 hourly_prices 모아서:
  - `hourly_index` 갱신 (avg, median, valid_count)
  - `hourly_ohlc` 갱신 (전 시간 close → 현재 close, IQR-based spread)
  - 영향 받는 날의 `daily_ohlc` 재계산 (해당 일의 시간봉들 모아서 OHLC 산출)

### 2.5 `database.py`

SQLite WAL 모드. 스키마는 거의 그대로지만 `complexes` 테이블에 `richgo_danji_id TEXT` 컬럼 추가. 기존 DB 에는 `init_db()` 의 `PRAGMA table_info` 검사 후 `ALTER TABLE ADD COLUMN` 마이그레이션.

### 2.6 `app.py` — Flask + APScheduler

| 작업 | Cron | 트리거 함수 |
|---|---|---|
| 가격 수집 | 매시간 02분 KST | `_run_price_only` → `price_collector.run_collection` |
| 부트스트랩 + 가격 | 매일 03:30 KST | `_run_full_refresh` → `complex_selector.refresh` + `price_collector.run_collection` |

`_acquire_run / _release_run` 으로 `is_running` 락 관리 (concurrent 방지).
스케줄러는 `if __name__ == "__main__"` 안에서 시작 → **gunicorn 으로 띄우면 안 됨**, `python app.py` 로 실행.

### 2.7 `build_mapping.py` (1회성 도구)

로컬에서 실행하는 매핑 빌더:

1. 8개 자치구 sgg-level Richgo opengoods 호출 → 50건씩 받음
2. 응답에서 emd 코드 추출 → emd-level 호출로 풀 확장 (snowball)
3. `isOnlyLeaders=true` 추가 호출
4. 자치구당 100~200 unique danji 풀 형성 (총 1042개)
5. complexes.json 의 100개 와 fuzzy 매칭:
   - 정규화 후 정확 일치
   - 양방향 substring
   - 자카드 유사도 ≥ 0.5
6. 결과 → `richgo_mapping.json` 저장 (현재 94/100)

매핑은 정적이므로 commit 후 재실행 불필요 (단지가 새로 추가되거나 Naver 데이터 갱신 시에만).

## 3. DB 스키마 (SQLite)

```sql
CREATE TABLE complexes (
  complex_no       TEXT PRIMARY KEY,        -- Naver complex_no (canonical)
  complex_name     TEXT NOT NULL,
  district         TEXT NOT NULL,
  household_cnt    INTEGER NOT NULL,        -- 불변, Naver 에서 수집
  trade_volume     INTEGER,                  -- 사용 안 함 (Naver 시절 잔재)
  area_no_59       TEXT,                     -- Naver pyeong code (legacy)
  pyeong_no        TEXT,                     -- Naver pyeong code (legacy)
  rank             INTEGER,                  -- 1..100
  selected_at      TIMESTAMP NOT NULL,
  richgo_danji_id  TEXT                     -- Richgo danjiId (NULL = 미매핑 6단지)
);

CREATE TABLE hourly_prices (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  collected_at     TIMESTAMP NOT NULL,
  complex_no       TEXT NOT NULL,
  min_price        INTEGER,                  -- 만원, NULL = 가격 없음
  article_count    INTEGER DEFAULT 0,        -- openGoodsCount
  FOREIGN KEY (complex_no) REFERENCES complexes(complex_no)
);
CREATE UNIQUE INDEX ux_hourly_prices_ts_cx ON hourly_prices(collected_at, complex_no);

CREATE TABLE hourly_index (
  collected_at     TIMESTAMP PRIMARY KEY,
  avg_price        REAL,                     -- 억
  median_price     REAL,
  sample_count     INTEGER,                  -- 100
  valid_count      INTEGER                   -- 가격 있는 단지 수
);

CREATE TABLE hourly_ohlc (
  ts               TIMESTAMP PRIMARY KEY,
  avg_open  REAL, avg_high  REAL, avg_low  REAL, avg_close  REAL,
  median_open REAL, median_high REAL, median_low REAL, median_close REAL,
  valid_count INTEGER
);

CREATE TABLE daily_ohlc (
  date             DATE PRIMARY KEY,
  avg_open  REAL, avg_high  REAL, avg_low  REAL, avg_close  REAL,
  median_open REAL, median_high REAL, median_low REAL, median_close REAL,
  hour_count       INTEGER
);

CREATE TABLE meta (
  key              TEXT PRIMARY KEY,
  value            TEXT NOT NULL,
  updated_at       TIMESTAMP NOT NULL
);
```

## 4. 자치구 코드

`config.DISTRICTS` — sggBjdCode (10자리, Naver cortarNo 와 동일).

| 자치구 | sggBjdCode |
|---|---|
| 강남구 | 1168000000 |
| 서초구 | 1165000000 |
| 용산구 | 1117000000 |
| 송파구 | 1171000000 |
| 마포구 | 1144000000 |
| 성동구 | 1120000000 |
| 동작구 | 1159000000 |
| 강동구 | 1174000000 |

## 5. 배포 (Railway)

- `railway.toml`: Dockerfile 빌더, `/api/status` 헬스체크, restart on failure (3 retries)
- `Dockerfile`: `python:3.11-slim` 베이스 (Playwright 제거 → 이미지 ~150MB)
- Volume: `/app/data` 에 영구 마운트 → SQLite + CSV + 단지 캐시
- 환경변수: 특별히 없음 (`PORT` 는 Railway 자동 설정)
- 시작 명령: Dockerfile CMD = `python app.py` (gunicorn 안 씀, APScheduler 가 `if __name__ == "__main__"` 안에 있어서)

## 6. 미매핑 6단지 (정보)

richgo_mapping.json `unmatched` 섹션에 기록:

| rank | 자치구 | complex_no | 단지명 | 가능한 이유 |
|---|---|---|---|---|
| 17 | 강남구 | 11698 | 도곡렉슬 | 현재 매물 0건? |
| 57 | 강남구 | 105735 | 강남자곡힐스테이트 | 매물 0건 |
| 60 | 강남구 | 107458 | 강남한양수자인 | 매물 0건 |
| 64 | 서초구 | 107901 | 서초더샵포레 | 매물 0건 |
| 83 | 서초구 | 178737 | 래미안원페를라 | 신축 (입주 직전?) |
| 84 | 서초구 | 103577 | 서초힐스 | 매물 0건 |

수동 매핑하려면 https://m.richgo.ai/pc 에서 단지명 검색 → URL 의 `realty/danji/[id]` 부분이 danjiId → `richgo_mapping.json` 의 `mapping` 객체에 항목 추가 후 commit.

## 7. 알려진 한계

- **Richgo 의존**: 그들 API 변경 시 깨짐. /api/data/danji/onepage 응답 스키마는 Next.js SPA 분석 결과 파악 — 공식 문서 없음.
- **OFFER 가격은 일부 단지에만 존재**: 현재 매물이 없는 단지는 RICHGO_SISE (시세) 로 fallback. 두 가격은 의미가 다름 (호가 vs 산출 시세).
- **24평 외 평형 fallback**: pyeongType 24 가 없으면 25,23,26,22,27,21 순으로 시도. 24 < 60㎡ < 25 의 단지는 pyeong=25 가격으로 잡힘.
- **Naver 데이터는 갱신 불가**: 새 단지 편입/이탈은 로컬에서 Naver 크롤링 재실행 + complexes.json 갱신 + build_mapping.py 재실행 필요. Railway 에선 못함.
