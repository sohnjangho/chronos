import type { ReactNode } from 'react';
import './ui.css';

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export interface BadgeProps {
  tone?: Tone;
  /** 진한 바탕(개수 배지). 기본은 옅은 바탕. */
  solid?: boolean;
  className?: string;
  children: ReactNode;
}

export default function Badge({ tone = 'neutral', solid = false, className, children }: BadgeProps) {
  const classes = ['ui-badge', `ui-badge-${tone}`, solid && 'ui-badge-solid', className].filter(Boolean).join(' ');
  return <span className={classes}>{children}</span>;
}
