import { useEffect, useRef } from 'react';
import Desktop from './Desktop';
import Login from './Login';
import { useSession } from './session';
import { resetShellState } from './shellReset';
import { useTheme } from './theme';
import './tokens.css';
import './os.css';

/**
 * 세션이 없으면 로그인, 있으면 바탕화면. 로그아웃(401 포함)하거나 다른 사용자가 로그인하면
 * 창·패널·근거·대화·겹화면을 모두 비운다.
 */
export default function App() {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const previous = useRef(userId);
  useEffect(() => {
    const switched = previous.current !== null && userId !== null && previous.current !== userId;
    if (userId === null || switched) resetShellState();
    if (userId === null) useTheme.getState().load(null);
    previous.current = userId;
  }, [userId]);
  return userId !== null ? <Desktop /> : <Login />;
}
