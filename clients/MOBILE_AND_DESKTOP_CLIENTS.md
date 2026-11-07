# ỨNG DỤNG ĐA NỀN TẢNG (CLIENT SUITE)
## Windows (.exe) · Linux (.AppImage/.deb) · Android (.apk) · iOS (PWA) · TV Kiosk

Nguyên tắc đã chốt: **app tự viết là trung tâm**, các nền tảng mã nguồn mở (ERPNext, Invoice Ninja,
Home Assistant, Twenty, ThingsBoard…) là **nguồn dữ liệu** chảy về FastAPI. Người dùng chỉ nhìn vào
một màn hình duy nhất — Nhiệt × Kinh doanh — thay vì phải mở năm giao diện khác nhau.

Toàn bộ client bên dưới đóng gói từ cùng một codebase `frontend/` (React + Vite), nên không có bản
nào lệch tính năng so với bản nào.

---

## 0. ĐỊA CHỈ BACKEND ĐƯỢC "NUNG" VÀO LÚC BUILD

Vite nhúng các biến `VITE_*` thẳng vào bundle, nên `VITE_API_URL` **không đổi được sau khi build**.

| Bản chạy | `VITE_API_URL` | Vì sao |
|---|---|---|
| Trình duyệt (dev) | *để trống* | Vite proxy `/api` và `/ws` sang `localhost:8080` |
| Trình duyệt (prod sau reverse proxy) | *để trống* | Cùng origin với backend |
| Electron / iOS simulator | *để trống* | `src/lib/config.ts` tự suy ra `http://localhost:8080` |
| Android emulator | *để trống* | Tự suy ra `http://10.0.2.2:8080` (alias của emulator về máy host) |
| **Android máy thật / iOS thật / bản phát hành** | **BẮT BUỘC đặt `https://…`** | Xem mục 3 |

Đặt qua `frontend/.env` (xem `frontend/.env.example`) hoặc qua biến môi trường lúc build — Vite ưu tiên
`process.env` hơn file `.env`, nên CI chỉ cần `env: VITE_API_URL`.

---

## 1. DESKTOP — WINDOWS & LINUX (ELECTRON)

`frontend/electron/main.js` nạp `dist/index.html` từ `file://`, ẩn menu, đặt nền `#0b0f19` trùng màu
`<body>` để lúc khởi động không nhoè sang một màu navy khác.

**Build tại máy:**

```bash
cd frontend
npm run electron:build:win     # -> release/ThermalBiz-Setup-1.0.0.exe  (NSIS)
                               # -> release/ThermalBiz-Portable-1.0.0.exe
npm run electron:build:linux   # -> release/ThermalBiz-1.0.0.AppImage
                               # -> release/ThermalBiz-1.0.0.deb
npm run electron:pack          # chỉ giải nén ra release/win-unpacked/ để chạy thử, không tạo installer
```

**Build bằng CI** (khuyên dùng — không cần cài electron-builder ở máy dev): xem mục 5.

Chỗ cài đặt sau khi chạy installer:

- Windows: `%LOCALAPPDATA%\Programs\Thermal & Biz Command Center\ThermalBiz.exe`
  (NSIS `perMachine: false`, có cho chọn thư mục, tạo shortcut Desktop + Start Menu,
  gỡ cài đặt **không** xoá app data)
- Linux deb: `/opt/Thermal & Biz Command Center/ThermalBiz` + symlink trong `/usr/bin`

`app.asar` chỉ chứa `dist/` và `electron/` (~1 MB): mọi thư viện UI đã được Vite gộp vào bundle, và
`dependencies` trong `package.json` cố ý để trống nên electron-builder không nhét `node_modules` vào.

---

## 2. TV KIOSK CHO BAN GIÁM ĐỐC

Script một-cú-bấm, tự tìm bản desktop đã cài và bật chế độ kiosk **thật** (chiếm toàn màn hình, khoá
các phím tắt thoát của Chromium):

- Windows: [`clients/desktop-kiosk/launch-kiosk.bat`](desktop-kiosk/launch-kiosk.bat)
- Linux: [`clients/desktop-kiosk/launch-kiosk.sh`](desktop-kiosk/launch-kiosk.sh)

Thứ tự ưu tiên: bản Electron đã cài → nếu không có thì mở trình duyệt ở chế độ kiosk
(Edge/Chrome trên Windows; Chrome/Chromium/Firefox trên Linux).

Hai biến tuỳ chỉnh, đều **không bắt buộc**:

```bash
THERMAL_KIOSK_URL=http://localhost:5173   # địa chỉ bản web, dùng khi rơi xuống nhánh trình duyệt
THERMAL_KIOSK_EXE=/duong/dan/ThermalBiz   # nếu cài app ở chỗ khác chỗ mặc định
```

Electron có khoá single-instance: kiosk rất dễ bị bấm đúp, bản thứ hai chỉ đưa cửa sổ đang có lên
trước thay vì mở thêm một khung hình nữa đè lên cùng cái TV.

---

## 3. ANDROID — FILE .APK THẬT (CAPACITOR)

Thư mục `frontend/android/` **đã được commit** (đúng khuyến nghị của Capacitor), nên CI chỉ cần
`cap sync`, không phải `cap add`. Icon launcher (đủ 5 mật độ + adaptive icon) và 11 splash screen đã
được sinh theo màu nền `#0b0f19` của app.

**Build bằng CI** (xem mục 5) → artifact `android-apk`. Máy dev không cần cài Java/Android SDK.

**Build tại máy** (cần JDK 17 + Android SDK, Capacitor 5 dùng Android Gradle Plugin 8.x):

```bash
cd frontend
npm run cap:sync                      # build web + copy sang android/
npm run cap:android                   # mở Android Studio
# hoặc build thẳng:
cd android && ./gradlew assembleDebug
```

### ⚠️ Bản phát hành BẮT BUỘC dùng `https://`

`capacitor.config.json` đặt `androidScheme: "https"`, nên WebView chạy ở origin `https://localhost`.
Mọi request tới `http://…` vì thế là **mixed content** và bị Android chặn. Ngoài ra `targetSdk 33`
còn chặn cleartext ở tầng network policy.

Capacitor có khoá `android.allowMixedContent`, nhưng chính tài liệu của họ ghi rõ *"This is not
intended for use in production"* — nên repo này **không** bật nó, và cũng không thêm
`usesCleartextTraffic` hay `network_security_config.xml`. Muốn APK nối được backend thật, hãy chạy
workflow `Packages` với `api_url=https://…`.

Khi `api_url` để trống hoặc là `http://`, CI sẽ in ra một **warning** (không fail) để vẫn lấy được
APK chạy thử trên emulator.

---

## 4. iOS — PWA (VÀ ĐƯỜNG CAPACITOR KHI CÓ MÁY MAC)

Repo hiện không sinh project Xcode vì việc đó phải làm trên macOS. Có hai đường:

**(a) PWA — dùng được ngay, không cần Mac.** App có `manifest.webmanifest` (3 icon, có bản
`maskable`) và `sw.js`, nên chỉ cần phục vụ `frontend/dist/` qua **`https://`** rồi mở Safari →
Share → **"Add to Home Screen"** là có app toàn màn hình như native.

FastAPI hiện **không** mount static, nên phải có một web server riêng đứng trước `dist/`:

```bash
cd frontend && npm run preview    # chạy thử tại máy: http://localhost:4173
```

`vite preview` kế thừa `server.proxy` từ `vite.config.ts`, nên bản chạy thử này vẫn gọi được
backend ở `localhost:8080` mà không cần đặt `VITE_API_URL`. Khi ra production thì dùng nginx/Caddy
phục vụ `dist/` và proxy ngược `/api` + `/ws` về FastAPI — cùng origin nên `VITE_API_URL` vẫn để trống.

> Service worker chỉ bật khi `import.meta.env.PROD`, tức là `npm run dev` sẽ không bao giờ cache.

**(b) Capacitor iOS — khi có Mac:**

```bash
cd frontend
npx cap add ios && npm run cap:sync && npx cap open ios
```

Cũng như Android: `capacitor://` không cùng origin với backend nên **phải** đặt `VITE_API_URL`
là `https://…`, và App Transport Security của iOS còn gắt hơn Android.

### Service worker chỉ dành cho bản trình duyệt

`src/lib/pwa.ts` **không** đăng ký service worker khi:

- `file://` (Electron) hoặc `capacitor://` (iOS) — scheme không có origin hợp lệ cho SW;
- **Android**, dù origin `https://localhost` trông giống hệt một trang web thật — chỉ bridge native
  (`window.Capacitor.isNativePlatform()`) mới phân biệt được. Không loại trừ thì Android và iOS chạy
  hai đường khác nhau, và SW đi cache đúng những file Capacitor đã đặt sẵn trên máy;
- dev server — SW cache asset sẽ phục vụ bản cũ đè lên hot-reload.

Chiến lược cache an toàn cho một màn hình HACCP: **không bao giờ cache `/api/`**; điều hướng là
network-first với `index.html` đã cache làm dự phòng (cache-first cho HTML sẽ trỏ vào các asset đã
bị hash lại ở lần deploy sau → trắng màn hình); `/assets/` là cache-first (an toàn vì Vite băm tên
file); icon/manifest là stale-while-revalidate. WebSocket không đi qua SW nên không cần xử lý `/ws/`.

---

## 5. CI — GITHUB ACTIONS

Hai workflow trong `.github/workflows/`:

| File | Khi nào chạy | Làm gì |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | mọi push / PR | pytest backend · `alembic upgrade head` trên Postgres 16 · typecheck + vitest + build frontend, rồi khẳng định đủ 8 asset PWA trong `dist/` |
| [`packages.yml`](../.github/workflows/packages.yml) | tag `v*` **hoặc** bấm "Run workflow" | đóng gói desktop (Windows + Linux) và build APK Android |

`packages.yml` cố ý **không** chạy mỗi lần push lên `main`: một lần build Electron kéo dài hàng chục
phút và sinh ra ~250 MB, trong khi code đã được `ci.yml` kiểm tra rồi.

**Lấy bản dựng thử:** GitHub → tab *Actions* → workflow **Packages** → *Run workflow* → điền
`api_url` (để trống = bản nối localhost/emulator) → chạy. Artifact giữ 30 ngày:
`desktop-windows`, `desktop-linux`, `android-apk`.

**Phát hành:** `git tag v1.1.0 && git push origin v1.1.0`.

Workflow đặt `permissions: contents: read` (tối thiểu) và `timeout-minutes: 45` mỗi job.

---

## 6. CÁC NỀN TẢNG MÃ NGUỒN MỞ — VAI TRÒ MỚI

Chúng vẫn chạy, nhưng **không còn là giao diện người dùng cuối**:

| Nền tảng | Vai trò |
|---|---|
| ThingsBoard / Home Assistant | thu telemetry nhiệt, đồng hồ điện |
| Invoice Ninja / ERPNext / Twenty | hoá đơn, công nợ, khách hàng, vật tư |
| Grafana | tuỳ chọn — dashboard kỹ thuật cho tổ vận hành, không phải màn hình BGĐ |

Backend đã có sẵn hai cửa nhận dữ liệu, khoá bằng `X-Connector-API-Key`:
`POST /api/ingest/telemetry` (+ `/batch`) và `POST /api/ingest/billing`.

> **Còn nợ (đợt 4):** hai connector trong `connectors/` hiện vẫn ghi **OSS → OSS**
> (`thingsboard-to-erpnext` đẩy sang `/api/resource/{doctype}` của ERPNext,
> `ha-to-invoiceninja` đẩy sang `/api/v1/invoices` của Invoice Ninja) chứ chưa đẩy về
> `/api/ingest/*`. Nghĩa là màn hình của mình đang chạy trên dữ liệu seed, chưa phải số liệu thật
> từ hiện trường. Việc nối lại hai connector đó, kèm ΔkWh / TOU 3 giá / idempotency, là nội dung
> của đợt 4 — chưa xong thì đừng coi số trên app là số đo thật.

Nếu vẫn muốn dùng client chính thức của chúng (Invoice Ninja Flutter, Home Assistant Companion,
Grafana mobile) cho một tác vụ chuyên biệt thì cài bình thường; chỉ cần nhớ rằng số liệu ở đó
chưa qua được các rule nghiệp vụ (COP, HACCP, TOU 3 giá, hạn mức tín dụng) mà backend của mình áp.
