// 사용자 커스텀 아이콘 자동 탐지 및 18개 프로그램·시스템 아이콘 메타데이터.
// frontend/src/assets/icons/<id>.{png,webp,svg,jpg} 에 파일을 넣으면 데스크톱·태블릿·스마트폰 모두에 동일하게 반영된다.

export interface IconSlotSpec {
  id: string;
  label: string;
  tone: string;
  optional?: boolean;
  englishDescription: string;
}

export const ICON_SLOTS: readonly IconSlotSpec[] = [
  {
    id: 'chat',
    label: '에이전트 대화',
    tone: 'violet',
    englishDescription:
      'AI Schedule Agent Chat — glowing conversational speech bubbles with a subtle AI neural sparkle/star inside, representing an intelligent assistant for project scheduling.',
  },
  {
    id: 'questionnaire',
    label: '질문지',
    tone: 'teal',
    englishDescription:
      'Project Intake Questionnaire — sleek structured checklist form or clipboard with checkmarks and input lines for gathering project scheduling requirements.',
  },
  {
    id: 'workflow',
    label: '워크플로우',
    tone: 'indigo',
    englishDescription:
      'Automated Agent Workflow — connected luminous nodes and branching flow arrows depicting a multi-step automated AI pipeline.',
  },
  {
    id: 'approvals',
    label: '승인함',
    tone: 'amber',
    englishDescription:
      'Approval Inbox — refined inbox tray or verification badge with a crisp approval checkmark for reviewing and signing off schedule changes.',
  },
  {
    id: 'explorer',
    label: '탐색기',
    tone: 'sky',
    englishDescription:
      'Project File Explorer — modern layered folders representing a structured project workspace and schedule file browser.',
  },
  {
    id: 'settings',
    label: '설정',
    tone: 'slate',
    englishDescription:
      'System & Agent Settings — precision minimalist gear wheel or fine control sliders representing OS configuration and preferences.',
  },
  {
    id: 'devconsole',
    label: '개발 콘솔',
    tone: 'graphite',
    englishDescription:
      'Developer & LLM Console (Admin) — sleek dark terminal command window displaying a crisp ">_" prompt symbol for developer diagnostics and agent tuning.',
  },
  {
    id: 'schedule-table',
    label: '스케줄',
    tone: 'blue',
    englishDescription:
      'WBS Activity Schedule Table — clean calendar-table grid with neatly aligned rows and task bars representing a master project activity schedule.',
  },
  {
    id: 'gantt',
    label: '간트차트',
    tone: 'orange',
    englishDescription:
      'Gantt Timeline Chart — staggered horizontal timeline bars linked by crisp dependency connectors visualizing project phases over time.',
  },
  {
    id: 'cpm',
    label: 'CPM',
    tone: 'fuchsia',
    englishDescription:
      'Critical Path Method (CPM) Network — interconnected project network nodes with one glowing highlighted critical path route running from start to finish.',
  },
  {
    id: 'progress',
    label: '공정률',
    tone: 'rose',
    englishDescription:
      'Progress & S-Curve Analytics — smooth upward S-curve progress graph with a completion milestone dot tracking planned vs. actual project completion.',
  },
  {
    id: 'compare',
    label: '비교판',
    tone: 'lime',
    englishDescription:
      'Baseline vs. Revised Schedule Comparison — balanced split-view comparison panels with contrasting delta bars highlighting schedule revisions.',
  },
  {
    id: 'conditions',
    label: '조건·규칙',
    tone: 'green',
    englishDescription:
      'Scheduling Constraints & Rules — clean rule shield or calendar grid paired with constraint sliders representing working-day rules and logic constraints.',
  },
  {
    id: 'delays',
    label: '지연 기록',
    tone: 'brown',
    englishDescription:
      'Delay Log & Impact Tracker — precision clock face paired with a subtle alert indicator representing schedule slippage tracking and delay cause analysis.',
  },
  {
    id: 'reports',
    label: '보고서',
    tone: 'emerald',
    englishDescription:
      'Monthly & Quarterly Schedule Reports — clean A4 executive progress report sheet with structured tables and S-curve summary charts.',
  },
  {
    id: 'library',
    label: '자료함',
    tone: 'cyan',
    englishDescription:
      'Engineering Knowledge Library — modern stacked archive documents or sleek digital book spine with a subtle search/index glow for reference drawings and project specs.',
  },
  {
    id: 'apps',
    label: '전체 앱',
    tone: 'slate',
    englishDescription:
      'App Launcher Grid (System) — symmetrical 2x2 rounded-square grid emblem used to open the full ChronOS application drawer across all devices.',
  },
  {
    id: 'field',
    label: '현장 점검',
    tone: 'rose',
    optional: true,
    englishDescription:
      'Mobile Field Inspection & Check-in (Optional) — smartphone camera and hard-hat checklist symbol representing daily construction site progress check-ins and AI photo inspection (falls back to progress if omitted).',
  },
  {
    id: 'chronos',
    label: 'ChronOS 마크',
    tone: 'blue',
    optional: true,
    englishDescription:
      'ChronOS OS Brand Mark (Optional) — minimalist futuristic circular timepiece or orbital clock emblem representing the ChronOS AI Schedule Agent OS.',
  },
] as const;

const bundled = import.meta.glob<string>('../assets/icons/*.{png,webp,svg,jpg,jpeg}', {
  eager: true,
  import: 'default',
});

const BUNDLED_ICONS: Record<string, string> = {};
for (const [filepath, url] of Object.entries(bundled)) {
  const filename = filepath.split('/').pop() ?? '';
  const stem = filename.replace(/\.[^.]+$/, '').toLowerCase();
  if (stem) BUNDLED_ICONS[stem] = url;
}

let overrides: Record<string, string> = {};

/** 테스트 및 동적 프리뷰용 런타임 아이콘 경로 덮어쓰기. */
export function setCustomIconOverrides(next: Record<string, string>): void {
  overrides = { ...next };
}

/** id 에 해당하는 사용자 커스텀 아이콘 URL (없으면 undefined). */
export function getCustomIconUrl(id: string): string | undefined {
  const key = id.toLowerCase();
  return overrides[key] ?? BUNDLED_ICONS[key];
}
