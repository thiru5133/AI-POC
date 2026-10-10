import { Navigate, Route, Routes } from "react-router-dom";
import { homePathFor, useAuth } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppShell } from "./layouts/AppShell";
import { PublicLayout } from "./layouts/PublicLayout";
import { AdminHomePage } from "./pages/AdminHomePage";
import { CallPage } from "./pages/CallPage";
import { LoginPage } from "./pages/LoginPage";
import { PendingApprovalPage } from "./pages/PendingApprovalPage";
import { RegisterPage } from "./pages/RegisterPage";
import { RequestsPage } from "./pages/superadmin/RequestsPage";
import { UsersPage } from "./pages/superadmin/UsersPage";

/** "/" has no page of its own: send people to their home, or to the login screen. */
function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <p className="muted center loading">Loading…</p>;
  return <Navigate to={user ? homePathFor(user) : "/login"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />

      <Route element={<PublicLayout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/pending" element={<PendingApprovalPage />} />
      </Route>

      <Route element={<AppShell />}>
        <Route path="/admin" element={<AdminHomePage />} />
        <Route path="/call" element={<CallPage />} />
        <Route element={<ProtectedRoute roles={["superadmin"]} />}>
          <Route path="/superadmin/requests" element={<RequestsPage />} />
          <Route path="/superadmin/users" element={<UsersPage />} />
        </Route>
      </Route>

      <Route path="*" element={<p className="muted center loading">Page not found.</p>} />
    </Routes>
  );
}
