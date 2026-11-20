# ChronOS 계획 3 — 대화 첨부 · 자료함(벡터 검색) · 모델 고르기 · 정보 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대화에 그림·표·엑셀·PDF·문서를 붙이면 에이전트가 읽고 답하며, 그 파일이 자료함에 「종류·공종·현장·시기·출처」로 분류·임베딩돼 회사 자료로 쌓이고, 에이전트가 다른 대화에서도 뜻으로 찾아 쓴다. 대화마다 모델을 고르고, 그림이 붙은 턴은 「그림 읽기」 모델이 답한다. 엑셀 공정표는 물어보고 일정 초안으로 가져오고, 기상청 공공데이터로 날씨 근거를 붙인다.

**Architecture:** 원본은 `data/files/`, 파일 정보·조각·분류·대화 연결은 SQLite(조각은 FTS5 낱말 검색), 벡터는 **Qdrant 서버**(맥 직접, `127.0.0.1:6333`, 자료 `data/qdrant/`). 받기 → 글 뽑기(요청 안) → 임베딩·분류(서버 안 뒤 작업 줄) 차례. 검색은 뜻(Qdrant) + 낱말(FTS5)을 RRF 로 합친다. 판단(공정표인지·빈 칸 묻기/추정·분류 값)은 에이전트, 계산(날짜·통계·행 수)은 코드.

**Tech Stack:** 계획 1·2 와 같고 새 의존성: `qdrant-client`(백엔드, 시험은 내장 `:memory:`), `pypdf`, `openpyxl`. 맥용 Qdrant 실행 파일(운영만). 그림 줄이기는 브라우저 canvas.

**Spec:** `docs/superpowers/specs/2026-11-20-chat-files-library-design.md`(PM 승인 11-20). 기존 결정: 계획 1·2 의 progress·보고서.

**이 계획의 범위:** 설계서 전부(PM: "전부 만든다"). Task 번호는 계획 2 에 이어 47부터. 시작 조건: 계획 2 Task 39(대화 카드) 커밋 — 끝남.

## 병렬 묶음

| 묶음 | 작업 | 선행 |
|---|---|---|
| G5 | 47 표·파일 받기·글 뽑기 | — |
| G6 | 48 임베딩·Qdrant·검색 · 51 모델 고르기·그림 읽기·임베딩 배정(서버) · 52 정보 API·날씨 도구 · 54 화면 시안 | 47 |
| G7 | 49 분류·요약 · 50 세션 기억·파일 도구·그림 턴 · 53 공정표 가져오기 | 48(49·50), 47(53) |
| G8 | 55 대화 첨부·모델 ▾ · 56 자료함 · 57 설정 두 곳 | 54 PM 고름 + 49·50·51·52 |
| G9 | 58 끝에서 끝까지·운영 문서 | 55~57 |

## Global Constraints

계획 1·2 의 제약을 그대로 잇는다(`.superpowers/sdd/2026-11-20-chronos-plan-2-bundle2/global-constraints.md`). 그중 이 계획에서 특히:

- **판단은 에이전트, 계산은 코드 [PM 11-20].** 공정표인지, 빈 칸을 물을지 추정할지, 분류 값은 에이전트가 판단한다. 날짜·여유·통계·행 수는 코드만 계산한다. LLM 이 낸 글의 날짜는 계산에 쓰지 않는다.
- **Docker 없음 [PM 11-20].** 시험·점검은 맥에서 직접(`scripts/check-local.sh`). PM 앱은 `~/projects/chronos-serve`(8210/5600) — 건드리지 않는다. 시험은 다른 포트·임시 data 폴더.
- 비밀값: LLM·정보 API 키는 Fernet 암호문·끝 4자리만. 로그·추적·자료·근거에 키를 남기지 않는다. 공공데이터 키는 질의 `serviceKey` 로만.
- **실측은 PM 이 직접**(서브에이전트는 `.env` 를 못 읽음): 실측 스크립트는 요청 수 상한·키 지우기·DB 읽기 전용, 서브에이전트는 쓰기만 하고 멈춘다.
- 첨부 한도: **파일당 50MB · 한 번에 10개** [PM]. 보는 범위: **지금은 회사 전체** [PM]. 에이전트는 **볼 수 있는 파일 전부**를 찾되 지금 대화에 붙인 파일을 먼저 [PM].
- 분류: **축 고정(종류·공종·현장·시기·출처), 값은 에이전트가 늘림**, 바로 저장·언제든 고침 [PM].
- 공정표 파일: **먼저 묻고 가져오기**, 빈 칸은 에이전트 판단(질문지 또는 추정), 초안은 승인함 [PM].
- 그림이 붙은 턴은 「그림 읽기」(`vision`) 배정 모델 [PM]. 임베딩 모델은 「임베딩」(`embedding`) 배정 [PM].
- 새 표·칸은 **Task 47 만** `tables.py` 에 정의(Task 21 규칙과 같은 방식). 화면은 프로그램끼리 import 금지, 공용은 `frontend/src/shared/`.
- 도구: 한 파일에 하나, 입력 `extra="forbid"`, 실패는 `ToolError(한국어)`, 이름 점 표기(`files.read`), 지시는 `guides/<기능>.md`.
- 화면 검수 5항목(넘침 없음·긴 목록은 분류+찾기·기계 출력은 묶어 보기·FHD 스크린샷·두 테마).
- 작업 등급: `[fable]` 은 11-23 13:00 전에는 opus + effort xhigh.

## Review Focus

1. **같은 파일을 두 대화에서 올림** — 한 벌만 저장(sha256), 둘 다 그 파일을 기억하고 다시 임베딩하지 않는다. → Task 47 `test_same_content_twice_is_one_file_two_links`.
2. **한글 이름·CP949 CSV·암호 걸린 PDF/xlsx** — 이름은 그대로 보이고, CP949 는 읽고, 암호 파일은 `failed`(「암호가 걸린 파일이라 읽을 수 없습니다」)로 남고 대화는 계속된다. → Task 47 `test_cp949_csv_and_korean_name`, `test_encrypted_pdf_fails_politely`.
3. **Qdrant 가 꺼진 채 파일을 올림** — 업로드·대화는 되고(낱말 검색), 서버가 돌아오면 다시 넣기. → Task 48 `test_qdrant_down_keeps_keyword_search_and_requeues`.
4. **지운 파일을 붙였던 대화가 다시 말함** — 맥락 줄 「(지워짐)」, `files.read` 는 "지워진 파일입니다", 오류로 멈추지 않음. → Task 50 `test_deleted_file_in_session_context`.
5. **임베딩 모델을 바꾸는 중에 새 파일이 들어옴** — 두 컬렉션 모두에 들어가고, 바꾸기 끝난 뒤 검색에 나온다. → Task 48 `test_upload_during_reindex_lands_in_both`.

---

### Task 47: 표 · 파일 받기 · 글 뽑기 · 낱말 검색 [opus] · G5

**Files:**
- Modify: `backend/app/store/tables.py`(새 표·칸 — 이 계획의 유일한 표 작업), `backend/pyproject.toml`(`pypdf`, `openpyxl`, `qdrant-client` 정확한 버전), `backend/app/llm/assignments.py`(`Purpose` 에 `"vision"`, `"embedding"` 더함 + `DEFAULT_ASSIGNMENTS`: vision=(`liner-claude-router`,`balanced`), embedding=(`openai/text-embedding-3-small`, None))
- Create: `backend/app/files/{__init__,extract,chunk,kinds}.py`, `backend/app/store/files.py`, `backend/app/programs/files/{__init__,router,service,schemas}.py`
- Test: `backend/tests/files/test_extract.py`, `backend/tests/store/test_files.py`, `backend/tests/programs/test_files_api.py`, `backend/tests/fixtures/files/`(작은 가상 파일들: png·csv(UTF-8·CP949)·xlsx·pdf(글·스캔 흉내·암호)·docx·hwpx·txt)

**Interfaces:**
- Produces(표): `files(id, sha256 unique, name, ext, kind, size, status, reason, uploaded_by, uploaded_at, pages, summary, deleted_at)` · `file_chunks(id, file_id, seq, locator, text)` + FTS5 가상 표 `file_chunks_fts(text)` · `file_axes(file_id, axis, value)` · `axis_values(axis, value, created_at, is_new)` · `chat_session_files(session_id, file_id, attached_at)` · `info_connections(id, name, preset, base_url, secret_ciphertext, secret_last4, status, checked_at)` · `reindex_jobs(id, model, collection, total, done, status, started_at, finished_at)` · `chat_sessions` + `model_connection_id int|null, model_name str|null, model_routing str|null`. `status ∈ {received, extracted, indexed, classified, failed}`. `kind ∈ {image, table, sheet, pdf, doc, text}`.
- Produces(코드): `files.kinds.kind_of(name, head: bytes) -> str | None`(받지 않으면 None) · `files.extract.extract(path, kind) -> Extracted(text_parts: list[tuple[locator, str]], pages: int, scanned: bool)` · `files.chunk.chunks(parts, size=800, overlap=100) -> list[Chunk(seq, locator, text)]` · `store.files.{save_upload(session, data: bytes, name, user) -> FileRow, link(session, chat_id, file_id), session_files(session, chat_id) -> list[FileRow], keyword_search(session, query, limit, file_ids=None) -> list[ChunkHit], get(session, file_id), soft_delete(session, file_id, user), purge(session, file_id)}`.
- API: `POST /api/files`(multipart `files[]`, 선택 `chat_id`) → `{items:[{file_id, name, kind, status, reason}]}` · `GET /api/files/{id}` · `GET /api/files/{id}/raw`(원본) · `GET /api/files/{id}/preview?page=` · `DELETE /api/files/{id}`(올린 사람·관리자, 숨김) · `DELETE /api/files/{id}?purge=1`(관리자).
- 한도: 파일당 50MB → 413 「파일이 너무 큽니다(50MB까지)」, 11개 이상 → 422 「한 번에 10개까지 올릴 수 있습니다」, 안 받는 확장자 → 422(설계 5-1 표의 안내 글).
- 뽑기 규칙(설계 5-1 표 그대로): csv·tsv 앞 200행, xlsx 시트별 앞 200행(값만), pdf 앞 300쪽(글이 쪽당 평균 20자 미만이면 `scanned`), docx·hwpx zip XML, txt·md UTF-8→CP949, 그림은 글 없음(설명은 Task 49).

- [ ] **Step 1: 실패하는 시험**
```python
def test_same_content_twice_is_one_file_two_links(client, admin, chat_a, chat_b): ...  # 같은 바이트 둘 → file_id 같음, chat_session_files 2줄, extract 1번
def test_cp949_csv_and_korean_name(client, admin): r = upload("공정표_A현장.csv", cp949_bytes); assert r["name"] == "공정표_A현장.csv" and "골조" in chunks_text(r["file_id"])
def test_encrypted_pdf_fails_politely(client, admin): r = upload("locked.pdf", ...); assert r["status"] == "failed" and r["reason"] == "암호가 걸린 파일이라 읽을 수 없습니다"
def test_scanned_pdf_is_kept_but_marked(): ...  # status extracted, reason "스캔 문서라 글을 읽을 수 없습니다(OCR 미지원)"
def test_limits(client, admin): ...  # 50MB+1 → 413, 11개 → 422, .hwp → 422 "PDF 로 저장해 주세요"
def test_keyword_search_finds_exact_token(session): ...  # "C24" 가 든 조각이 1위
def test_soft_delete_hides_from_search_but_keeps_row(session): ...
def test_existing_db_gets_new_tables_and_columns(tmp_path): ...  # 계획 2 모양 DB → init_db → 새 표·chat_sessions 새 칸
```
- [ ] **Step 2: 실패 확인** — `cd backend && .venv/bin/python -m pytest -q tests/files tests/store/test_files.py tests/programs/test_files_api.py` → FAIL(모듈 없음)
- [ ] **Step 3: 구현** — 위 Interfaces. 원본 경로 `data/files/<sha[:2]>/<sha>`. 받기 응답은 뽑기까지 끝낸 상태(`extracted`/`failed`)로 돌려주고, 임베딩·분류는 Task 48·49 의 뒤 작업 줄에 넣는다(지금은 줄 넣기 함수 자리만: `files.jobs.enqueue(file_id)` — Task 48 이 채움, 이 작업에서는 아무것도 하지 않는 함수).
- [ ] **Step 4: 통과 확인** — 위 명령 + 전체 + ruff + check_lines
- [ ] **Step 5: 커밋** `feat: 파일 받기·글 뽑기·낱말 검색(계획 3 표)`

### Task 48: 임베딩 · Qdrant · 뜻+낱말 검색 · 다시 넣기 [fable] · G6

**Files:**
- Create: `backend/app/llm/embeddings.py`, `backend/app/files/{vectors,search,jobs}.py`, `backend/scripts/probe_liner_embeddings.py`
- Modify: `backend/app/main.py`(시작 때 뒤 작업 줄 시작·종료 — 몇 줄), `backend/app/config.py`(`CHRONOS_QDRANT_URL`, 기본 `http://127.0.0.1:6333`)
- Test: `backend/tests/files/test_vectors.py`, `test_search.py`, `test_jobs.py`, `backend/tests/llm/test_embeddings.py`

**Interfaces:**
- Consumes: Task 47 `store.files.*`, `assignments.resolve(session, "embedding")`
- Produces: `llm.embeddings.embed(session, texts: list[str]) -> list[list[float]]`(배정 모델, 64개씩, 실패 `EmbedFailed(code)` — Task 27 오류 code 와 같은 이름) · `files.vectors.Store(url | ":memory:")` — `collection_for(model, dim) -> str`(`chunks__<model 정리>__<dim>`), `upsert(collection, points)`, `search(collection, vector, limit, filter: dict[axis, list[value]] | None) -> list[(chunk_id, score)]`, `available() -> bool` · `files.search.search(session, query, *, limit=8, filters=None, prefer_file_ids=None) -> list[Hit(file_id, chunk_id, locator, text, score, source: "vector"|"keyword"|"both")]`(RRF k=60, `prefer_file_ids` 는 점수 ×1.5) · `files.jobs` — `enqueue(file_id)`, `enqueue_reindex(model)`, 작업 하나씩 차례로, 실패하면 30초 뒤 다시(최대 3번), 서버 시작 때 남은 줄을 다시 읽음.
- 규칙(설계 4·5-1 [내 판단]): Qdrant 가 안 되면 뜻 검색만 끄고 낱말 검색, 파일은 `extracted` 로 두고 「다시 넣기」 줄에 남김(시작 때·5분마다 `available()` 확인 뒤 넣기). 임베딩 실패도 같음(칩 「뜻 검색 준비 안 됨」 = `status extracted` + `reason`). 임베딩 모델을 바꾸면 `reindex_jobs` 한 줄 → 새 컬렉션에 전부 다시 → 그동안 검색은 옛 컬렉션, 새로 들어온 파일은 두 컬렉션 모두 → 끝나면 바꾸고 옛 컬렉션 지움.
- **Step 0(PM 실측):** `probe_liner_embeddings.py` — `GET /v1/models` 1번(임베딩 지원 모델 목록), `POST /v1/embeddings` 1번(문장 2개). 출력: 모델 이름들·차원·걸린 시간. 서브에이전트는 쓰고 멈춘 뒤 PM 명령을 돌려준다. 안 되면 이 작업 멈춤.

- [ ] **Step 0:** 실측 스크립트 → PM 실행 → 결과를 `docs/dev-journal/2026-11.md`
- [ ] **Step 1: 실패하는 시험**(`httpx.MockTransport` + Qdrant `:memory:`)
```python
async def test_meaning_search_beats_keyword_for_paraphrase(): ...  # "겨울 콘크리트" → "동절기 타설" 조각 1위(가짜 임베딩: 뜻 같은 글은 같은 벡터)
async def test_keyword_still_finds_exact_token_when_vector_misses(): ...  # "SNET" 은 낱말 쪽에서 나옴, source "keyword"
async def test_filters_by_axis_values(): ...  # filters={"현장":["A현장"]} 밖 파일은 안 나옴
async def test_qdrant_down_keeps_keyword_search_and_requeues(): ...  # available False → 검색 결과 source 모두 keyword, 파일 status extracted, 다시 넣기 줄 1
async def test_embed_failure_leaves_extracted_with_reason(): ...  # reason "뜻 검색 준비 안 됨"
async def test_reindex_switches_after_done(): ...  # 진행 중 search 는 옛 컬렉션, 끝나면 새 컬렉션, 옛 것 지움
async def test_upload_during_reindex_lands_in_both(): ...
async def test_no_key_in_logs_or_errors(caplog): ...
```
- [ ] **Step 2~4:** 실패 확인 → 구현 → 통과(전체·ruff·check_lines)
- [ ] **Step 5: 커밋** `feat: 임베딩과 Qdrant 뜻 검색·다시 넣기`

### Task 49: 분류 · 요약 · 그림 설명 · 값 합치기 제안 [opus] · G7

**Files:**
- Create: `backend/app/files/classify.py`, `backend/app/agent/prompts/classify_file.md`, `backend/tests/files/test_classify.py`
- Modify: `backend/app/files/jobs.py`(임베딩 뒤 분류 단계 부르기 — 한 줄), `backend/app/programs/files/{router,service,schemas}.py`(축 고침·값 목록·합치기 API)

**Interfaces:**
- Consumes: Task 47·48, `LlmClient.chat("light", …, json_schema=…)`, 그림이면 `chat("vision", [image_url 메시지])`
- Produces: `files.classify.classify(session, file_id) -> Classified(axes: dict[str, list[str]], summary: str, new_values: list[(axis, value)])` — 지금 값 목록(축마다)을 지시에 넣고 strict JSON 으로 받는다. 값은 앞뒤 공백·중복 정리만 코드가(뜻 판단은 에이전트). 그림은 설명 글(최대 600자)을 조각 하나로 저장·임베딩. 한 줄 요약 120자.
- API: `GET /api/files?q=&{axis}=값&page=` 목록(필터·찾기) · `GET /api/files/axes` → `{축: [{value, count, is_new}]}` · `PATCH /api/files/{id}/axes {축: [값]}`(누구나, 사람이 고친 값은 그대로 저장) · `GET /api/files/merge-suggestions`(관리자: 한 축 값 30개 넘거나 비슷한 이름 — 비슷함은 에이전트 판단, 하루 한 번 뒤 작업으로 만들고 저장) · `POST /api/files/merge {axis, from: [값], to: 값}`(관리자).
- 대화에 남길 한 줄(사건 `card{kind:"file_saved", file_id, name, axes}`): 「자료함에 넣음: 시방서·골조·A현장 [고치기]」.

- [ ] **Step 1: 실패하는 시험**
```python
async def test_reuses_existing_values(): ...  # 값 목록에 "시방서" 있음 → 같은 값, new_values []
async def test_new_value_is_marked_new(): ...  # axis_values.is_new True, GET /axes 에 is_new
async def test_image_gets_a_description_chunk_with_vision_purpose(): ...  # 부른 purpose == "vision", 조각 1개
async def test_llm_failure_keeps_file_usable(): ...  # status indexed 유지, reason "분류하지 못했습니다", 대화 카드 없음
def test_patch_axes_and_list_filters(client, admin): ...
def test_merge_moves_files_and_drops_old_value(client, admin): ...
```
- [ ] **Step 2~4** · **Step 5: 커밋** `feat: 자료 분류·요약·그림 설명·값 합치기`

### Task 50: 세션 기억 · 파일 도구 · 그림 턴 [fable] · G7

**Files:**
- Create: `backend/app/tools/data/{read_file,search_files}.py`, `backend/app/agent/prompts/guides/files.md`, `backend/tests/tools/test_file_tools.py`, `backend/tests/agent/test_image_turn.py`
- Modify: `backend/app/agent/context.py`(「이 대화에 붙인 파일」 줄), `backend/app/agent/loop.py`(그림 턴 모델 바꾸기·`image_url` 끼우기 — 줄 수 늘림 30줄 안), `backend/app/programs/chat/schemas.py`(`MessageIn.file_ids: list[int] = []`, 최대 10), `backend/app/llm/client.py`(`chat(..., purpose_override: Assignment | None = None)` — 대화 모델 고름(Task 51)·그림 읽기용)

**Interfaces:**
- Consumes: Task 47 `session_files`, Task 48 `search`, Task 51 `chat_model(session, chat_id) -> Assignment | None`
- Produces:
  - 맥락 줄(매 턴): `이 대화에 붙인 파일: #12 시방서_A현장.pdf (pdf · 시방서·골조 · 분류됨) "콘크리트 양생 최소 7일…" | #13 1103.jpg (image · 현장 사진) …` — 최대 20개, 넘으면 최근 20 + 「외 n개」, 지운 파일은 「(지워짐)」.
  - 도구 `files.read {file_id: int, query: str | null, page: int | null, image: bool = false}` → `{name, kind, status, parts: [{locator, text}]}`(query 있으면 그 파일 안에서 검색 상위 5, 없으면 앞 5조각 또는 page). 지운 파일 → ToolError 「지워진 파일입니다」. `image=true` 면 이 단계부터 턴 끝까지 「그림 읽기」 모델 + 그림을 `image_url`(줄인 사본, data URI)로 다음 메시지에 끼움.
  - 도구 `files.search {query: str(1..200), filters: {axis: [value]} | null, limit: int(1..10)=5}` → `{hits: [{file_id, name, locator, text(≤400), axes}]}` — 이 대화에 붙인 파일 우선.
  - 그림 턴: 이번 `MessageIn.file_ids` 에 kind image 가 있으면 그 턴 모든 LLM 호출이 `vision` 배정, 첫 사용자 메시지에 그림들(`image_url`). 대화 모델을 골랐어도 그 턴만, 사건 `notice{text: "그림이 있어 그림 읽기 모델(<모델>)로 답합니다."}`. 다음 턴부터는 그림 설명 글만 맥락에.
  - `guides/files.md`: 파일 내용을 말할 때 출처 「파일 이름 · 쪽/시트」를 붙인다, 읽지 않은 내용은 말하지 않는다, 먼저 이 대화 파일, 모자라면 `files__search`.

- [ ] **Step 1: 실패하는 시험**(ScriptedLlm)
```python
async def test_context_lists_session_files_with_status(): ...
async def test_deleted_file_in_session_context(): ...  # 맥락 「(지워짐)」, files.read → "지워진 파일입니다", 턴은 끝까지 감
async def test_read_file_returns_locators(): ...  # parts[0]["locator"] == "3쪽"
async def test_search_prefers_session_files(): ...
async def test_image_turn_uses_vision_and_notice(): ...  # 부른 purpose 모두 vision, notice 사건, 메시지에 image_url
async def test_next_turn_uses_description_only(): ...  # 다음 턴 메시지에 image_url 없음, 설명 글 있음
async def test_read_image_true_switches_from_that_step(): ...
async def test_message_with_11_files_is_refused(): ...  # 422
```
- [ ] **Step 2~4** · **Step 5: 커밋** `feat: 대화에 붙인 파일 기억·파일 도구·그림 턴`

### Task 51: 모델 고르기 · 그림 읽기 · 임베딩 배정(서버) [opus] · G6

**Files:**
- Modify: `backend/app/llm/assignments.py`(두 쓰임새 기본값은 Task 47 이 넣음 — 여기서는 `chat_model`), `backend/app/programs/llm_settings/{router,service,schemas}.py`(배정 표에 vision·embedding, 임베딩 모델 목록 거르기, 임베딩 바꾸면 다시 넣기), `backend/app/programs/chat/{router,service,schemas}.py`(대화 모델 칸)
- Test: `backend/tests/programs/test_llm_settings_api.py`(더함), `backend/tests/programs/test_chat_model_api.py`

**Interfaces:**
- Produces: `assignments.chat_model(session, chat_id) -> Assignment | None` · `PUT /api/chats/{id}/model {connection_id, model, routing_strategy | null}` / `DELETE`(기본으로) · `GET /api/chats/{id}` 에 `model: {connection_id, model, routing_strategy} | null` · `GET /api/llm/models?for=chat|vision|embedding`(연결의 `/v1/models` 를 endpoints 로 거름 — 임베딩은 `/v1/embeddings` 지원만) · `PUT /api/llm/assignments` 가 `embedding` 을 바꾸면 `{reindex: {job_id, total}}` 를 함께 돌려주고 Task 48 `enqueue_reindex` · `GET /api/files/reindex` → 진행(`total, done, status`).
- 대화 모델은 에이전트 루프의 대화 호출(`normal`)만 바꾼다(생성 `hard`·분류 `light`·그림 `vision` 은 배정 그대로) [설계 5-5].

- [ ] **Step 1: 실패하는 시험**
```python
def test_assignments_include_vision_and_embedding(client, admin): ...
def test_embedding_models_are_filtered(client, admin): ...  # endpoints 에 /v1/embeddings 있는 것만
def test_changing_embedding_starts_reindex(client, admin): ...
def test_chat_model_override_only_for_normal(client, user, ...): ...  # 생성 쪽 purpose hard 는 배정 그대로
def test_other_users_chat_model_is_403(client, user2): ...
```
- [ ] **Step 2~4** · **Step 5: 커밋** `feat: 대화 모델 고르기·그림 읽기·임베딩 배정`

### Task 52: 정보 API 연결 · 날씨 도구 [opus] · G6

**Files:**
- Create: `backend/app/info/{__init__,kma,places}.py`(`places.py` = 내장 위치 표 약 30곳: 이름·ASOS 지점·예보 격자 nx·ny), `backend/app/programs/info_settings/{__init__,router,service,schemas}.py`, `backend/app/tools/data/weather.py`, `backend/app/agent/prompts/guides/weather.md`, `backend/scripts/probe_kma.py`
- Test: `backend/tests/info/test_kma.py`, `backend/tests/tools/test_weather_tool.py`, `backend/tests/programs/test_info_settings_api.py`

**Interfaces:**
- API(관리자): `GET/POST /api/info/connections`, `PATCH/DELETE /api/info/connections/{id}`, `POST /api/info/connections/{id}/test`(ASOS 1번) — 모양은 LLM 연결 API 와 같다(끝 4자리).
- `info.kma.asos_daily(conn, stn, start, end) -> list[DayObs(date, tavg, tmin, rain_mm)]` · `info.kma.short_forecast(conn, nx, ny) -> list[DayFcst(date, tmin, tmax, pop)]` · 실패는 Task 27 과 같은 code·안내 글.
- 도구 `info.weather {place: str, kind: "history"|"forecast", month: int(1..12) | null, years: int(1..10)=10}` — place 는 `places` 에 있는 이름만(없으면 ToolError 「모르는 위치입니다: X — 가까운 시·도 이름을 알려 주세요」). history: 지난 n년 그 달 → **코드가** `{tavg, tmin_avg, freezing_days, rain_days(≥1mm), max_rain_mm}`(해 평균) 계산 → 근거로 저장(Task 27 `store.evidence`, 출처 「기상청 ASOS 일자료 · 공공데이터포털」, 기준 기간 글) + `card{kind:"evidence", …}`. forecast: 3일 하루별. 숫자는 가정 근거로만(지침·도구 설명에 명시). 한도: 요청당 3번(근거 검색과 합산 안 함 — 따로 셈).
- **Step 0(PM 실측):** `probe_kma.py` — ASOS 1번(서울 108, 지난 12월 일주일), 단기예보 1번(서울 격자 60·127). 서브에이전트는 쓰고 멈춤. PM 은 키를 설정 화면에서 넣기 전이므로 실측 스크립트는 키를 **명령줄 환경 변수 `KMA_SERVICE_KEY`** 로 받는다(출력·기록에 남기지 않음).

- [ ] **Step 0:** 실측 → 일지
- [ ] **Step 1: 실패하는 시험**
```python
async def test_history_stats_are_computed_by_code(): ...  # 가짜 ASOS 일자료 → freezing_days 등 손 계산과 같음
async def test_unknown_place_is_refused(): ...
async def test_weather_saved_as_evidence_with_source(): ...
async def test_service_key_never_logged(caplog): ...
def test_info_connection_crud_shows_last4_only(client, admin): ...
```
- [ ] **Step 2~4** · **Step 5: 커밋** `feat: 정보 API 연결과 날씨 근거 도구`

### Task 53: 공정표 파일 가져오기 [fable] · G7

**Files:**
- Create: `backend/app/files/schedule_import.py`, `backend/app/tools/generate/import_schedule.py`, `backend/app/agent/prompts/{import_detect,import_map}.md`, `backend/app/agent/prompts/guides/import.md`, `backend/tests/files/test_schedule_import.py`, `backend/tests/tools/test_import_tool.py`
- Modify: `backend/app/agent/generation.py`(가져온 액티비티를 "고정값"으로 받는 자리 — 기존 생성 루프에 `fixed: ImportedRows | None` 인자, 줄 수 늘림 40줄 안)

**Interfaces:**
- Consumes: Task 47 뽑은 표, 기존 생성 루프(`generation.generate`)·질문지 도구·첫 저장 승인 길
- Produces:
  - 판단(에이전트, `normal`, strict): `detect(table_preview) -> {is_schedule: bool, reason}` — 표가 공정표인지. 카드 숫자(행 수·열 이름)는 코드가 센다.
  - 카드 `card{kind:"schedule_file", file_id, sheet, rows, columns_found: [..], missing: [..]}` + [일정 초안으로 가져오기](대화에 「이 파일로 일정 초안을 만들어 줘(#id)」 를 보냄).
  - 도구 `schedule.import {file_id, sheet: str | null}`: 에이전트가 열 대응(strict JSON `{id_col, name_col, wbs_col, duration_col, pred_col, start_col, finish_col}` 각 null 가능) → **코드가** 행을 액티비티로(파일 값 그대로, 기간·선행 문자열은 기존 파서) → 빈 칸은 에이전트가 판단: 사람에게 물을 것은 기존 질문지 도구로(질문지 열림), 아니면 생성 루프가 추정(같은 점검·고침, 추정한 칸 출처 「추정」) → 파일의 시작·끝 날짜를 제약으로 둘지도 에이전트 판단(SNET/FNLT) → 첫 저장 길(승인함).
  - `guides/import.md`: 위 흐름, "먼저 묻고 가져온다", 날짜는 계산하지 않는다.

- [ ] **Step 1: 실패하는 시험**(ScriptedLlm)
```python
async def test_detect_card_counts_rows_by_code(): ...  # 120행 → rows 120, missing ["기간"]
async def test_non_schedule_table_gets_no_card(): ...
async def test_import_keeps_file_values_and_marks_estimates(): ...  # 파일에 기간 있는 행은 그대로, 빈 행은 source "추정"
async def test_import_asks_when_agent_decides_to(): ...  # 에이전트가 ask → 질문지 사건
async def test_import_goes_to_approvals(): ...
async def test_llm_dates_are_ignored(): ...  # 모델이 날짜를 내도 일정 날짜는 코드 계산
```
- [ ] **Step 2~4** · **Step 5: 커밋** `feat: 공정표 파일을 물어보고 일정 초안으로 가져오기`

### Task 54: 화면 시안 — 대화 첨부 · 자료함 · 설정 [opus] · G6

**Files:** Create `docs/design/mockups/{ChatAttach,Library,SettingsFiles}.dc.html`(시안마다 안 2~3개를 한 파일 안 탭으로), `docs/design/mockups/plan3-mockups.md`(안마다 한 줄 차이점)
**Produces:** 대화 첨부(입력칸 📎·끌어 놓기·칩 상태 5종·말풍선 칩·컨텍스트 「이 대화의 파일」·창 위 「모델 ▾」·그림 턴 안내 줄), 자료함(축 필터·찾기·목록·상세 미리 보기·「새」 표시·관리자 합치기 제안), 설정(배정 표 「그림 읽기」·「임베딩」 줄과 바꾸기 확인 창·다시 넣기 진행률, 「정보 API 연결」 카드). 기존 시안(`docs/design/mockups/*.dc.html`)과 같은 토큰·글꼴·모양, 밝은·어두운.
- [ ] **Step 1:** 외부 사례 조사(Claude·ChatGPT 첨부, Google Drive·Notion 필터) 한 쪽 메모
- [ ] **Step 2:** 시안 작성 → FHD 스크린샷
- [ ] **Step 3:** **PM 에게 보이고 고름 받기**(컨트롤러가 전달) — 고른 안을 `plan3-mockups.md` 에 적음
- [ ] **Step 4: 커밋** `docs: 계획 3 화면 시안(PM 고름)`

### Task 55: 대화 첨부 · 모델 ▾ · 이 대화의 파일 [opus] · G8

**Files:** Create `frontend/src/programs/chat/{AttachButton,FileChips,ModelPicker}.tsx`, `frontend/src/shared/files/{filesApi.ts,resizeImage.ts,FileChip.tsx}`, `frontend/src/programs/chat/cards/{FileSavedCard,ScheduleFileCard}.tsx` + 시험; Modify `frontend/src/programs/chat/{Composer.tsx,Chat.tsx,ContextPanel.tsx,chatApi.ts,chatStore.ts}`, `cards/index.tsx`
**Interfaces:** Consumes Task 47 `POST /api/files`, Task 50 `MessageIn.file_ids`·`notice`, Task 51 대화 모델 API·`GET /api/llm/models?for=chat`, Task 49 `file_saved` 카드, Task 53 `schedule_file` 카드, Task 54 고른 시안. Produces: `resizeImage(file, maxEdge=1568) -> Blob`(png·jpg·webp, 원본도 함께 올림), 칩 상태 `올리는 중·읽는 중·저장됨 · <축 값>·뜻 검색 준비 안 됨·실패 — <까닭>`, 붙여넣기(그림)·끌어 놓기·📎, 한도 넘으면 보내기 전 안내.
- [ ] **Step 1: 실패하는 시험** — 붙여넣기·끌어 놓기·📎로 칩 생김 / 11개면 「한 번에 10개까지」 / 그림은 줄여서 올림(긴 변 1568) / 보낼 때 `file_ids` / 칩 상태 바뀜(폴링 `GET /api/files/{id}` 2초, `classified`·`failed` 면 멈춤) / 모델 ▾ 고르면 `PUT /api/chats/{id}/model` / notice 줄 / 컨텍스트 패널 목록·「(지워짐)」 / 두 카드
- [ ] **Step 2~4**(화면 검수: 480×760·1560×900·360폭, 두 테마) · **Step 5: 커밋** `feat: 대화 첨부와 모델 고르기`

### Task 56: 자료함 프로그램 [fable] · G8

**Files:** Create `frontend/src/programs/library/{index.ts,Library.tsx,FacetBar.tsx,FileList.tsx,FileDetail.tsx,Preview.tsx,MergeSuggestions.tsx,libraryApi.ts,library.css}` + 시험; Modify `frontend/src/programs/index.ts`(등록, 색 하나 더 — 「프로그램마다 다른 색」), `backend/app/tools/ui/open_window.py`(+시험·목록 맞춤), `backend/app/agent/prompts/system.md`(그 밖 줄)
**Interfaces:** Consumes Task 47·49·51 API. Produces 프로그램 `library`(「자료함」, work, 1400×860): 왼쪽 축 필터(값·개수·「새」), 위 찾기(뜻+낱말 — `GET /api/files?q=`), 목록(이름·축 값·요약·올린 날, 50개씩), 상세(미리 보기: 그림·쪽 글·표 앞 20행 / 축 값 고치기 / [대화에 붙이기] → `open('chat', {attach: file_id})` / [내려받기] / [지우기](올린 사람·관리자, 확인 창) / 관리자 [완전히 지우기]), 관리자 합치기 제안 탭, 머리에 다시 넣기 진행률(있을 때).
- [ ] **Step 1: 실패하는 시험** — 필터 조합·찾기·상세·축 고치기 PATCH·지우기 권한·합치기(관리자만)·진행률 표시·200개 목록 넘침 없음
- [ ] **Step 2~4**(화면 검수) · **Step 5: 커밋** `feat: 자료함 프로그램`
- 참고: `open('chat', {attach})` 를 대화가 받는 한 줄은 Task 55 가 `Chat.tsx` 에 넣는다(Task 55 Produces 에 더함: `params.attach` → 그 파일을 칩으로).

### Task 57: 설정 — 그림 읽기·임베딩 줄 · 다시 넣기 · 정보 API 연결 [opus] · G8

**Files:** Modify `frontend/src/programs/settings/{AssignmentParts.tsx,models.ts,Settings.tsx,settingsApi.ts}`; Create `frontend/src/programs/settings/{ReindexDialog.tsx,InfoConnections.tsx}` + 시험
**Interfaces:** Consumes Task 51·52 API. Produces 배정 표 두 줄(그림 읽기·임베딩, 임베딩 목록은 `for=embedding`), 임베딩 바꾸기 확인 창(「자료 n개·조각 m개를 새 모델로 다시 넣습니다」 + 가격 참고 — Task 46 표), 진행률(`GET /api/files/reindex` 3초 폴링), 「정보 API 연결」 구역(카드·[연결 테스트]·추가·삭제, 프리셋 「기상청(공공데이터포털)」).
- [ ] **Step 1~4**(화면 검수) · **Step 5: 커밋** `feat: 설정 — 그림 읽기·임베딩·정보 API`

### Task 58: 끝에서 끝까지 · 운영 문서 [opus] · G9

**Files:** Create `frontend/e2e/plan3.spec.ts`, `backend/tests/e2e/test_files_flow.py`, `scripts/qdrant-local.sh`(맥 Qdrant 받기·띄우기 — 버전 고정, `data/qdrant`); Modify `README.md`, `~/projects/chronos-serve-logs/README.md`(PM 앱 띄우기에 Qdrant 한 줄), `docs/demo/시나리오.md`(설계 1장 시연 장면 1~5)
- 흐름(가짜 LLM·Qdrant `:memory:` 또는 로컬 서버): 대화에 사진·PDF·엑셀 붙임 → 칩 저장됨 → 「동절기 타설 기준?」 → 출처 붙은 답 → 다른 대화에서 같은 질문 → 자료함에서 찾음 → 엑셀 카드 → 가져오기 → 질문지 → 승인함 → 날씨(가짜 KMA) 근거 → 모델 ▾ 바꾸기 → 그림 턴 안내.
- [ ] **Step 1~4** · **Step 5: 커밋** `test: 계획 3 끝에서 끝까지와 운영 문서`

## 설계서 대응표

| 설계서 | 작업 |
|---|---|
| 1 성공 모습 1~5 | 58 |
| 4 방법 ②·Qdrant·낱말 검색 | 48 |
| 5-1 받기·확장자·조각·임베딩 모델·실패 | 47·48 |
| 5-2 분류(축 고정·값 늘림·합치기) | 49 |
| 5-3 세션 기억·도구·출처·지우기 | 50·47 |
| 5-4 공정표 가져오기 | 53 |
| 5-5 모델 고르기·그림 읽기·턴 범위 | 51·50 |
| 5-6 정보 API·날씨 | 52 |
| 5-7 화면(시안 먼저) | 54·55·56·57 |
| 5-8 표·칸 | 47 |
| 6 빌더에게 맡김 | 각 작업 안에서 |
