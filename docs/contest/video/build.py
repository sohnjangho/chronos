"""ChronOS 시연 영상 만들기 (5분 이내, FHD, 내레이션 = Gemini TTS).

사용:
  python3 build.py            # 전부 (TTS 키가 없으면 내레이션 자리는 무음, 길이는 어림)
  python3 build.py --only S5  # 한 장면만 다시
키: ~/.chronos-tts.env 의 GEMINI_API_KEY (파일에서만 읽고, 출력·로그에 남기지 않는다).
결과: ~/projects/chronos-film/recordings/edit/ChronOS_시연영상.mp4
"""
import base64, hashlib, json, os, subprocess, sys, wave
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
IMG = HERE.parent / 'a4' / 'img'
REC = Path.home() / 'projects/chronos-film/recordings'
OUT = REC / 'edit'
WORK = OUT / 'work'
TTS_DIR = OUT / 'tts'
SR = 24000
FPS = 30
TTS_MODEL = os.environ.get('TTS_MODEL', 'gemini-3.8-flash-tts')
VOICE = os.environ.get('TTS_VOICE', 'Charon')
STYLE = os.environ.get('TTS_STYLE', '')

# ── 장면 ─────────────────────────────────────────────────────────────
# lines: (자막, 읽을 글). pieces: (파일, 시작, 끝, 몫). cards: 그림 장면.
S = [
  # 첫 20초(PM 11-25, R&D 실증 사례): 실사 영상 4컷 → 「6주가 밀렸다. 과제는 7개월.」 → 간트+CPM 카드 → 제목
  # 실사 영상이 오면 OPEN_VIDEOS 에 파일을 넣는다. 없으면 실사 사진을 천천히 당겨 보인다.
  dict(id='O1', min=9, chip='', kb=True, cards=['c-cut1', 'c-cut2', 'c-cut3', 'c-cut4'], lines=[
    ('성능 시험이 재시험으로 6주 밀렸습니다. 여유가 있다고 봤습니다.', '성능 시험이 재시험으로, 육 주 밀렸습니다. 여유가 있다고 봤습니다.'),
    ('그런데 실증 설비를 설치하려던 날, 인허가가 일정표에 없었다는 걸 알았습니다.', '그런데 실증 설비를 설치하려던 날, 인허가가 일정표에 없었다는 걸 알았습니다.')]),
  dict(id='O2', min=4.5, chip='', cards=['c-hook'], lines=[
    ('과제 종료가 7개월 늘었습니다. 일이 늦어서가 아니라, 늦게 알아서 생긴 실패입니다.', '과제 종료가, 칠 개월 늘었습니다. 일이 늦어서가 아니라, 늦게 알아서 생긴 실패입니다.')]),
  dict(id='O4', min=6.5, chip='', cards=['c-research'], nosub=True, lines=[
    ('실제로도 실증 일정은 연구 밖에서 늦어집니다. 특례 심의만 최대 120일입니다.',
     '실제로도, 실증 일정은 연구 밖에서 늦어집니다. 특례 심의만 최대 백이십 일입니다.')]),
  dict(id='O3', min=6, chip='', cards=['c-cold'], nosub=True, lines=[
    ('지금이라면, 일정을 짤 때 압니다.', '지금이라면, 일정을 짤 때 압니다.')]),
  dict(id='S02', chip='', cards=['c-title'], nosub=True, lines=[
    ('ChronOS. 에이전트가 일정을 관리합니다. 일정이 바뀔 때마다 완료일정을 좌우하는 일이 어디로 옮겨 갔는지 먼저 알려 줍니다.',
     '크로노스. 에이전트가 일정을 관리합니다. 일정이 바뀔 때마다, 완료일정을 좌우하는 일이 어디로 옮겨 갔는지, 먼저 알려 줍니다.')]),
  dict(id='W1', min=22, chip='WOW 1 · 에이전트 OS', pieces=[('A/A-os-computer-use-rnd.mp4', 20, 46, 2), ('A/A-os-computer-use-rnd.mp4', 46, 68.0, 1)], lines=[
    ('ChronOS 는 채팅창 하나가 아니라 OS 입니다.', '크로노스는 채팅창 하나가 아니라, 오에스입니다.'),
    ('대화로 지연을 알리면, 에이전트가 스케줄과 지연 기록 창을 직접 열어 일합니다.', '대화로 지연을 알리면, 에이전트가 스케줄과 지연 기록 창을 직접 열어 일합니다.'),
    ('사람은 창이 열리고 숫자가 바뀌는 것을 눈으로 따라갑니다.', '사람은 창이 열리고 숫자가 바뀌는 것을, 눈으로 따라갑니다.'),
    ('만회안을 부탁하면 비교판을 띄웁니다.', '만회안을 부탁하면, 비교판을 띄웁니다.'),
    ('남의 화면을 흉내 내지 않고, 자기 OS 의 창을 도구로 정확히 엽니다.', '남의 화면을 흉내 내지 않고, 자기 오에스의 창을 도구로 정확히 엽니다.')]),
  dict(id='W1b', min=12, chip='WOW 1 · 워크플로우', pieces=[('B/B-workflow-rnd.mp4', 28, 44, 1.5), ('B/B-workflow-rnd.mp4', 44, 53.7, 1)], lines=[
    ('요청마다 워크플로우를 그 자리에서 짜고, 잘 된 순서는 스킬로 저장합니다.', '요청마다 워크플로우를 그 자리에서 짜고, 잘 된 순서는 스킬로 저장합니다.'),
    ('단계를 누르면 어떤 도구를 왜 썼는지, 어느 모델이 무엇을 돌려줬는지 보입니다.', '단계를 누르면, 어떤 도구를 왜 썼는지, 어느 모델이 무엇을 돌려줬는지 보입니다.')]),
  dict(id='S2', min=20, chip='WOW 4 · AI 공정표 초안', pieces=[('S2-create-v2.mp4', 12, 54, 4), ('S2-create-v2.mp4', 54, 190, 1.2), ('S2-create-v2.mp4', 190, 224.3, 4)], lines=[
    ('공정표 초안도 말 한 줄로 만듭니다.', '공정표 초안도, 말 한 줄로 만듭니다.'),
    ('모자란 정보는 질문지로 묻습니다. 인허가 문항에 실증특례가 필요하다고 적습니다.', '모자란 정보는 질문지로 묻습니다. 인허가 문항에, 실증특례가 필요하다고 적습니다.'),
    ('초안에는 실증특례 심의, 설치 허가, 사용 전 검사가 법령 근거와 함께 들어갑니다.', '초안에는 실증특례 심의, 설치 허가, 사용 전 검사가, 법령 근거와 함께 들어갑니다.'),
    ('날짜는 코드가 계산하고, 규칙 점검을 통과한 초안만 승인함으로 갑니다.', '날짜는 코드가 계산하고, 규칙 점검을 통과한 초안만 승인함으로 갑니다.')]),
  dict(id='S3', min=11, chip='시연 일정 · 수소 연료전지 실증 과제 (가상)', pieces=[('S3-gantt-points-rnd.mp4', 0, 44.88, 1)], lines=[
    ('시연 일정은 수소 연료전지 실증 과제, 종료는 2028년 6월 30일입니다.', '시연 일정은 수소 연료전지 실증 과제, 종료는 이천이십팔 년 유월 삼십 일입니다.'),
    ('지금 완료일정을 좌우하는 일은 인허가 갈래입니다.', '지금 완료일정을 좌우하는 일은, 인허가 갈래입니다.')]),
  dict(id='S4', min=9.5, chip='장면 1 · 같은 3일', pieces=[('S4-delay-window-rnd.mp4', 0, 31.48, 1)], lines=[
    ('데이터 수집 시스템 구축이 3일 늦어졌습니다.', '데이터 수집 시스템 구축이, 삼 일 늦어졌습니다.'),
    ('과제 종료도, 관리 포인트도 그대로입니다. 여유 18일 안에서 흡수됩니다.', '과제 종료도, 관리 포인트도 그대로입니다. 여유 십팔 일 안에서 흡수됩니다.')]),
  dict(id='S5', min=18, chip='장면 1 · 같은 3일, 다른 영향', pieces=[('S5-delay-curtain-rnd.mp4', 0, 28.36, 1)], lines=[
    ('이번엔 성능 시험이 재시험으로 3일 늦어졌습니다.', '이번엔 성능 시험이, 재시험으로 삼 일 늦어졌습니다.'),
    ('과제 종료는 이번에도 그대로라 안심하기 쉽습니다.', '과제 종료는 이번에도 그대로라, 안심하기 쉽습니다.'),
    ('하지만 연구 쪽 여유가 4일에서 1일로 줄어, 관리 포인트가 바뀌었습니다.', '하지만 연구 쪽 여유가 사 일에서 일 일로 줄어, 관리 포인트가 바뀌었습니다.'),
    ('첫 장면에서 놓쳤던 바로 그 순간을, 에이전트가 먼저 알립니다.', '첫 장면에서 놓쳤던 바로 그 순간을, 에이전트가 먼저 알립니다.')]),
  dict(id='S6', min=18, chip='장면 2 · Liner Search · Premium Data · MCP · Search Agent', pieces=[('S6-outside-risks.mp4', 0, 31.0, 1)], lines=[
    ('새 관리 포인트에 대해서만 Liner Search 가 외부 영향을 찾습니다.', '새 관리 포인트에 대해서만, 라이너 서치가 외부 영향을 찾습니다.'),
    ('알루미늄 시세와 환율, 업계 소식을 출처와 함께 붙이고, 근거가 된 문장도 바로 열어 봅니다.',
     '알루미늄 시세와 환율, 업계 소식을 출처와 함께 붙이고, 근거가 된 문장도 바로 열어 봅니다.'),
    ('6개월이 지난 글은 쓰지 않고, 찾지 못하면 숫자를 지어내지 않습니다.', '육 개월이 지난 글은 쓰지 않고, 찾지 못하면 숫자를 지어내지 않습니다.')]),
  dict(id='S7a', min=10, chip='WOW 3 · AI 전화', pieces=[('S7-call-edit.mp4', 0, 29.35, 1)], lines=[
    ('포인트가 옮겨 간 곳의 담당자에게, AI 가 먼저 전화합니다.', '포인트가 옮겨 간 곳의 담당자에게, 에이아이가 먼저 전화합니다.'),
    ('무엇을 묻고 무엇을 말하지 않을지는 사람이 정합니다.', '무엇을 묻고, 무엇을 말하지 않을지는 사람이 정합니다.')]),
  dict(id='S7b', chip='WOW 3 · AI 전화 · 통화 중', pieces=[('S7-call-edit.mp4', 29.35, 117.0, 1)],
       audio='loopback-s7-film-edit/mix.wav', note='통화 음성: 시험 통화 녹음으로 재구성 (상대 역 AI · 전화망 없음)', lines=[]),
  dict(id='S7c', min=9, chip='WOW 3 · 통화 카드', pieces=[('S7-call-edit.mp4', 117.0, 138.8, 1)], lines=[
    ('통화가 끝나면 질문마다 답과 근거가 된 말이 남습니다.', '통화가 끝나면, 질문마다 답과 근거가 된 말이 남습니다.'),
    ('근거가 없는 답은 사실로 기록하지 않습니다.', '근거가 없는 답은, 사실로 기록하지 않습니다.')]),
  dict(id='S8', min=18, chip='WOW 2 · 당겨도 소용 있나', pieces=[('S8-pull-check-rnd.mp4', 0, 36.36, 2), ('S8b-points-window-rnd.mp4', 0, 18.16, 1)], lines=[
    ('습관처럼 설비 제작을 당기려 하면, 에이전트가 먼저 계산합니다.', '습관처럼 설비 제작을 당기려 하면, 에이전트가 먼저 계산합니다.'),
    ('설비 제작을 5일 당겨도, 과제 종료는 하루만 당겨집니다.', '설비 제작을 오 일 당겨도, 과제 종료는 하루만 당겨집니다.'),
    ('지금 완료일정을 좌우하는 일은 성능 시험입니다.', '지금 완료일정을 좌우하는 일은, 성능 시험입니다.'),
    ('같은 5일이 성능 시험이 늦어지기 전에는 4일의 값어치였습니다.', '같은 오 일이, 성능 시험이 늦어지기 전에는 사 일의 값어치였습니다.')]),
  dict(id='S9', min=24, chip='장면 5 · 만회안과 승인', pieces=[('S9-recovery-approve-rnd.mp4', 0, 67.8, 1)], lines=[
    ('만회안은 같은 계산으로 견줍니다. 병행 우선 안은 허가 전 제작이라 위험이 큽니다.', '만회안은 같은 계산으로 견줍니다. 병행 우선 안은, 허가 전 제작이라 위험이 큽니다.'),
    ('압축·자원 추가 안은 설치 허가와 내구 시험 기간을 줄여, 과제 종료를 6월 22일로 당깁니다.', '압축, 자원 추가 안은, 설치 허가와 내구 시험 기간을 줄여, 과제 종료를 유월 이십이 일로 당깁니다.'),
    ('승인은 사람이 하고, 새 버전에서 한 바퀴가 다시 돕니다.', '승인은 사람이 하고, 새 버전에서 한 바퀴가 다시 돕니다.')]),
  dict(id='S11', min=12, chip='확장 ① 분야로 · 건설 · 생산', pieces=[('S3-gantt-points.mp4', 0, 38.9, 1), ('S11-production.mp4', 0, 36.3, 1)], lines=[
    ('분야가 바뀌어도 엔진은 같습니다. 건설 공정도, 생산 일정도 같은 방식으로 돕니다.', '분야가 바뀌어도 엔진은 같습니다. 건설 공정도, 생산 일정도, 같은 방식으로 돕니다.'),
    ('분야마다 볼 외부 자료만 켜고 끕니다.', '분야마다, 볼 외부 자료만 켜고 끕니다.')]),
  # 확장 ② 앱으로 (기획서 30쪽 연동 그림). 실행 추적은 W1b 가 이미 보여 주므로 S12 자리를 쓴다(5분 안).
  dict(id='S11b', min=9.5, chip='', cards=['c-apps'], nosub=True, lines=[
    ('원가·도면 검토 앱을 붙이면, 물량이 일정과 원가로 이어집니다.', '원가와 도면 검토 앱을 붙이면, 물량이 일정과 원가로 이어집니다.'),
    ('에이전트가 일정, 원가, 진도를 함께 관리합니다.', '에이전트가 일정, 원가, 진도를 함께 관리합니다.')]),
  dict(id='S99', chip='', cards=['c-end'], tail=2.0, lines=[
    ('무엇이 완료일정을 늦추는지는, 바뀔 때마다 다시 정해집니다.', '무엇이 완료일정을 늦추는지는, 바뀔 때마다 다시 정해집니다.'),
    ('ChronOS', '크로노스.')]),
]

# 제출본: CHRONOS_SUBMISSION=1 이면 저장소 밖 치환표(실명·경력)를 자막·내레이션에 되돌린다
_SUBMAP = Path.home() / 'reports/AI대회/01_라이너_엑스톤_2026/제출/개인정보_치환.json'
if os.environ.get('CHRONOS_SUBMISSION') == '1' and _SUBMAP.exists():
    _pairs = json.loads(_SUBMAP.read_text(encoding='utf-8')).get('video', [])
    for _seg in S:
        _new = []
        for _sub, _tts in _seg['lines']:
            for _a, _b in _pairs:
                _sub = _sub.replace(_a, _b); _tts = _tts.replace(_a, _b)
            _new.append((_sub, _tts))
        _seg['lines'] = _new


# 실사 영상 4컷(개발 세션이 Liner Videos API 로 만듦). 없으면 사진으로 대신한다.
_RV = '../../chronos/docs/contest/assets/realvideo-rnd/'
# (REC 기준 경로, 시작 초, 끝 초): 칸 길이에 맞춰 이 구간을 조금 빠르게 보인다. R&D 판 영상이 오면 채운다.
OPEN_VIDEOS = [(_RV + 'r1-cut1-a.mp4', 1.0, 4.6),   # 연구원이 떨어진 그래프를 가리킨다
               (_RV + 'r1-cut2-a.mp4', 0.5, 4.1),
               (_RV + 'r1-cut3-a.mp4', 0.0, 3.6),   # 전화를 내린다
               (_RV + 'r1-cut4-b.mp4', 1.0, 4.6)]   # 머리를 감싼다


# ── 그림 (카드·자막) ─────────────────────────────────────────────────
BASE_CSS = """*{box-sizing:border-box}html,body{margin:0;width:1920px;height:1080px;font-family:"Apple SD Gothic Neo","Pretendard",sans-serif}"""
DARK_BG = "background:radial-gradient(120% 70% at 50% 110%,#0b2a5e 0%,rgba(11,42,94,0) 60%),radial-gradient(80% 50% at 85% 0%,#1e1b4b 0%,rgba(30,27,75,0) 60%),#05070d;color:#e2e8f0"
GRAD = "background:linear-gradient(90deg,#7dd3fc,#818cf8);-webkit-background-clip:text;background-clip:text;color:transparent"


def img(name):
    return 'file://' + str(IMG / name)


# 기획서 3쪽 실사 4컷과 같은 말풍선. 사진 카드와 실사 영상 위에 같이 쓴다.
CUT_BUB = {
    1: '<div class="bub" style="left:120px;top:110px">재시험이면 6주.<br>여유 있으니 괜찮아.</div>',
    2: '<div class="nar" style="left:120px;top:110px">실증 설비 제작 끝. 다음 주 설치만 하면 된다.</div>',
    3: '<div class="bub phone" style="right:120px;top:110px">"실증특례 승인 없이는 설치 못 합니다.<br>심의만 3개월이에요."</div><div class="bub" style="right:120px;top:330px">그게 일정표에<br>없었는데…</div>',
    4: '<div class="nar" style="left:120px;top:110px">실증 운전 12개월을 못 채운다. 과제 종료 7개월 연장.</div>',
}
BUB_CSS = """.bub{position:absolute;background:#fff;color:#0f172a;font-size:46px;font-weight:800;line-height:1.35;padding:26px 36px;border-radius:34px;box-shadow:0 14px 40px rgba(0,0,0,.45)}
.bub.phone{background:#e0f2fe;color:#075985;font-weight:700;font-size:40px}
.nar{position:absolute;background:#fbbf24;color:#1c1917;font-size:44px;font-weight:800;padding:20px 32px;border-radius:6px;box-shadow:0 14px 40px rgba(0,0,0,.45)}
.no{position:absolute;left:60px;bottom:60px;width:72px;height:72px;border-radius:50%;background:#fbbf24;color:#05070d;font:800 40px/72px sans-serif;text-align:center}"""


def bub_html(n):  # 실사 영상 위에 얹는 투명 말풍선
    return f'<html><head><style>{BASE_CSS}body{{background:transparent;position:relative}}{BUB_CSS}</style></head><body>{CUT_BUB[n]}<div class="no">{n}</div><div style="position:absolute;right:40px;bottom:28px;font-size:20px;color:rgba(255,255,255,.75)">연출 영상 · Liner Videos API</div></body></html>'



def card_html(cid):
    if cid == 'c-3days':
        svg = (HERE.parent / 'a4' / 'ChronOS_기획서_rev7.html').read_text(encoding='utf-8')
        a = svg.index('<svg viewBox="0 0 720 220"'); b = svg.index('</svg>', a) + 6
        s = svg[a:b].replace('width="100%" style="margin-top:6mm"', 'width="1560"')
        return f"""<html><head><style>{BASE_CSS}body{{{DARK_BG};padding:110px 180px}}</style></head><body>
<div style="font:700 26px Menlo;letter-spacing:.2em;color:#f87171">같은 3일, 다른 영향</div>
<div style="font-size:78px;font-weight:800;color:#fff;letter-spacing:-.03em;margin:18px 0 60px">크기가 아니라 <span style="background:linear-gradient(90deg,#fbbf24,#f97316);-webkit-background-clip:text;background-clip:text;color:transparent">위치</span>가 약속을 늦춘다</div>{s}</body></html>"""
    if cid.startswith('c-cut'):
        n = int(cid[-1])
        bub = CUT_BUB[n]
        return f"""<html><head><style>{BASE_CSS}body{{background:#000 url('{img(f'rd1-{n}.jpg')}') center/cover no-repeat;position:relative}}
.bub{{position:absolute;background:#fff;color:#0f172a;font-size:46px;font-weight:800;line-height:1.35;padding:26px 36px;border-radius:34px;box-shadow:0 14px 40px rgba(0,0,0,.45)}}
.bub.phone{{background:#e0f2fe;color:#075985;font-weight:700;font-size:40px}}
.nar{{position:absolute;background:#fbbf24;color:#1c1917;font-size:44px;font-weight:800;padding:20px 32px;border-radius:6px;box-shadow:0 14px 40px rgba(0,0,0,.45)}}
.no{{position:absolute;left:60px;bottom:60px;width:72px;height:72px;border-radius:50%;background:#fbbf24;color:#05070d;font:800 40px/72px sans-serif;text-align:center}}</style></head>
<body>{bub}<div class="no">{n}</div><div style="position:absolute;right:40px;bottom:28px;font-size:20px;color:rgba(255,255,255,.75)">연출 이미지 · Liner Images API</div></body></html>"""
    if cid == 'c-hook':
        return f"""<html><head><style>{BASE_CSS}body{{background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}}</style></head><body>
<div style="font-size:120px;font-weight:800;color:#fff;letter-spacing:-.03em;line-height:1.2">6주가 밀렸다.</div>
<div style="font-size:150px;font-weight:800;color:#fbbf24;letter-spacing:-.03em;line-height:1.2;margin-top:10px">과제는 7개월.</div></body></html>"""
    if cid == 'c-cold':  # 기획서 4쪽의 간트+CPM (그때 vs ChronOS 였다면)
        src = (HERE.parent / 'a4' / 'ChronOS_기획서_rev7.html').read_text(encoding='utf-8')
        i = src.index('<svg viewBox="0 0 720 ', src.index('<!-- 3 간트 + CPM')); j = src.index('</svg>', i) + 6
        g = src[i:j].replace('width="100%"', 'width="1180"', 1)
        return f"""<html><head><style>{BASE_CSS}body{{{DARK_BG};position:relative}}</style></head><body>
<div style="position:absolute;left:370px;top:40px">{g}</div>
<div style="position:absolute;left:0;right:0;bottom:46px;text-align:center;font-size:54px;font-weight:800;color:#fff">지금이라면, <span style="color:#7dd3fc">일정을 짤 때 안다.</span></div></body></html>"""
    if cid == 'c-research':  # 기획서 5쪽 「조사로 확인한 것」
        st = [('120일', '규제 특례 심의까지 최대', '매일일보 2024.06'), ('45~150일', '지역별 인허가 기간', '기후에너지경제 2025.12'), ('58.0%', '"실증 지원 체계 부족"', 'KISTEP 2018 · 연구자 설문')]
        cells = ''.join(f'<div style="border:2px solid rgba(248,113,113,.45);background:rgba(248,113,113,.07);border-radius:28px;padding:60px 48px">'
                        f'<div style="font-size:104px;font-weight:800;color:#f87171;letter-spacing:-.04em;line-height:1;white-space:nowrap">{a}</div>'
                        f'<div style="font-size:44px;font-weight:800;color:#fff;margin-top:30px;line-height:1.3">{b}</div>'
                        f'<div style="font-size:24px;color:#94a3b8;margin-top:18px">{c}</div></div>' for a, b, c in st)
        return f"""<html><head><style>{BASE_CSS}body{{{DARK_BG};padding:150px 140px}}</style></head><body>
<div style="font:700 28px Menlo;letter-spacing:.2em;color:#f87171">조사로 확인한 것</div>
<div style="font-size:84px;font-weight:800;color:#fff;letter-spacing:-.03em;margin:22px 0 70px;line-height:1.2">R&amp;D 실증 일정은 <span style="color:#fbbf24">연구 밖</span>에서 늦어진다</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:44px">{cells}</div>
<div style="font-size:32px;color:#94a3b8;margin-top:60px">인허가, 특례 심의, 부처 간 조율처럼 연구자가 통제하지 못하는 외부 절차가 일정을 좌우한다.</div></body></html>"""
    if cid == 'c-title':  # 기획서 표지와 같은 구성
        cards = [('에이전트 OS 시스템', '채팅창 하나가 아니라 OS. 스케줄·간트·CPM 창을 직접 열어 일한다.'),
                 ('AGI 시스템', '무엇을 할지 스스로 정하고, 워크플로우를 짜고, 잘 된 순서는 스킬로 남긴다.'),
                 ('에이전트가 직접 연락', '담당자에게 문자를 보내고 AI 전화로 묻는다. 보내기 전엔 사람이 승인한다.')]
        cc = ''.join(f'<div style="border-top:3px solid rgba(255,255,255,.2);padding-top:22px"><div style="font-size:36px;font-weight:800;color:#fff">{t}</div>'
                     f'<div style="font-size:26px;color:#cbd5e1;line-height:1.5;margin-top:12px">{d}</div></div>' for t, d in cards)
        return f"""<html><head><style>{BASE_CSS}body{{{DARK_BG};padding:90px 120px;position:relative}}</style></head><body>
<div style="display:inline-block;font:700 22px Menlo;letter-spacing:.12em;color:#7dd3fc;border:2px solid rgba(125,211,252,.5);border-radius:999px;padding:8px 22px">LINER .EXE-THON 2026</div>
<div style="font:700 24px Menlo;letter-spacing:.2em;color:#7dd3fc;margin-top:60px">일정 에이전트 OS</div>
<div style="font-size:170px;font-weight:800;letter-spacing:-.04em;color:#fff;margin-top:10px;line-height:1">Chron<span style="{GRAD}">OS</span></div>
<div style="font-size:60px;font-weight:800;color:#fff;margin-top:36px;letter-spacing:-.02em">에이전트가 <span style="color:#7dd3fc">일정을 관리한다.</span></div>
<div style="font-size:32px;color:#cbd5e1;margin-top:28px;line-height:1.55;width:660px">일정이 바뀔 때마다, 완료일정을 좌우하는 일이 어디로 옮겨 갔는지 먼저 알려 주는 에이전트.</div>
<img src="{img('cap/cover-os.jpg')}" style="position:absolute;right:120px;top:110px;width:900px;border-radius:16px;border:2px solid rgba(255,255,255,.2);box-shadow:0 30px 90px rgba(0,0,0,.6)">
<div style="position:absolute;left:120px;right:120px;bottom:90px;display:grid;grid-template-columns:repeat(3,1fr);gap:56px">{cc}</div></body></html>"""
    if cid == 'c-apps':  # 기획서 30쪽 「② 앱으로」 연동 그림
        src = (HERE.parent / 'a4' / 'ChronOS_기획서_rev7.html').read_text(encoding='utf-8')
        i = src.index('<svg', src.index('<!--D:syn-->')); j = src.index('</svg>', i) + 6
        g = src[i:j].replace('width="100%"', 'width="1480"', 1)
        return f"""<html><head><style>{BASE_CSS}body{{{DARK_BG};padding:110px 220px}}</style></head><body>
<div style="font:700 26px Menlo;letter-spacing:.2em;color:#4ade80">확장 ② 앱으로</div>
<div style="font-size:64px;font-weight:800;color:#fff;letter-spacing:-.03em;margin:14px 0 26px">앱을 붙일수록 <span style="color:#fbbf24">에이전트가 프로젝트 전체</span>를 관리한다</div>{g}</body></html>"""
    if cid == 'c-end':
        return f"""<html><head><style>{BASE_CSS}body{{{DARK_BG};display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}}</style></head><body>
<div style="font-size:64px;font-weight:800;color:#fff;line-height:1.4;letter-spacing:-.02em">무엇이 완료일정을 늦추는지는,<br><span style="{GRAD}">바뀔 때마다 다시 정해집니다.</span></div>
<div style="font-size:150px;font-weight:800;color:#fff;letter-spacing:-.04em;margin-top:70px">Chron<span style="{GRAD}">OS</span></div>
<div style="font:600 28px Menlo;color:#94a3b8;margin-top:30px">Liner .EXE-THON 2026 · github.com/sohnjangho/chronos</div></body></html>"""
    raise KeyError(cid)


def overlay_html(chip, sub, note=None, dark_bg=False):
    chip_html = '' if not chip else (
        f'<div style="position:absolute;left:44px;top:36px;background:rgba(5,7,13,.86);border:2px solid {"#fbbf24" if chip.startswith("WOW") else "#38bdf8"};'
        f'color:#fff;font-size:28px;font-weight:800;padding:10px 24px;border-radius:999px">{chip}</div>')
    sub_html = '' if not sub else (
        '<div style="position:absolute;left:0;right:0;bottom:54px;display:flex;justify-content:center">'
        f'<div style="max-width:1560px;background:rgba(5,7,13,{0.55 if dark_bg else 0.84});color:#fff;font-size:42px;font-weight:700;line-height:1.45;'
        f'padding:16px 34px;border-radius:16px;text-align:center">{sub}</div></div>')
    note_html = '' if not note else (
        '<div style="position:absolute;left:0;right:0;bottom:54px;display:flex;justify-content:center">'
        f'<div style="background:rgba(5,7,13,.84);color:#fde68a;font-size:32px;font-weight:700;padding:12px 30px;border-radius:14px">{note}</div></div>')
    return f'<html><head><style>{BASE_CSS}body{{background:transparent}}</style></head><body>{chip_html}{sub_html}{note_html}</body></html>'


def render(jobs):
    if not jobs:
        return
    jf = WORK / 'jobs.json'
    jf.write_text(json.dumps(jobs, ensure_ascii=False))
    subprocess.run(['node', str(HERE / 'render.mjs'), str(jf)], check=True)


# ── TTS ──────────────────────────────────────────────────────────────
def gemini_key():
    f = Path.home() / '.chronos-tts.env'
    if not f.exists():
        return None
    for ln in f.read_text().splitlines():
        if ln.startswith('GEMINI_API_KEY='):
            return ln.split('=', 1)[1].strip().strip('"\'')
    return None


def tts(text):
    """읽을 글 → pcm int16 배열 (Gemini TTS). 캐시: tts/<hash>.wav"""
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    key = gemini_key()
    h = hashlib.sha1(f'{TTS_MODEL}|{VOICE}|{STYLE}|{text}'.encode()).hexdigest()[:16]
    f = TTS_DIR / f'{h}.wav'
    if f.exists():
        x = read_wav(f)
        return unwrap(x.tobytes()) if x[:2].tobytes() == b'RIFF' else x
    if not key:
        n = int(SR * max(1.2, len(text.replace(' ', '')) / 6.8))  # 어림 길이, 무음
        return np.zeros(n, dtype=np.int16)
    body = {'contents': [{'parts': [{'text': STYLE + text}]}],
            'generationConfig': {'responseModalities': ['AUDIO'],
                                 'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': VOICE}}}}}
    for attempt in range(5):
        r = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent',
                          headers={'x-goog-api-key': key, 'Content-Type': 'application/json'}, json=body, timeout=180)
        if r.status_code == 200 and 'candidates' in r.json():
            break
        print('TTS 다시 시도', r.status_code, r.text[:200].replace(key, '***'))
        import time; time.sleep(4 * (attempt + 1))
    r.raise_for_status()
    part = r.json()['candidates'][0]['content']['parts'][0]['inlineData']
    pcm = unwrap(base64.b64decode(part['data']))
    pcm = trim_silence(pcm)
    write_wav(f, pcm)
    return pcm


def scene_tts(lines):
    """장면의 문장을 한 번에 읽고(호출 1번), 문장 사이 쉼에서 잘라 문장별 소리로 나눈다."""
    if not lines:
        return []
    texts = [t for _, t in lines]
    pcm = tts('\n'.join(texts))
    n = len(texts)
    if n == 1:
        return [pcm]
    hop = int(0.02 * SR)
    env = np.array([np.abs(pcm[i:i + hop]).mean() for i in range(0, len(pcm) - hop, hop)])
    quiet = env < max(250, np.percentile(env, 30) * 0.6)
    runs = []  # (길이, 가운데 표본)
    i = 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if (j - i) * 0.02 >= 0.15 and i > 0 and j < len(quiet):
                runs.append((j - i, ((i + j) // 2) * hop))
            i = j
        else:
            i += 1
    if len(runs) >= n - 1:
        # 글자 수로 어림한 경계마다 가장 가까운 쉼(길이 0.25초 이상 우선)을 고른다
        tot = sum(len(t) for t in texts); acc = 0; cuts = []; used = set()
        for t in texts[:-1]:
            acc += len(t); want = len(pcm) * acc / tot
            cand = [(abs(c - want) - (0.4 * SR if L * 0.02 >= 0.25 else 0), c) for L, c in runs if c not in used]
            c = min(cand)[1]; used.add(c); cuts.append(c)
        cuts.sort()
    else:  # 쉼을 못 찾으면 글자 수 비율로
        tot = sum(len(t) for t in texts); acc = 0; cuts = []
        for t in texts[:-1]:
            acc += len(t); cuts.append(int(len(pcm) * acc / tot))
        print('  쉼 부족 → 글자 비율로 나눔:', texts[0][:20])
    edges = [0] + cuts + [len(pcm)]
    return [fade(trim_silence(pcm[edges[k]:edges[k + 1]])) for k in range(n)]


def trim_silence(x, thr=350):
    idx = np.nonzero(np.abs(x) > thr)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] - int(0.05 * SR)); b = min(len(x), idx[-1] + int(0.12 * SR))
    return x[a:b]


def unwrap(b):
    """TTS 가 돌려준 바이트 → int16. WAV(RIFF) 면 머리말을 떼고, 아니면 날 PCM 으로 본다."""
    import io
    if b[:4] == b'RIFF':
        with wave.open(io.BytesIO(b)) as w:
            assert w.getframerate() == SR and w.getnchannels() == 1
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return np.frombuffer(b, dtype=np.int16)


def fade(x, ms=12):
    n = min(len(x) // 4, int(SR * ms / 1000))
    if n < 2:
        return x
    y = x.astype(np.float32)
    y[:n] *= np.linspace(0, 1, n); y[-n:] *= np.linspace(1, 0, n)
    return (y * 0.9).astype(np.int16)  # 0.9 = 1dB 여유


def read_wav(f):
    with wave.open(str(f)) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2, f
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def write_wav(f, x):
    with wave.open(str(f), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(x.astype(np.int16).tobytes())


def ff(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args)], check=True)


# ── 장면 하나 ────────────────────────────────────────────────────────
def build(seg):
    sid = seg['id']
    lines = seg['lines']
    clips = scene_tts(lines)
    lead, gap, tailpad = 0.45, 0.32, seg.get('tail', 0.55)
    t = lead; spans = []
    for c in clips:
        d = len(c) / SR; spans.append((t, t + d)); t += d + gap
    narr_end = (spans[-1][1] if spans else 0) + tailpad
    want = seg.get('min', 3.0)
    if spans and not seg.get('audio') and want > narr_end and len(spans) > 1:
        extra = (want - narr_end) * 0.85 / (len(spans) - 1)
        spans = [(a0 + k * extra, b0 + k * extra) for k, (a0, b0) in enumerate(spans)]
        narr_end = spans[-1][1] + tailpad
    if seg.get('audio'):
        ext = read_wav(REC / seg['audio'])
        T = len(ext) / SR + 0.3
    else:
        T = max(narr_end, seg.get('min', 3.0))
    # 소리
    n = int(T * SR) + 1
    mix = np.zeros(n, dtype=np.int32)
    if seg.get('audio'):
        mix[int(0.15 * SR):int(0.15 * SR) + len(ext)] += ext
    for (a, _), c in zip(spans, clips):
        i = int(a * SR); mix[i:i + len(c)] += c
    write_wav(WORK / f'{sid}.wav', np.clip(mix, -32767, 32767))
    # 그림: 자막 줄마다 하나, 없으면 칩·주석만
    dark = bool(seg.get('cards'))
    jobs = []
    if lines:
        for k, (sub, _) in enumerate(lines):
            jobs.append({'html': overlay_html(seg['chip'], None if seg.get('nosub') else sub, dark_bg=dark), 'out': str(WORK / f'{sid}-o{k}.png'), 'transparent': True})
    else:
        jobs.append({'html': overlay_html(seg['chip'], None, note=seg.get('note')), 'out': str(WORK / f'{sid}-o0.png'), 'transparent': True})
    for cid in seg.get('cards', []):
        jobs.append({'html': card_html(cid), 'out': str(WORK / f'{cid}.png')})
    if sid == 'O1':
        for n in CUT_BUB:
            jobs.append({'html': bub_html(n), 'out': str(WORK / f'O1-bub{n}.png'), 'transparent': True})
    render(jobs)
    # 영상
    inputs, fc, vlabels = [], [], []
    if seg.get('cards'):
        cs = seg['cards']; each = T / len(cs)
        vids = OPEN_VIDEOS if sid == 'O1' and OPEN_VIDEOS and all((REC / v[0]).exists() for v in OPEN_VIDEOS) else None
        for k, cid in enumerate(cs):
            if vids:  # 실사 영상: 앞부분을 칸 길이만큼, 화면을 채우게
                v, a, b = vids[k]
                inputs += ['-i', REC / v]
                fc.append(f'[{k}:v]trim={a}:{b},setpts=(PTS-STARTPTS)*{each / (b - a):.5f},fps={FPS},scale=1920:1080:force_original_aspect_ratio=increase,'
                          f'crop=1920:1080,format=yuv420p,setsar=1,tpad=stop_mode=clone:stop_duration=2,trim=duration={each:.3f}[v{k}]')
            elif seg.get('kb'):  # 사진을 천천히 당겨 보인다
                nf = int(each * FPS) + 1
                inputs += ['-loop', '1', '-framerate', str(FPS), '-t', f'{each:.3f}', '-i', WORK / f'{cid}.png']
                fc.append(f"[{k}:v]scale=7680:4320,zoompan=z='1+0.06*on/{nf}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=3840x2160:fps={FPS},scale=1920:1080,"
                          f'format=yuv420p,setsar=1,trim=duration={each:.3f}[v{k}]')
            else:
                inputs += ['-loop', '1', '-t', f'{each:.3f}', '-i', WORK / f'{cid}.png']
                fc.append(f'[{k}:v]scale=1920:1080,fps={FPS},format=yuv420p,setsar=1[v{k}]')
            vlabels.append(f'[v{k}]')
    else:
        tw = sum(p[3] for p in seg['pieces'])
        for k, (src, a, b, w) in enumerate(seg['pieces']):
            alloc = T * w / tw
            speed = (b - a) / alloc
            inputs += ['-i', REC / src]
            fc.append(f'[{k}:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed:.5f},fps={FPS},scale=1920:1080,format=yuv420p,setsar=1,'
                      f'tpad=stop_mode=clone:stop_duration=1,trim=duration={alloc:.3f}[v{k}]')
            vlabels.append(f'[v{k}]')
            print(f'  {sid} 조각 {k}: {src} {a}-{b}s ×{speed:.2f} → {alloc:.1f}s')
    fc.append(f'{"".join(vlabels)}concat=n={len(vlabels)}:v=1:a=0[base]')
    cur = 'base'; base_in = len(vlabels)
    ovs = [(WORK / f'{sid}-o{k}.png') for k in range(max(1, len(lines)))]
    for k, png in enumerate(ovs):
        inputs += ['-i', png]
        if lines:
            a = spans[k][0] - 0.15
            b = spans[k + 1][0] - 0.15 if k + 1 < len(spans) else T
            en = f":enable='between(t,{max(0,a):.2f},{b:.2f})'"
        else:
            en = ''
        nxt = f'o{k}'
        fc.append(f'[{cur}][{base_in + k}:v]overlay=0:0{en}[{nxt}]'); cur = nxt
    nb = 0
    if seg.get('cards') and vids:  # 실사 영상 칸마다 기획서와 같은 말풍선
        for k in range(len(seg['cards'])):
            inputs += ['-i', WORK / f'O1-bub{k + 1}.png']
            fc.append(f"[{cur}][{base_in + len(ovs) + k}:v]overlay=0:0:enable='between(t,{k * each:.2f},{(k + 1) * each:.2f})'[b{k}]"); cur = f'b{k}'
            nb += 1
    out = WORK / f'{sid}.mp4'
    ff(*inputs, '-i', WORK / f'{sid}.wav', '-filter_complex', ';'.join(fc), '-map', f'[{cur}]', '-map', f'{base_in + len(ovs) + nb}:a',
       '-t', f'{T:.3f}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-r', FPS, '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2', out)
    print(f'{sid}: {T:.1f}s')
    return T


# 치찰음(ㅅ·ㅊ)이 모음보다 크게 튀는 TTS 소리를 누그러뜨린 뒤 크기를 맞춘다
AFX = 'deesser=i=0.5:m=0.5:f=0.5,loudnorm=I=-16:TP=-1.5:LRA=11'


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None
    total = 0; durs = {}
    for seg in S:
        if only and seg['id'] not in only:
            p = WORK / f"{seg['id']}.mp4"
            if p.exists():
                d = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p], capture_output=True, text=True).stdout)
                durs[seg['id']] = d; total += d
            continue
        d = build(seg); durs[seg['id']] = d; total += d
    lst = WORK / 'list.txt'
    lst.write_text(''.join(f"file '{WORK / (s['id'] + '.mp4')}'\n" for s in S))
    raw = WORK / 'joined.mp4'
    ff('-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', raw)
    final = OUT / 'ChronOS_시연영상.mp4'
    ff('-i', raw, '-c:v', 'copy', '-af', AFX, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', final)
    print(json.dumps({k: round(v, 1) for k, v in durs.items()}, ensure_ascii=False))
    print(f'합계 {total:.1f}s ({int(total // 60)}:{int(total % 60):02d}) → {final}')
    print('TTS:', '사용' if gemini_key() else '키 없음(무음·어림 길이)')


if __name__ == '__main__':
    main()
