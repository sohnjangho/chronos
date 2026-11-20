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

// eslint 규칙은 정적 import 만, 깊이 2 까지만 본다. 아래 검사는 동적 import() 와 깊이에 상관없이 본다.
const IMPORTS = /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)|\b(?:import|export)\b[^'"()]*?\bfrom\s*['"]([^'"]+)['"]|\bimport\s*['"]([^'"]+)['"]/g;

/** file 은 src/programs 기준 경로("./<프로그램>/…"). 다른 프로그램에 닿는 import 글을 돌려준다. */
function crossImports(file: string, code: string): string[] {
  const own = file.split('/')[1];
  return [...code.matchAll(IMPORTS)]
    .map((m) => m[1] ?? m[2] ?? m[3])
    .filter((spec) => {
      const target = spec.startsWith('.') ? new URL(spec, `file:///src/programs/${file.slice(2)}`).pathname : spec;
      const hit = /(?:^|\/)programs\/([^/]+)/.exec(target);
      return hit !== null && hit[1] !== own;
    });
}

test('the source scan catches static, dynamic and deep imports of another program', () => {
  expect(crossImports('./alpha/index.ts', "import x from '../beta';")).toEqual(['../beta']);
  expect(crossImports('./alpha/a/b/c/View.tsx', "const V = lazy(() => import('../../../../beta/View'));")).toEqual([
    '../../../../beta/View',
  ]);
  expect(crossImports('./alpha/a/b/View.tsx', "export { y } from '../../../beta/y';\nimport type { T } from\n  'src/programs/beta/t';")).toEqual([
    '../../../beta/y',
    'src/programs/beta/t',
  ]);
  expect(crossImports('./alpha/index.ts', "import '../index';")).toEqual(['../index']);
  const allowed = "import '../../os/os.css';\nimport y from './y';\nconst z = import('../alpha/q');\nimport { api } from '../../shared/api';";
  expect(crossImports('./alpha/index.ts', allowed)).toEqual([]);
});

test('no program imports another program, statically or dynamically, at any depth', () => {
  const sources = import.meta.glob<string>('./*/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true });
  const files = Object.entries(sources);
  expect(files.length).toBeGreaterThanOrEqual(8);
  expect(files.flatMap(([file, code]) => crossImports(file, code).map((spec) => `${file}: ${spec}`))).toEqual([]);
});
