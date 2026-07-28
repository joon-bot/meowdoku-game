/* ==========================================================================
 * 토끼네 자리 — 서비스 워커
 * --------------------------------------------------------------------------
 * 게임은 index.html 하나에 다 들어 있고 퍼즐도 안에 박혀 있어서,
 * 껍데기(HTML·이미지·폰트)만 캐시해 두면 완전히 오프라인으로 돌아간다.
 *
 * 전략
 *   - install  : 필요한 파일을 전부 미리 받아 둔다 (한 번에 실패하지 않도록 개별 처리)
 *   - fetch    : 캐시 우선. 없으면 네트워크로 받아서 캐시에 넣는다.
 *                문서 요청은 네트워크 우선 — 배포 직후에도 새 버전이 바로 보이게.
 *   - activate : 옛 버전 캐시를 지운다.
 * ========================================================================== */

// __BUILD__ 는 배포 워크플로가 커밋 해시로 바꿔 넣는다.
// 에셋 파일 이름이 고정이라(rabbit.png, jua.woff2 …) 캐시 키가 그대로면
// 새로 배포해도 옛 그림·폰트가 계속 나온다. 로컬에서는 치환 없이 그냥 쓴다.
const VERSION = 'tokkine-jari-__BUILD__';
const SHELL = [
  './',
  './index.html',
  './manifest.json',
  './assets/rabbit.png',
  './assets/rabbit_jump.png',
  './assets/rabbit_sad.png',
  './assets/icon-192.png',
  './assets/icon-512.png',
  './assets/fonts/jua.woff2',
  './assets/fonts/gowun.woff2',
];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    // 하나가 404 여도 나머지는 살아남게 개별로 받는다.
    await Promise.all(SHELL.map((url) =>
      cache.add(new Request(url, { cache: 'reload' })).catch(() => {})
    ));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 문서: 네트워크 우선 (끊기면 캐시된 껍데기로)
  if (req.mode === 'navigate') {
    e.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(VERSION);
        cache.put('./index.html', fresh.clone());
        return fresh;
      } catch (err) {
        return (await caches.match('./index.html')) || (await caches.match('./')) || Response.error();
      }
    })());
    return;
  }

  // 나머지(이미지·폰트): 캐시 우선
  e.respondWith((async () => {
    const hit = await caches.match(req);
    if (hit) return hit;
    try {
      const res = await fetch(req);
      if (res && res.status === 200 && res.type === 'basic') {
        const cache = await caches.open(VERSION);
        cache.put(req, res.clone());
      }
      return res;
    } catch (err) {
      return Response.error();
    }
  })());
});
