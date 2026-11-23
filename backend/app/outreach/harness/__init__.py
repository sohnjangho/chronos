"""연락 하네스 — 문자·카카오톡·통화에 하나(설계 「연락 하네스 — 문자·카카오톡·통화에 하나로」).

한 벌씩만 둔다: types(낱말: 등급·범위·판정·통로 인터페이스) · events(하네스 사건 기록) · registry(통로 등록부)
· gate(나가는 문) · door(들어오는 문) · tools·toolsets·facts·rules_text(도구 묶음) · review(뒤 확인).
통로(app.outreach.channels)·제공사(app.outreach.provider)·음성·글 세션(app.outreach.voice·text)이 이것을 부르고,
하네스는 그것들을 import 하지 않는다(통로는 registry 로 찾는다). 하네스는 코드만 — 제공사·LLM 을 부르지 않는다.
이 파일은 아무것도 불러오지 않는다(하위 모듈을 따로 불러 쓴다).
"""
