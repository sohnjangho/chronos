"""거는 통화(Task 88)·받는 통화(Task 95)의 음성 모델 지시문. 글 쪽과 같은 고정 줄(rules_text.fixed_lines)과 그 상대의 범위 단락
(rules_text.scope_paragraph — 둘 다 범위의 사실 수준을 받아 관리자 등급 연락처면 그 글)을 그대로 쓰고, 통화에만 있는 줄을 더한다.
번호·키는 넣지 않는다.

- **번호를 넣지 않는 것이 첫째 줄이다**(리뷰 판정 18): 이 글에는 사람이 적은 자유 글(목적·질문·피할 것·이름)만 들어가고, 넣기 전에
  redact.hide_phones 로 가린다. 가리개가 놓치는 꼴(끊어 적은 번호 등)은 CallSpec 이 그 통화의 번호로 다시 보고 만들어지지 않는다 —
  그때 일꾼은 걸지 않는다. 시각 범위는 `HH:MM~HH:MM` 으로 적는다(줄표로 이은 네 자리 둘은 대표번호로 읽힌다).
- 지키는 것은 이 글이 아니라 코드다: 도구 묶음은 등급이 정하고(toolsets.for_class), 도구는 불릴 때마다 범위를 다시 본다.
"""

from collections.abc import Iterable

from app.outreach import languages, redact, site_name
from app.outreach.harness import rules_text
from app.outreach.harness.types import FactLevel

MAX_ITEMS = 10  # 질문·피할 것 각각 이만큼까지
MAX_CHARS = 300  # 한 칸의 글자 수

# 마치는 인사(11-24 되돌이 시험: 거는 통화 두 판 모두 마지막 답을 듣자마자 말없이 end_call) — 거는·받는 통화 같은 줄
CLOSING_LINE = ("용건이 끝나면 end_call (done) 을 부르기 전에 반드시 「확인해 주셔서 감사합니다. 좋은 하루 보내세요.」처럼 짧은 "
                "마치는 인사를 소리 내어 말하고, 그 인사를 다 말한 뒤에 end_call (done) 으로 끊습니다. 마치는 인사 없이 end_call 을 "
                "부르지 않습니다(음성사서함·자동 응답일 때만 말 없이 끊습니다).")
# 묻는 말씨(11-24 PM 녹음 확인) — 물어볼 것은 사람이 전화로 말하듯, 일정표 말·출처 이름 없이
ASKING_LINE = ("물어볼 것은 전화로 사람이 말하듯 자연스럽게 묻되 뜻과 숫자·날짜는 적힌 그대로 둡니다. 작업 번호·여유(TF)·"
               "크리티컬 같은 일정표 말과 자료 출처 이름은 말하지 않습니다.")

# 범위 밖 물음의 거절 말(PM 승인 11-24): 거절이 그 낱말(「단가」)을 되풀이하면 뒤 확인이 금액 말로 센다 — 낱말 없이 넘긴다
REFUSAL = "그 부분은 제가 말씀드릴 수 없어서, 담당자께 전달하겠습니다"
REFUSAL_LINE = (f"위에서 말하지 않는다고 한 것이나 「말하지 않을 것」을 물으시면, 그 물음의 낱말을 되풀이하지 말고 「{REFUSAL}」라고만 "
                "답한 뒤 남은 물어볼 것으로 넘어갑니다.")

CALL_LINES = (
    "이 통화는 우리가 먼저 건 전화입니다. 처음 인사에서 AI 비서이고 통화가 기록된다는 것을 밝힙니다.",
    "받은 분이 찾는 분인지 먼저 확인하고 confirm_person 으로 알립니다. 확인하기 전에는 그분의 요청이나 일정을 말하지 않습니다.",
    "아래 「물어볼 것」만 묻습니다. 그 밖의 것은 묻지 않습니다.",
    ASKING_LINE,
    REFUSAL_LINE,
    "답을 들으면 record_answer 에 질문, 답, 상대가 한 말 그대로를 적습니다.",
    "음성사서함이나 자동 응답으로 넘어가면 말을 남기지 않고 end_call (voicemail) 로 끊습니다.",
    "받은 분이 담당자가 아니면 누가 담당인지 여쭤보고 find_contact 를 redirect=true 로 부릅니다.",
    "전화번호를 말하거나 받아 적지 않습니다. 새 연락처를 알려 주시면 propose_contact 로만 남깁니다.",
    CLOSING_LINE,
)


INBOUND_LINES = (  # 받는 통화에만 있는 줄(Task 95) — 도구 이름은 그 등급이 받은 것만 쓰인다(없는 도구는 부를 수 없다)
    "이 통화는 상대가 걸어 온 전화입니다. 처음 인사에서 AI 비서이고 통화가 기록된다는 것을 밝힙니다.",
    "상대가 묻는 것에만 답하고, 아래 범위 밖의 것은 「말씀드릴 수 없는 내용입니다」라고 답합니다.",
    "전화번호를 말하거나 받아 적지 않습니다.",
    "음성사서함이나 자동 응답이면 말을 남기지 않고 end_call 로 끊습니다.",
    CLOSING_LINE,
)


def _clean(text: object) -> str:
    """사람이 적은 글 한 칸: 번호를 가리고 줄 바꿈을 빈칸으로, 길면 자른다."""
    if not isinstance(text, str):
        return ""
    return " ".join(redact.hide_phones(text).split())[:MAX_CHARS]


def _items(values: Iterable[object] | None) -> list[str]:
    cleaned = [_clean(value) for value in (values or [])]
    return [value for value in cleaned if value][:MAX_ITEMS]


def outbound(site: str, contact_name: str, role_title: str, company: str, purpose: str,
             questions: Iterable[object] | None, avoid: Iterable[object] | None, language: str,
             reference: dict[str, str] | None = None, facts: FactLevel = "trade") -> str:
    """거는 통화의 지시문 한 덩어리. 번호·키 없음(자유 글은 가린 뒤에 넣는다). site 는 부를 이름(site_name.spoken),
    reference 는 현장 참고 자료(site_name.reference — 지시가 아닌 자료 칸으로 넣는다). facts 는 door.outbound_scope 의
    grant_facts(관리자 등급 연락처면 all — 그 단락과 고정 줄)."""
    who = " · ".join(part for part in (_clean(contact_name), _clean(role_title), _clean(company)) if part)
    lines = [
        "당신은 건설 현장 일정 담당 ChronOS AI 비서입니다. 전화로 협력사 담당자에게 일정을 확인합니다.",
        f"현장: {_clean(site)}",
        f"건 분: {who}",
        f"통화 목적: {_clean(purpose) or '일정 확인'}",
        languages.line(language, languages.SPEAK),  # 「상대의 언어: en(영어). 영어로 말합니다.」(Task 100 — 글 쪽과 같은 상수)
        *site_name.reference_lines(reference),
        "",
        rules_text.scope_paragraph("outbound", facts),
        *rules_text.fixed_lines("outbound", facts),
        *CALL_LINES,
    ]
    asked = _items(questions)
    if asked:
        lines += ["", "물어볼 것:", *(f"- {item}" for item in asked)]
    kept = _items(avoid)
    if kept:
        lines += ["", "말하지 않을 것:", *(f"- {item}" for item in kept)]
    return "\n".join(lines)


def inbound(caller_class: str, site: str | None, name: str | None, language: str,
            reference: dict[str, str] | None = None, facts: FactLevel = "trade") -> str:
    """받는 통화의 지시문(Task 95). 범위 단락·고정 줄은 하네스의 rules_text 그대로, 등급 이름·번호는 글에 없다. site·name 은
    번호로 정한 상대가 한 현장·한 사람일 때만 넣는다(자유 글은 가린 뒤에). reference(현장 참고 자료)는 현장이 있을 때만.
    facts 는 그 상대 범위의 Scope.grant_facts(관리자 등급이면 all — 그 단락과 고정 줄). 등급표 밖이면 ValueError."""
    lines = ["당신은 건설 현장 일정 담당 ChronOS AI 비서입니다. 걸려 온 전화를 받아 일정에 관한 물음에 답합니다."]
    if _clean(site):
        lines += [f"현장: {_clean(site)}", *site_name.reference_lines(reference)]
    if _clean(name):
        lines.append(f"상대 이름(주소록): {_clean(name)}")
    lines += [languages.line(language, languages.SPEAK), "", rules_text.scope_paragraph(caller_class, facts),
              *rules_text.fixed_lines(caller_class, facts), *INBOUND_LINES]
    return "\n".join(lines)
