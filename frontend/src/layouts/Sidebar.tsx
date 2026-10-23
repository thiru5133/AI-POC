import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { DashboardIcon, InboxIcon, ChatIcon, LogoutIcon, PhoneIcon, PlugIcon, UsersIcon } from "../components/icons";
import type { UserRole } from "../types";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  roles: UserRole[];
}

const ROLE_LABEL: Record<UserRole, string> = { superadmin: "Super admin", admin: "Business admin", user: "User" };

const NAV_ITEMS: NavItem[] = [
  { to: "/admin", label: "Dashboard", icon: <DashboardIcon />, roles: ["admin"] },
  { to: "/conversations", label: "Conversations", icon: <ChatIcon />, roles: ["admin"] },
  { to: "/mcp", label: "MCP integration", icon: <PlugIcon />, roles: ["admin"] },
  { to: "/phone", label: "Phone", icon: <PhoneIcon />, roles: ["admin"] },
  { to: "/superadmin/businesses", label: "Businesses", icon: <InboxIcon />, roles: ["superadmin"] },
  { to: "/superadmin/domain-numbers", label: "Domain numbers", icon: <PhoneIcon />, roles: ["superadmin"] },
  { to: "/superadmin/users", label: "Users", icon: <UsersIcon />, roles: ["superadmin"] },
  { to: "/chat", label: "Chat & voice", icon: <PhoneIcon />, roles: ["admin", "user"] },
  { to: "/conversations", label: "My conversations", icon: <ChatIcon />, roles: ["user"] },
];

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;

  const items = NAV_ITEMS.filter((item) => item.roles.includes(user.role));
  const initials = user.name
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <aside className={`sidebar${open ? " open" : ""}`} aria-label="Main navigation">
      <div className="sidebar-brand">
        <span className="logo" aria-hidden>
          AR
        </span>
        <span>AI Receptionist</span>
      </div>

      <nav className="sidebar-nav">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
          >
            {item.icon}
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-user">
        <span className="avatar" aria-hidden>
          {initials || "?"}
        </span>
        <div className="sidebar-user-text">
          <strong>{user.name}</strong>
          <span>{ROLE_LABEL[user.role]}</span>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="Log out"
          title="Log out"
          onClick={() => void logout().then(() => navigate("/login"))}
        >
          <LogoutIcon />
        </button>
      </div>
    </aside>
  );
}
