# ChronOS 계획 2 — 묶음 2 (변화 대응) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실적을 넣으면 공정률·S-커브·CPM 이 움직이고, 지연을 말하면 영향(준공·여유 흡수·크리티컬·자원·비용)이 계산되어 지연 기록에 쌓이며, 에이전트가 규칙으로 만든 만회안(만약에 복사본)을 비교판에서 골라 승인하면 일정이 바뀐다. 근거 검색(Liner Search)·내 규칙·개발 콘솔(에이전트 구조·실행 추적·사용량)·생산 분야까지 — 설계 18장 묶음 2 전부.

**Architecture:** 계획 1 구조 위에 순수 계산 셋(`core/delay.py` 지연 넣기·영향, `core/shorten.py` 단축안, `core/progress.py` 공정률)을 더한다. 일정을 바꾸는 제안은 모두 `app/agent/proposals.propose()` 하나로 승인 기준(`assess`·`approval_mode`)을 거친다. 만약에 복사본(`scenarios`)은 저장된 일정과 따로 있다가 반영할 때만 승인으로 들어간다. 지연 사건은 '열림(아직 일정에 없음)'과 '반영됨' 두 상태라 두 번 세지 않는다. LLM 은 단축안을 고르고 설명만 하고, 날짜·여유·영향·공정률은 코드가 계산한다.

**Tech Stack:** 계획 1과 같다(새 의존성 없음). 네트워크 그림·S-커브·구조도는 SVG 로 직접 그린다. Liner Search API 는 httpx 로 `POST {base_url}/tools/search/web|scholar`(`x-api-key`).

**Spec:** `docs/design/2026-11-19-ChronOS-설계.md` (v2.4) 7·8(8-3 CPM·8-4 진행·8-5 실적)·9·10·12·13·16·17·18 장. 화면 시안(확정본, 숫자는 예시): `docs/design/mockups/{ScheduleCPM,ScheduleProgress,Delay,Compare,DevConsoleA}.dc.html`. CPM 형태 참고(그림만): `~/schedule-management/frontend/e2e/screens/CPM-1920.png`. 실측: `docs/dev-journal/2026-11.md`(Liner 는 `usage.cost` 를 보내지 않는다).

**이 계획의 범위:** 묶음 2. Task 번호는 계획 1에 이어 21부터. 시작 조건: 계획 1 Task 16~19 커밋(작업마다 "선행" 줄). 묶음 3·4 로 넘기는 것은 맨 끝 대응표.

## 병렬 묶음과 일정

같은 묶음(G)의 작업은 서로 다른 파일만 건드리므로 동시에 돌려도 된다. 뒤 묶음은 앞 묶음이 모두 커밋된 뒤 시작한다. 구현자 2~3명 기준.

| 묶음 | 작업 | 언제 |
|---|---|---|
| G1 | 21 자료 넓히기 · 22 지연 영향 계산 · 23 단축안 계산 · 24 공정률 계산·진행 API · 25 화면 자리 | 11-21 오전~오후 |
| G2 | 26 변경 제안 공통화·만약에 복사본 · 27 근거 검색 · 28 생산 분야 묶음 · 29 실행 추적·개발 콘솔 API | 11-21 오후~밤 |
| G3 | 30 실적 입력 · 31 CPM 탭 · 32 진행 탭 · 33 지연 기록 API·도구 · 34 단축안 도구·비교 API · 35 내 규칙 | 11-22 |
| G4 | 36 지연 기록 화면 · 37 비교판 화면 · 38 개발 콘솔 화면 · 39 대화 카드 · 40 생산 분야 표시·예시 자료 · 41 주의할 일정 위젯 → **42 끝에서 끝까지**(36~41 뒤) | 11-22 밤~11-23 |
| ◆ | Checkpoint C — 실제 Liner 로 묶음 2 시연 흐름 | 11-23 밤 |


> **[PM 결정 11-20] 일정판 탭 → 도구 프로그램 넷.** 스케줄표·간트·CPM·공정률(옛 「진행」)은 각각의 프로그램(`schedule-table`·`gantt`·`cpm`·`progress`)이다(계획 1 Task 16b). 이 계획에서 「CPM 탭」「진행 탭」이라 적은 것은 `cpm`·`progress` 프로그램의 화면을 뜻하고, 일정 공유 코드는 `frontend/src/shared/schedule/` 에서 가져온다. Task 25 의 「탭 연결」은 「프로그램 등록(자리표시 바꾸기)」으로 읽는다.


> **[PM 결정 11-20] 「Plan」 = 지금 일정(실적 없이 계산).** 화면의 날짜는 Plan 과 Actual 두 벌뿐이다. Plan 은 지금 버전을 실적 없이 계산한 일정이라, 직접 고치거나 변경을 승인하면 바뀐다. 처음 계획은 버전 기록·비교판에서 본다. 그래서 「만회안 승인 때 Plan 다시 잡기」 체크(`reset_plan`)는 쓰지 않는다(칸은 남겨 둠) — 이 계획에서 그것을 다루는 단계는 건너뛴다.

## Global Constraints

계획 1의 제약을 그대로 잇는다.

- 화면 글자는 전부 한국어. 코드 식별자·경로·명령은 영어.
- 기준 해상도 FHD 1920×1080. 좁은 화면 대응은 하지 않는다.
- **LLM이 날짜를 계산하지 않는다.** 날짜·여유·자원 겹침·조건 통과·지연 영향·공정률은 `app/core`, `app/harness` 코드만 계산한다. LLM 이 낸 글에 날짜가 들어 있으면 버린다(Task 34).
- 점검하지 않은 조건을 통과로 표시하지 않는다. `checkable=False` 조건은 "자동 점검 안 됨"으로만 표시한다.
- 비밀값: API 키는 화면에서만 입력받아 Fernet 으로 암호화해 DB 에 넣는다. 응답에는 끝 4자리만. `.env`·`data/`·DB 파일은 커밋하지 않는다. 로그·추적 기록(`trace_events`)·근거 기록에 키를 남기지 않는다. **근거 검색도 같은 키**: 기본 LLM 연결(provider `liner`)의 키를 서버에서 풀어 `x-api-key` 헤더로만 보낸다.
- 다른 회사 LLM API 를 직접 부르지 않는다. 기본 연결은 Liner(`https://platform.liner.com/api/v1`).
- 예시 자료는 전부 가상. 기존 저장소(`~/schedule-management`, 미니PC `~/project-platform`) 코드와 `@sohnjangho/agent-ux-*` 패키지를 복사·설치하지 않는다(형태만 참고).
- 모듈 규칙: `app/core`는 DB·LLM·FastAPI 를 import 하지 않는다. `app/programs/<a>`는 `app/programs/<b>`를 import 하지 않는다. 에이전트는 도구를 `app/tools/registry`로만 부른다. 화면의 `src/programs/<a>`는 `src/programs/<b>`를 import 하지 않는다 — 다른 프로그램은 `useWindows.getState().open(id, params)` 로만 연다.
- 파일 길이: 화면 파일 권장 300줄·상한 600줄, 서버 파일 권장 400줄·상한 800줄, 함수 권장 50줄·상한 100줄. 시험·자동 생성·자료 파일 제외. `scripts/check.sh`가 검사한다.
- 색·글꼴 값은 `frontend/src/os/tokens.css`의 변수만 쓴다(밝은·어두운 테마 둘 다 있음).
- 포트: 서버 8210, 화면 5600. 둘 다 `0.0.0.0`.
- 검증은 Docker 안에서: `docker compose run --rm backend pytest -q`, `docker compose run --rm frontend npm test`. 끝났다고 말하기 전에 `bash scripts/check.sh` 전체가 통과해야 한다.
- 작업 등급: 각 Task 제목의 `[fable]` `[opus]` `[sonnet]`. **`[fable]` 은 Fable 한도 해제(11-23 13:00 KST) 전에는 opus + effort xhigh 로 보낸다**(계획 1 판단).
- git: 한 브랜치 `feature/plan-2`(main 에서 따되 계획 1 이 아직 병합 전이면 `feature/plan-1` 위), 작업마다 커밋. 같은 묶음 작업이 동시에 돌므로 **자기 파일만 경로로 stage** 하고, `index.lock` 이면 기다렸다 다시 한다. PR 과 `~/reports/pr_YYYYMMDD_HHMM.md` 보고서(요약·diff 경로·영향 grep·Docker 시험 로그·검토 요청)는 Checkpoint C 에서. main 병합은 PM 확인 뒤.
- **파일 경계:** 작업의 Files 목록 밖 파일을 고쳐야 하면 멈추고 NEEDS_CONTEXT 로 묻는다(같은 묶음의 다른 작업과 겹치지 않게).
- 계획 1 Task 16~19 의 이름(`useSchedule`·`shared/gantt/*`·`useSchedulePreview`·조건 API 모양·`ApprovalDetail` 등)은 그 작업 보고서의 "최종 인터페이스"로 확인한다. 이 계획의 글과 다르면 보고서를 따르고 보고서에 적는다.

이번 계획에서 더하는 것.

- **새 표·칸은 Task 21 만** `app/store/tables.py` 에 정의한다. `create_all` 이 새 표를, `add_missing_columns` 가 기존 표의 새 칸(NULL 가능 또는 상수 기본값만)을 더한다. PM 의 `data/` 는 지우지 않는다. FK 는 두지 않는다(계획 1 판단).
- **도구:** 한 파일에 도구 하나(`app/tools/<묶음>/<파일>.py`). 입력 모델은 `ConfigDict(extra="forbid")`(안쪽 모델도). 없는 일정·계산 불가는 `with explained_schedule_errors():`, 그 밖의 실패는 `ToolError(한국어)`. 이름은 점 표기(`delay.record`), 지시문·안내 글에서는 모델이 보는 `delay__record` 꼴. 사건은 `ctx.emit(AgentEvent(...))` — 새 사건 종류는 만들지 않고 `card{kind}` 와 `open_window` 만 쓴다. 쓰기 도구는 `mutates=True`, flush 만(루프가 commit/rollback).
- **에이전트 지시:** 기능마다 `app/agent/prompts/guides/<기능>.md` 한 파일. `system.md` 는 고치지 않는다(Task 21 이 조각을 붙인다).
- **일정 변경 제안:** 전부 `app.agent.proposals.propose()`(Task 26). 실적 입력만 `force_auto=True`(설계 10-3 "실적 입력에 따른 재계산 = 자동 적용") — 그래도 승인 표에 `status='auto'`·`restore_to` 줄을 남겨 되돌릴 수 있다.
- **LLM 호출:** `LlmClient.chat(purpose, messages, json_schema=…)`(strict). 단축안 추천·설명은 `hard`. LLM 이 실패해도 기능은 코드 결과로 끝난다. LLM 호출 전에는 쓰기를 commit 한 상태여야 한다(계획 1 판단).
- **비용:** 관리하지 않는다(PM 11-19). LLM `usage.cost` 가 오면 보이고 없으면 비운다(실측: 오지 않음). 지연 기록의 "일수 × 하루 금액" 환산만 계산한다(설계 2장).
- **Data Date 기준:** 공정률·S-커브의 날짜 d 값은 "d 날 아침 = 전날까지 한 일" 이다. cpm 의 Data Date 규칙(남은 일을 Data Date 부터 센다)과 같은 뜻.
- **프로그램 라우터:** Task 24 이후 `app/programs/<이름>/router.py` 의 이름이 `router` 로 끝나는 `APIRouter` 는 자동 등록된다. `main.py` 는 고치지 않는다.
- **화면:** 새 프로그램은 `src/programs/<id>/`. 화면 맥락은 `useUiContext.getState().publish(windowId, {program, schedule_id, selected_activity})`, 창 제목은 `setTitle(windowId, "<프로그램> — <일정 이름>")`. `params.id` 가 없으면 `useCurrentSchedule` 의 일정을 연다.
- **계산 규칙 [PM 확인 11-20]:** 지연 넣기는 시작 전 작업이면 시작을 미루고(기간 그대로) 진행 중이면 남은 기간에 더한다. 단축안은 제안대로(병행 FS→SS+선행 기간 절반, 압축 20%, 자원 +1). 만회안 승인 때 Plan 다시 잡기는 기본 꺼짐·체크로 켬. 공정률은 Data Date 아침 기준(제안).

### 화면 검수 (PM 지시 2026-11-20 — 모든 화면 작업의 구현·리뷰에 적용)
1. 넘침 없음: 창 기본 크기와 그보다 작은 크기(약 900×600, 최소 크기까지)에서 어떤 요소도 창 밖으로 넘치지 않는다. 가로 스크롤 없음(계획 1 간트처럼 네트워크 그림·차트 영역 안에서 그림을 옮기는 것은 창 넘침이 아니다 — 이 계획의 해석), 입력 칸·표·단추가 잘리거나 삐져나오지 않음. 내용이 길면 창 안에서 세로로 스크롤한다.
2. 긴 목록은 고를 수 있게: 수십 개가 넘는 선택지(액티비티 고르기 등)는 분류와 찾기로 고르게 한다. 한 줄로 늘어놓은 긴 목록 금지.
3. 기계 출력은 읽히게: JSON·목록·오류·시험 결과를 원문 텍스트로 늘어놓지 않는다. 요약 줄 + 묶음·표·접기로 보인다(개발 콘솔의 원문도 접어서).
4. 확인 증거: 구현자는 FHD Chrome 에서 기본 크기와 작은 크기로 열어 1~3을 확인하고 스크린샷을 `.superpowers/sdd/2026-11-20-chronos-plan-2-bundle2/shots/task-<N>/` 에 남겨 보고서에 적는다. 리뷰어는 CSS(min-width:0, max-width, overflow, 줄바꿈)와 스크린샷 목록으로 확인하고, 빠졌으면 Important 로 적는다.
5. 테마: 밝은·어두운 테마 둘 다에서 1~3을 확인하고 스크린샷도 둘 다 남긴다.

### 예시 자료 (대회 규정 5 · 개인정보)
시험·고정 자료·시안·스크린샷에 나오는 사람·회사·현장은 모두 가상이다(예: 김하늘 / demo-admin / 5층 사무동 신축 / 가상 부품 공장). PM 의 실명·아이디·이메일을 쓰지 않는다.

## Review Focus

1. **지연을 두 번 센다** — 실적 입력에서 감지돼 이미 일정에 들어간 지연, 또는 승인된 복사본으로 반영된 지연이 영향 분석·만회안 기준에 다시 들어가 준공이 이중으로 밀린다. → Task 26 `test_approving_scenario_applies_and_reflects_its_delays`, Task 33 `test_reflected_event_is_not_inserted_again`, Task 34 `test_shorten_base_skips_reflected_delays`
2. **낡은 복사본을 반영** — 복사본을 만든 뒤 일정이 바뀌었는데 그 복사본을 승인해 사이의 고침을 덮는다. → 제출은 409, 승인 때 충돌이면 반영 안 하고 복사본은 다시 열림(낡음 표시). Task 26 `test_stale_scenario_submit_is_409`, `test_conflict_on_approve_reopens_scenario`
3. **코드 밖에서 날짜가 생김** — 실적 입력에서 LLM 이 실제 날짜를 지어내거나 Data Date 뒤 실적을 넣는다, 만회안 설명(LLM)에 날짜가 들어간다. → 빈 날짜는 코드가 규칙으로 채우고 "가정"으로 알린다, Data Date 뒤 실적은 거절, LLM 설명의 날짜는 버린다. Task 30 `test_actual_after_data_date_is_refused`, `test_progress_fills_start_and_remaining`, Task 34 `test_llm_note_with_a_date_is_dropped`
4. **근거 검색 실패·키 노출** — Liner Search 가 401/402/429/시간 초과여도 대화·생성이 멈추지 않고 "근거 검색 실패"로 표시하며, 키는 응답·기록·추적 어디에도 없다. → Task 27 `test_search_errors_are_explained`, `test_key_never_logged_or_returned`, Task 29 `test_trace_never_contains_the_key`
5. **공정률 경계** — Data Date 가 착공 전·준공 뒤, 가중치 합 0(마일스톤만·직접 입력 없음), Plan 과 지금이 다름 → 0 으로 나누기 없이 0·null 로 답한다. → Task 24 `test_progress_edges`

---

## File Structure (새로 생기는 것)

```
backend/app/
  core/            delay.py  shorten.py  progress.py                          순수 계산
  agent/           proposals.py  ops.py  trace.py
                   prompts/guides/{scenario,evidence,actuals,delay,shorten,rules}.md  prompts/shorten_note.md
  llm/             search.py                                                   Liner Search
  store/           scenarios.py  delays.py  links.py  evidence.py  my_rules.py  traces.py
  tools/           data/{find_activity,record_actual,search_evidence,attach_evidence}.py
                   respond/{record_delay,analyze_delay,make_shortening}.py
                   out/{create_scenario,submit_scenario,propose_rule}.py
  programs/        progress/ scenarios/(+compare.py) delays/ evidence/ rules/ devconsole/ attention/
  domains/         manufacturing/pack.yaml
frontend/src/
  programs/schedule/cpm/  programs/schedule/progress/
  programs/compare/  programs/delays/  programs/devconsole/
  os/AttentionWidget.tsx
```

---

### Task 21: 묶음 2 자료 넓히기 — 표·칸·일정 자료·Data Date·가중치·지시문 조각 [opus] · G1

**선행:** 계획 1 Task 17(일정 응답에 자원 부하)·18(조건 API) 커밋.

**Files:** Modify `backend/app/store/tables.py`, `backend/app/core/model.py`, `backend/app/store/schedules.py`, `backend/app/store/view.py`, `backend/app/programs/schedule/{schemas,service,router,edits}.py`, `backend/app/agent/context.py`; Create `backend/app/agent/prompts/guides/.gitkeep`, `backend/app/tools/respond/__init__.py`(설명 한 줄: "대응 도구 — 지연 영향·단축안"), `backend/tests/store/test_bundle2_tables.py`, `backend/tests/programs/test_schedule_bundle2.py`, `backend/tests/agent/test_guides.py`

**Interfaces — Consumes:** `app.core.model.Activity`·`CalendarSpec`·`BlockedPeriod`, `app.store.schedules.{activity_json, activity_from_json, to_json, from_json, run, load}`, `app.store.view.view_data`, `app.harness.assemble.prepare_stored`, `app.store.versions.save_new_version`, `app.store.upgrade.add_missing_columns`, `app.agent.context.system_prompt`, `app.tools.registry.{load_all, list_tools}`
**Produces:**
- `Activity.manual_weight: float | None = None` — 맨 끝 칸(`pinned_start` 뒤). core 계산은 쓰지 않는다. `activity_json` 에 `"manual_weight"`, 읽을 때 없으면 None.
- 표(모두 `created_at`, FK 없음):
```
scenarios        id, schedule_id int index, base_version int, name str(100), source str(10) 'agent'|'shorten'|'delay',
                 snapshot_json dict, conditions_json list, moves_json list=[], delay_event_ids list=[], summary_json dict={},
                 status str(10)='open' ('open'|'submitted'|'applied'|'discarded'), approval_id int|null, created_by str(100)
delay_events     id, schedule_id int index, activity_id str(50), start_date date, days int, cause text="",
                 responsibility str(10)='undecided' ('owner'|'ours'|'force'|'undecided'), daily_cost int|null, evidence str(200)="",
                 source str(10)='chat' ('chat'|'actual'|'user'), status str(10)='open' ('open'|'reflected'),
                 impact_json dict={}, analyzed_version int|null, reflected_version int|null, created_by str(100)
my_rules         id, scope str(10) 'domain'|'schedule', domain str(50), schedule_id int|null, condition_json dict,
                 enabled bool=True, approval_id int|null, created_by str(100)
evidence_searches id, chat_session_id int|null index, query text, mode str(10), ok bool, error_code str(20)|null,
                 result_count int=0, latency_ms int=0
evidence_items   id, search_id int index, title str(300), url str(1000), hostname str(200)="", description text="",
                 published str(20)|null, extra_json dict={}
evidence_links   id, evidence_id int index, schedule_id int|null, draft_id int|null, condition_id str(100)|null,
                 assumption_label str(100)|null
trace_events     id, chat_session_id int index, turn_id int index, run_id int|null, seq int, kind str(10) 'context'|'llm'|'end',
                 label str(100)="", started_at, ms int|null, model str(200)|null, input_tokens int=0, output_tokens int=0,
                 cost float|null, ok bool=True, error str(200)|null, input_text text="", output_text text=""
approvals +      link_kind str(10)|null ('scenario'|'rule'), link_id int|null, reset_plan bool=False, rule_json dict|null
                 (kind 주석에 'rule' 추가)
schedules +      weight_mode str(10)='duration' ('duration'|'manual')
```
- `ScheduleView` 넓힘: 액티비티마다 `ls`, `lf`(run 결과의 CpmRow), `manual_weight`. 위에 `weight_mode`, `calendar: {days_per_week, blocked: [{tag, start, finish}]}`, `summary.weight_missing`.
  - `weight`: duration 모드는 지금 그대로(`od/Σod`, 마일스톤 0). manual 모드는 `manual_weight / Σ(manual_weight>0)` 소수 4자리, 없거나 0 이면 0. `weight_missing` = manual 모드에서 `manual_weight` 가 None 인 task 수(duration 모드는 0).
  - `calendar.blocked`: 조건을 넣은 달력(`prepare_stored` 결과)의 `BlockedPeriod` 를 해마다 날짜로 펼쳐 `[schedule.start, finish]` 와 겹치는 것만, 시작일 순. 해를 넘기는 기간(`start_md > end_md`)은 끝이 다음 해. 2월 29일이 없는 해는 2월 28일. `view_data` 안에서는 다른 계산 날짜처럼 `date` 객체, API 응답은 `YYYY-MM-DD`.
- API:
  - `PATCH /api/schedules/{id}` `{data_date: "YYYY-MM-DD" | null, base_version}` → 새 버전(`by_kind='user'`, note `"Data Date 2027-03-03"` / `"Data Date 지움"`, changes `[{id: null, field: "data_date", from, to}]`) → ScheduleView. 확인 차례·오류는 Task 4 쓰기와 같다(409 `version_conflict`, 바뀐 것 없으면 200 그대로). 1900~2199 밖이거나 모르는 칸이면 422 `invalid_request`.
  - `PUT /api/schedules/{id}/weight-mode` `{mode: "duration"|"manual"}` → `{mode}` (버전 없음, 로그인한 누구나).
  - 액티비티 PATCH 본문에 `manual_weight: float >= 0 | null`(note `"A 가중치 없음 → 3"`).
- 지시문 조각: `context.GUIDES_DIR = prompts/guides`. `system_prompt()` 는 `system.md` 를 채운 뒤 끝에 `GUIDES_DIR/*.md`(이름이 `_` 로 시작하지 않는 것)를 이름 순으로 `\n\n` 으로 붙인다.

- [ ] **Step 1: 실패하는 시험** (`sid` = 계획 1 픽스처: A 3일 → B 2일, 2027-03-01 시작, 주 5일, 자원 crane 1대)
```python
def test_view_has_late_dates_and_manual_weight(client, admin, sid):
    a = act(client.get(f"/api/schedules/{sid}", headers=admin).json(), "A")
    assert (a["ls"], a["lf"], a["manual_weight"]) == ("2027-03-01", "2027-03-03", None)
def test_duration_mode_is_default(client, admin, sid):
    v = client.get(f"/api/schedules/{sid}", headers=admin).json()
    assert v["weight_mode"] == "duration" and act(v, "A")["weight"] == 0.6 and v["summary"]["weight_missing"] == 0
def test_manual_weight_mode(client, admin, sid):
    assert client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "manual"}, headers=admin).json() == {"mode": "manual"}
    v = client.patch(f"/api/schedules/{sid}/activities/A", json={"manual_weight": 3, "base_version": 1}, headers=admin).json()
    assert v["weight_mode"] == "manual" and act(v, "A")["weight"] == 1.0 and act(v, "B")["weight"] == 0.0 and v["summary"]["weight_missing"] == 1
def test_data_date_patch_makes_a_version(client, admin, sid):
    v = client.patch(f"/api/schedules/{sid}", json={"data_date": "2027-03-03", "base_version": 1}, headers=admin).json()
    assert v["version"] == 2 and v["data_date"] == "2027-03-03"
    assert client.get(f"/api/schedules/{sid}/versions", headers=admin).json()[0]["note"] == "Data Date 2027-03-03"
def test_data_date_patch_stale_and_range(client, admin, sid):
    assert client.patch(f"/api/schedules/{sid}", json={"data_date": "2027-03-03", "base_version": 0}, headers=admin).status_code == 409
    assert client.patch(f"/api/schedules/{sid}", json={"data_date": "1899-12-31", "base_version": 1}, headers=admin).json()["code"] == "invalid_request"
def test_blocked_periods_are_dated(client, admin, session):
    # A 200일(꼬리표 없음) 하나, 조건 blocked_period (7,29)~(8,4) 프레스
    assert view(...)["calendar"]["blocked"] == [{"tag": "프레스", "start": "2027-07-29", "finish": "2027-08-04"}]
def test_wrapping_period_ends_next_year(client, admin, session):
    # A 260일(준공 2028-02-25), 조건 blocked_period (12,1)~(2,28) 타설
    assert view(...)["calendar"]["blocked"] == [{"tag": "타설", "start": "2027-12-01", "finish": "2028-02-28"}]
def test_new_tables_and_columns(session):
    insp = inspect(session.get_bind())
    assert {"scenarios", "delay_events", "my_rules", "evidence_searches", "evidence_items", "evidence_links", "trace_events"} <= set(insp.get_table_names())
    assert {"link_kind", "link_id", "reset_plan", "rule_json"} <= {c["name"] for c in insp.get_columns("approvals")}
def test_existing_db_gets_new_columns(tmp_path, monkeypatch):
    # 계획 1 모양의 approvals·schedules 표(새 칸 없음)와 줄 하나씩 → init_db → 칸이 생기고 기존 줄은 weight_mode "duration", reset_plan 0
def test_manual_weight_roundtrip(sample_schedule):
    s = replace(sample_schedule, activities=(replace(sample_schedule.activities[0], manual_weight=2.5), sample_schedule.activities[1]))
    assert from_json(to_json(s)) == s and activity_from_json({k: v for k, v in activity_json(s.activities[0]).items() if k != "manual_weight"}).manual_weight is None
def test_guides_are_appended_in_name_order(monkeypatch, tmp_path):
    (tmp_path / "b.md").write_text("둘째"); (tmp_path / "a.md").write_text("첫째"); (tmp_path / "_x.md").write_text("숨김")
    monkeypatch.setattr(context, "GUIDES_DIR", tmp_path); p = context.system_prompt()
    assert p.index("첫째") < p.index("둘째") and "숨김" not in p
def test_guides_name_tools_as_the_model_sees_them():
    load_all(); names = {s.name for s in list_tools(enabled_only=False)}
    for f in context.GUIDES_DIR.glob("*.md"):
        assert not [n for n in names if n in f.read_text()], f.name      # 점 표기 금지(__ 꼴만)
```
- [ ] **Step 2:** 실패 확인 — [ ] **Step 3:** 구현. `view.py` 는 Task 4·7 의 계산 경로(`prepare_stored` → `run`)를 그대로 쓰고 칸만 더한다 — [ ] **Step 4:** 통과 확인(기존 시험 전부 포함) — [ ] **Step 5:** 커밋 `feat: 묶음 2 자료 — 표·칸·일정 자료 넓히기`

---

### Task 22: 지연 영향 계산 [fable] · G1

**Files:** Create `backend/app/core/delay.py`, `backend/tests/core/test_delay.py`

**Interfaces — Consumes:** `app.core.model.{Schedule, Activity}`, `app.core.cpm.compute`, `app.core.resources.level`, `app.core.calendar.WorkCalendar`
**Produces:**
```python
@dataclass(frozen=True)
class DelayEvent: id: str; activity_id: str; start: date; days: int; daily_cost: int | None = None
@dataclass(frozen=True)
class MilestoneShift: activity_id: str; before: date; after: date; delta: int          # 근무일
@dataclass(frozen=True)
class Clash: resource_id: str; first: date; days: int; over: int                         # 새로 생긴 (맞추기 전) 초과
@dataclass(frozen=True)
class EventImpact:
    event_id: str; applied: bool; note: str | None
    finish_before: date; finish_after: date; finish_delta: int; absorbed: int
    milestones: tuple[MilestoneShift, ...]; critical_added: tuple[str, ...]; critical_removed: tuple[str, ...]
    affected: tuple[str, ...]; new_clashes: tuple[Clash, ...]; cost: int | None
@dataclass(frozen=True)
class DelayAnalysis: base_finish: date; final_finish: date; total_delta: int; total_absorbed: int; impacts: tuple[EventImpact, ...]
class DelayInputError(ValueError): event_id: str; message: str
FINISHED_NOTE = "이미 끝난 액티비티입니다. 지연이 실적에 들어 있습니다."
MILESTONE_NOTE = "마일스톤에는 기간을 더할 수 없습니다. 앞 작업에 기록해 주세요."
def ordered(events) -> list[DelayEvent]                                      # (start, id) 순
def insert_delay(schedule, event) -> tuple[Schedule, str | None]           # (넣은 일정, 넣지 못한 까닭)
def diff_impact(before: Schedule, after: Schedule, *, event_id: str, days: int, daily_cost: int | None,
                applied: bool = True, note: str | None = None) -> EventImpact
def analyze(schedule: Schedule, events: Sequence[DelayEvent]) -> DelayAnalysis
```
규칙 [제안]:
- 받는 일정은 **조건을 넣은 일정**(부르는 쪽이 `prepare_stored`). core 는 조건을 모른다.
- 넣기 [PM 결정 11-20: 시작 전 작업은 **시작을 미룬다**]: 시작 전 task → 기간(od)과 사용자 제약(SNET·FNLT)은 그대로 두고, 일정의 정식 칸 `Activity.start_floor`(지연으로 미룬 시작 하한)를 `max(기존, 자원 맞춘 일정의 ES 를 그 액티비티 달력으로 days 근무일 민 날)` 로 올린다. CPM 은 실적이 없을 때 이 하한을 지키고, 자원 맞춤도 지키며, 저장(`to_json`/`from_json`)과 일정 보기(`ActivityView.start_floor`)에 들어간다(구현: 커밋 4fb0da8·1ddc515). 진행 중(`actual_start` 있음, `actual_finish` 없음) → 이미 시작했으므로 `rd = (rd if rd is not None else od) + days`. 끝남 → 넣지 않음(`FINISHED_NOTE`). 마일스톤 → 넣지 않음(`MILESTONE_NOTE`). 없는 액티비티 → `DelayInputError(id, "없는 액티비티입니다: Z")`, `days < 1` → `DelayInputError(id, "지연 일수는 1일 이상이어야 합니다.")`. `start` 는 차례와 표시에만 쓴다.
- 계산: `lv = level(s, compute(s), shift=True)`; 준공 = `lv.cpm.finish`, 크리티컬 = `lv.cpm` 의 critical, 날짜 = `lv.cpm.rows` 의 (es, ef).
- `finish_delta` = `WorkCalendar(schedule.calendar).workdays_between(finish_before, finish_after)`. `absorbed` = applied 이면 `max(0, days − max(0, finish_delta))`, 아니면 0.
- `milestones`: kind != task 인데 EF 가 바뀐 것(일정 차례). `affected`: (es, ef) 가 바뀐 id(일정 차례).
- `new_clashes`: `level(s, compute(s), shift=False).overloads` 의 (자원, 날짜) 가운데 뒤에만 있는 것 → 자원마다 첫 날·날 수·가장 큰 (need − capacity).
- `cost`: daily_cost 가 None 이면 None, applied 이고 finish_delta > 0 이면 `daily_cost × finish_delta`, 아니면 0.
- `analyze`: `ordered` 차례로 하나씩 넣어 가며 각 사건의 몫을 `diff_impact(넣기 전, 넣은 뒤)` 로 잰다. `ScheduleError` 는 그대로 나간다.

- [ ] **Step 1: 실패하는 시험** (CAL5 = 주 5일·공휴일 없음, 2027-03-01 월)
```python
BASE = sched([act("A", 3), act("B", 2), act("C", 1)], [Relation("A", "B"), Relation("A", "C")])   # A 3/1~3/3, B 3/4~3/5, C 3/4, 준공 3/5
def ev(i, aid, day, days, cost=None): return DelayEvent(i, aid, date(2027, 3, day), days, cost)
def test_critical_delay_moves_finish():
    i = analyze(BASE, [ev("e1", "B", 4, 2)]).impacts[0]
    assert (i.finish_before, i.finish_after, i.finish_delta, i.absorbed) == (date(2027, 3, 5), date(2027, 3, 9), 2, 0)
    assert i.affected == ("B",) and i.critical_added == () and i.cost is None
def test_float_absorbs_noncritical_delay():
    i = analyze(BASE, [ev("e1", "C", 4, 1)]).impacts[0]
    assert (i.finish_delta, i.absorbed, i.critical_added) == (0, 1, ("C",))
def test_events_are_inserted_in_start_order_each_with_its_share():
    r = analyze(BASE, [ev("b", "B", 3, 2), ev("c", "C", 2, 1)])
    assert [x.event_id for x in r.impacts] == ["c", "b"] and [x.finish_delta for x in r.impacts] == [0, 2]
    assert (r.final_finish, r.total_delta, r.total_absorbed) == (date(2027, 3, 9), 2, 1)
def test_not_started_task_starts_later_with_the_same_duration():       # PM 결정 11-20
    s = analyze(BASE, [ev("e1", "B", 4, 2)])
    after = insert_delay(BASE, ev("e1", "B", 4, 2))[0]
    b = next(a for a in after.activities if a.id == "B")
    assert b.od == 2 and b.constraint == Constraint("SNET", date(2027, 3, 8))   # ES 3/4 → 2 근무일 뒤 3/8
    assert s.impacts[0].finish_after == date(2027, 3, 9)
def test_not_started_task_with_fnlt_keeps_it_and_hides_the_helper_milestone():
    s = sched([act("A", 3), replace(act("B", 2), constraint=Constraint("FNLT", date(2027, 3, 12)))], [Relation("A", "B")])
    i = analyze(s, [ev("e", "B", 4, 2)]).impacts[0]
    assert i.finish_after == date(2027, 3, 9) and all(not x.startswith("~") for x in i.affected + i.critical_added)
def test_in_progress_adds_to_remaining():
    s = replace(sched([act("A", 3, actual_start=date(2027, 3, 1), rd=1), act("B", 2), act("C", 1)], [Relation("A", "B"), Relation("A", "C")]), data_date=date(2027, 3, 2))
    i = analyze(s, [ev("e", "A", 2, 2)]).impacts[0]                      # 준공 3/4 → 3/8
    assert (i.finish_before, i.finish_after, i.finish_delta) == (date(2027, 3, 4), date(2027, 3, 8), 2)
def test_finished_activity_is_not_inserted():
    s = sched([act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 3), progress=1.0), act("B", 2)], [Relation("A", "B")])
    i = analyze(s, [ev("e", "A", 2, 2)]).impacts[0]
    assert (i.applied, i.note, i.finish_delta, i.absorbed) == (False, FINISHED_NOTE, 0, 0)
def test_cost_is_finish_delta_times_daily_cost():
    assert analyze(BASE, [ev("e", "B", 4, 2, 3_100_000)]).impacts[0].cost == 6_200_000
    assert analyze(BASE, [ev("e", "C", 4, 1, 3_100_000)]).impacts[0].cost == 0
def test_milestone_shift_is_reported():
    s = sched([act("A", 3), act("B", 2), Activity("M", "준공", "finish_ms", "1", 0)], [Relation("A", "B"), Relation("B", "M")])
    assert analyze(s, [ev("e", "B", 4, 2)]).impacts[0].milestones == (MilestoneShift("M", date(2027, 3, 5), date(2027, 3, 9), 2),)
def test_new_resource_clash_and_leveling():
    R = Resource("crane", "타워크레인", "대", 1)
    s = replace(sched([act("A", 2, resources=("crane",)), act("X", 3), act("D", 2, resources=("crane",))], [Relation("X", "D")]), resources=(R,))
    i = analyze(s, [ev("e", "A", 1, 2)]).impacts[0]                      # A 3/1~3/4 가 D(3/4~) 와 겹침 → 맞춤이 D 를 3/5~3/8 로
    assert i.new_clashes == (Clash("crane", date(2027, 3, 4), 1, 1),) and (i.finish_delta, i.absorbed) == (1, 1)
def test_bad_input_raises():
    with pytest.raises(DelayInputError) as e: analyze(BASE, [ev("e", "Z", 4, 1)])
    assert e.value.message == "없는 액티비티입니다: Z"
    with pytest.raises(DelayInputError): analyze(BASE, [ev("e", "B", 4, 0)])
def test_diff_impact_between_two_schedules():                             # 실적에서 감지한 지연(이미 일정에 들어감)용
    after = sched([act("A", 3), act("B", 4), act("C", 1)], [Relation("A", "B"), Relation("A", "C")])
    assert diff_impact(BASE, after, event_id="x", days=2, daily_cost=None).finish_delta == 2
```
- [ ] **Step 2~5:** 실패 확인 → 구현(`core` 는 표준 라이브러리와 `app.core` 만) → 통과 확인 → 커밋 `feat: 지연 영향 계산`

---

### Task 23: 단축안 계산 [fable] · G1

**Files:** Create `backend/app/core/shorten.py`, `backend/tests/core/test_shorten.py`

**Interfaces — Consumes:** `app.core.model.{Schedule, Relation, Resource}`, `app.core.cpm.compute`, `app.core.resources.{level, LevelResult}`, `app.core.calendar.WorkCalendar`, `tests/core/helpers.py::big_schedule`
**Produces:**
```python
MoveKind = Literal["parallel", "compress", "add_resource"]
@dataclass(frozen=True)
class Move:
    id: str; kind: MoveKind; activity_ids: tuple[str, ...]; text: str
    relation: Relation | None = None            # parallel: 바꾼 뒤 관계(pred, succ, "SS", lag)
    od: int | None = None                       # compress: 새 기간
    resource_id: str | None = None; capacity: int | None = None   # add_resource: 새 용량
@dataclass(frozen=True)
class Package: key: Literal["A", "B", "C"]; name: str; moves: tuple[Move, ...]; finish: date; gain: int; reached: bool
@dataclass(frozen=True)
class ShortenResult: base_finish: date; target: int; packages: tuple[Package, ...]
PACKAGES = (("A", "병행 우선", {"parallel"}), ("B", "압축·자원 추가", {"compress", "add_resource"}),
            ("C", "섞음", {"parallel", "compress", "add_resource"}))
COMPRESS_RATIO = 0.2; COMPRESS_MIN_OD = 5; PARALLEL_MIN_OD = 4; MAX_MOVES = 6; MAX_CANDIDATES = 12
def candidate_moves(schedule: Schedule, lv: LevelResult) -> list[Move]
def apply_moves(schedule: Schedule, moves: Sequence[Move], *, resources: bool = True) -> Schedule
def shorten(schedule: Schedule, *, target: int, max_moves: int = MAX_MOVES) -> ShortenResult
```
규칙 [제안] (받는 일정은 조건을 넣은 일정, 크리티컬은 `lv.cpm` 기준):
- **parallel(병행)**: 관계가 FS lag 0, 선행·후행 모두 크리티컬 task, 둘 다 `actual_start` 없음, 선행 `od ≥ 4` → `Relation(pred, succ, "SS", ceil(od_pred / 2))`. id `par:A>B`, 글 `"A 절반 지점에서 B 시작 (FS → SS+3)"`.
- **compress(압축)**: 크리티컬 task, 실적 없음, `od ≥ 5` → `od − ceil(od × 0.2)`. id `cmp:A`, 글 `"A 기간 6일 → 4일 (작업 시간을 늘림)"`. 액티비티마다 한 번.
- **add_resource(자원 추가)**: 용량 ≥ 1 인 자원 r 를 쓰는 액티비티가 `lv.shifted` 에 있고 크리티컬이면 → `capacity + 1`. id `res:crane`, 글 `"타워크레인 1대 → 2대"`.
- 후보는 ES 이른 크리티컬부터 `MAX_CANDIDATES` 개. 고르기(묶음마다 따로): 지금 일정에서 허용된 종류의 후보마다 이득(근무일, 지금 준공 − 넣은 뒤 준공)을 잰다 — parallel·compress 는 `compute(lv.schedule 에 넣은 것)`(맞춤 고정을 둔 빠른 계산), add_resource 는 `level` 까지. 이득이 가장 큰 것(같으면 parallel < add_resource < compress, 그다음 id)을 `level` 까지 다시 계산해 실제 이득 > 0 이면 넣고, 아니면 버리고 다음 후보. 누적 이득 ≥ target 이거나 `max_moves` 또는 후보가 다하면 멈춘다.
- `Package.finish`·`gain` 은 최종 일정을 `level(shift=True)` 한 값. `reached = gain >= target`. 이동이 같은 집합인 뒤 묶음은 뺀다(빈 묶음은 남긴다). `target < 1` 이면 `ValueError("줄일 일수는 1 이상이어야 합니다.")`.
- `apply_moves(..., resources=False)` 는 add_resource 를 빼고 관계·기간만 바꾼다(저장용 원본 일정에 쓸 때).

- [ ] **Step 1: 실패하는 시험** (CAL5)
```python
CHAIN = sched([act("A", 6), act("B", 4), act("C", 5)], [Relation("A", "B"), Relation("B", "C")])   # A 3/1~3/8, B 3/9~3/12, C 3/15~3/19
def test_parallel_package_reaches_target_with_one_move():
    a = shorten(CHAIN, target=3).packages[0]
    assert (a.key, [m.id for m in a.moves], a.finish, a.gain, a.reached) == ("A", ["par:A>B"], date(2027, 3, 16), 3, True)
    assert a.moves[0].relation == Relation("A", "B", "SS", 3) and a.moves[0].text == "A 절반 지점에서 B 시작 (FS → SS+3)"
def test_parallel_package_keeps_going_until_no_gain():
    a = shorten(CHAIN, target=10).packages[0]
    assert ([m.id for m in a.moves], a.finish, a.gain, a.reached) == (["par:A>B", "par:B>C"], date(2027, 3, 12), 5, False)
def test_compress_package():
    b = shorten(CHAIN, target=3).packages[1]
    assert ([m.id for m in b.moves], [m.od for m in b.moves], b.finish, b.gain) == (["cmp:A", "cmp:C"], [4, 4], date(2027, 3, 16), 3)
def test_same_moves_are_not_repeated_as_another_package():
    assert [p.key for p in shorten(CHAIN, target=3).packages] == ["A", "B"]          # C 는 A 와 같아 빠짐
def test_add_resource_when_leveling_pushes_critical_work():
    R = Resource("crane", "타워크레인", "대", 1)
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 3, resources=("crane",))], []), resources=(R,))   # 맞춤 뒤 준공 3/8
    r = shorten(s, target=1)
    assert [p.key for p in r.packages] == ["A", "B"] and r.packages[0].moves == ()
    m = r.packages[1].moves[0]; assert (m.id, m.capacity, r.packages[1].gain, m.text) == ("res:crane", 2, 3, "타워크레인 1대 → 2대")
def test_started_work_is_not_touched():
    s = sched([act("A", 6, actual_start=date(2027, 3, 1)), act("B", 4), act("C", 5)], [Relation("A", "B"), Relation("B", "C")])
    ids = {m.id for p in shorten(s, target=3).packages for m in p.moves}; assert "par:A>B" not in ids and "cmp:A" not in ids
def test_apply_moves_without_resources_keeps_capacity():
    m = [Move("res:crane", "add_resource", ("A",), "", resource_id="crane", capacity=2), Move("cmp:A", "compress", ("A",), "", od=4)]
    out = apply_moves(two_crane_sched, m, resources=False); assert out.resources[0].capacity == 1 and out.activities[0].od == 4
def test_target_must_be_positive():
    with pytest.raises(ValueError): shorten(CHAIN, target=0)
def test_two_hundred_activities_shorten_quickly():
    t = time.perf_counter(); shorten(big_schedule(), target=5); assert time.perf_counter() - t < 5.0
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 단축안 계산`

---

### Task 24: 공정률·S-커브 계산과 진행 API [opus] · G1

**Files:** Create `backend/app/core/progress.py`, `backend/app/programs/progress/{__init__,router,service,schemas}.py`, `backend/tests/core/test_progress.py`, `backend/tests/programs/test_progress_api.py`; Modify `backend/app/main.py`(라우터 자동 등록)

**선행:** 없음(G1). Task 21 과 동시에 돌면 Task 21 커밋 뒤 이 작업의 시험을 다시 돌린다(`view_data` 를 읽기만 함).

**Interfaces — Consumes:** `app.store.view.view_data`(activities 의 `es, ef, plan_start, plan_finish, weight, status, tf, critical, progress, actual_*`), `app.store.schedules.load`, `app.harness.assemble.prepare_stored`, `app.core.calendar.WorkCalendar`, `app.agent.context.today`(모듈 속성으로 불러 시험이 바꿔 끼울 수 있게), `app.security.deps.current_user`
**Produces:**
```python
# core/progress.py — 값은 0~1, d 의 값 = "d 날 아침(전날까지)" 기준
@dataclass(frozen=True)
class Bar: id: str; kind: str; wbs: str; weight: float; plan_start: date | None; plan_finish: date | None
           start: date; finish: date; actual_start: date | None; actual_finish: date | None; progress: float
@dataclass(frozen=True)
class CurvePoint: date: date; plan_cum: float; actual_cum: float | None; forecast_cum: float | None
                  plan_period: float; actual_period: float | None                    # 퍼센트, 소수 1자리
def planned(bar, cal, day) -> float
def actual(bar, cal, day, data_date) -> float | None
def forecast(bar, cal, day, data_date) -> float | None
def points(bars, data_date, unit: Literal["week", "month"]) -> list[date]
def curve(bars, cal, *, data_date, unit) -> list[CurvePoint]
def weighted(bars, fractions: dict[str, float]) -> float                              # Σ w·f ×100, 1자리
def spi(plan_pct: float, actual_pct: float) -> float | None                           # plan 0 → None, 2자리
```
- `planned`: Plan 없음 → 0. 마일스톤 → `day > plan_finish` 이면 1. task → `[plan_start, plan_finish]` 근무일 수 n, `[plan_start, day)` 근무일 수 k, `min(k/n, 1)`.
- `actual`: `day > data_date` → None. `actual_start` 없거나 `day ≤ actual_start` → 0. 끝남이고 `day > actual_finish` → 1. 그 밖에는 창 `[actual_start, end)`(진행 중 end = data_date, 끝남 end = actual_finish 다음 날)의 근무일 n·`[actual_start, day)` 의 k 로 `진도 × k/n`.
- `forecast`: `day < data_date` → None. 끝남 → 1. 시작 전 → 지금 계산 `[start, finish]` 로 `planned` 와 같은 식. 진행 중 → `p + (1−p) × k/n`(창 `[data_date, finish]`, k = `[data_date, day)`).
- `points`: 시작 = Plan·지금 시작 가운데 가장 이른 날, 끝 = Plan·지금 종료 가운데 가장 늦은 날 + 1일. week = 시작 + 7k (끝 전까지) + 끝, month = 시작 + 다음 달들 1일 + 끝. Data Date 가 그 사이면 끼운다.
- `GET /api/schedules/{id}/progress?unit=week|month`(기본 week, 그 밖 422 `invalid_request`, 없는 일정 404, 계산 불가 422 `schedule_invalid`) →
```
{schedule_id, version, data_date, data_date_assumed: bool, unit, weight_mode, plan_now, actual_now, gap, spi,
 finish: {current, plan, deadline, delta, deadline_float},            # delta = 근무일(plan→current), deadline = 켜진 finish_by 가운데 가장 이른 것
 counts: {total, done, in_progress, late},                             # task 만
 curve: [CurvePoint], spi_trend: [{date, spi}],                        # spi_trend: data_date 이전·plan_cum>0 인 점
 wbs: [{code, name, weight, plan, actual, diff}],                      # 맨 위 WBS 묶음마다, 묶음 안에서 가중치를 다시 나눔
 milestones: [{id, name, plan, actual_or_forecast, delta, status}],   # status 완료|예정|지연|앞섬
 top_delays: [{id, name, delay, tf, finish_impact}],                   # late task, delay 큰 순(최대 5), finish_impact = critical 이면 delay
 lookahead: {from, to, starts: [{id, name, date}], finishes: [...], blocked: [{id, name, date, reason}]},   # data_date~+20일, task 만
 cpm: {plan_compliance: {pct, done, due} | null,                      # due = plan_finish < data_date 인 task, done = 그 가운데 actual_finish ≤ plan_finish
       critical_variance: {days, max_id} | null,                       # 크리티컬 task 의 (지금 근무일 길이 − Plan 근무일 길이) 합, 가장 큰 것
       finish_variance: {days, plan, current} | null}}
```
  Data Date 가 없으면 `context.today()`, `data_date_assumed: true`. blocked 의 reason 은 `"선행 미완: A"`(실적 종료가 없는 선행 id, 쉼표로).
- `main.py`: `app/programs/*/router.py` 를 이름 순으로 import 해, 이름이 `router` 로 끝나는 `APIRouter` 속성을 모두 `include_router`(기존 직접 등록을 대신). 함수 `include_program_routers(app) -> list[str]`(등록한 모듈 이름).

- [ ] **Step 1: 실패하는 시험** — 픽스처 `sid_progress`: WBS "1 기초"·"2 골조", A(5, wbs 1) → B(5, wbs 2) → M(준공, finish_ms, wbs 2). 버전 1(Plan): A 3/1~3/5, B 3/8~3/12, M 3/12. 버전 2: data_date 3/3, A actual_start 3/1·progress 0.2·rd 4 → A 3/1~3/8, B 3/9~3/15, M 3/15.
```python
def test_now_values(client, admin, sid_progress):
    p = get_progress(client, admin, sid_progress)
    assert (p["plan_now"], p["actual_now"], p["gap"], p["spi"]) == (20.0, 10.0, -10.0, 0.5)
    assert p["finish"] == {"current": "2027-03-15", "plan": "2027-03-12", "deadline": None, "delta": 1, "deadline_float": None}
    assert p["counts"] == {"total": 2, "done": 0, "in_progress": 1, "late": 2}
def test_weekly_curve(client, admin, sid_progress):
    c = get_progress(client, admin, sid_progress)["curve"]
    assert [x["date"] for x in c] == ["2027-03-01", "2027-03-03", "2027-03-08", "2027-03-15", "2027-03-16"]
    assert [x["plan_cum"] for x in c] == [0.0, 20.0, 50.0, 100.0, 100.0]
    assert [x["actual_cum"] for x in c] == [0.0, 10.0, None, None, None]
    assert [x["forecast_cum"] for x in c] == [None, 10.0, 40.0, 90.0, 100.0]
    assert [x["plan_period"] for x in c] == [0.0, 20.0, 30.0, 50.0, 0.0]
def test_tables(client, admin, sid_progress):
    p = get_progress(client, admin, sid_progress)
    assert p["wbs"] == [{"code": "1", "name": "기초", "weight": 0.5, "plan": 40.0, "actual": 20.0, "diff": -20.0},
                        {"code": "2", "name": "골조", "weight": 0.5, "plan": 0.0, "actual": 0.0, "diff": 0.0}]
    assert p["milestones"] == [{"id": "M", "name": "준공", "plan": "2027-03-12", "actual_or_forecast": "2027-03-15", "delta": 1, "status": "지연"}]
    assert [d["id"] for d in p["top_delays"]] == ["A", "B"] and p["top_delays"][0]["finish_impact"] == 1
    assert p["lookahead"]["blocked"] == [{"id": "B", "name": "작업 B", "date": "2027-03-09", "reason": "선행 미완: A"}]
    assert p["spi_trend"] == [{"date": "2027-03-03", "spi": 0.5}]
def test_cpm_block(client, admin, sid_progress):
    assert get_progress(client, admin, sid_progress)["cpm"] == {"plan_compliance": None, "critical_variance": {"days": 1, "max_id": "A"},
                                                               "finish_variance": {"days": 1, "plan": "2027-03-12", "current": "2027-03-15"}}
def test_plan_compliance(client, admin, sid_progress):        # 버전 3: A 실적 3/1~3/5 끝남, data_date 3/15
    assert get_progress(...)["cpm"]["plan_compliance"] == {"pct": 50, "done": 1, "due": 2}
@pytest.mark.parametrize("case", ["before_start", "after_finish", "only_milestones", "manual_without_weights"])
def test_progress_edges(client, admin, session, case):        # Review Focus 5
    p = get_progress(...)   # 예외 없음
    expected = {"before_start": (0.0, 0.0, None), "after_finish": (100.0, 0.0, 0.0), "only_milestones": (0.0, 0.0, None), "manual_without_weights": (0.0, 0.0, None)}[case]
    assert (p["plan_now"], p["actual_now"], p["spi"]) == expected
def test_missing_data_date_uses_today(client, admin, sid, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 3)); p = get_progress(client, admin, sid)
    assert (p["data_date"], p["data_date_assumed"]) == ("2027-03-03", True)
def test_month_unit_and_bad_unit(client, admin, sid_progress):
    assert get_progress(client, admin, sid_progress, unit="month")["curve"][0]["date"] == "2027-03-01"
    assert client.get(f"/api/schedules/{sid_progress}/progress?unit=day", headers=admin).status_code == 422
def test_program_routers_are_discovered(client, admin):
    assert {"approvals", "progress", "schedule"} <= set(include_program_routers(FastAPI()))
    assert client.get("/api/settings/approval", headers=admin).status_code == 200
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 공정률·S-커브 계산과 진행 API`

---

### Task 25: 화면 자리 — 새 프로그램 셋·일정판 탭 연결·대화 `ask`·일정 자료 타입 [sonnet] · G1

**선행:** 계획 1 Task 16·17 커밋.

**Files:** Create `frontend/src/programs/{compare,delays,devconsole}/index.ts`, `frontend/src/programs/schedule/cpm/CpmTab.tsx`, `frontend/src/programs/schedule/progress/ProgressTab.tsx`; Modify `frontend/src/programs/index.ts`, `frontend/src/programs/index.test.ts`, `frontend/src/programs/schedule/{Schedule.tsx,scheduleApi.ts}`, `frontend/src/programs/schedule/Schedule.test.tsx`, `frontend/src/programs/chat/{Chat.tsx,Chat.test.tsx}`

**Interfaces — Consumes:** `register`·`programs`(os/registry), `glyph`, `ProgramProps`, `useChat.{newChat, openSession, send}`, 계획 1 Task 16 의 `Schedule.tsx` 탭 막대·`scheduleApi.ts`
**Produces:**
- 매니페스트: `compare`(비교판, work, tone `violet`, 1600×900) · `delays`(지연 기록, work, tone `rose`, 1400×860) · `devconsole`(개발 콘솔, system, `adminOnly: true`, tone `slate`, 1600×900). 화면은 `os/Placeholder`. 등록 차례 `[chat, questionnaire, workflow, approvals, explorer, settings, devconsole, schedule, compare, conditions, delays]`.
- `Schedule.tsx`: CPM 탭 `lazy(() => import('./cpm/CpmTab'))`, 진행 탭 `lazy(() => import('./progress/ProgressTab'))`. 두 파일은 `export default function CpmTab(props: { windowId: string; scheduleId: number })` 꼴로 `data-testid="cpm-tab"`/`"progress-tab"` 와 "준비 중입니다." 만 그린다(Task 31·32 가 채운다).
- `scheduleApi.ts`: `Activity` + `ls: string; lf: string; manual_weight: number | null`. `ScheduleView` + `weight_mode: 'duration' | 'manual'; calendar: { days_per_week: number; blocked: { tag: string; start: string; finish: string }[] }`, `summary.weight_missing: number`. 함수 `patchSchedule(id, body: { data_date: string | null; base_version: number }): Promise<ScheduleView>`, `putWeightMode(id, mode): Promise<{ mode: 'duration' | 'manual' }>`.
- 대화 `params.ask`(보낼 글): `session` 이 있으면 그 대화를 열고, 없으면 새 대화에서 `send(ask)` 를 **한 번만**(같은 params 객체·StrictMode 두 번 불러도 한 번). 보내기가 거절되면(`send` 가 false) 대화창 안내 줄에 "앞의 요청이 끝난 뒤 다시 보내 주세요."

- [ ] **Step 1: 실패하는 시험**
```ts
test('new programs register in dock order and devconsole is admin only', () => { registerPrograms(); expect(programs('admin').map((p) => p.id)).toEqual(['chat', 'questionnaire', 'workflow', 'approvals', 'explorer', 'settings', 'devconsole', 'schedule', 'compare', 'conditions', 'delays']); expect(programs('user').map((p) => p.id)).not.toContain('devconsole') })
test('cpm and progress tabs load their own files', async () => { renderSchedule({ tab: 'cpm' }); expect(await screen.findByTestId('cpm-tab')).toBeInTheDocument(); await userEvent.click(screen.getByRole('tab', { name: '진행' })); expect(await screen.findByTestId('progress-tab')).toBeInTheDocument() })
test('ask param sends once in a new chat', async () => { render(<StrictMode><Chat windowId="w1" params={{ ask: '만회 계획을 만들어 줘' }} /></StrictMode>); await waitFor(() => expect(sendSpy).toHaveBeenCalledTimes(1)); expect(sendSpy).toHaveBeenCalledWith('만회 계획을 만들어 줘'); expect(newChatSpy).toHaveBeenCalled() })
test('ask with session opens that session first', async () => { render(<Chat windowId="w1" params={{ session: '4', ask: '지연 영향을 알려 줘' }} />); await waitFor(() => expect(openSessionSpy).toHaveBeenCalledWith(4)); expect(sendSpy).toHaveBeenCalledWith('지연 영향을 알려 줘') })
test('rejected ask leaves a notice', async () => { sendSpy.mockResolvedValue(false); render(<Chat windowId="w1" params={{ ask: 'x' }} />); expect(await screen.findByText('앞의 요청이 끝난 뒤 다시 보내 주세요.')).toBeVisible() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 묶음 2 화면 자리`

---

### Task 26: 변경 제안 공통화 · 만약에 복사본 · 승인 연결 [fable] · G2

**Files:** Create `backend/app/agent/{proposals,ops}.py`, `backend/app/store/{scenarios,delays,links}.py`, `backend/app/programs/scenarios/{__init__,router,service,schemas}.py`, `backend/app/tools/out/{create_scenario,submit_scenario}.py`, `backend/app/agent/prompts/guides/scenario.md`, `backend/tests/agent/test_proposals.py`, `backend/tests/programs/test_scenarios_api.py`, `backend/tests/tools/test_scenario_tools.py`; Modify `backend/app/tools/out/submit_change.py`, `backend/app/store/approvals.py`, `backend/app/programs/approvals/service.py`

**Interfaces — Consumes:** `submit_change` 본문(Task 11), `app.agent.approval.{assess, REASONS}`, `app.store.settings.approval_mode`, `app.store.approvals.{create, apply, DraftUsed, AGENT_NAME, last_request}`, `app.store.versions.{VersionConflict, mark_plan}`, `app.store.diff.schedule_changes`, `app.store.schedules.{load, run, to_json, from_json}`, `app.harness.{assemble.assemble_all, conditions.read_conditions, checks.check}`, `app.core.delay.{insert_delay, ordered, DelayEvent}`(Task 22), 표 `Scenario`·`DelayEvent`(Task 21)
**Produces:**
```python
# app/agent/ops.py — submit_change 에서 옮김(모양 그대로): PredIn, UpdateOp, AddOp, DeleteOp, NewActivity
Op = Annotated[UpdateOp | AddOp | DeleteOp, Field(discriminator="op")]
class OpError(ValueError): message: str             # 도구는 ToolError 로, API 는 422 invalid_change 로
def apply_ops(schedule, ops) -> Schedule
def with_inputs(stored: list[dict], given: list[dict]) -> list[dict]
# app/agent/proposals.py
@dataclass(frozen=True)
class Proposal:
    kind: Literal["first_save", "change"]; title: str      # 분야 범위 내 규칙은 propose 를 거치지 않는다(Task 35)
    before: Schedule | None; before_conditions: list[dict]; after: Schedule; after_conditions: list[dict]
    schedule_id: int | None; draft_id: int | None; base_version: int
    link_kind: Literal["scenario", "rule"] | None = None; link_id: int | None = None
    reset_plan: bool = False; rule_json: dict | None = None
@dataclass(frozen=True)
class ProposalResult: row: Approval; applied: bool; reasons: list[str]
class ProposalError(Exception): code: Literal["schedule_invalid", "no_change", "stale", "draft_used"]; message: str
def propose(session, p: Proposal, *, chat_session_id: int | None, requested_by: str,
            emit: Callable[[AgentEvent], None] | None = None, force_auto: bool = False,
            extra_reasons: Sequence[str] = ()) -> ProposalResult
# app/store/scenarios.py
def create(session, *, schedule_id, base_version, name, source, schedule, conditions, moves=(), delay_event_ids=(),
           created_by, extra_summary: dict | None = None) -> Scenario              # summary_json 을 코드가 채움, flush
def summarize(session, schedule_id, schedule, conditions) -> dict
def get(session, sid) -> Scenario                                                 # NotFound
def listed(session, schedule_id, statuses: Sequence[str]) -> list[Scenario]      # 새것부터
def set_status(session, row, status, *, approval_id: int | None = None) -> None
# app/store/delays.py (Task 33 이 넓힌다)
def open_events(session, schedule_id) -> list[DelayEventRow]                      # status open, (start_date, id) 순
def to_core(row) -> core.delay.DelayEvent                                         # id = str(row.id)
def mark_reflected(session, ids: Sequence[int], version: int) -> None
@dataclass(frozen=True)
class DelayedBase: schedule: Schedule; conditions: list[dict]; version: int; event_ids: list[int]; skipped: list[int]
def delayed_base(session, schedule_id, event_ids: Sequence[int] | None = None) -> DelayedBase   # 지금 버전 원본에 열린 사건을 차례로 insert_delay
# app/store/links.py — 승인 결과를 연결된 것에 알린다(같은 트랜잭션, flush 만)
def after_apply(session, row: Approval) -> None     # reset_plan → mark_plan(새 버전); scenario → applied + 그 사건 reflected
def after_reject(session, row: Approval) -> None    # scenario → open
def after_conflict(session, row: Approval) -> None  # scenario → open
```
- `propose` = 지금 `submit_change` 본문(계산 확인 → 바뀐 것 없음 확인 → 점검 → `assess`). 사유 = `assess` 사유 + `extra_reasons` + (`reset_plan` 이면 `"plan_reset"`) — `REASONS` 차례, 겹침 없음. 승인 필요: `important` 사유 하나라도 · `all` 늘 · `auto` `condition_violated` 있을 때. `force_auto` 면 사유와 상관없이 바로 반영(`status='auto'`, `restore_to = base_version`). 오류 글: stale `"그 사이 일정이 바뀌었습니다. 일정을 다시 읽고 고쳐 주세요."` · no_change `"바뀌는 것이 없습니다."` · draft_used `"이미 저장한 초안입니다."` · schedule_invalid `schedule_error_message`. 사건은 `submit_change` 와 같다(`approval {id,title,reasons,summary}` / `card auto_applied`). `submit_change` 는 이것을 부르고 `ProposalError` → `ToolError`(기존 시험 그대로 통과).
- `store.approvals.apply` 끝에 `links.after_apply`. 승인함 결정의 거부(`reject`·`reject_retry`)·충돌 경로에서 `after_reject`/`after_conflict`(결정 commit 과 같이).
- `summary_json`: `{finish, finish_delta, plan_delta, deadline_float, critical_count, violations: [violation_json], uncheckable, peak: {resource_id, name, need, capacity, when} | null, changed_count, gain: null, base_finish: null, note: "", recommended: false}` — 날짜 차이는 모두 조건 넣은 달력의 근무일. `finish_delta` = 만들 때의 지금 준공 → 복사본 준공. `peak` = 맞춘 일정의 `peaks` 가운데 need/capacity 가 가장 큰 것(같으면 id 순).
- API(`app/programs/scenarios/router.py`):
  - `GET /api/schedules/{id}/scenarios?status=open|applied|all`(기본 open = open·submitted) → `[ScenarioOut]`. `ScenarioOut = {id, schedule_id, name, source, base_version, stale, status, approval_id, moves: [{id, kind, text}], delay_event_ids, summary, created_by, created_at}`, `stale` = `base_version != 지금 버전`. 반영된 `source='shorten'` 은 `recovery: {planned_gain, achieved}`(achieved = 근무일(지금 준공 → summary.base_finish)).
  - `GET …/scenarios/{sid}` → ScenarioOut + `diff`(지금 일정 대비 `assess` 의 diff).
  - `DELETE …/scenarios/{sid}` → `{status: "discarded"}`. submitted·applied 는 409 `scenario_locked` "승인을 기다리거나 반영된 복사본은 버릴 수 없습니다."
  - `POST …/scenarios/{sid}/submit` `{title?: str ≤100, reset_plan: bool = false}` → `{approval_id, applied, status}`. stale → 409 `scenario_stale` "기준 일정이 바뀌었습니다. 복사본을 다시 만들어 주세요." · open 이 아님 → 409 `scenario_locked` · no_change → 422 `no_change`. 성공하면 복사본 status `submitted`(자동 적용이면 `applied`).
- 도구 `scenario.create {name: str(1..100), base_version: int, changes: [Op](0..100) = [], conditions: [dict] | null = null}` (program `compare`, mutates) — 일정을 바꾸지 않는다. 바꾸는 것이 없으면 ToolError "바꾸는 것이 없는 복사본입니다.". 사건 `card {kind: "scenario_created", scenario_id, schedule_id, name, summary}` + `open_window {program: "compare", params: {id, base: "current", other: "s:<sid>"}}`. 출력 `{scenario_id, summary}`.
- 도구 `scenario.submit {scenario_id: int, title: str | null = null, reset_plan: bool = false}` (program `approvals`, mutates) → 출력은 `out.submit_change` 의 `SubmitOut` 모양.
- `guides/scenario.md`: "만약에 …면?" → 일정을 고치지 말고 `scenario__create`(일정을 읽어 base_version). 반영은 사람이 비교판에서 하거나, 사용자가 반영하라고 할 때 `scenario__submit`. 복사본 수에 제한 없음(설계 13-2).

- [ ] **Step 1: 실패하는 시험** (`sid` = A 3일 → B 2일, 준공 3/5)
```python
async def test_scenario_does_not_touch_the_schedule(client, admin, ctx_sid):
    r = await call("scenario.create", {"name": "B 4일", "base_version": 1, "changes": [{"op": "update_activity", "id": "B", "od": 4}]}, ctx_sid)
    s = r.output["summary"]; assert r.ok and (s["finish"], s["finish_delta"]) == ("2027-03-09", 2) and view(client, admin)["version"] == 1
async def test_scenario_events(ctx_sid, events):
    await call("scenario.create", {...}, ctx_sid)
    assert [e.data.get("kind", e.type) for e in events] == ["scenario_created", "open_window"] and events[-1].data["params"]["other"].startswith("s:")
def test_submit_creates_linked_approval(client, admin, session, sid, scenario_id):
    r = client.post(f"/api/schedules/{sid}/scenarios/{scenario_id}/submit", json={"reset_plan": False}, headers=admin).json()
    row = session.get(Approval, r["approval_id"])
    assert (row.link_kind, row.link_id, r["applied"]) == ("scenario", scenario_id, False) and "finish_changed" in row.reasons_json
def test_approving_scenario_applies_and_reflects_its_delays(client, admin, session, sid):      # Review Focus 1
    e = add_open_delay(session, sid, "B", days=2); sc = scenario_from(delayed_base(session, sid))
    a = submit(client, admin, sid, sc); approve(client, admin, a)
    session.expire_all(); assert get(session, sc).status == "applied" and session.get(DelayEventRow, e).status == "reflected"
    assert session.get(DelayEventRow, e).reflected_version == 2 and view(client, admin)["finish"] == "2027-03-09"
def test_reset_plan_adds_reason_and_moves_plan(client, admin, session, sid, scenario_id):
    a = client.post(..., json={"reset_plan": True}).json()["approval_id"]; assert "plan_reset" in session.get(Approval, a).reasons_json
    approve(client, admin, a); vs = client.get(f"/api/schedules/{sid}/versions", headers=admin).json()
    assert [(v["n"], v["is_plan"]) for v in vs] == [(2, True), (1, False)] and view(client, admin)["plan_finish"] == view(client, admin)["finish"]
def test_reject_reopens_scenario(...)  # decide reject → scenario status "open"
def test_stale_scenario_submit_is_409(client, admin, session, sid, scenario_id):               # Review Focus 2
    client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 4, "base_version": 1}, headers=admin)
    r = client.post(f"/api/schedules/{sid}/scenarios/{scenario_id}/submit", json={}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "scenario_stale" and session.query(Approval).count() == 0
def test_conflict_on_approve_reopens_scenario(client, admin, session, sid, scenario_id):       # Review Focus 2
    a = submit(...); client.patch(... od 4 base 1 ...)
    assert client.post(f"/api/approvals/{a}/decide", json={"decision": "approve", "note": ""}, headers=admin).status_code == 409
    s = client.get(f"/api/schedules/{sid}/scenarios/{scenario_id}", headers=admin).json(); assert (s["status"], s["stale"]) == ("open", True)
def test_discard_and_locked(...)       # open → discarded / submitted → 409 scenario_locked
def test_force_auto_records_an_auto_row(session, sid):
    r = propose(session, change_with_finish_moved(sid), chat_session_id=None, requested_by="김하늘", force_auto=True)
    assert r.applied and (r.row.status, r.row.restore_to) == ("auto", 1) and "finish_changed" in r.reasons
def test_delayed_base_inserts_open_events_and_skips_finished(session, sid_with_finished_A):
    d = delayed_base(session, sid)        # B +2(열림), A +1(끝난 액티비티)
    assert {a.id: a.od for a in d.schedule.activities}["B"] == 4 and d.skipped == [event_on_A]
def test_applied_shorten_scenario_reports_recovery(client, admin, session, sid_chain):  # summary gain 3, base_finish 3/19, 지금 준공 3/16
    assert client.get(f"/api/schedules/{sid}/scenarios?status=applied", headers=admin).json()[0]["recovery"] == {"planned_gain": 3, "achieved": 3}
```
- [ ] **Step 2~5:** 실패 확인 → 구현(기존 `tests/tools/test_submit_change.py`·`tests/programs/test_approvals_api.py` 전부 그대로 통과) → 통과 확인 → 커밋 `feat: 변경 제안 공통화와 만약에 복사본`

---

### Task 27: 근거 검색 — Liner Search · 도구 · 근거 보관 · 조건 출처 링크 [opus] · G2

**선행:** 계획 1 Task 18 커밋(조건 API·조건 화면).

**Files:** Create `backend/app/llm/search.py`, `backend/app/store/evidence.py`, `backend/app/tools/data/{search_evidence,attach_evidence}.py`, `backend/app/programs/evidence/{__init__,router,service,schemas}.py`, `backend/app/agent/prompts/guides/evidence.md`, `backend/tests/llm/test_search.py`, `backend/tests/tools/test_evidence_tools.py`, `backend/tests/programs/test_evidence_api.py`; Modify `backend/app/tools/generate/run.py`(`FactIn`), `backend/app/programs/conditions/{service,schemas}.py`, `frontend/src/programs/conditions/{ConditionItem.tsx,condApi.ts}` + 그 시험

**Interfaces — Consumes:** `app.llm.assignments.default_connection`, `app.security.crypto.decrypt`, `app.llm.errors.LlmError`, `app.store.chats.messages`(마지막 사용자 메시지 시각), 표 `EvidenceSearch`·`EvidenceItem`·`EvidenceLink`, `ScheduleDraft.schedule_id`(초안이 일정이 된 뒤 링크 찾기)
**Produces:**
```python
SearchMode = Literal["web", "scholar"]
@dataclass(frozen=True)
class SearchHit: title: str; url: str; hostname: str; description: str; date: str | None
                 authors: tuple[str, ...] = (); journal: str | None = None; citation_count: int | None = None
@dataclass(frozen=True)
class SearchResult: hits: list[SearchHit]; latency_ms: int
class SearchNotReady(Exception): message: str
class SearchFailed(Exception): code: str; message: str
async def liner_search(session, query: str, mode: SearchMode = "web", *, max_results: int = 5,
                       timeout_s: float = 20, transport: httpx.AsyncBaseTransport | None = None) -> SearchResult
```
- 연결: 기본 연결이 없음 → `SearchNotReady("근거 검색에는 Liner 연결이 필요합니다. 설정에서 연결해 주세요.")` · provider 가 `liner` 아님 → `"근거 검색은 Liner 연결에서만 됩니다."` · 키 풀기 실패 → `"저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요."`.
- 요청: `POST {base_url}/tools/search/{mode}`, 헤더 `x-api-key`·`Content-Type: application/json`, 본문 web `{query, max_results, include_knowledge: false}` / scholar `{query, max_results}`. `httpx.AsyncClient(trust_env=False)`. 응답 `results[]` 의 `title, url, hostname, description, date`(+ scholar `authors, journal, citationCount`).
- 시험은 모듈 속성 `app.llm.search.TRANSPORT`(기본 None, 주면 `transport` 대신 씀)를 바꿔 끼운다.
- 오류(`SearchFailed`): 400 `bad_request` "검색 요청 형식이 맞지 않습니다." · 401 `bad_key` "API 키가 맞지 않습니다." · 402 `no_credit` "Liner 크레딧이 부족합니다." · 429 `rate_limited` "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요." · 5xx `server_error` "검색 서버에 문제가 생겼습니다." · 시간 초과 `timeout` "응답이 너무 늦습니다." · 연결 실패 `bad_url` "주소에 연결할 수 없습니다." · 읽을 수 없는 200 `unknown` "검색 결과를 읽지 못했습니다.". 키·헤더는 어떤 기록에도 남기지 않는다.
- `store/evidence.py`: `record_search(session, *, chat_session_id, query, mode, ok, error_code, latency_ms, hits) -> tuple[int, list[EvidenceItem]]` · `searches_since(session, chat_session_id, since) -> int` · `last_user_message_at(session, chat_session_id) -> datetime | None` · `link(session, *, evidence_ids, schedule_id=None, draft_id=None, condition_id=None, assumption_label=None) -> int` · `for_schedule(session, schedule_id)`(일정 링크 + 그 일정을 만든 초안의 링크) · `for_conditions(session, schedule_id) -> dict[str, list[EvidenceItem]]`.
- 도구 `evidence.search {query: str(1..300), mode: "web"|"scholar" = "web", max_results: int(1..5) = 5}` (program None, mutates) → `{search_id, used, limit: 3, results: [{evidence_id, title, url, hostname, description(≤300자), date, authors, journal}]}` + `card {kind: "evidence", search_id, query, mode, results: [{evidence_id, title, url, hostname, date}]}`. 이번 요청(마지막 사용자 메시지 뒤)에 이미 3번 했으면(실패 포함) ToolError `"이번 요청에서 근거 검색을 3번 했습니다. 찾은 근거나 분야 기본값을 쓰세요."`. 실패는 실패 줄을 남기고 ToolError `"<안내> 근거 없이 분야 기본값을 쓰고 '근거 검색 실패'라고 적으세요."`.
- 도구 `evidence.attach {schedule_id: int | null, draft_id: int | null, items: [{evidence_id: int, condition_id: str | null, assumption_label: str | null}](1..10)}` (mutates) — 대상은 정확히 하나, 항목마다 둘 중 하나. 없는 근거 ToolError `"없는 근거입니다: 7"`. 출력 `{linked: n}`.
- `generate.run` 의 `FactIn` 에 `evidence_ids: list[int] = []` — facts·assumptions 그대로 초안 `assumptions_json`·결과 카드까지 간다.
- API `GET /api/evidence?schedule_id=<id>` 또는 `?chat_session_id=<id>`(정확히 하나, 아니면 422 `invalid_request`; 남의 대화는 404) → `[{id, title, url, hostname, description, date, mode, query, links: [{condition_id, assumption_label}]}]`.
- 조건 API(Task 18) 조건마다 `evidence: [{id, title, url}]`(기본 `[]`). 조건 화면 `ConditionItem` 은 있으면 "출처 n" 아래 링크(새 탭, `rel="noopener noreferrer"`).
- `guides/evidence.md`: L3 이상 생성에서 분야 기준 기간(예: 층당 골조 기간)이 필요하면 `evidence__search` 를 최대 3번 → 찾은 값으로 가정을 정하고 assumptions 에 `source: "근거 검색"`, `evidence_ids` → 생성 뒤 `evidence__attach`(draft_id, assumption_label). 실패하면 분야 기본값 + `source: "분야 기본값(근거 검색 실패)"`. 답에 근거를 말할 때는 "[근거 n]".

- [ ] **Step 1: 실패하는 시험** (`httpx.MockTransport`, `tests/llm_doubles.add_connection`)
```python
async def test_web_search_request_and_parse(session, liner_conn):
    t = mock(200, {"requestId": "r", "results": [{"title": "골조 공기 기준", "url": "https://example.com/a", "hostname": "example.com", "description": "층당 8~12일", "date": "2026-03-01"}], "totalCount": 1})
    r = await liner_search(session, "철근콘크리트 층당 골조 공기", transport=t)
    assert t.last.url.path == "/api/v1/tools/search/web" and t.last.headers["x-api-key"] == KEY and json.loads(t.last.content) == {"query": "철근콘크리트 층당 골조 공기", "max_results": 5, "include_knowledge": False}
    assert r.hits[0].title == "골조 공기 기준"
async def test_scholar_body_and_fields(session, liner_conn): ... body has no include_knowledge; hits[0].authors == ("김하늘",) and citation_count == 12
@pytest.mark.parametrize("status,code", [(401, "bad_key"), (402, "no_credit"), (429, "rate_limited"), (502, "server_error")])
async def test_search_errors_are_explained(session, liner_conn, status, code):                  # Review Focus 4
    with pytest.raises(SearchFailed) as e: await liner_search(session, "q", transport=mock(status, {}))
    assert e.value.code == code
async def test_not_ready_without_liner(session):
    with pytest.raises(SearchNotReady): await liner_search(session, "q")
async def test_key_never_logged_or_returned(session, liner_conn, caplog, ctx, monkeypatch):                   # Review Focus 4
    monkeypatch.setattr(search, "TRANSPORT", mock(401, {})); r = await call("evidence.search", {"query": "q"}, ctx)
    assert KEY not in caplog.text and KEY not in json.dumps(r.model_dump()) and KEY not in str(session.query(EvidenceSearch).one().__dict__)
async def test_tool_records_and_emits_card(ctx, events, session): ... r.output["results"][0]["evidence_id"] == 1 and events[-1].data["kind"] == "evidence" and session.query(EvidenceItem).count() == 1
async def test_three_searches_per_request(ctx_chat): 3번 뒤 4번째 → error "이번 요청에서 근거 검색을 3번 했습니다. 찾은 근거나 분야 기본값을 쓰세요."
async def test_failure_tells_the_agent_to_fall_back(ctx): mock(402) → r.error.endswith("근거 없이 분야 기본값을 쓰고 '근거 검색 실패'라고 적으세요.") and failed row ok False error_code "no_credit"
async def test_attach_and_condition_links(client, admin, ctx_sid): attach condition_id "in.finish_by" → GET conditions → that condition evidence[0]["url"] == "https://example.com/a"
async def test_generation_keeps_evidence_ids(ctx, session): generate.run(assumptions=[{"label": "층당 골조 기간", "value": "10일", "source": "근거 검색", "evidence_ids": [3]}]) → draft.assumptions_json[0]["evidence_ids"] == [3]
def test_evidence_list_needs_exactly_one_filter(client, admin): assert client.get("/api/evidence", headers=admin).status_code == 422
```
```ts
test('condition shows its sources as links', () => { render(item({ evidence: [{ id: 1, title: '골조 공기 기준', url: 'https://example.com/a' }] })); expect(screen.getByText('출처 1')).toBeVisible(); expect(screen.getByRole('link', { name: '골조 공기 기준' })).toHaveAttribute('rel', 'noopener noreferrer') })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(조건 화면 화면 검수 스크린샷) → 커밋 `feat: 근거 검색`

---

### Task 27b: 분야 근거 검색 — Liner MCP `search_legal`·`search_business` [opus] · G3 (Task 27 뒤)

**[PM 결정 11-20]** 모델 API = 생각과 말, Search API(web·scholar) = 일반 근거, **MCP 분야 도구 = 분야 전문 근거**로 나눠 쓴다. 건설의 인허가·법정 기간·작업 제한은 `search_legal`, 생산의 공급업체·자재 리드타임은 `search_business`. (`deep_research_agent` 조사 맡기기는 계획 3 사업화 분야와 함께.)

**Files:** Create `backend/app/llm/mcp_client.py`, `backend/scripts/probe_liner_mcp.py`, `backend/tests/llm/test_mcp_client.py`; Modify `backend/app/llm/search.py`(Task 27), `backend/app/tools/data/search_evidence.py`(Task 27), `backend/app/agent/prompts/guides/evidence.md`, `backend/app/domains/construction/pack.yaml`(근거 안내 한 줄), `backend/app/domains/production/pack.yaml`(Task 28, 근거 안내 한 줄) + 그 시험

**Interfaces — Consumes:** Task 27 `evidence.search`·`store/evidence.py`·카드 `evidence`, Task 6 연결(키는 서버에만)
**Produces:**
- 먼저 실측(Step 0): `backend/scripts/probe_liner_mcp.py` — DB 기본 연결의 키로 `https://platform.liner.com/api/v1/mcp` 에 `Authorization: Bearer <key>` · Streamable HTTP(JSON-RPC 2.0 `POST`, `Accept: application/json, text/event-stream`)로 `initialize` → `notifications/initialized` → `tools/list` → `tools/call search_legal {"query": "건축물 착공신고 처리 기한"}` → `tools/call search_business {"query": "철근 공급업체 납기"}` (모두 5번 이하). 키는 출력·기록하지 않는다. 결과(되는지·응답 모양·걸린 시간)를 `docs/dev-journal/2026-11.md` 에 적는다. **안 되면 Task 27b 는 여기서 멈추고 보고한다(기능을 넣지 않는다).**
- `mcp_client.py`(새 의존성 없이 httpx): `async def call_tool(base_url: str, secret: str, name: str, arguments: dict, *, timeout: float = 30) -> list[dict]` — 세션 열기(`initialize`, 응답 헤더 `Mcp-Session-Id` 가 있으면 이후 요청에 붙임) → `tools/call` → 결과의 content(text JSON 또는 structured)에서 검색 결과 `[{title, url, description, date}]` 를 뽑는다. 응답이 `text/event-stream` 이면 `data:` 줄의 JSON-RPC 결과를 읽는다. JSON-RPC 오류·HTTP 오류·시간 초과는 Task 27 의 검색 오류와 같은 안내로 바꾼다. `MCP_URL` 은 연결의 base_url 에서 `/mcp` 를 붙여 만든다.
- `evidence.search` 의 `mode` 에 `"legal" | "business"` 를 더한다 → MCP `search_legal`·`search_business`. 저장(`evidence_searches.mode`)·카드·한도(요청당 3번, web/scholar 와 합산)는 Task 27 과 같다. MCP 가 실패하면 같은 질의로 web 을 한 번 시도하고 카드에 「분야 검색 실패 → 웹 검색」을 적는다(그것도 한도에 센다).
- `guides/evidence.md`: 언제 어느 mode 를 쓰는지 — 인허가·법정 기간·작업 금지·안전 규정 → legal, 공급업체·자재·부품 리드타임 → business, 학술 기준 → scholar, 그 밖 → web. 분야 묶음 YAML 의 근거 안내 한 줄이 같은 것을 말한다.

- [ ] **Step 0: 실측** (위). 안 되면 멈춤.
- [ ] **Step 1: 실패하는 시험** (`httpx.MockTransport`)
```python
async def test_call_tool_json_response(): r = await call_tool(BASE, "k", "search_legal", {"query": "q"}, transport=mock_json([{"title": "건축법 시행령", "url": "https://law.example/1"}])); assert r[0]["title"] == "건축법 시행령"
async def test_call_tool_sse_response(): r = await call_tool(BASE, "k", "search_business", {"query": "q"}, transport=mock_sse(...)); assert r[0]["url"].startswith("https://")
async def test_session_id_is_reused(): ...  # initialize 응답의 Mcp-Session-Id 가 tools/call 헤더에 붙는다
async def test_bearer_header_and_no_key_in_errors(): ...  # Authorization: Bearer k, 오류 글에 키 없음
async def test_evidence_legal_mode_records_and_cards(): ...  # mode "legal" → 저장·카드 mode "legal"
async def test_legal_failure_falls_back_to_web_once_and_counts(): ...
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 분야 근거 검색(Liner MCP 법령·기업)`

### Task 28: 생산 분야 묶음 [sonnet] · G2

**Files:** Create `backend/app/domains/manufacturing/pack.yaml`, `backend/tests/domains/test_manufacturing_pack.py`; Modify `backend/app/domains/loader.py`(`DisplaySpec`), `backend/app/domains/construction/pack.yaml`(`display`)

**Interfaces — Consumes:** `app.domains.loader.{DomainPack, load, domains, read_pack, PARAM_KEYS}`, `app.harness.conditions.Condition`, `app.harness.assemble.prepare`, `app.harness.checks.check`, `app.agent.generation.generate`(시험), `tests/gen_doubles.ScriptedLlm`
**Produces:**
- `loader.DisplaySpec(BaseModel, frozen, extra="forbid")`: `gantt_group_by: Literal["wbs", "resource"] = "wbs"`, `deadline_label: str = "준공"`, `extra_columns: list[Literal["resources", "constraint", "es_ef", "ls_lf"]] = []`. `DomainPack.display: DisplaySpec = DisplaySpec()`. 건설 YAML 에 `display: {gantt_group_by: wbs, deadline_label: 준공, extra_columns: []}`.
- 생산 묶음(`id: manufacturing`, `name: 생산`, 가상 예시 기준 "가상 부품 공장 — 프레스 브래킷 주문"):

| 칸 | 값 |
|---|---|
| terms | activity 공정 · resource 설비 · start 착수 · deadline 납기 · milestone 마일스톤 · wbs 주문·공정 묶음 · calendar 가동 달력 · float 여유 · critical_path 크리티컬 패스 · contingency 예비 기간 · actual 실적 |
| default_calendar | `{days_per_week: 5, holidays: KR}` |
| rules (layer domain, source 분야 규칙) | `manufacturing.press_maintenance` blocked_period `{start_md: [7, 29], end_md: [8, 4], tag: 프레스}` "프레스 라인은 하계 정기 보수 기간(7월 29일~8월 4일)에 멈춘다" · `manufacturing.cooling_after_heat` min_gap `{after_tag: 열처리, days: 1, unit: workdays}` "열처리 뒤 하루 이상 식힌 다음 다음 공정에 넣는다" · `manufacturing.fai_before_mass` text_only "양산은 초도품 검사(FAI) 합격 뒤 시작한다" · `manufacturing.mold_trial` text_only "금형은 시사출(T1) 승인 뒤 양산에 쓴다" · `manufacturing.inspect_before_ship` text_only "출하 전 최종 검사를 거친다" |
| key_resources | `press_line` 프레스 라인(라인) [프레스] · `heat_furnace` 열처리로(기) [열처리] · `cnc` CNC 가공기(대) [가공] · `assembly_line` 조립 라인(라인) [조립] · `cmm` 3차원 측정기(대) [검사] · `mold_shop` 금형 제작반(조) [금형] |
| activity_types | 금형 ← [금형, 시사출] → mold_shop · 프레스 ← [프레스, 블랭킹, 성형, 피어싱] → press_line · 열처리 ← [열처리, 담금질, 뜨임] → heat_furnace · 가공 ← [가공, 탭핑, 드릴] → cnc · 조립 ← [조립] → assembly_line · 검사 ← [검사, 측정, 초도품] → cmm · 자재 ← [발주, 입고] → [] · 출하 ← [포장, 출하] → [] |
| wbs_template | 1 준비(설계·금형): 1.1 제품·공정 설계(1.1.1 도면 검토·공정 설계, 1.1.2 지그·검사구 설계), 1.2 금형(1.2.1 금형 설계, 1.2.2 금형 제작, 1.2.3 시사출(T1)·수정) / 2 자재: 2.1 원자재 발주·입고, 2.2 수입 검사 / 3 생산: 3.1 프레스(3.1.1 블랭킹, 3.1.2 성형·피어싱), 3.2 열처리(3.2.1 담금질·뜨임), 3.3 가공(3.3.1 CNC 가공, 3.3.2 탭핑), 3.4 조립(3.4.1 서브 조립, 3.4.2 최종 조립) / 4 품질·출하: 4.1 초도품 검사(FAI), 4.2 양산 검사, 4.3 포장·출하 |
| assumption_defaults | `workdays_per_week` 주 근무일 5일(토·일·법정 공휴일 휴무) · `shifts_per_day` 하루 교대 2교대(기간은 근무일로 센다) · `oee` 설비 종합 효율 85% · `setup_time` 금형 교체 4시간(같은 날 안에서 처리) · `mold_lead_time` 금형 제작 25일(중형 프레스 금형 1벌, 시사출 전까지) · `contingency_ratio` 예비 기간 10%(납기 직전에 모아 둔다) · `orders_as_wbs` 주문과 WBS: 주문마다 맨 위 묶음 하나(납기는 그 묶음 끝 마일스톤) |
| display | `{gantt_group_by: resource, deadline_label: 납기, extra_columns: [resources]}` |

  설비 용량은 분야 규칙(resource_cap)으로 두지 않는다 — L1·L2 는 자원이 없어 늘 "없는 자원"이 되기 때문. 주요 자원 용량(조건·규칙의 자원 조건)으로 다룬다.

- [ ] **Step 1: 실패하는 시험**
```python
def test_both_domains(): assert domains() == ["construction", "manufacturing"]
def test_pack_reads(): p = load("manufacturing"); assert p.name == "생산" and [Condition.from_dict(r).kind for r in p.rules_raw] == ["blocked_period", "min_gap", "text_only", "text_only", "text_only"]
def test_resources_and_types_link():
    p = load("manufacturing"); assert {r.id for r in p.key_resources} == {"press_line", "heat_furnace", "cnc", "assembly_line", "cmm", "mold_shop"}
    assert next(t for t in p.activity_types if t.tag == "프레스").resources == ["press_line"]
def test_display(): assert load("manufacturing").display == DisplaySpec(gantt_group_by="resource", deadline_label="납기", extra_columns=["resources"]) and load("construction").display.deadline_label == "준공"
def test_press_maintenance_blocks_press_work():
    s = Schedule(date(2027, 7, 28), CalendarSpec(5), (WbsNode("3", "생산", None),), (Activity("P1", "브래킷 블랭킹", "task", "3", 3, tags=("프레스",)),), ())
    r = compute(prepare(s, [Condition.from_dict(d) for d in load("manufacturing").rules_raw]))
    assert (r.rows["P1"].es, r.rows["P1"].ef) == (date(2027, 7, 28), date(2027, 8, 6))
@pytest.mark.parametrize("lag,ok", [(0, False), (1, True)])
def test_cooling_gap_is_checked(lag, ok):          # 열처리 2일(3/1~3/2) → 가공 1일
    rep = check(heat_then_machine(lag), assemble([Condition.from_dict(d) for d in load("manufacturing").rules_raw], [], []))
    assert ("manufacturing.cooling_after_heat" in rep.passed) is ok
def test_prompt_mentions(): p = load("manufacturing").prompt(); assert p.startswith("분야: 생산 (manufacturing)") and "납기" in p
async def test_generation_attaches_press_line(ctx):
    r = await generate(ctx, ScriptedLlm([MFG_WBS, MFG_SCHED]), domain="manufacturing", level="L3", request="브래킷 2만 개 주문 일정")
    assert "press_line" in next(a for a in r.schedule.activities if "블랭킹" in a.name).resources
def test_system_prompt_lists_both(): assert "construction(건설), manufacturing(생산)" in system_prompt()
```
- [ ] **Step 2~5:** 실패 확인 → 작성 → 통과 확인 → 커밋 `feat: 생산 분야 묶음`

---

### Task 29: 실행 추적 기록과 개발 콘솔 API [fable] · G2

**Files:** Create `backend/app/agent/trace.py`, `backend/app/store/traces.py`, `backend/app/programs/devconsole/{__init__,router,service,schemas}.py`, `backend/tests/agent/test_trace.py`, `backend/tests/programs/test_devconsole_api.py`; Modify `backend/app/agent/loop.py`

**Interfaces — Consumes:** `run_turn`·`MAX_STEPS`(loop), `build_context`·`system_prompt`·`situation`·`date_helper`·`history`(context), `registry.as_llm_tools`, `LlmReply`, 표 `TraceEvent`·`WorkflowRun`·`WorkflowStep`·`LlmCall`·`ChatSession`·`User`, `app.agent.turns.is_running`, `require_admin`, `tests/loop_doubles`·`tests/llm_doubles.FakeLiner`
**Produces:**
```python
# app/agent/trace.py
CONTEXT_PARTS = ("지시문", "분야 지식", "정밀도", "지금 상황", "날짜 도우미", "대화", "도구 목록")
TEXT_LIMIT = 60_000; MESSAGE_LIMIT = 4_000
class TraceLog:
    def __init__(self, session, chat_session_id: int, turn_id: int): ...       # turn_id = 이번 사용자 메시지 id
    def context(self, parts: list[dict], history_count: int, tool_count: int) -> None
    def llm_start(self, messages: list[dict], purpose: str) -> TraceEvent      # ms None 으로 먼저 쓴다(호출 전 commit 에 실림)
    def llm_end(self, ev: TraceEvent, reply: LlmReply | None, error: str | None, ms: int) -> None
    def attach_run(self, run_id: int) -> None                                  # 실행 기록이 생기면 같은 턴의 사건에 run_id
    def end(self, status: Literal["done", "failed", "stopped"], text: str | None) -> None
def context_parts(session, user, chat_session_id, ui, tools: list[dict]) -> list[dict]   # [{name, chars}] CONTEXT_PARTS 차례
```
- 루프 고리(줄 수 늘림은 20줄 안): 사용자 메시지 저장 뒤 `TraceLog` → `context` 한 번 → LLM 호출마다 `llm_start`(commit 전) / `llm_end` → 실행 기록이 생기면 `attach_run` → 끝 상태마다 `end`. input_text = 메시지 JSON(메시지마다 4,000자, 전체 60,000자에서 자름), output_text = 답 글 + 도구 호출 JSON. 기록 실패는 경고만(턴을 바꾸지 않음).
- `store/traces.py`: `turns(session, limit) -> list[TurnRow]`, `events(session, turn_id) -> list[TraceEvent]`, `usage(session, *, days, group) -> UsageOut`.
- API(모두 관리자만, 아니면 403 `admin_only`):
  - `GET /api/devconsole/turns?limit=30` → `[{turn_id, chat_session_id, user_name, request(60자), started_at, status: running|done|failed|stopped, llm_calls, tool_calls, tokens, cost, ms}]` 새것부터.
  - `GET /api/devconsole/turns/{turn_id}` → `{turn, structure: {nodes, loop_count, limit: MAX_STEPS}, timeline}`.
    - nodes(차례): `request` 요청 받기 · `context` 컨텍스트 조립 · `skill` 스킬 찾기 · `plan` 워크플로우 짜기 · `judge` 판단 (모델) · `tool` 도구 실행 · `check` 조건 점검 · `approval` 승인 판단 · `respond` 응답·기록. 각 `{key, label, state: past|now|todo|skipped, count, detail: {in, out, ms, settings}}`.
    - 규칙: `skill` 은 늘 `skipped`(detail.in "스킬은 묶음 3에서 — 지금은 늘 없음"). `plan` = 첫 llm 사건, `judge` = 나머지 llm(count). 단계(`workflow_steps`)는 도구 이름으로: `harness.check`·`generate.run` → `check`, `out.submit_change`·`scenario.submit`·`rules.propose` → `approval`, 그 밖 → `tool`. `respond` 는 `end` 사건이 있으면 past. 턴이 돌고 있으면 끝나지 않은 사건(ms 없는 llm, running 단계)의 칸이 `now`, 없으면 `judge`. 들르지 않은 칸은 `todo`. `loop_count` = llm 사건 수. `context` detail 에 parts(이름·글자 수·첫 호출 입력 토큰을 글자 비례로 나눈 추정 토큰·비중 %). settings: `check` "점검 한도 5회", `approval` "승인 수준: <approval_mode 한국어>".
    - timeline: context·llm·tool(단계)·inner_llm(턴 시간 안의 이 대화 `llm_calls` 가운데 purpose 가 normal 이 아닌 것) 사건을 시각 순 `{seq, kind, label, started_at, ms, model, input_tokens, output_tokens, cost, ok, error, input_text, output_text}`.
  - `GET /api/devconsole/usage?days=14&group=model|user|day|purpose`(days 1..90) → `{rows: [{key, calls, input_tokens, output_tokens, cost, failed}], totals: {...}, cost_known: bool, searches: {calls, failed}}` — `llm_calls`(user 는 대화 주인 이름, 대화 없으면 "대화 밖"), `searches` 는 `evidence_searches`. cost 는 NULL 아닌 것만 더하고 하나도 없으면 null. rows 는 day 면 날짜 순, 그 밖은 calls 많은 순.

- [ ] **Step 1: 실패하는 시험**
```python
async def test_turn_writes_context_llm_and_end(run, session):
    await run(ScriptedLlm([calls("schedule.read", {}), reply("두 개입니다")]), "몇 개야?")
    ev = session.query(TraceEvent).order_by(TraceEvent.seq).all()
    assert [e.kind for e in ev] == ["context", "llm", "llm", "end"] and len({e.turn_id for e in ev}) == 1 and ev[1].model and ev[-1].label == "done"
async def test_llm_event_is_written_before_the_call(run_with_slow_llm, other_session):   # 호출 중에 다른 연결로 ms None 인 llm 사건이 보인다
async def test_trace_never_contains_the_key(run_real_client, session):                   # Review Focus 4 — FakeLiner + LlmClient(KEY)
    await run_real_client("안녕"); assert all(KEY not in (e.input_text + e.output_text) for e in session.query(TraceEvent))
def test_admin_only(client, user): assert client.get("/api/devconsole/turns", headers=user).json()["code"] == "admin_only"
def test_turn_structure(client, admin, finished_turn):               # schedule.read 한 번 뒤 답
    s = client.get(f"/api/devconsole/turns/{finished_turn}", headers=admin).json()["structure"]; n = {x["key"]: x for x in s["nodes"]}
    assert [x["key"] for x in s["nodes"]] == ["request", "context", "skill", "plan", "judge", "tool", "check", "approval", "respond"]
    assert (n["skill"]["state"], n["plan"]["state"], n["judge"]["count"], n["tool"]["count"], n["check"]["state"], n["respond"]["state"]) == ("skipped", "past", 1, 1, "todo", "past")
    assert (s["loop_count"], s["limit"]) == (2, 12)
def test_running_turn_marks_now(client, admin, running_turn_with_running_step):  # 단계 tool "harness.check" running → check 가 now
def test_context_parts(client, admin, finished_turn): parts = node("context")["detail"]["in"]["parts"]; assert [p["name"] for p in parts] == list(CONTEXT_PARTS)
def test_usage_by_model(client, admin, session):
    add_calls(session, [("claude-sonnet-5.5", 100, 20, None, True), ("claude-sonnet-5.5", 50, 10, None, True), ("liner-mark-1.3", 30, 5, None, False)])
    u = client.get("/api/devconsole/usage?group=model", headers=admin).json()
    assert u["rows"] == [{"key": "claude-sonnet-5.5", "calls": 2, "input_tokens": 150, "output_tokens": 30, "cost": None, "failed": 0},
                         {"key": "liner-mark-1.3", "calls": 1, "input_tokens": 30, "output_tokens": 5, "cost": None, "failed": 1}] and u["cost_known"] is False
def test_usage_by_user_labels_calls_outside_chat(...): rows 에 "대화 밖"
```
- [ ] **Step 2~5:** 실패 확인 → 구현(기존 `tests/agent/test_loop.py` 전부 통과) → 통과 확인 → 커밋 `feat: 실행 추적 기록과 개발 콘솔 API`

---

### Task 30: 실적 입력 — 대화 도구 · 스케줄표 Data Date·가중치·지연 알림 [opus] · G3

**Files:** Create `backend/app/tools/data/{find_activity,record_actual}.py`, `backend/app/agent/prompts/guides/actuals.md`, `backend/tests/tools/test_actual_tools.py`, `frontend/src/programs/schedule/table/{DataDateField.tsx,DelayNotice.tsx}` + 시험; Modify `frontend/src/programs/schedule/table/{Toolbar.tsx,TableTab.tsx,columns.tsx}`, `frontend/src/programs/schedule/scheduleStore.ts` + 그 시험

**Interfaces — Consumes:** `propose(..., force_auto=True)`(Task 26), `view_data`, `load`, `context.today`, `explained_schedule_errors`, `patchSchedule`·`putWeightMode`(Task 25), 계획 1 Task 16 의 `useSchedule`(`load`, `patchActivity`) 와 표 칸 정의
**Produces:**
- 도구 `schedule.find {query: str(1..50), limit: int(1..10) = 5}` (program `schedule`) → `{matches: [{id, name, wbs, kind, es, ef, plan_start, plan_finish, progress, actual_start, actual_finish, status, tf}]}` — id 가 같은 것 먼저, 그다음 이름(공백 빼고 소문자)에 query 가 든 것, 일정 차례. 없으면 빈 목록.
- 도구 `schedule.record_actual {activity_id: str, progress: float(0..1) | null, actual_start: date | null, actual_finish: date | null, data_date: date | null}` (program `schedule`, mutates; 셋 가운데 적어도 하나) → `{version, applied: true, approval_id, data_date, activity: {id, name, progress, actual_start, actual_finish, rd, es, ef, status}, assumed: [str], finish: {before, after}, delay: {activity_id, late_days, finish_delta} | null, before_version, after_version}` + `card {kind: "actual_recorded", schedule_id, activity_id, name, progress, assumed, delay, version}`.
  규칙 [제안] (코드가 채우고 `assumed` 에 적는다):
  - Data Date = 인자 → 일정의 data_date → `context.today()`. 인자가 있고 다르면 일정 data_date 를 바꾼다.
  - `actual_finish` 가 있으면 progress = 1. 진도 > 0 인데 실제 시작이 없으면: 지금 계산 ES ≤ Data Date 면 ES, 아니면 Data Date — `"실제 시작일을 2027-03-01로 두었습니다(계획 시작일)."` / `(Data Date)`. 진도 1 인데 실제 종료가 없으면 Data Date — `"실제 종료일을 Data Date 2027-03-03로 두었습니다."`.
  - 진행 중이면 `rd = max(1, ceil(od × (1 − progress)))` — `"남은 기간을 2일로 두었습니다(원래 기간 × (1 − 진도))."`.
  - 실적 날짜 > Data Date → ToolError `"실적 날짜가 Data Date(2027-03-03)보다 뒤일 수 없습니다."` · 종료 < 시작 → `"실제 종료일이 실제 시작일보다 앞설 수 없습니다."` · 마일스톤은 진도 0 또는 1 만 · 없는 id → `"없는 액티비티입니다: Z"`.
  - 저장: `propose(kind change, title "<id> 실적 <n>%", force_auto=True)` — 준공이 바뀌어도 자동 적용, 승인 표 `auto` 줄·`restore_to`.
  - 지연 감지: 그 액티비티의 Plan 대비 늦음(근무일)이 저장 뒤에 늘었으면 `delay = {activity_id, late_days: 늘어난 일수, finish_delta: 근무일(전 준공 → 뒤 준공)}`.
- `guides/actuals.md`: 진도·실제 날짜를 말하면 `schedule__find`(고른 액티비티가 있으면 그것) → `schedule__record_actual`(퍼센트는 0~1, 날짜는 날짜 도우미 것만). `delay` 가 오면 바로 `delay__record`(source "actual", days = late_days, before_version)를 부르고 영향을 말한 뒤 만회안(`shorten__make`)을 제안한다. `assumed` 는 꼭 말한다.
- 스케줄표: 머리줄 Data Date 를 누르면 날짜 칸(`DataDateField`) → `patchSchedule` → 응답 view 로 다시 그림(409 는 Task 16 처럼 다시 불러옴). 도구줄 "가중치: 기간 비례 ▾ / 직접 입력" → `putWeightMode` → 다시 불러옴. manual 모드에서 가중치(%) 칸은 고칠 수 있고 `manual_weight` 로 PATCH, `summary.weight_missing > 0` 이면 머리줄 경고 "가중치 없는 작업 n개".
- 지연 알림(`DelayNotice`): 고침 응답에서 어떤 액티비티의 status 가 `late` 가 되거나 늦음이 늘었으면 창 안 띠 "A2020 이(가) Plan보다 3일 늦어졌습니다." + [지연 기록 열기] → `open('delays', { id, activity, days })` · [닫기].

- [ ] **Step 1: 실패하는 시험** (픽스처: A 5일 → B 5일, 버전 1 Plan: A 3/1~3/5, B 3/8~3/12)
```python
async def test_progress_fills_start_and_remaining(ctx_ab):                                      # Review Focus 3
    o = (await call("schedule.record_actual", {"activity_id": "A", "progress": 0.6, "data_date": "2027-03-03"}, ctx_ab)).output
    assert (o["activity"]["actual_start"], o["activity"]["rd"], o["activity"]["ef"], o["delay"]) == ("2027-03-01", 2, "2027-03-04", None)
    assert o["assumed"][0] == "실제 시작일을 2027-03-01로 두었습니다(계획 시작일)." and o["applied"] is True
async def test_late_progress_reports_delay(ctx_ab):
    o = (await call(..., {"activity_id": "A", "progress": 0.2, "data_date": "2027-03-03"}, ctx_ab)).output
    assert o["delay"] == {"activity_id": "A", "late_days": 1, "finish_delta": 1} and (o["before_version"], o["after_version"]) == (1, 2)
async def test_actual_input_is_auto_applied_with_undo(ctx_ab, session):
    o = ...(progress 0.2)...; row = session.get(Approval, o["approval_id"])
    assert row.status == "auto" and row.restore_to == 1 and "finish_changed" in row.reasons_json
async def test_actual_after_data_date_is_refused(ctx_ab, session):                              # Review Focus 3
    r = await call(..., {"activity_id": "A", "actual_finish": "2027-03-10", "data_date": "2027-03-03"}, ctx_ab)
    assert r.error == "실적 날짜가 Data Date(2027-03-03)보다 뒤일 수 없습니다." and current_version(session) == 1
async def test_done_without_finish_uses_data_date(ctx_ab):
    o = ...({"activity_id": "A", "progress": 1, "data_date": "2027-03-03"}); assert o["activity"]["actual_finish"] == "2027-03-03" and "실제 종료일을 Data Date 2027-03-03로 두었습니다." in o["assumed"]
async def test_missing_data_date_uses_today(ctx_ab, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 3)); assert ...({"activity_id": "A", "progress": 0.6})["data_date"] == "2027-03-03"
async def test_find_by_id_then_name(ctx_ab): assert [m["id"] for m in (await call("schedule.find", {"query": "b"}, ctx_ab)).output["matches"]] == ["B"]
async def test_unknown_activity(ctx_ab): assert (await call("schedule.record_actual", {"activity_id": "Z", "progress": 0.5}, ctx_ab)).error == "없는 액티비티입니다: Z"
```
```ts
test('data date edit patches the schedule', async () => { mockPatchSchedule(viewWith({ version: 2, data_date: '2027-06-01' })); await userEvent.click(screen.getByRole('button', { name: /Data Date/ })); await userEvent.type(dateInput(), '2027-06-01{Enter}'); expect(lastBody()).toEqual({ data_date: '2027-06-01', base_version: 1 }); expect(await screen.findByText(/2027\.06\.01/)).toBeVisible() })
test('manual weight mode makes the weight cell editable and warns about missing weights', async () => { mockWeightMode('manual', viewWith({ weight_mode: 'manual', summary: { weight_missing: 3 } })); await chooseWeightMode('직접 입력'); expect(within(cell('A2020', '가중치(%)')).getByRole('textbox')).toBeInTheDocument(); expect(screen.getByText('가중치 없는 작업 3개')).toBeVisible() })
test('a newly late activity offers the delay window', async () => { mockPatch(viewWith({ A2020: { status: 'late +3' } })); await editCell('A2020', '진도(%)', '20'); await userEvent.click(await screen.findByRole('button', { name: '지연 기록 열기' })); expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', activity: 'A2020', days: '3' }) })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(화면 검수 스크린샷) → 커밋 `feat: 실적 입력 — 대화와 스케줄표`

---

### Task 31: 일정판 CPM 탭 [fable] · G3

**Files:** Create(덮어씀) `frontend/src/programs/schedule/cpm/{CpmTab.tsx,CpmToolbar.tsx,CpmSummary.tsx,NodeCard.tsx,Edges.tsx,DetailPanel.tsx,RelationEditor.tsx,layout.ts,cards.ts,cpmApi.ts,exportPng.ts,cpm.css}` + `*.test.ts(x)`

**Interfaces — Consumes:** `useSchedule`(`view`, `selected`, `select`, `setPredecessors`), `predecessors.{parse, format}`(Task 16), ScheduleView 의 `es, ef, ls, lf, tf, ff, critical, status, plan_start, plan_finish, od, rd, progress, actual_*`(Task 21·25), `GET /api/schedules/{id}/progress` 의 `cpm`(Task 24), `GET /api/schedules/{id}/scenarios?status=applied` 의 `recovery`(Task 26), 시안 `ScheduleCPM.dc.html`, 형태 참고 `CPM-1920.png`
**Produces:**
```ts
// layout.ts
export const CARD_W = 248, CARD_H = 168, GAP_X = 96, GAP_Y = 32, PAD = 24;
type ViewMode = 'all' | 'critical' | 'selected';
layoutNetwork(view: ScheduleView, opt: { mode: ViewMode; selected?: string | null; wbs?: string | null }):
  { nodes: { id: string; x: number; y: number; col: number; row: number }[];
    edges: { from: string; to: string; type: RelType; lag: number; critical: boolean; label: string; points: [number, number][] }[];
    width: number; height: number }
// col = 보이는 노드 안의 가장 긴 선행 사슬 깊이, 같은 col 은 (es, wbs, id) 순. x = PAD + col·(CARD_W+GAP_X), y = PAD + row·(CARD_H+GAP_Y)
// 꺾은선: FS 선행 오른쪽 가운데 → 후행 왼쪽 가운데, SS 왼→왼, FF 오른→오른, SF 왼→오른. label = format([{pred,type,lag}]) 의 관계 부분("FS", "SS+15")
// cards.ts
cardRows(a: Activity, layers: { plan: boolean; actual: boolean; cpm: boolean }): { label: string; value: string }[]
statusLabel(a): '완료' | '진행 중' | '미착수'
planChip(status: string): { text: string; tone: 'danger' | 'success' | 'neutral' }   // 'late +4'→'+4일' danger · 'early -1'→'−1일' success · 'on_plan'→'계획 내' · 'new'→'새 액티비티' · 'done'→'완료'
// exportPng.ts
svgMarkup(svg: SVGSVGElement): string ; exportPng(svg, fileName): Promise<void>   // SVG → Image → canvas → PNG 내려받기
```
- 화면(시안 「일정판 CPM」): 위 도구줄 — 층 단추 Plan · Actual · CPM, 보기(전체 / 크리티컬 경로만 / 선택 항목), 찾기 칸 + [찾기](이름·ID, 첫 일치를 고르고 화면 가운데로), [자동 배치](끌어 옮긴 자리 버림), [맞춤], WBS 필터(맨 위 묶음, "전체 WBS"), [범례], [PNG 내보내기]. 오른쪽 위 "노드 n · 관계 n · 크리티컬 n · 음수 플로트 n".
- 요약 줄 넷: Plan 준수율(`cpm.plan_compliance`, 없으면 "—"), 크리티컬 경로 총 변동(`+1일 · 최대 A`), 만회 계획 달성률(가장 최근 반영된 단축안의 `achieved/planned_gain` %, 없으면 "— 만회 계획 없음"), 프로젝트 완료 편차(`+1일 · Plan 03.12 → 03.15`).
- 그림은 전부 SVG: 카드(머리: ◇(마일스톤)·ID·상태 / 이름 / Plan 대비 칩 / 줄: ES/EF · LS/LF · OD/RD · TF/진도 · Plan). 층 끄기: CPM → ES/EF·LS/LF·TF 줄과 크리티컬 빨강 숨김, Plan → Plan 줄·Plan 대비 숨김, Actual → 진도·실적 표시 숨김. 크리티컬 카드·관계는 `--danger`. 카드를 끌면 자리만 바뀐다(이 창 메모리). 확대·축소(×1.25)·맞춤은 왼쪽 아래.
- 오른쪽 패널 "상세": 고른 카드의 유형·Plan·Actual·OD/RD·TF/FF·진도·주요 자원·선행·후행(관계·간격). 화살표나 패널의 관계를 누르면 `RelationEditor`(종류 FS/SS/FF/SF, 간격, [삭제], [저장]) → 후행의 선행 목록을 바꿔 `setPredecessors(succ, items)` (오류·409 는 store 가 처리). 카드를 누르면 `select(id)`(화면 맥락은 store 가 알림).
- 200개 노드에서 끌기·확대가 끊기지 않는다(관계선은 바뀐 노드 것만 다시 계산).

- [ ] **Step 1: 실패하는 시험**
```ts
const v = view([a('A', { es: '2027-03-01' }), a('B', { es: '2027-03-04' }), a('D', { es: '2027-03-04', critical: false }), a('C', { es: '2027-03-08' })], [r('A', 'B'), r('A', 'D'), r('B', 'C'), r('D', 'C', 'SS', 15)]);
test('columns follow the longest predecessor chain', () => { const n = Object.fromEntries(layoutNetwork(v, { mode: 'all' }).nodes.map((x) => [x.id, [x.x, x.y]])); expect(n).toEqual({ A: [24, 24], B: [368, 24], D: [368, 224], C: [712, 24] }) })
test('critical mode drops non-critical nodes and their edges', () => { const g = layoutNetwork(v, { mode: 'critical' }); expect(g.nodes.map((x) => x.id)).toEqual(['A', 'B', 'C']); expect(g.edges.every((e) => e.from !== 'D' && e.to !== 'D')).toBe(true) })
test('selected mode keeps direct neighbours', () => expect(layoutNetwork(v, { mode: 'selected', selected: 'D' }).nodes.map((x) => x.id).sort()).toEqual(['A', 'C', 'D']))
test('edge label shows type and lag', () => expect(layoutNetwork(v, { mode: 'all' }).edges.find((e) => e.from === 'D')!.label).toBe('SS+15'))
test.each([['late +4', '+4일'], ['early -1', '−1일'], ['on_plan', '계획 내'], ['new', '새 액티비티']])('plan chip %s', (s, t) => expect(planChip(s).text).toBe(t))
test('turning the CPM layer off hides float rows and critical color', async () => { render(<CpmTab windowId="w1" scheduleId={1} />); await userEvent.click(screen.getByRole('button', { name: 'CPM' })); expect(card('A').querySelector('.critical')).toBeNull(); expect(within(card('A')).queryByText('LS/LF')).toBeNull() })
test('editing a relation saves the successor predecessors', async () => { await userEvent.click(edge('B', 'C')); await userEvent.selectOptions(screen.getByLabelText('종류'), 'SS'); await userEvent.clear(screen.getByLabelText('간격')); await userEvent.type(screen.getByLabelText('간격'), '2'); await userEvent.click(screen.getByRole('button', { name: '저장' })); expect(setPredSpy).toHaveBeenCalledWith('C', [{ pred: 'B', type: 'SS', lag: 2 }, { pred: 'D', type: 'SS', lag: 15 }]) })
test('summary line shows compliance, variance, recovery and finish', async () => { mockProgress({ cpm: { plan_compliance: { pct: 83, done: 5, due: 6 }, critical_variance: { days: 4, max_id: 'A2020' }, finish_variance: { days: 4, plan: '2027-11-24', current: '2027-11-28' } } }); mockScenarios([{ recovery: { planned_gain: 5, achieved: 3 } }]); expect(await screen.findByText('83%')).toBeVisible(); expect(screen.getByText('60%')).toBeVisible(); expect(screen.getByText(/Plan 11\.24 → 11\.28/)).toBeVisible() })
test('no applied recovery says so', async () => { mockScenarios([]); expect(await screen.findByText('만회 계획 없음')).toBeVisible() })
test('find selects the first match', async () => { await userEvent.type(screen.getByPlaceholderText('코드·이름 검색'), '작업 C'); await userEvent.click(screen.getByRole('button', { name: '찾기' })); expect(selectSpy).toHaveBeenCalledWith('C') })
test('png export serializes the network svg', () => expect(svgMarkup(networkSvg())).toContain('data-node="A"'))
test('two hundred nodes render', () => { renderWith(bigView(200)); expect(document.querySelectorAll('[data-node]')).toHaveLength(200) })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(화면 검수: 1600×900·900×600, 두 테마, 시안·참고 그림과 나란히 비교 메모) → 커밋 `feat: 일정판 CPM 탭`

---

### Task 32: 일정판 진행 탭 (S-커브) [fable] · G3

**Files:** Create(덮어씀) `frontend/src/programs/schedule/progress/{ProgressTab.tsx,KpiRow.tsx,SCurve.tsx,MilestoneTable.tsx,WbsTable.tsx,SpiTrend.tsx,DelayTop.tsx,Lookahead.tsx,progressApi.ts,scurve.ts,progress.css}` + `*.test.ts(x)`

**Interfaces — Consumes:** `GET /api/schedules/{id}/progress`(Task 24, 모양 그대로 타입으로), `useSchedule`(view.weight_mode·version 이 바뀌면 다시 불러옴), `exportPng`과 같은 방식(이 폴더에 따로 — 다른 탭 파일을 import 하지 않음), 시안 `ScheduleProgress.dc.html`
**Produces:**
```ts
// scurve.ts
scaleCurve(curve: CurvePoint[], box: { w: number; h: number; pad: number }, dataDate: string):
  { plan: string; actual: string; forecast: string; bars: { x: number; w: number; plan: number; actual: number | null }[];
    dataDateX: number; yOf(pct: number): number }      // 경로는 SVG d, null 점은 건너뜀(실적은 Data Date 에서 끝, 예측은 거기서 시작)
weekLabel(dataDate: string, planStart: string, planFinish: string): string   // "14주차 / 39주" — n = ceil((Data Date − Plan 시작) 일 / 7), N = ceil((Plan 준공 − Plan 시작 + 1) 일 / 7)
```
- 화면(시안 「일정판 진행」): 위 줄 Data Date · 단위 [주][월] · "가중치: 기간 비례|직접 입력" · [그림 내보내기]. 상태 띠: spi < 1 이면 "계획보다 늦음 · 13주차 / 39주 · 준공 +n일 · 준공 여유 m일"(위험색), 아니면 "계획대로". KPI 넷: 계획 공정률 · 실적 공정률(+ 차이 %p) · 일정 수행 지수(`spi`, "1.00 이상이면 계획대로") · 준공(지금·Plan 대비·기한) · 액티비티(완료/진행/지연).
- S-커브 카드: 계획 누적(실선) · 실적 누적(굵은 실선, Data Date 까지) · 지연 영향 반영(점선, Data Date 부터) · 주간(또는 월간) 계획·실적 막대 · Data Date 세로선 "Data Date 03.03 · 계획 20.0% · 실적 10.0%". 오른쪽 열: 마일스톤 추적 표 · WBS 묶음별 표(가중치·계획·실적·차이, 계획 위치 눈금) · 일정 수행 지수 추이(0.90 선 "0.90 아래: 대응 필요") · 지연 상위 액티비티 + [지연 기록 열기](→ `open('delays', {id})`) [만회 계획 요청](→ `open('chat', { ask: '지연을 만회할 계획을 만들어 줘' })`) · 앞으로 3주(시작 예정·종료 예정·선행 미완).
- "보고서에 넣기"는 묶음 3(보고서)에서 — 이 탭에는 두지 않는다.

- [ ] **Step 1: 실패하는 시험** (응답은 Task 24 시험의 값 그대로)
```ts
test('kpis show plan, actual, gap and spi', async () => { mockProgress(P); render(<ProgressTab windowId="w1" scheduleId={1} />); expect(await screen.findByText('20.0%')).toBeVisible(); expect(screen.getByText('10.0%')).toBeVisible(); expect(screen.getByText('−10.0%p')).toBeVisible(); expect(screen.getByText('0.50')).toBeVisible() })
test('late status banner', async () => { expect(await screen.findByText(/계획보다 늦음/)).toBeVisible() })
test('actual path stops at the data date and forecast starts there', () => { const s = scaleCurve(P.curve, { w: 800, h: 300, pad: 20 }, '2027-03-03'); expect(s.actual.split(/[ML]/).filter(Boolean)).toHaveLength(2); expect(s.forecast.startsWith(`M${s.dataDateX}`)).toBe(true); expect(s.yOf(100)).toBe(20) })
test('week label', () => expect(weekLabel('2027-06-01', '2027-03-01', '2027-11-24')).toBe('14주차 / 39주'))
test('unit switch refetches by month', async () => { await userEvent.click(screen.getByRole('button', { name: '월' })); expect(lastUrl()).toContain('unit=month') })
test('milestone and wbs tables', async () => { expect(await screen.findByText('지연 +1일')).toBeVisible(); expect(within(wbsTable()).getByText('−20.0')).toBeVisible() })
test('lookahead marks blocked starts', async () => { expect(await screen.findByText('선행 미완: A')).toBeVisible() })
test('buttons open the delay window and the chat', async () => { await userEvent.click(await screen.findByRole('button', { name: '만회 계획 요청' })); expect(openSpy).toHaveBeenCalledWith('chat', { ask: '지연을 만회할 계획을 만들어 줘' }) })
test('assumed data date is labeled', async () => { mockProgress({ ...P, data_date_assumed: true }); expect(await screen.findByText(/오늘로 가정/)).toBeVisible() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(화면 검수 스크린샷) → 커밋 `feat: 일정판 진행 탭`

---

### Task 33: 지연 기록 — 저장·분석 API·도구 [opus] · G3

**Files:** Modify `backend/app/store/delays.py`; Create `backend/app/programs/delays/{__init__,router,service,schemas}.py`, `backend/app/tools/respond/{record_delay,analyze_delay}.py`, `backend/app/agent/prompts/guides/delay.md`, `backend/tests/programs/test_delays_api.py`, `backend/tests/tools/test_delay_tools.py`

**Interfaces — Consumes:** `app.core.delay.{analyze, diff_impact, DelayInputError}`(Task 22), `store.delays.{open_events, to_core, delayed_base}`·`store.scenarios.create`(Task 26), `load`·`prepare_stored`·`view_data`·`context.today`, 표 `DelayEventRow`
**Produces:**
- store 더함: `create(session, *, schedule_id, activity_id, start_date, days, cause, responsibility, daily_cost, evidence, source, created_by, status="open") -> DelayEventRow` · `get(session, eid)` · `update(session, row, **fields)` · `delete(session, row)` · `listed(session, schedule_id)`(발생일·id 순) · `save_impacts(session, rows, analysis, version)`.
- 분석(`service.analyze(session, sid)`): 지금 버전을 `prepare_stored` 한 일정에 열린 사건을 `core.delay.analyze` → 사건마다 `impact_json`·`analyzed_version` 저장. 반영된 사건은 다시 넣지 않고 저장된 영향을 그대로 쓴다. GET 은 열린 사건 가운데 `analyzed_version != 지금 버전` 인 것이 있으면 다시 분석해 저장한다.
- API(`/api/schedules/{id}/delays`, 응답은 모두 `DelaysOut`):
```
DelaysOut = {schedule_id, version, events: [DelayOut],
  totals: {finish_impact, by_responsibility: {owner, ours, force, undecided}, absorbed, absorbed_events, cost: int | null, open_count},
  finish: {plan, current, with_open, deadline, deadline_float}}        # with_open = 열린 사건을 넣은 준공, deadline_float = 근무일(with_open → 기한)
DelayOut = {id, activity_id, activity_name, start_date, days, cause, responsibility, daily_cost, evidence, source, status,
  impact: {applied, note, finish_before, finish_after, finish_delta, absorbed, milestones: [{activity_id, name, before, after, delta}],
           critical_added, critical_removed, affected, new_clashes: [{resource_id, name, first, days, over}], cost} | null,
  analyzed_version, reflected_version, stale, created_by, created_at}
```
  - `GET` · `POST {activity_id, start_date, days(1..365), cause(1..200), responsibility, daily_cost?: int ≥ 0, evidence?: str ≤ 200}`(source `user`) · `PATCH /{eid}`(같은 칸 일부) · `DELETE /{eid}` · `POST /analyze` · `POST /scenario {event_ids?: [int]}` → `{scenario_id}`(`delayed_base` 로 source `delay`, 이름 "지연 반영안 (n건)", `delay_event_ids`).
  - `GET /api/schedules/{id}/delays/preview` → `{view: ScheduleView, moved: [{activity_id, name, before: {start, finish}, after: {start, finish}}]}` — 열린 사건을 넣은 일정(저장 안 함). 모양과 view 를 만드는 함수는 조건 미리 보기(계획 1 Task 18)와 같은 것을 쓴다(이름은 그 보고서). 설계 8-1 "간트의 흐린 막대"로 지연 영향을 보이는 데 쓴다.
  - 오류: 없는 액티비티 422 `invalid_delay` "없는 액티비티입니다: Z" · 반영된 사건의 일수·대상·시작일 고침 409 `delay_reflected` "일정에 반영된 사건은 일수·대상·시작일을 바꿀 수 없습니다." · 반영된 사건 지우기 409 `delay_reflected` "일정에 반영된 사건은 지울 수 없습니다." · 열린 사건 없이 scenario 422 `no_open_delays` "열린 지연 사건이 없습니다.".
- 도구 `delay.record {activity_id, days: int(1..365), cause: str(1..200), responsibility: "owner"|"ours"|"force"|"undecided" = "undecided", daily_cost: int(≥0) | null, start_date: date | null, source: "chat"|"actual" = "chat", before_version: int | null}` (program `delays`, mutates) — start_date 기본 = 일정 data_date 또는 `context.today()`. source `actual` 은 `before_version` 필수(없으면 ToolError "실적에서 감지한 지연은 before_version 이 필요합니다.")이고 바로 `reflected`(`reflected_version` = 지금 버전), 영향 = `diff_impact(before_version 일정, 지금 일정)`. 출력 `{event_id, status, impact, totals}` + `card {kind: "delay_impact", schedule_id, event_id, activity_id, name, days, status, impact, totals}` + `open_window {program: "delays", params: {id, event}}`.
- 도구 `delay.analyze {}` (program `delays`) → `{finish, totals, events: [{event_id, activity_id, days, status, finish_delta, absorbed}]}`.
- `guides/delay.md`: 지연을 말하면("비 때문에 골조가 3일 밀렸어") `schedule__find` → `delay__record`(원인·책임·하루 금액은 말한 것만, 모르면 책임 undecided — 둘 다 빠졌으면 카드 질문 둘로 물어도 된다) → 준공 영향·여유로 흡수된 일수·크리티컬 변화·비용을 결과 그대로 말한다. 만회 계획을 원하면 `shorten__make`. 지연은 일정을 바꾸지 않는다(반영은 비교판·승인).

- [ ] **Step 1: 실패하는 시험** (`sid3` = A 3일 → B 2일, A → C 1일, 준공 3/5)
```python
def test_record_and_analyze_on_critical(client, admin, sid3):
    r = post(client, admin, sid3, {"activity_id": "B", "start_date": "2027-03-04", "days": 2, "cause": "우천", "responsibility": "force"})
    i = r["events"][0]["impact"]; assert (i["finish_delta"], i["absorbed"], r["finish"]["with_open"], r["totals"]["by_responsibility"]["force"]) == (2, 0, "2027-03-09", 2)
def test_float_absorbs_noncritical(client, admin, sid3):
    r = post(..., {"activity_id": "C", "start_date": "2027-03-04", "days": 1, "cause": "자재 늦음", "responsibility": "owner"})
    assert (r["events"][0]["impact"]["absorbed"], r["events"][0]["impact"]["critical_added"], r["totals"]["absorbed_events"]) == (1, ["C"], 1)
def test_each_event_gets_its_share_in_start_order(client, admin, sid3):
    post(... B, start 3/3, days 2 ...); r = post(... C, start 3/2, days 1 ...)
    assert [(e["activity_id"], e["impact"]["finish_delta"]) for e in r["events"]] == [("C", 0), ("B", 2)]
def test_cost_is_finish_delta_times_daily_cost(client, admin, sid3):
    r = post(... B +2, "daily_cost": 3_100_000 ...); assert r["events"][0]["impact"]["cost"] == 6_200_000 and r["totals"]["cost"] == 6_200_000
def test_reflected_event_is_not_inserted_again(client, admin, session, sid3):                      # Review Focus 1
    post(... B +2 ...); sc = client.post(f"/api/schedules/{sid3}/delays/scenario", json={}, headers=admin).json()["scenario_id"]
    approve(client, admin, submit(client, admin, sid3, sc))
    r = get(client, admin, sid3); e = r["events"][0]
    assert (e["status"], e["impact"]["finish_delta"], r["finish"]["current"], r["finish"]["with_open"]) == ("reflected", 2, "2027-03-09", "2027-03-09")
    r2 = post(... B +1 ...); assert r2["events"][-1]["impact"]["finish_delta"] == 1 and r2["finish"]["with_open"] == "2027-03-10"
def test_reflected_event_is_locked(client, admin, reflected_event): assert patch(..., {"days": 5}).status_code == 409 and patch(...).json()["code"] == "delay_reflected"
def test_unknown_activity_is_422(client, admin, sid3): assert post_raw(..., {"activity_id": "Z", ...}).json() == {"code": "invalid_delay", "message": "없는 액티비티입니다: Z", "detail": None}
def test_scenario_from_open_delays(client, admin, sid3): two open events → scenario delay_event_ids == [e1, e2] and summary finish == with_open
def test_no_open_delays_scenario_is_422(client, admin, sid3): code "no_open_delays"
def test_preview_shows_open_delays_without_saving(client, admin, sid3):
    post(... B +2 ...); p = client.get(f"/api/schedules/{sid3}/delays/preview", headers=admin).json()
    assert p["view"]["finish"] == "2027-03-09" and [m["activity_id"] for m in p["moved"]] == ["B"] and view(client, admin)["version"] == 1
async def test_record_tool_card_and_window(ctx3, events): kinds == ["delay_impact", "open_window"] and events[-1].data == {"program": "delays", "params": {"id": str(sid3), "event": "1"}}
async def test_actual_source_is_reflected_with_version_diff(ctx3, session):   # 버전 2 에서 B rd 를 늘린 뒤
    o = (await call("delay.record", {"activity_id": "B", "days": 2, "cause": "실적 입력에서 감지", "source": "actual", "before_version": 1}, ctx3)).output
    assert o["status"] == "reflected" and o["impact"]["finish_delta"] == 2
async def test_actual_source_needs_before_version(ctx3): error "실적에서 감지한 지연은 before_version 이 필요합니다."
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 지연 기록과 지연 영향 분석`

---

### Task 34: 단축안 도구와 비교 API [opus] · G3

**Files:** Create `backend/app/tools/respond/make_shortening.py`, `backend/app/agent/prompts/shorten_note.md`, `backend/app/agent/prompts/guides/shorten.md`, `backend/app/programs/scenarios/compare.py`, `backend/tests/tools/test_shorten_tool.py`, `backend/tests/programs/test_compare_api.py`; Modify `backend/app/programs/scenarios/{router,schemas}.py`

**Interfaces — Consumes:** `app.core.shorten.{shorten, apply_moves}`(Task 23), `store.delays.delayed_base`·`store.scenarios.{create, listed, get}`(Task 26), `prepare_stored`, `run`, `check`·`assemble_all`·`read_conditions`, `level`, `LlmClient.chat`, `tests/gen_doubles.{ScriptedLlm, FailingLlm}`
**Produces:**
- 도구 `shorten.make {target_days: int(1..365) | null, include_open_delays: bool = true}` (program `compare`, mutates):
  1. `delayed_base`(include_open_delays 가 거짓이면 열린 사건 없이) → 기준 원본 일정. 열린 사건이 있으면 그것만 넣은 "지연 반영안"(source `delay`)을 만든다(같은 사건 묶음의 열린 지연 반영안이 있으면 그것을 쓴다).
  2. 기준 준공(조건 넣고 맞춘 것). 목표: `target_days` → 켜진 finish_by 가운데 가장 이른 기한을 넘으면 근무일(기한 → 기준 준공) → Plan 준공을 넘으면 근무일(Plan → 기준 준공) → 없으면 ToolError `"줄일 목표가 없습니다. 며칠 당길지 알려 주세요(target_days)."`.
  3. `shorten(prepared, target=…)` → 이동이 있는 묶음마다 복사본(source `shorten`, 이름 `"만회안 A · 병행 우선"`): 일정 = `apply_moves(기준 원본, moves, resources=False)`, 조건 = 저장 조건 + add_resource 마다 입력 조건 `{"id": "in.resource_cap.<rid>", "layer": "input", "kind": "resource_cap", "params": {"resource_id", "capacity"}, "text": "<자원> <n><단위>", "source": "단축안"}`(같은 id 가 있으면 바꿈), `moves_json`, `delay_event_ids`, `extra_summary = {gain, base_finish, note, recommended}`.
  4. LLM(`hard`, strict `SHORTEN_NOTE_SCHEMA = {recommended: anyOf[enum A|B|C, null], notes: [{key: enum A|B|C, note: string}]}`, 지시문 `shorten_note.md`, 사용자 메시지 = 안들의 JSON(key·이름·준공·이득·도달·이동 글·위반 수)). 설명에 `\d{4}-\d{2}-\d{2}` 또는 `\d{1,2}월 \d{1,2}일` 이 있으면 그 설명은 `""`. 만든 안에 없는 key 추천은 버린다. 실패·버림이면 코드가 고른다: 도달한 것 → 위반 적은 것 → 이동 적은 것 → 이득 큰 것 → key 순.
  5. 출력·카드 `card {kind: "shorten_options", schedule_id, base: "current"|"s:<지연 반영안 id>", base_finish, target, options: [{scenario_id, key, name, finish, gain, reached, moves: [글], violations, uncheckable, recommended, note}], recommended_scenario_id}` + `open_window {program: "compare", params: {id, base, other: "s:<추천 id>"}}`.
- 비교 API(`compare.py`, 라우터에 등록):
  - `GET /api/schedules/{id}/compare?base=<ref>&other=<ref>` — ref = `current` | `plan` | `v:<n>` | `s:<scenario id>`. 모르는 ref 422 `invalid_ref` "비교할 안을 찾을 수 없습니다: s:999".
```
{base: SideOut, other: SideOut, rows: [RowOut], changed_count}
SideOut = {ref, label, version, finish, plan_delta, deadline_float, critical_count, violations, uncheckable, peak, changes: [str], stale}
RowOut  = {activity_id, name, wbs, base: {start, finish, od} | null, other: {...} | null, start_delta, finish_delta,
           change: "pulled"|"pushed"|"same"|"added"|"removed"|"duration"}     # 차이는 기준 쪽 달력의 근무일, other − base
```
    label: "현재 일정 (버전 n)" · "Plan (버전 m)" · "버전 n" · 복사본 이름. changes: 복사본은 이동 글, 버전은 note. rows 는 기준 차례 다음 비교에만 있는 것.
  - `GET /api/schedules/{id}/compare/summary` → `{sides: [SideOut]}` — 현재 · Plan · 열린(open·submitted) 복사본 새것부터("여러 안 요약 표").
- `guides/shorten.md`: 만회·단축 요청 → `shorten__make`(며칠이라고 했으면 target_days). 결과는 안마다 준공·이득·바꾸는 것·위반을 표처럼 짧게, 추천 안과 그 까닭(설명 글). 반영은 비교판의 [이 안을 반영] 또는 사용자가 고르면 `scenario__submit`.

- [ ] **Step 1: 실패하는 시험** (`sid_chain` = A 6 → B 4 → C 5, 준공 3/19, 입력 조건 finish_by 2027-03-16)
```python
async def test_target_from_deadline_and_distinct_options(ctx_chain):
    o = (await call("shorten.make", {}, ctx_chain_with(ScriptedLlm([note({"recommended": "B", "notes": [{"key": "A", "note": "관계만 바꿉니다"}, {"key": "B", "note": "작업 시간을 늘립니다"}]})])))).output
    assert o["target"] == 3 and [x["key"] for x in o["options"]] == ["A", "B"] and [x["finish"] for x in o["options"]] == ["2027-03-16", "2027-03-16"]
    assert all(x["violations"] == 0 for x in o["options"]) and o["options"][0]["moves"] == ["A 절반 지점에서 B 시작 (FS → SS+3)"]
    assert o["recommended_scenario_id"] == o["options"][1]["scenario_id"]
async def test_llm_failure_falls_back_to_code_pick(ctx_chain_failing_llm):
    o = ...; assert [x["recommended"] for x in o["options"]] == [True, False] and all(x["note"] == "" for x in o["options"])
async def test_llm_note_with_a_date_is_dropped(ctx_chain):                                              # Review Focus 3
    o = ...(note "2027-03-16에 끝납니다" for A)...; assert o["options"][0]["note"] == ""
async def test_open_delays_are_in_the_base(ctx_chain, session):        # 열린 사건 B +2 → 기준 준공 3/23, 목표 5
    o = ...; assert (o["base_finish"], o["target"]) == ("2027-03-23", 5) and o["base"].startswith("s:")
    assert get(session, o["options"][0]["scenario_id"]).delay_event_ids == [event_id]
async def test_shorten_base_skips_reflected_delays(ctx_chain, session):                                 # Review Focus 1
    reflected_event_on_B(session); o = ...; assert (o["base"], o["base_finish"]) == ("current", "2027-03-19")
async def test_no_target_is_tool_error(ctx_sid_no_deadline): error == "줄일 목표가 없습니다. 며칠 당길지 알려 주세요(target_days)."
async def test_add_resource_becomes_input_condition(ctx_two_crane, session):
    c = get(session, option_b_id).conditions_json
    assert {"id": "in.resource_cap.crane", "layer": "input", "kind": "resource_cap", "params": {"resource_id": "crane", "capacity": 2}, "source": "단축안"}.items() <= next(d for d in c if d["id"] == "in.resource_cap.crane").items()
def test_compare_rows(client, admin, sid_chain, scenario_A):
    r = client.get(f"/api/schedules/{sid_chain}/compare?base=current&other=s:{scenario_A}", headers=admin).json(); rows = {x["activity_id"]: x for x in r["rows"]}
    assert (rows["B"]["start_delta"], rows["B"]["finish_delta"], rows["B"]["change"]) == (-3, -3, "pulled") and rows["A"]["change"] == "same" and r["changed_count"] == 2
    assert r["other"]["finish"] == "2027-03-16" and r["base"]["deadline_float"] == -3
def test_compare_summary(client, admin, sid_chain, scenario_A): assert [s["ref"] for s in client.get(f"/api/schedules/{sid_chain}/compare/summary", headers=admin).json()["sides"]] == ["current", "plan", f"s:{scenario_A}"]
def test_unknown_ref_is_422(client, admin, sid_chain): assert ...(other="s:999").json()["message"] == "비교할 안을 찾을 수 없습니다: s:999"
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 단축안 도구와 비교 API`

---

### Task 35: 내 규칙 — 제안·승인·저장·조건 창 [opus] · G3

**선행:** 계획 1 Task 18·19 커밋.

**Files:** Create `backend/app/store/my_rules.py`, `backend/app/tools/out/propose_rule.py`, `backend/app/programs/rules/{__init__,router,service,schemas}.py`, `backend/app/agent/prompts/guides/rules.md`, `backend/tests/tools/test_propose_rule.py`, `backend/tests/programs/test_rules_api.py`, `frontend/src/programs/conditions/MyRules.tsx` + 시험; Modify `backend/app/store/{approvals,links}.py`, `backend/app/agent/{generation,context}.py`, `frontend/src/programs/conditions/{LayerColumn.tsx,Conditions.tsx,condApi.ts}`, `frontend/src/programs/approvals/{ApprovalDetail.tsx,apvApi.ts}` + 그 시험

**Interfaces — Consumes:** `propose`·`links`(Task 26), `app.store.approvals.{create, apply}`, `app.store.settings.approval_mode`, `app.harness.conditions.{Condition, validate_params}`, `generation.generate`(분야 규칙 조립 자리), `context.situation`, 조건 API `preview`·`commit` 의 `{add: Condition}` 변경(Task 18), 승인함 상세 화면(Task 19)
**Produces:**
- `RULE_KINDS = ("min_gap", "max_duration", "duration_per_unit", "text_only", "blocked_period", "calendar")`.
- 도구 `rules.propose {scope: "domain"|"schedule", domain: str | null, condition: {kind, params: dict, text: str(1..200)}, why: str(1..200)}` (program `conditions`, mutates):
  - 종류가 아니면 ToolError `"내 규칙으로 둘 수 없는 종류입니다: finish_by"`, params 가 틀리면 `validate_params` 글. 조건 id `mine.<6자리 16진>`, layer `mine`, source `내 규칙`. domain 기본 = 대상 일정의 분야(일정도 domain 도 없으면 ToolError "어느 분야의 규칙인지 알려 주세요.").
  - scope `domain`: 승인 건 `kind='rule'`, 사유 `["rule_save"]`, `schedule_id=None`, `base_version=0`, `summary_json={"rule": {scope, domain, text, kind, params}}`, `snapshot_json={}`, `link_kind='rule'`, `rule_json`. 승인 수준을 따른다(auto 면 바로 저장). 사건 `approval`.
  - scope `schedule`(ctx.schedule_id 필요): `propose(change, after_conditions = 저장 조건 + 새 조건, link_kind='rule', rule_json, extra_reasons=["rule_save"])` — 승인되면 새 버전에 그 조건이 들어간다.
  - 출력 `{approval_id, applied, rule: {...}}`.
- `store.approvals.apply`: `kind == 'rule'` 이면 일정은 건드리지 않는다. `links.after_apply` 에 `rule` → `my_rules.create(scope, domain, schedule_id, condition_json, approval_id, created_by=requested_by)`.
- `store/my_rules.py`: `create` · `get` · `listed(session, *, domain=None, schedule_id=None)` · `for_generation(session, domain) -> list[Condition]`(켜진 분야 범위) · `set_enabled` · `delete`.
- API `GET /api/rules?domain=&schedule_id=` → `[{id, scope, domain, schedule_id, condition, enabled, created_by, created_at, in_schedule: bool | null}]`(schedule_id 를 주면 그 일정 지금 조건에 같은 id 가 있는가) · `PATCH /api/rules/{id} {enabled}` · `DELETE /api/rules/{id}`(만든 사람이나 관리자, 아니면 403 `not_owner` "만든 사람이나 관리자만 지울 수 있습니다."). 규칙을 끄거나 지워도 이미 그 조건을 가진 일정은 그대로(일정은 사본을 가진다).
- 생성: `generate()` 의 조립을 `assemble(분야 규칙, my_rules.for_generation(session, domain), inputs)` 로.
- 대화 맥락: "지금 상황" 조건 줄 다음에 `- 내 규칙 n개: <글>; <글>`(대상 일정 분야의 분야 범위 + 그 일정 범위, 일정이 없으면 모든 분야 범위, 10개·60자까지) 또는 `- 내 규칙: 없음`.
- `guides/rules.md`: 사용자가 늘 쓰는 방식을 말하면("우리는 층당 골조 10일로 잡아") `rules__propose` 로 제안만 한다 — 저장은 승인 뒤. 자동 점검이 되는 종류를 먼저 고르고, 안 되면 text_only.
- 조건 창 ③ 칸: 내 규칙 목록(범위 배지 "분야 전체 · 건설" / "이 일정", 켜짐 스위치, [지우기]). 이 일정에 없는 분야 규칙은 [이 일정에 넣기] → 조건 미리 보기 `{changes: [{add: {...condition, layer: "mine", source: "내 규칙"}}]}` → 기존 미리 보기 띠 → [확정]. 승인함 상세: `kind === 'rule'` 이면 "내 규칙 저장" 덩어리(글·범위·종류와 값 요약), 전후 표와 [간트에서 보기] 없음.

- [ ] **Step 1: 실패하는 시험**
```python
async def test_domain_rule_needs_approval_then_saves(ctx_sid, session, client, admin):
    r = await call("rules.propose", {"scope": "domain", "condition": {"kind": "max_duration", "params": {"days": 10}, "text": "층당 골조 10일 넘지 않기"}, "why": "늘 그렇게 잡음"}, ctx_sid)
    row = session.get(Approval, r.output["approval_id"]); assert (row.kind, row.reasons_json, session.query(MyRule).count()) == ("rule", ["rule_save"], 0)
    approve(client, admin, row.id); rules = client.get("/api/rules?domain=construction", headers=admin).json()
    assert rules[0]["condition"]["layer"] == "mine" and rules[0]["condition"]["id"].startswith("mine.") and rules[0]["scope"] == "domain"
async def test_schedule_rule_adds_a_mine_condition_in_a_new_version(ctx_sid, client, admin):
    ... approve → view version 2 → client.get(conditions).json()["layers"]["mine"][0]["text"] == "층당 골조 10일 넘지 않기"
async def test_wrong_kind_is_refused(ctx_sid): assert (await call("rules.propose", {... "kind": "finish_by", "params": {"date": "2027-11-30"} ...})).error == "내 규칙으로 둘 수 없는 종류입니다: finish_by"
async def test_rejected_rule_is_not_saved(...)
async def test_generation_assembles_domain_rules(ctx, session): saved max_duration → r = await generate(...); assert any(c.layer == "mine" for c in r.conditions)
def test_context_lists_my_rules(session, admin_user, saved_rule): assert "- 내 규칙 1개: 층당 골조 10일 넘지 않기" in build_context(...)[0]["content"]
def test_only_owner_or_admin_deletes(client, user, saved_rule_by_admin): assert client.delete(f"/api/rules/{saved_rule_by_admin}", headers=user).json()["code"] == "not_owner"
```
```ts
test('my rules column lists rules with scope badges', async () => { mockRules([rule({ scope: 'domain', in_schedule: false })]); render(<Conditions windowId="w1" params={{ id: '1' }} />); expect(await screen.findByText('분야 전체 · 건설')).toBeVisible() })
test('adding a domain rule to this schedule previews an add change', async () => { await userEvent.click(await screen.findByRole('button', { name: '이 일정에 넣기' })); expect(lastPreviewBody().changes).toEqual([{ add: expect.objectContaining({ id: 'mine.a1b2c3', layer: 'mine', source: '내 규칙' }) }]) })
test('approval detail renders a rule save', () => { render(<ApprovalDetail item={detail({ kind: 'rule', reasons: ['rule_save'], summary: { rule: { scope: 'domain', domain: 'construction', text: '층당 골조 10일 넘지 않기', kind: 'max_duration', params: { days: 10 } } } })} />); expect(screen.getByText('내 규칙 저장')).toBeVisible(); expect(screen.getByText('분야 전체 · 건설')).toBeVisible(); expect(screen.queryByRole('button', { name: '간트에서 보기' })).toBeNull() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(조건 창·승인함 화면 검수) → 커밋 `feat: 내 규칙`

---

### Task 36: 지연 기록 화면 [opus] · G4

**Files:** Create `frontend/src/programs/delays/{Delays.tsx,DelayTable.tsx,DelayDetail.tsx,DelayForm.tsx,ActivityPicker.tsx,KpiBar.tsx,delaysApi.ts,format.ts,delays.css}` + `*.test.tsx`; Modify `frontend/src/programs/delays/index.ts`(화면 연결)

**Interfaces — Consumes:** 지연 API·`delays/preview`(Task 33), `GET /api/schedules/{id}`(액티비티 고르기), `useSchedulePreview`(os, 계획 1 Task 18 — 간트 흐린 막대), `useCurrentSchedule`, `useUiContext`, `setTitle`, 시안 `Delay.dc.html`
**Produces:**
- 프로그램 `delays`, params `id`(일정) · `event`(고를 사건) · `activity`·`days`(새 사건 양식을 채워 엶 — Task 30 알림).
- 화면: 위 KPI 넷 — 준공 영향 합계(`+n일`, "Plan 11.24 → 11.28 · 기한 여유 2일"), 책임별 준공 영향(발주처·불가항력·우리·미정), 여유로 흡수된 지연(`n일 · 사건 m건`), 비용 환산(`format.won`: 1,240만 원; null 이면 "—"). 도구줄 [+ 지연 사건] · 책임 필터 · 상태(열림/반영됨) 필터 · [비교판에서 보기](`POST …/delays/scenario` → `open('compare', {id, base: 'current', other: 's:<sid>'})`) · [만회 계획 요청](`open('chat', {ask: '지연 기록을 반영한 만회 계획을 만들어 줘'})`). 표: 발생 · 사건(원인) · 대상 액티비티 · 책임 · 일수 · 여유 흡수 · 준공 영향 · 상태(열림/반영됨 v n/분석 필요). 아래 안내 "사건은 대화나 실적 입력에서도 등록됩니다. 여러 건은 발생 순서대로 넣어 각각의 몫을 계산합니다."
- 오른쪽 상세: 원인·책임·기간·하루 금액·근거 문서 [고치기](열린 사건만 일수·대상 고침, 반영된 사건은 원인·책임·금액만), 영향 분석(준공 `+3일 (여유 흡수 0일)`, 주요 날짜, 크리티컬 패스 "바뀌지 않음"/"A·B 가 새로 크리티컬", 영향 액티비티 n개 [간트에서 보기](열린 사건이면 `delays/preview` 를 받아 `useSchedulePreview` 에 `source: 'delays'` 로 넣은 뒤 — 간트가 밀린 막대와 이전 자리의 흐린 막대를 그린다 — `open('schedule', {id, tab: 'gantt', activity})`, 반영된 사건이면 바로 연다. 창을 닫거나 다른 일정을 고르면 그 미리 보기를 지운다), 자원 "7월 3주 타워크레인 겹침이 새로 생김", 비용), [이 사건 만회안 요청](`open('chat', {ask: '<사건> 지연을 만회할 계획을 만들어 줘'})`) · [다시 분석].
- `ActivityPicker`: WBS 묶음으로 나눈 목록 + 찾기(화면 검수 2). 양식 검사: 일수 1~365, 원인 필수, 하루 금액 0 이상 정수.
- `format.won(v: number | null): string` — null → "—", 1만 원 아래 → "9,000원", 그 밖 → 만 원 단위 반올림 + 천 단위 쉼표 + "만 원".
- "지연 보고서 만들기"는 묶음 4 — 두지 않는다.

- [ ] **Step 1: 실패하는 시험**
```ts
test('kpis summarize totals', async () => { mockDelays(D); expect(await screen.findByText('+2일')).toBeVisible(); expect(screen.getByText('620만 원')).toBeVisible(); expect(screen.getByText(/불가항력 2일/)).toBeVisible() })
test.each([[6_200_000, '620만 원'], [12_400_000, '1,240만 원'], [null, '—']])('won %s', (v, t) => expect(won(v)).toBe(t))
test('adding an event posts and redraws', async () => { await userEvent.click(screen.getByRole('button', { name: '+ 지연 사건' })); await pickActivity('작업 B'); await userEvent.type(screen.getByLabelText('일수'), '2'); await userEvent.type(screen.getByLabelText('원인'), '우천'); await userEvent.click(screen.getByRole('button', { name: '등록' })); expect(lastBody()).toMatchObject({ activity_id: 'B', days: 2, cause: '우천', responsibility: 'undecided' }) })
test('activity picker filters by search', async () => { await openForm(); await userEvent.type(screen.getByPlaceholderText('액티비티 찾기'), '골조'); expect(options()).toHaveLength(2) })
test('params prefill the form', () => { render(<Delays windowId="w1" params={{ id: '1', activity: 'A2020', days: '3' }} />); expect(screen.getByLabelText('일수')).toHaveValue('3') })
test('reflected events cannot change days', async () => { await selectRow('B', 'reflected'); await userEvent.click(screen.getByRole('button', { name: '고치기' })); expect(screen.getByLabelText('일수')).toBeDisabled() })
test('compare button makes a delay scenario and opens the compare window', async () => { mockScenario(9); await userEvent.click(screen.getByRole('button', { name: '비교판에서 보기' })); expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 'current', other: 's:9' }) })
test('gantt button previews open delays as ghost bars', async () => { mockDelayPreview({ view: V, moved: [m('B')] }); await selectRow('B', 'open'); await userEvent.click(screen.getByRole('button', { name: '간트에서 보기' })); expect(previewFor(1)?.source).toBe('delays') /* previewFor = Task 18 미리 보기 저장소에서 일정 1의 것 */; expect(openSpy).toHaveBeenCalledWith('schedule', { id: '1', tab: 'gantt', activity: 'B' }) })
test('recovery request goes to chat', async () => { await userEvent.click(screen.getByRole('button', { name: '만회 계획 요청' })); expect(openSpy).toHaveBeenCalledWith('chat', { ask: '지연 기록을 반영한 만회 계획을 만들어 줘' }) })
test('server error message is shown', async () => { mockPostError(422, { code: 'invalid_delay', message: '없는 액티비티입니다: Z' }); /* 등록 */ expect(await screen.findByText('없는 액티비티입니다: Z')).toBeVisible() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(화면 검수) → 커밋 `feat: 지연 기록 화면`

---

### Task 37: 비교판 화면 [fable] · G4

**Files:** Create `frontend/src/programs/compare/{Compare.tsx,PlanPicker.tsx,SummaryTable.tsx,OverlayChart.tsx,SideBySide.tsx,DiffTable.tsx,SubmitDialog.tsx,WhatIfDialog.tsx,compareApi.ts,rows.ts,compare.css}` + `*.test.ts(x)`; Modify `frontend/src/programs/compare/index.ts`

**Interfaces — Consumes:** 비교 API·요약 API(Task 34), 복사본 API(`submit`·`DELETE`, Task 26), `GET /api/schedules/{id}/versions`, `shared/gantt/{scale.ts(makeScale, barRect, months, weeks), Header.tsx}`(Task 17), `refreshApprovals`, 시안 `Compare.dc.html`
**Produces:**
- 프로그램 `compare`, params `id` · `base`(기본 `current`) · `other`(기본: 열린 복사본 가운데 가장 새것, 없으면 `plan`).
- 위: 기준 ▾ / 비교 ▾(`PlanPicker`: 묶음 "현재·Plan" / "버전"(버전 목록) / "만약에 복사본"(낡음 표시), 찾기) · 보기 [같은 차트][좌우 비교][차이 표] · [+ 만약에 복사본] · [복사본 버리기](비교가 복사본일 때) · [이 안을 반영 (승인함으로)](비교가 열린 복사본일 때).
- 여러 안 요약 표(`SummaryTable`): 안 · 준공 · Plan 대비 · 기한 여유 · 크리티컬 수 · 조건 위반 · 자원 최고 부하 · 바꾸는 것. 줄을 누르면 그 안이 비교가 된다. 낡은 복사본은 "기준 일정이 바뀌었습니다" 배지(반영된 복사본은 `status` 가 applied 라 늘 stale 이므로 배지를 띄우지 않는다).
- 같은 차트(`OverlayChart`): 액티비티마다 윗줄 기준 막대·아랫줄 비교 막대, 비교 막대 색 `pulled` `--success` · `pushed` `--danger` · 같음 회색. [달라진 것만 | 전체], 기한 세로선(`deadline_float` 이 있으면). 좌우 비교(`SideBySide`): 두 간트를 같은 척도로 나란히, 세로 스크롤 맞물림. 차이 표(`DiffTable`): ID · 이름 · 구분 · 시작 차이 · 종료 차이 · OD(기준→비교), 근무일 `−3일`/`+2일`.
- `rows.ts`: `visibleRows(rows, onlyChanged) → RowOut[]`, `deltaText(n: number | null) → string`(`−3일`·`+2일`·`0`·`—`).
- [이 안을 반영]: `SubmitDialog`(제목 기본 = 복사본 이름; PM 11-20: Plan 다시 잡기 체크 없음) → `POST …/submit {title}` → `refreshApprovals()` → `open('approvals', {id: String(approval_id)})`. 409 는 서버 글 그대로(낡음이면 버튼을 끔).
- [+ 만약에 복사본]: `WhatIfDialog`("무엇을 바꿔 볼까요?" 글 칸) → `open('chat', {ask: '만약에 복사본을 만들어 줘: <글>'})`.

- [ ] **Step 1: 실패하는 시험**
```ts
test('summary table lists plans', async () => { mockSummary(S); expect(await screen.findByRole('cell', { name: '만회안 A · 병행 우선' })).toBeVisible(); expect(within(summaryRow('만회안 A · 병행 우선')).getByText('2027.03.16')).toBeVisible() })
test('overlay colors pulled bars', async () => { mockCompare(C); expect(await bar('B', 'other')).toHaveClass('pulled') })
test('changed-only hides same rows', async () => { await userEvent.click(screen.getByRole('button', { name: '달라진 것만' })); expect(screen.queryByTestId('row-A')).toBeNull() })
test.each([[-3, '−3일'], [2, '+2일'], [0, '0'], [null, '—']])('delta %s', (n, t) => expect(deltaText(n)).toBe(t))
test('diff table shows workday deltas', async () => { await userEvent.click(screen.getByRole('button', { name: '차이 표' })); expect(within(diffRow('B')).getByText('−3일')).toBeVisible() })
test('side by side scrolls together', async () => { await userEvent.click(screen.getByRole('button', { name: '좌우 비교' })); fireEvent.scroll(pane(0), { target: { scrollTop: 120 } }); expect(pane(1).scrollTop).toBe(120) })
test('submit sends title then opens approvals', async () => { mockSubmit({ approval_id: 7, applied: false, status: 'submitted' }); await userEvent.click(screen.getByRole('button', { name: '이 안을 반영 (승인함으로)' })); await userEvent.click(screen.getByRole('button', { name: '보내기' })); expect(lastBody()).toEqual({ title: '만회안 A · 병행 우선' }); expect(openSpy).toHaveBeenCalledWith('approvals', { id: '7' }) })
test('stale scenario cannot be submitted', async () => { mockCompare({ ...C, other: { ...C.other, stale: true } }); expect(await screen.findByRole('button', { name: '이 안을 반영 (승인함으로)' })).toBeDisabled(); expect(screen.getByText('기준 일정이 바뀌었습니다')).toBeVisible() })
test('what-if asks the agent through chat', async () => { await userEvent.click(screen.getByRole('button', { name: '+ 만약에 복사본' })); await userEvent.type(screen.getByRole('textbox'), '크레인 2대로 하면?'); await userEvent.click(screen.getByRole('button', { name: '에이전트에게 맡기기' })); expect(openSpy).toHaveBeenCalledWith('chat', { ask: '만약에 복사본을 만들어 줘: 크레인 2대로 하면?' }) })
test('params pick base and other', async () => { render(<Compare windowId="w1" params={{ id: '1', base: 's:4', other: 's:5' }} />); await waitFor(() => expect(lastUrl()).toContain('base=s:4&other=s:5')) })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(화면 검수: 1600×900·900×600, 두 테마) → 커밋 `feat: 비교판 화면`

---

### Task 38: 개발 콘솔 화면 — 에이전트 구조·실행 추적·사용량 [fable] · G4

**Files:** Create `frontend/src/programs/devconsole/{DevConsole.tsx,TurnPicker.tsx,AgentStructure.tsx,NodeDetail.tsx,TraceTimeline.tsx,UsageTab.tsx,devApi.ts,structureLayout.ts,devconsole.css}` + `*.test.ts(x)`; Modify `frontend/src/programs/devconsole/index.ts`

**Interfaces — Consumes:** 개발 콘솔 API(Task 29), `useSession`(관리자 확인), `open('settings', {section: 'approval'})`, 시안 `DevConsoleA.dc.html`(A안)
**Produces:**
- 탭 셋: **에이전트 구조 · 실행 추적 · 사용량·비용**(설계 12장의 나머지 일곱 탭은 묶음 4 — 이번에는 탭 막대에 넣지 않는다).
- 위 줄: 요청 고르기 ▾(`TurnPicker`, 최근 30, 찾기) · 루프 `n바퀴 / 한도 12` · 도구 호출 n · 모델 호출 n · 토큰 21.4K · 비용(없으면 표시 안 함) · 걸린 시간(실행 중이면 "12.8초째"). 실행 중이면 1초마다 다시 불러오고 끝나면 멈춘다.
- 에이전트 구조(`AgentStructure`, SVG): 칸 아홉을 시안 배치로(요청 받기 → 컨텍스트 조립 → 스킬 찾기 → 워크플로우 짜기 → 판단 ⇄ 도구 실행 → 조건 점검(위반 → 고쳐서 다시) → 승인 판단 → 응답·기록) + 곁 칸(컨텍스트 재료 다섯, 스킬 실행·승인함). state 별 모양: `past` 채움 · `now` `--accent` 테두리·빛 · `todo` 점선 · `skipped` 회색 + "묶음 3". `structureLayout.ts`: `nodeBoxes(width) → Record<key, {x, y, w, h}>`, `edgesFor(nodes) → {from, to, label?}[]`.
- 칸을 누르면 오른쪽 `NodeDetail`: 하는 일(고정 글), 모델(쓰지 않음(코드)/모델 이름), 이번 요청(count·ms), 들어간 것·나온 것(접힌 원문, 펼치면 JSON 들여쓰기·접기 — 화면 검수 3), 컨텍스트 구성(`지시문 22% · …`, 막대), 관련 설정(값 + [설정 열기]).
- 실행 추적(`TraceTimeline`): 시간순 표(종류 배지 · 이름 · 시각 · 시간 · 모델 · 토큰 · 결과), 줄을 펼치면 입력·출력 원문을 접힌 블록으로.
- 사용량·비용(`UsageTab`): 기간 7/14/30일, 묶는 기준 모델/사용자/날짜/작업 종류, 표 + 가로 막대(토큰), 합계 줄, 근거 검색 호출 수. `cost_known` 이 거짓이면 비용 칸은 "—" 와 안내 "Liner가 비용 값을 보내지 않아 비용은 비어 있습니다(토큰만 셉니다)."

- [ ] **Step 1: 실패하는 시험**
```ts
test('three tabs only', () => { render(<DevConsole windowId="w1" />); expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['에이전트 구조', '실행 추적', '사용량·비용']) })
test('now node is lit and loop count shown', async () => { mockTurn(running({ now: 'tool', loop: 4 })); expect(await node('도구 실행')).toHaveClass('now'); expect(screen.getByText('4바퀴')).toBeVisible(); expect(screen.getByText('/ 한도 12')).toBeVisible() })
test('skill node says it comes later', async () => { expect(await node('스킬 찾기')).toHaveClass('skipped'); expect(screen.getByText('묶음 3')).toBeVisible() })
test('clicking a node shows its detail folded', async () => { await userEvent.click(await node('컨텍스트 조립')); expect(screen.getByText(/지시문 \d+%/)).toBeVisible(); expect(screen.getByRole('button', { name: '들어간 것 펼치기' })).toBeVisible() })
test('running turn polls every second and stops when done', async () => { vi.useFakeTimers(); mockTurnSequence([running(), done()]); render(<DevConsole windowId="w1" />); await vi.advanceTimersByTimeAsync(2500); expect(fetchCount()).toBe(2) })
test('trace rows expand to raw text blocks', async () => { await userEvent.click(screen.getByRole('tab', { name: '실행 추적' })); await userEvent.click(await screen.findByRole('button', { name: /llm/ })); expect(screen.getByText('입력 원문')).toBeVisible() })
test('usage shows dash and note when cost is unknown', async () => { mockUsage({ cost_known: false, rows: [{ key: 'claude-sonnet-5.5', calls: 2, input_tokens: 150, output_tokens: 30, cost: null, failed: 0 }] }); await openUsage(); expect(screen.getByText('Liner가 비용 값을 보내지 않아 비용은 비어 있습니다(토큰만 셉니다).')).toBeVisible() })
test('usage group switch refetches', async () => { await openUsage(); await userEvent.selectOptions(screen.getByLabelText('묶는 기준'), 'user'); expect(lastUrl()).toContain('group=user') })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(화면 검수, 시안 A안과 비교 메모) → 커밋 `feat: 개발 콘솔 화면`

---

### Task 39: 대화 카드 — 근거·실적·지연 영향·만회안·복사본 [opus] · G4

**Files:** Create `frontend/src/programs/chat/cards/{EvidenceCard,ActualCard,DelayImpactCard,ShortenCard,ScenarioCard}.tsx` + `cards2.test.tsx`; Modify `frontend/src/programs/chat/cards/{index.tsx,ResultCard.tsx,ApprovalCards.tsx}`

**Interfaces — Consumes:** 카드 등록부 `CARDS`·`Card`·`asList/asObj/asNum/asText`(Task 14), 사건 data 모양: `evidence`(Task 27) · `actual_recorded`(Task 30) · `delay_impact`(Task 33) · `shorten_options`(Task 34) · `scenario_created`(Task 26) · 승인 사건의 `summary.rule`(Task 35)
**Produces:** `CARDS` 에 `'card:evidence'`, `'card:actual_recorded'`, `'card:delay_impact'`, `'card:shorten_options'`, `'card:scenario_created'`.
- 근거: 검색어·모드 배지(웹/학술), 결과마다 제목 링크(새 탭)·사이트·날짜, 번호 "[근거 1]".
- 실적: "A2020 진도 60%로 넣었습니다(자동 적용 · 버전 4)" + 가정한 것 줄들 + 지연이 있으면 위험색 줄 "Plan보다 3일 늦어졌습니다 · 준공 +2일" [지연 기록 열기].
- 지연 영향: 준공 `+3일`, 여유로 흡수 `0일`, 크리티컬 변화, 새 자원 겹침, 비용(`620만 원`), [지연 기록 열기] [비교판에서 보기]은 `delay_impact.status==='open'` 일 때만 [만회 계획 요청].
- 만회안: 안마다 한 줄(추천 배지 · 이름 · 준공 · 이득 `−3일` · 도달 여부 · 위반 n) + 접힌 "바꾸는 것" + 설명 글, [비교판에서 보기] → `open('compare', {id, base, other: 's:<id>'})`.
- 복사본: 이름·준공·Plan 대비 [비교판에서 보기].
- 결과 카드(생성): 가정에 `evidence_ids` 가 있으면 "근거 n" 표시. 승인 카드: `summary.rule` 이 있으면 "내 규칙 저장: <글> (분야 전체/이 일정)".
- 모르는 칸이 빠져도 던지지 않는다(기존 규칙).

- [ ] **Step 1: 실패하는 시험**
```ts
test('evidence card links open in a new tab', () => { renderCard('card', { kind: 'evidence', query: '층당 골조 공기', mode: 'web', results: [{ evidence_id: 1, title: '골조 공기 기준', url: 'https://example.com/a', hostname: 'example.com', date: '2026-03-01' }] }); expect(screen.getByRole('link', { name: '골조 공기 기준' })).toHaveAttribute('target', '_blank'); expect(screen.getByText('[근거 1]')).toBeVisible() })
test('actual card shows assumptions and delay', async () => { renderCard('card', { kind: 'actual_recorded', schedule_id: 1, activity_id: 'A2020', name: '지상 골조', progress: 0.6, assumed: ['실제 시작일을 2027-05-06로 두었습니다(계획 시작일).'], delay: { activity_id: 'A2020', late_days: 3, finish_delta: 2 }, version: 4 }); expect(screen.getByText(/Plan보다 3일 늦어졌습니다/)).toBeVisible(); await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' })); expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', activity: 'A2020', days: '3' }) })
test('delay impact card', () => { renderCard('card', { kind: 'delay_impact', schedule_id: 1, event_id: 2, status: 'open', days: 3, impact: { finish_delta: 3, absorbed: 0, critical_added: [], critical_removed: [], new_clashes: [], cost: 9_300_000 } }); expect(screen.getByText('+3일')).toBeVisible(); expect(screen.getByText('930만 원')).toBeVisible(); expect(screen.getByRole('button', { name: '만회 계획 요청' })).toBeVisible() })
test('shorten card marks the recommendation and opens compare', async () => { renderCard('card', { kind: 'shorten_options', schedule_id: 1, base: 's:3', options: [opt('A', 4, false), opt('B', 5, true)] }); expect(within(optionRow('B')).getByText('추천')).toBeVisible(); await userEvent.click(within(optionRow('B')).getByRole('button', { name: '비교판에서 보기' })); expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 's:3', other: 's:5' }) })
test('broken data does not throw', () => { renderCard('card', { kind: 'shorten_options' }); expect(screen.queryByText(/보일 수 없는 카드/)).toBeNull() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(대화창 화면 검수) → 커밋 `feat: 묶음 2 대화 카드`

---

### Task 40: 생산 분야 표시와 예시 자료 [opus] · G4

**선행:** 계획 1 Task 20 커밋(`app/seed.py`).

**Files:** Modify `backend/app/store/view.py`, `backend/app/programs/schedule/schemas.py`, `backend/app/seed.py`, `frontend/src/programs/schedule/{scheduleApi.ts,gantt/GanttTab.tsx,table/columns.tsx}`; Create `frontend/src/programs/schedule/gantt/BlockedBands.tsx` + 시험, `backend/tests/programs/test_schedule_display.py`, `backend/tests/test_seed_manufacturing.py`

**Interfaces — Consumes:** `DomainPack.display`(Task 28), `ScheduleView.calendar.blocked`(Task 21), 계획 1 Task 17 간트(`rowsFor(view, by)`·묶는 기준 상태·기한 세로선), Task 16 열 고르기
**Produces:**
- ScheduleView + `display: {gantt_group_by, deadline_label, extra_columns}`(그 일정 분야 묶음의 `display`, 모르는 분야면 기본값). TS 타입도.
- 간트: 처음 묶는 기준 = `display.gantt_group_by`(사용자가 바꾸면 그대로). `BlockedBands`: `calendar.blocked` 마다 차트 전체 높이의 빗금 띠 + 위 이름표 `"<tag> 작업 금지"`(예: "프레스 작업 금지"), 그 tag 를 단 액티비티 줄에서는 더 진하게. 기한 세로선 이름표는 `display.deadline_label`("납기 09.10").
- 스케줄표: 저장된 열 고르기가 없으면 `display.extra_columns`(생산: 주요 자원) 를 켠 채로 시작.
- 씨앗: `python -m app.seed demo` 가 둘째 일정 **"가상 부품 공장 — 브래킷 BR-200 2만 개"**(manufacturing·L3)를 더 만든다. 착수 2027-07-05, 액티비티 26~32개(생산 WBS 틀), 주요 자원 6개(용량 press_line 1 · heat_furnace 1 · cnc 2 · assembly_line 1 · cmm 1 · mold_shop 1), 조건 = 분야 규칙 + 입력 `finish_by 2027-09-10`(source 질문지, 글 "납기 9월 10일") + `resource_cap press_line 1`. 실적 없음. 여러 번 돌려도 같다. LLM 을 부르지 않는다.

- [ ] **Step 1: 실패하는 시험**
```python
def test_view_carries_domain_display(client, admin, sid_manufacturing):
    assert client.get(f"/api/schedules/{sid_manufacturing}", headers=admin).json()["display"] == {"gantt_group_by": "resource", "deadline_label": "납기", "extra_columns": ["resources"]}
def test_seed_makes_a_factory_schedule(session):
    seed_demo(session); seed_demo(session)
    m = [r for r in list_records(session) if r.domain == "manufacturing"]; assert len(m) == 1
    v = view_data(session, m[0].id); assert 26 <= len(v["activities"]) <= 32 and v["finish"] <= date(2027, 9, 10)
    press = [a for a in v["activities"] if "프레스" in a["tags"]]
    assert any(a["es"] < date(2027, 7, 29) and a["ef"] > date(2027, 8, 4) for a in press)       # 정기 보수를 건너 이어짐
    assert v["calendar"]["blocked"] == [{"tag": "프레스", "start": date(2027, 7, 29), "finish": date(2027, 8, 4)}]
def test_seed_factory_passes_its_checks(session): report = harness_check(seed 일정); assert report.violations == []
```
```ts
test('blocked bands are labeled', () => { render(<GanttTab />); expect(screen.getByText('프레스 작업 금지')).toBeVisible() })
test('gantt starts grouped as the domain says', () => { expect(screen.getByRole('button', { name: '자원', pressed: true })).toBeInTheDocument() })
test('deadline label follows the domain', () => expect(screen.getByText(/납기 09\.10/)).toBeVisible())
test('table starts with the domain extra columns', () => { renderTable(viewWith({ display: { extra_columns: ['resources'] } })); expect(screen.getByRole('columnheader', { name: '주요 자원' })).toBeVisible() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(생산 간트 화면 검수) → 커밋 `feat: 생산 분야 표시와 예시 자료`

---

### Task 41: 주의할 일정 위젯 [sonnet] · G4

**Files:** Create `backend/app/programs/attention/{__init__,router,service,schemas}.py`, `backend/tests/programs/test_attention_api.py`, `frontend/src/os/{AttentionWidget.tsx,attention.ts,AttentionWidget.test.tsx}`; Modify `frontend/src/os/Desktop.tsx`

**Interfaces — Consumes:** `list_records`, `view_data`, `load`·`read_conditions`·`assemble_all`·`check`, 표 `DelayEventRow`, `ApprovalWidget` 의 배치·모양(계획 1 Task 12b), `useWindows.open`
**Produces:**
- `GET /api/attention` → `{items: [{id, name, domain, finish, plan_finish, finish_delta, late_count, negative_float_count, violations, open_delays, level: "danger"|"warning"|"ok"}]}` — `danger`: 음수 여유 > 0 이거나 위반 > 0 · `warning`: 늦은 task > 0 이거나 열린 지연 > 0 · 그 밖 `ok`. 차례 danger → warning → ok, 같으면 이름. 계산이 안 되는 일정은 `level: "danger"`, `violations: 1`.
- 위젯(바탕화면, 승인 대기 위젯 옆): 제목 "주의할 일정 n"(ok 제외), 줄마다 이름 · 배지(위험/주의) · 한 줄 까닭("준공 +4일 · 지연 사건 1건"), 누르면 `open('schedule', {id})`. 없으면 "주의할 일정이 없습니다". 60초마다 다시 불러온다(창이 보일 때만).

- [ ] **Step 1: 실패하는 시험**
```python
def test_levels(client, admin, session):
    late = store(session, make([task("A", 3), task("B", 2)], [Relation("A", "B")]), [finish_by("2027-03-04")])   # 위반
    ok = store(session, sample())
    items = client.get("/api/attention", headers=admin).json()["items"]
    assert [(i["id"], i["level"]) for i in items] == [(late, "danger"), (ok, "ok")] and items[0]["violations"] == 1
def test_open_delay_is_a_warning(client, admin, session, sid): add_open_delay(session, sid, "B", 1); assert get_item(sid)["level"] == "warning"
```
```ts
test('widget lists schedules needing attention', async () => { mockAttention([item('5층 사무동 신축', 'danger', '준공 +4일'), item('브래킷 BR-200', 'ok')]); render(<AttentionWidget />); expect(await screen.findByText('주의할 일정 1')).toBeVisible(); expect(screen.queryByText('브래킷 BR-200')).toBeNull() })
test('clicking opens the schedule', async () => { await userEvent.click(await screen.findByRole('button', { name: /5층 사무동 신축/ })); expect(openSpy).toHaveBeenCalledWith('schedule', { id: '1' }) })
test('empty state', async () => { mockAttention([]); expect(await screen.findByText('주의할 일정이 없습니다')).toBeVisible() })
test('polls every minute', async () => { vi.useFakeTimers(); render(<AttentionWidget />); await vi.advanceTimersByTimeAsync(60_000); expect(fetchCount()).toBe(2) })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(바탕화면 화면 검수) → 커밋 `feat: 주의할 일정 위젯`

---

### Task 42: 끝에서 끝까지 — 묶음 2 시연 흐름과 제출 준비물 [opus] · G4 끝(36~41 뒤)

**Files:** Create `backend/tests/e2e/test_bundle2_flow.py`, `frontend/e2e/bundle2.spec.ts`; Modify 계획 1 Task 20 의 가짜 LLM 대본 모듈(`CHRONOS_FAKE_LLM`, 이름은 Task 20 보고서), `docs/demo/시나리오.md`, `docs/contest/기획서.md`, `README.md`, `docs/dev-journal/2026-11.md`

**Interfaces — Consumes:** 전부
**Produces:**
- 서버 끝에서 끝까지(`ScriptedLlm`, 씨앗 `demo`): 로그인 → 대화 "지상 골조가 비 때문에 3일 늦어졌어"(+ ui: 일정판·A2020 고름) → `schedule.find` → `delay.record` → `delay_impact` 카드·지연 기록 1건(열림, 준공 영향 > 0) → 대화 "만회 계획 만들어 줘" → `shorten.make` → `shorten_options` 카드(도달한 안 ≥ 1, 위반 0) → 추천 복사본 `submit` → 승인함 결정 승인 → 새 버전, 그 지연 `reflected`, 복사본 `applied` → `GET …/progress` 의 `cpm.finish_variance.days` 가 만회 전보다 작거나 같음 → `GET /api/devconsole/turns` 에 두 턴, 첫 턴 구조의 `tool.count ≥ 2` → 생산 일정 view 의 `display.gantt_group_by == "resource"`.
- 화면 끝에서 끝까지(Playwright, 1920×1080, `CHRONOS_FAKE_LLM=1`): 로그인 → 일정판(건설) → 대화에서 지연 말하기 → 대화 카드·지연 기록 창 → [만회 계획 요청] → 만회안 카드 → 비교판(같은 차트, 요약 표) → [이 안을 반영] → 승인함 승인 → 일정판 CPM 탭(요약 줄) → 진행 탭(S-커브) → 개발 콘솔 구조 → 생산 일정 간트(자원 묶음·"프레스 작업 금지" 띠). 장면마다 `docs/demo/shots/b2-<번호>-<이름>.png`.
- 문서: `시나리오.md` 에 묶음 2 장면(지연 → 영향 → 만회안 → 승인, 두 번째 분야) 말·시간 초안. `기획서.md` "만든 것 / 설계만 된 것" 표와 "Liner 활용"(작업별 모델 배정 + 근거 검색 + 단축안 추천 hard). `README.md` "Liner API 를 쓰는 곳"에 `backend/app/llm/search.py`·`backend/app/tools/data/search_evidence.py`·`backend/app/tools/respond/make_shortening.py`. 일지에 묶음 2 결과.

- [ ] **Step 1: 실패하는 시험** — 위 서버 흐름. 끝 단언:
```python
assert event["status"] == "reflected" and scenario["status"] == "applied" and versions[0]["n"] == before_version + 1
assert progress_after["cpm"]["finish_variance"]["days"] <= progress_before["cpm"]["finish_variance"]["days"]
```
- [ ] **Step 2:** 실패 확인 — [ ] **Step 3:** 대본·시험·문서 — [ ] **Step 4:** `bash scripts/check.sh` 전체 + `docker compose run --rm e2e` 통과 — [ ] **Step 5:** 커밋 `test: 묶음 2 시연 흐름과 제출 준비물`

---

### Task 43: 창 움직임 효과 — 맥OS처럼 짧게 [opus] · 아무 때나(셸 파일만)

**[PM 요청 11-20]** 프로그램 창이 열리고 닫히고, 최소화·최대화(전체 화면)될 때 맥OS처럼 짧은 움직임을 넣는다. 셸(`frontend/src/os/**`)만 고친다.

**Files:** Modify `frontend/src/os/{Window.tsx,windowStore.ts,Dock.tsx,os.css}` (필요하면 `frontend/src/os/windowMotion.ts` 새로) + 그 시험

**Produces / 규칙:**
- **열기:** Dock 아이콘(또는 연 곳 — 앱 서랍·검색·다른 창의 요청이면 화면 가운데 아래)에서 창 자리로 커지며 나타남(scale 0.6→1, opacity 0→1, 원점 = 아이콘 쪽), 약 220ms, ease-out. 이미 열린 창을 앞으로 가져올 때는 움직임 없음.
- **닫기:** 창 자리에서 살짝 작아지며 사라짐(scale 1→0.92, opacity 1→0), 약 160ms, ease-in. 움직임이 끝난 뒤 store 에서 지운다(그동안 클릭은 막음).
- **최소화:** Dock 의 그 프로그램 아이콘 쪽으로 줄어들며 들어감(맥OS 「크기 조절」 효과 — 지니 효과는 하지 않는다), 약 260ms. 복귀는 거꾸로.
- **최대화(전체 화면)·복귀:** 창 틀이 지금 자리에서 작업 영역 크기로 부드럽게 바뀜(위치·크기 transition), 약 200ms. 끌기·크기 조절 중에는 움직임 없음.
- 모두 CSS transform/opacity 또는 Web Animations API 로(새 의존성 없음), 레이아웃을 흔들지 않게 transform 위주. 움직이는 동안에도 창 안의 프로그램은 다시 마운트되지 않는다.
- `prefers-reduced-motion: reduce` 이면 움직임 없이 바로 바뀐다. 시험 환경(jsdom)에서는 움직임을 끄는 스위치로 기존 시험이 그대로 통과한다.
- 성능: 창 10개가 열려 있어도 60fps 근처(transform 만), 움직임 중 Dock 확대와 겹쳐도 깨지지 않음.

- [ ] **Step 1: 실패하는 시험** — 열기·닫기·최소화·최대화 때 움직임 class/animation 이 붙고, 끝난 뒤 store 상태가 맞음(닫기는 끝난 뒤 제거), 움직임 중 클릭 막힘, reduced-motion 에서 바로 바뀜, 이미 열린 창 앞으로는 움직임 없음.
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → FHD Chrome 에서 녹화 또는 연속 캡처로 확인 → 커밋 `feat: 창 움직임 효과`

### Task 44: Liner 시각화 — 코드가 만든 표로 보고서·요약 그림 [opus] · G3 (Task 33·34 와 함께, 셸 파일 아님)

**[PM 결정 11-20]** Liner Visualization API(`POST {base_url}/tools/visualization`, 1회 $0.01, 결과는 HTML 한 장 `atlasArtifact.html` + `theme`·`description`·`resourceId`)를 **보고서·요약 그림**에 쓴다. 앱 안의 간트차트·CPM·공정률 그림은 우리 그림 그대로. 근거: `/Users/janghosohn/reports/AI대회/01_라이너_엑스톤_2026/01_대회정보/라이너_기능_조사.md` 2·3장.

**규칙(조사 3-3 그대로):**
- 숫자는 코드가 묶는다: 도구 `visual.make {kind: "summary"|"delay_impact"|"scenario_compare"|"s_curve"|"resource_load", schedule_id, version?}` — 인자에 숫자 없음. 표(열·단위·값)는 저장된 버전에서 코드가 만든다.
- 요청 글은 코드에 둔 고정 틀("아래 표의 값만 그대로 … 계산·반올림·추정·추가 금지") + CSV. `is_search_context` 는 켜지 않는다.
- 받은 HTML 을 코드로 대조: 우리 표의 모든 값·날짜가 HTML 데이터에 있고, 없는 날짜·값이 데이터 배열에 없을 것. 실패하면 한 번 다시, 또 실패하면 우리 그림(SVG)으로 대신하고 개발 콘솔 기록 "Liner 그림 검증 실패 → 기본 그림".
- 저장: 입력 표 해시·버전·resourceId·theme·검증 결과(`visuals` 표). 같은 입력이면 다시 부르지 않는다. 초당 2회 한도 — 차례로.
- 보여 주기: 대화 카드 `visual` 와 지연 기록·비교판·공정률 창의 [보고서용 그림] 단추 → `<iframe sandbox="allow-scripts" srcdoc>`(allow-same-origin 없음), 캡션 "데이터: 크로노스 계산(버전 vN, 기준일 …) · 그림: Liner Visualization · 숫자 대조 통과 n/n". 20~30초는 "그림 만드는 중" 자리.
- Step 0 실측(호출 2번 이하): 응답 모양·걸린 시간·외부 스크립트 주소 → 일지. 안 되면 멈추고 보고.

**Files:** Create `backend/app/llm/visualization.py`, `backend/app/store/visuals.py`, `backend/app/tools/visual/{__init__,make}.py`, `backend/app/programs/visuals/{__init__,router,service,schemas}.py`, `frontend/src/shared/visual/{VisualFrame.tsx,visualApi.ts}`, 대화 카드 `frontend/src/programs/chat/cards/VisualCard.tsx` + 시험; Modify 대화 카드 등록부, 지연·비교·공정률 프로그램에 [보고서용 그림] 단추 한 줄(그 작업들 뒤).

### Task 45: 검색 프리미엄 자료 — 날씨·원자재 가격·환율을 근거 표로 [opus] · G3 (Task 27 뒤)

**[PM 결정 11-20]** Search API 웹 검색의 `knowledge`(Premium Data: AccuWeather 평균·예보, 원자재 가격, 환율 등 표, 출처·기준일 포함)를 가정·조건의 근거로 쓴다.
- `evidence.search` 에 `knowledge: bool = false` — 참이면 `include_knowledge: true` 로 부르고 응답의 `knowledge` 표를 근거 항목(종류 `table`, 출처·기준일·열·행)으로 저장. 거짓이면 지금처럼 `include_knowledge: false`(비용 절반).
- 지침(`guides/evidence.md`): 날씨에 걸리는 작업(동절기 타설·도장·외부 작업)의 금지 기간이나 여유, 자재비·환율이 걸린 가정에는 `knowledge: true`. 표의 숫자는 **가정의 근거로만** 쓰고 날짜 계산에는 넣지 않는다.
- 화면: 근거 카드와 조건 「출처」에 표가 있으면 접히는 작은 표(출처·기준일 머리).
- Step 0 실측(호출 2번 이하): 날씨·원자재 질의에서 `knowledge` 모양 → 일지.

**Files:** Modify `backend/app/llm/search.py`, `backend/app/tools/data/search_evidence.py`, `backend/app/store/evidence.py`, `backend/app/agent/prompts/guides/evidence.md`, 근거 카드·조건 출처 화면 + 시험.

### Task 46: 모델 가격 참고 표시 [sonnet] · 아무 때나

**[PM 결정 11-20]** 모델을 고를 때만 참고로 가격을 보인다(비용 관리는 하지 않음). Liner 응답에는 라우터·liner-mark 비용이 없으므로 공개 가격표를 코드에 둔다.
- `backend/app/llm/prices.yaml`: 모델 id → `{input, output, cached_input}` USD/1M 토큰, `source` URL, `as_of: 2026-11-20` (조사 문서 「가격」 절 값; `gemini-3.8-flash` 는 가격 쪽 라우터 표 값). 라우터 항목은 "고르는 모델 범위"(가장 싼 ~ 가장 비싼)로.
- 모델 메타데이터(`/connections/{id}/models`, 시험 결과)에 `price` 를 붙인다(없으면 null).
- 설정 「작업별 모델 배정」 모델 칸과 찾기 결과에 「입력 $x / 출력 $y (1M 토큰)」, 라우터는 「$a~$b」. 표 아래 "가격 기준: Liner 공개 가격표(2026-11-20)".
**Files:** Create `backend/app/llm/prices.yaml`; Modify `backend/app/llm/connections.py`, `backend/app/programs/llm_settings/schemas.py`, `frontend/src/programs/settings/{models.ts,AssignmentParts.tsx,ProbeResult.tsx}` + 시험.

### ◆ Checkpoint C — 실제 Liner 로 묶음 2 시연 흐름

- [ ] 테일넷 주소로 띄우고 씨앗 `demo` 를 넣는다. 실제 Liner 연결로 처음부터 끝까지: 대화로 지연 말하기 → 영향 카드·지연 기록 → 만회 계획 요청 → 비교판에서 안 고르기 → 승인 → CPM·진행 탭이 바뀜. 걸린 시간·모델 호출 수·토큰·단축안 추천이 LLM 에서 왔는지(실패 시 코드 고름)를 일지에 적는다.
- [ ] 두 번째 분야: 대화 "가상 부품 공장에서 브래킷 2만 개 주문 일정 만들어 줘, 9월 10일 납기" → 질문지 → 생성(L3, manufacturing) → 승인 → 간트가 설비별로 묶이고 프레스 정기 보수 띠가 보인다. L3 생성 중 근거 검색이 1~3번 쓰였는지, 가정에 출처가 붙었는지 확인한다(실패하면 "근거 검색 실패"로 표시되는지).
- [ ] 근거 검색 실측 1번(web, `include_knowledge: false`)과 분야 근거(legal·business, Task 27b) 각 1번 — 생성 중 근거 카드와 조건 출처 링크로 보이는지.
- [ ] 개발 콘솔에서 위 턴의 구조·추적·사용량을 캡처해 기획서 "Liner 활용" 근거로 둔다.
- [ ] 한도 안에 통과하지 못하면 `prompts/guides/*.md`·`shorten_note.md` 를 고친다(코드 구조는 그대로). 전후를 일지에.
- [ ] PM 에게 화면을 보여 확인받는다(시안 대비 메모 포함). PR 과 보고서 `~/reports/pr_YYYYMMDD_HHMM.md`(Task 21~42).
- [ ] 다음 계획서 `docs/plans/…-plan-3-reports-skills-domains.md`(묶음 3)를 쓴다.

---

## 설계 대응표 (묶음 2)

| 설계 | Task |
|---|---|
| 8-3 일정판 CPM 탭(네트워크·도구줄·요약 줄·상세·관계 편집·PNG) | 21(ls·lf), 24(요약 값), 26(만회 달성률), 31 |
| 8-4 진행 탭(계획 대 실적 공정률·WBS 묶음별·S-커브·가중치) | 21(가중치 방식), 24, 32 |
| 8-5 실적 입력(대화·스케줄표, 지연 감지 → 제안) | 21(Data Date), 30, 33(실적에서 감지한 지연 등록), 39 |
| 13-1 지연 기록 + 지연 영향 분석(책임·하루 금액·여유 흡수·크리티컬·자원·비용·차례대로 몫) | 22, 33, 36, 39 |
| 13-2 단축안(병행·압축·자원 추가 → 조건 점검) · 만약에 복사본(제한 없음) · 비교판(겹쳐 보기·나란히·차이 표·요약 표) | 23, 26, 34, 37, 39 |
| 10-3 승인 기준(실적은 자동 적용·되돌리기, Plan 다시 잡기, 내 규칙 저장) | 26, 30, 35 |
| 9-1 ③ 내 규칙(제안 → 승인 → 저장, 분야 전체/이 일정, 생성·맥락에 반영) | 35 |
| 15 근거 보관 · 16 근거 검색(Liner Search 웹·학술) · 11-2 L3 이상 생성 중 검색 최대 3번 | 27, 39 |
| 12 개발 콘솔 — 에이전트 구조·실행 추적·사용량·비용 | 29, 38 |
| 17 생산 분야(용어·달력·분야 규칙·주요 자원·작업 유형·WBS 틀·기준값·납기 ◆·설비 정지 구간·자원으로 묶기·가상 예시) | 28, 40 |
| 6 바탕화면 위젯 "주의할 일정"(계획 1 Task 12 에서 넘김) | 41 |
| 18-1 코드 규정 · 19-1 제출 준비 | 전 작업, 42 |
| 뒤 계획으로 넘긴 것 | 지연 보고서 만들기·주간 보고서(묶음 4) · 진행 탭 "보고서에 넣기"(묶음 3 보고서) · 영향의 "다른 일정" 전파(묶음 3 일정 사이 연결) · CPM 오른쪽 "변동 분석" 패널(묶음 4) · 개발 콘솔 나머지 일곱 탭(묶음 4) · 생산 분야 기본 스킬(묶음 3 스킬) · 사업화 `deep_research_agent` 조사 맡기기(계획 3) |
