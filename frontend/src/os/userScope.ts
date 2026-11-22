// 사용자 단위 화면 상태의 시작과 끝. 이 모듈을 불러오면(App·Desktop) 한 번 등록된다.
import { useAgentView } from './agentView';
import { useCurrentSchedule } from './currentSchedule';
import { useDock } from './dockStore';
import { onUserChange, useSession } from './session';
import { resetShellState } from './shellReset';
import { useTabletRail } from './tabletRailStore';
import { useTheme } from './theme';
import { useDeviceMode } from './useIsMobile';
import { useZoom } from './zoom';

/** 그 사람의 저장된 테마·배율·Dock·태블릿 메뉴·현장·에이전트 뷰·화면 형태 설정을 읽는다(null 이면 기본값). */
function applyUser(userId: number | null) {
  useTheme.getState().load(userId);
  useZoom.getState().load(userId);
  useDock.getState().load(userId);
  useTabletRail.getState().load(userId);
  useCurrentSchedule.getState().load(userId);
  useAgentView.getState().load(userId);
  useDeviceMode.getState().load(userId);
}

let prevUserId: number | null = useSession.getState().session?.user.id ?? null;

// 로그아웃·다른 사람 로그인: 세션을 바꾸는 같은 호출 안에서(그리기 전에) 앞 사람 상태를 비우고 다음 사람 것을 읽는다.
// 단, 로그인 화면에서 사용자가 미리 고른 접속 화면 형태(데스크톱·태블릿·폰)는 첫 로그인 시 유지한다.
onUserChange((next) => {
  const nextId = next?.user.id ?? null;
  const signingIn = prevUserId === null && nextId !== null;
  const loginDeviceChoice = signingIn ? useDeviceMode.getState().mode : 'auto';
  prevUserId = nextId;
  resetShellState();
  applyUser(nextId);
  if (signingIn && loginDeviceChoice !== 'auto') {
    useDeviceMode.getState().setMode(loginDeviceChoice);
  }
});

// 처음 열 때 저장된 세션이 있으면 그 사람 것을 읽는다.
applyUser(useSession.getState().session?.user.id ?? null);
