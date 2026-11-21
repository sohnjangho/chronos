// 스마트폰 뷰포트 판별 훅(폭 <= 768px 이면 모바일 전용 셸로 자동 전환).
import { useEffect, useState } from 'react';

export const MOBILE_MAX_W = 768;

const check = () => (typeof window !== 'undefined' ? window.innerWidth <= MOBILE_MAX_W : false);

export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(check);
  useEffect(() => {
    const onResize = () => setMobile(check());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return mobile;
}
