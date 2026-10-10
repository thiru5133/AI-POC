import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { MenuIcon } from "../components/icons";
import { Sidebar } from "./Sidebar";

/** Authenticated layout: sidebar + content. Every route nested inside requires a logged-in admin or superadmin. */
export function AppShell() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);

  return (
    <ProtectedRoute roles={["admin", "superadmin"]}>
      <div className="shell">
        <Sidebar open={open} onNavigate={() => setOpen(false)} />
        {open && <button type="button" className="scrim" aria-label="Close menu" onClick={() => setOpen(false)} />}
        <div className="shell-main">
          <div className="topbar">
            <button type="button" className="icon-button" aria-label="Open menu" onClick={() => setOpen(true)}>
              <MenuIcon />
            </button>
            <strong>AI Receptionist</strong>
          </div>
          <main className="content">
            <Outlet />
          </main>
        </div>
      </div>
    </ProtectedRoute>
  );
}
