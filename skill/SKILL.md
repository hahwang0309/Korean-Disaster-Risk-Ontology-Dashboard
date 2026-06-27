---
name: disaster-risk-triples
description: "재난 관련 문서(수해백서·사고조사보고서·재난백서·사례 PDF/DOCX/TXT)에서 재난위험관리 온톨로지(위험원·노출·사건·피해·대응·맥락 16타입 + 32관계)에 맞춰 (subject, predicate, object) 트리플과 메타정보(properties)를 추출해, 재난이 어떻게 발생→전파(cascading)→피해→2차재난으로 이어지는지 예측하는 그래프 DB(JSON + Neo4j Cypher)를 만든다. 사용자가 '재난 문서에서 트리플 뽑아줘', '재난위험 온톨로지로 추출', '수해백서/사고보고서 그래프로', 'cascading 관계 추출', '재난 지식그래프', 'Neo4j 적재용 트리플'을 요청하거나, 재난 백서·사고조사보고서·재난 사례 문서를 주며 구조화·그래프화·트리플화를 원할 때 반드시 이 스킬을 사용한다."
trigger: /disaster-risk-triples
---

# 재난위험 트리플 추출 (disaster-risk-triples)

## 목적
재난 문서에서 **재난위험의 발생→발현→전파(cascading)→피해→대응** 인과 구조를 트리플로 뽑아, 다양한 문서가 하나의 그래프 DB로 합쳐지며 "이 위험요인/사건이 어떤 연쇄와 피해로 이어질지"를 예측할 수 있게 한다. 그래서 인과·연쇄 관계(TRIGGERS / CASCADES_INTO / CAUSES / AMPLIFIES)와 그 메타정보를 특히 중시한다.

온톨로지는 16개 엔티티 타입(+Other)과 32개(+PRECEDES) 관계로 고정돼 있다. 반면 **메타정보(properties) 스키마는 열려 있어** 문서를 처리할수록 점진적으로 확장되며, 전역 마스터 스키마 + 브릿지(별칭) 테이블로 일관성을 유지한다.

## 입력 / 출력
- 입력: 재난 문서 1개(PDF / DOCX / TXT). 경로와 (선택) 출력 디렉터리를 받는다. 출력 디렉터리 미지정 시 입력 파일과 같은 폴더.
- 출력:
  - `<문서명>_triples.json` — 온톨로지 준수 트리플 + 메타정보 + 해당 문서 emergent 스키마. (사람 검수·중간 산물)
  - `<문서명>.cypher` — Neo4j 적재용 MERGE 스크립트. (그래프 DB)
  - `<문서명>_dashboard.html` — 10종 인터랙티브 시각화 대시보드.
  - 전역 `data/master_property_schema.json` / `data/property_bridge_table.json` 갱신.

## 추출 밀도 모드 (호출 인자에서 파싱 — 미지정 시 저밀)
사용자 인자/요청에서 밀도 플래그를 읽어 **청크 크기(2단계)** 와 **추출 지침(3단계)** 을 함께 정한다. 플래그가 없으면 **저밀**.

| 플래그 | 청크 | 3단계 에이전트에 넣을 추출 지침(밀도 문구) |
|---|---|---|
| `--저밀`(기본, low) | ~1700줄 | "선별적 추출 — 예측 핵심인 인과·연쇄(TRIGGERS/CASCADES_INTO/CAUSES/AMPLIFIES)·주요 피해 수치·핵심 대응 위주의 백본만. 표·목록은 대표값·합계로 압축, 부차적 세부는 생략." |
| `--중밀`(medium) | ~900줄 | "균형 추출 — 백본 + 문단별 주요 사실·수치·요인. 표는 의미 있는 행 위주, 사소한 항목은 생략." |
| `--고밀`(high) | ~450줄 | "고밀도 망라 — 근거 있는 트리플을 빠짐없이. 표·목록은 항목/행 단위로 각각, 한 문단의 모든 관계를 binary로 분해. 완전 동일 의미 중복만 제외." |

(영문 `--density low|medium|high`, "고밀/중밀/저밀로", "high density" 등 자연어도 동일하게 해석.) 밀도가 높을수록 트리플↑·비용↑·엔티티 변형↑(4.5단계 해소 부담↑).

## 워크플로 (순서대로)

스킬 디렉터리를 `$SK` 로 둔다(이 파일이 있는 곳). 작업 디렉터리 `$WORK` 는 출력 디렉터리 아래 `_triples_work/` 로 만든다.

### 1. 텍스트 추출
```
python "$SK/scripts/extract_text.py" "<입력문서>" "$WORK/full.txt"
```
PDF는 poppler `pdftotext`(없으면 pypdf), DOCX는 XML 파싱. 추출 후 `full.txt` 의 앞부분을 잠깐 읽어 문서 성격(목차·표 비중 등)을 파악한다.

### 2. 청크 분할 (밀도 플래그 전달)
```
python "$SK/scripts/chunk_text.py" "$WORK/full.txt" "$WORK/chunks" [--고밀|--중밀|--저밀]
```
위 "추출 밀도 모드"에서 정한 플래그를 그대로 넘긴다(미지정=저밀). 출력 `DENSITY=..` / `CHUNKS=N` 확인 — `CHUNKS=N` 이 띄울 에이전트 수다. 밀도가 높을수록 청크가 작아져 N이 커진다(최대 40, 하니스가 ~10여 개씩 웨이브로 동시 실행).

### 3. 청크별 병렬 트리플 추출 (LLM 단계 — 이 스킬의 핵심)
청크마다 **하나의 서브에이전트**(Agent / Task 도구)를 **같은 턴에 모두 병렬**로 띄운다. 각 에이전트에 다음을 지시한다:
1. 추출 지침 `$SK/references/ontology.md` 를 읽을 것.
2. (마스터 브릿지의 canonical 키를 우선 쓰도록) `$SK/data/property_bridge_table.json` 의 키 목록을 참고할 것.
3. 자기 청크 `$WORK/chunks/chunk_NN.txt` 를 읽을 것.
4. 온톨로지를 **정확히** 지켜 트리플 + 노드/관계 properties 를 추출할 것. **이때 위 표에서 고른 밀도 문구(저/중/고밀)를 프롬프트에 그대로 명시**해 추출 범위를 맞춘다. 인과·연쇄(CASCADES_INTO 등)와 수치(death/amount+unit 등)는 어떤 밀도에서도 우선 포착.
5. 결과를 `ontology.md` 의 출력 형식 그대로 단일 JSON 객체로 `$WORK/chunks/meta_NN.json` 에 Write 할 것.
6. 한 줄 요약(트리플 수 + 경로)만 반환할 것.

**고밀도 원칙**: 각 에이전트는 자기 청크에서 근거 있는 트리플을 **빠짐없이** 뽑는다(표·목록은 항목/행 단위로, 한 문단의 가능한 모든 관계를 분해). 완전 동일 의미 중복만 피한다. 문서가 같은 사건을 여러 절에서 반복하면 청크 간 중복은 자연스럽다 — 4단계 dedup이 정리한다. (단순 연락처·일련번호·서식 잡음은 제외.)

### 4. 병합·검증·emergent 스키마
```
python "$SK/scripts/merge_validate.py" "$WORK/chunks" "<출력>/<문서명>_triples.json" \
  --glob 'meta_*.json' \
  --ontology "$SK/references/ontology_schema.json" \
  --bridge "$SK/data/property_bridge_table.json" \
  --source-doc "<문서 라벨>"
```
중복 제거 + 타입/관계 코드 검증 + 브릿지로 키 canonical화 + 문서별 emergent 스키마 산출. **WARNINGS가 0인지 확인**한다. invalid type / non-enum relation 경고가 있으면 해당 청크 출력을 고치거나(에이전트 재실행) 직접 교정한다.

### 4.5. 엔티티 해소 (Entity Resolution — 노드 분열 방지, 문서 간 병합의 핵심)
같은 실세계 개체가 표기 변형으로 갈라지면(예: `제15호 태풍 루사` / `제15호 태풍 루사(RUSA)` / `2002년 제15호 태풍 RUSA(루사)`) 노드가 분열돼 그래프가 파편화되고 **문서 간 병합**이 깨진다. 전역 **엔티티 별칭 레지스트리**(`data/entity_aliases.json`)로 노드명을 canonical 로 통일한다. properties 브릿지 테이블과 똑같은 패턴이다.

**자동 병합 강화(덜 보수적)**: dry-run/적용 시 다음을 **자동 병합**한다 — (1) 공백·전각·따옴표 차이, (2) **후행 괄호 한정자만 다른 동일타입 변형**(`화재` ↔ `화재(2008)`, `루사` ↔ `루사(RUSA)`), 단 공유 base가 충분히 특이적일 때만(generic 단어 `화재`·`정전` 단독은 제외). 연도가 **prefix**로 다른 건(`2010 산사태`≠`2011 산사태`) base가 달라 안전하게 분리 유지된다.
**이종타입 통합**: 같은 이름이 타입만 다르게 추출되면(예: `화재`가 ManmadeHazard와 Event로 갈림) dry-run이 `⚠ 동일명 이종타입`으로 보고한다. 올바른 타입으로 합치려면 해당 canonical entity에 `"merge_any_type": true` 를 넣고 다른 타입 표기를 `aliases` 에 추가한 뒤 `--write` — 노드명+타입이 그 entity로 통일된다(1차 위험원과 발현 사건이 같은 이름으로 갈린 경우 등에만 신중히 사용).

(a) **후보 탐지 (dry-run)** — 현재 레지스트리 적용 + 위 자동 병합 + 판단이 필요한 후보·이종타입 출력:
```
python "$SK/scripts/resolve_entities.py" "<출력>/<문서명>_triples.json" \
  --registry "$SK/data/entity_aliases.json"
```
(b) **Claude 확정** — 출력된 클러스터 중 **정말 같은 실세계 개체인 것만** 레지스트리 `entities` 에 `{"<canonical>": {"type":..., "aliases":[...]}}` 로 등재한다. 탐지는 토큰 중복으로 **과포함**될 수 있으니(예: 강릉시·강원도·중앙재해대책본부가 한 클러스터로 묶임) 반드시 걸러낸다. 합치면 안 되는 것: 서로 다른 기관(강릉시 ≠ 강원도 ≠ 강릉시 재해대책본부), **1차사건과 그로 인한 피해**(태풍 ≠ 태풍 인명피해), 서로 다른 위치·시점의 동명 시설. 애매하면 사용자에게 묻는다. canonical 이름은 한 번 정하면 바꾸지 말고 alias 흡수로 처리한다.
(c) **적용 (--write)** — 노드명을 canonical 로 치환하고 트리플 재중복제거:
```
python "$SK/scripts/resolve_entities.py" "<출력>/<문서명>_triples.json" \
  --registry "$SK/data/entity_aliases.json" --write
```
적용 후 노드명이 통일됐는지 확인한다. (이 단계는 문서를 거듭할수록 레지스트리가 성장해 같은 위험원·기관이 문서 전반에서 단일 노드로 모인다 — Cypher 가 `(name,type)` 로 MERGE 하므로.)

### 5. 마스터 스키마 누적 + 새 키 점검
```
python "$SK/scripts/update_master_schema.py" "<출력>/<문서명>_triples.json" \
  --master "$SK/data/master_property_schema.json" \
  --bridge "$SK/data/property_bridge_table.json" \
  --doc-id "<문서 라벨>"
```
이 문서가 새로 들여온 properties 키(canonical도 alias도 아닌 것)를 "consolidation 후보"로 출력한다.

### 6. Consolidation (새 키가 있을 때 — 점진적 스키마 정리)
5단계가 새 키를 보고하면, **Claude가 판단**해 브릿지 테이블을 갱신한다. 이게 "점진적 확장 + 주기적 정리"의 핵심이다:
- 새 키가 기존 canonical 키와 **같은 개념**이면 → 그 canonical 의 `aliases` 에 추가(예: `deaths` → `death`).
- 정말 **새로운 개념**이면 → `node_keys`/`relation_keys` 에 새 canonical 키로 등재(type·unit_hint·note 채움).
- 브릿지의 `version` 을 +1 한다.
- 정리 후 4단계(merge_validate)를 **다시 한 번** 돌려 이번 문서 트리플의 키도 최신 canonical 로 통일한다.
판단이 애매하면 사용자에게 묻는다. 브릿지는 과거 추출과 미래 추출을 같은 어휘로 잇는 "메타정보 브릿지 테이블"이므로, 한 번 정한 canonical 이름은 함부로 바꾸지 말고 alias 흡수로 처리한다.

### 7. Cypher 생성
```
python "$SK/scripts/to_cypher.py" "<출력>/<문서명>_triples.json" "<출력>/<문서명>.cypher" \
  --doc-id "<문서 라벨>"
```
노드는 `(name, type)` 로 MERGE(문서 간 같은 사건·기관·위험원이 한 노드로 합쳐짐), 축 라벨(Hazard/Event/Damage…) 부여, `sourceDocs` 로 출처 누적. 관계는 코드별 MERGE + properties + evidence. `cypher-shell < out.cypher` 또는 Neo4j Browser 붙여넣기로 적재.

### 8. 시각화 대시보드 생성
```
python "$SK/scripts/visualize.py" "<출력>/<문서명>_triples.json" "<출력>/<문서명>_dashboard.html" \
  --title "<문서 라벨>"
```
하나의 자가완결형 HTML(Plotly+D3, CDN은 SRI 고정)에 9종 시각화를 이 순서로 생성한다:
1. **Network Connectivity Map** (전체폭) — 위험원→…→피해 주요 전파 경로의 합집합, cascade 깊이 레이아웃. **링크 두께·밝기 = 통과 경로 수(트렁크)**, 노드 크기 = 통과 경로 수. 2. Entity Type Distribution · 3. Entity Type Heatmap(같은 행) · 4. Predicate Distribution · 5. Predicate Heatmap(같은 행) · 6. Sankey Diagram(전체폭) · 7. Force-directed Graph(전체폭) · 8. Centrality Ranking · 9. Community Detection(표만, 같은 행).
그래프 지표(degree·PageRank·community·경로 weight)는 스크립트가 Python에서 계산해 임베드하므로 추가 설치가 필요 없다. 각 시각화 하단에 데이터 기반 해석 문구. `--top` 으로 중심성/허브 크기 조절. 생성 후 사용자에게 경로 안내(`open <...>_dashboard.html`).

### 9. 요약 보고
사용자에게: 트리플 수, 엔티티/관계 분포, cascading 관계(CASCADES_INTO/TRIGGERS_SECONDARY) 개수, 검증 경고 0 여부, 새로 추가된 메타 키, 생성 파일 경로(JSON + Cypher + dashboard.html)를 보고한다.

## 예측 그래프를 위한 추출 우선순위
이 그래프의 쓸모는 "예측"이다. 그래서 다음을 특히 꼼꼼히:
- **연쇄 체인**: HazardSource→Event→(CASCADES_INTO)→Event→CAUSES→Damage 가 끊기지 않게. 정전·고립·통신두절 같은 상태변화는 Event(order=cascading) 단일 노드 + CASCADES_INTO 로 분기.
- **증폭 요인**: Exposure—AMPLIFIES→Damage (왜 같은 사건이 더 큰 피해가 됐는가).
- **위험요인**: RiskFactor—INCREASES_RISK_OF→Event (재발·예측의 선행지표).
- **대응 효과**: Response—MITIGATES/PREVENTS→… 의 effectiveness (어떤 대응이 통했나/실패했나).
- 관계 properties 의 `mechanism`/`probability`/`directCause`/`effectiveness` 는 예측 추론의 근거가 되므로 근거가 있으면 반드시 채운다.

## 참고 파일
- `references/ontology.md` — 추출 에이전트용 전체 지침(엔티티 정의·관계·메타정보·출력형식). 3단계에서 각 에이전트가 읽음.
- `references/ontology_schema.json` — 기계 판독용 타입·관계·enum(검증·Cypher 라벨). 4·7단계 스크립트가 읽음.
- `data/master_property_schema.json` — 전역 누적 메타 스키마.
- `data/property_bridge_table.json` — 메타정보 브릿지(별칭→canonical) 테이블.
- `data/entity_aliases.json` — 전역 엔티티 별칭 레지스트리(노드명→canonical). 4.5단계에서 사용.
- `scripts/resolve_entities.py` — 엔티티 해소(자동 탐지·병합 + Claude 확정 적용).
- `scripts/visualize.py` — 트리플 JSON → 11종 시각화 HTML 대시보드.

## 주의
- 온톨로지 16타입/32관계는 고정이다. 분류 거부 시 `Other`(+candidate 메모)만 쓴다. UNKNOWN·임의 라벨 금지.
- 발간사·인사말 등 의례 문장은 추출하지 않는다.
- 메타 스키마는 절대 미리 다 정하려 하지 말 것 — 문서가 쌓이며 자라는 게 정상이고, 정리는 6단계가 담당한다.
