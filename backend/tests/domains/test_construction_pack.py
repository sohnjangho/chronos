"""건설 분야 묶음(construction/pack.yaml): 검사·내용·에이전트 지시문 글."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import app.domains
from app.domains.loader import UnknownDomain, domains, load, read_pack
from app.harness.conditions import Condition

PACK_FILE = Path(app.domains.__file__).parent / "construction" / "pack.yaml"


def _broken(tmp_path: Path, change) -> Path:
    """진짜 묶음을 읽어 change(dict) 로 고친 뒤 임시 파일에 쓴다."""
    data = yaml.safe_load(PACK_FILE.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_construction_rules_are_valid_conditions():
    assert all(Condition.from_dict(r) for r in load("construction").rules_raw)


def test_pack_rejects_unknown_keys(tmp_path):
    path = _broken(tmp_path, lambda d: d.update(questions=[{"id": "scope"}]))
    with pytest.raises(ValidationError, match="questions"):
        read_pack(path)


def test_rules_round_trip_through_condition():
    for raw in load("construction").rules_raw:
        assert Condition.from_dict(raw).to_dict() == raw


def test_prompt_mentions_key_resources_and_the_curing_rule():
    text = load("construction").prompt()
    assert all(name in text for name in ["타워크레인", "철근공", "타설반"])
    assert "타설 뒤 양생 7일" in text


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


def test_domains_lists_the_packs():
    assert domains() == ["construction"]


def test_unknown_domain():
    with pytest.raises(UnknownDomain):
        load("farm")
    with pytest.raises(UnknownDomain):
        load("../domains")


def test_load_is_cached():
    assert load("construction") is load("construction")


def test_pack_basics():
    pack = load("construction")
    assert (pack.id, pack.name) == ("construction", "건설")
    assert {"activity": "액티비티", "resource": "자원", "deadline": "준공"}.items() <= pack.terms.items()
    assert (pack.default_calendar.days_per_week, pack.default_calendar.holidays) == (6, "KR")


def test_required_rules():
    rules = {r["kind"]: r for r in load("construction").rules_raw}
    curing = rules["min_gap"]
    assert curing["params"] == {"after_tag": "타설", "days": 7, "unit": "workdays"}
    assert curing["text"] == "타설 뒤 양생 7일"
    assert any(r["kind"] == "text_only" and r["text"] == "골조 2개 층 위부터 설비 배관" for r in load("construction").rules_raw)
    for r in load("construction").rules_raw:
        assert (r["layer"], r["source"], r["enabled"]) == ("domain", "분야 규칙", True)
    ids = [r["id"] for r in load("construction").rules_raw]
    assert len(ids) == len(set(ids))


def test_key_resources_and_activity_types():
    pack = load("construction")
    assert [(k.id, k.name, k.unit, k.tags) for k in pack.key_resources] == [
        ("tower_crane", "타워크레인", "대", ["골조", "외장"]),
        ("rebar_crew", "철근공", "명", ["철근"]),
        ("pour_crew", "타설반", "조", ["타설"]),
    ]
    types = {t.tag: t for t in pack.activity_types}
    assert {"타설", "철근", "골조", "외장", "터파기"} <= types.keys()
    assert {"타설", "콘크리트"} <= set(types["타설"].name_keywords) and types["타설"].resources == ["pour_crew"]
    assert {"철근", "배근"} <= set(types["철근"].name_keywords) and types["철근"].resources == ["rebar_crew"]
    assert {"외장", "커튼월", "패널"} <= set(types["외장"].name_keywords)
    assert {"터파기", "흙막이"} <= set(types["터파기"].name_keywords)


def test_wbs_template_has_four_parts_and_three_levels():
    nodes = load("construction").wbs_template
    by_code = {n.code: n for n in nodes}
    assert [n.name for n in nodes if n.parent is None] == ["기초", "골조", "외장·설비", "마감"]

    def depth(code):
        parent = by_code[code].parent
        return 1 if parent is None else 1 + depth(parent)

    assert max(depth(n.code) for n in nodes) == 3


def test_assumption_defaults():
    defaults = {a.key: a for a in load("construction").assumption_defaults}
    assert {"contingency_ratio", "frame_days_per_floor", "curing_days", "workdays_per_week"} <= defaults.keys()
    assert defaults["contingency_ratio"].value == "5%"
    assert all(a.label and a.value for a in defaults.values())


def test_prompt_covers_terms_calendar_wbs_and_defaults():
    text = load("construction").prompt()
    assert "건설" in text and "액티비티" in text and "주 6일" in text
    assert "골조 2개 층 위부터 설비 배관" in text and "자동 점검 안 됨" in text
    assert "외장·설비" in text and "예비 기간 비율" in text and "5%" in text


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d["rules"].append({"id": "x", "layer": "domain", "kind": "nope", "params": {}, "text": "t", "source": "분야 규칙"}), id="unknown_kind"),
        pytest.param(lambda d: d["rules"].append({"id": "x", "layer": "domain", "kind": "text_only", "text": "t", "source": "분야 규칙"}), id="missing_params"),
        pytest.param(lambda d: d["rules"].append({"id": "x", "layer": "input", "kind": "text_only", "params": {}, "text": "t", "source": "분야 규칙"}), id="wrong_layer"),
        pytest.param(lambda d: d["rules"].append({"id": "x", "layer": "domain", "kind": "text_only", "params": {}, "text": "t", "source": "프롬프트"}), id="wrong_source"),
        pytest.param(lambda d: d["rules"].append({"id": "x", "layer": "domain", "kind": "text_only", "params": {}, "text": "t", "source": "분야 규칙", "checkable": False}), id="unknown_rule_key"),
        pytest.param(lambda d: d["rules"].append(dict(d["rules"][0])), id="duplicate_rule_id"),
        pytest.param(lambda d: d["activity_types"][0].update(resources=["bulldozer"]), id="unknown_resource"),
        pytest.param(lambda d: d["key_resources"][0]["tags"].append("도장"), id="resource_tag_without_type"),
        pytest.param(lambda d: d["wbs_template"].append({"code": "9.1", "name": "x", "parent": "9"}), id="missing_wbs_parent"),
        pytest.param(lambda d: d["wbs_template"].append(dict(d["wbs_template"][0])), id="duplicate_wbs_code"),
        pytest.param(lambda d: d["key_resources"][0].update(color="red"), id="unknown_nested_key"),
    ],
)
def test_broken_pack_is_rejected(tmp_path, change):
    with pytest.raises(ValidationError):
        read_pack(_broken(tmp_path, change))


def test_real_pack_file_reads_the_same_as_load():
    assert read_pack(PACK_FILE) == load("construction")
