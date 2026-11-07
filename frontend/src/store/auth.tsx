import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { ApiError, apiGet, apiPost, onUnauthorized, setAccessToken } from '../lib/api';
import { TOKEN_STORAGE_KEY } from '../lib/config';
import { can } from '../lib/scopes';
import type { LoginResponse, Scope, UserPublic } from '../types/api';

type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextValue {
  status: AuthStatus;
  user: UserPublic | null;
  token: string | null;
  has: (scope: Scope) => boolean;
  login: (username: string, password: string) => Promise<UserPublic>;
  logout: () => void;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

function writeStoredToken(token: string | null): void {
  if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<UserPublic | null>(null);
  const [token, setToken] = useState<string | null>(null);

  const clearSession = useCallback(() => {
    setAccessToken(null);
    writeStoredToken(null);
    setToken(null);
    setUser(null);
    setStatus('anonymous');
  }, []);

  const adopt = useCallback((nextToken: string, nextUser: UserPublic) => {
    setAccessToken(nextToken);
    writeStoredToken(nextToken);
    setToken(nextToken);
    setUser(nextUser);
    setStatus('authenticated');
  }, []);

  useEffect(() => {
    onUnauthorized(clearSession);
  }, [clearSession]);

  // Token còn trong localStorage vẫn có thể hết hạn hoặc bị đổi vai trò,
  // nên phải xác minh lại bằng /api/auth/me thay vì tin vào thông tin đã lưu.
  useEffect(() => {
    const stored = readStoredToken();
    if (!stored) {
      setStatus('anonymous');
      return;
    }
    setAccessToken(stored);
    setToken(stored);
    const controller = new AbortController();
    apiGet<UserPublic>('/api/auth/me', controller.signal)
      .then((me) => {
        setUser(me);
        setStatus('authenticated');
      })
      .catch((error: unknown) => {
        if ((error as Error).name === 'AbortError') return;
        clearSession();
      });
    return () => controller.abort();
  }, [clearSession]);

  const login = useCallback(
    async (username: string, password: string): Promise<UserPublic> => {
      const response = await apiPost<LoginResponse>('/api/auth/login', { username, password });
      adopt(response.access_token, response.user);
      return response.user;
    },
    [adopt],
  );

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<void> => {
      await apiPost<void>('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      });
    },
    [],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      token,
      has: (scope: Scope) => can(user?.scopes, scope),
      login,
      logout: clearSession,
      changePassword,
    }),
    [status, user, token, login, clearSession, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth phải nằm trong <AuthProvider>');
  return context;
}

export function describeAuthError(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Đăng nhập thất bại, thử lại sau.';
}
