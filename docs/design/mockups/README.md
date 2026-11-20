# 화면 시안 (확정본)

PM이 2026-11-19에 고른 시안. 각 파일은 한 화면(보드)이며 FHD(1920×1080) 기준 크기다. 색·글꼴·간격은 `frontend/src/os/tokens.css` 값과 같다. 표시된 자료는 모두 가상의 예시다.

- Main / Login — OS 바탕화면 · 로그인
- ChatLarge / ChatSmall — 에이전트 대화창 (큰·작은)
- QuestionnaireB — 질문지 (B안)
- ScheduleTable / ScheduleGantt / ScheduleCPM / ScheduleProgress — 일정판 탭 넷
- ConditionsB — 조건·규칙 (겹별, B안)
- Compare · Delay · Report — 비교판 · 지연 기록 · 보고서
- Workflow · Approvals · Explorer · Notifications · Settings · DevConsoleA — 시스템 프로그램

파일은 참고용 HTML 이다(`<x-dc>` 틀과 `support.js` 없이 열면 모양 일부만 보인다). 구조와 문구, 수치 배치를 읽어 화면을 만든다.
