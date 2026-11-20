import type { ReactNode } from 'react';
import './ui.css';

export interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  className?: string;
  /** input · select · textarea 하나. label 로 감싸서 이름이 붙는다. */
  children: ReactNode;
}

export default function Field({ label, hint, error, className, children }: FieldProps) {
  return (
    <div className={['ui-field', className].filter(Boolean).join(' ')}>
      <label className="ui-field-label">
        {label}
        {children}
      </label>
      {hint && <span className="ui-field-hint">{hint}</span>}
      {error && <span className="ui-field-error">{error}</span>}
    </div>
  );
}
