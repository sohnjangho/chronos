import Desktop from './Desktop';
import Login from './Login';
import { useSession } from './session';
import './tokens.css';
import './os.css';
import './userScope';

/**
 * 세션이 없으면 로그인, 있으면 바탕화면. 로그아웃(401 포함)이나 다른 사람 로그인 때 앞 사람의 창·패널·근거·대화·
 * 현장·겹화면을 비우는 일은 userScope 가 세션을 바꾸는 순간(그리기 전에) 한다.
 */
export default function App() {
  const signedIn = useSession((s) => s.session !== null);
  return signedIn ? <Desktop /> : <Login />;
}
