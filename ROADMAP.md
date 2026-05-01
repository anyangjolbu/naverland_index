# Roadmap

각 Phase 종료 시 [HISTORY.md](HISTORY.md) 에 기록.

## Phase 0 — 사전 조사 ✅ (genspark 세션에서 완료)
- [x] Naver Land API 엔드포인트 확인 (regions / complexes / articles)
- [x] 자치구 cortarNo 매핑
- [x] 가격 파싱 로직 ("18억 5,000" → 185000 만원) 검증
- [x] Sandbox IP 429 차단 이슈 인지 → Render/로컬 IP에서 재시도 필요

## Phase 1 — 기반 코드 (현재 진행 중)
- [x] README / ARCHITECTURE / ROADMAP / HISTORY 셋업
- [ ] `requirements.txt`
- [ ] `config.py` (cortarNo, 헤더, 수집 주기 등)
- [ ] `database.py` (스키마 + 기본 CRUD)
- [ ] `naver_api.py` (HTTP 클라이언트 + 가격 파서 + 429 backoff)

## Phase 2 — 단지 선정기
- [ ] `complexes_data.py` — 시드 Top 100 (수동 조사 결과 하드코딩, 부트 시 1회 적재)
- [ ] `complex_selector.py` — 매시간 재확인:
  - 8개 구 → 동 → 단지 트래버스
  - 1000세대↑ + 59㎡ 보유 필터
  - 거래량 정렬 (소스 미해결 시 세대수 fallback)
- [ ] 거래량 데이터 소스 결정:
  - MOLIT 실거래가 API 시도 (API 키 필요)
  - 또는 Naver 단지 상세의 거래내역 필드 활용
- [ ] 100개 단지 검증 (육안: 헬리오시티/잠실엘스/반포자이 등 핵심 단지 포함되는지)

## Phase 3 — 호가 수집기
- [ ] `price_collector.py` — 단지별 59㎡ 매물 최저호가 추출
- [ ] 단지간 1~2초 sleep / 429 retry
- [ ] DB `hourly_prices` 적재 (UNIQUE 제약으로 중복 방지)
- [ ] 1회 수동 실행 → 100개 단지 모두 결측 사유 명확화

## Phase 4 — 인덱스 / OHLC 산출
- [ ] `index_calculator.py`
  - `hourly_index` 갱신 (avg/median, 결측 단지 제외)
  - `hourly_ohlc` 갱신 (이전 close → 현재 close, IQR spread)
  - `daily_ohlc` 갱신 (KST 00:00 기준)

## Phase 5 — Flask + 스케줄러 + 프론트
- [ ] `app.py` Flask + APScheduler
- [ ] `templates/index.html` + `static/css/style.css` + `static/js/chart.js`
- [ ] Lightweight Charts 봉차트 (시간봉 / 일봉, 평균 / 중위 토글)
- [ ] 단지 리스트 패널

## Phase 6 — Render 무료 배포
- [ ] `Procfile` / `render.yaml`
- [ ] `PORT` 환경변수 처리
- [ ] 배포 후 실제 Naver API 호출 가능 여부 검증
  - 가능 → 시간 단위 자동 수집 시작
  - 차단 → Playwright fallback 또는 외부 프록시 검토
- [ ] DB 영속화 (Render free tier 디스크 휘발성 → 외부 백업)
- [ ] 슬립 방지 (UptimeRobot 등)

## Phase 7 — 안정화 / 확장 (선택)
- [ ] Playwright 기반 백업 수집기
- [ ] 단지/면적/자치구 확장 (84㎡, 114㎡ 등)
- [ ] 이상치 탐지 (스팸 매물 제거)
- [ ] 알림 (가격 급변 시 텔레그램/이메일)

---

## 우선순위 이슈

1. **거래량 데이터 소스** — Phase 2 진입 직전 결정 필요. MOLIT 시도 우선.
2. **단지 갱신 1시간 주기** — 사용자 명시. 호출 비용이 크므로 (8개구 × 동 × 단지 ≈ 수백 콜) 캐싱 + 변동분만 갱신하는 식으로 최적화.
3. **Render free tier SQLite 휘발성** — 장기 운영의 핵심 리스크. Phase 6 진입 전 백업 전략 결정.
