import type { ReactElement } from 'react';

/**
 * 24×24 듀오톤 글래스 아이콘(프로그램 아이콘 타일 위).
 * 닫힌 도형(Z 로 끝나는 첫 배경 경로)은 은은한 반투명 유리 채움(fill-opacity 0.22)을 더해 딱딱한 단선 느낌을 없앤다.
 */
export function glyph(...paths: string[]): ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.85}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((d, i) => {
        const closed = /[zZ]\s*$/.test(d);
        return (
          <path
            key={d}
            d={d}
            fill={closed && i <= 1 ? 'currentColor' : 'none'}
            fillOpacity={closed && i <= 1 ? 0.22 : undefined}
          />
        );
      })}
    </svg>
  );
}
