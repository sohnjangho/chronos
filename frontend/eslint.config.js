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
  { ignores: ['dist'] },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    rules: {
      'max-lines': ['warn', 300],
      'max-lines-per-function': ['warn', 50],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}'],
    rules: { 'max-lines': 'off', 'max-lines-per-function': 'off' },
  },
  [0, 1, 2].map(noCrossProgramImports),
);
