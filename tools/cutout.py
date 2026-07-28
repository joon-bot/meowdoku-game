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

think 포즈에서 두 가지를 고쳤다.
  · 머리 오른쪽은 배경과 RGB 가 아예 같아서(거리 1~2) 윤곽이 45px 가까이 끊긴다.
    T_ART=8 로는 그 구간의 얇은 테두리(거리 5~8)마저 놓쳐 배경 채우기가
    머리 안으로 새어 들어갔다. T_ART 를 5 로 낮춰 테두리를 살리고,
    SEAL 을 끊긴 길이에 맞게 키웠다.
  · 부풀리기·깎기를 정사각 커널(MaxFilter/MinFilter)로 하면 크게 잡을수록
    가장자리에 계단 자국이 남는다. 가우시안 블러 + 문턱값으로 바꿨다.
    블러는 등방이라 커널 방향이 없고, 그래서 어느 각도에서도 매끈하다.

기존 rabbit / rabbit_jump / rabbit_sad 는 예전 설정(T_ART=8, 정사각 SEAL=6)으로
이미 깨끗하게 뽑혀 커밋돼 있다. 원본이 저장소에 없어 재현·재검증이 불가능하므로
그 셋은 다시 만들지 않았다. 다른 그림을 새로 넣을 땐 --t-art / --seal 로 맞춘다.
"""
import argparse
from collections import deque
from PIL import Image, ImageFilter

WORK = 512
T_ART = 5.0        # 배경 노이즈(최대 4.2)보다는 위, 가장 흐린 윤곽(5~8)보다는 아래
SEAL = 9           # 끊긴 윤곽을 잇는 반경 (px, WORK 기준)
DILATE_LEVEL = 40  # 블러 결과를 자르는 문턱 — 낮을수록 많이 부푼다
ERODE_LEVEL = 215  # 높을수록 많이 깎인다 (부풀린 만큼 되돌리는 값)


def _reshape(mask, sigma, level):
    """블러 + 문턱값 = 원형 팽창/침식. 정사각 커널과 달리 계단 자국이 없다."""
    return mask.filter(ImageFilter.GaussianBlur(sigma)).point(
        lambda v: 255 if v >= level else 0)


def cutout(src, dst, size=256, pad_ratio=0.05, t_art=T_ART, seal=SEAL):
    im = Image.open(src).convert('RGB').resize((WORK, WORK), Image.LANCZOS)
    w, h = im.size
    # 배경 노이즈를 살짝 눌러 둔다 — 흐린 윤곽과 노이즈의 간격을 벌린다
    px = im.filter(ImageFilter.GaussianBlur(1.0)).load()

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
            if dist(px[x, y]) >= t_art:
                ap[x, y] = 255
    sealed = _reshape(art, seal, DILATE_LEVEL)
    ap = sealed.load()

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
    solid = _reshape(solid, seal, ERODE_LEVEL)
    solid = solid.filter(ImageFilter.GaussianBlur(0.8))

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
    ap_ = argparse.ArgumentParser(description='크림 배경 그림에서 토끼만 오려낸다')
    ap_.add_argument('src')
    ap_.add_argument('dst')
    ap_.add_argument('--size', type=int, default=256)
    ap_.add_argument('--t-art', type=float, default=T_ART, help='테두리로 볼 최소 색 거리')
    ap_.add_argument('--seal', type=int, default=SEAL, help='끊긴 윤곽을 잇는 반경(px)')
    a = ap_.parse_args()
    cutout(a.src, a.dst, size=a.size, t_art=a.t_art, seal=a.seal)
