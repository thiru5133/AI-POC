import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { refreshSession, session } from "../services/apiClient";
import { authService } from "../services/authService";
import type { AuthUser } from "../types";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (identifier: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const off = session.onChange((next) => active && setUser(next));
    // Restore the session from the httpOnly refresh cookie on page load.
    void refreshSession().then((result) => {
      if (!active) return;
      setUser(result?.user ?? null);
      setLoading(false);
    });
    return () => {
      active = false;
      off();
    };
  }, []);

  const login = useCallback(async (identifier: string, password: string) => {
    const next = await authService.login(identifier, password);
    setUser(next);
    return next;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function homePathFor(user: AuthUser): string {
  return user.role === "superadmin" ? "/superadmin/requests" : "/admin";
}
