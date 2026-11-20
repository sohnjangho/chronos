import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import Field from './Field';

test('field labels its control', () => {
  render(
    <Field label="아이디" hint="관리자가 만든 아이디">
      <input />
    </Field>,
  );
  expect(screen.getByLabelText('아이디')).toBeInstanceOf(HTMLInputElement);
  expect(screen.getByText('관리자가 만든 아이디')).toBeInTheDocument();
});

test('field shows an error', () => {
  render(
    <Field label="수량" error="1 이상이어야 합니다.">
      <input />
    </Field>,
  );
  expect(screen.getByText('1 이상이어야 합니다.')).toHaveClass('ui-field-error');
});
