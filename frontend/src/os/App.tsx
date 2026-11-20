import { useEffect } from 'react';
import { useApprovals } from './approvals';
import Desktop from './Desktop';
import Login from './Login';
import { useSession } from './session';
import { useWindows } from './windowStore';
import './tokens.css';
import './os.css';

/** 세션이 없으면 로그인, 있으면 바탕화면. 로그아웃(401 포함)하면 창을 모두 닫는다. */
export default function App() {
  const signedIn = useSession((s) => s.session !== null);
  useEffect(() => {
    if (signedIn) return;
    useWindows.getState().reset();
    useApprovals.setState({ pending: 0 });
  }, [signedIn]);
  return signedIn ? <Desktop /> : <Login />;
}
