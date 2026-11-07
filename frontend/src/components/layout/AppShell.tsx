import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { DashboardProvider, useDashboard } from '../../store/dashboard';
import { useAuth } from '../../store/auth';
import { AlertTicker } from './AlertTicker';
import { ChangePasswordDialog } from './ChangePasswordDialog';
import { NavBar } from './NavBar';
import { TopBar } from './TopBar';

function ShellBody() {
  const { has } = useAuth();
  const { alerts } = useDashboard();
  const [passwordOpen, setPasswordOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-[#0b0f19]">
      <TopBar onChangePassword={() => setPasswordOpen(true)} />
      <NavBar />
      {has('alerts') ? <AlertTicker alerts={alerts} /> : null}
      <main className="flex-1 px-3 py-3 md:px-4 md:py-4">
        <Outlet />
      </main>
      <ChangePasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </div>
  );
}

/**
 * Shell dùng chung cho mọi trang đã đăng nhập. Đặt DashboardProvider ở đây để cả app
 * chỉ mở đúng MỘT WebSocket và một luồng REST, đổi tab không nạp lại dữ liệu.
 */
export function AppShell() {
  return (
    <DashboardProvider>
      <ShellBody />
    </DashboardProvider>
  );
}
