// e2e 와 playwright.config.ts 가 읽는 환경 변수(@types/node 없이 타입 검사하려고 이것만 선언한다).
declare const process: { env: Record<string, string | undefined> };
