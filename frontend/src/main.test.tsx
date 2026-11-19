import { act, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

test('첫 화면에 ChronOS 를 그린다', async () => {
  document.body.innerHTML = '<div id="root"></div>';
  await act(async () => {
    await import('./main');
  });
  expect(screen.getByText('ChronOS')).toBeInTheDocument();
});
