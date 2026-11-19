# ChronOS 계획 1 — 뼈대와 묶음 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인해서 OS 화면에 들어가 Liner 키를 넣고, 대화와 질문지로 건설 일정을 만들어 스케줄표·간트에서 보고, 조건을 바꾸면 일정이 움직이고, 에이전트의 변경을 승인·되돌릴 수 있는 상태까지 만든다.

**Architecture:** 서버(FastAPI)는 순수 계산(`core`) · 하네스 · 도구 등록부 · 에이전트 루프 · 프로그램별 API로 나뉜다. 화면(React)은 OS 셸(`os`)과 프로그램별 폴더(`programs/<이름>`)로 나뉘고, 프로그램은 매니페스트로 셸에 등록된다. LLM은 날짜를 계산하지 않는다 — 초안만 만들고 계산·점검은 코드가 한다.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · SQLite · pydantic v2 · openai SDK(base_url 교체로 Liner 호출) · cryptography(Fernet) · bcrypt · pytest · ruff / Node 22 · React 19 · TypeScript · Vite · zustand · vitest · eslint / Docker Compose

**Spec:** `docs/design/2026-11-19-ChronOS-설계.md` (v2.3 승인본). 화면 시안: https://claude.ai/artifact/3Pgg2ABkPTWJbNm24NRQep (비공개 — 형태 기준. 시안의 숫자는 예시)

**이 계획의 범위:** 설계 18장의 묶음 1. 묶음 2~4는 이 계획이 끝난 뒤 각각 별도 계획서로 쓴다(`plan-2-change-response`, `plan-3-reports-skills-domains`, `plan-4-console-rest`). 설계의 기능은 빼지 않는다.

## Global Constraints

- 화면 글자는 전부 한국어. 코드 식별자·경로·명령은 영어.
- 기준 해상도 FHD 1920×1080. 좁은 화면 대응은 하지 않는다.
- **LLM이 날짜를 계산하지 않는다.** 날짜·여유·자원 겹침·조건 통과 여부는 `app/core`, `app/harness` 코드만 계산한다.
- 점검하지 않은 조건을 통과로 표시하지 않는다. `checkable=False` 조건은 "자동 점검 안 됨"으로만 표시한다.
- 비밀값: API 키는 화면에서만 입력받아 Fernet으로 암호화해 DB에 넣는다. 응답에는 끝 4자리만. `.env`·`data/`·DB 파일은 커밋하지 않는다. 로그·추적 기록에 키를 남기지 않는다.
- 다른 회사 LLM API를 직접 부르지 않는다. 기본 연결은 Liner(`https://platform.liner.com/api/v1`).
- 예시 자료는 전부 가상. 기존 저장소(`~/schedule-management`, 미니PC `~/project-platform`) 코드와 `@sohnjangho/agent-ux-*` 패키지를 복사·설치하지 않는다(형태만 참고).
- 모듈 규칙: `app/core`는 DB·LLM·FastAPI를 import하지 않는다. `app/programs/<a>`는 `app/programs/<b>`를 import하지 않는다. 에이전트는 도구를 `app/tools/registry`로만 부른다. 화면의 `src/programs/<a>`는 `src/programs/<b>`를 import하지 않는다.
- 파일 길이: 화면 파일 권장 300줄·상한 600줄, 서버 파일 권장 400줄·상한 800줄, 함수 권장 50줄·상한 100줄. 시험·자동 생성·자료 파일 제외. `scripts/check.sh`가 검사한다.
- 색·글꼴 값은 `frontend/src/os/tokens.css`의 변수만 쓴다(값은 Task 12에 있음).
- 포트: 서버 8210, 화면 5600. 둘 다 `0.0.0.0`.
- 검증은 Docker 안에서: `docker compose run --rm backend pytest -q`, `docker compose run --rm frontend npm test`. 작업을 끝냈다고 말하기 전에 `scripts/check.sh` 전체가 통과해야 한다.
- git: `main`에 직접 작업하지 않는다. 작업마다 `feature/t<번호>-<이름>` 브랜치 → 커밋 → GitHub PR(비공개 저장소) → 확인 뒤 병합. 체크포인트마다 `~/reports/pr_YYYYMMDD_HHMM.md` 보고서(요약·diff 경로·영향·Docker 시험 로그·검토 요청).
- 작업 등급(모델): 각 Task 제목의 `[fable]` `[opus]` `[sonnet]`. 한 번에 한 작업, 끝나면 확인 뒤 다음.

## Review Focus

1. **LLM이 깨진 일정 초안을 돌려줌**(선후 고리, 없는 ID 참조, 기간 0 이하, JSON 아님) → 저장하지 않고 원인을 LLM에 돌려 다시 받는다. 한도까지 실패하면 사용자에게 이유를 말한다. — Task 9
2. **LLM 연결이 없거나 도중에 끊김·시간 초과·한도 초과** → 대화가 멈추지 않고 원인별 한국어 안내, 반쯤 만든 일정은 저장되지 않는다. — Task 6, 10
3. **조건끼리 부딪혀 맞출 수 없음**(준공 기한이 너무 이름) → 루프가 한도에서 멈추고, 가장 나은 안과 부딪히는 조건을 보고한다. 무한 루프·조용한 통과 없음. — Task 9
4. **오래된 버전에 대한 승인** — 에이전트가 변경안을 낸 뒤 사용자가 일정을 직접 고쳤다 → 승인 시 충돌을 알리고 반영하지 않는다. — Task 11
5. **쉬는 날·경계 입력** — 시작일이 공휴일, 기간 0(마일스톤), Actual이 Plan보다 앞, 자원 수량 0 → 계산이 예외 없이 정해진 규칙대로 답한다. — Task 2, 3

---

## File Structure

```
docker-compose.yml  scripts/check.sh  scripts/check_lines.py  scripts/check_secrets.sh
backend/
  pyproject.toml  Dockerfile
  app/main.py  app/config.py  app/db.py
  app/core/        model.py  calendar.py  cpm.py  resources.py          순수 계산
  app/harness/     conditions.py  checks.py  assemble.py                조건 점검
  app/store/       tables.py  schedules.py  versions.py                 저장·버전·변경 이력
  app/security/    passwords.py  tokens.py  crypto.py  deps.py
  app/llm/         client.py  connections.py  errors.py
  app/tools/       registry.py  context.py
                   generate/extract_conditions.py  make_wbs.py  make_schedule.py
                   calc/run_cpm.py  check/run_harness.py  data/read_schedule.py
                   ask/make_questionnaire.py  out/submit_change.py  ui/open_window.py
  app/agent/       loop.py  context.py  generation.py  events.py  approval.py  workflow_log.py
  app/domains/     loader.py  construction/pack.yaml
  app/programs/    auth/ llm_settings/ chat/ questionnaire/ schedule/ conditions/
                   approvals/ workflow/ explorer/   — 각 router.py service.py schemas.py
  tests/           app 구조를 그대로 따른다
frontend/
  package.json  vite.config.ts  Dockerfile  eslint.config.js
  src/main.tsx
  src/os/          tokens.css  Login.tsx  Desktop.tsx  MenuBar.tsx  Dock.tsx  Window.tsx
                   windowStore.ts  registry.ts  session.ts
  src/shared/      api.ts  sse.ts  ui/(Button Badge Tabs Table Field)  gantt/(scale.ts Bars.tsx Header.tsx)
  src/programs/    chat/ questionnaire/ schedule/ conditions/ approvals/ workflow/ explorer/ settings/
                   — 각 index.ts(매니페스트) + 화면 파일 + *.test.tsx
```

프로그램 매니페스트(`src/os/registry.ts`):
```ts
export interface ProgramManifest {
  id: string; name: string; group: 'system' | 'work'; adminOnly?: boolean;
  defaultSize: { w: number; h: number }; menus?: { label: string; items: string[] }[];
  component: React.LazyExoticComponent<React.ComponentType<{ windowId: string; params?: Record<string, string> }>>;
}
```

---

### Task 0: 저장소 도구와 검사 [opus]

**Files:** Create `docker-compose.yml`, `backend/pyproject.toml`, `backend/Dockerfile`, `backend/app/main.py`, `backend/app/config.py`, `backend/tests/test_health.py`, `frontend/package.json`, `frontend/Dockerfile`, `frontend/vite.config.ts`, `frontend/eslint.config.js`, `frontend/src/main.tsx`, `scripts/check.sh`, `scripts/check_lines.py`, `scripts/check_secrets.sh`, `scripts/tests/test_check_lines.py`

**Interfaces — Produces:**
- `GET /api/health` → `{"status":"ok"}`
- `app.config.Settings`: `admin_id`, `admin_password`, `secret_key`, `data_dir` (환경 변수 `CHRONOS_ADMIN_ID`, `CHRONOS_ADMIN_PASSWORD`, `CHRONOS_SECRET_KEY`, `CHRONOS_DATA_DIR` 기본 `./data`)
- `scripts/check_lines.py <root>`: 상한 초과 파일이 있으면 종료 코드 1, 권장 초과는 경고만. 규칙: `frontend/src/**/*.{ts,tsx}` 300/600, `backend/app/**/*.py` 400/800. `*.test.*`, `tests/`, `*.gen.*`, `app/domains/` 제외.
- `scripts/check_secrets.sh`: 추적 파일에서 `sk-[A-Za-z0-9]{20,}`, `api[_-]?key\s*[:=]\s*['"][A-Za-z0-9]{16,}`, `.env`(`.env.example` 제외) 발견 시 종료 코드 1
- `scripts/check.sh`: 비밀 검사 → 줄 수 검사 → `ruff check` → `pytest -q` → `eslint` → `vitest run` → `vite build` (Docker로)

- [ ] **Step 1: 실패하는 시험**
```python
# backend/tests/test_health.py
def test_health(client):            # client = TestClient(app) fixture in tests/conftest.py
    assert client.get("/api/health").json() == {"status": "ok"}

# scripts/tests/test_check_lines.py
def test_over_hard_limit_fails(tmp_path):
    f = tmp_path / "backend/app/x.py"; f.parent.mkdir(parents=True); f.write_text("a=1\n" * 801)
    assert run(tmp_path).returncode == 1
def test_over_soft_limit_warns_only(tmp_path):
    f = tmp_path / "backend/app/x.py"; f.parent.mkdir(parents=True); f.write_text("a=1\n" * 401)
    r = run(tmp_path); assert r.returncode == 0 and "x.py" in r.stdout
def test_tests_are_excluded(tmp_path):
    f = tmp_path / "backend/tests/t.py"; f.parent.mkdir(parents=True); f.write_text("a=1\n" * 2000)
    assert run(tmp_path).returncode == 0
```
- [ ] **Step 2:** `docker compose run --rm backend pytest -q` → 실패 확인
- [ ] **Step 3:** 구현. eslint에 `max-lines: [warn, 300]`, `max-lines-per-function: [warn, 50]`, 프로그램 간 import 금지 규칙(`no-restricted-imports` 패턴 `../*/`를 `src/programs/*`에서) 설정
- [ ] **Step 4:** `bash scripts/check.sh` → 전부 통과
- [ ] **Step 5:** 커밋 `chore: 저장소 도구와 검사`

---

### Task 1: 저장 기반과 로그인 [opus]

**Files:** Create `backend/app/db.py`, `backend/app/store/tables.py`, `backend/app/security/{passwords,tokens,deps}.py`, `backend/app/programs/auth/{router,service,schemas}.py`, `backend/tests/programs/test_auth.py`

**Interfaces — Produces:**
- 표 `users(id, login_id unique, name, role 'admin'|'user', password_hash, created_at)`
- `app.db.get_session()` (FastAPI 의존성), `app.db.init_db()` (표 만들기 + 첫 관리자 만들기 — `Settings.admin_id/admin_password`, 이미 있으면 건드리지 않음)
- `POST /api/auth/login {login_id, password}` → `200 {token, user:{id,name,role}}` / 틀리면 `401 {"code":"bad_credentials","message":"아이디 또는 비밀번호가 맞지 않습니다."}`
- `GET /api/auth/me` → `user`
- `GET/POST /api/auth/users`, `PATCH /api/auth/users/{id}` — 관리자만(`403 {"code":"admin_only"}`)
- `app.security.deps.current_user`, `require_admin` 의존성. 토큰은 서명된 Bearer 토큰(만료 12시간), `Settings.secret_key`로 서명
- 오류 응답 형식(전 API 공통): `{"code": str, "message": str(한국어), "detail": any|null}`

- [ ] **Step 1: 실패하는 시험**
```python
def test_first_admin_can_login(client):
    r = client.post("/api/auth/login", json={"login_id": "admin", "password": "test-pass"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
def test_wrong_password_401(client):
    r = client.post("/api/auth/login", json={"login_id": "admin", "password": "x"})
    assert r.status_code == 401 and r.json()["code"] == "bad_credentials"
def test_user_cannot_list_users(client, user_token):
    assert client.get("/api/auth/users", headers=auth(user_token)).status_code == 403
def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
def test_password_is_not_stored_plain(session):
    assert "test-pass" not in session.get(User, 1).password_hash
```
- [ ] **Step 2:** 실패 확인  - [ ] **Step 3:** 구현  - [ ] **Step 4:** 통과 확인  - [ ] **Step 5:** 커밋 `feat: 로그인과 계정 2등급`

---

### Task 2: 일정 모델·달력·경로 계산 [fable]

**Files:** Create `backend/app/core/{model,calendar,cpm}.py`, `backend/tests/core/{test_calendar,test_cpm}.py`

**Interfaces — Produces:**
```python
# model.py — 전부 frozen dataclass
RelType = Literal["FS", "SS", "FF", "SF"]
Constraint(type: Literal["SNET", "FNLT"], date: date)     # 이 날 이후 시작 / 늦어도 이 날 종료
Activity(id: str, name: str, kind: Literal["task", "start_ms", "finish_ms"], wbs: str,
         od: int, rd: int | None = None, progress: float = 0.0,
         actual_start: date | None = None, actual_finish: date | None = None,
         constraint: Constraint | None = None, resources: tuple[str, ...] = (), tags: tuple[str, ...] = ())
Relation(pred: str, succ: str, type: RelType = "FS", lag: int = 0)
WbsNode(code: str, name: str, parent: str | None)
Resource(id: str, name: str, unit: str, capacity: int)
BlockedPeriod(start_md: tuple[int, int], end_md: tuple[int, int], tag: str)   # 예: (12,1)~(2,28), "타설"
CalendarSpec(days_per_week: Literal[5, 6, 7], holidays: tuple[date, ...] = (), blocked: tuple[BlockedPeriod, ...] = ())
Schedule(start: date, calendar: CalendarSpec, wbs: tuple[WbsNode, ...], activities: tuple[Activity, ...],
         relations: tuple[Relation, ...], resources: tuple[Resource, ...] = (), data_date: date | None = None)

# calendar.py
class WorkCalendar:
    def __init__(self, spec: CalendarSpec): ...
    def is_workday(self, d: date, tags: tuple[str, ...] = ()) -> bool
    def next_workday(self, d: date, tags=()) -> date            # d가 일하는 날이면 d
    def add_workdays(self, start: date, n: int, tags=()) -> date  # n일짜리 작업의 종료일(포함). n=0이면 start
    def workdays_between(self, a: date, b: date) -> int         # a 다음 날부터 b까지 일하는 날 수 (b<a면 음수)
KOREA_HOLIDAYS_2027: tuple[date, ...]   # 2027년 한국 공휴일(대체 공휴일 포함) — 자료 상수

# cpm.py
CpmRow(es: date, ef: date, ls: date, lf: date, tf: int, ff: int, critical: bool)
CpmResult(rows: dict[str, CpmRow], finish: date, critical_path: tuple[str, ...])
class ScheduleError(Exception): code: Literal["cycle", "dangling_ref", "bad_duration", "empty"]; detail: dict
def compute(schedule: Schedule) -> CpmResult
```
규칙: 기간은 근무일. `ES`는 시작하는 날, `EF`는 끝나는 날(포함). `FS lag 0`이면 후행의 ES = 선행 EF의 다음 근무일. 마일스톤(`od=0`)은 ES=EF. `tf=0`이면 `critical`. 6일 근무는 일요일만 쉼. Actual이 있는 액티비티는 그 날짜를 고정으로 쓰고(`actual_finish`가 있으면 EF=actual_finish, 없고 `actual_start`만 있으면 ES=actual_start, 남은 기간 `rd`), 후행은 거기서 이어 계산한다. `FNLT`는 LF를 그 날짜로 묶어 TF가 음수가 될 수 있다.

- [ ] **Step 1: 실패하는 시험** (2027-03-01은 월요일)
```python
CAL5 = CalendarSpec(days_per_week=5)
def act(i, od, **k): return Activity(id=i, name=i, kind="task", wbs="1", od=od, **k)
def sched(acts, rels, cal=CAL5, start=date(2027, 3, 1)):
    return Schedule(start=start, calendar=cal, wbs=(WbsNode("1", "w", None),), activities=tuple(acts), relations=tuple(rels))

def test_fs_chain():
    r = compute(sched([act("A", 3), act("B", 2)], [Relation("A", "B")]))
    assert (r.rows["A"].es, r.rows["A"].ef) == (date(2027, 3, 1), date(2027, 3, 3))
    assert (r.rows["B"].es, r.rows["B"].ef) == (date(2027, 3, 4), date(2027, 3, 5))
    assert r.finish == date(2027, 3, 5) and r.critical_path == ("A", "B")
def test_weekend_is_skipped():
    r = compute(sched([act("A", 5), act("B", 1)], [Relation("A", "B")]))
    assert r.rows["B"].es == date(2027, 3, 8)
def test_float_on_parallel_branch():
    r = compute(sched([act("A", 5), act("B", 2), act("C", 1)], [Relation("A", "C"), Relation("B", "C")]))
    assert r.rows["B"].tf == 3 and not r.rows["B"].critical and r.rows["A"].critical
def test_ss_with_lag():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "SS", 2)]))
    assert r.rows["B"].es == date(2027, 3, 3)
def test_ff_and_sf():
    r = compute(sched([act("A", 5), act("B", 2)], [Relation("A", "B", "FF", 0)]))
    assert r.rows["B"].ef == date(2027, 3, 5)
def test_milestone_zero_duration():
    r = compute(sched([act("A", 3), Activity("M", "M", "finish_ms", "1", 0)], [Relation("A", "M")]))
    assert r.rows["M"].es == r.rows["M"].ef == date(2027, 3, 3)
def test_start_on_holiday_moves_to_next_workday():          # Review Focus 5
    cal = CalendarSpec(5, holidays=(date(2027, 3, 1),))
    assert compute(sched([act("A", 1)], [], cal)).rows["A"].es == date(2027, 3, 2)
def test_blocked_period_applies_only_to_tagged():
    cal = CalendarSpec(7, blocked=(BlockedPeriod((3, 1), (3, 7), "타설"),))
    r = compute(sched([act("A", 1, tags=("타설",)), act("B", 1)], [], cal))
    assert r.rows["A"].es == date(2027, 3, 8) and r.rows["B"].es == date(2027, 3, 1)
def test_fnlt_gives_negative_float():
    a = act("A", 10, constraint=Constraint("FNLT", date(2027, 3, 5)))
    assert compute(sched([a], [])).rows["A"].tf == -5
def test_actual_finish_later_than_plan_pushes_successor():
    a = act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 5), progress=1.0)
    assert compute(sched([a, act("B", 1)], [Relation("A", "B")])).rows["B"].es == date(2027, 3, 8)
def test_actual_earlier_than_plan_is_accepted():             # Review Focus 5
    a = act("A", 3, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 2), progress=1.0)
    assert compute(sched([a, act("B", 1)], [Relation("A", "B")])).rows["B"].es == date(2027, 3, 3)
@pytest.mark.parametrize("rels,code", [([Relation("A", "B"), Relation("B", "A")], "cycle"), ([Relation("A", "Z")], "dangling_ref")])
def test_bad_graph_raises(rels, code):
    with pytest.raises(ScheduleError) as e: compute(sched([act("A", 1), act("B", 1)], rels))
    assert e.value.code == code
def test_negative_duration_raises():
    with pytest.raises(ScheduleError) as e: compute(sched([act("A", -1)], []))
    assert e.value.code == "bad_duration"
def test_korea_holidays_2027_include_fixed_days():
    assert {date(2027, 1, 1), date(2027, 3, 1), date(2027, 5, 5), date(2027, 8, 15), date(2027, 10, 3), date(2027, 10, 9), date(2027, 12, 25)} <= set(KOREA_HOLIDAYS_2027)
```
- [ ] **Step 2:** 실패 확인  - [ ] **Step 3:** 구현 — 위상 정렬 한 번, 앞으로·거꾸로 두 번 훑기. `core`는 표준 라이브러리만 import  - [ ] **Step 4:** 통과 확인  - [ ] **Step 5:** 커밋 `feat: 일정 모델·달력·경로 계산`

---

### Task 3: 주요 자원 겹침과 맞춤 [fable]

**Files:** Create `backend/app/core/resources.py`, `backend/tests/core/test_resources.py`

**Interfaces — Consumes:** Task 2의 `Schedule`, `compute`, `CpmResult`, `WorkCalendar`
**Produces:**
```python
Peak(resource_id: str, when: date, need: int, capacity: int)
LevelResult(dates: dict[str, tuple[date, date]], finish: date, peaks: dict[str, Peak],
            overloads: tuple[Peak, ...], shifted: tuple[str, ...])
def level(schedule: Schedule, cpm: CpmResult, *, shift: bool = True) -> LevelResult
```
규칙: 액티비티 하나는 `resources`에 적힌 자원을 각각 1 단위 쓴다. `shift=True`면 용량을 넘는 날이 없도록 뒤로 민다 — 우선순위는 ES가 이른 것, 같으면 TF가 작은 것, 같으면 id 순. 밀린 액티비티의 후행은 선후 관계를 지키며 같이 밀린다. `shift=False`면 밀지 않고 `overloads`만 채운다. `peaks`는 자원마다 필요량이 가장 큰 날(동률이면 이른 날). 용량 0 이하인 자원을 쓰는 액티비티가 있으면 밀 수 없으므로 `overloads`에 넣고 날짜는 그대로 둔다.

- [ ] **Step 1: 실패하는 시험**
```python
R = Resource("crane", "타워크레인", "대", 1)
def test_two_tasks_one_crane_are_serialized():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",))], []), resources=(R,))
    r = level(s, compute(s))
    assert r.dates["A"] == (date(2027, 3, 1), date(2027, 3, 3)) and r.dates["B"][0] == date(2027, 3, 4)
    assert r.shifted == ("B",) and r.overloads == ()
def test_capacity_two_keeps_them_parallel():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",))], []), resources=(replace(R, capacity=2),))
    assert level(s, compute(s)).shifted == ()
def test_check_only_reports_overload_without_moving():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",))], []), resources=(R,))
    r = level(s, compute(s), shift=False)
    assert r.dates["B"][0] == date(2027, 3, 1) and r.overloads[0].need == 2 and r.peaks["crane"].need == 2
def test_shift_pushes_successor():
    s = replace(sched([act("A", 3, resources=("crane",)), act("B", 2, resources=("crane",)), act("C", 1)], [Relation("B", "C")]), resources=(R,))
    assert level(s, compute(s)).dates["C"][0] == date(2027, 3, 8)
def test_zero_capacity_does_not_loop():                      # Review Focus 5
    s = replace(sched([act("A", 1, resources=("crane",))], []), resources=(replace(R, capacity=0),))
    r = level(s, compute(s)); assert r.overloads and r.dates["A"][0] == date(2027, 3, 1)
def test_unknown_resource_id_is_ignored():
    s = sched([act("A", 1, resources=("ghost",))], []); assert level(s, compute(s)).overloads == ()
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 주요 자원 겹침과 맞춤`

---

### Task 4: 일정 저장·버전·변경 이력 [opus]

**Files:** Create `backend/app/store/{schedules,versions}.py`, Modify `backend/app/store/tables.py`, Create `backend/app/programs/schedule/{router,service,schemas}.py`, `backend/tests/store/test_versions.py`, `backend/tests/programs/test_schedule_api.py`

**Interfaces — Consumes:** Task 1 `get_session`, `current_user`; Task 2·3 계산
**Produces:**
- 표 `schedules(id, name, domain, level 'L1'..'L5', current_version, created_by, created_at)`, `schedule_versions(schedule_id, n, snapshot_json, conditions_json, note, by_kind 'user'|'agent', by_name, is_plan bool, created_at)`, `change_log(id, schedule_id, version_n, by_kind, by_name, summary, changes_json, created_at)`
- `store.schedules.load(session, schedule_id, version: int | None = None) -> tuple[Schedule, list[Condition-dict], int]`
- `store.versions.save_new_version(session, schedule_id, schedule: Schedule, conditions: list[dict], *, by_kind, by_name, note, changes: list[dict], base_version: int) -> int` — `base_version != current_version`이면 `VersionConflict(current: int)` 발생
- `store.versions.restore(session, schedule_id, n, *, by_name) -> int` — n번 내용을 새 버전으로 만든다(이력은 지우지 않음)
- `to_json(schedule) -> dict`, `from_json(d) -> Schedule` (왕복 동일)
- 계산 포함 응답 `ScheduleView`: `{id, name, domain, level, version, data_date, finish, plan_finish, wbs[], activities[{…Activity, plan_start, plan_finish, tf, ff, critical, status, weight}], relations[], resources[], summary{critical_count, negative_float_count, warning_count}}`
  - `plan_start/plan_finish`: `is_plan` 버전의 계산값. `status`: `done`(actual_finish 있음) / `late +n` / `early -n` / `on_plan` — Plan과 Actual(없으면 현재 계산값)의 근무일 차이
  - `weight`: 기간 비례(`od / Σod`)
- API: `GET /api/schedules`, `GET /api/schedules/{id}`, `PATCH /api/schedules/{id}/activities/{aid}`, `POST /api/schedules/{id}/activities`, `DELETE …/activities/{aid}`, `PUT /api/schedules/{id}/activities/{aid}/predecessors` (본문 `[{pred,type,lag}]`), `GET /api/schedules/{id}/versions`, `POST /api/schedules/{id}/versions/{n}/restore`. 사용자가 직접 고친 것은 바로 새 버전(`by_kind='user'`). 요청 본문에 `base_version` 필수.
- 고쳐서 계산이 깨지면(`ScheduleError`) `422 {"code":"schedule_invalid","message":"선후 관계가 고리를 이룹니다." …}` 저장하지 않음

- [ ] **Step 1: 실패하는 시험**
```python
def test_json_roundtrip(sample_schedule): assert from_json(to_json(sample_schedule)) == sample_schedule
def test_save_bumps_version_and_logs(session, sid, sample_schedule):
    n = save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="손장호", note="x", changes=[{"id": "A", "field": "od", "from": 3, "to": 4}], base_version=1)
    assert n == 2 and session.query(ChangeLog).filter_by(schedule_id=sid).count() == 1
def test_stale_base_version_conflicts(session, sid, sample_schedule):
    save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="a", note="", changes=[], base_version=1)
    with pytest.raises(VersionConflict) as e:
        save_new_version(session, sid, sample_schedule, [], by_kind="agent", by_name="에이전트", note="", changes=[], base_version=1)
    assert e.value.current == 2
def test_restore_creates_new_version_keeping_history(session, sid):
    assert restore(session, sid, 1, by_name="손장호") == 3 and len(list_versions(session, sid)) == 3
def test_patch_duration_recomputes(client, admin, sid):
    r = client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 5, "base_version": 1}, headers=admin)
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["finish"] > "2027-03-05"
def test_cycle_edit_is_rejected_and_not_saved(client, admin, sid):
    r = client.put(f"/api/schedules/{sid}/activities/A/predecessors", json={"items": [{"pred": "B", "type": "FS", "lag": 0}], "base_version": 1}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "schedule_invalid"
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 1
def test_status_late_from_actual(client, admin, sid):
    client.patch(f"/api/schedules/{sid}/activities/A", json={"actual_start": "2027-03-01", "actual_finish": "2027-03-05", "progress": 1, "base_version": 1}, headers=admin)
    a = next(x for x in client.get(f"/api/schedules/{sid}", headers=admin).json()["activities"] if x["id"] == "A")
    assert a["status"] == "done" and a["plan_finish"] == "2027-03-03"
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 일정 저장·버전·변경 이력`

---

### Task 5: LLM 연결 저장과 연결 테스트 [opus]

**Files:** Create `backend/app/security/crypto.py`, `backend/app/llm/{connections,errors}.py`, `backend/app/programs/llm_settings/{router,service,schemas}.py`, `backend/tests/programs/test_llm_settings.py`

**Interfaces — Produces:**
- 표 `llm_connections(id, name, provider 'liner'|'openai_compatible', base_url, secret_ciphertext, secret_last4, is_default, status 'ok'|'failed'|'unknown', model_count, checked_at, latency_ms)`, `llm_assignments(purpose 'light'|'normal'|'hard'|'longdoc' pk, connection_id, model, routing_strategy 'cost'|'balanced'|'quality'|null)`
- `crypto.encrypt(plain: str) -> str`, `crypto.decrypt(token: str) -> str` (Fernet, 키는 `Settings.secret_key`에서 유도)
- `llm.errors.explain(exc) -> LlmError(code, message)` — 코드와 문구: `bad_key` "API 키가 맞지 않습니다." / `bad_url` "주소에 연결할 수 없습니다." / `timeout` "응답이 너무 늦습니다." / `rate_limited` "호출 한도를 넘었습니다. 잠시 뒤 다시 해 주세요." / `unknown` "연결에 실패했습니다."
- `llm.connections.probe(base_url, secret) -> ProbeResult(ok, latency_ms, models: list[str], error: LlmError | None)` — `GET {base_url}/models`
- API(전부 관리자만, `status`만 누구나): `GET /api/llm/connections`(키는 `secret_last4`만) · `POST /api/llm/connections/test {provider, base_url, secret}` · `POST /api/llm/connections {name, provider, base_url, secret}` · `PATCH /api/llm/connections/{id} {name?, base_url?, secret?}` — `base_url`의 호스트가 바뀌는데 `secret`이 없으면 `422 {"code":"secret_required"}` · `POST /api/llm/connections/{id}/test` · `DELETE …/{id}` · `GET/PUT /api/llm/assignments` · `GET /api/llm/status → {ready: bool, default_connection: str|null}`
- 기본값: provider `liner`의 `base_url` 기본 `https://platform.liner.com/api/v1`. 첫 연결은 `is_default=True`. 배정 기본: light→`liner-claude-router`/cost, normal→/balanced, hard→/quality, longdoc→`liner-mark`/null (Checkpoint A에서 실제 키로 확인한 뒤 고칠 수 있음)

- [ ] **Step 1: 실패하는 시험** (`probe`는 `httpx.MockTransport`로 대체)
```python
def test_secret_is_encrypted_and_masked(client, admin, session, fake_probe_ok):
    r = client.post("/api/llm/connections", json={"name": "Liner 기본", "provider": "liner", "base_url": LINER, "secret": "abcd1234efgh5678"}, headers=admin)
    body = r.json(); assert body["secret_last4"] == "5678" and "secret" not in body and "abcd1234" not in r.text
    row = session.query(LlmConnection).one(); assert "abcd1234" not in row.secret_ciphertext and decrypt(row.secret_ciphertext) == "abcd1234efgh5678"
def test_test_endpoint_returns_models(client, admin, fake_probe_ok):
    r = client.post("/api/llm/connections/test", json={"provider": "liner", "base_url": LINER, "secret": "k"}, headers=admin)
    assert r.json()["ok"] is True and "liner-mark" in r.json()["models"]
@pytest.mark.parametrize("status,code", [(401, "bad_key"), (429, "rate_limited")])
def test_error_is_explained(client, admin, fake_probe_status, status, code):
    assert client.post("/api/llm/connections/test", json={"provider": "liner", "base_url": LINER, "secret": "k"}, headers=admin).json()["error"]["code"] == code
def test_host_change_requires_secret(client, admin, conn_id):
    r = client.patch(f"/api/llm/connections/{conn_id}", json={"base_url": "https://other.example/v1"}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "secret_required"
def test_user_role_forbidden_but_status_allowed(client, user):
    assert client.get("/api/llm/connections", headers=user).status_code == 403
    assert client.get("/api/llm/status", headers=user).json() == {"ready": False, "default_connection": None}
def test_key_never_in_logs(client, admin, caplog, fake_probe_ok):
    client.post("/api/llm/connections", json={"name": "n", "provider": "liner", "base_url": LINER, "secret": "abcd1234efgh5678"}, headers=admin)
    assert "abcd1234efgh5678" not in caplog.text
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: LLM 연결 저장과 연결 테스트`

---

### Task 6: LLM 호출과 도구 등록부 [fable]

**Files:** Create `backend/app/llm/client.py`, `backend/app/tools/{registry,context}.py`, `backend/app/tools/calc/run_cpm.py`, `backend/app/tools/data/read_schedule.py`, `backend/app/tools/ui/open_window.py`, `backend/tests/llm/test_client.py`, `backend/tests/tools/test_registry.py`

**Interfaces — Consumes:** Task 5 연결·배정·`explain`
**Produces:**
```python
Purpose = Literal["light", "normal", "hard", "longdoc"]
Usage(input_tokens: int, output_tokens: int, cost: float | None)
ToolCall(id: str, name: str, arguments: dict)
LlmReply(text: str, tool_calls: list[ToolCall], model: str, usage: Usage)
class LlmNotReady(Exception)                       # 연결이 없음
class LlmFailed(Exception): error: LlmError
class LlmClient:
    def __init__(self, session): ...
    async def chat(self, purpose: Purpose, messages: list[dict], *, tools: list[dict] | None = None,
                   json_schema: dict | None = None, timeout_s: float = 60) -> LlmReply
# 실제 모델 이름은 응답의 model, 비용은 usage.cost 에서 읽는다. routing_strategy 는 요청 본문 extra_body 로 보낸다.
# 호출마다 표 llm_calls(id, session_id, purpose, model, input_tokens, output_tokens, cost, latency_ms, ok, created_at)에 기록.

# tools/registry.py
ToolSpec(name: str, description: str, input_model: type[BaseModel], output_model: type[BaseModel],
         program: str | None, mutates: bool, enabled: bool)
def tool(name, description, *, program=None, mutates=False) -> decorator   # 함수 서명 (args: InputModel, ctx: ToolContext) -> OutputModel
def list_tools(*, enabled_only=True) -> list[ToolSpec]
def as_llm_tools() -> list[dict]                   # OpenAI tools 형식
async def call(name: str, arguments: dict, ctx: ToolContext) -> ToolResult
ToolResult(ok: bool, output: dict | None, error: str | None, ms: int)
ToolContext(session, user, schedule_id: int | None, emit: Callable[[AgentEvent], None])
```
`call`은 입력을 `input_model`로 검증하고, 틀리면 실행하지 않고 `ToolResult(ok=False, error="입력 형식 오류: …")`를 돌려준다. 없는 도구·꺼진 도구도 같은 방식. 도구 안의 예외는 `ok=False`로 바뀐다.
첫 도구 셋: `schedule.read`(일정 요약: 액티비티 수·준공·크리티컬 목록·조건 수) · `calc.cpm`(현재 일정 계산 결과) · `ui.open_window {program, params}`(→ `AgentEvent("open_window")` 내보냄)

- [ ] **Step 1: 실패하는 시험** (LLM은 `httpx.MockTransport`)
```python
async def test_chat_uses_assignment_and_records_cost(llm, session, fake_liner):
    r = await llm.chat("hard", [{"role": "user", "content": "hi"}])
    assert fake_liner.last_body["model"] == "liner-claude-router" and fake_liner.last_body["routing_strategy"] == "quality"
    assert r.model == "claude-opus-5.5" and r.usage.cost == 0.04 and session.query(LlmCall).one().cost == 0.04
async def test_no_connection_raises_not_ready(llm_empty):
    with pytest.raises(LlmNotReady): await llm_empty.chat("light", [])
async def test_timeout_becomes_llm_failed(llm, fake_liner_timeout):            # Review Focus 2
    with pytest.raises(LlmFailed) as e: await llm.chat("light", [], timeout_s=0.01)
    assert e.value.error.code == "timeout"
async def test_bad_args_are_rejected_before_running(ctx, spy_tool):
    r = await call("spy", {"n": "not-int"}, ctx); assert r.ok is False and "입력 형식" in r.error and spy_tool.calls == 0
async def test_unknown_tool(ctx): assert (await call("nope", {}, ctx)).ok is False
async def test_tool_exception_is_contained(ctx, boom_tool): assert (await call("boom", {}, ctx)).ok is False
def test_as_llm_tools_shape(): assert all(t["type"] == "function" and "parameters" in t["function"] for t in as_llm_tools())
async def test_open_window_emits_event(ctx, events):
    await call("ui.open_window", {"program": "schedule", "params": {"tab": "gantt"}}, ctx)
    assert events[-1].type == "open_window" and events[-1].data["program"] == "schedule"
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: LLM 호출과 도구 등록부`

---

### Task 7: 하네스 — 조건 종류·점검·조립 [fable]

**Files:** Create `backend/app/harness/{conditions,checks,assemble}.py`, `backend/app/tools/check/run_harness.py`, `backend/tests/harness/{test_checks,test_assemble}.py`

**Interfaces — Consumes:** Task 2·3
**Produces:**
```python
Layer = Literal["base", "domain", "mine", "input"]
Kind = Literal["no_cycle", "no_dangling", "calendar", "finish_by", "start_after", "milestone_by",
               "resource_cap", "blocked_period", "min_gap", "duration_per_unit", "max_duration", "text_only"]
Condition(id: str, layer: Layer, kind: Kind, params: dict, text: str, source: str, enabled: bool = True)
#  source: "기본 규칙" | "분야 규칙" | "내 규칙" | "프롬프트" | "질문지" | "문서"
#  checkable = kind != "text_only"
Violation(condition_id: str, message: str, activity_ids: tuple[str, ...], amount: int | None)
CheckReport(passed: list[str], violations: list[Violation], uncheckable: list[str])
def check(schedule: Schedule, conditions: list[Condition]) -> CheckReport   # 안에서 compute·level(shift=False) 호출
def assemble(domain_rules: list[Condition], my_rules: list[Condition], inputs: list[Condition]) -> list[Condition]
def apply_to_schedule(schedule: Schedule, conditions: list[Condition]) -> Schedule
#  finish_by → 종료 마일스톤의 FNLT, start_after → Schedule.start, resource_cap → Resource.capacity,
#  calendar → CalendarSpec, blocked_period → CalendarSpec.blocked 로 옮긴다
```
`params` 형식: `finish_by {date}` · `start_after {date}` · `milestone_by {activity_id, date}` · `resource_cap {resource_id, capacity}` · `calendar {days_per_week, holidays: "KR"|[]}` · `blocked_period {start_md, end_md, tag}` · `min_gap {after_tag, days}`(예: 타설 뒤 양생 7일 — `after_tag` 액티비티 종료와 그 후행 시작 사이 근무일 ≥ days) · `max_duration {days}` · `text_only {}`.
조립 규칙: `base`는 항상 들어가고 끌 수 없다. 같은 `kind`+같은 대상(`resource_id`/`activity_id`/`tag`)이 여러 겹에 있으면 뒤 겹(base<domain<mine<input)이 이기고, 진 조건은 `enabled=False`로 남긴다(화면에 "~보다 우선"으로 보임).
도구 `harness.check` — 현재 일정에 대해 `CheckReport`를 돌려준다.

- [ ] **Step 1: 실패하는 시험**
```python
def test_finish_by_violation_reports_days_over(s_finish_0305):
    r = check(s_finish_0305, [Condition("c1", "input", "finish_by", {"date": "2027-03-04"}, "준공 03.04 이전", "프롬프트")])
    assert r.violations[0].condition_id == "c1" and r.violations[0].amount == 1
def test_resource_cap_violation_lists_activities(two_crane_tasks):
    r = check(two_crane_tasks, [Condition("c2", "input", "resource_cap", {"resource_id": "crane", "capacity": 1}, "크레인 1대", "프롬프트")])
    assert set(r.violations[0].activity_ids) == {"A", "B"}
def test_min_gap_curing(pour_then_next_day):
    r = check(pour_then_next_day, [Condition("c3", "domain", "min_gap", {"after_tag": "타설", "days": 7}, "양생 7일", "분야 규칙")])
    assert r.violations and r.violations[0].amount == 6
def test_text_only_is_never_passed(s_finish_0305):
    r = check(s_finish_0305, [Condition("c4", "input", "text_only", {}, "안전 우선", "프롬프트")])
    assert r.uncheckable == ["c4"] and "c4" not in r.passed
def test_cycle_is_reported_not_raised(cyclic):
    assert check(cyclic, BASE_RULES).violations[0].condition_id == "base.no_cycle"
def test_input_overrides_domain_same_target():
    d = Condition("d1", "domain", "blocked_period", {"start_md": [12, 15], "end_md": [2, 15], "tag": "타설"}, "", "분야 규칙")
    i = Condition("i1", "input", "blocked_period", {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"}, "", "프롬프트")
    out = {c.id: c.enabled for c in assemble([d], [], [i])}; assert out == {**{b.id: True for b in BASE_RULES}, "d1": False, "i1": True}
def test_base_cannot_be_disabled():
    hacked = Condition("base.no_cycle", "input", "no_cycle", {}, "", "프롬프트", enabled=False)
    assert next(c for c in assemble([], [], [hacked]) if c.id == "base.no_cycle" and c.layer == "base").enabled
def test_apply_sets_capacity_and_calendar(two_crane_tasks):
    s = apply_to_schedule(two_crane_tasks, [Condition("c", "input", "resource_cap", {"resource_id": "crane", "capacity": 2}, "", "질문지")])
    assert s.resources[0].capacity == 2
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 하네스 조건 점검과 조립`

---

### Task 8: 건설 분야 묶음과 질문지 [sonnet 자료 + opus 코드]

**Files:** Create `backend/app/domains/loader.py`, `backend/app/domains/construction/pack.yaml`, `backend/app/tools/ask/make_questionnaire.py`, `backend/app/programs/questionnaire/{router,service,schemas}.py`, `backend/tests/domains/test_loader.py`, `backend/tests/programs/test_questionnaire.py`

**Interfaces — Consumes:** Task 7 `Condition`
**Produces:**
- `pack.yaml` 구조: `id: construction` · `name: 건설` · `terms{}` · `default_calendar{days_per_week: 6, holidays: KR}` · `rules[]`(Condition 형식 — 양생 7일 `min_gap`, 골조 2개 층 위부터 설비 배관은 `text_only`) · `info_items[]`: `{id, group '범위'|'날짜'|'달력·방식'|'자원·외부', label, question, required: {L1,L2,L3,L4,L5 각 'must'|'optional'|'skip'}, options[]: {value, label, hint?, recommended?}, allow_free: true, follow_ups[]: {when_value, item_id}, to_condition?: {kind, params_template}}` · `wbs_template[]`(기초/골조/외장·설비/마감 3단계) · `key_resources[]`: `{id, name, unit, tags[]}`(타워크레인·철근공·타설반) · `activity_types[]`: `{tag, name_keywords[], resources[]}`
  - `info_items`는 설계 11-3의 공통 19개 + 건설 추가 8개를 전부 담는다. `required` 값은 설계 표 그대로.
- `domains.loader.load(domain_id) -> DomainPack`, `DomainPack.must_items(level) -> list[InfoItem]`
- 표 `questionnaires(id, session_id, schedule_draft_id, domain, level, items_json, answers_json, status 'open'|'submitted', created_at)`
- 도구 `ask.questionnaire {purpose, items: [item_id…], prefilled: [{item_id, value, source}]}` → 질문지 만들고 `AgentEvent("questionnaire", {id})` 내보냄. 물을 것이 2개 이하면 질문지를 만들지 않고 `AgentEvent("card", {kind:"mini_questions", …})`
- API: `GET /api/questionnaires/{id}` → `{id, title, level, progress:{must_total, must_filled, optional_total, optional_filled}, groups:[{name, filled, total, items:[{item_id, label, question, required, options, allow_free, value, source, reason?}]}]}` · `PATCH /api/questionnaires/{id}/answers {item_id, value | "__auto__"}` — 답에 따라 `follow_ups` 항목이 생기고 사라진 결과를 돌려줌. `"__auto__"`는 `required='optional'`에만 허용(`422 must_item`) · `POST /api/questionnaires/{id}/submit` — `must`가 비어 있으면 `422 {"code":"must_missing","detail":{"items":[…]}}`

- [ ] **Step 1: 실패하는 시험**
```python
def test_pack_has_all_common_items(): assert len([i for i in load("construction").info_items]) >= 27
def test_l1_must_items_match_spec(): assert {i.id for i in load("construction").must_items("L1")} >= {"purpose", "scope", "start_date", "finish_date"}
def test_l3_requires_key_resources_but_l2_skips(): p = load("construction"); assert "key_resources" in ids(p.must_items("L3")) and "key_resources" not in ids(p.must_items("L2"))
def test_follow_up_appears_and_disappears(client, admin, qid):
    r = client.patch(f"/api/questionnaires/{qid}/answers", json={"item_id": "basement", "value": "b1"}, headers=admin)
    assert "retaining_wall" in item_ids(r.json())
    r = client.patch(f"/api/questionnaires/{qid}/answers", json={"item_id": "basement", "value": "none"}, headers=admin)
    assert "retaining_wall" not in item_ids(r.json())
def test_auto_rejected_on_must(client, admin, qid):
    assert client.patch(f"/api/questionnaires/{qid}/answers", json={"item_id": "work_week", "value": "__auto__"}, headers=admin).status_code == 422
def test_submit_blocked_until_must_filled(client, admin, qid):
    r = client.post(f"/api/questionnaires/{qid}/submit", headers=admin); assert r.status_code == 422 and r.json()["code"] == "must_missing"
def test_prefilled_keeps_source(client, admin, qid_prefilled):
    assert item(client.get(f"/api/questionnaires/{qid_prefilled}", headers=admin).json(), "finish_date")["source"] == "프롬프트"
async def test_two_or_fewer_questions_become_card(ctx, events):
    await call("ask.questionnaire", {"purpose": "generate", "items": ["work_week"], "prefilled": []}, ctx); assert events[-1].type == "card"
```
- [ ] **Step 2~5:** 실패 확인 → 구현(자료 채우기는 sonnet, 코드는 opus) → 통과 확인 → 커밋 `feat: 건설 분야 묶음과 질문지`

---

### Task 9: 일정 생성 — 조건 뽑기·WBS·스케줄·생성 루프 [fable]

**Files:** Create `backend/app/tools/generate/{extract_conditions,make_wbs,make_schedule}.py`, `backend/app/agent/generation.py`, `backend/app/agent/prompts/{extract,wbs,schedule,repair}.md`, `backend/tests/agent/test_generation.py`

**Interfaces — Consumes:** Task 6 `LlmClient`·등록부, Task 7 `check`·`assemble`·`apply_to_schedule`, Task 8 `DomainPack`, Task 4 `save_new_version`
**Produces:**
- 도구 `generate.extract_conditions {text, domain, level}` → `{domain, level, found: [{item_id, value, source:"프롬프트"}], conditions: [Condition], missing_must: [item_id]}` (LLM `light`, JSON 형식 답)
- 도구 `generate.make_wbs {answers, level}` → `{wbs: [WbsNode]}` (LLM `hard`). 깊이는 L1 1~2 · L2 2~3 · L3 3 · L4 4 · L5 5
- 도구 `generate.make_schedule {wbs, answers, level}` → `{activities, relations, resources}` — LLM은 `id, name, kind, wbs, od, tags, predecessors[{pred,type,lag}]`만 낸다. **날짜를 내지 않는다**(답에 날짜 필드가 있으면 버린다). 주요 자원 연결은 `pack.activity_types`의 `tags`로 코드가 붙인다.
- ```python
  GenStage = Literal["wbs", "schedule", "compute", "critical", "check"]
  GenRound(n: int, activity_count: int, violations: int)
  GenResult(ok: bool, schedule: Schedule | None, conditions: list[Condition], report: CheckReport | None,
            rounds: list[GenRound], assumptions: list[dict], conflict: list[str], reason: str | None)
  async def generate(ctx: ToolContext, llm: LlmClient, *, domain: str, level: str, answers: dict,
                     inputs: list[Condition], max_rounds: int = 5) -> GenResult
  ```
  흐름: WBS → 스케줄 → `apply_to_schedule` → `compute` → `check`. 위반이 있으면 위반 목록과 현재 초안 요약을 `repair` 지시문으로 LLM(`hard`)에 주고 고친 초안을 받아 다시. 단계가 바뀔 때마다 `AgentEvent("card", {kind:"generation", stage, rounds})`.
  - 초안이 깨졌으면(`ScheduleError`, JSON 아님, 없는 WBS 참조) 그 회차는 `violations=-1`로 기록하고 오류 내용을 LLM에 돌려 다시 받는다. 깨진 초안은 저장하지 않는다.
  - `max_rounds`에 닿으면 `ok=False`, 위반이 가장 적었던 초안을 `schedule`에, 끝까지 남은 조건 id를 `conflict`에, `reason="조건을 모두 맞추지 못했습니다."`
  - `LlmNotReady`/`LlmFailed`는 `ok=False, schedule=None, reason=<한국어 안내>`로 바꾼다.
  - `assumptions`: 생략 가능 항목에 분야 기본값을 쓴 것 `{item_id, value, source:"분야 기본값"}`
- 생성이 `ok`여도 저장하지 않는다 — 저장은 Task 11의 승인(첫 저장)을 거친다. 결과는 표 `schedule_drafts(id, session_id, schedule_json, conditions_json, report_json, created_at)`에 둔다.

- [ ] **Step 1: 실패하는 시험** (LLM은 미리 정한 답을 차례로 주는 `ScriptedLlm`)
```python
async def test_happy_path_three_rounds(ctx, pack_answers):
    llm = ScriptedLlm([WBS_OK, SCHED_LATE_BY_3, SCHED_LATE_BY_1, SCHED_OK])
    r = await generate(ctx, llm, domain="construction", level="L3", answers=pack_answers, inputs=[FINISH_BY_1130])
    assert r.ok and [x.violations for x in r.rounds] == [1, 1, 0] and r.report.violations == []
async def test_llm_dates_are_ignored(ctx, pack_answers):
    r = await generate(ctx, ScriptedLlm([WBS_OK, SCHED_OK_WITH_FAKE_DATES]), domain="construction", level="L3", answers=pack_answers, inputs=[])
    assert compute(r.schedule).rows["A1010"].es == date(2027, 3, 2)      # 03.01은 공휴일 → 코드가 계산
async def test_cyclic_draft_is_retried_not_saved(ctx, pack_answers, session):          # Review Focus 1
    r = await generate(ctx, ScriptedLlm([WBS_OK, SCHED_CYCLE, SCHED_OK]), domain="construction", level="L3", answers=pack_answers, inputs=[])
    assert r.ok and r.rounds[0].violations == -1 and session.query(ScheduleVersion).count() == 0
async def test_not_json_is_retried(ctx, pack_answers):                                 # Review Focus 1
    assert (await generate(ctx, ScriptedLlm([WBS_OK, "죄송합니다", SCHED_OK]), domain="construction", level="L3", answers=pack_answers, inputs=[])).ok
async def test_unsatisfiable_stops_at_limit_and_names_conflict(ctx, pack_answers):     # Review Focus 3
    llm = ScriptedLlm([WBS_OK] + [SCHED_LATE_BY_3] * 9)
    r = await generate(ctx, llm, domain="construction", level="L3", answers=pack_answers, inputs=[FINISH_BY_0401], max_rounds=3)
    assert not r.ok and len(r.rounds) == 3 and r.conflict == ["in.finish_by"] and r.schedule is not None
async def test_llm_down_gives_reason_and_no_draft(ctx, pack_answers, session):         # Review Focus 2
    r = await generate(ctx, FailingLlm("timeout"), domain="construction", level="L3", answers=pack_answers, inputs=[])
    assert not r.ok and r.schedule is None and "늦습니다" in r.reason and session.query(ScheduleDraft).count() == 0
async def test_key_resources_attached_by_tag(ctx, pack_answers):
    r = await generate(ctx, ScriptedLlm([WBS_OK, SCHED_OK]), domain="construction", level="L3", answers=pack_answers, inputs=[])
    assert "crane" in next(a for a in r.schedule.activities if "골조" in a.name).resources
async def test_generation_cards_are_emitted(ctx, pack_answers, events):
    await generate(ctx, ScriptedLlm([WBS_OK, SCHED_OK]), domain="construction", level="L3", answers=pack_answers, inputs=[])
    assert [e.data["stage"] for e in events if e.type == "card"][:2] == ["wbs", "schedule"]
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 일정 생성 루프`

---

### Task 10: 에이전트 루프·대화 API·워크플로우 기록 [fable]

**Files:** Create `backend/app/agent/{loop,context,events,workflow_log}.py`, `backend/app/agent/prompts/system.md`, `backend/app/programs/chat/{router,service,schemas}.py`, `backend/app/programs/workflow/{router,service,schemas}.py`, `backend/tests/agent/test_loop.py`, `backend/tests/programs/test_chat_api.py`

**Interfaces — Consumes:** Task 6·8·9
**Produces:**
```python
AgentEvent(type: Literal["text", "tool_start", "tool_end", "card", "workflow", "open_window",
                         "questionnaire", "approval", "usage", "error", "done"], data: dict)
UiContext(program: str | None, schedule_id: int | None, selected_activity: str | None)
async def run_turn(session, user, chat_session_id: int, text: str, ui: UiContext, *,
                   llm: LlmClient | None = None, max_steps: int = 12) -> AsyncIterator[AgentEvent]
def build_context(session, user, chat_session_id, ui) -> list[dict]   # 지시문 + 분야 요약 + 조건 요약 + 화면 맥락 + 대화
```
- 표 `chat_sessions(id, user_id, title, schedule_id, created_at)`, `chat_messages(id, session_id, role, content_json, created_at)`, `workflow_runs(id, chat_session_id, title, request, status 'running'|'done'|'failed'|'stopped', started_at, ended_at, tokens, cost)`, `workflow_steps(id, run_id, n, tool, program, why, status, input_json, output_json, ms, model, tokens, cost)`
- 루프: LLM(`normal`)에 도구 목록을 주고 호출 → 도구 호출이 오면 `tool_start` → `registry.call` → `tool_end` → 결과를 메시지에 붙여 다시 → 도구 호출이 없으면 `text`·`done`. 단계마다 `workflow_steps`에 기록하고 `workflow` 이벤트(단계 목록·상태). `max_steps`에 닿으면 `error {"code":"step_limit","message":"단계 한도에 닿아 멈췄습니다."}` 뒤 `done`.
- 일정 생성 요청 흐름(지시문에 적는다): `generate.extract_conditions` → 빈 필수 항목이 있으면 `ask.questionnaire` 뒤 턴을 끝냄 → 질문지 제출이 오면(`POST …/submit`이 같은 대화에 시스템 메시지 "질문지 제출됨"을 넣고 턴을 시작) `generation.generate` → 결과 카드(`kind:"generation_result"`: 준공·액티비티 수·크리티컬 수·가정·위반) → `out.submit_change`(Task 11)로 첫 저장 요청.
- `LlmNotReady`면 `error {"code":"llm_not_ready","message":"LLM 연결이 필요합니다. 설정에서 연결해 주세요.","action":{"open":"settings","params":{"section":"llm"}}}`
- API: `GET/POST /api/chat/sessions` · `GET /api/chat/sessions/{id}`(메시지 포함) · `POST /api/chat/sessions/{id}/messages {text, ui}` → `text/event-stream`, 이벤트마다 `event: <type>\ndata: <json>\n\n` · `POST /api/chat/sessions/{id}/stop` · `GET /api/workflows/runs` · `GET /api/workflows/runs/{id}`(단계 포함. `input_json`/`output_json`은 관리자가 아니면 2,000자에서 자른다)

- [ ] **Step 1: 실패하는 시험**
```python
async def test_plain_answer(run):
    ev = await run(ScriptedLlm([reply("안녕하세요")]), "안녕"); assert [e.type for e in ev] == ["text", "usage", "done"]
async def test_tool_call_roundtrip_is_logged(run, session):
    ev = await run(ScriptedLlm([calls("schedule.read", {}), reply("62개입니다")]), "액티비티 몇 개야?")
    assert [e.type for e in ev if e.type.startswith("tool")] == ["tool_start", "tool_end"]
    assert session.query(WorkflowStep).one().tool == "schedule.read"
async def test_step_limit_stops(run):
    ev = await run(ScriptedLlm([calls("schedule.read", {})] * 20), "x", max_steps=3)
    assert ev[-2].data["code"] == "step_limit" and ev[-1].type == "done"
async def test_llm_not_ready_points_to_settings(run_no_llm):                      # Review Focus 2
    ev = await run_no_llm("x"); assert ev[0].type == "error" and ev[0].data["action"]["open"] == "settings"
async def test_llm_fails_midway_keeps_conversation(run, session):                 # Review Focus 2
    ev = await run(ScriptedLlm([calls("schedule.read", {}), FAIL("timeout")]), "x")
    assert ev[-2].type == "error" and session.query(WorkflowRun).one().status == "failed"
async def test_ui_context_reaches_prompt(run, spy_llm):
    await run(spy_llm, "이거 당겨 줘", ui=UiContext("schedule", 1, "A2020")); assert "A2020" in spy_llm.last_messages_text
def test_sse_stream_format(client, admin, chat_id, scripted):
    body = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"text": "안녕", "ui": {}}, headers=admin).text
    assert "event: text\n" in body and body.rstrip().endswith("event: done\ndata: {}")
def test_step_io_truncated_for_user_role(client, user, run_id_with_big_output):
    assert len(client.get(f"/api/workflows/runs/{run_id_with_big_output}", headers=user).json()["steps"][0]["output_json"]) <= 2000
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 에이전트 루프와 대화 API`

---

### Task 11: 승인 판단·승인함·되돌리기 [opus]

**Files:** Create `backend/app/agent/approval.py`, `backend/app/tools/out/submit_change.py`, `backend/app/programs/approvals/{router,service,schemas}.py`, `backend/tests/agent/test_approval.py`, `backend/tests/programs/test_approvals_api.py`

**Interfaces — Consumes:** Task 4 버전, Task 7 `check`
**Produces:**
```python
Reason = Literal["first_save", "finish_changed", "milestone_changed", "critical_path_changed",
                 "condition_violated", "condition_changed", "structure_changed", "plan_reset", "rule_save"]
Decision(needs_approval: bool, reasons: list[Reason])
def decide(before: Schedule | None, after: Schedule, before_conditions, after_conditions, report: CheckReport,
           *, mode: Literal["all", "important", "auto"] = "important") -> Decision
```
규칙(`important`): 위 사유가 하나라도 있으면 승인 필요. 없으면 자동 적용. `all`은 항상 승인, `auto`는 `condition_violated`만 승인. `structure_changed` = 액티비티·관계 삭제 또는 WBS 변경. `mode`는 표 `settings(key, value)`의 `approval_mode`(기본 `important`).
- 표 `approvals(id, schedule_id, draft_id, kind, title, reasons_json, base_version, diff_json, status 'pending'|'approved'|'rejected'|'conflict', requested_by, decided_by, note, created_at, decided_at)`
- 도구 `out.submit_change {draft_id | changes[], title}` → 승인 필요면 승인 건을 만들고 `AgentEvent("approval", {id})`, 아니면 바로 `save_new_version(by_kind="agent")`하고 `AgentEvent("card", {kind:"auto_applied", version, count})`. 출력 `{applied: bool, approval_id?, version?}`
- API: `GET /api/approvals?status=pending|decided|auto` · `GET /api/approvals/{id}`(`diff`: `[{activity_id, name, before:{start,finish}, after:{start,finish}, finish_delta}]` + 조건 변화) · `POST /api/approvals/{id}/decide {decision:"approve"|"reject", note}` — 모든 로그인 계정 가능. 승인 시 `base_version != current_version`이면 `409 {"code":"version_conflict","message":"그 사이 일정이 바뀌었습니다. 에이전트에게 다시 요청해 주세요."}` 상태 `conflict`, 반영 안 함. 첫 저장(`first_save`) 승인이면 그 버전이 `is_plan=True`. · `GET /api/approvals/count`(메뉴바 배지)
- 되돌리기: Task 4의 `restore` API를 쓴다. 자동 적용 목록 `status=auto`는 `change_log`의 `by_kind='agent'`이면서 승인 건이 없는 것.

- [ ] **Step 1: 실패하는 시험**
```python
def test_absorbed_in_float_is_auto(s, s_noncritical_plus2): assert decide(s, s_noncritical_plus2, C, C, OK).needs_approval is False
def test_finish_change_needs_approval(s, s_finish_plus4): assert "finish_changed" in decide(s, s_finish_plus4, C, C, OK).reasons
def test_critical_path_change(s, s_other_path): assert "critical_path_changed" in decide(s, s_other_path, C, C, OK).reasons
def test_condition_change(s): assert "condition_changed" in decide(s, s, C, C_CRANE_2, OK).reasons
def test_first_save_always_needs_approval(s): assert decide(None, s, [], C, OK).reasons == ["first_save"]
def test_delete_activity_is_structure_change(s, s_minus_one): assert "structure_changed" in decide(s, s_minus_one, C, C, OK).reasons
def test_mode_all_and_auto(s, s_noncritical_plus2, s_finish_plus4):
    assert decide(s, s_noncritical_plus2, C, C, OK, mode="all").needs_approval and not decide(s, s_finish_plus4, C, C, OK, mode="auto").needs_approval
def test_approve_first_save_becomes_plan(client, admin, pending_first):
    r = client.post(f"/api/approvals/{pending_first}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert r.status_code == 200 and client.get("/api/schedules/1/versions", headers=admin).json()[0]["is_plan"] is True
def test_user_role_can_approve(client, user, pending): assert client.post(f"/api/approvals/{pending}/decide", json={"decision": "approve", "note": ""}, headers=user).status_code == 200
def test_stale_approval_conflicts_and_does_not_apply(client, admin, pending, sid):          # Review Focus 4
    client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 9, "base_version": 1}, headers=admin)
    r = client.post(f"/api/approvals/{pending}/decide", json={"decision": "approve", "note": ""}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict" and client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 2
def test_reject_keeps_schedule_and_stores_note(client, admin, pending, session):
    client.post(f"/api/approvals/{pending}/decide", json={"decision": "reject", "note": "크레인 추가는 안 됨"}, headers=admin)
    assert session.get(Approval, pending).note == "크레인 추가는 안 됨"
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 승인 판단과 승인함`

---

### Task 12: OS 셸 화면 [fable]

**Files:** Create `frontend/src/os/{tokens.css,session.ts,Login.tsx,Desktop.tsx,MenuBar.tsx,Dock.tsx,Window.tsx,windowStore.ts,registry.ts}`, `frontend/src/shared/{api.ts,sse.ts}`, `frontend/src/shared/ui/{Button,Badge,Tabs,Table,Field}.tsx`, 각 `*.test.tsx`/`*.test.ts`

**Interfaces — Consumes:** Task 1 로그인 API, Task 11 `GET /api/approvals/count`
**Produces:**
```ts
// windowStore.ts (zustand)
interface Win { id: string; programId: string; title: string; x: number; y: number; w: number; h: number; z: number; minimized: boolean; maximized: boolean; params?: Record<string, string> }
open(programId: string, params?: Record<string, string>): string   // 이미 열려 있으면 앞으로 가져오고 params 갱신
close(id) · focus(id) · move(id, x, y) · resize(id, w, h) · minimize(id) · toggleMaximize(id) · activeProgramId(): string | null
// registry.ts
register(m: ProgramManifest): void · programs(role: 'admin' | 'user'): ProgramManifest[]
// shared/api.ts
api<T>(path: string, init?: RequestInit): Promise<T>   // 토큰 붙임, 오류는 ApiError{code,message,detail,status}, 401이면 로그아웃
// shared/sse.ts
streamPost(path: string, body: unknown, onEvent: (type: string, data: unknown) => void, signal?: AbortSignal): Promise<void>
```
- `tokens.css` 값(시안과 같은 값): `--bg-topbar:#14213d; --bg-app:#f3f5f8; --bg-panel:#fff; --bg-panel-alt:#f7f9fb; --bg-selected:#e3edfb; --fg:#1c2333; --fg-muted:#5b6577; --border:#d9dfe8; --border-strong:#b9c2d0; --accent:#2f6fdb; --accent-text:#2a64c7; --danger:#c93b3b; --danger-text:#9b2c2c; --success:#1f9d55; --success-text:#17703f; --warning:#d98a1c; --warning-text:#8a5411; --tone-info-bg:#e3edfb; --tone-info-fg:#1f4f9e; --tone-success-bg:#dff3e6; --tone-warning-bg:#fbebd0; --tone-danger-bg:#fbe0e0; --radius-2:6px; --radius-3:8px; --radius-4:12px; --fs-12:12px; --fs-13:13px; --fs-14:14px; --row-h:32px; --topbar-h:44px; --font-sans:"Pretendard Variable",Pretendard,"Noto Sans KR",system-ui,sans-serif`. 바탕화면 배경 `linear-gradient(160deg,#0f1a33 0%,#1b2a4a 55%,#2a2f6b 100%)`.
- 화면: 로그인(시안 「로그인」) → 바탕화면. 메뉴바 = `ChronOS` 메뉴(정보·설정·잠금·로그아웃) · 앞에 있는 프로그램 이름과 그 `menus` · 승인 배지 · 알림 배지(묶음 3에서 연결, 지금은 0) · 사용자 이름과 등급 · 시계. 창 = 신호등 버튼(닫기·최소화·확대), 제목 줄 끌어 이동, 오른쪽 아래·가장자리로 크기 조절(최소 360×240), 누르면 맨 앞. Dock = 등록된 프로그램(관리자 전용은 관리자에게만), 실행 중 점, 배지, 누르면 열기/앞으로/최소화 복귀. 창은 메뉴바 아래·화면 안으로만 움직인다.
- 프로그램 화면은 `React.lazy`로 불러오고, 실패하면 창 안에 "이 프로그램을 열 수 없습니다" 표시(다른 창은 계속 동작).

- [ ] **Step 1: 실패하는 시험**
```ts
test('open twice focuses the same window', () => { const a = s.open('schedule'); s.open('chat'); const b = s.open('schedule', { tab: 'gantt' }); expect(b).toBe(a); expect(top().id).toBe(a); expect(win(a).params).toEqual({ tab: 'gantt' }) })
test('focus raises z above all', () => { const a = s.open('a'); const b = s.open('b'); s.focus(a); expect(win(a).z).toBeGreaterThan(win(b).z) })
test('move is clamped below the menubar and inside the screen', () => { const a = s.open('a'); s.move(a, -500, -500); expect(win(a).y).toBeGreaterThanOrEqual(44); expect(win(a).x).toBeGreaterThan(-win(a).w) })
test('resize has a minimum', () => { const a = s.open('a'); s.resize(a, 10, 10); expect(win(a)).toMatchObject({ w: 360, h: 240 }) })
test('minimized window is not active', () => { const a = s.open('a'); s.minimize(a); expect(s.activeProgramId()).toBeNull() })
test('admin-only programs are hidden from users', () => { register(m('dev', { adminOnly: true })); expect(programs('user').map(p => p.id)).not.toContain('dev') })
test('menubar shows the active program name', async () => { render(<Desktop />); await userEvent.click(dockIcon('일정판')); expect(within(menubar()).getByText('일정판')).toBeVisible() })
test('login failure shows the server message', async () => { mockLogin(401, { code: 'bad_credentials', message: '아이디 또는 비밀번호가 맞지 않습니다.' }); /* 제출 */ expect(await screen.findByText('아이디 또는 비밀번호가 맞지 않습니다.')).toBeVisible() })
test('a program that fails to load does not break the desktop', async () => { register(m('broken', { component: lazy(() => Promise.reject(new Error('x'))) })); /* 열기 */ expect(await screen.findByText('이 프로그램을 열 수 없습니다')).toBeVisible(); expect(dock()).toBeVisible() })
test('api adds token and maps errors', async () => { /* 422 응답 */ await expect(api('/x')).rejects.toMatchObject({ code: 'must_missing', status: 422 }) })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인(`docker compose run --rm frontend npm test`) → 커밋 `feat: OS 셸`

---

### Task 13: 설정 — LLM 연결·모델 배정 [opus]

**Files:** Create `frontend/src/programs/settings/{index.ts,Settings.tsx,LlmSection.tsx,ConnectionCard.tsx,Wizard.tsx,AssignmentTable.tsx,llmApi.ts,model.ts}`, `*.test.tsx`

**Interfaces — Consumes:** Task 5 API, Task 12 셸
**Produces:** 프로그램 `settings`(시스템, 기본 크기 1300×860). 메뉴: 내 정보 · (관리자) LLM 연결 · 작업별 모델 배정 · 계정. `params.section`으로 구역을 바로 연다. 시안 「설정」과 같은 구성 — 연결 카드(이름·공급자·상태 배지·URL·끝 4자리·확인 시각·[연결 테스트][URL 수정][키 교체][삭제]), 연결 추가 3단계(공급자 → 이름·URL·키 → 연결 테스트 결과와 모델 목록 → 저장), 배정 표(4줄, 모델은 불러온 목록에서 고름).
- `model.ts`: `PROVIDERS = [{value:'liner', label:'Liner', defaultBaseUrl:'https://platform.liner.com/api/v1'}, {value:'openai_compatible', label:'직접 URL (OpenAI 호환)', defaultBaseUrl:null}]`, `statusView(c) → {tone, text}`: ok → `연결됨 · 모델 ${n}개` / failed → `연결 실패` / unknown → `미확인`

- [ ] **Step 1: 실패하는 시험**
```ts
test('liner provider prefills the url', async () => { /* 마법사 ① Liner 선택 → ② */ expect(urlInput()).toHaveValue('https://platform.liner.com/api/v1') })
test('save is disabled until the test passes', async () => { /* ③ 테스트 전 */ expect(saveBtn()).toBeDisabled(); mockTest({ ok: true, latency_ms: 398, models: ['liner-mark'] }); await userEvent.click(testBtn()); expect(saveBtn()).toBeEnabled(); expect(screen.getByText(/모델 1개/)).toBeVisible() })
test('test failure shows the reason', async () => { mockTest({ ok: false, error: { code: 'bad_key', message: 'API 키가 맞지 않습니다.' } }); await userEvent.click(testBtn()); expect(screen.getByText('API 키가 맞지 않습니다.')).toBeVisible() })
test('key input is a password field and is cleared after save', async () => { expect(keyInput()).toHaveAttribute('type', 'password'); /* 저장 */ expect(screen.queryByDisplayValue('abcd1234efgh5678')).toBeNull(); expect(screen.getByText(/5678$/)).toBeVisible() })
test('changing host asks for the key again', async () => { mockPatch(422, { code: 'secret_required', message: '주소를 바꾸면 키를 다시 넣어야 합니다.' }); /* URL 수정 저장 */ expect(await screen.findByText('주소를 바꾸면 키를 다시 넣어야 합니다.')).toBeVisible() })
test('user role sees no admin sections', () => { renderAs('user'); expect(screen.queryByText('LLM 연결')).toBeNull() })
test('statusView', () => { expect(statusView({ status: 'ok', model_count: 512 })).toEqual({ tone: 'success', text: '연결됨 · 모델 512개' }) })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 설정 — LLM 연결`

### ◆ Checkpoint A — PM이 Liner 키를 넣는다

- [ ] `docker compose up -d` 뒤 테일넷 주소 `http://<이 맥의 테일넷 주소>:5600`을 PM에게 알린다. PM이 로그인 → 설정 → LLM 연결에서 키를 직접 넣고 연결 테스트를 누른다. **Claude는 키를 받지 않는다.**
- [ ] 연결 뒤 `backend/scripts/probe_liner.py`(이 체크포인트에서 만든다 — DB의 기본 연결로 호출)로 확인하고 `docs/dev-journal/2026-11.md`에 결과를 적는다: ① `liner-mark`·세 라우터의 도구 호출이 되는가 ② JSON 형식 답이 되는가 ③ 응답에 실제 모델 이름과 `usage.cost`가 오는가 ④ `routing_strategy`가 먹는가 ⑤ 그림 입력이 되는가(묶음 3용 기록만)
- [ ] 결과에 따라 배정 표 기본값(Task 5)을 고친다. 도구 호출이 안 되는 모델은 `normal`/`hard`에 배정하지 않는다.
- [ ] PR 보고서 `~/reports/pr_YYYYMMDD_HHMM.md` (Task 0~13)

---

### Task 14: 대화창 [fable]

**Files:** Create `frontend/src/programs/chat/{index.ts,Chat.tsx,ThreadList.tsx,Conversation.tsx,Composer.tsx,ContextPanel.tsx,cards/(ConditionsCard,GenerationCard,ResultCard,AutoAppliedCard,MiniQuestionsCard).tsx,chatStore.ts,chatApi.ts}`, `*.test.tsx`

**Interfaces — Consumes:** Task 10 대화 API·SSE, Task 12 `streamPost`·`windowStore.open`
**Produces:** 프로그램 `chat`(시스템, 기본 크기 480×760). 창 너비가 1100 이상이면 큰 화면(왼쪽 대화 목록 268 · 가운데 대화 · 오른쪽 컨텍스트 330), 미만이면 작은 화면(위쪽 대화 고르기 단추). 초록 버튼이 480×760 ↔ 1560×900을 오간다. 시안 「대화창 큰 화면」「작은 화면」과 같은 구성.
- 내 말은 오른쪽 말풍선, 에이전트 답은 본문. 도구 사용은 접힌 한 줄 `도구 n개 · n초`(펼치면 단계 이름). `card` 이벤트는 `kind`별 카드. `open_window` 이벤트는 `windowStore.open(program, params)`. `questionnaire` 이벤트는 `open('questionnaire', {id})`. `error` 이벤트에 `action.open`이 있으면 [설정 열기] 단추.
- 입력창 아래 `보는 중: <프로그램> · <고른 액티비티>` — 다른 프로그램이 `chatStore.setUiContext(...)`로 알린 값을 메시지와 함께 보낸다.
- 컨텍스트 패널: 지금 다루는 일정 · 에이전트가 참고하는 것(조건 수·겹별 수) · 워크플로우 단계(실시간) · 이번 대화 사용량(`usage` 이벤트 합).
- 보내는 중에는 [보내기]가 [중단]으로 바뀐다(`POST …/stop`).

- [ ] **Step 1: 실패하는 시험**
```ts
test('streams text into one assistant message', async () => { feed([['text', { delta: '안녕' }], ['text', { delta: '하세요' }], ['done', {}]]); await send('hi'); expect(screen.getByText('안녕하세요')).toBeVisible() })
test('tool steps collapse into one line', async () => { feed([['tool_start', { name: 'schedule.read' }], ['tool_end', { name: 'schedule.read', ms: 200 }], ['text', { delta: 'x' }], ['done', {}]]); await send('q'); expect(screen.getByText(/도구 1개/)).toBeVisible() })
test('generation card shows rounds', async () => { feed([['card', { kind: 'generation', stage: 'check', rounds: [{ n: 1, violations: 3 }, { n: 2, violations: 0 }] }], ['done', {}]]); await send('q'); expect(screen.getByText(/1회차 위반 3 → 2회차 0/)).toBeVisible() })
test('open_window event opens the program', async () => { feed([['open_window', { program: 'schedule', params: { tab: 'gantt' } }], ['done', {}]]); await send('q'); expect(openSpy).toHaveBeenCalledWith('schedule', { tab: 'gantt' }) })
test('llm_not_ready shows a settings button', async () => { feed([['error', { code: 'llm_not_ready', message: 'LLM 연결이 필요합니다. 설정에서 연결해 주세요.', action: { open: 'settings', params: { section: 'llm' } } }], ['done', {}]]); await send('q'); await userEvent.click(screen.getByRole('button', { name: '설정 열기' })); expect(openSpy).toHaveBeenCalledWith('settings', { section: 'llm' }) })
test('ui context is sent with the message', async () => { chatStore.getState().setUiContext({ program: 'schedule', schedule_id: 1, selected_activity: 'A2020' }); await send('이거 당겨 줘'); expect(lastBody().ui.selected_activity).toBe('A2020') })
test('wide window shows thread list and context panel', () => { renderAt(1560); expect(screen.getByText('새 대화')).toBeVisible(); expect(screen.getByRole('tab', { name: '컨텍스트' })).toBeVisible() })
test('narrow window hides them', () => { renderAt(480); expect(screen.queryByRole('tab', { name: '컨텍스트' })).toBeNull() })
test('send becomes stop while streaming', async () => { feedPending(); await send('q'); expect(screen.getByRole('button', { name: '중단' })).toBeVisible() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 대화창`

---

### Task 15: 질문지 화면 [opus]

**Files:** Create `frontend/src/programs/questionnaire/{index.ts,Questionnaire.tsx,GroupNav.tsx,QuestionCard.tsx,FilledList.tsx,qApi.ts}`, `*.test.tsx`

**Interfaces — Consumes:** Task 8 질문지 API
**Produces:** 프로그램 `questionnaire`(시스템, 기본 크기 1180×860, `params.id`). 시안 「질문지 (B안 확정)」 구성 — 왼쪽: 진행 막대(`필수 n개 중 m개`)와 묶음 목차(초록 채움·주황 남음·회색 아직), 묶음 안 항목 목록. 오른쪽: 질문 하나씩 — 선택지(추천 표시·힌트) + 직접 입력 칸 + 생략 가능이면 [알아서], 그 아래 "이 묶음에서 이미 채운 것"(값·출처·[고치기]). 아래: [이전][다음 질문] · [나머지는 알아서](생략 가능 항목만 `__auto__`) · [대화로 답하기](대화창을 앞으로) · [제출하고 생성 (필수 n개 남음)] — 필수가 남으면 비활성.
- 답할 때마다 `PATCH`하고 돌아온 전체 상태로 다시 그린다(이어지는 질문이 생기고 사라짐). 제출 성공 시 창을 닫고 대화창을 앞으로.

- [ ] **Step 1: 실패하는 시험**
```ts
test('progress and nav reflect server state', () => { render(q({ must_total: 20, must_filled: 16 })); expect(screen.getByText('필수 20개 중 16개')).toBeVisible() })
test('choosing an option patches and re-renders follow-ups', async () => { mockPatch(withItem('retaining_wall')); await userEvent.click(screen.getByRole('button', { name: /지하 1층/ })); expect(await screen.findByText(/흙막이/)).toBeVisible() })
test('free input submits on enter', async () => { await userEvent.type(freeInput(), '주 6일 격주{Enter}'); expect(lastPatch()).toEqual({ item_id: 'work_week', value: '주 6일 격주' }) })
test('auto button only on optional items', () => { render(q(mustItem())); expect(screen.queryByRole('button', { name: '알아서' })).toBeNull() })
test('submit disabled while must items remain', () => { render(q({ must_total: 20, must_filled: 16 })); expect(screen.getByRole('button', { name: /제출하고 생성 \(필수 4개 남음\)/ })).toBeDisabled() })
test('filled items show source and can be edited', async () => { expect(screen.getByText('프롬프트')).toBeVisible(); await userEvent.click(screen.getAllByRole('button', { name: '고치기' })[0]); expect(freeInput()).toBeVisible() })
test('submit closes and focuses chat', async () => { mockSubmit(200); await userEvent.click(submitBtn()); expect(closeSpy).toHaveBeenCalled(); expect(openSpy).toHaveBeenCalledWith('chat', undefined) })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 질문지 화면`

---

### Task 16: 일정판 — 스케줄표 [opus]

**Files:** Create `frontend/src/programs/schedule/{index.ts,Schedule.tsx,scheduleStore.ts,scheduleApi.ts}`, `frontend/src/programs/schedule/table/{TableTab.tsx,columns.tsx,Row.tsx,RelationsPanel.tsx,predecessors.ts,Toolbar.tsx}`, `*.test.tsx`/`*.test.ts`

**Interfaces — Consumes:** Task 4 일정 API(`ScheduleView`), Task 14 `chatStore.setUiContext`
**Produces:** 프로그램 `schedule`(업무, 기본 크기 1600×900, `params.id`·`params.tab`). 탭 `스케줄표 | 간트 | CPM | 진행` — 이 계획에서는 앞의 둘만 만들고 CPM·진행 탭은 "묶음 2에서 만듭니다" 자리표시.
- `scheduleStore`: `{ view: ScheduleView | null, selected: string | null, load(id), patchActivity(aid, fields), setPredecessors(aid, items), select(aid) }` — 고치면 서버 응답의 `ScheduleView`로 통째로 바꾼다. `409 version_conflict`면 다시 불러오고 "그 사이 일정이 바뀌어 다시 불러왔습니다" 알림.
- `predecessors.ts`: `parse("A2010, A1040 SS+15") → [{pred:'A2010',type:'FS',lag:0},{pred:'A1040',type:'SS',lag:15}]` / `format(items) → string` / 틀리면 `ParseError(message)` ("선행 형식이 맞지 않습니다: …")
- 칸(시안 「스케줄표」 순서): ID · 이름 · 유형 · WBS · 가중치(%) · OD · RD · Plan 시작 · Plan 종료 · Actual 시작 · Actual 종료 · 진도(%) · 상태 · TF · FF · 선행. 고칠 수 있는 칸: 이름·유형·OD·RD·Actual 시작/종료·진도·선행. Plan 시작/종료·TF·FF·상태·가중치는 읽기 전용. WBS 묶음 줄은 굵게, 접고 펼 수 있다. `tf === 0`은 위험색.
- 머리줄: Data Date · 완료 예정 · 크리티컬 n · 음수 플로트 n · 경고 n. 도구줄: [+ 행 추가][삭제] · 검색 · [열] · CSV 내보내기. 아래 관계 패널: 고른 액티비티의 선행·후행 표(구분·ID·이름·관계·간격), [+ 선행 추가].
- 행을 고르면 `chatStore.setUiContext({program:'schedule', schedule_id, selected_activity})`.

- [ ] **Step 1: 실패하는 시험**
```ts
test.each([['A1', [{ pred: 'A1', type: 'FS', lag: 0 }]], ['A1 SS+15', [{ pred: 'A1', type: 'SS', lag: 15 }]], ['A1 FF-2, B2', [{ pred: 'A1', type: 'FF', lag: -2 }, { pred: 'B2', type: 'FS', lag: 0 }]], ['', []]])('parse %s', (s, out) => expect(parse(s)).toEqual(out))
test('parse rejects garbage', () => expect(() => parse('A1 XX+1')).toThrow('선행 형식이 맞지 않습니다'))
test('format is the inverse of parse', () => expect(format(parse('A1 SS+15, B2'))).toBe('A1 SS+15, B2'))
test('editing OD patches with base_version and re-renders', async () => { mockPatch(viewWith({ version: 2, finish: '2027-11-26' })); await editCell('A2020', 'OD', '52'); expect(lastBody()).toEqual({ od: 52, base_version: 1 }); expect(await screen.findByText(/2027\.11\.26/)).toBeVisible() })
test('plan dates are read-only', () => { expect(cell('A2020', 'Plan 시작')).not.toHaveAttribute('contenteditable'); expect(within(cell('A2020', 'Plan 시작')).queryByRole('textbox')).toBeNull() })
test('server rejection shows message and restores the cell', async () => { mockPatch(422, { code: 'schedule_invalid', message: '선후 관계가 고리를 이룹니다.' }); await editCell('A2020', '선행', 'A3010'); expect(await screen.findByText('선후 관계가 고리를 이룹니다.')).toBeVisible(); expect(cell('A2020', '선행')).toHaveTextContent('A2010') })
test('version conflict reloads', async () => { mockPatch(409, { code: 'version_conflict', message: 'x' }); await editCell('A2020', 'OD', '52'); expect(loadSpy).toHaveBeenCalledTimes(2) })
test('critical TF is marked', () => expect(cell('A2020', 'TF')).toHaveClass('danger'))
test('selecting a row sets chat ui context and fills relations panel', async () => { await userEvent.click(row('A2020')); expect(chatStore.getState().ui.selected_activity).toBe('A2020'); expect(within(relationsPanel()).getByText('지하 1층 골조')).toBeVisible() })
test('wbs row collapses its children', async () => { await userEvent.click(toggle('2 골조')); expect(screen.queryByText('A2020')).toBeNull() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 일정판 스케줄표`

---

### Task 17: 일정판 — 간트 [fable]

**Files:** Create `frontend/src/shared/gantt/{scale.ts,Header.tsx,Bars.tsx,Links.tsx,layout.ts}`, `frontend/src/programs/schedule/gantt/{GanttTab.tsx,GanttToolbar.tsx,LeftGrid.tsx,ResourceStrip.tsx,grouping.ts}`, `*.test.ts(x)`

**Interfaces — Consumes:** Task 16 `scheduleStore`, `ScheduleView`
**Produces:**
```ts
// shared/gantt/scale.ts
interface Scale { start: Date; end: Date; pxPerDay: number }
makeScale(start: string, end: string, widthPx: number, padDays?: number): Scale
x(scale: Scale, date: string): number            // 그 날 0시의 x
barRect(scale, start: string, finish: string): { x: number; w: number }   // finish 포함 — 하루짜리도 pxPerDay 폭
months(scale): { label: string; x: number; w: number }[]   // 첫 달만 'YYYY년 M월', 나머지 'M월'
weeks(scale): { x: number; label: string }[]
// shared/gantt/layout.ts
linkPath(from: {x:number,w:number,row:number}, to: {...}, type: RelType, rowH: number): string   // 꺾은선 SVG path, 화살표는 marker
// programs/schedule/gantt/grouping.ts
type GroupBy = 'wbs' | 'resource'
rowsFor(view: ScheduleView, by: GroupBy, collapsed: Set<string>): GanttRow[]
//  GanttRow { key, kind: 'group' | 'activity' | 'milestone', label, activity?, depth, spanStart?, spanFinish? }
//  'resource' 묶음: 주요 자원마다 그룹 줄 + 그 자원을 쓰는 액티비티, 자원 없는 것은 '자원 없음' 그룹
```
- 화면(시안 「간트」): 왼쪽 표(WBS/ID · 이름 · OD · RD · TF) + 오른쪽 차트, 가운데 나눔선 끌어 폭 조절. 줄 높이 30.
- 층 단추 Plan · Actual · CPM(켜고 끔). Plan 막대: 일반 `--accent`계열, CPM 층이 켜지면 크리티컬은 `--danger`. Actual: 막대 아래 가는 `--success` 줄(시작~종료 또는 Data Date까지). 마일스톤 ◆. 묶음 줄은 얇은 요약 막대. 관계선은 CPM 층이 켜졌을 때 그리고 크리티컬 경로는 `--danger`.
- 세로선: Data Date(`--warning`), 준공 기한(`finish_by` 조건이 있으면 점선 `--danger`), 주말 음영(5·6일 근무에 맞게).
- 도구줄: 확대·축소(pxPerDay ×1.25) · [맞춤] · [Data Date] · [오늘] · 묶는 기준(WBS/자원) · 모두 펼치기/접기 · 범례.
- 아래 자원 줄: 주요 자원별 일별 필요량 막대, 용량 초과 구간은 `--danger`(값은 `ScheduleView.resources[].load[]` — Task 4 응답에 `load: [{date, need}]`, `capacity`, `peak` 추가. 이 Task에서 서버 응답을 넓힌다: Modify `backend/app/programs/schedule/service.py`, 시험 추가).
- 막대 끌기는 묶음 3. 이 계획에서는 막대를 누르면 행 선택만.

- [ ] **Step 1: 실패하는 시험**
```ts
test('one-day bar has one day width', () => { const s = makeScale('2027-03-01', '2027-03-31', 620, 0); expect(barRect(s, '2027-03-02', '2027-03-02').w).toBeCloseTo(s.pxPerDay) })
test('bar x is monotonic and finish is inclusive', () => { const s = makeScale('2027-03-01', '2027-03-31', 620, 0); const r = barRect(s, '2027-03-01', '2027-03-03'); expect(r.x).toBe(0); expect(r.w).toBeCloseTo(3 * s.pxPerDay) })
test('months label first with year', () => { expect(months(makeScale('2027-03-01', '2027-05-31', 900, 0)).map(m => m.label)).toEqual(['2027년 3월', '4월', '5월']) })
test('group by resource puts shared activity under each resource', () => { const rows = rowsFor(viewTwoResources, 'resource', new Set()); expect(rows.filter(r => r.activity?.id === 'A2020')).toHaveLength(2) })
test('collapsed group hides children but keeps summary span', () => { const rows = rowsFor(view, 'wbs', new Set(['2'])); expect(rows.find(r => r.key === '2')!.spanFinish).toBe('2027-07-14'); expect(rows.some(r => r.activity?.id === 'A2020')).toBe(false) })
test('CPM layer off hides links and critical color', async () => { render(<GanttTab />); await userEvent.click(screen.getByRole('button', { name: 'CPM' })); expect(document.querySelectorAll('[data-link]')).toHaveLength(0); expect(bar('A2020')).not.toHaveClass('critical') })
test('actual layer draws progress under the plan bar', () => { expect(actualBar('A2020')).toBeInTheDocument(); expect(actualBar('A3010')).toBeNull() })
test('deadline line appears only with a finish_by condition', () => { expect(screen.getByText(/기한 11\.30/)).toBeVisible() })
test('overloaded days are marked in the resource strip', () => { expect(document.querySelectorAll('[data-res="crane"] .over').length).toBeGreaterThan(0) })
test('zoom changes pxPerDay by 1.25', async () => { const before = pxPerDay(); await userEvent.click(screen.getByRole('button', { name: '확대' })); expect(pxPerDay()).toBeCloseTo(before * 1.25) })
```
```python
def test_schedule_view_includes_resource_load(client, admin, sid_two_crane_tasks):
    res = client.get(f"/api/schedules/{sid_two_crane_tasks}", headers=admin).json()["resources"][0]
    assert res["capacity"] == 1 and res["peak"]["need"] == 2 and res["load"][0] == {"date": "2027-03-01", "need": 2}
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 일정판 간트`

---

### Task 18: 조건·규칙 — 겹별 보기와 실시간 미리 보기 [fable]

**Files:** Create `backend/app/programs/conditions/{router,service,schemas}.py`, `backend/tests/programs/test_conditions_api.py`, `frontend/src/programs/conditions/{index.ts,Conditions.tsx,LayerColumn.tsx,ConditionItem.tsx,PreviewBar.tsx,condApi.ts,condStore.ts}`, `*.test.tsx`; Modify `frontend/src/programs/schedule/scheduleStore.ts`(미리 보기 겹)

**Interfaces — Consumes:** Task 7 `check`·`assemble`·`apply_to_schedule`, Task 4 버전, Task 11 `decide`·승인 건 만들기
**Produces:**
- API: `GET /api/schedules/{id}/conditions` → `{version, layers: {base[], domain[], mine[], input[]}, summary:{passed, violated, uncheckable}}` — 각 조건 `{id, layer, kind, params, text, source, enabled, editable, state:'passed'|'violated'|'uncheckable'|'off', message?, overridden_by?, used_by?: string[]}` (`editable`: base 거짓, domain은 켜고 끄기만, mine·input 참)
- `POST /api/schedules/{id}/conditions/preview {base_version, changes:[{id, params?, enabled?} | {add: Condition} | {remove: id}]}` → `{feasible: bool, view: ScheduleView, before:{finish, critical_count, violated}, after:{…}, moved:[{activity_id, name, before:{start,finish}, after:{start,finish}}], violations:[…]}` — **저장하지 않는다.** 계산은 `apply_to_schedule` → `compute` → `level(shift=True)` → `check`. `feasible`은 위반이 없을 때 참.
- `POST /api/schedules/{id}/conditions/commit {base_version, changes}` → `decide(...)`로 판단해 `{applied: true, version}` 또는 `{applied: false, approval_id}`(조건 자체를 바꾸는 것은 `condition_changed` 사유라 `important`에서는 승인함으로 간다)
- `POST /api/schedules/{id}/conditions/ask-agent {base_version, changes}` → 대화 세션에 "이 조건에 맞게 일정을 고쳐 줘" 턴을 시작하고 `{chat_session_id}` (화면은 대화창을 앞으로)
- 프로그램 `conditions`(업무, 기본 크기 1400×860, `params.id`). 시안 「조건·규칙 (B안 확정)」 — 네 칸(① 기본 규칙 "못 바꿈" · ② 분야 규칙 "관리자만 수정" · ③ 내 규칙 · ④ 입력 조건, ④가 가장 넓음). 조건마다 글·출처·상태 배지·(해당하면) 수량 입력 칸. 값을 바꾸면 300ms 뒤 `preview` 호출 → 위쪽 막대에 "미리 보기 중 · 준공 a → b · 위반 n" + [되돌리기][에이전트에게 맞추게 하기][확정]. `feasible`이 거짓이면 [확정] 대신 위반 안내와 [에이전트에게 맞추게 하기]를 강조.
- 미리 보기 동안 `scheduleStore.setPreview(view, moved)` — 일정판 간트가 미리 보기 일정을 그리고, 움직인 액티비티의 이전 위치를 점선 막대로 남긴다. [되돌리기]·창 닫기·[확정]에서 `clearPreview()`.
- 내 규칙 저장·제안은 묶음 2. 이 계획에서 ③ 칸은 읽기만 한다.

- [ ] **Step 1: 실패하는 시험**
```python
def test_layers_and_states(client, admin, sid):
    j = client.get(f"/api/schedules/{sid}/conditions", headers=admin).json()
    assert j["layers"]["base"][0]["editable"] is False and any(c["state"] == "uncheckable" for c in j["layers"]["input"])
def test_preview_crane_two_pulls_finish_and_does_not_save(client, admin, sid_crane):
    r = client.post(f"/api/schedules/{sid_crane}/conditions/preview", json={"base_version": 1, "changes": [{"id": "in.crane", "params": {"resource_id": "crane", "capacity": 2}}]}, headers=admin).json()
    assert r["after"]["finish"] < r["before"]["finish"] and r["moved"] and client.get(f"/api/schedules/{sid_crane}", headers=admin).json()["version"] == 1
def test_preview_infeasible_deadline(client, admin, sid):
    r = client.post(f"/api/schedules/{sid}/conditions/preview", json={"base_version": 1, "changes": [{"id": "in.finish_by", "params": {"date": "2027-06-30"}}]}, headers=admin).json()
    assert r["feasible"] is False and r["violations"][0]["condition_id"] == "in.finish_by"
def test_commit_condition_change_goes_to_approval(client, admin, sid_crane):
    r = client.post(f"/api/schedules/{sid_crane}/conditions/commit", json={"base_version": 1, "changes": [{"id": "in.crane", "params": {"resource_id": "crane", "capacity": 2}}]}, headers=admin).json()
    assert r["applied"] is False and r["approval_id"]
def test_base_layer_cannot_be_changed(client, admin, sid):
    assert client.post(f"/api/schedules/{sid}/conditions/preview", json={"base_version": 1, "changes": [{"id": "base.no_cycle", "enabled": False}]}, headers=admin).status_code == 422
def test_user_cannot_toggle_domain_rule(client, user, sid):
    assert client.post(f"/api/schedules/{sid}/conditions/commit", json={"base_version": 1, "changes": [{"id": "dom.curing", "enabled": False}]}, headers=user).status_code == 403
def test_stale_base_version_conflicts(client, admin, sid_v2):
    assert client.post(f"/api/schedules/{sid_v2}/conditions/preview", json={"base_version": 1, "changes": []}, headers=admin).status_code == 409
```
```ts
test('four columns with lock labels', () => { expect(screen.getByText('못 바꿈')).toBeVisible(); expect(screen.getByText('관리자만 수정')).toBeVisible() })
test('changing a quantity previews after debounce and shows the delta', async () => { mockPreview({ feasible: true, before: { finish: '2027-11-24' }, after: { finish: '2027-11-12' }, moved: [m('A3010')] }); await userEvent.clear(qty('타워크레인')); await userEvent.type(qty('타워크레인'), '2'); expect(await screen.findByText(/11\.24 → 11\.12/)).toBeVisible(); expect(scheduleStore.getState().preview).not.toBeNull() })
test('revert clears the preview', async () => { /* 위 상태에서 */ await userEvent.click(screen.getByRole('button', { name: '되돌리기' })); expect(scheduleStore.getState().preview).toBeNull(); expect(qty('타워크레인')).toHaveValue('1') })
test('infeasible preview hides confirm and offers the agent', async () => { mockPreview({ feasible: false, violations: [{ condition_id: 'in.finish_by', message: '준공이 기한보다 20일 늦습니다.' }] }); /* 기한 변경 */ expect(await screen.findByText('준공이 기한보다 20일 늦습니다.')).toBeVisible(); expect(screen.queryByRole('button', { name: '확정' })).toBeNull(); expect(screen.getByRole('button', { name: '에이전트에게 맞추게 하기' })).toBeVisible() })
test('commit that needs approval says so', async () => { mockCommit({ applied: false, approval_id: 7 }); await userEvent.click(screen.getByRole('button', { name: '확정' })); expect(await screen.findByText(/승인함으로 보냈습니다/)).toBeVisible() })
test('uncheckable condition is labeled, never "통과"', () => { expect(within(item('안전 우선')).getByText('자동 점검 안 됨')).toBeVisible(); expect(within(item('안전 우선')).queryByText('통과')).toBeNull() })
test('gantt draws ghost bars for moved activities during preview', () => { scheduleStore.getState().setPreview(previewView, [m('A3010')]); render(<GanttTab />); expect(document.querySelector('[data-ghost="A3010"]')).toBeInTheDocument() })
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 조건·규칙과 실시간 미리 보기`

---

### Task 19: 승인함 · 워크플로우 · 탐색기 화면 [opus]

**Files:** Create `frontend/src/programs/approvals/{index.ts,Approvals.tsx,ApprovalList.tsx,ApprovalDetail.tsx,DecisionBox.tsx,apvApi.ts}`, `frontend/src/programs/workflow/{index.ts,Workflow.tsx,RunList.tsx,StepGraph.tsx,StepDetail.tsx,graphLayout.ts,wfApi.ts}`, `frontend/src/programs/explorer/{index.ts,Explorer.tsx,Tree.tsx,VersionPanel.tsx,exApi.ts}`, `backend/app/programs/explorer/{router,service,schemas}.py`, `backend/tests/programs/test_explorer.py`, `*.test.tsx`

**Interfaces — Consumes:** Task 11 승인 API, Task 10 워크플로우 API·`workflow` 이벤트, Task 4 버전 API
**Produces:**
- `approvals`(시스템, 1200×760, `params.id`): 시안 「승인함 (2판)」 — 왼쪽 [대기 n][결정됨][자동 적용 n] + 목록, 오른쪽 제목·요청·"승인이 필요한 이유"(사유별 한국어: `finish_changed` "준공일" · `critical_path_changed` "크리티컬 패스" · `condition_changed` "조건 변경" · `first_save` "새 일정의 첫 저장" · `structure_changed` "구조 변경" · `milestone_changed` "주요 날짜" · `condition_violated` "조건 위반" · `plan_reset` "Plan 다시 잡기" · `rule_save` "내 규칙 저장") · 전후 표 · [간트에서 보기] · 결정 상자(의견 칸, [거부][거부하고 다시 짜게 하기][승인하고 반영]). `409 version_conflict`면 서버 문구를 보여 주고 상태를 "충돌"로. "자동 적용" 탭은 줄마다 [되돌리기](→ `restore`). "거부하고 다시 짜게 하기"는 거부 뒤 의견을 대화 메시지로 보낸다.
- `workflow`(시스템, 1400×860, `params.run`): 시안 「워크플로우·스킬」에서 실행 기록 탭만(저장·스킬 탭은 묶음 3 자리표시). 왼쪽 실행 목록, 가운데 단계 그림(완료 `--success` 테두리 · 실행 중 `--accent` + 강조 · 대기 점선), 오른쪽 단계 상세(도구·왜·모델·시간·받은 것·돌려준 것). 실행 중이면 2초마다 다시 불러온다. `graphLayout.ts`: `layout(steps) → {nodes:[{id,x,y}], edges:[{from,to}]}` — 순서대로 가로 4칸씩 줄바꿈, `parallel_group`이 같은 단계는 세로로 쌓는다.
- `explorer`(시스템, 1100×720): 시안 「탐색기」에서 일정 목록과 버전 패널만(문서·보고서·복사본은 묶음 2·3 자리표시). `GET /api/explorer/tree` → `{schedules:[{id,name,domain,level,version,finish,updated_at}]}`. 일정을 고르면 오른쪽에 요약과 버전 목록(번호·`Plan` 표시·메모·누가·[되돌리기]), [일정판에서 열기]. `DELETE /api/schedules/{id}`는 관리자만.

- [ ] **Step 1: 실패하는 시험**
```ts
test('reasons are shown in Korean', () => { render(detail({ reasons: ['finish_changed', 'condition_changed'] })); expect(screen.getByText('준공일')).toBeVisible(); expect(screen.getByText('조건 변경')).toBeVisible() })
test('approve posts decision and moves the item out of pending', async () => { mockDecide(200); await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' })); expect(lastBody()).toEqual({ decision: 'approve', note: '' }); expect(await screen.findByText('대기 0')).toBeVisible() })
test('conflict shows server message', async () => { mockDecide(409, { code: 'version_conflict', message: '그 사이 일정이 바뀌었습니다. 에이전트에게 다시 요청해 주세요.' }); await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' })); expect(await screen.findByText(/그 사이 일정이 바뀌었습니다/)).toBeVisible() })
test('reject-and-retry sends the note to chat', async () => { await userEvent.type(noteBox(), '크레인 추가는 안 됨'); await userEvent.click(screen.getByRole('button', { name: '거부하고 다시 짜게 하기' })); expect(chatSendSpy).toHaveBeenCalledWith(expect.stringContaining('크레인 추가는 안 됨')) })
test('auto-applied row can be reverted', async () => { await userEvent.click(screen.getByRole('tab', { name: /자동 적용/ })); await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]); expect(restoreSpy).toHaveBeenCalled() })
test('graph layout wraps at four and stacks parallel steps', () => { const g = layout(steps(6, { parallel: [2, 3] })); expect(g.nodes[2].x).toBe(g.nodes[3].x); expect(g.nodes[2].y).not.toBe(g.nodes[3].y); expect(g.nodes[5].y).toBeGreaterThan(g.nodes[0].y) })
test('step states map to styles', () => { render(<StepGraph steps={[s('done'), s('running'), s('pending')]} />); expect(node(0)).toHaveClass('done'); expect(node(1)).toHaveClass('running'); expect(node(2)).toHaveClass('pending') })
test('explorer restore asks before applying', async () => { await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]); expect(screen.getByText(/버전 1의 내용으로 새 버전을 만듭니다/)).toBeVisible() })
```
```python
def test_tree_lists_schedules(client, admin, sid): assert client.get("/api/explorer/tree", headers=admin).json()["schedules"][0]["id"] == sid
def test_user_cannot_delete_schedule(client, user, sid): assert client.delete(f"/api/schedules/{sid}", headers=user).status_code == 403
```
- [ ] **Step 2~5:** 실패 확인 → 구현 → 통과 확인 → 커밋 `feat: 승인함·워크플로우·탐색기 화면`

---

### Task 20: 끝에서 끝까지 — 시연 뼈대와 제출 준비물 [opus]

**Files:** Create `backend/app/seed.py`, `backend/tests/e2e/test_generate_flow.py`, `frontend/e2e/demo.spec.ts`(Playwright, FHD), `docs/demo/시나리오.md`, `docs/contest/기획서.md`, `docs/dev-journal/2026-11.md`; Modify `README.md`, `docker-compose.yml`(`e2e` 서비스)

**Interfaces — Consumes:** 전부
**Produces:**
- `python -m app.seed demo` — 가상 예시 일정 "5층 사무동 신축"(건설·L3, 액티비티 60개 안팎, 조건 14개, 주요 자원 3개, 일부 실적 입력)을 만든다. 여러 번 돌려도 같은 결과(먼저 지우고 만든다). LLM을 부르지 않는다.
- 서버 끝에서 끝까지 시험(`ScriptedLlm`): 로그인 → 대화 "5층 사무동 공정표 만들어 줘…" → 질문지 생성 → 답 채우고 제출 → 생성(3회차 통과) → 승인 건 → 승인 → 버전 1이 Plan → 조건 미리 보기(크레인 2대) → 확정 → 승인 → 버전 2 → 버전 1로 되돌리기 → 버전 3.
- 화면 끝에서 끝까지(Playwright, 1920×1080, 씨앗 자료 + 서버의 `CHRONOS_FAKE_LLM=1`이 `ScriptedLlm`을 쓰게 함): 로그인 → Dock에서 일정판 → 간트 탭에 막대와 크리티컬 색 → 조건·규칙에서 크레인 2 입력 → 미리 보기 문구와 간트 점선 막대 → 되돌리기 → 대화창에서 생성 요청 → 질문지 열림. 각 단계 화면을 `docs/demo/shots/`에 저장.
- 제출 항목과 문서 두 가지(A4 기획서 PDF, 발표용 자료)는 `docs/contest/제출물.md`를 따른다. A4 기획서와 발표용 자료 제작은 별도 계획(`plan-5-submission`)으로 쓴다 — 이 Task는 그 원고(`기획서.md`)와 영상 시나리오 초안까지.
- `docs/demo/시나리오.md`: 5분 영상의 장면·말·시간 초안(묶음 1 범위). `docs/contest/기획서.md`: 신청 때 기획서의 문제 정의·배경을 옮기고 솔루션·Liner 활용·"형태를 새로 잡은 이유"·"만든 것 / 설계만 된 것" 표를 채운 초안. `README.md`: 실행 방법, **Liner API를 쓰는 곳**(`backend/app/llm/client.py`, `backend/app/programs/llm_settings/`, 배정 표), 구조 그림, 화면 캡처.

- [ ] **Step 1: 실패하는 시험** — 위 두 흐름을 시험으로 쓴다. 서버 시험의 끝 단언:
```python
assert [v["n"] for v in versions] == [3, 2, 1] and versions[-1]["is_plan"] is True
assert view_after_restore["finish"] == view_v1["finish"]
```
- [ ] **Step 2:** 실패 확인  - [ ] **Step 3:** 씨앗·`CHRONOS_FAKE_LLM`·시험·문서 작성  - [ ] **Step 4:** `bash scripts/check.sh` 전체 통과 + `docker compose run --rm e2e` 통과  - [ ] **Step 5:** 커밋 `test: 끝에서 끝까지 흐름과 제출 준비물`

### ◆ Checkpoint B — 실제 Liner로 한 번 돌린다

- [ ] 테일넷 주소로 띄우고, 실제 Liner 연결로 "5층 사무동 공정표" 생성을 처음부터 끝까지 돌린다(L1, L3 각 한 번). 걸린 시간·회차·비용을 개발 일지에 적는다.
- [ ] 생성이 한도 안에 통과하지 못하면 `prompts/*.md`와 `repair` 흐름을 고친다(코드 구조는 그대로). 고친 내용과 전후 결과를 일지에 적는다.
- [ ] PM에게 화면을 보여 확인받는다. PR 보고서 `~/reports/pr_YYYYMMDD_HHMM.md` (Task 14~20).
- [ ] 다음 계획서 `docs/plans/…-plan-2-change-response.md`(묶음 2)를 쓴다.

---

## 설계 대응표 (묶음 1)

| 설계 | Task |
|---|---|
| 5장 계정과 권한 | 1, 12, 13, 18, 19 |
| 6장 OS 화면 | 12 |
| 7장 프로그램 (묶음 1 대상 9개) | 13~19 |
| 8-1 스케줄표 · 8-2 간트 | 4, 16, 17 |
| 9장 하네스 네 겹 · 자원 조건 · 실시간 변경 | 3, 7, 18 (내 규칙 저장·제안은 계획 2) |
| 10-1 루프 · 10-3 승인 기준 | 10, 11 (10-2 스킬은 계획 3) |
| 11장 생성(대화+질문지), L1~L3 | 8, 9, 10, 14, 15 (L4~L5·더 자세히 풀기·생성 중 근거 검색은 계획 3) |
| 12-1 LLM 연결·모델 배정 | 5, 6, 13 |
| 15장 저장(일정·버전·변경 이력·탐색기 기본) | 4, 19 |
| 18-1 코드 규정 · 19-1 제출 준비 | 0, 20 |
| 뒤 계획으로 넘긴 것 | CPM 탭·진행 탭·실적 입력 대화·지연 기록·단축안·비교판·근거 검색·내 규칙·개발 콘솔(계획 2) / 보고서·양식·스킬·문서·다른 분야·확률·알림(계획 3) / 나머지(계획 4) |
