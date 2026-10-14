import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { refreshSession, session } from "../services/apiClient";
import { authService } from "../services/authService";
import type { AuthUser, LoginResult } from "../types";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (identifier: string, password: string) => Promise<LoginResult>;
  verifyOtp: (email: string, code: string) => Promise<AuthUser>;
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
    const result = await authService.login(identifier, password);
    if ("user" in result) setUser(result.user);
    return result;
  }, []);

  const verifyOtp = useCallback(async (email: string, code: string) => {
    const next = await authService.verifyOtp(email, code);
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

  const value = useMemo(
    () => ({ user, loading, login, verifyOtp, logout }),
    [user, loading, login, verifyOtp, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function homePathFor(user: AuthUser): string {
  if (user.role === "superadmin") return "/superadmin/businesses";
  return user.role === "admin" ? "/admin" : "/chat";
}
