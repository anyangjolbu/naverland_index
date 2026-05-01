# 서울 아파트 59㎡ 최저호가 Index

서울 핵심 8개 자치구 — **강남 / 서초 / 용산 / 송파 / 마포 / 성동 / 동작 / 강동** —
의 1,000세대 이상 + 전용 59㎡ 보유 아파트 **Top 100** (거래량 순) 의 매물 최저호가를
시간 단위로 수집하여, 평균/중위 가격을 주식처럼 봉차트(OHLC)로 시각화한다.

## Index 정의

- 단지 i, 시각 t의 59㎡ 매물 최저호가: `P_i(t)` (만원 단위)
- **Mean Price**:   `Avg(t)  = mean(P_i(t))`
- **Median Price**: `Med(t)  = median(P_i(t))`
- 표시 단위: **억** (e.g., `18.5` = 18억 5천만원)
- **Index base = 가격값 자체** — 1000을 기준으로 하는 정규화 안 함.

## 수집 / 차트 사양

| 항목 | 값 |
|---|---|
| 수집 주기 | 매시간 1회 (KST 정각) |
| 단지 풀 갱신 | 매시간 1회 (조건 재확인 + 재랭킹) |
| Top 100 정렬 | **거래량 순** (월간 실거래 건수 기반) |
| 결측 단지 | 매물 0건 단지는 해당 시각 집계에서 **제외** |
| 일봉 기준 | **KST 00:00 ~ 23:59:59** (1일) |
| 시간봉 | 1H 단위 OHLC |
| 데이터 보존 | **무제한** |

## 폴더 구조

```
네이버부동산/
├── README.md              # (이 파일)
├── ARCHITECTURE.md        # 모듈 구조 / 데이터 모델 / 엔드포인트
├── ROADMAP.md             # 단계별 작업 계획
├── HISTORY.md             # 진행 히스토리
│
├── requirements.txt
├── config.py              # 상수 / 설정
├── database.py            # SQLite 스키마 / CRUD
├── naver_api.py           # Naver Land API 클라이언트 + 가격 파서
├── complexes_data.py      # 하드코딩 Top 100 단지 (시드) — 미작성
├── complex_selector.py    # 단지 선정 / 재랭킹 — 미작성
├── price_collector.py     # 시간 단위 호가 수집 — 미작성
├── index_calculator.py    # 시간봉/일봉 OHLC 산출 — 미작성
├── app.py                 # Flask + APScheduler — 미작성
│
├── data/                  # SQLite DB + 단지 캐시
├── templates/             # HTML
├── static/                # CSS + JS (Lightweight Charts)
└── logs/
```

## 기술 스택

- Python 3 + Flask + APScheduler
- SQLite (단일 파일, 무제한 누적)
- TradingView **Lightweight Charts** (캔들스틱)
- 배포: **Render 무료 티어** 우선 시도, 안 되면 로컬

자세한 설계: [ARCHITECTURE.md](ARCHITECTURE.md) · 작업 단계: [ROADMAP.md](ROADMAP.md) · 진행 기록: [HISTORY.md](HISTORY.md)
