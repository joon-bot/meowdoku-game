"""
배경 제거 — 이 그림들은 단순 색 키로는 안 된다.

측정해 보면 배경(249,237,213)과 토끼 몸통 크림색의 거리가 2~16 으로,
배경 노이즈(최대 5.5)와 구간이 겹친다. 즉 "이 색이면 배경" 이라고 자를 수 있는
문턱값이 존재하지 않는다. 몸 한가운데가 배경과 같은 색인 지점도 있다.

대신 실루엣을 닫아서 푼다.
  1) 배경에서 T_ART 이상 떨어진 픽셀 = 윤곽·눈·귀·그림자 (실루엣의 "테두리")
  2) 그 마스크를 SEAL 만큼 부풀려 테두리의 끊긴 곳을 잇는다
  3) 테두리에서 도달할 수 없는 투명 영역 = 실루엣 내부 -> 채운다
  4) 부풀린 만큼 다시 깎아 원래 윤곽으로 되돌린다 (= 모폴로지 클로징)
이러면 몸 안쪽이 배경과 같은 색이어도 구멍이 뚫리지 않는다.
"""
import sys
from collections import deque
from PIL import Image, ImageFilter

WORK = 512
T_ART = 8.0        # 배경 노이즈(5.5)보다는 위, 윤곽선(10~16)보다는 아래
SEAL = 6           # 끊긴 윤곽을 잇는 반경 (px, WORK 기준)


def cutout(src, dst, size=256, pad_ratio=0.05):
    im = Image.open(src).convert('RGB').resize((WORK, WORK), Image.LANCZOS)
    w, h = im.size
    px = im.load()

    edge = []
    for x in range(0, w, 2):
        edge += [px[x, 0], px[x, h - 1]]
    for y in range(0, h, 2):
        edge += [px[0, y], px[w - 1, y]]
    bg = tuple(sorted(c[i] for c in edge)[len(edge) // 2] for i in range(3))

    def dist(p):
        return ((p[0] - bg[0]) ** 2 + (p[1] - bg[1]) ** 2 + (p[2] - bg[2]) ** 2) ** 0.5

    # 1) 테두리 후보 + 2) 부풀려 잇기
    art = Image.new('L', (w, h), 0)
    ap = art.load()
    for y in range(h):
        for x in range(w):
            if dist(px[x, y]) >= T_ART:
                ap[x, y] = 255
    art = art.filter(ImageFilter.MaxFilter(2 * SEAL + 1))
    ap = art.load()

    # 3) 바깥에서 못 닿는 투명 영역 = 내부 -> 채운다
    seen = bytearray(w * h)
    q = deque()
    def seed(x, y):
        i = y * w + x
        if not seen[i] and not ap[x, y]:
            seen[i] = 1
            q.append((x, y))
    for x in range(w):
        seed(x, 0); seed(x, h - 1)
    for y in range(h):
        seed(0, y); seed(w - 1, y)
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                seed(nx, ny)

    solid = Image.new('L', (w, h))
    sp = solid.load()
    for y in range(h):
        for x in range(w):
            sp[x, y] = 0 if seen[y * w + x] else 255

    # 4) 부풀린 만큼 되돌리고 가장자리 정리
    solid = solid.filter(ImageFilter.MinFilter(2 * SEAL + 1))
    solid = solid.filter(ImageFilter.GaussianBlur(1.0))

    out = im.convert('RGBA')
    out.putalpha(solid)

    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    cw, ch = out.size
    side = int(max(cw, ch) * (1 + pad_ratio * 2))
    sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    sq.paste(out, ((side - cw) // 2, (side - ch) // 2))
    sq.resize((size, size), Image.LANCZOS).save(dst, optimize=True)

    ink = sum(1 for y in range(h) for x in range(w) if not seen[y * w + x])
    print(f'{dst}  배경={bg}  내용={cw}x{ch}  실루엣={ink * 100 // (w * h)}%')


if __name__ == '__main__':
    cutout(sys.argv[1], sys.argv[2])
