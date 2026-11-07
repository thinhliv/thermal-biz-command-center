const { app, BrowserWindow, Menu } = require('electron');
const path = require('path');

let mainWindow;

// TV kiosk không có chuột/bàn phím: chiếm toàn màn hình và khoá luôn các phím tắt thoát của Chromium.
const isKiosk = process.argv.includes('--kiosk');

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    kiosk: isKiosk,
    // Trùng màu nền của <body> (bg-[#0b0f19]) để lúc khởi động không nhoè sang một màu navy khác.
    backgroundColor: '#0b0f19',
    title: 'Thermal & Biz Command Center - Executive Dashboard',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  // Nạp bản build production hoặc dev server
  const isDev = process.env.NODE_ENV === 'development';
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  // Bỏ menu mặc định cho gọn khung hình TV/kiosk
  Menu.setApplicationMenu(null);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Kiosk rất dễ bị bấm đúp: bản thứ hai chỉ đưa cửa sổ đang có lên trước thay vì mở thêm
// một khung hình nữa đè lên cùng cái TV.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(createWindow);
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
