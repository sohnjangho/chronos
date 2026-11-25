# 쓰는 법: python3 docs/manual/annotate.py docs/manual/img  (Pillow 필요)
# 받은 그림에 빨간 상자·번호를 그린다(원본은 그대로, <이름>-m.png 로 저장).
import sys
from PIL import Image, ImageDraw, ImageFont
IMG = sys.argv[1]
RED = (224, 36, 43)
M = 44  # 왼쪽·위 여백(번호 원이 잘리지 않게)

def load(name, crop=None):
    im = Image.open(f'{IMG}/{name}').convert('RGB')
    if crop: im = im.crop(crop)
    out = Image.new('RGB', (im.width + 2 * M, im.height + 2 * M), 'white')
    out.paste(im, (M, M))
    return out

def mark(im, marks, scale=1.0):
    d = ImageDraw.Draw(im)
    r = int(17 * scale)
    font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', int(24 * scale), index=1)
    for (x0, y0, x1, y1), n, side in marks:
        x0 += M; x1 += M; y0 += M; y1 += M; p = int(6 * scale)
        d.rounded_rectangle((x0-p, y0-p, x1+p, y1+p), radius=int(9*scale), outline='white', width=int(8*scale))
        d.rounded_rectangle((x0-p, y0-p, x1+p, y1+p), radius=int(9*scale), outline=RED, width=max(3, int(4*scale)))
        cx, cy = ((x0-p-r-6, (y0+y1)/2) if side == 'L' else (x0-p, y0-p))
        d.ellipse((cx-r-2, cy-r-2, cx+r+2, cy+r+2), fill='white')
        d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=RED)
        d.text((cx, cy), str(n), fill='white', font=font, anchor='mm')
    return im

def save(im, name, maxw=1700):
    if im.width > maxw: im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    im.save(f'{IMG}/{name}', optimize=True)
    print(name, im.size)

T = 'T'; L = 'L'
# 4장
a = load('assign-01.png')
save(mark(a, [((616,243,1648,303),1,L), ((1662,246,1749,301),2,T), ((1778,265,2005,325),3,T), ((30,800,2005,905),4,L)], 1.2), 'assign-01-m.png')
a2 = Image.open(f'{IMG}/assign-02.png').convert('RGB'); a3 = Image.open(f'{IMG}/assign-03.png').convert('RGB')
a3 = a3.resize((a3.width*2, a3.height*2), Image.LANCZOS)
c = Image.new('RGB', (a2.width + a3.width + 80, max(a2.height, a3.height)), 'white')
c.paste(a2, (0, 0)); c.paste(a3, (a2.width + 80, 20))
cm = Image.new('RGB', (c.width + 2*M, c.height + 2*M), 'white'); cm.paste(c, (M, M))
save(mark(cm, [((308,17,1047,470),1,T), ((a2.width+80+16, 20+16, a2.width+80+484, 20+330),2,T)]), 'assign-02-m.png')
# 6장
save(mark(load('notify-01-connection-card.png'), [((45,165,205,218),1,T), ((219,165,355,218),2,T), ((1238,53,1507,88),3,T), ((62,320,615,362),4,L)]), 'notify-01-m.png')
save(mark(load('notify-03-sender.png'), [((27,76,744,146),1,L)]), 'notify-03-m.png')
save(mark(load('notify-04-test-mode.png'), [((26,76,496,108),1,L), ((26,216,746,273),2,L)]), 'notify-04-m.png')
save(mark(load('notify-07-agent-permission.png'), [((190,126,431,182),1,L), ((190,315,431,370),2,L)]), 'notify-07-m.png')
save(mark(load('notify-10-inbound-scope.png'), [((26,75,1545,129),1,L), ((26,278,746,337),2,L)]), 'notify-10-m.png')
save(mark(load('notify-05-limits.png', (0, 0, 1572, 1680)), [((26,17,751,61),1,L), ((1394,82,1544,136),2,T), ((437,264,526,318),3,T)]), 'notify-05-m.png')
save(mark(load('notify-08-ai-call.png'), [((35,442,175,496),1,T), ((190,442,321,496),2,T), ((337,442,522,496),3,T), ((640,442,797,496),4,T), ((49,585,472,629),5,L)]), 'notify-08-m.png')
v = load('notify-09-voice-picker.png', (0, 590, 1572, 1432))
save(mark(v, [((35,699-590,1506,908-590),1,L), ((1402,1228-590,1537,1280-590),2,T)]), 'notify-09-m.png')
save(mark(load('notify-12-diagnosis.png'), [((0,74,1572,381),1,L)]), 'notify-12-m.png')
