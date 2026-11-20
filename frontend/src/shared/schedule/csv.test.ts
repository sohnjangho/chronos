import { afterEach, expect, test, vi } from 'vitest';
import { makeView } from './testKit';
import { COLUMNS } from './columns';
import { download, toCsv } from './csv';

const cols = COLUMNS.filter((c) => ['id', 'name', 'tf'].includes(c.key));
const NO_TEXT = { preds: '', wbsLabel: '', resources: '' };

/** A2020 의 이름과 TF 를 바꾼 일정의 CSV 에서 A2020 줄. */
function lineFor(name: string, tf = 0) {
  const view = makeView();
  view.activities[5] = { ...view.activities[5], name, tf };
  const lines = toCsv(view, cols, () => NO_TEXT).replace(/^\uFEFF/, '').split('\r\n');
  return lines.find((l) => l.startsWith('A2020,'))!;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// fix 1 I1: 표 계산 프로그램이 수식으로 읽지 않게 = + - @ 탭 CR 로 시작하는 글 앞에 ' 를 붙인다.
test.each([
  ['=SUM(A1:A3)', "A2020,'=SUM(A1:A3),0"],
  ['+cmd|calc', "A2020,'+cmd|calc,0"],
  ['-2+3', "A2020,'-2+3,0"],
  ['@HYPERLINK("x")', `A2020,"'@HYPERLINK(""x"")",0`],
  ['\t탭으로 시작', "A2020,'\t탭으로 시작,0"],
  ['\r줄 바꿈으로 시작', `A2020,"'\r줄 바꿈으로 시작",0`],
])('a cell starting with a formula character is neutralised: %j', (name, line) => {
  expect(lineFor(name)).toBe(line);
});

test('plain numbers keep their sign, so a negative TF stays a number', () => {
  expect(lineFor('지상 골조', -3)).toBe('A2020,지상 골조,-3');
});

test('quotes, commas, line breaks and Korean are quoted as CSV', () => {
  expect(lineFor('지상 "코어" 골조, 1단계\n야간 작업')).toBe('A2020,"지상 ""코어"" 골조, 1단계\n야간 작업",0');
});

// fix 1 m8: 내려받기가 시작되기 전에 주소를 풀지 않는다.
test('the download URL is revoked a moment later, not at once', () => {
  vi.useFakeTimers();
  const revoke = vi.fn();
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: revoke }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  download('일정.csv', 'a');
  expect(click).toHaveBeenCalled();
  expect(revoke).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1000);
  expect(revoke).toHaveBeenCalledWith('blob:x');
});
