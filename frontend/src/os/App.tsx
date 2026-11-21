import Desktop from './Desktop';
import Login from './Login';
import MobileShell from './MobileShell';
import { useSession } from './session';
import { useIsMobile } from './useIsMobile';
import './tokens.css';
import './os.css';
import './userScope';

/**
 * 세션이 없으면 로그인, 있으면 바탕화면(폭 <= 768px 은 스마트폰 전용 MobileShell).
 * 로그아웃(401 포함)이나 다른 사람 로그인 때 앞 사람의 창·패널·근거·대화·현장·겹화면을 비우는 일은 userScope 가 한다.
 */
export default function App() {
  const signedIn = useSession((s) => s.session !== null);
  const mobile = useIsMobile();
  if (!signedIn) return <Login />;
  return mobile ? <MobileShell /> : <Desktop />;
}
