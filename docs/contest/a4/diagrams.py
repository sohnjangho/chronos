"""기획서 다이어그램(어두운 지면용 SVG + 번호 지시선)을 만들어 rev7 HTML 의 <!--D:이름--> … <!--/D--> 자리에 넣는다.
사용: python3 diagrams.py
"""
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / 'ChronOS_기획서_rev7.html'
FONT = 'Apple SD Gothic Neo, Noto Sans KR, sans-serif'
C = dict(code='#38bdf8', liner='#fbbf24', human='#4ade80', input='#94a3b8', rec='#a78bfa', out='#f472b6')
FILL = {k: f'rgba({int(v[1:3],16)},{int(v[3:5],16)},{int(v[5:7],16)},.07)' for k, v in C.items()}


def node(cx, cy, title, sub='', w=86, h=44, kind=None, hot=False):
    st = C[kind] if kind else 'rgba(255,255,255,.22)'
    sw = 2.2 if hot else 1.2
    o = [f'<rect x="{cx-w/2}" y="{cy-h/2}" width="{w}" height="{h}" rx="9" fill="#0f172a" stroke="{st}" stroke-width="{sw}"/>']
    ty = cy - 3 if sub else cy + 4
    o.append(f'<text x="{cx}" y="{ty}" font-size="11" font-weight="800" fill="#fff" text-anchor="middle">{title}</text>')
    if sub:
        o.append(f'<text x="{cx}" y="{cy+12}" font-size="8.4" fill="#94a3b8" text-anchor="middle">{sub}</text>')
    return ''.join(o)


def group(x, y, w, h, label, kind):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{FILL[kind]}" stroke="{C[kind]}" stroke-opacity=".55"/>'
            f'<text x="{x+12}" y="{y+17}" font-size="10.5" font-weight="800" fill="{C[kind]}">{label}</text>')


def arrow(pts, color='#64748b', w=1.6, dash=False, label=None, lx=None, ly=None, lc=None, anchor='start'):
    d = ' '.join(f'{x},{y}' for x, y in pts)
    mid = {'#64748b': 'ag', '#fbbf24': 'aa', '#38bdf8': 'ab', '#4ade80': 'agr'}[color]
    o = [f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{w}" {"stroke-dasharray=\'4 3\'" if dash else ""} marker-end="url(#{mid})" stroke-linejoin="round"/>']
    if label:
        o.append(f'<text x="{lx}" y="{ly}" font-size="9" font-weight="700" fill="{lc or color}" text-anchor="{anchor}" stroke="#0a0d16" stroke-width="3" paint-order="stroke">{label}</text>')
    return ''.join(o)


def badge(x, y, n):
    return (f'<circle cx="{x}" cy="{y}" r="9" fill="#fbbf24" stroke="#05070d" stroke-width="1.5"/>'
            f'<text x="{x}" y="{y+4}" font-size="11" font-weight="800" fill="#05070d" text-anchor="middle">{n}</text>')


def defs():
    m = ''.join(f'<marker id="{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
                for i, c in [('ag', '#64748b'), ('aa', '#fbbf24'), ('ab', '#38bdf8'), ('agr', '#4ade80')])
    return f'<defs>{m}</defs>'


def svg(w, h, body):
    return f'<svg viewBox="0 0 {w} {h}" width="100%" font-family="{FONT}">{defs()}{body}</svg>'


def legend(items, cols=2):
    li = ''.join(f'<li><i>{n}</i><span><b>{t}</b> {d}</span></li>' for n, t, d in items)
    return f'<ul class="af2 dl" style="grid-template-columns:repeat({cols},1fr)">{li}</ul>'


# ── 1. 에이전트의 한 바퀴 (고리) ─────────────────────────────
def d_loop():
    W, H, cx, cy, rx, ry = 720, 300, 360, 152, 262, 112
    steps = [('변동 감지', '대화 · 현장 · 문자 · 엑셀', 'input'), ('영향 계산', '날짜 · 여유 · 자원 (코드)', 'code'),
             ('관리 포인트', '크리티컬 · 여유 적은 작업 (코드)', 'code'), ('외부 영향 찾기', '그 작업만 · Liner Search', 'liner'),
             ('담당자에게 묻기', '문자 · AI 전화 · Liner Model', 'liner'), ('만회안 · 당김 효과', '코드 계산 · Liner 설명', 'code'),
             ('사람이 승인', '새 버전 · 기록에 쌓임', 'human')]
    n = len(steps)
    ang = [math.radians(-90 - 360 / n * 1.5 + 360 / n * i) for i in range(n)]
    pos = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in ang]
    o = [f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="none" stroke="rgba(251,191,36,.10)" stroke-width="16"/>']
    # 고리 화살표: 타원 위의 호를 노드 사이에 그린다
    for i in range(n):
        a0, a1 = ang[i], ang[(i + 1) % n]
        if a1 < a0:
            a1 += 2 * math.pi
        g = 0.26
        p0 = (cx + rx * math.cos(a0 + g), cy + ry * math.sin(a0 + g))
        p1 = (cx + rx * math.cos(a1 - g), cy + ry * math.sin(a1 - g))
        col = '#4ade80' if i == n - 1 else '#fbbf24'
        mk = 'agr' if i == n - 1 else 'aa'
        o.append(f'<path d="M{p0[0]:.1f},{p0[1]:.1f} A{rx},{ry} 0 0 1 {p1[0]:.1f},{p1[1]:.1f}" fill="none" stroke="{col}" stroke-width="2.4" marker-end="url(#{mk})"/>')
    for i, ((t, s, k), (x, y)) in enumerate(zip(steps, pos)):
        o.append(node(x, y, f'{"①②③④⑤⑥⑦"[i]} {t}', s, w=150, h=44, kind=k, hot=(i in (2, 6))))
    # 가운데: 안쪽 루프
    o.append(f'<rect x="{cx-118}" y="{cy-36}" width="236" height="72" rx="14" fill="rgba(251,191,36,.07)" stroke="#fbbf24" stroke-opacity=".6"/>')
    o.append(f'<text x="{cx}" y="{cy-16}" font-size="10" font-weight="800" fill="#fbbf24" text-anchor="middle">에이전트 루프 · Liner Model</text>')
    o.append(f'<text x="{cx}" y="{cy+3}" font-size="11" font-weight="800" fill="#fff" text-anchor="middle">판단 → 도구 실행 → 자가 점검</text>')
    o.append(f'<text x="{cx}" y="{cy+20}" font-size="9" fill="#cbd5e1" text-anchor="middle">단계마다 이 작은 고리가 돈다 · 틀리면 다시, 최대 12단계</text>')
    o.append(f'<path d="M{cx+92},{cy+26} q20,-28 0,-50" fill="none" stroke="#fbbf24" stroke-width="1.6" marker-end="url(#aa)"/>')
    # 번호 지시선
    for (i, num, dx, dy) in [(1, 1, -84, -2), (2, 2, 84, -2), (3, 3, 84, -2), (4, 4, 84, 6), (6, 5, -84, 6)]:
        x, y = pos[i]
        o.append(badge(x + dx, y + dy - 18, num))
    o.append(badge(cx - 128, cy - 30, 6))
    o.append(f'<text x="{cx}" y="{H-4}" font-size="9" fill="#94a3b8" text-anchor="middle">⑦ 승인하면 새 버전이 되고, 에이전트는 ①로 돌아가 관리 포인트를 다시 뽑는다. 고리는 변동마다 돈다.</text>')
    items = [(1, '날짜는 코드만', '공휴일, 선후 관계, 자원까지 엔진이 계산한다. AI 가 낸 날짜는 버린다.'),
             (2, '옮겨 갔는지 먼저 본다', '변동마다 관리 포인트를 다시 뽑고, 바뀌었으면 카드로 알린다.'),
             (3, '그곳만 찾는다', '새 관리 포인트에 대해서만 Liner Search 가 출처와 함께 찾으니 호출이 적다.'),
             (4, '직접 연락한다', '연락 하네스 6가지 검사를 통과해야 문자와 AI 전화가 나간다.'),
             (5, '사람이 정한다', '승인해야 일정이 바뀐다. 승인 기록과 버전이 남는다.'),
             (6, '안쪽 고리', '각 단계 안에서 에이전트가 도구를 고르고 결과를 스스로 점검한다.')]
    return svg(W, H, ''.join(o)) + legend(items, 3)


# ── 2. 에이전트 로직: 변동 하나가 결정이 되기까지 ─────────────
def d_logic():
    W, H = 760, 540
    o = [group(16, 14, 392, 100, '① 변동이 들어오는 길', 'input'), group(452, 14, 292, 100, '⑥ 사람이 결정', 'human'),
         group(16, 140, 392, 110, '에이전트 루프 · Liner Model', 'liner'), group(436, 140, 308, 110, '④ 외부 영향 · Liner Search', 'liner'),
         group(16, 278, 600, 110, '②③ 코드 엔진 · 날짜는 여기서만 계산', 'code'),
         group(16, 416, 322, 104, '쌓이는 기록', 'rec'), group(352, 416, 392, 104, '⑤ 연락 하네스', 'out')]
    y1, y2, y3, y4 = 72, 205, 343, 476
    for x, t, s in [(68, '대화 한 줄', '"3일 늦어졌어"'), (162, '현장 체크인', '진도 · 사진 판독'), (256, '걸려 온 전화', '문자 · 협력사 보고'), (350, '엑셀 · CSV', '협력사 공정표')]:
        o.append(node(x, y1, t, s, w=88))
    o.append(node(530, y1, '새 버전', '되돌릴 수 있다', kind='human'))
    o.append(node(670, y1, '승인함', '승인 · 거부 · 다시 짜기', w=104, kind='human', hot=True))
    for x, t, s in [(68, '컨텍스트 조립', '지침 · 스킬 · 보는 화면'), (162, '판단', 'Router 3전략'), (256, '도구 실행', '40여 개 · 실패 시 되돌림'), (350, '자가 점검', '결과 보고 고친다')]:
        o.append(node(x, y2 + 8, t, s, w=88, kind='liner'))
    for x, t, s in [(492, 'Premium Data', '시세 · 환율 + 출처'), (592, 'MCP', '업계 소식 · 법령'), (692, 'Search Agent', '근거가 된 문장')]:
        o.append(node(x, y2 + 8, t, s, w=92, kind='liner'))
    xs = [66, 160, 254, 348, 452, 556]
    for x, t, s in zip(xs, ['달력 · CPM', '자원 맞춤', '4겹 하네스', '지연 영향', '관리 포인트', '당김 효과 · 만회안'],
                       ['공휴일 · 선후 관계', '크레인 · 설비 용량', '기본·분야·내 규칙·입력', '완료 +n일 · 여유 흡수', '크리티컬 + 여유 적은 작업', '5일 중 며칠이 반영되나']):
        o.append(node(x, y3 + 8, t, s, w=92, kind='code', hot=(t == '관리 포인트')))
    for x, t, s in [(68, '지연 기록', '원인 · 책임 · 비용'), (170, '자료함', '시방서 5축 분류'), (272, '보고서', '회사 양식 학습')]:
        o.append(node(x, y4 + 8, t, s, w=90, kind='rec'))
    for x, t, s in [(430, '나가는 문', '시험모드·근무시간·권한 등 6검사'), (560, '문자 · AI 전화', '첫마디는 코드가 정함'), (680, '뒤 확인', '받아쓰기와 답 대조')]:
        o.append(node(x, y4 + 8, t, s, w=110 if t == '나가는 문' else 96, kind='out'))
    # 화살표
    o.append(arrow([(68, y1 + 22), (68, y2 - 14)]))
    for a, b in [(112, 118), (206, 212), (300, 306)]:
        o.append(arrow([(a, y2 + 8), (b, y2 + 8)], '#fbbf24'))
    o.append(arrow([(350, y2 - 14), (350, y2 - 26), (162, y2 - 26), (162, y2 - 14)], '#fbbf24', label='틀리면 다시 · 최대 12단계', lx=256, ly=y2 - 30, anchor='middle'))
    o.append(arrow([(256, y2 + 30), (256, y3 - 14)], '#38bdf8', label='계산은 코드에 맡긴다', lx=262, ly=y3 - 22))
    for a, b in zip(xs, xs[1:]):
        o.append(arrow([(a + 46, y3 + 8), (b - 46, y3 + 8)], '#38bdf8'))
    o.append(arrow([(470, y3 - 14), (470, y2 + 50), (492, y2 + 50), (492, y2 + 30)], '#fbbf24', label='새 포인트만 찾는다', lx=500, ly=y2 + 62))
    o.append(arrow([(452, y3 + 30), (452, 446), (430, 446), (430, y4 - 14)], '#64748b', label='담당자에게 묻는다', lx=462, ly=443))
    o.append(arrow([(485, y4 + 8), (512, y4 + 8)], '#64748b'))
    o.append(arrow([(608, y4 + 8), (632, y4 + 8)], '#64748b'))
    o.append(arrow([(375, y4 + 8), (317, y4 + 8)], '#64748b', dash=True))
    # 바깥 고리(강조): 만회안 → 승인함 → 새 버전 → 다시 계산 → 관리 포인트
    o.append(arrow([(602, y3 + 8), (752, y3 + 8), (752, y1), (722, y1)], '#4ade80', w=2.6, label='대안을 올린다', lx=746, ly=y3 - 4, lc='#4ade80', anchor='end'))
    o.append(arrow([(618, y1), (574, y1)], '#4ade80', w=2.6))
    o.append(arrow([(486, y1), (424, y1), (424, y3 - 26), (440, y3 - 26), (440, y3 - 14)], '#4ade80', w=2.6, label='⑦ 다시 계산', lx=418, ly=y1 + 46, lc='#4ade80', anchor='end'))
    for x, y, n in [(256, y2 - 44, 1), (244, y3 - 34, 2), (480, y2 + 76, 3), (380, y4 + 34, 4), (424, y1 + 64, 5)]:
        o.append(badge(x, y, n))
    items = [(1, '틀리면 다시 돈다', '판단 → 도구 실행 → 자가 점검. 결과가 규칙에 어긋나면 고쳐서 다시, 최대 12단계.'),
             (2, '날짜는 코드만', '에이전트는 계산을 엔진에 맡기고, 엔진은 4겹 하네스로 규칙을 확인한다.'),
             (3, '새 포인트에만 Liner Search', '관리 포인트가 새로 생긴 작업만 외부 영향을 찾는다. 6개월 넘은 글은 쓰지 않는다.'),
             (4, '연락은 문을 지나야 나간다', '시험 모드, 차단, 근무시간, 상한, 권한, 중복. 6가지를 통과해야 문자와 전화가 나간다.'),
             (5, '바깥 고리가 닫힌다', '만회안 → 승인함 → 새 버전 → 다시 계산. 승인한 순간 관리 포인트를 다시 뽑는다.')]
    return svg(W, H, ''.join(o)) + legend(items, 2)


# ── 3. 구조도 ───────────────────────────────────────────────
def d_arch():
    W, H = 760, 400
    o = [group(110, 14, 300, 372, 'ChronOS', 'code'), group(436, 14, 308, 222, 'Liner API', 'liner'), group(436, 254, 308, 132, '그 밖의 연결 · Liner 가 아닌 것', 'input')]
    o.append(node(52, 70, '사용자', 'PC · 태블릿 · 폰', w=84))
    o.append(node(186, 70, 'React', 'OS 화면 · 앱 19개', w=110))
    o.append(node(336, 70, 'FastAPI', '에이전트 · 도구', w=110, hot=True, kind='code'))
    o.append(node(336, 190, '일정 엔진', 'CPM · 관리 포인트', w=110, kind='code', hot=True))
    o.append(node(186, 190, '하네스', '4겹 규칙 · 연락 규칙', w=110, kind='code'))
    o.append(node(186, 310, 'SQLite', '일정 · 버전 · 승인', w=110))
    o.append(node(336, 310, 'Qdrant', '자료함 뜻 검색', w=110))
    for x, y, t, s in [(492, 70, 'Model · Router', '판단 · 글'), (592, 70, 'Search', '근거 · 시세 · 출처'), (692, 70, 'MCP', '법령 · 업체'),
                       (542, 170, 'Visualization', '보고서 차트'), (652, 170, 'Embeddings', '자료 색인')]:
        o.append(node(x, y, t, s, w=96, kind='liner'))
    for x, t, s in [(492, 'Gemini Live', '실시간 통화 음성'), (592, '한국AI통신', '문자 · 전화 통로'), (692, '기상청', '날씨 공공데이터')]:
        o.append(node(x, 320, t, s, w=96))
    o.append(arrow([(94, 70), (131, 70)], '#38bdf8'))
    o.append(arrow([(241, 70), (281, 70)], '#38bdf8'))
    o.append(arrow([(391, 64), (444, 64)], '#fbbf24', w=2.2))
    o.append(arrow([(391, 78), (420, 78), (420, 170), (494, 170)], '#fbbf24', label='근거 · 차트', lx=426, ly=164))
    o.append(arrow([(336, 92), (336, 168)]))
    o.append(arrow([(281, 190), (241, 190)]))
    o.append(arrow([(186, 212), (186, 288)]))
    o.append(arrow([(336, 212), (336, 288)]))
    o.append(arrow([(391, 84), (412, 84), (412, 320), (444, 320)], '#64748b', dash=True, label='통화 · 날씨', lx=416, ly=300))
    for x, y, n in [(392, 168, 1), (186, 162, 2), (436, 46, 3), (436, 286, 4)]:
        o.append(badge(x, y, n))
    items = [(1, '날짜는 여기서만', '일정 엔진(코드)이 CPM, 자원, 지연 영향, 관리 포인트를 계산한다.'),
             (2, '규칙으로 막는다', '4겹 하네스와 연락 규칙. 승인 없이 일정이 바뀌거나 연락이 나가지 않는다.'),
             (3, 'Liner 5종', 'Model·Router, Search, MCP, Visualization, Embeddings 를 일에 맞춰 쓴다.'),
             (4, 'Liner 가 아닌 것', '실시간 통화 음성은 지연 시간 때문에 Gemini Live, 통신은 한국AI통신, 날씨는 기상청.')]
    return svg(W, H, ''.join(o)) + legend(items, 2)


# ── 4. OS 확장 ───────────────────────────────────────────────
def d_os():
    W, H = 760, 330
    o = [group(250, 14, 494, 124, '모든 앱이 함께 쓰는 바닥', 'liner'), group(16, 180, 400, 136, '지금 있는 앱 19개', 'code'), group(440, 180, 304, 136, '다음에 붙일 앱', 'human')]
    o.append(node(60, 80, '사용자', '말 한 줄', w=80))
    o.append(node(178, 80, '에이전트', 'OS 전체를 맡는다', w=104, hot=True, kind='code'))
    for x, t, s in [(320, '도구 등록부', '앱마다 도구 등록'), (432, '승인함', '사람이 결정'), (544, '하네스', '규칙으로 막는다'), (656, '버전 · 기록', '되돌리기 · 추적')]:
        o.append(node(x, 80, t, s, w=100, kind='liner'))
    for x, t, s in [(86, '일정 도구', '스케줄 · 간트 · CPM'), (216, '연락처', '문자 · AI 전화'), (346, '보고서 · 자료함', '양식 학습 · 검색')]:
        o.append(node(x, 256, t, s, w=112, kind='code'))
    for x, t, s in [(500, '원가', '기성 · 비용 영향'), (592, '품질 · 안전', '검사 · 작업 허가'), (684, '구매', '발주 · 납기')]:
        o.append(node(x, 256, t, s, w=84, kind='human'))
    o.append(arrow([(100, 80), (124, 80)], '#38bdf8'))
    o.append(arrow([(230, 80), (268, 80)], '#38bdf8'))
    o.append(arrow([(178, 102), (178, 160), (216, 160), (216, 232)], '#38bdf8', w=2.2, label='창을 열고 조작', lx=222, ly=156))
    o.append(arrow([(320, 102), (320, 166), (592, 166), (592, 232)], '#4ade80', dash=True, w=2, label='도구만 등록하면 붙는다', lx=600, ly=162, lc='#4ade80'))
    for x, y, n in [(178, 52, 1), (262, 46, 2), (600, 206, 3)]:
        o.append(badge(x, y, n))
    items = [(1, '에이전트가 OS 를 맡는다', '대화 한 줄을 받아 필요한 앱 창을 직접 열고 조작한다.'),
             (2, '같은 바닥', '앱 19개가 도구 등록부, 승인함, 하네스, 버전을 함께 쓴다.'),
             (3, '붙이면 바로 쓴다', '새 앱은 폴더 하나와 도구 등록으로 붙고, 붙는 순간 에이전트가 쓴다.')]
    return svg(W, H, ''.join(o)) + legend(items, 3)


def main():
    s = HTML.read_text(encoding='utf-8')
    for name, fn in [('loop', d_loop), ('logic', d_logic), ('arch', d_arch), ('os', d_os)]:
        a, b = f'<!--D:{name}-->', '<!--/D-->'
        i = s.index(a) + len(a)
        j = s.index(b, i)
        s = s[:i] + fn() + s[j:]
    HTML.write_text(s, encoding='utf-8')
    print('diagrams ok')


if __name__ == '__main__':
    main()
