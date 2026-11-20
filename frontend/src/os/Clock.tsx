import { useEffect, useState } from 'react';

const DAYS = '일월화수목금토';

/** 예: "11월 19일 (목) 오후 10:10" */
export function formatClock(d: Date): string {
  const h = d.getHours();
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${DAYS[d.getDay()]}) ${h < 12 ? '오전' : '오후'} ${h % 12 || 12}:${mm}`;
}

const untilNextMinute = () => 60_000 - (Date.now() % 60_000);

/** 분이 바뀔 때마다 다시 그린다. */
export default function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      setNow(new Date());
      timer = setTimeout(tick, untilNextMinute());
    };
    timer = setTimeout(tick, untilNextMinute());
    return () => clearTimeout(timer);
  }, []);
  return <span className="os-mb-clock">{formatClock(now)}</span>;
}
