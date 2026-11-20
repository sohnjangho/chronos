import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// vitest 를 globals 없이 쓰므로 Testing Library 가 스스로 정리하지 못한다.
afterEach(cleanup);
