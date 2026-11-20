import type { ReactElement } from 'react';

/** 24×24 흰 선 그림(프로그램 아이콘 타일 위). 인자 하나가 path 하나. 색은 currentColor. 크기는 타일이 정한다. */
export function glyph(...paths: string[]): ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
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
