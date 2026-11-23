// 문자 길이(Task 79): 서버(backend/app/outreach/channels/sms.py length_kind)와 같은 셈 — 나갈 글(NFC·앞뒤 빈칸 지움)의 코드 포인트마다
// ASCII(U+0000~U+007F)는 1바이트, 그 밖은 모두 2바이트. 90바이트까지 문자 1건(sms), 넘으면 장문(long).
import { describe, expect, test } from 'vitest';
import { SMS_BYTES, smsLength } from './smsLength';

const ko = (n: number) => '가'.repeat(n);
const en = (n: number) => 'a'.repeat(n);

describe('smsLength', () => {
  test('nothing typed is 0 characters, 0 bytes, one SMS', () => {
    expect(smsLength('')).toEqual({ chars: 0, bytes: 0, kind: 'sms' });
    expect(SMS_BYTES).toBe(90);
  });

  test('Korean is 2 bytes: 45 characters is one SMS, 46 is a long message', () => {
    expect(smsLength(ko(45))).toEqual({ chars: 45, bytes: 90, kind: 'sms' });
    expect(smsLength(ko(46))).toEqual({ chars: 46, bytes: 92, kind: 'long' });
  });

  test('ASCII is 1 byte: 90 characters is one SMS, 91 is a long message', () => {
    expect(smsLength(en(90))).toEqual({ chars: 90, bytes: 90, kind: 'sms' });
    expect(smsLength(en(91))).toEqual({ chars: 91, bytes: 91, kind: 'long' });
    expect(smsLength('0123456789 !?-.')).toEqual({ chars: 15, bytes: 15, kind: 'sms' });
  });

  test('mixed text counts each character by its own width, right at the boundary', () => {
    expect(smsLength(ko(44) + 'ab')).toEqual({ chars: 46, bytes: 90, kind: 'sms' });
    expect(smsLength(ko(44) + 'abc')).toEqual({ chars: 47, bytes: 91, kind: 'long' });
    expect(smsLength(ko(45) + '.')).toEqual({ chars: 46, bytes: 91, kind: 'long' });
  });

  test('a newline inside the text is 1 byte; tabs too', () => {
    expect(smsLength('가\n나')).toEqual({ chars: 3, bytes: 5, kind: 'sms' });
    expect(smsLength(ko(44) + '\na')).toEqual({ chars: 46, bytes: 90, kind: 'sms' });
    expect(smsLength('a\tb')).toEqual({ chars: 3, bytes: 3, kind: 'sms' });
  });

  test('full-width letters, Hanja and other non-ASCII characters are 2 bytes', () => {
    expect(smsLength('ＡＢ')).toEqual({ chars: 2, bytes: 4, kind: 'sms' });
    expect(smsLength('漢字')).toEqual({ chars: 2, bytes: 4, kind: 'sms' });
    expect(smsLength('·—')).toEqual({ chars: 2, bytes: 4, kind: 'sms' });
  });

  test('an emoji is one code point of 2 bytes; a joined emoji counts every code point in it', () => {
    expect(smsLength('😀')).toEqual({ chars: 1, bytes: 2, kind: 'sms' });
    // 👨‍👩‍👧 = 👨 + ZWJ + 👩 + ZWJ + 👧 — 다섯 코드 포인트, 서버도 다섯으로 센다(Python len).
    expect(smsLength('👨‍👩‍👧')).toEqual({ chars: 5, bytes: 10, kind: 'sms' });
    expect(smsLength(ko(44) + '😀')).toEqual({ chars: 45, bytes: 90, kind: 'sms' });
    expect(smsLength(ko(45) + '😀')).toEqual({ chars: 46, bytes: 92, kind: 'long' });
  });

  test('counts the text that will go out: composed (NFC) and without leading or trailing blanks', () => {
    // 조합형 「가」(ᄀ + ᅡ)는 NFC 로 한 글자가 된다.
    expect(smsLength('가')).toEqual({ chars: 1, bytes: 2, kind: 'sms' });
    expect(smsLength('  가 나 \n\n')).toEqual({ chars: 3, bytes: 5, kind: 'sms' });
    expect(smsLength(' '.repeat(200))).toEqual({ chars: 0, bytes: 0, kind: 'sms' });
    expect(smsLength(`${ko(45)}   `)).toEqual({ chars: 45, bytes: 90, kind: 'sms' });
  });
});
