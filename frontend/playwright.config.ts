import { defineConfig } from '@playwright/test';

// 화면 끝에서 끝까지 시험(맥에서 직접). 서버는 scripts/e2e-local.sh 가 임시 자료·가짜 LLM 으로 띄우고 주소를 넘긴다.
// 결과 폴더(E2E_OUTPUT_DIR)는 저장소 밖 임시 폴더. 단계 화면은 시험이 docs/demo/shots/ 에 따로 저장한다.
export default defineConfig({
  testDir: './e2e',
  outputDir: process.env.E2E_OUTPUT_DIR ?? '/tmp/chronos-playwright',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5700',
    viewport: { width: 1920, height: 1080 }, // 기준 해상도 FHD
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
    colorScheme: 'light',
    browserName: 'chromium',
  },
});
