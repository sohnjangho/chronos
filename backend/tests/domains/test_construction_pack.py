"""건설 분야 묶음(construction/pack.yaml): 검사·내용·에이전트 지시문 글."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import app.domains
from app.domains import loader
from app.domains.loader import UnknownDomain, domains, load, read_pack
from app.harness import conditions
from app.harness.conditions import Condition

PACK_FILE = Path(app.domains.__file__).parent / "construction" / "pack.yaml"
CURING_TEXT = "슬래브 거푸집 해체는 타설 뒤 7일 이상 습윤 양생을 거친 뒤에 한다 (다음 층 철근·거푸집 작업은 막지 않는다)"


def _changed(tmp_path: Path, change) -> Path:
    """진짜 묶음을 읽어 change(dict) 로 고친 뒤 임시 파일에 쓴다."""
    data = yaml.safe_load(PACK_FILE.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _rule(rid: str, kind: str, params: dict, text: str = "t", **extra) -> dict:
    return {"id": rid, "layer": "domain", "kind": kind, "params": params, "text": text, "source": "분야 규칙", **extra}


def _tags(name: str) -> set[str]:
    """액티비티 이름에 붙을 작업 유형(name_keywords 가운데 하나가 들어 있으면)."""
    return {t.tag for t in load("construction").activity_types if any(k in name for k in t.name_keywords)}


# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_construction_rules_are_valid_conditions():
    assert all(Condition.from_dict(r) for r in load("construction").rules_raw)


def test_pack_rejects_unknown_keys(tmp_path):
    path = _changed(tmp_path, lambda d: d.update(questions=[{"id": "scope"}]))
    with pytest.raises(ValidationError, match="questions"):
        read_pack(path)


def test_rules_round_trip_through_condition():
    for raw in load("construction").rules_raw:
        c = Condition.from_dict(raw)
        assert Condition.from_dict(c.to_dict()) == c
        assert {k: c.to_dict()[k] for k in raw} == raw


def test_prompt_mentions_key_resources_and_the_curing_rule():
    text = load("construction").prompt()
    assert all(name in text for name in ["타워크레인", "철근공", "타설반", "형틀목공"])
    assert CURING_TEXT in text


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


def test_domains_lists_the_packs():
    assert domains() == ["construction", "manufacturing"]


def test_unknown_domain():
    with pytest.raises(UnknownDomain):
        load("farm")
    with pytest.raises(UnknownDomain):
        load("../domains")


def test_load_reads_the_file_once(monkeypatch):
    loader._load.cache_clear()
    calls = []
    real = loader.read_pack
    monkeypatch.setattr(loader, "read_pack", lambda path: calls.append(path) or real(path))
    assert load("construction") == load("construction")
    assert len(calls) == 1


def test_cached_pack_cannot_be_corrupted():
    pack = load("construction")
    pack.rules_raw[0]["text"] = "고침"
    pack.rules_raw[0]["params"]["x"] = 1
    pack.terms["activity"] = "고침"
    pack.key_resources[0].tags.append("고침")
    pack.activity_types[0].name_keywords.clear()
    again = load("construction")
    assert again.rules_raw[0]["text"] != "고침" and "x" not in again.rules_raw[0]["params"]
    assert again.terms["activity"] == "액티비티" and "고침" not in again.key_resources[0].tags
    assert again.activity_types[0].name_keywords


def test_pack_reloads_from_its_own_dump(tmp_path):
    pack = load("construction")
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(pack.model_dump(by_alias=True, mode="json"), allow_unicode=True), encoding="utf-8")
    assert read_pack(path) == pack


def test_pack_basics():
    pack = load("construction")
    assert (pack.id, pack.name) == ("construction", "건설")
    assert {"activity": "액티비티", "resource": "자원", "deadline": "준공", "actual": "실적"}.items() <= pack.terms.items()
    assert "progress" not in pack.terms
    assert (pack.default_calendar.days_per_week, pack.default_calendar.holidays) == (6, "KR")


def test_rules():
    rules = load("construction").rules_raw
    by_id = {r["id"]: r for r in rules}
    curing = by_id["construction.curing"]
    assert (curing["kind"], curing["params"], curing["text"]) == ("text_only", {}, CURING_TEXT)
    assert not any(r["kind"] == "min_gap" for r in rules)  # 양생은 다음 층 작업을 막지 않는다
    assert any(r["kind"] == "text_only" and r["text"] == "설비 배관은 골조보다 2개 층 아래에서 따라간다" for r in rules)
    for r in rules:
        assert set(r) == {"id", "layer", "kind", "params", "text", "source", "enabled"}
        assert (r["layer"], r["source"], r["enabled"]) == ("domain", "분야 규칙", True)
    assert len(by_id) == len(rules)


def test_key_resources_and_activity_types():
    pack = load("construction")
    assert [(k.id, k.name, k.unit, sorted(k.tags)) for k in pack.key_resources] == [
        ("tower_crane", "타워크레인", "대", sorted(["골조", "철근", "거푸집", "외장"])),
        ("rebar_crew", "철근공", "명", ["철근"]),
        ("form_crew", "형틀목공", "명", ["거푸집"]),
        ("pour_crew", "타설반", "조", ["타설"]),
    ]
    types = {t.tag: t for t in pack.activity_types}
    assert {"타설", "철근", "거푸집", "골조", "외장", "터파기"} <= types.keys()
    assert (types["타설"].name_keywords, types["타설"].resources) == (["타설"], ["pour_crew"])
    assert {"철근", "배근"} <= set(types["철근"].name_keywords)
    assert set(types["철근"].resources) == {"rebar_crew", "tower_crane"}
    assert (types["거푸집"].name_keywords, set(types["거푸집"].resources)) == (["거푸집"], {"tower_crane", "form_crew"})
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


def test_wbs_leaves_and_activity_types_fit_together():
    nodes = load("construction").wbs_template
    parents = {n.parent for n in nodes}
    leaves = [n.name for n in nodes if n.code not in parents]
    assert not any("양생" in name for name in leaves)  # 양생은 타설 액티비티에 넣지 않는다
    assert _tags("버림 콘크리트") == set()  # 버림 콘크리트는 타설반 작업이 아니다
    assert _tags("기준층 콘크리트 타설") == {"타설"}
    assert _tags("기준층 거푸집") == {"거푸집"} and _tags("기준층 철근 배근") == {"철근"}


def test_assumption_defaults():
    defaults = {a.key: a for a in load("construction").assumption_defaults}
    assert {"contingency_ratio", "frame_days_per_floor", "curing_days", "workdays_per_week"} <= defaults.keys()
    assert defaults["contingency_ratio"].value == "5%" and "준공 직전에 한데 모아 둔다" in defaults["contingency_ratio"].note
    assert defaults["curing_days"].value == "7일"
    assert "다음 층 작업을 막는 기간이 아니다" in defaults["curing_days"].note
    assert all(a.label and a.value for a in defaults.values())


def test_prompt_covers_terms_calendar_wbs_and_defaults():
    text = load("construction").prompt()
    assert "건설" in text and "액티비티" in text and "주 6일" in text
    assert "설비 배관은 골조보다 2개 층 아래에서 따라간다" in text and "자동 점검 안 됨" in text
    assert "외장·설비" in text and "예비 기간 비율" in text and "5%" in text


def test_prompt_shows_how_checkable_rules_are_checked(tmp_path):
    def add(d):
        d["rules"].append(_rule("x.gap", "min_gap", {"after_tag": "타설", "days": 7, "unit": "workdays"}, "간격"))
        d["rules"].append(_rule("x.cap", "resource_cap", {"resource_id": "tower_crane", "capacity": 2}, "크레인 두 대"))

    lines = read_pack(_changed(tmp_path, add)).prompt().splitlines()
    gap = next(x for x in lines if x.startswith("- 간격"))
    assert "min_gap" in gap and "after_tag=타설" in gap and "days=7" in gap and "unit=workdays" in gap
    assert "자동 점검" in gap and "자동 점검 안 됨" not in gap
    cap = next(x for x in lines if x.startswith("- 크레인 두 대"))
    assert "resource_id=tower_crane" in cap and "capacity=2" in cap
    curing = next(x for x in lines if x.startswith(f"- {CURING_TEXT}"))
    assert "자동 점검 안 됨" in curing and "=" not in curing


def test_known_param_keys_match_the_harness():
    harness = {kind: {key for key, _, _ in spec} for kind, spec in conditions._PARAMS.items()}
    assert {k: v for k, v in loader.PARAM_KEYS.items() if k in harness} == harness


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d["rules"].append(_rule("x", "nope", {})), id="unknown_kind"),
        pytest.param(lambda d: d["rules"].append({k: v for k, v in _rule("x", "text_only", {}).items() if k != "params"}), id="missing_params"),
        pytest.param(lambda d: d["rules"].append({**_rule("x", "text_only", {}), "layer": "input"}), id="wrong_layer"),
        pytest.param(lambda d: d["rules"].append({**_rule("x", "text_only", {}), "source": "프롬프트"}), id="wrong_source"),
        pytest.param(lambda d: d["rules"].append(_rule("x", "text_only", {}, checkable=False)), id="unknown_rule_key"),
        pytest.param(lambda d: d["rules"].append(_rule("x", "min_gap", {"after_tag": "타설", "days": 7, "unti": "workdays"})), id="param_typo"),
        pytest.param(lambda d: d["rules"].append(_rule("x", "text_only", {"days": 7})), id="params_on_text_only"),
        pytest.param(lambda d: d["rules"].append(_rule("x", "min_gap", {"after_tag": "타설", "days": -1})), id="bad_param_value"),
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
        read_pack(_changed(tmp_path, change))


def test_real_pack_file_reads_the_same_as_load():
    assert read_pack(PACK_FILE) == load("construction")
