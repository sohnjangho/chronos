"""월간·분기별 보고서, 양식 첨부·학습·프로젝트별 기억, 타 프로젝트 선택·복사 및 .pptx 추출 시험."""

import io
import zipfile

import pytest
from sqlalchemy import select

from app.files.extract import extract
from app.files.kinds import kind_of
from app.programs.reports import service
from app.store.schedules import create_schedule
from app.store.tables import ReportTemplate, User
from app.tools.context import ToolContext
from app.tools.registry import call, list_tools, load_all
from tests import schedules


def _make_sample_pptx(path) -> None:
    slide1 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody>"
        "<a:p><a:r><a:t>1. 분기 공정 요약</a:t></a:r></a:p>"
        "<a:p><a:r><a:t>전체 공정률을 보고합니다.</a:t></a:r></a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    slide2 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody>"
        "<a:p><a:r><a:t>2. WBS 공종별 현황</a:t></a:r></a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide2.xml", slide2)
        z.writestr("ppt/slides/slide1.xml", slide1)


def test_pptx_kind_and_slide_extraction(tmp_path):
    p = tmp_path / "monthly_template.pptx"
    _make_sample_pptx(p)
    assert kind_of("monthly_template.pptx", p.read_bytes()[:16]) == "doc"
    got = extract(p, "doc")
    assert got.pages == 2
    assert [loc for loc, _ in got.text_parts] == ["1슬라이드", "2슬라이드"]
    assert "1. 분기 공정 요약" in got.text_parts[0][1]
    assert "2. WBS 공종별 현황" in got.text_parts[1][1]


def test_learn_project_memory_cross_project_adopt_revise_and_export(client, session, admin):
    sid1 = create_schedule(
        session,
        name="5층 사무동 신축",
        domain="construction",
        level="L3",
        schedule=schedules.sample(),
        conditions=[],
        by_kind="agent",
        by_name="에이전트",
        note="1번 프로젝트",
    )
    sid2 = create_schedule(
        session,
        name="배터리 파일럿 라인",
        domain="production",
        level="L2",
        schedule=schedules.sample(),
        conditions=[],
        by_kind="agent",
        by_name="에이전트",
        note="2번 프로젝트",
    )
    session.commit()

    sample_md = (
        "# 발주처 월간 공정 보고서\n\n"
        "## 1. 월간 공정 요약\n"
        "기준일 2027.06.01 기준 실적을 보고합니다.\n\n"
        "## 2. 공종별 진도 표\n"
        "| 구분 | 비중 | 계획(%) | 실적(%) | 편차 |\n"
        "|---|---|---|---|---|\n"
        "| 기초 | 20% | 100 | 100 | 0 |\n\n"
        "## 3. 마일스톤 준공 전망\n"
        "주요 마일스톤 일정 확인 바랍니다.\n\n"
        "## 4. 현장 특기사항\n"
        "안전 점검 결과 양호합니다.\n"
    ).encode()

    up = client.post(
        "/api/files",
        headers=admin,
        files=[("files", ("client_monthly_sample.md", sample_md, "text/markdown"))],
    )
    assert up.status_code == 200, up.text
    file_id = up.json()["items"][0]["file_id"]

    # 1. 양식 학습
    learned_res = client.post(
        "/api/reports/templates/learn",
        headers=admin,
        json={"file_id": file_id, "schedule_id": sid1, "cadence": "monthly", "name": "A발주처 월간 양식"},
    )
    assert learned_res.status_code == 200, learned_res.text
    learned = learned_res.json()
    assert learned["suggested_cadence"] == "monthly"
    assert learned["suggested_name"] == "A발주처 월간 양식"
    headings = [s["heading"] for s in learned["sections"]]
    assert any("월간 공정 요약" in h for h in headings)
    assert any("공종별 진도 표" in h for h in headings)
    wbs_sec = next(s for s in learned["sections"] if "공종별 진도" in s["heading"])
    assert wbs_sec["data_binding"] == "wbs_table"
    assert wbs_sec["table_columns"] == ["구분", "비중", "계획(%)", "실적(%)", "편차"]
    manual_sec = next(s for s in learned["sections"] if "현장 특기사항" in s["heading"])
    assert manual_sec["data_binding"] == "manual_input"

    # 2. 프로젝트 1 기본 양식으로 저장
    create_res = client.post(
        "/api/reports/templates",
        headers=admin,
        json={
            "schedule_id": sid1,
            "cadence": "monthly",
            "name": learned["suggested_name"],
            "is_default": True,
            "source_file_id": file_id,
            "source_file_name": "client_monthly_sample.md",
            "sections": learned["sections"],
            "style": learned["style"],
        },
    )
    assert create_res.status_code == 200, create_res.text
    tpl1_id = create_res.json()["id"]

    # 일간(daily)은 거절
    daily_res = client.post(
        f"/api/schedules/{sid1}/reports",
        headers=admin,
        json={"cadence": "daily"},
    )
    assert daily_res.status_code == 422

    # 3. 프로젝트 1 에서 월간 보고서 생성 시 학습 양식 자동 기억·적용
    rep1_res = client.post(
        f"/api/schedules/{sid1}/reports",
        headers=admin,
        json={"cadence": "monthly", "period_label": "2027년 6월"},
    )
    assert rep1_res.status_code == 200, rep1_res.text
    rep1 = rep1_res.json()
    assert rep1["template_id"] == tpl1_id
    assert rep1["template_name"] == "A발주처 월간 양식"
    assert any("1 골조" in str(cell) for b in rep1["blocks"] if b["table"] for row in b["table"]["rows"] for cell in row)

    # 4. 프로젝트 2 목록에서는 'other_projects' 에만 보이고, 자동 생성 시에는 프로젝트 2 기본으로 섞이지 않는다
    list2 = client.get(f"/api/reports/templates?schedule_id={sid2}", headers=admin).json()
    assert list2["current_project"] == []
    assert [t["id"] for t in list2["other_projects"]] == [tpl1_id]
    assert list2["other_projects"][0]["project_name"] == "5층 사무동 신축"

    rep2_auto = client.post(
        f"/api/schedules/{sid2}/reports",
        headers=admin,
        json={"cadence": "monthly"},
    ).json()
    assert rep2_auto["template_id"] is None
    assert rep2_auto["template_name"] == "기본 월간 공정 보고서"

    # 프로젝트 2 에서 명시적으로 프로젝트 1 양식 선택 생성 가능
    rep2_pick = client.post(
        f"/api/schedules/{sid2}/reports",
        headers=admin,
        json={"cadence": "monthly", "template_id": tpl1_id},
    ).json()
    assert rep2_pick["template_name"] == "A발주처 월간 양식"

    # 프로젝트 2 로 복사·기억(adopt) 후 분기/월간 기억 확인
    adopted = client.post(
        f"/api/reports/templates/{tpl1_id}/adopt",
        headers=admin,
        json={"schedule_id": sid2, "is_default": True, "name": "라인 적용 월간 양식"},
    )
    assert adopted.status_code == 200, adopted.text
    adopted_id = adopted.json()["id"]
    assert adopted.json()["schedule_id"] == sid2

    rep2_remembered = client.post(
        f"/api/schedules/{sid2}/reports",
        headers=admin,
        json={"cadence": "monthly"},
    ).json()
    assert rep2_remembered["template_id"] == adopted_id

    # 5. 분기별 보고서 생성 + AI 수정 피드백 기억
    q_rep = client.post(
        f"/api/schedules/{sid1}/reports",
        headers=admin,
        json={"cadence": "quarterly", "period_label": "2027년 2분기"},
    )
    assert q_rep.status_code == 200
    assert q_rep.json()["cadence"] == "quarterly"

    prose_blk = next(b for b in rep1["blocks"] if b["block_kind"] == "prose")
    rev = client.post(
        f"/api/schedules/{sid1}/reports/{rep1['id']}/revise",
        headers=admin,
        json={"block_id": prose_blk["id"], "instruction": "마지막에 준공 리스크 한 줄 추가", "remember_rule": True},
    )
    assert rev.status_code == 200, rev.text
    assert "마지막에 준공 리스크 한 줄 추가" in rev.json()["style"]["learned_rules"]
    session.expire_all()
    tpl1_row = session.get(ReportTemplate, tpl1_id)
    assert tpl1_row is not None
    assert "마지막에 준공 리스크 한 줄 추가" in tpl1_row.style_json["learned_rules"]

    # 6. HTML / DOCX 내보내기 검증
    html_res = client.get(f"/api/schedules/{sid1}/reports/{rep1['id']}/export?format=html", headers=admin)
    assert html_res.status_code == 200
    assert "A발주처 월간 양식" in html_res.text

    docx_res = client.get(f"/api/schedules/{sid1}/reports/{rep1['id']}/export?format=docx", headers=admin)
    assert docx_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(docx_res.content)) as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")
    assert "월간 공정 요약" in doc_xml
    assert "1 골조" in doc_xml


async def test_report_agent_tools(client, session):
    del client
    load_all()
    names = {t.name for t in list_tools()}
    assert {"report.learn_template", "report.generate"} <= names

    sid = schedules.store(session, schedules.sample())
    session.commit()
    admin_user = session.scalars(select(User).where(User.login_id == "admin")).one()
    events = []
    ctx = ToolContext(session=session, user=admin_user, schedule_id=sid, emit=events.append)

    res = await call("report.generate", {"cadence": "quarterly", "period_label": "2027년 3분기"}, ctx)
    assert res.ok, res.error
    assert res.output["cadence"] == "quarterly"
    assert res.output["period_label"] == "2027년 3분기"
    assert any(e.type == "card" and e.data["kind"] == "report" for e in events)
    assert service.list_reports(session, sid, "quarterly").items


async def test_learn_from_file_fixes_llm_manual_input_misbinding(session, monkeypatch):
    from types import SimpleNamespace

    from app.llm import fake as llm_fake
    from app.llm.client import LlmClient
    from app.programs.reports import learner
    from app.store import files as files_store

    user = session.scalars(select(User).where(User.login_id == "admin")).one()
    md = (
        "# 발주처 월간공정보고 양식\n\n"
        "## 1. 금월 프로젝트 핵심 요약\n요약 본문\n\n"
        "## 2. 마일스톤 표\n| 마일스톤 | 계획일 | 전망 | 상태 |\n|---|---|---|---|\n| 착공 | 2027-03-01 | 2027-03-01 | 완료 |\n\n"
        "## 3. 지연 원인 분석\n| 작업 | 지연일 | 원인 |\n|---|---|---|\n| 골조 | 3일 | 우천 |\n\n"
        "## 4. 3주 룩어헤드\n| 작업 | 착수예정 |\n|---|---|\n| 외장 | 2027-04-20 |\n\n"
        "## 5. 현장 특기사항\n안전 무재해 달성\n"
    ).encode()
    row = files_store.save_upload(session, md, "발주처_월간공정보고_양식.md", user)
    monkeypatch.setattr(llm_fake, "enabled", lambda: False)

    async def fake_chat(self, purpose, messages, **kwargs):
        return SimpleNamespace(
            finish_reason="stop",
            text="",
            parsed={
                "suggested_name": "발주처 월간 표준 양식",
                "suggested_cadence": "monthly",
                "analysis_summary": "초안",
                "tone": "~습니다",
                "date_format": "YYYY.MM.DD",
                "sections": [
                    {"heading": "1. 금월 프로젝트 핵심 요약", "block_kind": "manual", "data_binding": "manual_input", "table_columns": [], "section_prompt": ""},
                    {"heading": "2. 마일스톤 표", "block_kind": "manual", "data_binding": "manual_input", "table_columns": [], "section_prompt": ""},
                    {"heading": "3. 지연 원인 분석", "block_kind": "manual", "data_binding": "manual_input", "table_columns": [], "section_prompt": ""},
                    {"heading": "4. 3주 룩어헤드", "block_kind": "manual", "data_binding": "manual_input", "table_columns": [], "section_prompt": ""},
                    {"heading": "5. 현장 특기사항", "block_kind": "manual", "data_binding": "manual_input", "table_columns": [], "section_prompt": ""},
                ],
                "learned_rules": [],
            },
        )

    monkeypatch.setattr(LlmClient, "chat", fake_chat)
    _, _, _, sections, _, _ = await learner.learn_from_file(session, row.id, "monthly")
    bindings = {s.heading: s.data_binding for s in sections}
    assert bindings == {
        "1. 금월 프로젝트 핵심 요약": "summary_prose",
        "2. 마일스톤 표": "milestone_table",
        "3. 지연 원인 분석": "delay_table",
        "4. 3주 룩어헤드": "lookahead_3w",
        "5. 현장 특기사항": "manual_input",
    }
    ms_sec = next(s for s in sections if s.heading == "2. 마일스톤 표")
    assert ms_sec.table_columns == ["마일스톤", "계획일", "전망", "상태"]


async def test_prose_length_cutoff_and_revise_failure_protect_content(client, session, admin, monkeypatch):
    from types import SimpleNamespace

    from app.llm import fake as llm_fake
    from app.llm.client import LlmClient, LlmFailed
    from app.llm.errors import LlmError
    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory, TemplateSection

    sid = create_schedule(
        session,
        name="5층 사무동 테스트",
        domain="construction",
        level="L3",
        schedule=schedules.sample(),
        conditions=[],
        by_kind="agent",
        by_name="에이전트",
        note="보고서 테스트",
    )
    session.commit()

    rep = client.post(
        f"/api/schedules/{sid}/reports",
        headers=admin,
        json={"cadence": "monthly", "period_label": "2027년 4월"},
    ).json()
    prose_blk = next(b for b in rep["blocks"] if b["block_kind"] == "prose")
    orig_text = prose_blk["text"]

    monkeypatch.setattr(llm_fake, "enabled", lambda: False)

    async def truncated_chat(self, purpose, messages, **kwargs):
        assert kwargs.get("max_tokens", 0) >= 4000
        return SimpleNamespace(finish_reason="length", text="2027.04.17 기준 계획 대비 -2.1%p를", parsed=None)

    monkeypatch.setattr(LlmClient, "chat", truncated_chat)
    _, _, _, blocks = await generator.generate_report_blocks(
        session,
        sid,
        "monthly",
        "2027년 4월",
        [TemplateSection(id="s1", heading="요약", block_kind="prose", data_binding="summary_prose")],
        StyleMemory(),
    )
    assert not blocks[0].text.endswith("-2.1%p를")
    assert len(blocks[0].text) > 40

    async def failing_chat(self, purpose, messages, **kwargs):
        raise LlmFailed(LlmError("server_error", "일시 오류"))

    monkeypatch.setattr(LlmClient, "chat", failing_chat)
    rev = client.post(
        f"/api/schedules/{sid}/reports/{rep['id']}/revise",
        headers=admin,
        json={"block_id": prose_blk["id"], "instruction": "핵심 수치 강조", "remember_rule": False},
    )
    assert rev.status_code == 502
    after = client.get(f"/api/schedules/{sid}/reports/{rep['id']}", headers=admin).json()
    after_blk = next(b for b in after["blocks"] if b["id"] == prose_blk["id"])
    assert after_blk["text"] == orig_text
    assert "[수정 반영:" not in after_blk["text"]


# ── 11-23 시나리오 재검증 결함(R1~R6) ─────────────────────────────────


def _scenario(session, sid: int, base: int, name: str, status: str, finish: str, delta: int, crit: int) -> None:
    from app.store import scenarios as scen_store
    from app.store.schedules import load

    current, stored, _ = load(session, sid)
    row = scen_store.create(
        session, schedule_id=sid, base_version=base, name=name, source="shorten", schedule=current,
        conditions=stored, created_by="김공정",
        extra_summary={"finish": finish, "finish_delta": delta, "critical_count": crit},
    )
    scen_store.set_status(session, row, status)
    session.commit()


def _bump_version(session, sid: int) -> int:
    from app.store.schedules import load
    from app.store.versions import save_new_version

    current, stored, n = load(session, sid)
    return save_new_version(session, sid, current, stored, by_kind="user", by_name="김공정", note="시험",
                            changes=[], base_version=n, plan_change=False)


async def test_learned_table_columns_get_values_by_meaning(session):
    """R1: 양식 열 이름의 뜻으로 값을 넣는다. 못 맞춘 칸은 「—」, 뜻이 같은 열은 그대로, 하나도 못 맞추면 기본 열."""
    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory, TemplateSection

    sid = schedules.store(session, schedules.sample())
    session.commit()
    _scenario(session, sid, 1, "만회안 B", "applied", "2027-10-05", -19, 27)
    cols3 = ["만회 대안", "주요 조치 내용", "단축 효과(일)", "추가 비용/자원", "리스크 및 크리티컬패스 영향도", "귀책 주체", "승인 결과"]
    ms_cols = ["구분", "기준 계획일", "현재 예측일", "차이(일)", "상태 및 특기사항"]
    sections = [
        TemplateSection(id="s3", heading="3. 만회 계획", block_kind="table", data_binding="scenario_compare", table_columns=cols3),
        TemplateSection(id="s2", heading="2. 마일스톤", block_kind="table", data_binding="milestone_table", table_columns=ms_cols),
        TemplateSection(id="s9", heading="9. 엉뚱한 표", block_kind="table", data_binding="scenario_compare",
                        table_columns=["가", "나", "다"]),
    ]
    _, _, _, blocks = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", sections, StyleMemory())
    t3 = blocks[0].table
    assert t3["columns"] == cols3
    assert t3["rows"] == [["만회안 B", "—", "-19일", "—", "—", "—", "반영 완료"]]
    assert blocks[1].table["columns"] == ms_cols
    assert blocks[2].table["columns"][0] == "시나리오" and len(blocks[2].table["columns"]) == 5
    assert blocks[2].table["rows"][0][:3] == ["만회안 B", "2027.10.05", "-19일"]

    # 4절(룩어헤드) 7열: 날짜는 기간 칸, 작업 이름은 작업 칸
    cols4 = ["작업/공종", "계획 기간", "선행 인계", "자재 조달", "장비 투입", "사전 조치 내역", "담당/상태"]
    std4 = ["일자", "구분", "작업명", "선행·유의사항"]
    cols, picks = generator._fit_columns("lookahead_3w", cols4, std4)
    assert cols == cols4
    row = generator._pick(["2027.04.17", "착수 예정", "A1100 기초 거푸집", "착수 가능"], picks)
    assert row == ["A1100 기초 거푸집", "2027.04.17", "착수 가능", "—", "—", "—", "착수 예정"]
    # 기본 열과 같은 이름은 그대로 자리에
    std_ms = ["마일스톤", "Plan", "실적·예측", "차이(일)", "상태"]
    assert generator._fit_columns("milestone_table", ms_cols, std_ms) == (ms_cols, [0, 1, 2, 3, 4])
    assert generator._fit_columns("milestone_table", std_ms, std_ms) == (std_ms, [0, 1, 2, 3, 4])


# 리뷰 I-4: 뜻이 둘인 양식 열 이름은 「—」, 지나치게 넓은 낱말은 빼서 엉뚱한 값을 넣지 않는다.
STD = {
    "wbs_table": ["WBS", "가중치", "계획(%)", "실적(%)", "차이(%p)"],
    "milestone_table": ["마일스톤", "Plan", "실적·예측", "차이(일)", "상태"],
    "delay_table": ["사건", "책임", "준공 영향", "상태·대책"],
    "lookahead_3w": ["일자", "구분", "작업명", "선행·유의사항"],
}


@pytest.mark.parametrize(("binding", "header", "expected"), [
    ("delay_table", "지연 일수", "—"),             # 준공 영향이 아니다
    ("delay_table", "조치 내용", "상태·대책"),      # 사건 이름이 아니다
    ("lookahead_3w", "선행 작업", "—"),             # 선행·작업 두 뜻 — 그 작업 이름이 아니다
    ("milestone_table", "지연 사유", "—"),          # +8(차이)이 아니다
    ("wbs_table", "실적 비율", "실적(%)"),          # 가중치가 아니다
    ("wbs_table", "계획 대비 실적", "—"),           # 계획·실적 두 뜻 — 실적 % 가 아니다
])
def test_a_header_with_two_meanings_or_a_loose_word_gets_no_wrong_value(binding, header, expected):
    from app.programs.reports import generator

    std = STD[binding]
    others = [c for c in std if c != expected][:3]  # 나머지 열은 기본 이름 그대로(절반 넘게 맞게)
    cols, picks = generator._fit_columns(binding, [header, *others], std)
    assert cols == [header, *others]
    assert generator._pick(std, picks)[0] == expected


def test_default_columns_keep_their_own_place():
    """기본 열 이름 그대로면 그 자리(「준공 차이(만들 때 일정 대비)」는 준공·차이 두 낱말이어도 차이 열)."""
    from app.programs.reports import generator

    std = ["시나리오", "예상 준공", "준공 차이(만들 때 일정 대비)", "크리티컬 수", "상태"]
    assert generator._fit_columns("scenario_compare", std, std) == (std, [0, 1, 2, 3, 4])
    for binding, cols in STD.items():
        assert generator._fit_columns(binding, cols, cols) == (cols, list(range(len(cols))))


async def test_scenario_table_keeps_only_current_round(session):
    """R2: 반영된 안이 있으면 그 안과 기준 버전이 같은 안(+ 지금 버전 기준 안)만 보인다. 옛 실행의 안은 빠진다."""
    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory, TemplateSection

    sid = schedules.store(session, schedules.sample())
    session.commit()
    _scenario(session, sid, 1, "만회안 B", "open", "2027-09-24", -27, 29)  # 옛 실행(버전 1 기준)
    _scenario(session, sid, 1, "만회안 A", "open", "2027-10-25", -4, 12)
    _bump_version(session, sid)  # 버전 2
    _scenario(session, sid, 2, "지연 반영안 (2건)", "open", "2027-11-04", 5, 12)
    _scenario(session, sid, 2, "만회안 A", "open", "2027-10-30", 1, 12)
    _scenario(session, sid, 2, "만회안 B", "applied", "2027-10-05", -19, 27)
    _bump_version(session, sid)  # 버전 3 = 만회안 B 반영
    sec = TemplateSection(id="s", heading="만회", block_kind="table", data_binding="scenario_compare")
    _, _, _, blocks = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", [sec], StyleMemory())
    t = blocks[0].table
    assert [r[0] for r in t["rows"]] == ["만회안 B", "만회안 A", "지연 반영안 (2건)"]
    assert t["columns"][2] == "준공 차이(만들 때 일정 대비)"

    # 반영된 안이 없으면 지금 버전 기준 안만
    sid2 = schedules.store(session, schedules.sample())
    session.commit()
    _scenario(session, sid2, 1, "옛 안", "open", "2027-09-24", -27, 29)
    _bump_version(session, sid2)
    _scenario(session, sid2, 2, "새 안", "open", "2027-10-30", 1, 12)
    _, _, _, blocks2 = await generator.generate_report_blocks(session, sid2, "monthly", "2027년 4월", [sec], StyleMemory())
    assert [r[0] for r in blocks2[0].table["rows"]] == ["새 안"]


async def test_delay_plan_whose_delays_are_already_in_the_schedule_is_shown_applied(session):
    """재확인: 지연 2건이 만회안 B 와 함께 버전 3에 반영됐으면, 같은 사건을 넣은 열린 「지연 반영안 (2건)」은 「검토 중」이 아니라
    「반영 완료」다(반영된 만회안처럼). 사건이 하나라도 아직 열려 있으면 검토 중 그대로."""
    from datetime import date

    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory, TemplateSection
    from app.store import scenarios as scen_store
    from app.store.schedules import load
    from app.store.tables import DelayEvent

    def delay(sid: int, status: str) -> int:
        row = DelayEvent(schedule_id=sid, activity_id="A", start_date=date(2027, 3, 2), days=2, cause="자재 반입 지연",
                         created_by="김공정", status=status, reflected_version=3 if status == "reflected" else None)
        session.add(row)
        session.flush()
        return row.id

    def delay_plan(sid: int, ids: list[int]) -> None:
        current, stored, _ = load(session, sid)
        scen_store.create(session, schedule_id=sid, base_version=2, name=f"지연 반영안 ({len(ids)}건)", source="delay",
                          schedule=current, conditions=stored, delay_event_ids=ids, created_by="김공정",
                          extra_summary={"finish": "2027-11-04", "finish_delta": 5, "critical_count": 12})
        session.commit()

    sec = TemplateSection(id="s", heading="만회", block_kind="table", data_binding="scenario_compare")
    rows = {}
    for case, statuses in (("reflected", ("reflected", "reflected")), ("one_open", ("reflected", "open"))):
        sid = schedules.store(session, schedules.sample())
        session.commit()
        _bump_version(session, sid)  # 버전 2
        delay_plan(sid, [delay(sid, s) for s in statuses])
        _scenario(session, sid, 2, "만회안 A", "open", "2027-10-30", 1, 12)
        _scenario(session, sid, 2, "만회안 B", "applied", "2027-10-05", -19, 27)
        _bump_version(session, sid)  # 버전 3 = 만회안 B 반영(지연 반영)
        _, _, _, blocks = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", [sec], StyleMemory())
        rows[case] = {r[0]: r[-1] for r in blocks[0].table["rows"]}
    assert rows["reflected"] == {"만회안 B": "반영 완료", "만회안 A": "검토 중", "지연 반영안 (2건)": "반영 완료"}
    assert rows["one_open"]["지연 반영안 (2건)"] == "검토 중"


async def test_open_recorded_delays_get_their_own_line_in_the_plan_table(session):
    """재확인 2: 기록만 하고 아직 반영하지 않은(열린) 지연은 간트의 띠처럼 보고서 만회 표에 한 줄로 — 「기록된 지연 n건 ·
    지연 일수 합 n일」 · 「승인 전(일정에 반영되지 않음)」. 계산한 수치(준공·차이·크리티컬)는 바꾸지 않는다."""
    from datetime import date

    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory, TemplateSection
    from app.store.tables import DelayEvent

    sid = schedules.store(session, schedules.sample())
    session.commit()
    _scenario(session, sid, 1, "만회안 A", "open", "2027-10-30", 1, 12)
    sec = TemplateSection(id="s", heading="만회", block_kind="table", data_binding="scenario_compare")
    _, _, _, before = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", [sec], StyleMemory())
    session.add(DelayEvent(schedule_id=sid, activity_id="A", start_date=date(2027, 3, 2), days=2, cause="자재 반입 지연",
                           created_by="김공정", status="open"))
    session.commit()
    _, _, _, blocks = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", [sec], StyleMemory())
    rows = blocks[0].table["rows"]
    assert rows[:-1] == before[0].table["rows"]  # 있던 줄·수치는 그대로
    assert rows[-1] == ["기록된 지연 1건 · 지연 일수 합 2일", "—", "—", "—", "승인 전(일정에 반영되지 않음)"]


async def test_prose_drops_heading_line_and_markdown_stars(session, monkeypatch):
    """R3: 서술·수정 답의 첫 줄이 절 제목이면 빼고 ** 를 지운다. 두 프롬프트에 금지 문장이 있다."""
    from types import SimpleNamespace

    from app.llm import fake as llm_fake
    from app.llm.client import LlmClient
    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory, TemplateSection

    sid = schedules.store(session, schedules.sample())
    session.commit()
    monkeypatch.setattr(llm_fake, "enabled", lambda: False)
    prompts: list[str] = []
    heading = "1. 금월 프로젝트 핵심 요약 (Executive Summary)"

    async def chat(self, purpose, messages, **kwargs):
        prompts.append(messages[-1]["content"])
        return SimpleNamespace(finish_reason="stop", text=f"**{heading}**\n- 핵심 **결론**: 준공 영향 없음.", parsed=None)

    monkeypatch.setattr(LlmClient, "chat", chat)
    sec = TemplateSection(id="s1", heading=heading, block_kind="prose", data_binding="summary_prose")
    _, _, _, blocks = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", [sec], StyleMemory())
    assert blocks[0].text == "- 핵심 결론: 준공 영향 없음."
    text = await generator.revise_block_text(session, {"heading": heading, "text": "원문"}, "다듬어 줘", StyleMemory(),
                                             schedule_id=sid)
    assert text == "- 핵심 결론: 준공 영향 없음."
    assert all("제목 줄을 다시 쓰지 않는다" in p and "마크다운 기호를 쓰지 않는다" in p for p in prompts)


async def test_prose_fallback_retries_once_then_marks_auto_text(client, session, admin, monkeypatch):
    """R4: 잘리면 길이를 올려 한 번 더 부른다. 성공하면 표시 없음, 또 잘리면 auto_text. 고치면 표시가 지워진다."""
    from types import SimpleNamespace

    from app.llm import fake as llm_fake
    from app.llm.client import LlmClient
    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory, TemplateSection

    sid = schedules.store(session, schedules.sample())
    session.commit()
    monkeypatch.setattr(llm_fake, "enabled", lambda: False)
    sec = [TemplateSection(id="s1", heading="요약", block_kind="prose", data_binding="summary_prose")]
    limits: list[int] = []

    async def cut_then_ok(self, purpose, messages, **kwargs):
        limits.append(kwargs["max_tokens"])
        if len(limits) == 1:
            return SimpleNamespace(finish_reason="length", text="잘린", parsed=None)
        return SimpleNamespace(finish_reason="stop", text="AI 가 쓴 문단입니다.", parsed=None)

    monkeypatch.setattr(LlmClient, "chat", cut_then_ok)
    _, _, _, blocks = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", sec, StyleMemory())
    assert (blocks[0].text, blocks[0].auto_text) == ("AI 가 쓴 문단입니다.", False)
    assert len(limits) == 2 and limits[1] > limits[0]

    limits.clear()

    async def always_cut(self, purpose, messages, **kwargs):
        limits.append(kwargs["max_tokens"])
        return SimpleNamespace(finish_reason="length", text="잘린", parsed=None)

    monkeypatch.setattr(LlmClient, "chat", always_cut)
    _, _, _, blocks = await generator.generate_report_blocks(session, sid, "monthly", "2027년 4월", sec, StyleMemory())
    assert blocks[0].auto_text is True and len(limits) == 2 and "잘린" not in blocks[0].text

    # API: LLM 이 연결되지 않아 자동 문안이면 표시, AI 수정 뒤에는 표시가 지워진다
    monkeypatch.setattr(llm_fake, "enabled", lambda: True)
    rep = client.post(f"/api/schedules/{sid}/reports", headers=admin, json={"cadence": "monthly"}).json()
    prose = next(b for b in rep["blocks"] if b["block_kind"] == "prose")
    assert prose["auto_text"] is True
    rev = client.post(f"/api/schedules/{sid}/reports/{rep['id']}/revise", headers=admin,
                      json={"block_id": prose["id"], "instruction": "짧게", "remember_rule": False})
    assert rev.status_code == 200, rev.text
    assert next(b for b in rev.json()["blocks"] if b["id"] == prose["id"])["auto_text"] is False


async def test_revise_prompt_gets_progress_facts(session, monkeypatch):
    """R5: AI 부분 수정 프롬프트에 공정 수치(Data Date·공정률)가 들어간다."""
    from types import SimpleNamespace

    from app.llm import fake as llm_fake
    from app.llm.client import LlmClient
    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory

    sid = schedules.store(session, schedules.sample())
    session.commit()
    monkeypatch.setattr(llm_fake, "enabled", lambda: False)
    seen: list[str] = []

    async def chat(self, purpose, messages, **kwargs):
        seen.append(messages[-1]["content"])
        return SimpleNamespace(finish_reason="stop", text="고친 문단", parsed=None)

    monkeypatch.setattr(LlmClient, "chat", chat)
    await generator.revise_block_text(session, {"heading": "요약", "text": "원문"}, "다듬어", StyleMemory(), schedule_id=sid)
    assert "[프로젝트 공정 수치]" in seen[0] and "Data Date:" in seen[0] and "실적 공정률:" in seen[0]


def test_auto_summary_separates_late_tasks_from_delay_events(session):
    """R6: 「계획보다 늦은 작업」과 「기록된 지연 사건」을 다른 낱말로 쓴다."""
    from app.programs.progress import service as progress_service
    from app.programs.reports import generator
    from app.programs.reports.schemas import StyleMemory

    sid = schedules.store(session, schedules.sample())
    session.commit()
    prog = progress_service.progress(session, sid, "month")
    events = [{"status": "reflected"}, {"status": "reflected"}]
    for tone in ("~습니다", "개조식 ~함"):
        txt = generator._deterministic_summary("현장", "monthly", "2027년 4월", prog, events, StyleMemory(tone=tone))
        assert "계획보다 늦은 작업" in txt and "기록된 지연 사건 2건(모두 반영)" in txt
        assert "주요 지연 사안" not in txt and "지연 이슈" not in txt
    txt = generator._deterministic_summary("현장", "monthly", "2027년 4월", prog,
                                           [{"status": "open"}, {"status": "reflected"}], StyleMemory())
    assert "기록된 지연 사건 2건(열림 1건)" in txt
