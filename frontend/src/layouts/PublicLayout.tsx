import { Link, Outlet } from "react-router-dom";

/** Logged-out pages (login, register, pending): brand on top, centered card. */
export function PublicLayout() {
  return (
    <div className="public">
      <header className="public-bar">
        <Link to="/" className="sidebar-brand plain">
          <span className="logo" aria-hidden>
            AR
          </span>
          <span>AI Receptionist</span>
        </Link>
      </header>
      <main className="public-main">
        <Outlet />
      </main>
    </div>
  );
}
