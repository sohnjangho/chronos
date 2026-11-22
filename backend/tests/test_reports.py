"""월간·분기별 보고서, 양식 첨부·학습·프로젝트별 기억, 타 프로젝트 선택·복사 및 .pptx 추출 시험."""

import io
import zipfile

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
