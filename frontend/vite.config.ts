import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5600,
    strictPort: true,
    proxy: {
      '/api': 'http://backend:8210',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    css: { include: [/\.css\?raw$/] },
    // 전체를 함께 돌릴 때 느려지는 시험(ESLint 를 부르는 시험 등)이 시간 초과로 거짓 실패하지 않게.
    testTimeout: 15000,
    // Docker VM 메모리(약 1GB)에서 파일마다 jsdom 일꾼을 많이 띄우면 일꾼이 SIGKILL 된다. 동시에 3개까지만.
    maxWorkers: 3,
  },
});
