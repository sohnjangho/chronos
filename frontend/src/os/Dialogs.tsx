import { useEffect, useRef, type ReactNode } from 'react';
import { version } from '../../package.json';
import Button from '../shared/ui/Button';
import { ChronosMark } from './icons';
import ProgramIcon from './ProgramIcon';
import { useModalFocus } from './modalFocus';
import { getProgram } from './registry';
import { useShell } from './shell';

export const SHORTCUTS: [string, string][] = [
  ['Ctrl+K', '검색 열기 (바탕화면에서는 / 도 됨)'],
  ['Ctrl+Alt+S', '좌우 분할'],
  ['Ctrl+Alt+G', '격자 정렬'],
  ['Ctrl+Alt+C', '계단식 정렬'],
  ['Ctrl+Alt+M', '모두 최소화'],
  ['Ctrl+Alt+Q', '모두 닫기'],
  ['Ctrl+Alt+W', '창 닫기'],
  ['Ctrl+`', '다음 창'],
  ['Ctrl+Alt+=', '창 배율 확대'],
  ['Ctrl+Alt+-', '창 배율 축소'],
  ['Ctrl+Alt+0', '창 배율 100%'],
  ['Ctrl+Alt+D', 'Dock 보이기·숨기기(확대한 창이 있을 때)'],
  ['Ctrl+Alt+.', 'Context 패널 열기·닫기'],
];

function InfoDialog({ name, icon, children }: { name: string; icon: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const close = () => useShell.getState().setDialog(null);
  const trap = useModalFocus(ref);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div
      ref={ref}
      className="os-about"
      role="dialog"
      aria-modal="true"
      aria-label={name}
      tabIndex={-1}
      onKeyDown={(e) => (e.key === 'Escape' ? close() : trap(e))}
    >
      <div className="os-about-head">
        {icon}
        <div className="os-about-name">{name.replace(/ 정보$/, '')}</div>
      </div>
      <div className="os-about-body">{children}</div>
      <Button onClick={close}>닫기</Button>
    </div>
  );
}

/** 셸 대화상자: ChronOS 정보 · 프로그램 정보 · 키보드 단축키. */
export default function ShellDialogs() {
  const dialog = useShell((s) => s.dialog);
  if (!dialog) return null;
  if (dialog.kind === 'about')
    return (
      <InfoDialog name="ChronOS 정보" icon={<ChronosMark size={64} />}>
        <div>버전 {version}</div>
        <div className="os-about-desc">일정을 만들고, 지키고, 고치는 에이전트 OS</div>
      </InfoDialog>
    );
  if (dialog.kind === 'program') {
    const p = getProgram(dialog.programId);
    return (
      <InfoDialog name={`${p?.name ?? dialog.programId} 정보`} icon={p && <ProgramIcon program={p} size={64} />}>
        <div>{p?.kind === 'work' ? '업무 프로그램' : '시스템 프로그램'}</div>
        <div className="os-about-desc">{dialog.programId}</div>
      </InfoDialog>
    );
  }
  return (
    <InfoDialog name="키보드 단축키" icon={null}>
      <table className="os-keys">
        <tbody>
          {SHORTCUTS.map(([keys, what]) => (
            <tr key={keys}>
              <th scope="row">
                <kbd>{keys}</kbd>
              </th>
              <td>{what}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </InfoDialog>
  );
}
