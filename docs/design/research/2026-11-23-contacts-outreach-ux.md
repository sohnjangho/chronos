# 협력사 주소록·보내기·전화·기록 화면 — 외부 제품 조사 (2026-11-23)

공개 도움말·개발 문서만 읽음(가입·API 호출 없음). 본 제품 8개: **Procore**(Directory), **TeamGantt**(협력사 일정 확인 요청), **Buildertrend**, **Solapi**, **NHN Cloud 알림톡**, **채널톡**, **Twilio**, **HubSpot**, **Aircall**. Fieldwire는 일반 사항만 확인했다.
"확인 못 함"이라고 적은 것은 공개 문서에 없었다는 뜻이다(추측으로 채우지 않음). 화면 캡처는 문서 본문에 없어 열 구성 같은 세부는 비어 있는 곳이 있다.

---

## 1. 주소록

| 항목 | 찾은 내용 |
|---|---|
| 회사별 묶기 | Procore 프로젝트 Directory의 Users 보기는 **"Group By" 기본값이 "Company"**이고, 탭은 Users / Contacts / Companies / Distribution Groups로 나뉜다. 비활성 사람과 회사는 Inactive 탭으로 따로 모은다. [Procore 보기 전환](https://support.procore.com/products/online/user-guide/project-level/directory/tutorials/switch-between-views-in-the-project-directory) |
| 로그인 없는 연락처 | Procore는 **User**(로그인함)와 **Contact**(기록에만 이름이 남고 로그인 안 함)를 나눈다. Contact는 나중에 사용자로 초대할 수 있다. [Procore contact FAQ](https://support.procore.com/faq/what-is-a-contact-in-procore-and-which-project-tools-support-the-concept) → 우리 협력사 담당자는 대부분 Contact에 해당한다. |
| 목록 vs 상세 필드 | Procore는 Name 정렬과 열 표시 설정(≡ 메뉴)만 확인했고 기본 열 목록은 확인 못 함. [같은 문서](https://support.procore.com/products/online/user-guide/project-level/directory/tutorials/switch-between-views-in-the-project-directory) TeamGantt 협력사 필드는 **이름 · 공종(Trade, 목록에서 고름) · 전화(선택, 수신 동의 필요) · 이메일(선택) · 알림 수단("Email only / SMS only / Email & SMS / None")**이다. [TeamGantt](https://teamgantt.helpscoutdocs.com/article/179-adding-and-managing-subcontractors) |
| 프로젝트 분리 | Procore는 **회사 Directory(전체 명부) ↔ 프로젝트 Directory(배정된 사람)**의 두 층이다. 프로젝트에서 새로 만든 사람은 회사 명부에도 자동으로 들어가고, 다른 프로젝트에는 회사 명부에서 골라 넣는다. [Procore 프로젝트 Directory](https://support.procore.com/products/online/user-guide/project-level/directory) Fieldwire도 계정 People / 프로젝트 People 두 탭을 둔다. [Fieldwire](https://help.fieldwire.com/hc/en-us/articles/360003476711) |
| 대량 넣기 | Procore "Bulk Add from Co. Directory"는 CSV가 아니라 **이미 회사 명부에 있는 회사·사람을 골라 표로 확인한 뒤 "Add to Project"**를 누르는 방식이다. 행마다 빨간 X로 빼고, "Notify?" 체크로 추가 안내를 보낼지 고른다. [Procore Bulk Add](https://support.procore.com/products/online/user-guide/project-level/directory/tutorials/bulk-add-users-to-the-project-directory) 파일 가져오기는 별도의 "Procore Imports"로 하며 세부는 확인 못 함. Solapi와 NHN은 **수신번호와 변수 값을 담은 엑셀·CSV 업로드**를 발송 화면에 둔다. NHN은 "CSV를 엑셀에서 저장하면 한글이 깨질 수 있다"고 경고한다. [Solapi 알림톡 가이드](https://solapi.com/guides/kakao-ata-guide) · [NHN 알림톡 콘솔](https://docs.nhncloud.com/ko/Notification/KakaoTalk%20Bizmessage/ko/alimtalk-console-guide/) |
| 번호 없음·미확인 | TeamGantt는 SMS 수신 동의를 마친 번호 옆에 **초록 "Verified" 체크**를 붙인다. 동의 전에는 SMS를 보낼 수 없고, 동의 링크를 복사해 당사자에게 직접 보내야 한다. [TeamGantt](https://teamgantt.helpscoutdocs.com/article/179-adding-and-managing-subcontractors) Solapi 수신거부 목록은 **번호 두 자리를 가려** 보여 준다. [Solapi FAQ](https://solapi.com/guides/sms-faq) "번호 없음"을 따로 표시하는 방식은 확인 못 함. |

## 2. 보내기 화면

- **받는 사람 고르기**
  - TeamGantt가 가장 가깝다. 일정이 바뀌면 간트 위 **"Confirm schedule"**을 누른다. 그러면 **바뀐 작업에 배정된 협력사만** 후보로 뜨고, 골라서 "Request Confirmation"을 누른다. 즉 **일정 항목이 받는 사람을 정하는 구조**다. [TeamGantt](https://teamgantt.helpscoutdocs.com/article/179-adding-and-managing-subcontractors)
  - 채널톡은 받는 사람을 지정하거나 저장해 둔 세그먼트를 불러온다. [채널톡 알림톡](https://docs.channel.io/help/ko/articles/9747de9a)
  - 공종 단위로 고르는 화면은 확인 못 함.
- **채널 정하기와 대체 순서**
  - TeamGantt는 사람마다 저장된 알림 수단(SMS/이메일/둘 다)을 따른다. 보낼 때마다 고르지 않는다.
  - Solapi는 알림톡 실패 시 **문자로 대체 발송이 기본으로 켜져** 있고 끄려면 `disableSms`를 설정한다. 대체 문구는 템플릿과 따로 관리하며 승인 뒤에도 바꿀 수 있다(템플릿 목록 ⋮ → "대체 발송 설정"). 원래 요금은 환불되고 문자 요금이 차감된다. [Solapi disableSms](https://solapi.com/developers/api/messages-disablesms) · [Solapi 알림톡 가이드](https://solapi.com/guides/kakao-ata-guide)
  - 채널톡은 반대로 **알림톡이 실패해도 문자로 자동 재발송하지 않는다**. [채널톡](https://docs.channel.io/help/ko/articles/9747de9a) → 제품마다 기본값이 달라서 화면에 명시해야 한다.
- **미리보기·변수·길이·비용**
  - 변수는 `#{이름}` 형식이다. 채널톡은 변수마다 **고객 필드에 연결하거나 "선택 안 함"과 고정 대체 문구**를 고른다. [채널톡](https://docs.channel.io/help/ko/articles/9747de9a)
  - 알림톡은 변수를 바꾼 뒤 기준으로 **1,000자 제한**이고, 버튼 이름에는 변수를 못 쓴다. NHN은 치환할 값이 없으면 발송 실패로 처리한다. [NHN](https://docs.nhncloud.com/ko/Notification/KakaoTalk%20Bizmessage/ko/alimtalk-console-guide/)
  - 비용: 채널톡 알림톡은 건당 7 PU(1 PU = 1원)를 문서에 밝힌다. [채널톡](https://docs.channel.io/help/ko/articles/9747de9a) 보내기 화면에서 글자 수·바이트·예상 비용을 실시간으로 보여 주는지는 확인 못 함.
  - 웹 발송 문자에는 "[Web 발신]"이 붙고 지울 수 없다. [Solapi FAQ](https://solapi.com/guides/sms-faq)
- **실수 방지 확인 단계**
  - Solapi 웹 발송은 **"전송/예약 준비" → 미리보기 → 발송**의 두 단계다. 요청하지 않은 묶음은 "사용자 요청 대기" 상태로 남았다가 24시간 뒤 지워진다. [Solapi 알림톡 가이드](https://solapi.com/guides/kakao-ata-guide) · [Solapi 발송 내역](https://solapi.com/guides/message-log)
  - NHN 대량 발송에는 **"검수 후 진행"** 옵션이 있다. [NHN](https://docs.nhncloud.com/ko/Notification/KakaoTalk%20Bizmessage/ko/alimtalk-console-guide/)
  - 채널톡은 발송 직전에 대상 고객 정보가 맞는지 다시 확인한다. [채널톡 캠페인](https://docs.channel.io/help/ko/articles/%EC%BA%A0%ED%8E%98%EC%9D%B8-9064c609)
- **알림톡 템플릿 심사 흐름**(카카오가 직접 심사)
  - 상태는 **요청 → 검수 중 → 승인/반려**이고, 1년간 쓰지 않으면 **휴면**이 된다. 영업일 2일 안에 처리된다. 수정은 승인·반려 상태에서만 되고, 고치면 "검수 중"부터 다시 시작한다. 삭제는 요청·반려 상태에서만 된다. [NHN](https://docs.nhncloud.com/ko/Notification/KakaoTalk%20Bizmessage/ko/alimtalk-console-guide/)
  - 채널톡은 심사에 영업일 2~3일이 걸린다고 안내하고, 목록 화면은 상태가 늦게 바뀔 수 있으니 상세 화면에서 확인하라고 한다. 승인된 템플릿은 고칠 수 없다. 정보성 메시지만 보낼 수 있다. [채널톡](https://docs.channel.io/help/ko/articles/9747de9a)
  - Solapi에는 심사자에게만 보이는 **"검수 의견 작성"** 칸이 있다. [Solapi](https://solapi.com/guides/kakao-ata-guide)

## 3. 전화

- **세 가지 방식**
  - **사람이 직접 거는 전화**: HubSpot과 Aircall은 레코드에서 바로 걸고, 끝나면 결과를 기록한다(아래 참고).
  - **AI 음성 에이전트 발신**: Aircall은 대시보드에서 대본·말투·첫 마디·사람 연결 규칙을 정한다. 첫 마디의 `{{변수}}`에 맞는 값이 없으면 **통화 자체를 거절**한다. 요청 응답은 "202 = 대기열에 들어감"이고, 중복 방지 키를 쓰며 기본 1시간 안에 걸리지 않으면 만료된다. [Aircall AI 발신](https://developer.aircall.io/docs/ai-outbound-calls)
  - **녹음 음성 자동 안내**: 조사한 제품 문서에서 따로 다룬 것은 찾지 못했다.
- **통화 상태 용어**(Twilio): queued · ringing · in-progress · completed · busy · no-answer · canceled · failed. 받은 쪽이 사람인지 자동응답인지(AnsweredBy: human / machine / unknown)도 따로 남긴다. [Twilio Call](https://www.twilio.com/docs/voice/api/call-resource)
- **통화 뒤 보이는 것**
  - HubSpot 통화 목록의 열: Call title · Activity date · Call status · Assigned to · Call notes · 연결된 연락처·회사·딜 · **Call outcome** · Recording URL · Direction · Source.
  - HubSpot 미리보기 창: 녹음 재생(10초 건너뛰기)과 **녹취 문장을 누르면 그 시점으로 이동**하는 기능, 결과·담당자·통화 시간(편집 가능).
  - HubSpot 기본 결과값: **Busy / Connected / Left live message / Left voicemail / No answer / Wrong number**. 사용자 정의 결과는 최대 30개이고 저장하면 고칠 수 없다. [HubSpot 통화 목록](https://knowledge.hubspot.com/calling/review-calls-in-the-call-index) · [HubSpot 결과값](https://knowledge.hubspot.com/calling/create-custom-call-and-meeting-outcomes)
  - Aircall은 **AI가 결과 태그를 제안하고 상담원이 확인해야 적용**된다. 요약은 자유 문장인 표준 요약과 관리자가 템플릿으로 정한 항목형 요약이 있다. 항목마다 `ai_generated` 표시가 있고, 사람이 고친 항목에는 `updated_by`가 남는다. 녹음한 외부 통화에만 녹취가 생긴다. [Aircall AI 요약](https://developer.aircall.io/docs/ai-call-summaries) · [Aircall 자동 태깅](https://aircall.io/blog/features/ai-assist-pro-upgrades/)
  - Aircall 통화 목록은 **User 열에 AI 에이전트 로고**를 붙여 AI가 한 통화를 구분한다. 녹취에는 AI 구간과 사람에게 넘긴 구간이 함께 보여 넘긴 지점을 알 수 있다. [Aircall 지원](https://support.aircall.io/en-gb/articles/30773411643421)

## 4. 기록

- **배치**
  - Solapi는 **두 탭**이다. **전송 요청 내역**은 묶음 단위로 생성일·상태·타입·현황(실패/성공/진행 수)을 보이고, **메시지 목록**은 수신번호별 메시지를 보인다. [Solapi 발송 내역](https://solapi.com/guides/message-log)
  - NHN은 "요청 상태"와 "발송 결과"를 **두 열로 나눈다**. [NHN](https://docs.nhncloud.com/ko/Notification/KakaoTalk%20Bizmessage/ko/alimtalk-console-guide/)
  - HubSpot은 통화를 연락처·회사·딜 레코드에 연결하고 **전체 통화 목록**도 따로 둔다. [HubSpot](https://knowledge.hubspot.com/calling/review-calls-in-the-call-index)
- **상태 용어**
  - Twilio 문자: sent / delivered / undelivered / failed. 실패에는 오류 코드가 붙는다. [Twilio 상태](https://support.twilio.com/hc/en-us/articles/223134347-What-do-the-SMS-statuses-mean-)
  - Solapi 묶음: 사용자 요청 대기 / 예약 발송 대기 중 / 발송 요청 완료 / 접수 실패 / 처리 완료 / 시스템 오류.
  - NHN 대량 발송: 대기 / 발송 준비 / 발송 중 / 발송 완료 / 발송 실패 / 발송 취소.
  - TeamGantt 확인 요청: **confirmed / declined / pending / not notified**.
- **실패·재시도**
  - Solapi는 실패 코드를 단계별로 나눈다. 2XXX는 접수 검증 실패, 3XXX는 통신사 전달 뒤 실패다(예: 3032 미가입자, 3054 스팸). [Solapi 처리 과정](https://solapi.com/guides/message-processing) · [FAQ](https://solapi.com/guides/sms-faq)
  - "접수 실패" 묶음은 자동으로 다시 보내지 않고 **[재발송] 버튼**으로 사람이 보낸다.
  - **대체 발송 건은 현황 숫자에 더해진다**(100건 요청 + 대체 50건 = 150). 대체 발송 건을 따로 표시하는 라벨은 확인 못 함. [Solapi 발송 내역](https://solapi.com/guides/message-log)
  - TeamGantt는 "Confirm schedule → Pending → **Resend Confirmation**"으로 **응답 안 한 사람에게만** 다시 보낸다.
- **작업 항목과 연결**
  - TeamGantt는 간트의 **Confirmation 열에 작업별 확인 상태**가 보인다. 거절할 때 남긴 말은 요청자에게 이메일로 간다. 받는 사람은 로그인 없이 링크에서 확인 또는 거절을 누른다. [TeamGantt](https://teamgantt.helpscoutdocs.com/article/179-adding-and-managing-subcontractors)
  - Buildertrend에도 협력사가 도착 시간 요청에 Confirm/Decline으로 답하는 기능이 있다는 검색 결과가 있었다. 다만 도움말 원문에서 세부 화면은 확인 못 함. [Buildertrend 협력사 FAQ](https://buildertrend.com/help-article/subcontractor-faqs/)

## 5. AI 초안 + 사람 승인

- **HubSpot Prospecting Agent**: 설정할 때 **"Review before sending"**(메시지마다 승인)과 **"Send automatically"** 중 하나를 고른다. 처음에는 검토 모드로 쓰다가 품질이 괜찮으면 자동으로 바꾸라고 권한다. 검토할 초안이 생기면 담당 발신자에게 앱 안 알림이나 하루 한 번 이메일이 간다. 사람마다 "agent access"를 켜야 그 사람 이름으로 보낼 수 있다. [HubSpot 에이전트](https://knowledge.hubspot.com/prospecting/use-the-prospecting-agent)
- **HubSpot 초안 검토 화면**: Outreach queue에서 **회사 → 연락처 순으로 고르면 오른쪽에 초안**이 뜬다. 메일마다 **regenerate**, 전체 **Regenerate all**, 직접 고친 뒤 "Save email updates", 마지막에 **"Start outreach"**를 누른다. 옆에 **보내는 이유(의도 신호·연락 이유·마지막 연락일)**가 함께 보인다. 따로 된 '거절' 버튼이나 'AI 작성' 라벨은 문서에서 확인 못 함. [같은 문서](https://knowledge.hubspot.com/prospecting/use-the-prospecting-agent)
- **HubSpot 수동 메일 작업**: 시퀀스가 멈춘 상태로 템플릿이 미리 채워지고, 사람이 **"Review and send"**를 눌러야 나간다. [HubSpot 시퀀스 작업](https://knowledge.hubspot.com/sequences/complete-your-sequence-tasks)
- **Aircall**: 요약 항목마다 AI가 만든 것인지 표시하고(`ai_generated`), 누가 고쳤는지(`updated_by`) 남긴다. 태그는 AI가 제안하고 사람이 확정한다. [Aircall](https://developer.aircall.io/docs/ai-call-summaries)

## 6. 시험 모드

- **Twilio 체험 계정**: **확인된 번호(최대 5개, 가입 번호는 자동 포함)에만** 문자와 전화를 보낼 수 있다. 다른 번호로 보내면 오류 21608이 난다. 메시지 앞에 "Sent from a Twilio Trial account"가 붙고 업그레이드하면 사라진다. [Twilio 체험 가이드](https://www.twilio.com/docs/messaging/guides/how-to-use-your-free-trial-account) · [Twilio 체험 제한](https://www.twilio.com/docs/usage/trials)
- **Twilio 시험 자격 증명**: 실제로 아무것도 보내지 않고 과금도 없다. **매직 번호**(예: +15005550009는 SMS를 못 받는 번호)로 실패 경우를 재현한다. 콘솔에서 시험과 실제를 화면으로 어떻게 구분하는지는 문서에 없다. [Twilio 시험 자격 증명](https://www.twilio.com/docs/iam/test-credentials)
- **Solapi**: 대체 발송 문구를 템플릿 등록 전에 **"발송 테스트"**로 미리 받아 본다. [Solapi](https://solapi.com/guides/kakao-ata-guide)
- 국내 제공사 중에 "허용 번호로만 보내는 샌드박스"를 둔 곳은 확인 못 함(NHN 문서에도 없음).

## 7. 우리에게 권하는 것

### 배치안 세 가지

**A. 명부 중심형 (Procore식)**: 왼쪽은 회사, 가운데는 담당자 표, 오른쪽은 상세와 보내기.
```
[회사▾]  | 이름  공종  전화        수단     | 상세/보내기
 ㈜대한  | 김OO  철근  010-****-12 문·톡·☎ | [문자][톡][전화]
 ㈜성진  | 이OO  전기  (번호 없음) —      | 최근 기록 …
```
- 장점: 주소록 관리가 쉽다.
- 단점: "무슨 일정 때문에" 보내는지가 약하다. 보낼 때 일정을 다시 골라야 한다.

**B. 일정 항목 중심형 (TeamGantt식)**: 일정 항목의 [알리기]를 누르면 배정 협력사가 미리 채워진 보내기 창이 뜨고, 항목에 확인 상태 열이 붙는다.
```
공정표 ── 골조 3층 타설 11/28  확인: ✓2 ✗0 …1  [알리기]
           └ 보내기 창: 받는 사람(자동) · 채널 · 미리보기 · [발송 준비→확인]
```
- 장점: 기록이 처음부터 항목에 연결되고, 받는 사람 실수가 줄어든다.
- 단점: 일정과 상관없는 연락(일반 공지)을 할 곳이 따로 필요하다.

**C. 보낼함·승인함형 (HubSpot 큐식)**: AI와 사람이 만든 초안이 모두 "승인 대기함"에 쌓인다. 왼쪽 목록에서 고르면 오른쪽에 초안·근거·받는 사람이 보이고 [승인/수정/반려]를 누른다.
```
승인 대기(3) | 초안: 철근 반입 지연 알림 (AI 작성 · 근거: 일정 #42 변경)
 ● 철근 3명  | 받는 사람 3 · 알림톡→문자 · 예상 21원
 ○ 전기 1명  | [반려] [수정] [승인하고 보내기]
```
- 장점: 사람 승인 원칙과 AI 초안이 가장 잘 드러나고, 기록과 이어진다.
- 단점: 급한 1건 연락에는 단계가 많다.

**권하는 안: B를 기본으로 하고 C를 승인함으로 붙인다.** 보내기는 일정 항목에서 시작하고, AI 초안과 사람 초안이 모두 승인함을 거친다. 주소록(A)은 별도 프로그램으로 두되 보내기 진입점은 두지 않거나 최소로만 둔다. 이유: (c) "기록 ↔ 일정 항목 연결"과 (b) "사람 확인 필수"를 화면 구조 자체로 보장할 수 있다.

### 따라 할 세부 10가지
1. **목록에서는 전화번호 가운데를 가리고**(010-****-1234), 누르면 보여 준다. 가린 표시 자체는 Solapi 수신거부 목록에도 있다.
2. **수단별 수신 가능 배지**(문자·톡·전화)를 둔다. 번호를 확인한 사람에게는 **초록 "확인됨" 체크**를 붙이고, 확인 전에는 해당 수단 버튼을 잠근다(TeamGantt).
3. 주소록은 **회사별 묶기를 기본**으로 하고 공종 필터를 둔다. 관계가 끝난 협력사는 삭제하지 말고 **비활성 탭**으로 옮긴다(Procore).
4. 대량 넣기는 **붙여넣기·CSV → 표로 미리 확인(행마다 X로 빼기) → "프로젝트에 추가"** 순서로 한다. 한글 인코딩 경고도 띄운다(Procore·NHN).
5. 보내기 창에 **채널 순서를 명시**한다("알림톡 → 실패 시 문자"). 대체 문구는 따로 편집하게 하고, 기본값(켜짐/꺼짐)을 숨기지 않는다(Solapi와 채널톡의 기본값이 반대).
6. 미리보기에서 **변수를 받는 사람별 실제 값으로 바꿔** 보여 준다. 값이 비면 빨간색으로 표시하고 발송을 막는다(NHN은 치환 값이 없으면 실패로 처리하고, Aircall은 변수가 빠지면 통화를 거절한다). 1,000자 기준으로 글자 수를 세고 예상 비용도 보인다.
7. 확인은 **두 단계**로 한다. [발송 준비] 뒤에 받는 사람 수·채널·비용 요약을 보이고 [보내기]를 누른다. 준비만 하고 보내지 않은 건은 일정 시간 뒤 자동으로 버린다(Solapi "사용자 요청 대기", 24시간).
8. 기록에서는 **"요청 상태"와 "전달 결과"를 두 열로** 나눈다(NHN). 실패에는 단계별 사유 코드와 쉬운 설명을 붙이고, **[응답 없는 사람만 다시 보내기]**를 둔다(TeamGantt·Solapi). 대체 발송 건에는 "↪ 문자 대체" 라벨을 붙인다(Solapi에는 이 라벨이 없음).
9. 통화 결과는 **정해진 값 중에서 고르게** 한다(받음 / 통화 중 / 안 받음 / 음성 메시지 남김 / 번호 틀림, HubSpot 기본값). AI가 결과와 요약을 제안하면 **사람이 확정**하고, 항목마다 "AI 작성"과 "수정한 사람"을 남긴다(Aircall). 녹취 문장을 누르면 녹음의 그 지점으로 이동한다(HubSpot).
10. 시험 모드에서는 **허용 번호에만 보내고**(Twilio 체험 계정과 같은 방식), 본문 앞에 **"[시험]" 머리말을 강제로 붙인다**. 화면 전체에 띠를 두르고, 허용 목록 밖의 번호는 받는 사람 목록에서 회색 처리해 고를 수 없게 한다. 일부러 실패하는 가짜 번호를 몇 개 두어 실패 화면도 시험한다(Twilio 매직 번호).
