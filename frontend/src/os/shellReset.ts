import { useAgentView } from './agentView';
import { useAiChat } from './aiChat';
import { useApprovals } from './approvals';
import { useContextPanel } from './contextStore';
import { useCurrentSchedule } from './currentSchedule';
import { useEvidence } from './evidence';
import { useSchedulePreview } from './schedulePreview';
import { useShell } from './shell';
import { useUiContext } from './uiContext';
import { useDeviceMode } from './useIsMobile';
import { useWindows } from './windowStore';

/**
 * 앞 사용자의 화면 상태를 모두 지운다(로그아웃, 다른 사용자 로그인).
 * 창 id 가 w1 부터 다시 시작해도 앞 사람의 근거·대화가 보이지 않게 한다.
 */
export function resetShellState(): void {
  useAgentView.getState().reset();
  useAiChat.getState().reset();
  useContextPanel.getState().reset();
  useEvidence.setState({ byWindow: {} });
  useUiContext.getState().reset();
  useSchedulePreview.getState().reset();
  useShell.setState({ dialog: null, drawer: 'closed', palette: false, dockRevealed: false, announcement: '' });
  useDeviceMode.setState({ mode: 'auto' });
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useCurrentSchedule.setState({ userId: null, current: null });
}
