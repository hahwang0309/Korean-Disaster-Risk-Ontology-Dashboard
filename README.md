# Korean Disaster-Risk Ontology Dashboard

한국 재난 문서(수해백서·사고조사보고서·재난백서)에서 **재난위험관리 온톨로지**(위험원·노출·사건·피해·대응·맥락 — 16 엔티티 타입 + Other / 32 관계 + PRECEDES)에 따라 (subject, predicate, object) 트리플을 추출해, 재난이 어떻게 **발생 → 전파(cascading) → 피해 → 대응**으로 이어지는지 예측하기 위한 그래프 데이터베이스 프로젝트.

## 🔗 Live
https://hahwang0309.github.io/Korean-Disaster-Risk-Ontology-Dashboard/

## 문서

| # | 문서 | 도메인 | 트리플 | 노드 |
|---|------|--------|--------|------|
| 01 | 태풍 루사·매미 수해백서 (강릉시, 2005) | 풍수해 `natural_storm` | 298 | 446 |
| 02 | 우면산 산사태 원인 보완조사 (서울시, 2014) | 산사태 `natural_landslide` | 231 | 266 |
| 03 | 4·16 세월호참사 백서 (대한변협, 2015) | 해양교통 `social_transport` | 1,170 | 1,221 |
| 04 | 이천 코리아2000 냉동창고 화재 백서 (경기소방, 2008) | 화재 `social_fire` | 221 | 244 |

## 구성
- `index.html` — 문서별 대시보드 색인 / `schema.html` — 온톨로지 스키마(Mermaid)
- `dashboards/` — 문서별 인터랙티브 시각화(9종: Network Connectivity Map · Entity/Predicate Distribution·Heatmap · Sankey · Force-directed Graph · Centrality · Community). 자가완결 HTML(Plotly + D3, 공개 CDN·SRI 고정).
- `data/` — 원본 트리플(`*_triples.json`) 및 Neo4j 적재 스크립트(`*.cypher`)
- `skill/` — **추출 파이프라인 코드** (Claude Code 스킬 `disaster-risk-triples`). 이 코드로 위 산출물을 생성한다.

## skill/ — 추출 파이프라인
재난 문서(PDF/DOCX/TXT) → 트리플 JSON + Cypher + 대시보드 생성. Python 표준 라이브러리만 사용(추가 설치 불필요, PDF는 poppler `pdftotext` 권장).

| 파일 | 역할 |
|---|---|
| `SKILL.md` | 워크플로 전체 정의(밀도 모드·엔티티 해소·시각화) |
| `references/ontology.md` | 추출 에이전트용 온톨로지 지침 |
| `references/ontology_schema.json` | 기계판독용 타입·관계 enum(검증·Cypher) |
| `scripts/extract_text.py` · `chunk_text.py` | 텍스트 추출 · (밀도별)청크 분할 |
| `scripts/merge_validate.py` | 병합·검증·emergent 메타스키마 |
| `scripts/resolve_entities.py` | 엔티티 해소(괄호 한정자 자동병합·이종타입 통합) |
| `scripts/update_master_schema.py` | 전역 메타스키마 누적 |
| `scripts/to_cypher.py` · `visualize.py` | Neo4j Cypher · 9종 대시보드 생성 |
| `data/` | 전역 누적 상태(메타 브릿지 테이블·엔티티 별칭 레지스트리·마스터 스키마) 스냅샷 |

추출 단계(청크별 트리플 추출)는 LLM 에이전트가 수행하므로 전체 파이프라인은 Claude Code의 `/disaster-risk-triples` 스킬로 구동된다. `scripts/`는 결정적(deterministic) 전·후처리 단계로 단독 실행 가능.

## 온톨로지
6축 16타입: NaturalHazard·ManmadeHazard·RiskFactor / Region·Facility·Population / Event / Damage / ResponseAction·ResponseActor·Resilience / Context (+Other).
인과·연쇄 관계(TRIGGERS·CASCADES_INTO·CAUSES·AMPLIFIES·INCREASES_RISK_OF 등)를 중심으로 cascading 위험 전파를 표현.

> 출처 문서는 모두 공개 발간 자료입니다. 트리플은 LLM 추출 결과로, 원문 대조 검수가 필요할 수 있습니다.
