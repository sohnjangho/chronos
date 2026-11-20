// @vitest-environment node
import { ESLint } from 'eslint';
import { expect, test } from 'vitest';

const root = new URL('../../', import.meta.url).pathname;
const eslint = new ESLint({ cwd: root });

async function ruleHits(file: string, code: string) {
  const [result] = await eslint.lintText(code, { filePath: `${root}${file}` });
  return result.messages.filter((m) => m.ruleId === 'no-restricted-imports').length;
}

test('a program importing another program fails lint', async () => {
  expect(await ruleHits('src/programs/alpha/index.ts', "import x from '../beta/index';\nexport default x;\n")).toBe(1);
  expect(await ruleHits('src/programs/alpha/parts/View.tsx', "import x from '../../beta/View';\nexport default x;\n")).toBe(1);
  expect(await ruleHits('src/programs/alpha/index.ts', "import x from 'src/programs/beta';\nexport default x;\n")).toBe(1);
});

test('a program may import os, shared and its own files', async () => {
  const code = [
    "import { register } from '../../os/registry';",
    "import { api } from '../../shared/api';",
    "import View from './View';",
    'export default [register, api, View];',
    '',
  ].join('\n');
  expect(await ruleHits('src/programs/alpha/index.ts', code)).toBe(0);
});
