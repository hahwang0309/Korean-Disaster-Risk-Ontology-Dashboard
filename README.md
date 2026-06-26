# Korean Disaster-Risk Ontology Dashboard

한국 재난 문서(수해백서·사고조사보고서·재난백서)에서 **재난위험관리 온톨로지**(위험원·노출·사건·피해·대응·맥락 — 16 엔티티 타입 + Other / 32 관계 + PRECEDES)에 따라 (subject, predicate, object) 트리플을 추출해, 재난이 어떻게 **발생 → 전파(cascading) → 피해 → 대응**으로 이어지는지 예측하기 위한 그래프 데이터베이스 프로젝트.

## 🔗 Live
https://hahwang0309.github.io/Korean-Disaster-Risk-Ontology-Dashboard/

## 문서

| # | 문서 | 도메인 | 트리플 | 노드 |
|---|------|--------|--------|------|
| 01 | 태풍 루사·매미 수해백서 (강릉시, 2005) | 풍수해 `natural_storm` | 299 | 447 |
| 02 | 우면산 산사태 원인 보완조사 (서울시, 2014) | 산사태 `natural_landslide` | 237 | 272 |
| 03 | 4·16 세월호참사 백서 (대한변협, 2015) | 해양교통 `social_transport` | 1,172 | 1,238 |

## 구성
- `index.html` — 문서별 대시보드 색인
- `dashboards/` — 문서별 인터랙티브 시각화(9종: Network Connectivity Map · Entity/Predicate Distribution·Heatmap · Sankey · Force-directed Graph · Centrality · Community). 자가완결 HTML(Plotly + D3, 공개 CDN·SRI 고정).
- `data/` — 원본 트리플(`*_triples.json`) 및 Neo4j 적재 스크립트(`*.cypher`)

## 온톨로지
6축 16타입: NaturalHazard·ManmadeHazard·RiskFactor / Region·Facility·Population / Event / Damage / ResponseAction·ResponseActor·Resilience / Context (+Other).
인과·연쇄 관계(TRIGGERS·CASCADES_INTO·CAUSES·AMPLIFIES·INCREASES_RISK_OF 등)를 중심으로 cascading 위험 전파를 표현.

> 출처 문서는 모두 공개 발간 자료입니다. 트리플은 LLM 추출 결과로, 원문 대조 검수가 필요할 수 있습니다.
