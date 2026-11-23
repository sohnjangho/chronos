"""거는 통화의 음성 모델 지시문(Task 88). 글 쪽과 같은 고정 줄(rules_text.FIXED)과 우리가 건 상대의 범위 단락을 그대로 쓰고,
통화에만 있는 줄을 더한다. 번호·키는 넣지 않는다.

- **번호를 넣지 않는 것이 첫째 줄이다**(리뷰 판정 18): 이 글에는 사람이 적은 자유 글(목적·질문·피할 것·이름)만 들어가고, 넣기 전에
  redact.hide_phones 로 가린다. 가리개가 놓치는 꼴(끊어 적은 번호 등)은 CallSpec 이 그 통화의 번호로 다시 보고 만들어지지 않는다 —
  그때 일꾼은 걸지 않는다. 시각 범위는 `HH:MM~HH:MM` 으로 적는다(줄표로 이은 네 자리 둘은 대표번호로 읽힌다).
- 지키는 것은 이 글이 아니라 코드다: 도구 묶음은 등급이 정하고(toolsets.for_class), 도구는 불릴 때마다 범위를 다시 본다.
"""

from collections.abc import Iterable

from app.outreach import redact
from app.outreach.harness import rules_text

MAX_ITEMS = 10  # 질문·피할 것 각각 이만큼까지
MAX_CHARS = 300  # 한 칸의 글자 수

CALL_LINES = (
    "이 통화는 우리가 먼저 건 전화입니다. 처음 인사에서 AI 비서이고 통화가 기록된다는 것을 밝힙니다.",
    "받은 분이 찾는 분인지 먼저 확인하고 confirm_person 으로 알립니다.",
    "아래 「물어볼 것」만 묻습니다. 그 밖의 것은 묻지 않습니다.",
    "답을 들으면 record_answer 에 질문, 답, 상대가 한 말 그대로를 적습니다.",
    "음성사서함이나 자동 응답으로 넘어가면 말을 남기지 않고 end_call (voicemail) 로 끊습니다.",
    "받은 분이 담당자가 아니면 누가 담당인지 여쭤보고 find_contact 를 redirect=true 로 부릅니다.",
    "전화번호를 말하거나 받아 적지 않습니다. 새 연락처를 알려 주시면 propose_contact 로만 남깁니다.",
    "용건이 끝나면 인사하고 end_call (done) 으로 끊습니다.",
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
             questions: Iterable[object] | None, avoid: Iterable[object] | None, language: str) -> str:
    """거는 통화의 지시문 한 덩어리. 번호·키 없음(자유 글은 가린 뒤에 넣는다)."""
    who = " · ".join(part for part in (_clean(contact_name), _clean(role_title), _clean(company)) if part)
    lines = [
        "당신은 건설 현장 일정 담당 ChronOS AI 비서입니다. 전화로 협력사 담당자에게 일정을 확인합니다.",
        f"현장: {_clean(site)}",
        f"건 분: {who}",
        f"통화 목적: {_clean(purpose) or '일정 확인'}",
        f"대화 언어 코드: {_clean(language) or 'ko'}",
        "",
        rules_text.scope_paragraph("outbound"),
        *rules_text.FIXED.values(),
        *CALL_LINES,
    ]
    asked = _items(questions)
    if asked:
        lines += ["", "물어볼 것:", *(f"- {item}" for item in asked)]
    kept = _items(avoid)
    if kept:
        lines += ["", "말하지 않을 것:", *(f"- {item}" for item in kept)]
    return "\n".join(lines)
