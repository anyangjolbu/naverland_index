# Roadmap

대부분의 Phase 0~6 항목은 완료 (자세한 변경사: [HISTORY.md](HISTORY.md)).
이 문서는 **현재 미해결 / 향후 개선 아이디어** 만 유지.

## 미해결

### 1. canonical 100 단지 갱신 메커니즘
현재 `complexes.json` 은 2026-04 시점 Naver 크롤링 결과로 고정.
신축 입주 / 재건축 / 세대수 변경 등을 반영하려면:

- **현실적 옵션**: 사용자 집 PC 에서 주기적으로 (분기 1회 정도) Naver 직접 크롤러 재실행 → 갱신된 complexes.json 을 repo 에 push → build_mapping.py 재실행. 크롤러 코드는 [NAVER_DIRECT.md](NAVER_DIRECT.md) 에 reference 보존됨 (or `git show 8ac93f5:naver_api.py` 로 복구).
- **이상적 옵션**: 자체 Naver 크롤러를 집 PC + Cloudflare Tunnel 로 외부 노출 → Railway 가 호출. 셋업 부담 큼.

지금은 미해결 — 단지 풀이 1년 정도는 거의 안 변하므로 우선순위 낮음.

## 향후 아이디어

### 데이터 보강
- [ ] 84㎡, 114㎡ 같은 다른 평형 인덱스 추가 (테이블 + 차트 분리). pyeongType 매핑 표 작성 필요 — 24=59㎡전용, 33=84㎡, 45=114㎡ 추정
- [ ] Naver 직접 크롤러 백업 (집 PC + Cloudflare Tunnel) — Richgo API 변경/폐쇄 대비. [NAVER_DIRECT.md](NAVER_DIRECT.md) 참조
- [ ] 자치구 추가 (현재 8개 → 25개 서울 전체)
- [ ] 전세 인덱스 추가 (`tradeType=Jeonse`)
- [ ] 실거래가 (MOLIT) vs 호가 spread 시각화

### 알림 / 분석
- [ ] 가격 급변 (주간 ±N%) 시 텔레그램 / 이메일
- [ ] 평소 대비 매물 급증 / 급감 알림
- [ ] 자치구별 상관관계 / 베타 분석

### 운영
- [ ] DB 백업 자동화 (Railway Volume → S3/GCS 주간)
- [ ] Grafana / Sentry 같은 외부 모니터링
- [ ] Richgo API 변경 감지 (응답 스키마 schema validation)

### 코드 개선
- [ ] gunicorn 으로 전환 (APScheduler 를 모듈 스코프로 옮긴 후 worker 1개로)
- [ ] hourly job 의 lock 보다 큐 기반 (작업 적체 시 무시 대신 deferred 실행)
- [ ] 가격 source ('OFFER' vs 'SISE') 를 hourly_prices 에 컬럼 추가 → 차트에서 구분 표시
