// 문자 한 건의 길이(Task 79). 서버의 셈(backend/app/outreach/channels/sms.py `length_kind`)과 같다:
// 나갈 글 — 서버처럼 NFC 로 맞추고 앞뒤 빈칸을 지운 글 — 의 코드 포인트마다 ASCII(U+0000~U+007F: 영문·숫자·기호·빈칸·줄바꿈·탭)는
// 1바이트, 그 밖(한글·한자·전각 글자·「·」「—」 같은 기호·이모지)은 모두 2바이트. 이모지 하나는 코드 포인트 하나(2바이트)이고,
// 이어 붙인 이모지(👨‍👩‍👧)는 든 코드 포인트(이음 글자 포함)를 다 센다. 90바이트까지 문자 1건(sms), 넘으면 장문(long).
// 제공사는 길이로 단문·장문을 스스로 고른다 — 이모지를 제공사가 어떻게 세는지는 확인하지 못했다.

export const SMS_BYTES = 90;

export interface SmsLength {
  /** 나갈 글의 글자 수(코드 포인트 — 서버의 1~1000자 검사와 같은 셈) */
  chars: number;
  bytes: number;
  kind: 'sms' | 'long';
}

export function smsLength(text: string): SmsLength {
  let chars = 0;
  let bytes = 0;
  for (const ch of text.normalize('NFC').trim()) {
    chars += 1;
    bytes += ch.codePointAt(0)! < 0x80 ? 1 : 2;
  }
  return { chars, bytes, kind: bytes <= SMS_BYTES ? 'sms' : 'long' };
}
