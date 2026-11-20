import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import Button from './Button';

test('button defaults to type=button and calls onClick', async () => {
  const onClick = vi.fn();
  render(<Button onClick={onClick}>저장</Button>);
  const b = screen.getByRole('button', { name: '저장' });
  expect(b).toHaveAttribute('type', 'button');
  await userEvent.click(b);
  expect(onClick).toHaveBeenCalledOnce();
});

test('variant sets the class and other props pass through', () => {
  render(
    <Button variant="primary" type="submit" disabled className="extra">
      확정
    </Button>,
  );
  const b = screen.getByRole('button', { name: '확정' });
  expect(b).toHaveClass('ui-btn', 'ui-btn-primary', 'extra');
  expect(b).toHaveAttribute('type', 'submit');
  expect(b).toBeDisabled();
});
