# 재난위험관리 온톨로지 — 트리플 추출 지침

목적: 다양한 재난 문서에서 **재난위험이 어떻게 발생(Hazard)→발현(Event)→전파(Cascading)→피해(Damage)로 이어지고, 대응(Response)이 이를 어떻게 바꾸는지**를 (subject, predicate, object) 트리플로 추출해 예측용 그래프 DB를 만든다. 따라서 인과·연쇄(TRIGGERS / CASCADES_INTO / CAUSES / AMPLIFIES)와 그 메타정보를 특히 빠짐없이 잡는다.

각 엔티티는 아래 16개 타입 중 하나로 분류한다. 맞지 않으면 `Other` + properties 첫 키 `candidate`에 `[후보: A, B / 이유: ...]` 메모. UNKNOWN·#·임의 라벨 금지.

## 엔티티 타입 (16 + Other)
[위험원 Hazard]
- **NaturalHazard**: 자연현상 위해(태풍·집중호우·산사태·강풍·해일·지진·폭염·감염병). properties.origin 필수(meteorological/geological/hydrological/biological/climatological).
- **ManmadeHazard**: 인간 행위·기술 위해(용접불꽃·과적·군중밀집·배터리발화·방화). properties.origin 필수(fire/explosion/structural/chemical/transport/infra_failure/crowd/cyber).
- **RiskFactor**: 사건 확률·강도를 높이는 잠재 조건(노후 제방·산사태 다발지·유목·지하 밀폐구조·단선운행·고령화). 세 조건 모두 충족: (1)발현된 사건·피해 아님 (2)시설·인구·지역 자체 아님 (3)확률을 높이는 성질. properties.nature 권장(latent/emerging/recurring/unquantified).

[노출 Exposure]
- **Region**: 위해에 노출된 지리적 범위(강릉시·강원도·OO동). properties.scope 권장(macro/meso/micro).
- **Facility**: 위해에 노출된 시설·인프라·교통수단(도로·교량·제방·하천·농경지·상수도·통신시설·주택·지하주차장·여객선).
- **Population**: 위해에 노출된 인구·집단(이재민·주민·관광객·승객·근로자). 실제 사망·부상 **수치는 Damage로 분리**.

[사건 Event]
- **Event**: 위해가 발현된 현상(태풍 상륙·집중호우·하천 범람·침수·산사태 발생·화재 확산·정전·고립·침몰·압사). properties.order 필수(primary/secondary/cascading/nth). 상태변화(정전·붕괴·고립·통신두절)는 order=cascading + subtype=state_change.

[피해 Damage]
- **Damage**: 사건의 부정적 결과. properties.category 필수(human/property/service/economic/infra/environmental). 피해유형+수치 불가분 결합은 Damage 단일 추출 + properties에 수치(death/injury/missing/amount/count + unit).

[대응 Response]
- **ResponseAction**: 예방·완화·대응·복구 조치(긴급대피·가두방송·인명구조·이재민구호·제방복구·119신고·진압). properties.phase 필수(prevention/mitigation/preparedness/response/recovery).
- **ResponseActor**: 대응 주체(강릉시·시장·중앙재난안전대책본부·소방서·해경·군부대·자원봉사자). 복합어 "행안부 장관"→ResponseActor + properties.affiliation 메모.
- **Resilience**: 흡수·완충·회복 역량 **명사구**(이중화 회선·비상계획·여유자원·다중 공급망). 술어 단독("잘 견뎌냈다") 추출 금지 → 관계 BUILDS로만. properties.kind 권장(absorbing/buffering/recovery).

[맥락 Context]
- **Context**: 일시·위치·기상·정량기준(2002-08-31·1일 강수량 870.5mm·풍속 33m/s·맹골수도). properties.subkind 권장(DateTime/Location/Weather/Metric/Threshold).

[기타]
- **Other**: 위 16개 미해당. properties.candidate에 `[후보: A, B / 이유: ...]` 강제.

### 핵심 분류 규칙
1. 발현 전 잠재 조건 → Hazard/RiskFactor, 발현된 현상 → Event, 결과 → Damage
2. 노출 단계 인구·시설 → Exposure, 실제 피해 수치 → Damage
3. 대응 행위 → ResponseAction, 대응 주체 → ResponseActor, 역량 → Resilience
4. 날짜·기상·정량기준 → Context (Event properties에 dateTime/intensity로 넣되, 단독 기준점은 Context 노드)
5. 피해유형+수치 불가분 결합 → Damage 단일 추출 + 수치 메모
6. Hazard·Event에 disasterType 권장(natural_storm/natural_landslide/social_fire 등)

## 관계 타입 (predicate.code, 32종 — 가장 가까운 코드)
- Hazard→Event/Exposure: TRIGGERS AFFECTS INCREASES_RISK_OF PRECONDITIONS
- Hazard→Hazard: COMPOUNDS DERIVES_FROM
- **Event→Event(동일 청크 양쪽 명시 필수): CASCADES_INTO TRIGGERS_SECONDARY CONCURRENT_WITH** ← 연쇄 예측의 핵심, 적극 추출
- Event→Damage: CAUSES
- Exposure→Damage: AMPLIFIES
- Exposure→Resilience/Context: HAS_RESILIENCE LOCATED_IN
- Hazard/Event→Context: OCCURS_AT UNDER_CONDITION
- Response→Hazard/Event/Damage: PREVENTS MODIFIES_RISK_OF MITIGATES RESPONDS_TO
- Response→Resilience: BUILDS
- Resilience→Damage: OFFSETS
- ResponseActor→Response: PERFORMS FAILS
- ResponseActor→ResponseActor: COMMANDS COORDINATES_WITH BELONGS_TO
- ResponseActor→Context: DEPLOYED_TO
- Damage→Context: QUANTIFIED_BY
- Response→Object(매뉴얼): GUIDED_BY
enum 외 모호 케이스는 predicate.code에 자유 기술 + properties.note에 의미 1문장.
인과 방향 고정: CASCADES_INTO·TRIGGERS는 선행→후행 단방향.

## 메타정보(properties) — 매우 중요, 스키마는 열려 있음
노드·관계 모두 자유 형태 `properties`를 함께 추출한다. **메타정보 스키마는 고정돼 있지 않다.** 본문 근거가 있으면 어떤 키든 신설해 점진적으로 확장한다. 근거 없는 값은 만들지 않는다(빈 객체 `{}` 허용).

- 노드 properties: enum 속성(origin/order/category/phase/scope/nature/subkind/kind/disasterType) 우선 + 서술 메타. 자주 쓰는 키(한정 아님): `dateTime` `location` `mechanism` `cause` `feature` `scale` `intensity` `consequence` `death` `injury` `missing` `displaced` `amount` `area` `count` `unit` `actor` `affiliation` `duration`.
- 관계 properties: 그 인과/연쇄의 양상. 자주 쓰는 키(한정 아님): `role` `scale` `probability`(High/Med/Low) `directCause` `mechanism` `reason` `effectiveness`(High/Med/Low) `spreadRisk` `specialNote` `timing` `phase`.
- 수치는 가능하면 숫자값 + 별도 `unit` 키로 분리(예: `"amount": 913999, "unit": "백만원"`). 어려우면 문자열.
- 가능하면 master 브릿지 테이블의 **canonical 키**를 우선 사용(있을 경우 별도 안내됨). 새 개념이면 새 키를 만들어도 된다 — 정리는 후속 consolidation 단계에서 한다.

## 출력 형식 (JSON 객체 하나만, 코드펜스·설명 금지)
{
  "triples": [
    {
      "subject": {"name": "2002년 태풍 루사(RUSA)", "type": "NaturalHazard",
                  "properties": {"origin": "meteorological", "disasterType": "natural_storm", "landfallDateTime": "2002-08-31 15:30"}},
      "predicate": {"code": "TRIGGERS",
                    "properties": {"scale": "대형", "probability": "High", "mechanism": "집중호우 유발"}},
      "object": {"name": "강릉지방 집중호우(2002)", "type": "Event",
                 "properties": {"order": "primary", "dateTime": "2002-08-31", "intensity": "1일 강수량 870.5mm", "location": "강릉"}},
      "evidence": "원문 근거 문장(짧게 인용)"
    }
  ]
}

규칙:
- **노드 명명 일관성(중요 — 엔티티 분열 방지)**: 같은 실세계 개체는 청크 전체에서 **동일한 정식 명칭**으로 표기한다. 약칭·영문·괄호 병기로 표기가 흔들리지 않게, 가장 완전한 형태를 name 으로 쓰고(예: `2002년 제15호 태풍 루사(RUSA)`), 다른 표기(루사, RUSA, 태풍 루사)는 properties.alias 에 모은다. `(전국)`·`(강릉)` 같은 범위 한정은 name 에 넣지 말고 properties.scope/location 으로 분리한다. 1차 위험원/사건과 그로 인한 피해는 **서로 다른 노드**다(예: 태풍 루사 ≠ 강릉시 루사 인명피해).
- predicate는 반드시 `{"code": <관계코드>, "properties": {...}}` 형태. 노드는 `{"name","type","properties"}`.
- 트리플마다 evidence에 원문 근거를 짧게 인용한다.
- **추출 밀도는 호출 시 지정된 모드(저밀/중밀/고밀)를 따른다** — 구체 지침은 이 프롬프트와 함께 주어진다. 미지정 기본은 저밀(선별적: 인과·연쇄·핵심 피해/대응 백본 위주). 어떤 모드든 **완전히 동일한 의미의 중복**만 피하고(같은 사실의 재진술), 같은 노드라도 다른 관계·다른 수치면 별개 트리플이다.
- 추출하지 않는 것(모든 모드 공통): 발간사·인사말 등 의례 문장, 단순 연락처·일련번호·서식 잡음.
- 반드시 위 JSON 객체 하나만 출력.
