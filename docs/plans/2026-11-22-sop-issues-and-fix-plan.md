# ChronOS 실무 시나리오 E2E 점검 결과 · 결함 분석 및 전체 수정 계획서

> **작성일:** 2026-11-22  
> **최종 갱신:** 2026-11-23 (Wave 1 + 원라이너 + SOP 지시서 선행 패치 반영)  
> **기준 커밋:** `f8d70a6` (`feature/plan-1`) 위에 현재 워킹트리 패치 적용됨  
> **검증 대상 지시서:** `docs/demo/실무_작업_시나리오_지시서.md` (총 46단계 `PRE-01` ~ `STEP 10-2`)  
> **대상 독자:** 나머지 항목을 이어서 수정·검증할 엔지니어 / AI 에이전트(Claude)

---

## 0. 현재 진행 현황 (2026-11-23 Antigravity 완료분 vs Claude 잔여 작업)

### 0-1. 선행 완료 내역 (`[x]`)
- **Wave 1 (P0) 전 항목 코드 수정 및 단위 테스트 통과 (`139 passed`, `tsc --noEmit` 통과):**
  - `[x]` **A1 (`Plan` 기준선 보호):** `backend/app/store/approvals.py` (`is_plan_change`, `_rule_changes_dates`), `backend/app/tools/out/propose_rule.py` (`plan_change` 요약 전달), `frontend/src/programs/approvals/DecisionBox.tsx` (`plan_change === false` 안내 문구), `backend/tests/programs/test_plan_frozen.py` (`text_only` 규칙 Plan 유지 / `calendar` 날짜 변경 규칙 Plan 갱신 분리 테스트).
  - `[x]` **A2 (보고서 양식 `manual_input` 오매핑 수정):** `backend/app/programs/reports/learner.py` (`_infer_binding` 한국어 키워드 보강, `system_prompt` 10종 `data_binding` 명세, `_sanitize_llm_result` 휴리스틱 교정·열 보조 추출), `backend/tests/test_reports.py`.
  - `[x]` **A3 (보고서 800토큰 절단 및 무경고 폴백 제거):** `backend/app/programs/reports/generator.py` (`_progress_facts_text`, `_draft_prose_with_llm`/`revise_block_text` `max_tokens=4000`, `finish_reason == "length"` 시 결정론적 폴백, 실 LLM 실패(`LlmFailed`/`length`) 시 원문 보존 `ApiError(502)`, 미연결 `LlmNotReady`는 오프라인 테스트/미설정 호환 유지), `backend/app/programs/reports/service.py`, `backend/tests/test_reports.py`.
  - `[x]` **A4 (`visual_check.py` 날짜 조각 오탐 수정):** `backend/app/llm/visual_check.py` (`_known_dates`, `_strip_known_dates`로 표 날짜에서 파생된 날짜 표현만 제거), `backend/tests/llm/test_visual_check.py`.
- **인프라·성능 원라이너 (`[x]`):**
  - `[x]` **A5 일부:** `scripts/qdrant-local.sh` 실행 전 `ulimit -n 65536 || ulimit -n 10240` 추가 (`bash -n` 문법 확인 완료).
  - `[x]` **A7 일부:** `backend/app/tools/generate/extract_conditions.py` (`L245`) 및 `backend/app/agent/domain_synth.py` (`L176`) `max_tokens` `6000 → 12000` 상향.
- **Wave 4 (P3) SOP 지시서 & 저장 UX 보완 (`[x]`):**
  - `[x]` **C1~C5:** `docs/demo/실무_작업_시나리오_지시서.md` (`PRE-03` 로그아웃/모달 닫기, `STEP 2-1` 즉시 격리 대화 진입, `STEP 4-3` 교차 계정 거부 재작성 안내, `STEP 5-5` `전체 앱`, `STEP 7-2` `이 프로젝트에 양식 기억` 2단계 확인 반영).
  - `[x]` `frontend/src/programs/reports/ReportsTab.tsx`: 분석된 미저장 양식(`mode === 'new'`) 상단에 `[이 프로젝트에 양식 기억]` 클릭 필요 안내 배너(`role="status"`) 추가.

### 0-2. 선행 검증 실행 결과 (2026-11-23 실행 완료)
```bash
cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest tests/programs/test_plan_frozen.py tests/programs/test_approvals_api.py tests/programs/test_rules_api.py tests/test_reports.py tests/llm/test_visual_check.py tests/tools/test_generate_tools.py
# -> 139 passed in 21.82s

cd /Users/janghosohn/projects/chronos/frontend && npm run typecheck
# -> tsc --noEmit && tsc --noEmit -p e2e (exit 0)

bash -n /Users/janghosohn/projects/chronos/scripts/qdrant-local.sh
# -> exit 0
```
- **미실행 검증 (Claude 담당):** 백엔드 전체 `pytest`, `frontend npm test` (`vitest run`), 실 Liner API 격리 Playwright E2E 재검증.
- **참고 (서버 상태):** 시스템 재시작으로 기존 백그라운드 데몬(`:6333`, `:8210`, `:5600`)은 종료된 상태이므로, E2E/실행 확인 시 Qdrant(`scripts/qdrant-local.sh`)부터 다시 기동해야 `ulimit -n` 상향이 적용됨.

### 0-3. Claude 잔여 작업 목록 (우선순위 순, `[ ]`)
1. `[ ]` **A5 잔여 (`backend/app/files/jobs.py` / `vectors.py`):** Qdrant 5xx(`UnexpectedResponse`) 실패 시 `RETRY_S(30초)`마다 `embed()` API 중복 과금 차단(단기 재시도 시 임베딩 재사용 또는 Qdrant 5xx 장기 백오프/서킷 브레이커) + `tests/files/test_jobs.py` 단위 테스트 추가.
2. `[ ]` **A6-2 (`files.set_axes`) & A6-3 (`field.list`):** 기존 서비스(`programs/files/service.py:patch_axes`, `programs/progress/field.py:list_field`)를 감싸는 `@tool` 2종 추가 + `registry.py` `load_all()` 자동 로딩 확인 + `prompts/system.md` / `guides/files.md` 보강 + 단위 테스트.
3. `[ ]` **A6-1 (`schedule.import` `담당자원` 열 지원):** `files/schedule_import.py`, `tools/generate/import_schedule.py`, `prompts/import_map.md`에 `resource_col` 및 `EL-130` 빈 자원 `추정` 가정 기록 추가(`generation_build.py`의 `Schedule.resources` 정합성 확인 필수) + 단위 테스트.
4. `[ ]` **B1~B6 (UX 5건 + 하네스 실엔진화):**
   - **B1:** `MobileShell` `390px` 상단 바 `"나가기"` 우측 클리핑 해소 (`MobileShell.tsx`, `mobile.css`)
   - **B2:** 좁은 `Chat` 창 `파일` 컨텍스트 패널 오버레이 토글 (`Chat.tsx`, `chat.css`)
   - **B3:** `AppDrawer` 편집 `"완료"` 클릭 시 닫힘 동작 개선 + 명시적 닫기(`✕`) 버튼 (완료 시 `실무_작업_시나리오_지시서.md` `PRE-03`의 `Esc` 닫기 단서도 함께 제거)
   - **B4:** 교차 계정 `reject_retry` 원 제안자 시각적 배지/배너 보강 (`ThreadList.tsx` 등)
   - **B5:** `TabletShell` 왼쪽 레일 하단 여백/페이드 보정 (`tablet.css`)
   - **B6:** 개발 콘솔 `H-LOOP-01` · `H-LIM-01` 실엔진 검증(`live_harness`) 전환 (`catalog.py`, `HarnessTab.tsx`)
5. `[ ]` **A7 후속 점검 & 전체 회귀 검증:** 비정형 IT/SW 생성(`STEP 10-2`) `240s` 내 완료 확인(필요 시 `extract.md`/`wbs.md` 장황성 경량화), 전체 `pytest` · `vitest` · 격리 E2E 재검증.

---

## 1. 문서 개요 및 테스트 환경 요약

### 1-1. E2E 검증 결과 요약
- **테스트 환경:** 격리 복제 DB(`/tmp/chronos-sop-data/chronos.db`), 격리 포트(`:5605` Vite / `:8215` FastAPI), 실 Qdrant(`127.0.0.1:6333`), **실제 Liner API** 연동 (`deepseek/deepseek-v4.1-flash-1017`, `STEP 3-4`에서 `Liner Mark 1.0` 전환 검증).
- **집계 결과:** 총 46개 STEP 중 **PASS 41건 / FAIL 5건 / BLOCKED 0건**
  - 다만 PASS 판정 단계 중에서도 실무 품질 저하·조용한 폴백·도구 미비·UI 클리핑·지시서 문구 불일치가 다수 발견되어, 본 문서는 **치명/기능 결함 7군(세부 9건) · 마이너 UX/하네스 6건 · 지시서 불일치 5건 = 총 18개 항목(세부 20건)**을 모두 정리한다.

### 1-2. 작업 시 운영 환경 보존 원칙 (필수 숙지)
- **로컬 실행 중인 운영/데모 서버:**
  - 프론트엔드 Vite: `:5600`
  - 백엔드 FastAPI: `:8210`
  - 로컬 Qdrant: `:6333` (`scripts/qdrant-local.sh`)
- **주의사항:**
  1. E2E 재검증이나 일회성 테스트 스크립트를 돌릴 때는 `data/chronos.db`를 직접 오염시키지 말고, `/tmp/chronos-sop-data` 등에 복사본과 별도 `CHRONOS_DATA_DIR`, 별도 포트(`:5605`, `:8215`), 별도 Qdrant `qdrant_instance`를 사용해 검증할 것.
  2. 테스트 종료 후 임시 컬렉션(`chunks__<test_instance>__*`)과 임시 파일은 정리할 것.

### 1-3. 전체 수정 항목 마스터 인덱스

| ID | Wave | 상태 | 심각도 | 관련 STEP | 문제 요약 | 핵심 대상 파일 |
|---|---|---|---|---|---|---|
| **A1** | Wave 1 | **`[x]` 완료** | **P0 (치명)** | `4-3`, `4-4` | 일정 범위 `내 규칙` 승인 시 `Plan` 기준선이 지연 예측일로 덮어써짐 (`SPI 0.87→0.99`) | `backend/app/store/approvals.py`, `tools/out/propose_rule.py`, `frontend/src/programs/approvals/DecisionBox.tsx`, `backend/tests/programs/test_plan_frozen.py` |
| **A2** | Wave 1 | **`[x]` 완료** | **P0 (기능)** | `7-2~7-4` | 양식 파일 LLM 학습 시 전 항목 `manual_input` 오매핑 → 빈 보고서 생성 | `backend/app/programs/reports/learner.py`, `backend/tests/test_reports.py` |
| **A3** | Wave 1 | **`[x]` 완료** | **P0 (기능)** | `7-3~7-5` | 보고서 서술/수정 `max_tokens=800` 문장 중도 절단 및 실패 시 `[수정 반영: ...]` 조용한 덮어쓰기 | `backend/app/programs/reports/generator.py`, `backend/app/programs/reports/service.py`, `backend/tests/test_reports.py` |
| **A4** | Wave 1 | **`[x]` 완료** | **P0 (검증)** | `7-1` | `visual_check.py`가 날짜 숫자 조각(`2027`, `3`, `10`, `04`)을 환각으로 오탐해 정상 Liner 차트 거부 | `backend/app/llm/visual_check.py`, `backend/tests/llm/test_visual_check.py` |
| **A5** | Wave 2 | **`[△]` 일부(`qdrant-local.sh`)** | **P1 (운영)** | `3-1` | Qdrant `Too many open files` (500) 실패 + 재시도마다 `embed` API 반복 과금 | `scripts/qdrant-local.sh`(`[x]`), `backend/app/files/jobs.py`(`[ ]`), `backend/app/files/vectors.py`, `backend/tests/files/test_jobs.py` |
| **A6-1** | Wave 2 | **`[ ]` 잔여** | **P1 (도구)** | `2-6` | `schedule.import`가 `담당자원` 열을 버리고 `EL-130` 빈 자원 가정 미기록 | `backend/app/files/schedule_import.py`, `backend/app/tools/generate/import_schedule.py`, `backend/app/agent/prompts/import_map.md`, `backend/tests/files/test_schedule_import.py` |
| **A6-2** | Wave 2 | **`[ ]` 잔여** | **P1 (도구)** | `3-1` | 에이전트 5축 분류 수정 도구 부재 (`files.set_axes`) | `backend/app/tools/data/set_file_axes.py` (신규), `backend/app/agent/prompts/system.md`, `backend/app/agent/prompts/guides/files.md` |
| **A6-3** | Wave 2 | **`[ ]` 잔여** | **P1 (도구)** | `5-4` | FieldHub 현장 데이터(`field_items`) 조회 도구 부재 (`field.list`) | `backend/app/tools/data/list_field.py` (신규), `backend/app/agent/prompts/system.md` |
| **A7** | Wave 2 | **`[△]` `max_tokens=12000` 완료** | **P1 (성능)** | `10-2` | 비정형 IT/SW 생성 `extract_conditions` `max_tokens=6000` 절단 재시도 + 총 소요 `240s` 초과 | `backend/app/tools/generate/extract_conditions.py`(`[x]`), `backend/app/agent/domain_synth.py`(`[x]`), `backend/app/agent/generation_steps.py` (E2E 재확인 필요) |
| **B1** | Wave 3 | **`[ ]` 잔여** | **P2 (UX)** | `5-2`, `5-4` | 모바일 `390px` 상단 바 `"나가기"` 버튼 우측 클리핑 | `frontend/src/os/MobileShell.tsx`, `frontend/src/os/mobile.css` |
| **B2** | Wave 3 | **`[ ]` 잔여** | **P2 (UX)** | `3-1` | 좁은 데스크톱 `Chat` 창에서 `이 대화의 파일` 컨텍스트 패널 미노출 | `frontend/src/programs/chat/Chat.tsx`, `frontend/src/programs/chat/chat.css` |
| **B3** | Wave 3 | **`[ ]` 잔여** | **P2 (UX)** | `PRE-03` | `AppDrawer` 편집 `"완료"` 버튼이 모달을 닫지 않아 설정 화면 버튼 가림 | `frontend/src/os/AppDrawer.tsx`, `frontend/src/programs/settings/AppearanceSection.tsx` |
| **B4** | Wave 3 | **`[ ]` 잔여** | **P2 (UX)** | `4-3` | 타인 제안 `거부하고 다시 짜게 하기` 교차 계정 시 원 제안자에게 시각적 알림/배지 부족 | `backend/app/programs/approvals/service.py`, `backend/app/store/approvals.py`, `frontend/src/programs/approvals/useApprovalData.ts`, `frontend/src/programs/chat/` |
| **B5** | Wave 3 | **`[ ]` 잔여** | **P2 (UX)** | `5-5` | 태블릿 `1180×820` 왼쪽 레일 하단 아이콘(`승인함`) 구분선 경계 잘림 | `frontend/src/os/TabletShell.tsx`, `frontend/src/os/tablet.css` |
| **B6** | Wave 3 | **`[ ]` 잔여** | **P2 (콘솔)** | `9-2` | 개발 콘솔 `H-LOOP-01`·`H-LIM-01` 정적 `contract_check` JSON 반환 | `backend/app/programs/devconsole/catalog.py`, `frontend/src/programs/devconsole/HarnessTab.tsx` |
| **C1~C5** | Wave 4 | **`[x]` 완료** (`B3` 후 `C2` 재확인) | **P3 (문서)** | `PRE-03`, `2-1`, `5-5`, `7-2` | SOP 지시서(`실무_작업_시나리오_지시서.md`) ↔ 실제 UI 표기/절차 5건 불일치 | `docs/demo/실무_작업_시나리오_지시서.md`, `frontend/src/programs/reports/ReportsTab.tsx` |

---

## 2. 설계 결정 현황 (2건 모두 확정 및 Wave 1·4 반영 완료)

1. **`[확정 — 권장안 반영 완료]` 결정 1 — [A1] `내 규칙(scope="schedule")` 승인 시 `Plan` 기준선 갱신 여부**
   - `text_only` 규칙 또는 실제 계획 작업/계산 날짜를 바꾸지 않는 규칙 승인은 `plan_change=False`로 두어 기존 `Plan` 기준선과 `SPI`/지연 경고를 유지하고, 실제로 일정·달력을 바꾸는 규칙만 `Plan`을 갱신하도록 구현 완료 (`test_plan_frozen.py` 두 케이스 분리 검증 완료).

2. **`[확정 — 옵션 A 반영 완료]` 결정 2 — [C5] `STEP 7-2` 보고서 양식 학습 후 저장 UX**
   - 2단계(`양식 분석 · 학습` → 바인딩 검토·수정 → `이 프로젝트에 양식 기억` 클릭 저장) 구조를 유지하되, `ReportsTab.tsx`에 미저장 초안 안내 배너(`role="status"`)를 추가하고 `docs/demo/실무_작업_시나리오_지시서.md` `STEP 7-2` 절차를 일치시킴.

---

## 3. Wave 1 (P0) — 핵심 데이터 정합성 · 보고서 · 차트 검증

### [A1] 일정 범위 `내 규칙` 승인 시 `Plan` 기준선 덮어쓰기 결함 (`STEP 4-3`, `STEP 4-4`)

#### (a) 현상 및 재현 경로
1. `STEP 4-1` 시점 기준 `5층 사무동 신축` 프로젝트는 `Plan 2027.10.20` vs 예측 준공 `2027.10.29` (`+8일` 지연, `SPI 0.87`, 지연 경고 `49건`) 상태였다.
2. `STEP 4-3`에서 `planner.kim`이 `"야간 작업 금지 (주변 민원)"` 규칙(`scope="schedule"`, `condition.kind="text_only"`, `params={}`)을 `rules.propose`로 제안해 승인 ID `#9`가 생성되었고, `admin`이 이를 승인해 버전 `3`이 저장되었다.
3. 직후(`STEP 4-4`) `공정률` 및 에이전트 `progress.read` / `schedule.list`를 조회하자:
   - `5층 사무동 신축`의 `Plan` 완료일이 `2027.10.20 → 2027.10.29`로 덮어써짐.
   - 계획 공정률 `16.0% → 14.0%`, `SPI 0.87 → 0.99`, `Plan 대비 +8일 → 0일`, 경고 `49건 → 0건`, `schedule.list` 위험도 `danger → ok`로 왜곡되어 화면/업무 상태와 불일치 발생.

#### (b) 코드 수준 근본 원인
1. `backend/app/tools/out/propose_rule.py:106-120` (`_schedule_rule`):
   - `scope == "schedule"`일 때 `before == after`지만 `after_conditions=[*stored, rule["condition"]]`를 담아 `Proposal(kind="change", ..., link_kind="rule", rule_json=rule)`을 생성한다.
2. `backend/app/store/approvals.py:81-97` (`_plan_change`):
   - 93~94행에서 `if row.link_kind == "rule": return True`로 무조건 `True`를 반환한다.
   - 그 결과 `apply()`(`approvals.py:116-120`)가 `save_new_version(..., plan_change=True)`를 호출하고, `versions.py:62-75` (`_plan`)가 `actuals`까지 반영된 지연 상태의 CPM 결과를 새 버전의 `plan_json`에 덮어쓴다.
3. `frontend/src/programs/approvals/DecisionBox.tsx:15-17`:
   - UI 힌트는 `item.kind === 'rule'`일 때만 *"일정은 바뀌지 않고..."*를 표시하지만, 일정 범위 규칙은 `kind === 'change'`(`link_kind === 'rule'`)이므로 일반 버전 변경 힌트만 출력되고 `Plan` 갱신 여부도 드러나지 않는다.

#### (c) 구체적 수정 지시사항
1. **`backend/app/store/approvals.py` (`_plan_change`, L81-97):**
   - `row.link_kind == "rule"` 분기에서 무조건 `True`를 반환하지 않도록 수정한다.
   - 판별 로직:
     - `before, conditions, _ = load(session, row.schedule_id, row.base_version)`
     - `after = from_json(row.snapshot_json)`
     - `rule_kind = ((row.rule_json or {}).get("condition") or {}).get("kind")`
     - 만약 `rule_kind == "text_only"`이거나 `not plan_changed(before, after)` **이면서** 추가/변경된 조건이 실제 CPM 날짜·자원·캘린더 계산을 바꾸지 않는 경우(예: `plan_with(after_no_actuals, row.conditions_json)` vs 기존 `Plan`, 또는 `calendar`/`blocked_period`/`max_duration`/`min_gap`이 실제로 일정을 변경했는지 확인) → `return False`로 기존 `plan_json`을 물려받는다.
     - 실제 공정 날짜나 캘린더/제약을 바꾸어 기준 계획 자체가 달라지는 규칙만 `return True` 처리한다.
   - **참고(주석/계약):** `approvals.py:82-88` 및 `versions.py:9-12`의 Docstring도 수정된 정책(`text_only` 및 비일정변경 규칙은 기존 `Plan` 상속)과 일치하게 갱신한다.
2. **`backend/app/tools/out/propose_rule.py` (`_schedule_rule`, L106-120):**
   - `rule_json`이 생성된 `Approval` 레코드에도 정확히 보존되는지 `propose()` (`backend/app/agent/proposals.py`) 연결을 확인한다(누락되어 있다면 `rule_json` 전달 보장).
   - `summary_json`에 `plan_change` 예상 여부를 포함하면 승인함 UI에서 명확히 표시 가능하다.
3. **`frontend/src/programs/approvals/DecisionBox.tsx` (L15-21):**
   - `item.kind === 'change'` 중 `link_kind === 'rule'`이면서 `plan_change`가 `false`인 건에는 `"승인하면 내 규칙이 일정에 반영되며, 기존 기준선(Plan)은 유지됩니다."` 안내를 표시한다.
4. **`backend/tests/programs/test_plan_frozen.py` (L150-158):**
   - 기존 `test_approving_a_schedule_rule_snaps_the_forecast`는 `kind="text_only"`를 넣고 `Plan`이 스냅되는 것을 검증하고 있으므로:
     - `test_approving_text_only_schedule_rule_keeps_plan`: `text_only` 규칙 승인 시 버전은 증가(`v3`)하되 `_plan(v)`는 `SNAPPED`(`2027-03-01 ~ 2027-03-12`)가 유지됨을 검증.
     - (신규) `test_approving_calendar_schedule_rule_updates_plan`: 실제 근무일수/일정을 변경하는 규칙(`calendar` 등) 승인 시 동작을 명시적으로 검증.

#### (d) 구현 시 주의할 함정 (Pitfalls)
- `approvals.py:93-94`의 `if row.link_kind == "rule": return True` 두 줄만 단순히 삭제하면 바로 아래 96행 `list(row.conditions_json) != conditions`가 **여전히 `True`를 반환한다**(규칙 1건이 `conditions_json`에 추가되었기 때문). 반드시 93~94행 내부에서 `"일정 변경 없는 규칙"` 판별 후 명시적으로 `return False`를 해야 한다.

#### (e) 검증 방법
- `cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest tests/programs/test_plan_frozen.py tests/programs/test_approvals_api.py tests/programs/test_rules_api.py`
- 실환경 E2E: `5층 사무동 신축` 지연 상태에서 `야간 작업 금지 (text_only)` 승인 후 `Plan 2027.10.20`, `SPI 0.87`, `지연 +8일`, `schedule.list` 위험도 유지 확인.

---

### [A2] 보고서 양식 파일 LLM 학습 시 전 항목 `manual_input` 오매핑 (`STEP 7-2`, `7-3`, `7-4`)

#### (a) 현상 및 재현 경로
1. `STEP 7-2`에서 `발주처_월간공정보고_양식.md`(제목: `1. 금월 프로젝트 핵심 요약`, `2. 마일스톤 표`, `3. 지연 원인 분석`, `4. 3주 룩어헤드`)를 업로드하고 `양식 분석 · 학습` 실행.
2. 실 Liner LLM(`deepseek/deepseek-v4.1-flash-1017`) 응답 결과 4개 섹션 모두 `block_kind="manual"`, `data_binding="manual_input"`(`직접 입력`)으로 저장됨 (`report_templates` id=1, 2).
3. 그 결과 `STEP 7-3` 월간 보고서 생성 본문이 ChronOS 수치·표 없이 빈 입력 상자 4개(`bodyLen=389`)로 생성되었고, `STEP 7-4` `report.revise`도 데이터를 몰라 `"[지연/정상] · *(데이터 미연계)*"`를 출력함.

#### (b) 코드 수준 근본 원인
1. `backend/app/programs/reports/learner.py:279-284` (`learn_from_file`의 `system_prompt`):
   - `LEARN_SCHEMA`에는 `enum` 문자열(`"summary_prose"`, `"milestone_table"`, `"delay_table"`, `"lookahead_3w"`, …)만 있고, `system_prompt`에는 **각 `data_binding` 슬롯이 무슨 ChronOS 자료를 뜻하는지 설명이 전혀 없다**.
   - 반면 283행은 *"연결할 ChronOS 자료가 없는 항목은 block_kind='manual', data_binding='manual_input'으로 둔다"*라고 강조해 LLM이 보수적으로 전 항목을 `manual_input`으로 분류했다.
2. `backend/app/programs/reports/learner.py:205-239` (`_sanitize_llm_result`):
   - 정작 규칙 기반 `_infer_binding(heading, has_table)`(`learner.py:97-119`)은 `"요약"→summary_prose`, `"마일스톤"→milestone_table`, `"지연"→delay_table`, `"다음/룩어헤드/lookahead"→lookahead_3w`를 정확히 매핑할 수 있는데, LLM 응답을 정제하는 `_sanitize_llm_result()`에서 `binding == "manual_input"`일 때 `_infer_binding`을 호출해 보정하는 안전망이 없다.
   - 또한 `_infer_binding()` L113의 키워드 목록 `("익월", "차월", "차분기", "다음", "추진계획", "주요예정", "예정작업", "lookahead")`에 한국어 `"룩어헤드"`, `"3주"`, `"향후계획"`이 빠져 있어 `"4. 3주 룩어헤드"`는 휴리스틱에서도 놓칠 위험이 있다.

#### (c) 구체적 수정 지시사항
1. **`backend/app/programs/reports/learner.py`:**
   - `_infer_binding()`(L97-119):
     - `lookahead_3w` 키워드에 `"룩어헤드"`, `"3주"`, `"향후"`, `"착수예정"` 추가.
     - `delay_table` 키워드에 `"원인"`, `"만회"`, `"부진"` 등 보강; `"현장 특기사항"`·`"특기사항"`처럼 진짜 자유 서술인 제목은 `manual_input`을 유지하도록 기존 테스트(`test_reports.py:115-116`) 호환성 확인.
   - `LEARN_SCHEMA` & `system_prompt` (L59-67, L279-284):
     - `system_prompt`에 ChronOS의 10가지 `data_binding` 슬롯 정의와 선택 기준을 명시:
       - `summary_prose` (`block_kind="prose"`): 경영 요약·핵심 요약·총평·개요 문단
       - `kpi_summary` (`kpi`): 계획/실적 공정률·SPI·준공일 등 핵심 KPI 카드
       - `s_curve_month` (`chart`): 월별/기간별 누적 S-커브 차트
       - `spi_trend` (`chart`): SPI/성과지수 추이 차트
       - `milestone_table` (`table`): 주요 마일스톤 일정·상태 표
       - `wbs_table` (`table`): WBS·공종별 진도/공정률 표
       - `delay_table` (`table`): 지연 작업·지연 원인·만회/리스크 표
       - `lookahead_3w` (`table`): 3주 룩어헤드·차기/익월 예정 작업 표
       - `scenario_compare` (`table`): 만회안·단축안 시나리오 비교 표
       - `manual_input` (`manual`): 위 공정 데이터와 무관한 순수 자유 기입란(안전 특기사항·발주처 전달메모 등)일 때만 사용
     - **중요 지시:** *"문서 제목이나 표 내용이 위 ChronOS 슬롯 중 하나와 대응하면 반드시 해당 `data_binding`을 선택하고 `manual_input`을 남발하지 말 것"* 명시.
   - `_sanitize_llm_result()` (L205-239):
     - 각 섹션에서 LLM이 `binding == "manual_input"`을 반환했더라도, `_infer_binding(heading, bool(cols))`의 반환값이 `!= "manual_input"`이면 추론된 `(kind, binding)`으로 교정한다.
     - 만약 교정된 `kind == "table"`인데 LLM의 `table_columns`가 비어 있다면 `fallback[2]`(휴리스틱 결과) 중 유사 heading 섹션의 `table_columns`를 보조 채움한다.
     - `analysis_summary`에도 실제 연결된 항목 수(`sum(s.data_binding != "manual_input" for s in sections)`)가 정확히 반영되게 보정한다.
2. **`backend/tests/test_reports.py`:**
   - 기존 테스트(`test_reports.py:115-116` `"현장 특기사항" == "manual_input"`) 통과 유지.
   - 실 LLM(`LlmClient.chat` mock)이 `발주처_월간공정보고_양식.md` 4개 항목을 모두 `manual_input`으로 반환하는 상황에서도 `_sanitize_llm_result`가 `summary_prose`, `milestone_table`, `delay_table`, `lookahead_3w`로 복구함을 검증하는 단위 테스트 추가.

#### (e) 검증 방법
- `cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest tests/test_reports.py`
- 실환경 E2E(`STEP 7-2~7-3`): `발주처_월간공정보고_양식.md` 학습 시 4개 항목이 모두 `연결됨` 상태로 매핑되고 보고서 생성 시 실제 KPI·표 데이터가 채워짐을 확인.

---

### [A3] 보고서 서술 LLM `max_tokens=800` 문장 중도 절단 및 `revise` 무경고 폴백 제거 (`STEP 7-3~7-5`)

#### (a) 현상 및 재현 경로
1. `STEP 7-3` / `STEP 7-5`에서 기본 양식으로 월간/분기 보고서를 생성하면 요약 문단이 `"2027.04.17 기준 월간 계획 공정률은 16.0%, 실적 공정률은 13.9%로 계획 대비 -2.1%p를"`, `"2027년 3분기 주기 보고 기준 가"`처럼 첫 문장 도중에 끊김.
2. `llm_calls` 로그 `#220`, `#221` 확인 결과 `output_tokens=800`, `finish_reason='length'`로 중단됨.
3. 또한 `revise_block_text`는 LLM 실패 시 오류를 알리지 않고 HTTP 200과 함께 원문 뒤에 `"[수정 반영: <지시>]"`를 조용히 덧붙인다.

#### (b) 코드 수준 근본 원인
1. `backend/app/programs/reports/generator.py:168` (`_draft_prose_with_llm`) 및 `L423` (`revise_block_text`):
   - `max_tokens=800`으로 호출하고 있어, 추론형 모델(`deepseek/deepseek-v4.1-flash-1017`)이 내부 thinking 토큰을 소모한 뒤 본문 1~2문장 시점에 토큰 상한에 걸려 `finish_reason='length'`로 잘린다.
2. `generator.py:170-171`:
   - `reply.finish_reason == "length"` 확인 없이 잘린 `reply.text`를 그대로 반환·저장한다.
3. `generator.py:400-430` (`revise_block_text`):
   - `schedule_id`나 `ProgressOut` 요약 수치를 받지 않아 빈 블록이나 `manual_input` 블록을 `"지연 원인을 구체 수치로 보강"`하라고 요청할 때 LLM이 `*(데이터 미연계)*`를 출력하거나 수치를 짐작할 수밖에 없다.
   - `L428-430`: 예외/빈 응답 시 실패를 숨기고 `f"{current_text}\n[수정 반영: {instruction}]".strip()`를 반환해 보고서 원문을 오염시킨다.

#### (c) 구체적 수정 지시사항
1. **`backend/app/programs/reports/generator.py`:**
   - `_draft_prose_with_llm()` (L160-175):
     - `max_tokens=4000`으로 상향 (`app/llm/client.py` 기본 일반 호출 여유).
     - `if reply.finish_reason == "length" or not cleaned: return fallback_text` (문장이 중간에 잘렸으면 절대 DB에 저장하지 않고 결정론적 문안 `_deterministic_summary`로 안전 폴백 + 경고 로그).
   - `revise_block_text()` (L397-430):
     - 시그니처에 `schedule_id: int | None = None` 또는 `facts_text: str = ""` 추가(기존 호출부 호환 위해 기본값 제공). `schedule_id`가 있으면 `_build_facts()` 수준의 검증된 프로젝트 공정 수치(계획/실적 공정률, SPI, 준공일, 상위 지연/마일스톤)를 프롬프트에 함께 전달.
     - `max_tokens=4000`으로 상향.
     - `fake.enabled()`가 아닌 실 LLM 모드에서 예외 발생, `reply.finish_reason == "length"`, 또는 응답 본문이 비어 있는 경우 `"[수정 반영: ...]"`를 붙이지 말고 `ApiError(502, "llm_revise_failed", "AI 문단 수정에 실패했습니다. 잠시 후 다시 시도해 주세요.")`를 발생시켜 원문을 보호한다.
2. **`backend/app/programs/reports/service.py` (`revise_report_block`, L366-395):**
   - `generator.revise_block_text(session, blocks[idx], body.instruction, style, schedule_id=schedule_id)` 형태로 `schedule_id` 전달.
   - `ApiError`가 올라오면 `session.commit()`하지 않고 오류 반환.
3. **`frontend/src/programs/reports/ReportsTab.tsx` (`handleReviseBlock`, L380-405):**
   - `reviseReportBlock` 실패 시 기존 `setError(...)` 분기가 원문을 덮어쓰지 않는지 확인하고, 수정 성공 시 규칙 기억 안내 유지.
4. **`backend/tests/test_reports.py`:**
   - Mock LLM이 `finish_reason="length"` + 반쪽 문장을 반환하면 `_draft_prose_with_llm`이 `_deterministic_summary` 완전 문장을 반환하는 테스트 추가.
   - 실모드(`fake` 꺼짐)에서 `revise_report_block` LLM 실패 시 `"[수정 반영: ...]"`가 저장되지 않고 502 에러와 함께 원문이 보존됨을 검증하는 테스트 추가.

#### (e) 검증 방법
- `cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest tests/test_reports.py`
- 실환경 E2E(`STEP 7-3`, `7-4`, `7-5`): 보고서 요약 문단이 마침표로 완결되는 3~5문장으로 생성되고, AI 수정 시 프로젝트 실수치 기반 문장이 반영되는지 확인.

---

### [A4] `visual_check.py` 날짜 숫자 조각 오탐으로 정상 Liner 차트 거부 (`STEP 7-1`)

#### (a) 현상 및 재현 경로
1. `STEP 7-1`에서 `공정률 > 보고서용 그림` 생성 클릭 시 Liner Visualization API가 정상 Chart.js HTML을 반환했고, 데이터 82개 중 82개(`passed=82, total=82`) 모두 표 수치와 일치했다.
2. 그러나 검증기(`visual_check.py`)가 `problems: ["보이는 글에 표에 없는 숫자: 2027", "...: 3", "...: 10", "...: 04"]`로 실패 판정해 `"Liner 그림 검증 실패 → 기본 그림"`으로 폴백됨.

#### (b) 코드 수준 근본 원인
1. `backend/app/llm/visual_check.py:48`:
   - `_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")` — 하이픈 ISO 형식(`YYYY-MM-DD`)만 날짜로 인식한다.
2. `visual_check.py:195-206` (`_check_visible`):
   - 201행 `rest = _DATE.sub(" ", text)`로 `YYYY-MM-DD`만 지운 뒤, 204~206행에서 `_SHOWN_NUMBER.findall(rest)`로 남은 모든 숫자가 `table.rows`의 float 집합(`numbers`)에 있는지 검사한다.
   - Liner 차트의 X축 라벨/제목/툴팁에는 `2027년 3월`, `2027.10.30`, `04.17`, `3/15` 등 로캘 날짜 표기가 포함되는데, `_DATE`에 걸리지 않아 `2027`, `3`, `10`, `04`가 표에 없는 환각 숫자로 오탐된다.

#### (c) 구체적 수정 지시사항
1. **`backend/app/llm/visual_check.py` (`_check_visible` L195-206 부근):**
   - `table.rows` 및 축 범위 내 날짜 값에서 실제 존재하는 `YYYY-MM-DD` 문자열들을 파싱해 유효 날짜 `(year, month, day)` 집합과 연도 집합을 추출한다.
   - `_check_visible`에서 `_DATE.sub(" ", text)` 이후, **표에 존재하는 날짜/연도 범위에서 파생된 날짜 포맷 토큰만** 정규식으로 안전하게 치환 제거한다(예시):
     - `YYYY년 M월 DD일`, `YYYY년 M월`, `M월 D일` (해당 연·월·일이 표 날짜에 실제 속할 때만!)
     - `YYYY.MM.DD`, `YYYY/MM/DD`, `YYYY.MM` (표 날짜/연월과 일치할 때만!)
     - `MM.DD`, `M/D` (표 날짜의 월·일 쌍과 일치할 때만!)
     - 차트 제목·축 라벨에 단독으로 쓰인 연도 `YYYY` (예: `2027년`, 또는 표 날짜 연도 집합에 포함된 4자리 연도 앞뒤 구분)
   - 위 조건에 맞지 않는 숫자(예: 표에 없는 연도 `2029`, 환각 수치 `99.9%`, `150일`)는 **절대 치환하지 않고** 그대로 `_SHOWN_NUMBER` 검사에서 차단한다.
2. **`backend/tests/llm/test_visual_check.py`:**
   - 기존 모든 테스트가 그대로 통과하는지 확인.
   - 표에 `"2027-03-01" ~ "2027-10-30"` 날짜가 있을 때 HTML 차트 텍스트/JS에 `"2027년 3월"`, `"04.17"`, `"2027.10.30"`이 포함되어도 `verdict.ok is True`가 되는 테스트 추가.
   - 동시에 표에 없는 연도(`"2029년 5월"`)나 표에 없는 수치(`"123.4%"`)가 섞이면 여전히 `verdict.ok is False`로 차단되는 회귀 테스트 추가.

#### (d) 구현 시 주의할 함정 (Pitfalls)
- 단순히 `1~31`이나 `2020~2030` 정수를 `numbers` 화이트리스트에 통째로 추가하면 `test_visual_check.py`의 환각 탐지 테스트(표에 없는 임의의 작은 정수 탐지)가 깨진다. 반드시 **날짜 구문(년/월/일·구분자 포함) + 표 날짜와의 대조** 방식으로만 제거해야 한다.

#### (e) 검증 방법
- `cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest tests/llm/test_visual_check.py tests/programs/test_visuals_api.py`
- 실환경 E2E(`STEP 7-1`): 보고서용 그림 생성 시 `"기본 그림"` 폴백 대신 Liner 차트가 검증을 통과해 정상 표시되는지 확인.

---

## 4. Wave 2 (P1) — 인프라 안정성 · 에이전트 도구 3종 · 생성 속도

### [A5] Qdrant `Too many open files` 해소 및 임베딩 API 중복 과금 차단 (`STEP 3-1`)

#### (a) 현상 및 재현 경로
1. `STEP 3-1`에서 시방서/양식 파일 업로드 시 `files.status='extracted'`, `reason='뜻 검색 준비 안 됨'`으로 머물고 Qdrant 벡터 색인이 완료되지 않음.
2. Qdrant 로그(`HTTP 500`): `RocksDB open error: Too many open files` (동일 프로세스에 2번째 컬렉션 생성 시 FD 소진).
3. 백엔드 `files/jobs.py`가 Qdrant 500 실패 후 `RETRY_S(30초)`마다 재시도하면서 선행 단계인 외부 `embed` API를 매번 재호출해 `llm_calls` #215, #217, #222~224, #240~242, #258~260 등 동일 파일 임베딩이 여러 번 과금됨.

#### (b) 코드 수준 근본 원인
1. `scripts/qdrant-local.sh:32-36`: macOS 기본 프로세스 파일 디스크립터 상한(보통 256~2560)을 상향하지 않고 `exec "$BIN"` 실행.
2. `backend/app/files/jobs.py:191-198` (`_store_vectors`):
   - `found = await embed(...)` (외부 과금) → `await asyncio.to_thread(store.upsert, collection, points)` 순서로 실행된다.
   - `store.upsert` (`vectors.py:60-71`)가 Qdrant HTTP 500(`UnexpectedResponse`)을 던지면 `_index_file` 전체가 실패하고 `_failed()` (`jobs.py:318-334`)가 `item.retries < MAX_RETRIES(3)`인 동안 30초 뒤 재시도한다.
   - 이때 `store.available()` (`vectors.py:55-58`)은 `get_collections()`만 200 OK로 확인하므로 통과하고, 다시 `embed()`를 호출한 뒤 `create_collection`에서 또 500으로 실패하는 과금 루프가 최대 4회(최초+재시도3회) 파일마다 돈다.

#### (c) 구체적 수정 지시사항
1. **`scripts/qdrant-local.sh` (L32-36):**
   - `exec "$BIN"` 직전에 FD 상한을 높인다:
     ```bash
     ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true
     echo "Qdrant file descriptor limit: $(ulimit -n)"
     ```
2. **`backend/app/files/jobs.py` (L191-198, L224-238, L318-334) & `backend/app/files/vectors.py`:**
   - **방안 (1+2 병행 권장):**
     1. Qdrant 서버 내부 오류(`UnexpectedResponse` status >= 500, 또는 `create_collection`/`upsert`의 `RocksDB`/5xx 예외)는 `_QdrantDown` 또는 별도 장기 백오프 오류로 간주해 30초 단기 재시도(`_queue`) 대신 `_waiting`(5분 `RECHECK_S`)으로 이동시켜 파일마다 `embed()`가 4번씩 돌지 않도록 차단.
     2. `_store_vectors`에서 이미 계산된 임베딩 벡터를 `(file_id, model)` 단위로 인메모리 캐시(성공·포기 시 즉시 `pop`, 상한 크기 제한 예: 최근 몇 건)하거나 `store.upsert` 실패 시 직전 임베딩 결과를 폐기하지 않고 재사용 가능하게 설계해, 어떤 재시도 경로에서도 동일 청크의 `embed()` 중복 호출을 원천 차단한다.
3. **`backend/tests/files/test_jobs.py`:**
   - `store.upsert`가 Qdrant `UnexpectedResponse`(500) 또는 예외를 던질 때 `embed` mock 호출 횟수가 파일당 1회를 넘지 않고 안전하게 `_waiting` / `NOT_READY` 처리됨을 검증하는 단위 테스트 추가.

#### (e) 검증 방법
- `cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest tests/files/test_jobs.py tests/files/test_vectors.py`
- Qdrant 재시작 시 로그에 `Qdrant file descriptor limit: 65536`(또는 `10240` 이상) 확인, 새 컬렉션 생성 후 파일 `status='classified'` 전환 및 `llm_calls` `embed` 1회 호출 확인.

---

### [A6-1] `schedule.import` CSV `담당자원` 열 지원 및 빈 자원 가정 기록 (`STEP 2-6`)

#### (a) 현상 및 재현 경로
1. `STEP 2-6`에서 `협력사_전기설비_공정표.csv`(`작업ID, 작업명, WBS, 기간(일), 선행작업, 담당자원` 포함, `EL-130` 행만 `담당자원` 빈칸)를 업로드하고 가져오기 실행.
2. 결과: 5개 액티비티·v1 승인까지 완료되었으나, `EL-120` 기간 5일 가정만 남고 `EL-130` 빈 담당자원 가정은 누락됨(에이전트가 *"도구가 자원 가정은 남기지 않았습니다"*라고 직접 응답).

#### (b) 코드 수준 근본 원인
1. `backend/app/files/schedule_import.py:34-36`:
   - `COLUMNS = ("id_col", "name_col", "wbs_col", "duration_col", "pred_col", "start_col", "finish_col")`에 `resource_col`이 없다.
   - `Plan` (`L148-165`), `ImportedRow` (`L239-268`), `ImportedRows.estimates()` (`L312-324`), `convert()` (`L369-399`) 모두 자원을 읽거나 병합하지 않는다.
2. `backend/app/tools/generate/import_schedule.py:80-93` (`ColumnsIn`) & `L176-183` (`_request`):
   - `ColumnsIn`에 `resource_col`이 없고 `_request()`가 LLM에 `id | 이름 | WBS | 기간 | 선행`만 넘긴다.
   - 참고: 핵심 도메인 모델 `backend/app/core/model.py:30` (`Activity.resources: tuple[str, ...] = ()`) 및 `Schedule.resources: tuple[Resource, ...] = ()`는 이미 자원을 지원한다!

#### (c) 구체적 수정 지시사항
1. **`backend/app/files/schedule_import.py`:**
   - `COLUMNS`에 `"resource_col"` 추가, `LABELS["resource_col"] = "담당자원"`, `Plan.resource_col: str | None = None`.
   - `ImportedRow`: `resources: tuple[str, ...] | None = None` 필드 추가
     - 파일에 `resource_col`이 **있고** 해당 행에 값이 있으면 쉼표/슬래시로 분리한 비어 있지 않은 자원명 tuple (예: `("전기팀 A",)`).
     - 파일에 `resource_col`이 **있는데** 해당 행이 빈 칸이면 `None` (빈 칸 = 추정/가정 대상).
     - 파일에 `resource_col` 자체가 **없으면** `()` (해당 표에 자원 열 없음).
   - `convert()`에서 자원 문자열 파싱, `card()` `missing`에 `p.resource_col`이 있을 때 `"담당자원 빈 칸 N개"` 표시(`blank_rows` 한도 계산 영향 여부는 `od`/`preds` LLM 추정 여부와 일관성 확인).
   - `ImportedRow.merged()` (`L254-267`) & `ImportedRows.merge()` (`L284-298`):
     - 파일 값이 있으면 `resources`를 파일 값으로 고정 덮어쓰고, 빈 칸(`resources is None`)이면 생성/추정 결과(`a.get("resources")`) 또는 미지정 상태 반영.
     - 참고: `generate.build`가 `Schedule`을 조립할 때 `Activity.resources`에 등장하는 이름들이 `Schedule.resources` 정의와 매칭되는지(`generation_build.py` 확인!) 점검해 resource ID/이름 정합성을 맞춘다.
   - `ImportedRows.estimates()` (`L312-324`):
     - `r.resources is None`(파일에 자원 열이 있는데 그 행이 빈칸)인 경우, 할당된 자원이 있으면 `"담당자원 <이름>(추정)"`, 없으면 `"담당자원 미지정(파일 빈칸)"`을 `source="추정"` 가정 목록에 추가한다.
2. **`backend/app/tools/generate/import_schedule.py` & `backend/app/agent/prompts/import_map.md`:**
   - `ColumnsIn`에 `resource_col: str | None = None` 추가.
   - `_request()`(L176-183) 표에 `자원` 열(있으면 값, 빈칸이면 `?`) 포함.
   - `import_map.md` L4 열 설명에 `- resource_col: 담당 자원·팀·장비 열` 추가.
3. **`backend/tests/files/test_schedule_import.py`:**
   - `담당자원` 열이 있고 1개 행(`EL-130`)만 빈 칸인 CSV 테스트 케이스 추가: 나머지 행 자원 보존 + `estimates()`에 `EL-130` 빈 자원 가정이 `source="추정"`으로 생성됨을 검증.

#### (d) 구현 시 주의할 함정 (Pitfalls)
- `generation_build.py`가 초안을 `Schedule`로 변환할 때 `Activity.resources`와 `Schedule.resources`의 `id` 참조 규칙(미등록 `resource id` 허용 여부 vs `Resource` 객체 생성)을 반드시 먼저 확인하고 맞춘다(기존에 등록된 자원 ID가 없을 때 `check_schedule` 또는 직렬화가 실패하지 않도록 `Schedule.resources` 자동 보충 필요 여부 확인).

---

### [A6-2] 에이전트 5축 분류 수정 도구 `files.set_axes` 추가 (`STEP 3-1`)

#### (a) 현상 및 재현 경로
- `STEP 3-1` 대화 중 `"동절기 콘크리트 시방서를 자료함에 5축으로 분류해서 보관해 줘"` 요청 시, 에이전트가 *"5축 분류를 지정하는 도구가 현재 제가 쓸 수 있는 도구 목록에 없습니다"*라고 응답함(이후 비동기 백그라운드 분류가 수초 뒤 자동 수행되긴 하나, 사용자 명시 요청을 에이전트가 직접 반영/수정할 수단이 없음).

#### (b) 코드 수준 근본 원인
- 백엔드 `backend/app/programs/files/service.py:286-296`에 `patch_axes(session, file_id, body)`가 이미 완성되어 있으나 `@tool`로 노출되어 있지 않다. (현재 등록 도구 33종, 도구 총량 상한 40종 이내로 여유 있음.)

#### (c) 구체적 수정 지시사항
1. **신규 도구 모듈 `backend/app/tools/data/set_file_axes.py`:**
   - `app/tools/registry.py:115` (`load_all()`)가 `app/tools/*/` 패키지를 자동 import하므로 `app/tools/data/__init__.py` 또는 모듈 import 경로가 로딩되는지 확인한다(`app/tools/data/__init__.py` 확인 필수).
   - `@tool("files.set_axes", "자료함 파일의 5축 분류(종류·공종·현장·시기·출처)를 설정하거나 수정한다. 지정한 축만 바뀐다.", program="files", mutates=True)`
   - 입력 모델 (`ConfigDict(extra="forbid")`):
     - `file_id: int`
     - `axes: dict[Literal["종류", "공종", "현장", "시기", "출처"], list[str]]` (빈 dict 거절 또는 최소 1축)
   - 내부 실행: `programs.files.service.patch_axes(ctx.session, args.file_id, args.axes)` 호출(`ApiError` 발생 시 `ToolError(e.message)`로 변환) → 갱신된 `file_id`, `name`, `axes` 반환.
2. **프롬프트 및 가이드 보강:**
   - `backend/app/agent/prompts/guides/files.md`에 *"사용자가 첨부 파일 또는 자료함 파일의 5축(종류·공종·현장·시기·출처) 분류·태그를 지정하거나 수정을 요청하면 `files__set_axes`를 부른다."* 추가.
   - `backend/app/agent/prompts/system.md` (필요 시 도구 목록/규칙 확인).
3. **단위 테스트 (`backend/tests/tools/test_new_read_tools.py` 또는 신규 테스트):**
   - `files.set_axes`로 5축 값 설정 후 `store.files.axes_of()` 반영 확인 및 없는 `file_id` / 잘못된 축 키 거절(`ValidationError`/`ToolError`) 검증.

---

### [A6-3] FieldHub 현장 데이터 조회 도구 `field.list` 추가 (`STEP 5-4`)

#### (a) 현상 및 재현 경로
- `STEP 5-4`에서 `field.park`가 스마트폰 UI에서 D-3 핸드오프(`[ ] 자재 미준비`, `"후행 자재 창고 입고 대기(내일 오전 반입 예정)"`)와 일일 체크인을 제출한 직후, `현장 AI` 탭에서 영향 질의(턴 `#383`)를 하자 에이전트가 *"D-3 자재 준비 점검 결과 자체는 시스템에 등록돼 있지 않습니다"*라고 오답함.

#### (b) 코드 수준 근본 원인
- `backend/app/programs/progress/field.py:308-312` (`list_field`)가 `field_items` 테이블(체크인·사진 AI 판독·만회안 의견 폴·D-3 핸드오프)과 집계(`FieldSummary`)를 모두 관리하지만, 이를 읽는 `@tool`이 없어 에이전트가 `field_items`에 접근할 수 없다.
- 기존 제안서(`agent_tools_proposal.md:51-60`)의 도구 명칭인 **`field.list`** 로 통일한다 (`33 → 35종`, 40개 상한 준수).

#### (c) 구체적 수정 지시사항
1. **신규 도구 모듈 `backend/app/tools/data/list_field.py`:**
   - `@tool("field.list", "대상 일정의 현장 점검 목록(일일 체크인·현장 사진 AI 판독·만회안 의견·D-3 핸드오프 자재/장비/인력 준비 상태)과 요약 집계를 읽는다.", program="progress", mutates=False)`
   - 입력 모델 (`ConfigDict(extra="forbid")`):
     - `schedule_id: int | None = None` (`None`이면 `ctx.require_schedule_id()`)
     - `kind: Literal["checkin", "photo", "poll", "handoff"] | None = None`
     - `status: Literal["pending", "responded", "applied"] | None = None`
   - 내부 실행: `programs.progress.field.list_field(ctx.session, sid)` 호출(`ApiError` → `ToolError`) → `summary` 및 필터된 `items`(각 item의 `id`, `kind`, `activity_id`, `activity_name`, `trade`, `status`, `title`, `response_choice`, `reported_progress`, `reported_rd`, `response_note`, `payload_json` [D-3 체크리스트 `material/equipment/workforce` 포함], `updated_at`) 반환.
   - `app/tools/data/__init__.py`에서 `list_field`, `set_file_axes`가 `load_all()` 시 반드시 import 되도록 확인!
2. **프롬프트/가이드 보강:**
   - `backend/app/agent/prompts/system.md`에 *"현장 체크인, 사진 검측, 공종 담당자 만회안 의견, D-3 핸드오프(자재·장비·인력 준비 여부) 질문에는 반드시 `field__list`를 먼저 호출해 확인한다."* 추가.
3. **단위 테스트 (`backend/tests/tools/test_new_read_tools.py` 또는 신규 테스트):**
   - `handoff` 항목(`material=False`) 저장 후 `field.list` 호출 시 해당 액티비티의 자재 미준비 상태와 메모가 정확히 반환됨을 검증.

#### (d) 구현 시 주의할 함정 (Pitfalls)
- `backend/app/tools/registry.py:115-120`의 `load_all()` 구조를 먼저 확인할 것! 현재 `load_all()`은 subpackage(`app.tools.data`, `app.tools.generate`, ...)만 `importlib.import_module` 하고, 각 subpackage 내부 모듈은 해당 subpackage의 `__init__.py`에서 import해야 등록되거나 `pkgutil` 순회 방식에 의존한다. 새 파일 추가 후 `len(registry.list_tools()) == 35`가 되는지 테스트로 반드시 확인하자.

---

### [A7] `extract_conditions` / `domain_synth` `max_tokens=6000` 절단 재시도 및 비정형 생성 `240s` 초과 해소 (`STEP 10-2`)

#### (a) 현상 및 재현 경로
1. `STEP 10-2`에서 `"사내 AI 업무 포털 웹서비스 16주 구축 일정"` 요청 → 질문지 2문항 답변 + 1가정 제출 뒤 전체 생성이 `240초` 대기 한도를 초과하여 타임아웃 (`workflow_run #34` `stopped`).
2. `llm_calls` 로그 분석 결과:
   - `llm_call #253`: `generate.extract_conditions`가 `max_tokens=6000` (`light` 슬롯, 추론형 모델)에서 `finish_reason='length'`로 1회 실패해 재시도(`+23.2s` 허비).
   - 이어서 `domain_synth` (`#257`, `15.6s`) → `WBS` 생성 (`#261`, `18,477 output_tokens`, `77.4s`) → `스케줄 만들기`까지 진행되면서 총 누적 시간이 `240s`를 넘김.

#### (b) 코드 수준 근본 원인
1. `backend/app/tools/generate/extract_conditions.py:245`:
   - `max_tokens=6000`이 추론형 모델(`deepseek/deepseek-v4.1-flash-1017`)에서 JSON 스키마 생성 + thinking 토큰을 담기에 부족해 `finish_reason='length'` 1회 실패 → 전체 재시도로 불필요한 `23s` 지연을 유발한다.
2. `backend/app/agent/domain_synth.py:176`:
   - 동적 도메인 프로필 합성(`synthesize_pack`)도 `light` 모델에 `max_tokens=6000`으로 묶여 있어 비정형 도메인에서 동일한 절단 위험이 존재한다.
3. `backend/app/agent/generation_steps.py` (WBS·Schedule 단계):
   - WBS 생성이 단일 턴에서 18k+ thinking/output 토큰을 소모해 ~77초가 걸렸으며, 앞선 재시도 시간과 합쳐지면 4분(`240s`)을 초과하기 쉽다.

#### (c) 구체적 수정 지시사항
1. **`backend/app/tools/generate/extract_conditions.py` (L245) & `backend/app/agent/domain_synth.py` (L176):**
   - 두 곳 모두 `max_tokens=12000`으로 상향(추론형 모델의 thinking 토큰 여분 확보로 1회 실패+재시도 제거).
2. **`backend/app/agent/prompts/extract.md`, `domain_profile.md`, `wbs.md`, `schedule.md` 및 `generation_steps.py`:**
   - 구조화 JSON 생성 시 과도한 내부 장황함을 줄이도록 간결 출력 지침 점검(정확도·요구 스키마 훼손 없는 범위에서 불필요한 중복 설명 제거).
   - 프론트엔드/SOP 기준 생성 중 실시간 진행 배너가 사용자에게 멈춘 것처럼 보이지 않도록 `workflow` / `agent` 진행 상태 이벤트 표출 점검.
3. **`docs/demo/실무_작업_시나리오_지시서.md` (`STEP 10-2`):**
   - 비정형 도메인(웹 검색+동적 합성+L3/L4 생성)의 현실적 실 LLM 응답 SLA 안내 확인.

#### (e) 검증 방법
- `cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest tests/tools/test_generate_tools.py tests/agent/test_universal_scheduling.py`
- 실환경 E2E(`STEP 10-2`): 재실행 시 `extract_conditions`가 1회 성공하고 전체 워크플로우가 `240s` 이내로 완료→`out.submit_change` 초안 생성까지 도달하는지 확인.

---

## 5. Wave 3 (P2) — 모바일 · 태블릿 · 데스크톱 UX 및 하네스 실엔진화

### [B1] 모바일 `390px` 상단 바 `"나가기"` 버튼 우측 클리핑 (`STEP 5-2`, `STEP 5-4`)

#### (a) 현상 및 재현 경로
- `field.park` 계정으로 `390×844` 모바일 뷰포트 접속 후 프로젝트 `5층 사무동 신축` 선택 시, `MobileHeader` 우측 `"나가기"` 버튼 오른쪽 끝이 뷰포트 밖으로 잘림(`sop-STEP-5-2.png`, `sop-STEP-5-4.png`).

#### (b) 원인 및 수정 지시사항
- **근거 코드:** `frontend/src/os/MobileShell.tsx:84-132`, `frontend/src/os/mobile.css:15-80`, `L288-329`.
- **원인:** 한 줄 `.mob-head` 안에 `[아이콘/제목 + 현장 전용 배지]` + `[ScheduleSelector + DeviceSwitch(자동|폰|태블릿|PC 창 4버튼) + 테마 + 나가기]`가 모두 들어가 `390px`를 초과함.
- **수정:**
  1. `MobileShell.tsx` & `mobile.css`: `data-device="phone"`(`<= 480px`)에서 `<DeviceSwitch />` 4칸 버튼 대신 단일 순환/메뉴 토글 버튼으로 축약(또는 `전체 프로그램 > 화면 전환`으로 이동)해 가로 공간 ~130px 확보.
  2. `.mob-root[data-device="phone"] .os-site-btn` `max-width: 112px; overflow: hidden; text-overflow: ellipsis;` 보정, `.mob-title`은 `flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;` 확인, `.mob-text-btn`(`나가기`)는 `flex: none;` 유지.
- **검증:** Playwright `390×844`에서 `"나가기"` 버튼의 `getBoundingClientRect().right <= 390` 및 다른 버튼과 겹침 없음 확인.

---

### [B2] 좁은 데스크톱 `Chat` 창에서 `이 대화의 파일` 컨텍스트 패널 미노출 (`STEP 3-1`)

#### (a) 현상 및 재현 경로
- 기본 데스크톱 절반 폭 창(`wide === false`, 1100px 미만)으로 `에이전트 대화`를 사용할 때 오른쪽 `<ContextPanel />` 자체가 렌더되지 않아, 파일 첨부 직후 `이 대화의 파일` 목록·상태를 사용자가 화면에서 바로 확인할 수 없음(`sop-STEP-3-1.png`).

#### (b) 원인 및 수정 지시사항
- **근거 코드:** `frontend/src/programs/chat/Chat.tsx:73-100`, `L148-178`, `frontend/src/programs/chat/chat.css:73-110`.
- **수정:**
  1. `!wide`일 때 렌더링되는 `<SessionBar />` 우측(`+ 새 대화` 옆)에 `"파일"`(현재 대화 첨부 파일 개수가 >0이면 `"파일 (N)"` 배지) 토글 버튼을 추가한다.
  2. 토글 ON 시 좁은 창 내부 상단/우측 오버레이(`.ch-pop` 또는 전용 슬라이드 패널 + `Escape`/바깥 클릭 닫기)로 `<ContextPanel />`을 렌더링한다.
- **검증:** Vitest(`Chat.test.tsx`)에 좁은 폭(800px)에서 토글 버튼 클릭 시 `ContextPanel`이 열리고 첨부 파일이 보임을 검증하는 테스트 추가.

---

### [B3] `AppDrawer` 편집 `"완료"` 버튼이 모달을 닫지 않고 편집 모드만 해제 (`PRE-03`)

#### (a) 현상 및 재현 경로
- `설정 > 모양 > Dock 아이콘 편집` 클릭(`useShell.getState().setDrawer('edit')`) → 아이콘 순서/고정 편집 후 `"완료"` 클릭 시 모달이 닫히지 않고 `'open'` 상태로 남아, 뒤쪽 설정 창의 `"Dock 기본 구성으로 복원"` 버튼을 가림.

#### (b) 원인 및 수정 지시사항
- **근거 코드:** `frontend/src/os/AppDrawer.tsx:124-168` (`useShell.getState().setDrawer(edit ? 'open' : 'edit')`), 호출부 `AppearanceSection.tsx:203`, `DockMenu.tsx:29`.
- **수정:**
  1. `AppDrawer` 모달 헤더(`.os-drawer-head`) 우측에 명시적 닫기 버튼(`✕` / `aria-label="닫기"`)을 항상 제공한다.
  2. 또한 외부(`설정` 또는 Dock 우클릭)에서 직접 `'edit'` 모드로 열린 경우를 추적하거나, 편집 모드 `"완료"` 클릭 시 모달이 함께 닫히도록(`close()`) 동작을 정리한다(단, 기존 `AppDrawer.test.tsx` L89 등 테스트 기대 동작 확인 후 반영).

---

### [B4] 타인 제안 `거부하고 다시 짜게 하기` 교차 계정 알림·안내 보강 (`STEP 4-3`)

#### (a) 현상 및 재현 경로
- `planner.kim`이 대화에서 규칙(`#10`)을 제안하고 `admin`이 승인함에서 `거부하고 다시 짜게 하기` 실행 → 백엔드는 `owner_is_decider=False`로 반환(`approvals/service.py:128-129`)해 즉시 에이전트가 돌지 않고 `pending_retries` 큐에 적재한 뒤, `admin`에게는 *"대화 주인에게 다시 짜기 요청을 남겼습니다."*만 출력한다.

#### (b) 원인 및 수정 지시사항
- **근거 코드:** `backend/app/programs/approvals/service.py:107-130`, `backend/app/store/approvals.py:172-189`, `frontend/src/programs/approvals/useApprovalData.ts:22-29`, `frontend/src/programs/chat/`.
- **수정:**
  1. **원 제안자(`planner.kim`) UI 개선:** `Chat` 세션 목록(`ThreadList.tsx`) 및 대화 상단에 `pending_retries`가 남아 있는 대화에 `"거부 재작성 대기 N건"` 배지/알림 배너를 눈에 띄게 표시하고, 클릭 시 즉시 `resume` 실행되도록 유도.
  2. **(선택) 메뉴바 알림 연동:** 승인함/알림 배지에 자신에게 돌아온 재작성 대기 건도 안내되어 계정을 다시 로그인한 직후 바로 발견할 수 있게 개선.

---

### [B5] 태블릿 왼쪽 레일 하단 아이콘 경계 잘림 (`STEP 5-5`)

#### (a) 현상 및 재현 경로
- 태블릿 뷰(`1180×820`)에서 왼쪽 레일(`.tab-rail-scroll`)의 아이콘이 많을 때 하단 고정 영역(`.tab-rail-foot`: `메뉴 편집`, `전체 앱`, `설정`) 위쪽 경계선 바로 아래로 `승인함` 아이콘 절반이 잘려 보임(`fail-STEP 5-5.png`).

#### (b) 원인 및 수정 지시사항
- **근거 코드:** `frontend/src/os/TabletShell.tsx:350-440`, `frontend/src/os/tablet.css:120-150`.
- **수정:**
  1. `frontend/src/os/tablet.css`: `.tab-rail-scroll`에 `padding-bottom: 16px;` 및 하단 스크롤 페이드(`mask-image` 또는 `.tab-rail-foot` 상단 그라데이션)를 적용하고, `.tab-rail-btn` 패딩·아이콘 간격(`gap`)을 미세 조정해 `820px` 높이에서 기본 아이콘 6~7개가 스크롤 경계에 어색하게 걸치지 않도록 보정.

---

### [B6] 개발 콘솔 하네스 시험 `H-LOOP-01`·`H-LIM-01` 실엔진 검증 전환 (`STEP 9-2`)

#### (a) 현상 및 재현 경로
- `STEP 9-2`에서 `H-CPM-01`, `H-RES-01`, `H-CAL-01`, `H-APV-01`, `H-IN-01`, `H-OUT-01` 등은 실엔진(`engine="live_harness"`)을 실행하나, `H-LOOP-01`과 `H-LIM-01`만 정적 사전 정의 JSON(`engine="contract_check"`)을 반환함.

#### (b) 원인 및 수정 지시사항
- **근거 코드:** `backend/app/programs/devconsole/catalog.py:366-390`, `frontend/src/programs/devconsole/HarnessTab.tsx:222-232`.
- **수정:**
  1. `catalog.py`:
     - `H-LOOP-01`: 실제 `registry.call("schedule.read", {"schedule_id": 999999999}, dry_ctx)`(또는 읽기 전용 세션 컨텍스트 + savepoint 롤백 검증)를 실행해 `result.ok is False` 및 오류 메시지/reflection 트리거를 실제 측정하고 `engine="live_harness"` 반환.
     - `H-LIM-01`: `app/agent/loop.py`의 단계 한도 판정 헬퍼(또는 mock `LlmClient`로 `MAX_STEPS` 초과 루프 1회 시뮬레이션 — 외부 API 호출 없음!)를 직접 실행해 실제 `단계 한도에 닿아 멈췄습니다.` 차단 동작을 검증하고 `engine="live_harness"` 반환.
  2. `HarnessTab.tsx:226`: `tested.engine === 'live_harness'`일 때 `"실엔진 검증"` 배지 외에 만약 `contract_check`가 남는다면 구분 배지 표시.

---

## 6. Wave 4 (P3) — SOP 지시서(`docs/demo/실무_작업_시나리오_지시서.md`) 현행화 (C1 ~ C5)

코드 수정(Wave 1~3)과 맞추어 아래 5건의 지시서 문구 불일치를 `docs/demo/실무_작업_시나리오_지시서.md`에 반영한다.

| ID | 위치 (STEP) | 기존 지시서 문구 | 실제/수정 후 UI 기준 정합화 내용 | 근거 파일 |
|---|---|---|---|---|
| **C1** | `PRE-03` | 데스크톱 로그아웃 `사용자 이름 ▾ > 나가기` | 데스크톱 메뉴 표기 **`사용자 이름 ▾ > 로그아웃`** (`나가기`는 모바일/태블릿 셸 표기) | `frontend/src/os/menus.ts:143` |
| **C2** | `PRE-03` | `"완료"` 클릭 후 이어서 `"Dock 기본 구성으로 복원"` 클릭 | `[B3]` 수정 반영 시 `"완료"` 클릭으로 모달이 닫히며 바로 복원 가능함을 확인 (필요 시 `닫기(✕)`/Esc 안내 병기) | `frontend/src/os/AppDrawer.tsx:162` |
| **C3** | `STEP 2-1` | `✦ AI로 새 프로젝트 일정 생성` 클릭 시 새 프로젝트 모달(`AI 에이전트로 일정 생성` 탭)이 열림 | `✦ AI로 새 프로젝트 일정 생성` 클릭 시 모달을 거치지 않고 **즉시 새 프로젝트 격리 대화 창이 열림**(`+ 새 프로젝트 직접 만들기`만 모달 사용) | `frontend/src/os/ScheduleSelector.tsx:143-152` |
| **C4** | `STEP 5-5` | 태블릿 왼쪽 레일 맨 아래 `전체 프로그램` 버튼 | 레일 버튼 라벨은 **`전체 앱`** (`전체 프로그램`은 해당 화면이 열렸을 때 본문 제목) | `frontend/src/os/TabletShell.tsx:427` |
| **C5** | `STEP 7-2` | `양식 분석 · 학습` 클릭 후 바로 왼쪽 프로젝트 양식 목록 등록 확인 | 결정 2(옵션 A) 채택 시 `양식 분석 · 학습` 후 오른쪽 패널 하단 **`이 프로젝트에 양식 기억`** 클릭하여 DB 저장·목록 등록 확인 명시 (옵션 B 채택 시 현행 유지). 추가로 `STEP 4-3`의 교차 계정 `거부하고 다시 짜게 하기` 동작(원 제안자 대화 창 열람 시 재실행) 안내도 보완 | `frontend/src/programs/reports/ReportsTab.tsx:999-1001`, `backend/app/programs/approvals/service.py:128-129` |

---

## 7. 전체 수정 후 검증 체크리스트 및 실행 명령

### 7-1. 자동화 테스트 (코드 수정 후 필수 실행)
```bash
# 1. 백엔드 전체 단위·통합 테스트
cd /Users/janghosohn/projects/chronos/backend && .venv/bin/pytest

# 2. 프론트엔드 타입체크 및 단위 테스트
cd /Users/janghosohn/projects/chronos/frontend && npm run typecheck && npm test
```

### 7-2. 격리 실환경 E2E 재검증 체크리스트 (실 Liner API)
1. **Qdrant (`scripts/qdrant-local.sh`)** 기동 시 `ulimit -n` 상향 확인 (`A5`).
2. **Wave 1 핵심 재검증:**
   - `STEP 4-3` → `STEP 4-4`: `야간 작업 금지 (text_only)` 승인 후 `5층 사무동 신축` `Plan 2027.10.20`, `SPI 0.87`, 지연 `49건`, `schedule.list` 위험도 유지 (`A1`).
   - `STEP 7-1`: `공정률 > 보고서용 그림`에서 날짜 조각 오탐 없이 Liner 차트 통과 (`A4`).
   - `STEP 7-2` → `7-3` → `7-4` → `7-5`: `발주처_월간공정보고_양식.md` 4개 섹션 자동 바인딩(`summary_prose`, `milestone_table`, `delay_table`, `lookahead_3w`), 문장 절단 없는 완결 보고서, 실수치 기반 `revise` 동작 확인 (`A2`, `A3`).
3. **Wave 2 도구·성능 재검증:**
   - `STEP 2-6`: `협력사_전기설비_공정표.csv` 임포트 시 `EL-130` 빈 담당자원 가정 기록 (`A6-1`).
   - `STEP 3-1`: 좁은 창 `파일` 패널 확인 + 대화 중 5축 분류 수정(`files.set_axes`) + Qdrant 임베딩 1회 적재 완료 (`B2`, `A6-2`, `A5`).
   - `STEP 5-4`: FieldHub D-3 핸드오프 자재 미준비 상태 저장 후 `현장 AI`가 `field.list` 호출로 정확히 응답 (`A6-3`).
   - `STEP 10-2`: `사내 AI 업무 포털` 비정형 일정 생성 `extract_conditions` 재시도 없이 `240s` 이내 완료 (`A7`).
4. **Wave 3 UX·콘솔 재검증:**
   - `PRE-03`: `AppDrawer` 편집 완료/닫기 동작 (`B3`).
   - `STEP 5-2` (`390×844` Playwright): 헤더 `"나가기"` 버튼 우측 클리핑 없음 (`B1`).
   - `STEP 5-5` (`1180×820` Playwright): 태블릿 레일 하단 아이콘 경계 잘림 없음 (`B5`).
   - `STEP 9-2`: `H-LOOP-01`, `H-LIM-01` `실엔진 검증 (live_harness)` 배지 확인 (`B6`).
5. **정리:** 테스트 종료 후 `/tmp/chronos-sop-*` 및 테스트 Qdrant 컬렉션 제거, 운영 `:5600` / `:8210` / `:6333` 정상 동작 최종 확인.
