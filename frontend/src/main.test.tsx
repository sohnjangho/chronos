import { act, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

test('첫 화면에 ChronOS 를 그린다', async () => {
  document.body.innerHTML = '<div id="root"></div>';
  await act(async () => {
    await import('./main');
  });
  // 로그인 화면의 브랜드는 로고 동영상이라 글자 대신 이름표로 그린다.
  expect(screen.getByLabelText(/^ChronOS/)).toBeInTheDocument();
});
