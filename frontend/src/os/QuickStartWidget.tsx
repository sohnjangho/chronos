// 바탕화면 우측 상단 「빠른 시작」 위젯: 새 프로젝트 직접/AI 생성 및 핵심 화면 바로 열기.
import { useCurrentSchedule } from './currentSchedule';
import { useWindows } from './windowStore';

export default function QuickStartWidget() {
  const open = useWindows((s) => s.open);
  const openDirectModal = () => useCurrentSchedule.getState().openNewProjectModal('direct');
  const startAiProject = () => {
    useCurrentSchedule.getState().enterNewProjectMode();
    void import('../programs/chat/chatStore').then(({ useChat }) => useChat.getState().newChat(null));
    open('chat');
  };

  return (
    <section className="os-widget os-quick-widget" aria-label="빠른 시작">
      <div className="os-widget-title">빠른 시작</div>
      <ul className="os-widget-list">
        <li>
          <button type="button" className="os-widget-item os-quick-item" onClick={openDirectModal}>
            <span className="os-widget-name">+ 새 프로젝트 만들기</span>
            <span className="os-quick-desc">빈 프로젝트 생성 · 직접 일정 구성</span>
          </button>
        </li>
        <li>
          <button type="button" className="os-widget-item os-quick-item" onClick={startAiProject}>
            <span className="os-widget-name">✦ AI 일정 생성</span>
            <span className="os-quick-desc">R&amp;D · 인허가 · 조달 · SW · 제조 · 건설</span>
          </button>
        </li>
        <li>
          <button type="button" className="os-widget-item os-quick-item" onClick={() => open('explorer')}>
            <span className="os-widget-name">탐색기</span>
            <span className="os-quick-desc">프로젝트 목록 · 버전 관리</span>
          </button>
        </li>
        <li>
          <button type="button" className="os-widget-item os-quick-item" onClick={() => open('gantt')}>
            <span className="os-widget-name">간트차트</span>
            <span className="os-quick-desc">현재 선택된 프로젝트 타임라인</span>
          </button>
        </li>
      </ul>
    </section>
  );
}
