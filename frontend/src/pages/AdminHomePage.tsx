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
        <p className="muted">Your admin tools will appear here. In the meantime you can try the receptionist.</p>
        <Link to="/call" className="button primary">
          Open live call
        </Link>
      </div>
    </>
  );
}
