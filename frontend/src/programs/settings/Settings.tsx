import { useState, type ReactNode } from 'react';
import type { ProgramProps } from '../../os/registry';
import { useSession } from '../../os/session';
import AccountSection from './AccountSection';
import AppearanceSection from './AppearanceSection';
import ApprovalSection, { MeSection } from './ApprovalSection';
import InfoSection from './InfoSection';
import LlmSection, { AssignSection } from './LlmSection';
import NotifySection from './NotifySection';
import { resolveSection, visibleSections, type SectionId } from './model';
import SchedulePrefsSection from './SchedulePrefsSection';
import './settings.css';

const VIEWS: Record<SectionId, () => ReactNode> = {
  me: () => <MeSection />,
  appearance: () => <AppearanceSection />,
  prefs: () => <SchedulePrefsSection />,
  llm: () => <LlmSection />,
  info: () => <InfoSection />,
  notify: () => <NotifySection />,
  assign: () => <AssignSection />,
  account: () => <AccountSection />,
  approval: () => <ApprovalSection />,
};

const ICON_PATHS: Record<SectionId, string[]> = {
  me: ['M12 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z', 'M5 19.5c1.3-3 4-4.5 7-4.5s5.7 1.5 7 4.5'],
  appearance: ['M12 3.5v2', 'M12 18.5v2', 'M3.5 12h2', 'M18.5 12h2', 'M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z'],
  prefs: ['M4 6h16', 'M4 12h10', 'M4 18h14', 'M18 10v8'],
  llm: ['M7 7h10v10H7z', 'M9.5 4v3', 'M14.5 4v3', 'M9.5 17v3', 'M14.5 17v3'],
  info: ['M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z', 'M12 10.5v5.5', 'M12 8h.01'],
  notify: ['M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.5H5l1.5-1.5z', 'M10 20.5a2 2 0 0 0 4 0'],
  assign: ['M4 7h6', 'M14 7h6', 'M10 7a2 2 0 1 0 4 0', 'M4 17h10', 'M18 17h2', 'M14 17a2 2 0 1 0 4 0'],
  account: ['M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M4 18.5c1-2.5 2.8-3.5 5-3.5s4 1 5 3.5', 'M16.5 9.5v4', 'M14.5 11.5h4'],
  approval: ['M12 4l6 2.5v5.5c0 4-2.5 6.8-6 8-3.5-1.2-6-4-6-8V6.5L12 4z', 'M9.5 12l1.8 1.8 3.2-3.6'],
};

function NavIcon({ id }: { id: SectionId }) {
  return (
    <svg className="st-nav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICON_PATHS[id].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/**
 * 설정 프로그램. 왼쪽에 구역 목록(나 · 관리자), 오른쪽에 고른 구역.
 * params.section 으로 구역을 바로 열고, 열린 창에 새 params 가 오면 그 구역으로 옮긴다.
 * 관리자 구역은 관리자에게만 보이고, 사용자가 부르면 내 정보로 간다.
 */
export default function Settings({ params }: ProgramProps) {
  const role = useSession((s) => s.session?.user.role) ?? 'user';
  const [section, setSection] = useState<string | undefined>(params?.section);
  const [seenParams, setSeenParams] = useState(params);
  if (params !== seenParams) {
    setSeenParams(params);
    setSection(params?.section);
  }
  const current = resolveSection(section, role);
  const sections = visibleSections(role);
  const navItem = (s: (typeof sections)[number]) => (
    <button
      key={s.id}
      type="button"
      className="st-nav-item"
      aria-current={s.id === current ? 'page' : undefined}
      onClick={() => setSection(s.id)}
    >
      <NavIcon id={s.id} />
      <span>{s.label}</span>
    </button>
  );
  return (
    <div className="st-root">
      <nav className="st-nav" aria-label="설정 구역">
        <div className="st-grp">나</div>
        {sections.filter((s) => !s.adminOnly).map(navItem)}
        {role === 'admin' && (
          <>
            <div className="st-grp">관리자</div>
            {sections.filter((s) => s.adminOnly).map(navItem)}
          </>
        )}
      </nav>
      <div className="st-main">{VIEWS[current]()}</div>
    </div>
  );
}
