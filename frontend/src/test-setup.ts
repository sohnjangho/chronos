import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

// vitest 를 globals 없이 쓰므로 Testing Library 가 스스로 정리하지 못한다.
afterEach(cleanup);

// 전체 시험을 함께 돌리면(PM 앱·다른 작업과 CPU 를 나눔) findBy/waitFor 기본 1초가 모자랄 때가 있다.
configure({ asyncUtilTimeout: 3000 });
