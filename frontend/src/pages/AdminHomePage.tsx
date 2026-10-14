import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";

export function AdminHomePage() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader title="Dashboard" subtitle={`Welcome back, ${user?.name ?? ""}`} />
      <div className="card">
        <h2>Get started</h2>
        <p className="muted">Connect your systems under MCP integration, review what customers asked under Conversations, or try the assistant yourself.</p>
        <Link to="/chat" className="button primary">
          Try your assistant
        </Link>
      </div>
    </>
  );
}
