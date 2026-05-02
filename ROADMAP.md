# Roadmap

대부분의 Phase 0~6 항목은 완료 (자세한 변경사: [HISTORY.md](HISTORY.md)).
이 문서는 **현재 미해결 / 향후 개선 아이디어** 만 유지.

## 미해결

### 1. 미매핑 6단지 수동 매핑
Richgo opengoods 풀에 안 잡혀 자동 매핑 실패한 단지들. 현재 가격 수집 안됨.

| rank | 자치구 | complex_no | 단지명 |
|---|---|---|---|
| 17 | 강남구 | 11698 | 도곡렉슬 |
| 57 | 강남구 | 105735 | 강남자곡힐스테이트 |
| 60 | 강남구 | 107458 | 강남한양수자인 |
| 64 | 서초구 | 107901 | 서초더샵포레 |
| 83 | 서초구 | 178737 | 래미안원페를라 |
| 84 | 서초구 | 103577 | 서초힐스 |

**작업**: 각 단지명을 https://m.richgo.ai/pc 에서 검색 → URL `realty/danji/[id]` 의 id 복사 → `richgo_mapping.json` 의 `mapping` 객체에 항목 추가:
```json
"11698": { "danjiId": "...", "richgo_name": "도곡렉슬", "match_type": "manual", "score": 1.0 }
```
commit & push 하면 다음 부트스트랩에서 자동 반영.

### 2. canonical 100 단지 갱신 메커니즘
현재 `complexes.json` 은 2026-04 시점 Naver 크롤링 결과로 고정.
신축 입주 / 재건축 / 세대수 변경 등을 반영하려면:

- **현실적 옵션**: 사용자 집 PC 에서 주기적으로 (분기 1회 정도) 옛 Naver 크롤링 코드 실행 → 갱신된 complexes.json 을 repo 에 push → build_mapping.py 재실행
- **이상적 옵션**: 자체 Naver 크롤러를 집 PC + Cloudflare Tunnel 로 외부 접속 가능하게 두고, Railway 가 호출. 셋업 부담 큼.

지금은 미해결 — 단지 풀이 1년 정도는 거의 안 변하므로 우선순위 낮음.

## 향후 아이디어

### 데이터 보강
- [ ] 84㎡, 114㎡ 같은 다른 평형 인덱스 추가 (테이블 + 차트 분리)
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
