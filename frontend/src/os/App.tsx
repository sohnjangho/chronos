import Desktop from './Desktop';
import Login from './Login';
import MobileShell from './MobileShell';
import { usePresence } from './presence';
import TabletShell from './TabletShell';
import { useSession } from './session';
import { useActiveDevice } from './useIsMobile';
import './tokens.css';
import './os.css';
import './userScope';

/**
 * 세션이 없으면 로그인, 있으면 접속 기기(phone / tablet / desktop)에 맞는 전용 셸을 연다.
 * 로그아웃(401 포함)이나 다른 사람 로그인 때 앞 사람의 창·패널·근거·대화·현장·겹화면을 비우는 일은 userScope 가 한다.
 */
export default function App() {
  const signedIn = useSession((s) => s.session !== null);
  const device = useActiveDevice();
  usePresence(); // 접속 신호(설정 → 계정의 「접속 중」). 로그아웃·잠금 동안은 보내지 않는다
  if (!signedIn) return <Login />;
  if (device === 'phone') return <MobileShell />;
  if (device === 'tablet') return <TabletShell />;
  return <Desktop />;
}
