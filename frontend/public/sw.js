/* Service worker cho bản PWA (iOS/Android thêm vào màn hình chính).
 *
 * Nguyên tắc quan trọng nhất: KHÔNG BAO GIỜ cache dữ liệu nghiệp vụ. Một màn hình HACCP
 * hiển thị nhiệt độ lấy từ cache còn nguy hiểm hơn là không hiển thị gì, vì người vận hành
 * sẽ tin rằng kho lạnh vẫn đang âm sâu. Vì vậy /api/ luôn đi thẳng ra mạng.
 *
 * Những gì được cache chỉ là phần vỏ (HTML + asset tĩnh có hash) để app mở được khung
 * đăng nhập khi mất mạng, và để lần mở sau nhanh hơn trên TV kiosk.
 */

const VERSION = 'thermal-biz-v1';
const SHELL_CACHE = `${VERSION}-shell`;
const ASSET_CACHE = `${VERSION}-assets`;

// Danh sách cố ý ngắn: asset có hash do Vite sinh ra thay đổi theo mỗi lần build nên không
// thể hardcode. Chúng được nạp dần vào ASSET_CACHE khi chạy, còn index.html luôn được làm
// mới qua mạng trước (xem nhánh navigate bên dưới).
const SHELL_URLS = [
  './index.html',
  './favicon.svg',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/maskable-512.png',
  './icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // addAll() hỏng cả mẻ nếu một URL 404, nên lọc từng cái để thiếu icon không chết SW.
      .then((cache) => Promise.allSettled(SHELL_URLS.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => !key.startsWith(VERSION))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // Khác origin nghĩa là backend thật (VITE_API_URL) hoặc CDN — không thuộc phạm vi cache.
  if (url.origin !== self.location.origin) return;

  // scope luôn kết thúc bằng '/', nên app deploy dưới thư mục con vẫn tính đúng tiền tố API.
  const apiBase = new URL('api/', self.registration.scope).pathname;
  if (url.pathname === apiBase.slice(0, -1) || url.pathname.startsWith(apiBase)) return;

  if (request.mode === 'navigate') {
    event.respondWith(navigate(request));
    return;
  }

  if (url.pathname.startsWith(new URL('assets/', self.registration.scope).pathname)) {
    event.respondWith(immutableAsset(request));
    return;
  }

  event.respondWith(shellAsset(request));
});

/** HTML luôn hỏi mạng trước: cache mà thắng thì bản build cũ sẽ trỏ tới asset đã bị xoá. */
async function navigate(request) {
  const shellUrl = new URL('./index.html', self.registration.scope).href;
  try {
    const response = await fetch(request);
    const cache = await caches.open(SHELL_CACHE);
    await cache.put(shellUrl, response.clone());
    return response;
  } catch {
    return (await caches.match(shellUrl)) ?? Response.error();
  }
}

/** Tên file đã chứa hash nội dung nên cache-first ở đây không bao giờ phục vụ bản cũ. */
async function immutableAsset(request) {
  const cache = await caches.open(ASSET_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

/** Icon/manifest: trả bản cached cho nhanh, âm thầm làm mới nền cho lần mở sau. */
async function shellAsset(request) {
  const cache = await caches.open(SHELL_CACHE);
  const hit = await cache.match(request);
  const refresh = fetch(request)
    .then(async (response) => {
      if (response.ok) await cache.put(request, response.clone());
      return response;
    })
    // Đã có hit thì lỗi mạng không quan trọng; nuốt để không thành unhandled rejection.
    .catch(() => null);
  return hit ?? (await refresh) ?? Response.error();
}
