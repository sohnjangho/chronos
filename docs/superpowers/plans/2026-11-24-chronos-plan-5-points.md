# 계획 5 — 관리 포인트 카드 + Liner Premium Data · Search Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 버전이 바뀔 때 관리 포인트(크리티컬 + 여유 ≤ k, w주 창)를 계산하고, 새로 들어온 포인트만 바깥 위험(날씨·자재·환율·업체)을 근거와 함께 찾아 카드로 보이고, 담당자 확인 연락 초안으로 잇는다.

**Architecture:** 계산은 `app/core/points.py`(순수 함수, 기존 CPM 값만). 버전 저장·지연 분석 뒤에 `app/points/service.py` 가 계산·저장·차이를 내고, `app/points/risk.py` 가 분야별로 켜진 바깥 자료만 부른다(날씨=기상청 `info.weather` 내부 함수, 자재·환율=Liner Search `include_knowledge:true` 의 `knowledge` 표, 업체=MCP `search_business`). 근거 문장은 `app/llm/search_agent.py`(Search Agent, 뒤에서 채움). 카드·도구·API 는 기존 지연 카드·연락 초안 흐름을 그대로 탄다.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, httpx, React 19, vitest, Playwright.

**Spec:** `docs/plans/2026-11-24-chronos-plan-5-management-points.md` (지시서) + 진행 기록 `.superpowers/sdd/2026-11-24-chronos-plan-5-points/progress.md`(PM 결정·0단계 실측).

## Global Constraints

- 0단계 실측(11-24): Premium Data 날씨는 앞으로 약 23시간 시간별뿐 → **날씨는 기상청**(3일 안 = 예보, 그 뒤 = 그달 지난 n년 통계 `history`). Premium Data 는 **금속·원자재**(The World Bank 월별: 구리·알루미늄·철광석, USD/톤)와 **환율**(Xignite 지금 값)만. 국내 철근 단가·시멘트(한국) 없음.
- **PM 결정: 바깥 자료 네 갈래(weather·materials·fx·business)를 분야(schedule.domain)별로 켜고 끈다.** 기본값: construction 넷 다 켬, manufacturing weather 끔·나머지 켬, 그 밖의 분야 business 만 켬. 개발 콘솔에서 바꿀 수 있다.
- 설정값은 상수로 박지 않는다(settings 표, `app/store/settings.py` 의 `_INT_BOUNDS` 꼴): `points_tf_days` k (0~10, 기본 3) · `points_window_weeks` w (1~8, 기본 3) · `points_max_new` (1~10, 기본 5) · `points_forecast_reuse_hours` (1~48, 기본 6) · `points_sources` (분야 → 켜진 갈래 목록, JSON).
- 날짜·여유·자원은 코드만 계산. Liner 숫자는 표시·근거로만, 일정 반영은 [조건으로 넣어 보기] → 승인함으로만. 자동 발송 없음.
- 숫자를 지어내지 않는다: 값이 없으면 「바깥 자료 없음」, 숫자 없이.
- PM 포트 8210·5600·6333 과 `data/` 를 건드리지 않는다. 시험은 가짜 Liner·가짜 기상청. 실제 Liner 는 마지막 Task 의 시연 한 번만(격리 복사본).
- 키·전화번호는 기록·로그·trace·응답에 없다. 커밋마다 `scripts/check_secrets.sh` → `git push origin feature/plan-1`.
- 화면은 만들기 전 시안 1개를 PM 에게(Task 6 앞).
- 줄일 순서(지시서 끝): 공정률 위젯 → 개발 콘솔 설정 편집 → 만회안의 Search Agent 근거 → 업체 검색.

## Review Focus

1. 끝난 액티비티(actual_finish 있음)·마일스톤·창 밖(ES > DD + w주)은 포인트가 아니다 — 한 일정이 모두 끝났으면 포인트 0, 카드 없음.
2. 첫 버전(앞 버전 없음)은 「바뀜」이 아니라 「처음 계산」으로 — 카드는 내지 않고 포인트만 남긴다.
3. 현장 주소가 비었거나 기상청 지점에 없는 주소 → 날씨 줄 「현장 주소가 없어(또는 지점을 몰라) 날씨를 보지 않음」, 다른 갈래는 그대로.
4. Liner 가 `knowledge` 를 안 주거나 값이 숫자가 아님 → 그 줄만 「바깥 자료 없음」, 카드 전체는 뜬다.
5. Search Agent 의 HTTP 200 안 `data-error`·시간 초과 → 「근거 문장을 찾지 못했습니다」로 끝나고 카드·대화는 막히지 않는다.

---

### Task 1: 관리 포인트 계산·저장·차이 + 설정값

**Files:**
- Create: `backend/app/core/points.py`, `backend/app/points/__init__.py`, `backend/app/points/service.py`, `backend/app/store/points.py`
- Modify: `backend/app/store/settings.py` (설정 다섯), `backend/app/db.py` (표 등록), `backend/app/store/versions.py` (`_save` 뒤 훅), delay 분석 서비스(지연 분석이 끝난 곳 — `app/programs/delays`)
- Test: `backend/tests/core/test_points.py`, `backend/tests/points/test_points_service.py`

**Interfaces:**
- Produces: `Point(activity_id: str, name: str, critical: bool, tf: int, es: date, ef: date)`; `compute_points(schedule: Schedule, cpm: CpmResult, *, tf_days: int, window_weeks: int) -> tuple[Point, ...]` (ES 순); `PointsDiff(added: tuple[Point,...], removed: tuple[str,...], tightened: tuple[tuple[str,int,int],...])` (id, 앞 tf, 뒤 tf); `diff_points(prev: tuple[Point,...] | None, cur) -> PointsDiff | None` (prev None → None); `service.refresh(session, schedule_id, version) -> PointsDiff | None` (계산·표에 저장·차이); `store.points.get(session, schedule_id, version) -> tuple[Point,...] | None`; settings `points_config(session) -> PointsConfig(tf_days, window_weeks, max_new, forecast_reuse_hours, sources: dict[str, list[str]])`, `sources_for(session, domain) -> set[str]`.

- [ ] Step 1: 실패 시험 — `test_critical_and_near_critical_in_window`(TF 0·2·3·4, k=3 → 0·2·3 만), `test_finished_and_milestones_excluded`, `test_window_cuts_by_es`(DD + w주 넘는 ES 제외, 진행 중은 포함), `test_diff_added_removed_tightened`, `test_first_version_diff_is_none`, `test_all_finished_gives_no_points`, settings 경계(범위 밖 → 기본값), `sources_for("construction")=={"weather","materials","fx","business"}`, `sources_for("manufacturing")` 에 weather 없음, 모르는 분야 `{"business"}`.
- [ ] Step 2: 실패 확인 `cd backend && .venv/bin/python -m pytest tests/core/test_points.py tests/points -q` → FAIL(모듈 없음)
- [ ] Step 3: 구현 — 날짜·tf 는 `cpm.compute` 행 그대로(지연 분석과 같은 평준화 값을 쓰려면 `delay._measure` 처럼 `level(...).cpm`), 창은 `calendar` 의 근무일이 아니라 달력 주. 표 `management_points(schedule_id, version, points_json, computed_at)` 기본키 (schedule_id, version). 훅은 저장 트랜잭션을 깨지 않게(계산 실패는 로그만).
- [ ] Step 4: 통과 확인 + `tests/store tests/programs/delays` 이웃
- [ ] Step 5: 커밋 `feat: 관리 포인트 — 크리티컬·여유 k 일 이하·w 주 창, 버전마다 계산하고 앞 버전과 견줌`

### Task 2: 시연 짝 찾기 (씨앗 「5층 사무동 신축」)

**Files:** Create `backend/scripts/find_demo_pair.py`; Modify `docs/demo/시나리오.md`
**Interfaces:** Consumes Task 1 `compute_points`, `delay.analyze`.
- [ ] Step 1: 씨앗을 임시 DB 에 만들고(`app.seed`, 임시 CHRONOS_DATA_DIR), 끝나지 않은 task 마다 3일 지연을 `delay.analyze` 로 넣어 (finish_delta, critical_added, 포인트 차이) 를 표로 낸다. 실외 작업(WBS·이름에 타설·골조·외벽·방수·토공 등) 표시.
- [ ] Step 2: 짝 고르기 — A: finish_delta 0·포인트 그대로, B: 포인트가 바뀌고(새 크리티컬) 실외 작업. 둘 다 같은 3일, 같은 공종이면 더 좋음. 없으면 씨앗을 고치지 말고 보고.
- [ ] Step 3: `docs/demo/시나리오.md` 에 「관리 포인트 장면」 절: 두 ID·이름·여유·결과 숫자(스크립트 출력 그대로)·시연 순서.
- [ ] Step 4: 커밋 `docs: 시연 — 같은 3일 지연, 다른 영향(관리 포인트 장면 짝)`

### Task 3: 바깥 위험 겨냥 검색 (분야별 갈래)

**Files:** Create `backend/app/points/risk.py`, `backend/app/llm/knowledge.py`; Modify `backend/app/llm/search.py` (knowledge 켠 부르기 함수 하나), `backend/app/store/evidence.py`(mode `knowledge` 기록, 재사용 시간 검사); Test `backend/tests/points/test_risk.py`, `backend/tests/llm/test_knowledge.py`
**Interfaces:**
- Consumes: Task 1 `Point`, `PointsConfig`, `sources_for`; 기존 `info.weather` 내부(기상청 예보·통계 — 도구 함수가 아니라 그 안의 조회 함수를 부른다), `mcp_client.call_tool(... "search_business" ...)`, project profile 의 주소(`programs/projects`).
- Produces: `Risk(activity_id: str, kind: Literal["weather","materials","fx","business"], line: str, evidence_id: int | None, as_of: str | None, source: str | None, status: Literal["ok","none","skipped"])`; `async look(session, schedule_id: int, version: int, points: Sequence[Point]) -> list[Risk]` (새 포인트 앞에서 `max_new` 개만); `knowledge.read(resp: dict) -> list[KnowledgeTable]`, `KnowledgeTable(title, source, as_of, columns, rows)`; `knowledge.trend(table, months=3) -> tuple[float, float, float] | None`(앞 값·뒤 값·%).
- [ ] Step 1: 실패 시험 — 분야 꺼진 갈래는 부르지 않음(가짜가 호출 0 확인), LLM(light, 가짜)이 고른 `weather_sensitive`·`materials`(["copper","aluminum","iron ore"] 중에서만)·`imported`, 날씨: ES 가 3일 안 → 예보 줄 / 뒤 → 「{월} 지난 n년 강수일 평균」 줄 / 주소 없음·지점 모름 → skipped, 자재: `knowledge` 있음 → 「구리 3개월 +8.2% (The World Bank, 2026-10)」, 없음·숫자 아님 → none, 환율: 지금 값 한 줄, 업체: MCP 결과 첫 줄, 재사용: 같은 질의 6시간 안이면 다시 부르지 않음·지나면 부름, 근거 표에 출처와 함께 남음.
- [ ] Step 2: 실패 확인 → Step 3: 구현(질의는 영어 고정 꼴 `"{commodity} price"`, `"USD KRW exchange rate"`; `include_knowledge: True` + `country_code`·`lang` 은 보내지 않음) → Step 4: 통과 + `tests/llm tests/tools/data` 이웃 → Step 5: 커밋 `feat: 관리 포인트 바깥 위험 — 분야별 날씨(기상청)·자재·환율(Premium Data)·업체(MCP)`

### Task 4: Search Agent 근거 문장 (뒤에서 채움)

**Files:** Create `backend/app/llm/search_agent.py`, `backend/app/points/quotes.py`; Test `backend/tests/llm/test_search_agent.py`, `backend/tests/points/test_quotes.py`
**Interfaces:**
- Produces: `AgentQuote(text: str, url: str, title: str)`; `async ask(session, question: str, *, mode: Literal["general","scholar"]="general", timeout: float = 300) -> list[AgentQuote]` (`POST {base}/agents/search`, `stream:false`; `data-error` 가 있으면 `SearchAgentFailed(code)`; 답 본문은 버리고 `referenceChunks` 의 문장과 링크만); `quotes.fill(schedule_id, version, activity_id, kind)` 백그라운드(상태 `pending|ready|failed`, 표 `point_quotes`), `quotes.get(...)`.
- [ ] Step 1: 실패 시험 — 성공(문장·링크), 200 안 `data-error` → failed, 시간 초과 → failed, `[DONE]` 만 있고 chunk 없음 → failed(빈 성공 아님), 키가 오류 글에 없음, 비용 기록(llm_calls purpose `search_agent`).
- [ ] Step 2~4: 실패 확인 → 구현 → 통과 → Step 5: 커밋 `feat: Search Agent — 관리 포인트 위험의 출처 문장을 뒤에서 채움`

### Task 5: 카드·도구·API·연락 잇기 (서버)

**Files:** Create `backend/app/tools/points/check.py`(`points.check`), `backend/app/programs/points/router.py`; Modify 에이전트 지침(`app/agent/prompts/system.md` 한 줄), 카드 이벤트(지연 카드 내는 곳과 같은 꼴), `programs/attention`(포인트 수·바뀜); Test `backend/tests/points/test_points_api.py`, `backend/tests/tools/test_points_check.py`
**Interfaces:**
- Consumes: Task 1 `service.refresh`, `store.points.get`; Task 3 `look`; Task 4 `quotes`.
- Produces: `GET /api/schedules/{id}/points` → `{version, points[], diff, risks[], quotes{}}`; `POST /api/schedules/{id}/points/{activity_id}/contact` → 기존 `notify.draft_message`/`draft_call` 초안(받는 사람은 그 액티비티 담당 협력사 연락처에서 사람이 고름, 질문에 포인트·위험 한 줄); 카드 이벤트 kind `points_changed` (data: schedule_id, version, added, removed, tightened, risks, quotes 상태).
- [ ] Step 1: 실패 시험 — 현장 관리자 403(연락)·읽기 허용 여부는 기존 일정 읽기 권한과 같게, 카드는 diff 가 있을 때만, 연락 초안이 시험 모드·허용 번호·근무시간 하네스를 그대로 거침(가짜 통로), 번호가 응답·카드에 없음, `points.check` 출력에 날짜·여유는 코드 값만.
- [ ] Step 2~4 → Step 5: 커밋 `feat: 관리 포인트 카드·도구·API — 담당자 확인 연락 초안으로`

### Task 6: 화면 — 카드·주의할 일정 (시안 승인 뒤)

**Files:** Create `frontend/src/programs/chat/cards/PointsChangedCard.tsx` (+ test); Modify 카드 등록부, `frontend/src/programs/attention/*`; Test vitest + `frontend/e2e/points.spec.ts`(가짜)
- [ ] Step 0: 시안 — `DelayImpactCard` 꼴을 따른 정적 HTML 1개, FHD 밝게·어둡게 → PM 승인(컨트롤러가 받음).
- [ ] Step 1: 실패 시험 — 새 포인트 줄(여유 n→m·크리티컬 표시), 위험 줄(출처·기준 시각), [근거 문장 보기]: pending → 「근거 문장 찾는 중」, ready → 문장·링크, failed → 「찾지 못했습니다」, [담당자에게 확인 연락] → 연락처 고르기 → 초안, [조건으로 넣어 보기]는 날씨 줄에만, 넘침 없음.
- [ ] Step 2~4 → Step 5: FHD 사진(밝게·어둡게·1280×800) `shots/task-p5-card/` → 커밋 `feat: 관리 포인트 카드 화면 — 근거 문장·담당자 확인 연락`

### Task 7: 개발 콘솔 — 추적·설정

**Files:** Modify `frontend/src/programs/devconsole/HarnessTab.tsx`(설정 다섯 + 분야별 갈래 표), 실행 추적(단계 「관리 포인트」: 계산 → 겨냥 검색 n → Search Agent n, 비용 종류), 백엔드 설정 API(`programs/devconsole`)
- [ ] Step 1~4: 실패 시험(설정 저장·범위·분야 표 저장, 추적 단계 표시) → 구현 → 통과
- [ ] Step 5: 커밋 `feat: 개발 콘솔 — 관리 포인트 추적·설정(분야별 바깥 자료)`

### Task 8: 실제 Liner 로 시연 한 번 (격리)

- [ ] Step 1: 격리 복사본(임시 data, 빈 포트, worker off, `CHRONOS_QDRANT_URL=""`, 실제 Liner 키는 컨트롤러가 임시 DB 에 넣음)에서 Task 2 짝으로 장면을 끝까지: 3일 지연 A → 영향 0 / B → 카드 → 위험 줄 → [근거 문장 보기] → [담당자에게 확인 연락] 초안까지(실제 발송 없음).
- [ ] Step 2: FHD 사진·호출 수·비용을 진행 기록에, 기획서 메모(붙인 Liner 기능·실측·한계) `docs/contest/` 에.

---

## 추가 (지시서 「F·G」, PM 승인 11-24, 커밋 9838626)

### Task 9: 당김 효과 확인 (F — 꼭)

**Files:** Create `backend/app/core/accel.py`, `backend/app/tools/points/accel_check.py`; Modify 만회안 카드 데이터(`app/tools/respond/make_shortening.py` 결과에 칸 둘), 비교판 요약 서버 쪽, settings(`accel_warn_ratio` 0.1~1.0 기본 0.5), 에이전트 지침 한 줄; Test `backend/tests/core/test_accel.py`, `backend/tests/tools/test_accel_check.py`
**Interfaces:**
- Consumes: `core.shorten.apply_moves(schedule, moves)`, `Move`, `core.resources.level`, `core.cpm.compute`; Task 1 `compute_points`(다음 줄 액티비티가 포인트인지).
- Produces: `AccelResult(pulled_days: int, finish_before: date, finish_after: date, finish_gain: int, ratio: float, warn: bool, next_chain: tuple[str, ...], next_chain_points: tuple[str, ...], same_chain: bool)`; `accel_effect(schedule: Schedule, moves: Sequence[Move], *, warn_ratio: float, tf_days: int, window_weeks: int) -> AccelResult` (pulled_days = 묶음이 줄인 기간 합 — compress 는 od 차, parallel 은 넣기 전 크리티컬에서 그 관계로 당겨진 일수, add_resource 는 0 으로 세고 finish_gain 만 본다); `pull_request(schedule, activity_id: str, days: int) -> Sequence[Move]` (od − days, 최소 1, 실적 있으면 `AccelRefused`); `next_chain` = 넣은 뒤 크리티컬 패스(위상 순) 가운데 묶음이 건드리지 않은 액티비티; 넣기 전 크리티컬과 같으면 `same_chain=True`.
- [ ] Step 1: 실패 시험 — 크리티컬 하나만 당김 → finish_gain == pulled / 병렬 경로가 곧 막음 → 일부만·warn / 자원 맞춤에 막힘 / 실적 있는 액티비티 거절 / 비율 경계(== warn_ratio 는 경고 안 함) / same_chain.
- [ ] Step 2~4: 실패 확인 → 구현(날짜·크리티컬은 엔진 값만, `level(..., shift=True)`) → 통과
- [ ] Step 5: 도구 `points.accel_check(activity_id, days)` + 카드 데이터 kind `accel_check`; 만회안 묶음 A·B 결과에 `finish_gain/pulled_days`·`next_chain` 칸, 비교판 요약에도. 커밋 `feat: 당김 효과 확인 — 당긴 일수 중 준공 반영·다음 결정 줄(만회안·비교판·도구)`

### Task 9b: F 시연 짝 (Task 2 스크립트 넓히기)
- [ ] 골조 계열 액티비티마다 n=1~5 당김 × (finish_gain, next_chain) 표. 「골조를 당겨도 준공이 거의 안 당겨지고 다음 줄이 커튼월·외장」 경우를 찾아 `docs/demo/시나리오.md` 에. 씨앗을 고치지 않는다. 없으면 보고.

### Task 10: 준비 상태 점검 요청 (G — 여유가 되면)
- 카드 단추 [준비 상태 확인 요청](시작이 DD 부터 `points_ready_days` 근무일 안, 기본 10) → 기존 D-3 핸드오프 점검 항목 생성 + Task 5 연락 초안 길. 사람이 누를 때만.

### Task 6 덧붙임
- 시안 문구는 분야 중립(「프로젝트 주소」「담당」), 건설 일정에서만 「실외 작업」. 카드 하이라이트는 자재(커튼월 알루미늄)·환율·업체 소식, 날씨는 기능으로만(PM 11-24). F 카드(당김 효과) 시안을 함께.
