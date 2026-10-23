import { Navigate, Route, Routes } from "react-router-dom";
import { homePathFor, useAuth } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { BusinessPicker } from "./components/BusinessPicker";
import { AppShell } from "./layouts/AppShell";
import { PublicLayout } from "./layouts/PublicLayout";
import { AdminHomePage } from "./pages/AdminHomePage";
import { CallPage } from "./pages/CallPage";
import { ChatPage } from "./pages/ChatPage";
import { ConversationsPage } from "./pages/ConversationsPage";
import { LoginPage } from "./pages/LoginPage";
import { McpPage } from "./pages/McpPage";
import { PhonePage } from "./pages/PhonePage";
import { RegisterPage } from "./pages/RegisterPage";
import { VerifyOtpPage } from "./pages/VerifyOtpPage";
import { BusinessesPage } from "./pages/superadmin/BusinessesPage";
import { DomainNumbersPage } from "./pages/superadmin/DomainNumbersPage";
import { UsersPage } from "./pages/superadmin/UsersPage";

/** A customer's history is per business, so they pick one first; an admin's is their own business's. */
function ConversationsRoute() {
  const { user } = useAuth();
  if (user?.role !== "user") return <ConversationsPage />;
  return <BusinessPicker>{(businessId) => <ConversationsPage key={businessId} />}</BusinessPicker>;
}

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
        <Route path="/verify" element={<VerifyOtpPage />} />
        <Route path="/call" element={<CallPage />} />
        <Route path="/call/:id" element={<CallPage />} />
      </Route>

      <Route element={<AppShell />}>
        <Route element={<ProtectedRoute roles={["admin"]} />}>
          <Route path="/admin" element={<AdminHomePage />} />
          <Route path="/mcp" element={<McpPage />} />
          <Route path="/phone" element={<PhonePage />} />
        </Route>
        <Route element={<ProtectedRoute roles={["admin", "user"]} />}>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/conversations/:id?" element={<ConversationsRoute />} />
        </Route>
        <Route element={<ProtectedRoute roles={["superadmin"]} />}>
          <Route path="/superadmin/businesses" element={<BusinessesPage />} />
          <Route path="/superadmin/domain-numbers" element={<DomainNumbersPage />} />
          <Route path="/superadmin/users" element={<UsersPage />} />
        </Route>
      </Route>

      <Route path="*" element={<p className="muted center loading">Page not found.</p>} />
    </Routes>
  );
}
