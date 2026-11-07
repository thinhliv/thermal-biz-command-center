import React from 'react';
import { HashRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { LoadingBlock } from './components/ui/StateBlock';
import { homePath } from './lib/scopes';
import { AlertsPage } from './pages/AlertsPage';
import { BusinessPage } from './pages/BusinessPage';
import { DebtsPage } from './pages/DebtsPage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OverviewPage } from './pages/OverviewPage';
import { ThermalPage } from './pages/ThermalPage';
import { AuthProvider, useAuth } from './store/auth';
import type { Scope } from './types/api';

function BootScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0b0f19]">
      <LoadingBlock label="Đang kiểm tra phiên đăng nhập…" />
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <BootScreen />;
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/**
 * Backend đã cắt section theo vai trò, nên vào thẳng URL cũng chỉ nhận trang rỗng.
 * Chặn ở client để người dùng không rơi vào màn hình trắng không lời giải thích.
 */
function RequireScope({ scope, children }: { scope: Scope; children: React.ReactNode }) {
  const { has, user } = useAuth();
  if (!has(scope)) return <Navigate to={user ? homePath(user.scopes) : '/login'} replace />;
  return <>{children}</>;
}

function RootRedirect() {
  const { user } = useAuth();
  return <Navigate to={homePath(user?.scopes)} replace />;
}

/**
 * HashRouter chứ không phải BrowserRouter: bản đóng gói chạy từ `file://` (Electron)
 * và `capacitor://` (Android/iOS), nơi `history.pushState` bị chặn theo origin.
 * Đổi sang BrowserRouter thì desktop build sẽ trắng trang ngay sau lần điều hướng đầu.
 */
export default function App() {
  return (
    <AuthProvider>
      <HashRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<RootRedirect />} />
            <Route
              path="/overview"
              element={
                <RequireScope scope="overview">
                  <OverviewPage />
                </RequireScope>
              }
            />
            <Route
              path="/thermal"
              element={
                <RequireScope scope="thermal">
                  <ThermalPage />
                </RequireScope>
              }
            />
            <Route
              path="/alerts"
              element={
                <RequireScope scope="alerts">
                  <AlertsPage />
                </RequireScope>
              }
            />
            <Route
              path="/business"
              element={
                <RequireScope scope="business">
                  <BusinessPage />
                </RequireScope>
              }
            />
            <Route
              path="/debts"
              element={
                <RequireScope scope="debts">
                  <DebtsPage />
                </RequireScope>
              }
            />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </HashRouter>
    </AuthProvider>
  );
}
