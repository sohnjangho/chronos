# ChronOS 통합 커스텀 아이콘 안내

이 폴더(`frontend/src/assets/icons/`)에 아래 **프로그램 ID와 같은 이름의 이미지 파일**(`<id>.png`, `.webp`, `.svg`, `.jpg`)을 넣으면 **데스크톱(Dock · 앱 서랍 · 메뉴바 · 검색), 태블릿(아이콘 레일 · 전체 앱), 스마트폰(하단 탭바 · 전체 앱 · 상단 바)** 에 코드 수정 없이 **모든 기기에서 동일한 아이콘**으로 자동 적용됩니다.

커스텀 파일이 없거나 이미지 로드에 실패한 슬롯은 자동으로 내장 벡터 SVG 타일로 표시됩니다.

---

## 제작 규격 권장사항 (Apple HIG · Material Design 3 기준)

- **해상도 / 비율**: `1024×1024 px` 또는 `512×512 px` (`1:1` 정사각형 PNG/WebP, SVG 가능)
- **안전 영역 (Safe Area)**: 핵심 심볼은 전체 캔버스의 **중앙 80% 영역** 안에 배치해 주세요 (모서리 잘림 방지).
- **모서리 형태**: OS UI가 모든 기기에서 동일한 스퀴클/라운드 비율(`border-radius: calc(size * 0.28)`)로 마스킹하므로 **모서리를 미리 깎지 않은 풀블리드 사각형 배경** 또는 **투명 배경 PNG** 모두 깔끔하게 적용됩니다.
- **일관성**: 18개 아이콘 모두 동일한 조명 각도, 선 굵기, 재질감(예: 3D 글래스모피즘, 플랫 그라데이션, 메탈릭 벡터 등)을 공유하도록 생성하면 OS 통일감이 극대화됩니다.

---

## 아이콘 파일명 및 영문 생성 설명 (총 18종)

| 파일명 | 프로그램 | 기본 톤 | English Description (for AI Icon Generation) |
| :--- | :--- | :--- | :--- |
| `chat.png` | 에이전트 대화 | Violet | **AI Schedule Agent Chat** — glowing conversational speech bubbles with a subtle AI neural sparkle/star inside, representing an intelligent assistant for project scheduling. |
| `questionnaire.png` | 질문지 | Teal | **Project Intake Questionnaire** — sleek structured checklist form or clipboard with checkmarks and input lines for gathering project scheduling requirements. |
| `workflow.png` | 워크플로우 | Indigo | **Automated Agent Workflow** — connected luminous nodes and branching flow arrows depicting a multi-step automated AI pipeline. |
| `approvals.png` | 승인함 | Amber | **Approval Inbox** — refined inbox tray or verification badge with a crisp approval checkmark for reviewing and signing off schedule changes. |
| `explorer.png` | 탐색기 | Sky | **Project File Explorer** — modern layered folders representing a structured project workspace and schedule file browser. |
| `settings.png` | 설정 | Slate | **System & Agent Settings** — precision minimalist gear wheel or fine control sliders representing OS configuration and preferences. |
| `devconsole.png` | 개발 콘솔 | Graphite | **Developer & LLM Console (Admin)** — sleek dark terminal command window displaying a crisp `>_` prompt symbol for developer diagnostics and agent tuning. |
| `schedule-table.png` | 스케줄 | Blue | **WBS Activity Schedule Table** — clean calendar-table grid with neatly aligned rows and task bars representing a master project activity schedule. |
| `gantt.png` | 간트차트 | Orange | **Gantt Timeline Chart** — staggered horizontal timeline bars linked by crisp dependency connectors visualizing project phases over time. |
| `cpm.png` | CPM | Fuchsia | **Critical Path Method (CPM) Network** — interconnected project network nodes with one glowing highlighted critical path route running from start to finish. |
| `progress.png` | 공정률 | Rose | **Progress & S-Curve Analytics** — smooth upward S-curve progress graph with a completion milestone dot tracking planned vs. actual project completion. |
| `compare.png` | 비교판 | Lime | **Baseline vs. Revised Schedule Comparison** — balanced split-view comparison panels with contrasting delta bars highlighting schedule revisions. |
| `conditions.png` | 조건·규칙 | Green | **Scheduling Constraints & Rules** — clean rule shield or calendar grid paired with constraint sliders representing working-day rules and logic constraints. |
| `delays.png` | 지연 기록 | Brown | **Delay Log & Impact Tracker** — precision clock face paired with a subtle alert indicator representing schedule slippage tracking and delay cause analysis. |
| `library.png` | 자료함 | Cyan | **Engineering Knowledge Library** — modern stacked archive documents or sleek digital book spine with a subtle search/index glow for reference drawings and project specs. |
| `apps.png` | 전체 앱 | Slate | **App Launcher Grid (System)** — symmetrical 2×2 rounded-square grid emblem used to open the full ChronOS application drawer across all devices. |
| `field.png` | 현장 점검 *(선택)* | Rose | **Mobile Field Inspection & Check-in (Optional)** — smartphone camera and hard-hat checklist symbol representing daily construction site progress check-ins and AI photo inspection (falls back to `progress` if omitted). |
| `chronos.png` | ChronOS 마크 *(선택)* | Blue | **ChronOS OS Brand Mark (Optional)** — minimalist futuristic circular timepiece or orbital clock emblem representing the ChronOS AI Schedule Agent OS. |
