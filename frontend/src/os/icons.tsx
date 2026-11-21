import { useEffect, useState, type ReactElement } from 'react';
import { getCustomIconUrl } from './customIcons';

// 셸이 쓰는 선 아이콘(직접 그림). 색은 currentColor.
function line(size: number, ...paths: string[]): ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

export const SearchIcon = () => line(18, 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z', 'M15.5 15.5 20 20');
export const InboxIcon = () => line(18, 'M4 13h4l1.5 3h5L16 13h4', 'M5 6h14l1 7v5H4v-5z');
export const BellIcon = () => line(18, 'M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z', 'M10 20.5a2 2 0 0 0 4 0');
export const MoonIcon = () => line(18, 'M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z');
export const SunIcon = () =>
  line(18, 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M12 2v2', 'M12 20v2', 'M4 12H2', 'M22 12h-2', 'M5 5l1.4 1.4', 'M17.6 17.6 19 19', 'M5 19l1.4-1.4', 'M17.6 6.4 19 5');
export const PersonIcon = () => line(18, 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4.5 20a7.5 7.5 0 0 1 15 0');
export const AppsIcon = ({ size = 24 }: { size?: number } = {}) =>
  line(
    size,
    'M6 4.5h3.5A1.5 1.5 0 0 1 11 6v3.5A1.5 1.5 0 0 1 9.5 11H6a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 6 4.5z',
    'M14.5 4.5H18A1.5 1.5 0 0 1 19.5 6v3.5A1.5 1.5 0 0 1 18 11h-3.5A1.5 1.5 0 0 1 13 9.5V6a1.5 1.5 0 0 1 1.5-1.5z',
    'M6 13h3.5A1.5 1.5 0 0 1 11 14.5V18a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 18v-3.5A1.5 1.5 0 0 1 6 13z',
    'M14.5 13H18a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5h-3.5A1.5 1.5 0 0 1 13 18v-3.5A1.5 1.5 0 0 1 14.5 13z',
  );
export const PanelIcon = () => line(22, 'M4 5h16v14H4z', 'M14 5v14', 'M16.5 9h1.5', 'M16.5 12h1.5');
export const MobileFieldIcon = () => line(18, 'M6 3.5h8a1.5 1.5 0 0 1 1.5 1.5v14A1.5 1.5 0 0 1 14 20.5H6A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 6 3.5z', 'M9 17.5h2', 'M18 8h2.5a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H18');

/** ChronOS 마크: 커스텀 chronos 아이콘이 있으면 우선 사용하고, 없으면 강조색 둥근 사각 안의 시계. size 는 한 변(px). */
export function ChronosMark({ size = 24 }: { size?: number }) {
  const customSrc = getCustomIconUrl('chronos');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [customSrc]);

  if (customSrc && !failed) {
    return (
      <span className="os-mark is-custom" data-icon-id="chronos" style={{ width: size, height: size }} aria-hidden="true">
        <img src={customSrc} alt="" className="os-icon-img" draggable={false} onError={() => setFailed(true)} />
      </span>
    );
  }

  return (
    <span className="os-mark" data-icon-id="chronos" style={{ width: size, height: size }} aria-hidden="true">
      {line(Math.round(size * 0.7), 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'M12 7.5V12l3 2')}
    </span>
  );
}
