import js from '@eslint/js';
import { defineConfig } from 'eslint/config';
import tseslint from 'typescript-eslint';

// src/programs/<a>/ 안의 파일은 다른 프로그램 src/programs/<b>/ 를 import하지 않는다.
// src/shared, src/os 는 쓸 수 있다. depth = 프로그램 폴더 아래 하위 폴더 깊이.
const noCrossProgramImports = (depth) => ({
  files: [`src/programs/*/${'*/'.repeat(depth)}*.{ts,tsx}`],
  rules: {
    'no-restricted-imports': [
      'error',
      {
        patterns: [
          {
            regex: `^(\\.\\./){${depth + 1}}[^./]|(^|/)programs/`,
            message: '다른 프로그램을 import하지 않는다. src/shared 나 src/os 를 쓴다.',
          },
        ],
      },
    ],
  },
});

export default defineConfig(
  { ignores: ['dist', '.playwright-browsers'] }, // .playwright-browsers: e2e 크로미움(scripts/e2e-local.sh)
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    rules: {
      'max-lines': ['warn', 300],
      // 함수 상한 100줄은 오류. 권장 50줄은 검토에서 본다(한 규칙에 기준 둘을 둘 수 없다).
      'max-lines-per-function': ['error', { max: 100, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}'],
    rules: { 'max-lines': 'off', 'max-lines-per-function': 'off' },
  },
  [0, 1, 2].map(noCrossProgramImports),
);
