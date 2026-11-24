"""연락 하네스의 상황 대본(Task 86 — 글 열, 음성 열은 Task 97 이 같은 대본으로).

- situations — 상황 S-01…S-24 를 한 번만 쓴다(매체를 모르는 꼴: Them · Model · ModelSays · Wait · Permit, 기대 Check).
- drive_text — 대본 하나를 글 길로 돌린다: 임시 DB · 가상 주소록 · 가짜 제공사(받은 문자) · 일꾼의 받기 판정 · 응대(SimulatedText) ·
  도구 · 뒤 확인 · 나가는 문 · FakeChannel. 시험(pytest)이나 모래상자 프로세스(CHRONOS_HARNESS_SANDBOX=1)에서만 돈다.
- drive_voice — 같은 대본을 통화 길로 돌린다(Task 97): 문 → 통화 일꾼(run_one) / 벨 → 받기 전 판정(inbound.on_incoming) → 가짜 통화
  (SimulatedVoice) → 통화 뒤 일(after.finish — 요약 모델은 가짜). 같은 울타리(시험·모래상자 프로세스에서만).
- grid — 설계 표 그대로의 칸(CELLS), run_cell, run_all(네 열), 한 채널에만 있는 경우(CHANNEL_ONLY — 문자·통화·카카오톡).
- breaks — 지키는 곳 하나를 그 실행 안에서만 무른다(BREAKS · 음성 열의 VOICE_BREAKS). 시험과 모래상자 프로세스에서만 불러올 수
  있다(서버는 부르지 않는다).
"""
