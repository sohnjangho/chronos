import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import Badge from './Badge';

test('badge shows its text with the tone class', () => {
  render(<Badge tone="danger">지연 +4일</Badge>);
  expect(screen.getByText('지연 +4일')).toHaveClass('ui-badge', 'ui-badge-danger');
});

test('badge defaults to neutral and can be solid', () => {
  render(
    <>
      <Badge>보통</Badge>
      <Badge tone="danger" solid>
        2
      </Badge>
    </>,
  );
  expect(screen.getByText('보통')).toHaveClass('ui-badge-neutral');
  expect(screen.getByText('2')).toHaveClass('ui-badge-solid');
});
