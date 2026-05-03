# 서울 아파트 59㎡ Index

서울 핵심 8개 자치구 (강남·서초·용산·송파·마포·성동·동작·강동) 의
**전용 59㎡ 보유 + 세대수 상위 100개 단지** 의 가격을 시간 단위로 추적해
평균/중위값을 봉차트(OHLC)로 시각화한다.

**Live**: https://naverlandindex-production.up.railway.app/

## 데이터 소스

원래 Naver 부동산을 직접 크롤링했으나 **Naver 가 모든 클라우드 IP 의
부동산 도메인 (`new.land.naver.com`, `m.land.naver.com`, `api.land.naver.com`)
접근을 silent drop** 하여 Railway 배포 후 수집 불능.

→ **Richgo** (`api-m.richgo.ai`) 의 공개 API 로 가격만 fetch 하는 구조로 전환.
인증 불필요, IP 차단 없음, 24평(=59㎡ 전용) 가격 + 시세 모두 제공.

```
canonical 100 단지 (Naver 에서 수집한 복귀 불가 데이터)
       │
       ▼
richgo_mapping.json  (Naver complex_no → Richgo danjiId, 94/100)
       │
       ▼
매시간 02분 KST: Richgo /api/data/danji/onepage 호출 (단지별)
       │
       ▼
24평 가격 추출 (OFFER 호가 → 없으면 RICHGO_SISE 시세 → KB 시세)
       │
       ▼
DB hourly_prices → hourly_ohlc → daily_ohlc → Flask API → 차트
```

## Index 정의

- 단지 i, 시각 t의 24평(=59㎡) 가격: `P_i(t)` (만원)
- **Mean**:   `Avg(t)  = mean(P_i(t))`
- **Median**: `Med(t)  = median(P_i(t))`
- 표시 단위: **억** (`P / 10000`)
- Index base = 가격값 자체 (1000 정규화 안 함)
- 결측 단지 (가격 없음) = 집계에서 제외

## 가격 소스 우선순위 (per-danji)

Richgo `/api/data/danji/onepage` 응답의 `pyeongInfos[24].danjiPriceInfo.memePriceDict` 에서:

1. **OFFER.minPrice** — 현재 매물 최저호가 (가장 정확, 자주 NULL)
2. **RICHGO_SISE.price** — Richgo 산출 시세 (호가 없을 때 fallback, 거의 항상 존재)
3. **KB.price** — KB 시세 (마지막 fallback)

매시간 ~94 호출 (~25초), 매핑된 모든 단지 100% 가격 수집.

## 폴더 구조

```
.
├── README.md                # 이 파일
├── ARCHITECTURE.md          # 모듈/데이터흐름/DB/엔드포인트
├── HISTORY.md               # 변경 기록
├── ROADMAP.md               # 미해결 / 향후 아이디어
│
├── Dockerfile               # python:3.11-slim (Playwright 제거)
├── railway.toml             # Railway 배포 설정 + 헬스체크
├── requirements.txt
│
├── app.py                   # Flask + APScheduler
├── config.py                # 자치구 sggBjdCode + TARGET_PYEONG_TYPE
├── database.py              # SQLite 스키마 + CRUD + 마이그레이션
├── richgo_api.py            # Richgo API 클라이언트 (replaces naver_api.py)
├── complex_selector.py      # 정적 부트스트랩 (canonical 100 → DB)
├── price_collector.py       # per-danji onepage 가격 수집기
├── index_calculator.py      # 시간봉/일봉 OHLC
│
├── complexes.json           # canonical Top 100 (Naver 에서 미리 수집)
├── richgo_mapping.json      # Naver complex_no → Richgo danjiId (94 매핑)
├── build_mapping.py         # 1회성 매핑 빌더 (snowball + fuzzy match)
│
├── data/                    # SQLite DB + 캐시 (Railway Volume 마운트)
├── logs/
├── templates/index.html     # 대시보드
└── static/                  # CSS + Lightweight Charts
```

## 기술 스택

| 컴포넌트 | 선택 |
|---|---|
| 언어/프레임워크 | Python 3.11 + Flask + APScheduler |
| DB | SQLite (Railway Volume 영구 저장) |
| 차트 | TradingView Lightweight Charts |
| 데이터 소스 | Richgo (`api-m.richgo.ai`) |
| 호스팅 | Railway Hobby ($5/월, 항상 가동, 영구 디스크) |
| 컨테이너 | `python:3.11-slim` (Chromium 불필요) |

## API 엔드포인트

| Path | 설명 |
|---|---|
| `GET /` | 대시보드 (HTML) |
| `GET /api/hourly?limit=720` | 시간봉 OHLC |
| `GET /api/daily?limit=365` | 일봉 OHLC |
| `GET /api/complexes` | 단지 목록 + 최신 가격 |
| `GET /api/district/hourly?limit=168` | 자치구별 시간봉 평균 |
| `GET /api/status` | 스케줄러/수집 상태 |
| `POST /api/run` | 수동 가격 수집만 (~25초) |
| `POST /api/refresh` | 수동 부트스트랩 + 가격 수집 (~30초) |

## 스케줄

| 시각 (KST) | 작업 | 소요 |
|---|---|---|
| 매시간 :02 | 가격 수집만 | ~25초 |
| 매일 03:30 | 부트스트랩 + 가격 수집 | ~30초 |

자세한 설계: [ARCHITECTURE.md](ARCHITECTURE.md) · 변경사: [HISTORY.md](HISTORY.md) · 향후 아이디어: [ROADMAP.md](ROADMAP.md) · Naver 직접 크롤링 노트 (로컬용 백업): [NAVER_DIRECT.md](NAVER_DIRECT.md)
