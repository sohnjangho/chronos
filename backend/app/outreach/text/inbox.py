"""들어온 문자를 글 세션에 넘기는 자리. 일꾼(app.outreach.worker)이 받기 판정이 engage·notice 인 문자를 저장·commit 한
뒤 이벤트 루프에서 `inbox.enqueue(message_id)` 를 부른다(모듈 속성으로 — 시험이 바꿔 끼운다).

지금은 아무것도 하지 않는다 — Task 84(글 세션·들어온 문자 응대)가 채운다. 채울 때 알아 둘 것:
- 넘어오는 줄은 이미 저장돼 있다: direction in · status received · caller_class(문이 정한 등급) · `admission` 사건 한 줄.
  받기 판정(door.admit)은 일꾼이 이미 했다 — 여기서 다시 하지 않는다(되풀이 셈이 한 번 더 세어진다).
- 서버가 오래 꺼져 있었으면 몇 시간 전 문자가 한꺼번에 넘어올 수 있다. 줄의 sent_at 이 상대가 보낸 때, created_at 이 우리가
  받은 때다.
- 이 함수가 예외를 올려도 일꾼은 멈추지 않는다(종류만 기록한다). 오래 걸리는 일은 여기서 하지 말고 줄에 넣기만 할 것.
- **enqueue 만 믿지 말 것.** 넘기기는 판정이 commit 된 **뒤 메모리에서** 일어난다 — 그 사이에 서버가 꺼지거나 enqueue 가
  예외를 올리면 그 줄은 다시 넘어오지 않는다(판정은 한 줄에 한 번뿐이다). 그래서 글 세션은 따로 쓸어야 한다: 받기 판정이
  engage·notice(`admission` 사건의 판정 allowed)이고 아직 답이 없는 받은 줄을 찾아 응대 줄에 넣을 것.
"""


def enqueue(message_id: int) -> None:
    """받은 문자 한 건을 응대 줄에 넣는다. 지금은 아무것도 하지 않는다(Task 84)."""
