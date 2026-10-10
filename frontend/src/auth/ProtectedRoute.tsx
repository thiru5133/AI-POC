import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import type { UserRole } from "../types";
import { useAuth } from "./AuthContext";

/** Guards children, or the nested routes (<Outlet/>) when used as a layout route. */
export function ProtectedRoute({ roles, children }: { roles: UserRole[]; children?: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <p className="muted center loading">Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!roles.includes(user.role)) {
    return (
      <div className="card denied" role="alert">
        <h1>Access denied</h1>
        <p>Your account does not have permission to view this page.</p>
      </div>
    );
  }
  return <>{children ?? <Outlet />}</>;
}
