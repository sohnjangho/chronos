# R&D 실증 사례 간트 + CPM 선 (가상 일정). 월 단위.
X0, MW = 168, 12.0   # 0개월 x, 1개월 폭
def x(m): return X0 + m * MW
RH = 19
CRIT, GRAY, AMB, RED = '#ef4444', '#64748b', '#f59e0b', '#f87171'

def axis(y, top, h):
    o = []
    for m in range(0, 45, 6):
        o.append(f'<line x1="{x(m)}" y1="{top}" x2="{x(m)}" y2="{top+h}" stroke="rgba(255,255,255,.07)"/>')
        o.append(f'<text x="{x(m)}" y="{y}" font-size="9" fill="#64748b" text-anchor="middle">{m}개월</text>')
    return ''.join(o)

def bar(r, a, b, top, color, label=None, kind='solid', note=None, note_color='#94a3b8'):
    y = top + r * RH
    o = []
    if label: o.append(f'<text x="14" y="{y+12}" font-size="10.5" fill="#cbd5e1">{label}</text>')
    w = x(b) - x(a)
    if kind == 'solid': o.append(f'<rect x="{x(a)}" y="{y+3}" width="{w}" height="12" rx="2.5" fill="{color}"/>')
    elif kind == 'ghost': o.append(f'<rect x="{x(a)}" y="{y+3}" width="{w}" height="12" rx="2.5" fill="none" stroke="#475569" stroke-dasharray="3 2"/>')
    elif kind == 'hatch': o.append(f'<rect x="{x(a)}" y="{y+3}" width="{w}" height="12" fill="url(#hz)"/>')
    elif kind == 'missing': o.append(f'<rect x="{x(a)}" y="{y+3}" width="{w}" height="12" rx="2.5" fill="rgba(248,113,113,.18)" stroke="{RED}" stroke-width="1.5" stroke-dasharray="4 2"/>')
    elif kind == 'wait': o.append(f'<rect x="{x(a)}" y="{y+3}" width="{w}" height="12" fill="url(#hg)"/>')
    if note: o.append(f'<text x="{x(b)+5}" y="{y+12.5}" font-size="9.5" fill="{note_color}" font-weight="700" stroke="#0a0d16" stroke-width="3.2" paint-order="stroke">{note}</text>')
    return ''.join(o)

def cp(points, top, color, dash=''):
    pts = ' '.join(f'{x(m)},{top + r*RH + 9}' for r, m in points)
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2" {dash} stroke-linejoin="round"/>' + \
        ''.join(f'<circle cx="{x(m)}" cy="{top + r*RH + 9}" r="2.6" fill="{color}"/>' for r, m in points)

def vline(m, top, h, color, label, dy=0, anchor='middle'):
    return (f'<line x1="{x(m)}" y1="{top-4}" x2="{x(m)}" y2="{top+h}" stroke="{color}" stroke-width="1.8" stroke-dasharray="4 3"/>'
            f'<text x="{x(m)}" y="{top-8+dy}" font-size="9.5" font-weight="800" fill="{color}" text-anchor="{anchor}">{label}</text>')

ROWS = ['소재 개발', '시제품 제작', '성능 시험', '실증 설비 설계', '실증 설비 제작', '실증특례 승인', '설치·사용전 검사', '실증 운전 12개월', '결과 보고·종료']

def panel_a(top):
    o = [f'<rect x="0" y="{top-38}" width="720" height="{len(ROWS)*RH+58}" rx="12" fill="rgba(248,113,113,.05)" stroke="rgba(248,113,113,.4)"/>',
         f'<text x="14" y="{top-18}" font-size="13.5" font-weight="800" fill="#fff">그때 · 사람이 짠 일정표</text>',
         f'<text x="196" y="{top-18}" font-size="10" fill="#94a3b8">점선 = 계획, 막대 = 실제</text>',
         axis(top + len(ROWS)*RH + 13, top, len(ROWS)*RH)]
    o.append(bar(0, 0, 8, top, CRIT, ROWS[0]))
    o.append(bar(1, 8, 12, top, CRIT, ROWS[1]))
    o.append(bar(2, 12, 15, top, GRAY, ROWS[2]))
    o.append(bar(2, 15, 16.5, top, '', kind='hatch', note='재시험 +6주 · "여유 있으니 괜찮아"'))
    o.append(bar(3, 12, 16, top, CRIT, ROWS[3]))
    o.append(bar(4, 16, 21, top, CRIT, ROWS[4]))
    o.append(f'<text x="14" y="{top+5*RH+12}" font-size="10.5" fill="{RED}" font-weight="800">{ROWS[5]}</text>')
    o.append(bar(5, 21, 26, top, '', kind='missing', note='일정표에 없었다 · 설치 날 발견'))
    o.append(bar(6, 21, 23, top, '', ROWS[6], kind='ghost'))
    o.append(bar(6, 26, 28, top, '', kind='wait'))
    o.append(bar(6, 28, 30, top, CRIT, note='설치팀 재투입 대기 2개월', note_color='#94a3b8'))
    o.append(bar(7, 23, 35, top, '', ROWS[7], kind='ghost'))
    o.append(bar(7, 30, 42, top, CRIT))
    o.append(bar(8, 35, 36, top, '', ROWS[8], kind='ghost'))
    o.append(bar(8, 42, 43, top, CRIT))
    o.append(cp([(0,0),(0,8),(1,8),(1,12),(3,12),(3,16),(4,16),(4,21),(5,21),(5,26),(6,26),(6,30),(7,30),(7,42),(8,42),(8,43)], top, '#fbbf24'))
    o.append(vline(36, top, len(ROWS)*RH, '#e2e8f0', '계획 종료', anchor='end'))
    o.append(vline(43, top, len(ROWS)*RH, RED, '실제 +7개월', anchor='end'))
    return ''.join(o)

def panel_b(top):
    o = [f'<rect x="0" y="{top-38}" width="720" height="{len(ROWS)*RH+58}" rx="12" fill="rgba(125,211,252,.05)" stroke="rgba(125,211,252,.45)"/>',
         f'<text x="14" y="{top-18}" font-size="13.5" font-weight="800" fill="#fff">ChronOS 였다면</text>',
         f'<text x="128" y="{top-18}" font-size="10" fill="#94a3b8">착수 때 빠진 인허가를 넣고, 재시험이 들어온 그 자리에서 크리티컬 패스를 다시 계산</text>',
         axis(top + len(ROWS)*RH + 13, top, len(ROWS)*RH)]
    o.append(bar(0, 0, 8, top, CRIT, ROWS[0]))
    o.append(bar(1, 8, 12, top, CRIT, ROWS[1]))
    o.append(bar(2, 12, 15, top, AMB, ROWS[2]))
    o.append(bar(2, 15, 16.5, top, '', kind='hatch', note='재시험 +6주 → 크리티컬이 인허가 쪽으로', note_color='#fbbf24'))
    o.append(bar(3, 12, 16, top, GRAY, ROWS[3]))
    o.append(bar(4, 16, 21, top, CRIT, ROWS[4]))
    o.append(f'<text x="14" y="{top+5*RH+12}" font-size="10.5" fill="#fbbf24" font-weight="800">{ROWS[5]}</text>')
    o.append(bar(5, 16, 21, top, AMB, note='착수 때 추가 · 중간 성적서로 먼저 접수', note_color='#fbbf24'))
    o.append(bar(6, 21, 23, top, CRIT, ROWS[6]))
    o.append(bar(7, 23, 35, top, CRIT, ROWS[7]))
    o.append(bar(8, 35, 36, top, CRIT, ROWS[8]))
    o.append(cp([(0,0),(0,8),(1,8),(1,12),(2,12),(2,16),(5,16),(5,21),(6,21),(6,23),(7,23),(7,35),(8,35),(8,36)], top, '#fbbf24'))
    o.append(vline(36, top, len(ROWS)*RH, '#4ade80', '종료 그대로', anchor='start'))
    return ''.join(o)

def svg():
    hz = ('<pattern id="hz" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#fbbf24"/><line x1="0" y1="0" x2="0" y2="6" stroke="#92400e" stroke-width="2.4"/></pattern>'
          '<pattern id="hg" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#334155"/><line x1="0" y1="0" x2="0" y2="6" stroke="#64748b" stroke-width="2"/></pattern>')
    h1 = 46; h2 = h1 + len(ROWS)*RH + 82
    H = h2 + len(ROWS)*RH + 34
    leg = (f'<g font-size="9.5" fill="#cbd5e1"><line x1="420" y1="{H-6}" x2="446" y2="{H-6}" stroke="#fbbf24" stroke-width="2.2"/><text x="450" y="{H-3}">크리티컬 패스(CPM)</text>'
           f'<rect x="556" y="{H-11}" width="14" height="10" rx="2" fill="{CRIT}"/><text x="574" y="{H-3}">완료를 좌우</text>'
           f'<rect x="642" y="{H-11}" width="14" height="10" rx="2" fill="{GRAY}"/><text x="660" y="{H-3}">여유 있음</text></g>')
    return (f'<svg viewBox="0 0 720 {H+4}" width="100%" font-family="Apple SD Gothic Neo, Noto Sans KR, sans-serif"><defs>{hz}</defs>'
            + panel_a(h1) + panel_b(h2) + leg + '</svg>')

if __name__ == '__main__':
    print(svg())
