# ChronOS (크로노스)

일정을 만들고, 지키고, 고치는 에이전트 OS.
2026 라이너 해커톤 .EXE-THON 출품작이다. 대회 기간(2026.11.12~11.25)에 새로 만들었다.

- 화면은 OS 형태이고, 에이전트 하나가 전체를 맡는다. 에이전트는 요청마다 워크플로우를 짜고 일정 계산 도구를 차례로 쓴다.
- 일정은 대화로 만든다: 프롬프트 → 질문지 → WBS → 스케줄 → 간트 → 크리티컬 패스.
- 조건(하네스 네 겹)을 바꾸면 일정이 바로 다시 계산된다. 지연이 생기면 영향을 계산하고 만회안을 낸다.
- **날짜는 코드가 계산한다.** LLM은 구조(WBS·기간·선후 관계)를 내고 설명한다. 점검하지 않은 조건은 「자동 점검 안 됨」으로만 보인다.
- 두뇌는 **Liner Model API**, 근거 검색은 **Liner Search API·MCP** 다.

![간트차트 — 크리티컬 패스](docs/demo/shots/03-간트-크리티컬.png)

## 화면

| 조건·규칙에서 타워크레인 1대 → 2대 미리 보기 | 간트의 미리 보기 점선(옮기기 전 자리) |
|---|---|
| ![조건 미리 보기](docs/demo/shots/04-조건-크레인2-미리보기.png) | ![간트 점선](docs/demo/shots/05-간트-점선-미리보기.png) |
| **대화로 일정 만들기 → 질문지** | **바탕화면 · 주의할 일정** |
| ![질문지](docs/demo/shots/07-대화-질문지.png) | ![바탕화면](docs/demo/shots/02-바탕화면.png) |
| **대화로 지연 기록 → 지연 영향(코드 계산)** | **만회안 카드 · 비교판(같은 차트·여러 안 요약)** |
| ![지연 영향](docs/demo/shots/b2-02-대화-지연영향.png) | ![만회안](docs/demo/shots/b2-04-대화-만회안.png) |
| **CPM 요약 줄(만회 계획 달성률)** | **생산 일정 간트 — 자원별 묶음·「프레스 작업 금지」 띠** |
| ![CPM 요약](docs/demo/shots/b2-07-CPM-요약.png) | ![생산 간트](docs/demo/shots/b2-10-생산간트-자원묶음.png) |

화면은 `bash scripts/e2e-local.sh`(아래 「시험」)가 1920×1080 으로 찍었다(`E2E_SHOTS_DIR` 로 `docs/demo/shots/` 를 줄 때). 예시 일정 「5층 사무동 신축」·「가상 부품 공장 — 브래킷 BR-200 2만 개」는 가상이다. 장면 순서와 말은 `docs/demo/시나리오.md`.

## 구조

```
┌ OS 화면 (React · TypeScript · Vite) ─────────────────────────────────┐
│ 로그인 · 메뉴바 · 바탕화면 위젯 · 창 · Dock                              │
│ 시스템: 에이전트 대화 · 질문지 · 워크플로우 · 승인함 · 탐색기 · 설정 · 개발 콘솔 │
│ 업무:   스케줄 · 간트차트 · CPM · 공정률 · 비교판 · 조건·규칙 · 지연 기록    │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ REST + SSE (/api)
┌ 서버 (FastAPI · SQLite) ▼────────────────────────────────────────────┐
│ 에이전트 루프(도구 호출) ── 도구 등록부(app/tools) ── 계산 코드(app/core)  │
│ 하네스 네 겹(app/harness): 기본 규칙 · 분야 규칙 · 내 규칙 · 입력 조건      │
│ 승인 판단 · 버전 · 변경 이력(app/store) · 분야 묶음(app/domains)           │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ httpx (키는 서버에서만, 화면에는 끝 4자리)
          Liner Model API (두뇌) · Liner Search API · Liner MCP (근거)
```

## Liner API를 쓰는 곳

| 위치 | 하는 일 |
|---|---|
| `backend/app/llm/client.py` | Liner Model API(`https://platform.liner.com/api/v1/chat/completions`)를 부른다. 도구 호출·JSON 스키마 응답·`routing_strategy`. 호출마다 사용량을 `llm_calls` 에 남긴다(주고받은 글과 키는 남기지 않음). |
| `backend/app/llm/assignments.py` | **작업별 모델 배정 표.** 쓰임새마다 기본값이 있고, 화면에서 바꿀 수 있다. |
| `backend/app/programs/llm_settings/` | 「설정 > LLM 연결」 API: 연결 추가·연결 시험·모델 목록·배정 저장. 키는 Fernet 으로 암호화해 DB 에 둔다. |
| `backend/app/llm/search.py` | Liner Search API(`/tools/search/web`, `scholar`) — 근거 검색. 키는 서버에서 풀어 `x-api-key` 로만 보낸다. |
| `backend/app/tools/data/search_evidence.py` | 에이전트 도구 `evidence.search`: web·scholar 는 Search API, legal·business 는 MCP 로 찾아 근거로 보관한다(분야 검색이 실패하면 web 으로 한 번). |
| `backend/app/llm/mcp_client.py` | Liner MCP 의 `search_legal`·`search_business` — 법령·기업 근거 검색. |
| `backend/app/tools/respond/make_shortening.py` | 에이전트 도구 `shorten.make`: 만회안은 코드가 만들고, Model API(**hard**, strict JSON)로 안마다 설명과 추천을 받는다. 날짜가 든 설명은 버리고, 실패하면 코드 추천. |
| `backend/app/llm/visualization.py` | Liner Visualization API — 보고서용 그림. 그림 속 숫자를 표와 대조해 어긋나면 우리 그림으로. |

작업별 기본 배정(`assignments.py`):

| 쓰임새 | 모델 · 라우팅 전략 | 부르는 곳 |
|---|---|---|
| light | `liner-claude-router` · cost | 조건 뽑기(`generate.extract_conditions`) |
| normal | `liner-claude-router` · balanced | 에이전트 대화 루프(`app/agent/loop.py`) |
| hard | `liner-claude-router` · quality | 일정 생성 WBS·초안·고침(`app/agent/generation_steps.py`), 단축안 추천·설명(`app/tools/respond/make_shortening.py`) |
| longdoc | `liner-mark`(1M 컨텍스트) | 긴 문서용으로 둔 자리(지금은 부르는 곳 없음) |

실측 기록(모델·라우팅·도구 호출·JSON·그림 입력·MCP): `docs/dev-journal/2026-11.md`.

## 실행 (맥에서 직접)

준비: Python 3.13, Node 22 이상.

```bash
# 1) 서버 의존성(pyproject.toml 의 고정 버전 — Dockerfile 과 같은 방법)
python3.13 -m venv backend/.venv
backend/.venv/bin/python -c "import tomllib; p = tomllib.load(open('backend/pyproject.toml', 'rb'))['project']; print('\n'.join(p['dependencies'] + p['optional-dependencies']['dev']))" > backend/.venv/requirements.txt
backend/.venv/bin/pip install -r backend/.venv/requirements.txt

# 2) 화면 의존성
(cd frontend && npm ci)

# 3) 설정: .env.example 을 .env 로 복사하고 세 값을 바꾼다(관리자 아이디·비밀번호, 32자 이상 열쇠)
cp .env.example .env
set -a; source .env; set +a
export CHRONOS_DATA_DIR="$PWD/data"

# 4) (선택) 가상 예시 일정 둘 넣기 — 「5층 사무동 신축」(건설)·「가상 부품 공장 — 브래킷 BR-200 2만 개」(생산).
#    여러 번 돌려도 같다(같은 이름의 일정만 지우고 다시 만든다)
(cd backend && .venv/bin/python -m app.seed demo)

# 5) 서버(8210)와 화면(5600)
(cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8210) &
(cd frontend && CHRONOS_API_URL=http://127.0.0.1:8210 npx vite)
```

브라우저에서 `http://localhost:5600` → 첫 관리자 계정으로 로그인 → **설정 > LLM 연결**에 Liner API 키를 넣는다. 키는 화면에서만 받고, 응답에는 끝 4자리만 나온다.

Docker 로도 띄울 수 있다(선택): `.env` 를 만든 뒤 `docker compose up`.

## 시험

```bash
bash scripts/check-local.sh   # 비밀 검사 · 줄 수 · ruff · pytest · eslint · tsc · vitest · vite build
bash scripts/e2e-local.sh     # 끝에서 끝까지(Playwright, 1920×1080)
```

처음 한 번 크로미움을 `frontend/.playwright-browsers` 에만 받는다(맥 전체 캐시를 건드리지 않음 — 스크립트도 같은 자리를 쓴다):

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" PLAYWRIGHT_SKIP_BROWSER_GC=1 npx playwright install chromium
```

단계 화면은 기본으로 임시 폴더에 찍힌다. 위의 캡처를 다시 찍을 때만 시험 파일 하나씩(씨앗 그대로에서) `E2E_SHOTS_DIR="$PWD/docs/demo/shots" bash scripts/e2e-local.sh e2e/demo.spec.ts` · `… e2e/bundle2.spec.ts`. 둘을 한 번에 돌리면 묶음 2 가 먼저 돌아 일정을 바꾸므로(끝에 사무동 일정을 버전 2 내용으로 되돌린다) 묶음 1 화면이 씨앗 그대로와 달라질 수 있다.

- 서버 끝에서 끝까지(`backend/tests/e2e/test_generate_flow.py`): 대화 → 질문지 → 생성(3회차 통과) → 승인 → 조건 미리 보기(크레인 2대) → 확정·승인 → 버전 1로 되돌리기. LLM 은 대본 가짜(`ScriptedLlm`).
- 서버 끝에서 끝까지 묶음 2(`backend/tests/e2e/test_bundle2_flow.py`): 씨앗 두 일정 → 대화 "지상 골조가 비 때문에 3일 늦어졌어"(고른 작업 A1210) → `schedule.find` → `delay.record`(준공 +3일) → "만회 계획 만들어 줘" → `shorten.make`(목표 도달 안 있음·위반 0) → 추천 안 제출·승인 → 버전 3·지연 반영됨 → 공정률 · 개발 콘솔 두 턴 · 생산 일정은 자원별 간트. LLM 은 앱 안 가짜(`app/llm/fake.py` 의 묶음 2 대본).
- 화면 끝에서 끝까지(`frontend/e2e/demo.spec.ts` 묶음 1, `frontend/e2e/bundle2.spec.ts` 묶음 2 — 지연 → 영향 → 만회안 → 비교판 → 승인 → CPM·공정률 → 개발 콘솔 → 생산 간트): `e2e-local.sh` 가 임시 폴더에 예시 일정을 넣고, 서버를 `CHRONOS_FAKE_LLM=1`(시험·시연 전용 가짜 Liner, `backend/app/llm/fake.py`)로 8310·5700 포트에 띄워 돈다. 이 시험의 흐름은 Liner 를 부르지 않고 `data/` 를 건드리지 않는다. 가짜는 Chat Completions(`LlmClient`)만 바꾼다 — 근거 검색·MCP·연결 시험·시각화는 불리면 그대로 Liner 로 나간다.

## 문서

| 위치 | 내용 |
|---|---|
| `docs/design/` | 설계 문서 |
| `docs/plans/` | 구현 계획서 |
| `docs/contest/` | 대회 규정 체크리스트, 제출물, 기획서 원고 |
| `docs/demo/` | 데모 영상 시나리오, 화면 캡처 |
| `docs/dev-journal/` | 개발 일지(Liner 실측) |

## 만드는 방법

AI 코딩 도구(Claude Code)를 써서 만들었다. 예시 자료(사람·회사·현장)는 전부 가상이다.
