"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/today", label: "Today" },
  { href: "/search", label: "Search" },
  { href: "/saved", label: "Saved" },
  { href: "/history", label: "History" },
  { href: "/schedules", label: "Schedules" },
  { href: "/watches", label: "Watches" },
  { href: "/connect", label: "Connect" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { me, logout } = useAuth();
  return (
    <div className="shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="topbar">
        <Link href={me ? "/today" : "/"} className="brand"><span className="brand-dot" aria-hidden="true" /> FocusFeed</Link>
        {me && (
          <nav className="nav" aria-label="Primary">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} aria-current={pathname?.startsWith(n.href) ? "page" : undefined}>{n.label}</Link>
            ))}
            <button className="btn-ghost btn-sm" onClick={() => void logout()} aria-label="Sign out">Sign out</button>
          </nav>
        )}
      </header>
      <main id="main" className="container">{children}</main>
    </div>
  );
}
