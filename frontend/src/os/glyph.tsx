import type { ReactElement } from 'react';

/** 24×24 선 그림 아이콘(Dock 용). 인자 하나가 path 하나. 색은 currentColor. */
export function glyph(...paths: string[]): ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      width="26"
      height="26"
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
