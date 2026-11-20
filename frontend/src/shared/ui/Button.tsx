import type { ButtonHTMLAttributes } from 'react';
import './ui.css';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'primary' | 'danger';
}

/** type 은 기본 "button"(폼 안에서 뜻밖에 제출되지 않게). */
export default function Button({ variant = 'default', type = 'button', className, ...rest }: ButtonProps) {
  const classes = ['ui-btn', variant !== 'default' && `ui-btn-${variant}`, className].filter(Boolean).join(' ');
  return <button type={type} className={classes} {...rest} />;
}
