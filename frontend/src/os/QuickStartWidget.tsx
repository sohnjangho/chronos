// 바탕화면 우측 상단 「빠른 시작」 위젯: 처음 쓰는 사용자·심사위원도 핵심 기능으로 바로 진입.
import { useWindows } from './windowStore';

const SHORTCUTS = [
  { id: 'chat', title: '에이전트 대화', desc: '새 일정 만들기 · 질문 · 파일 첨부' },
  { id: 'library', title: '자료함', desc: '시방서 · 도면 · 현장 사진 찾기' },
  { id: 'progress', title: '공정률', desc: 'S-커브 · SPI · 3주 룩어헤드' },
  { id: 'delays', title: '지연 기록', desc: '지연 영향 분석 · 만회 계획' },
] as const;

export default function QuickStartWidget() {
  const open = useWindows((s) => s.open);
  return (
    <section className="os-widget os-quick-widget" aria-label="빠른 시작">
      <div className="os-widget-title">빠른 시작</div>
      <ul className="os-widget-list">
        {SHORTCUTS.map((s) => (
          <li key={s.id}>
            <button type="button" className="os-widget-item os-quick-item" onClick={() => open(s.id)}>
              <span className="os-widget-name">{s.title}</span>
              <span className="os-quick-desc">{s.desc}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
