import { useState, type ReactNode } from 'react';
import type { ProgramProps } from '../../os/registry';
import { useSession } from '../../os/session';
import AccountSection from './AccountSection';
import ApprovalSection, { MeSection } from './ApprovalSection';
import LlmSection, { AssignSection } from './LlmSection';
import { resolveSection, visibleSections, type SectionId } from './model';
import './settings.css';

const VIEWS: Record<SectionId, () => ReactNode> = {
  me: () => <MeSection />,
  llm: () => <LlmSection />,
  assign: () => <AssignSection />,
  account: () => <AccountSection />,
  approval: () => <ApprovalSection />,
};

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
      {s.label}
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
