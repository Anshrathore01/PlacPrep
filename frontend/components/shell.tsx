"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  BrainCircuit,
  Building2,
  Code2,
  LayoutDashboard,
  LogIn,
  LogOut,
  Menu,
  MessageCircle,
  PlayCircle,
  Sparkles,
  UserPlus,
  X,
} from "lucide-react";
import { useState } from "react";
import dynamic from "next/dynamic";
import { useAuth, usePlaco } from "./providers";

const PlacoPanel = dynamic(
  () => import("./placo").then((mod) => mod.PlacoPanel),
  { ssr: false }
);

const links = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/questions", label: "Practice", icon: BrainCircuit },
  { href: "/mocks", label: "Mock Test", icon: PlayCircle },
  { href: "/ai-mock", label: "AI Mock Generator", icon: Sparkles },
  { href: "/coding", label: "Coding / DSA", icon: Code2 },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

export function AppShell({
  children,
  title,
}: {
  children: React.ReactNode;
  title?: string;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, signOut, status } = useAuth();
  const { openPanel } = usePlaco();
  const router = useRouter();
  const pathname = usePathname();

  const isAuthenticated = status === "AUTHENTICATED" && user !== null;

  const nav = (
    <nav className="space-y-1">
      {links.map(({ href, label, icon: Icon }) => {
        const isActive =
          href === "/dashboard"
            ? pathname === "/dashboard"
            : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={() => setMobileOpen(false)}
            className={`focus-ring flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
              isActive
                ? "bg-indigo-50 text-indigo-700"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
            }`}
          >
            <Icon size={18} />
            {label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="min-h-screen bg-[#f7f8fc]">
      {/* Desktop Sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-slate-200 bg-white px-5 py-6 lg:flex lg:flex-col lg:justify-between">
        <div>
          <Brand isAuthenticated={isAuthenticated} />
          <div className="mt-8">{nav}</div>
        </div>

        <div className="border-t border-slate-100 pt-4">
          {isAuthenticated ? (
            <button
              onClick={() => {
                signOut();
                router.replace("/");
              }}
              className="focus-ring flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            >
              <LogOut size={18} />
              Log out
            </button>
          ) : (
            <div className="space-y-2">
              <Link
                href="/login"
                className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-3 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                <LogIn size={16} /> Log in
              </Link>
              <Link
                href="/register"
                className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                <UserPlus size={14} /> Start preparing
              </Link>
            </div>
          )}
        </div>
      </aside>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/30 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
        >
          <aside
            className="flex h-full w-72 flex-col justify-between bg-white p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <div className="flex items-center justify-between">
                <Brand isAuthenticated={isAuthenticated} />
                <button
                  onClick={() => setMobileOpen(false)}
                  aria-label="Close menu"
                  className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                >
                  <X size={20} />
                </button>
              </div>
              <div className="mt-8">{nav}</div>
            </div>

            <div className="border-t border-slate-100 pt-4">
              {isAuthenticated ? (
                <button
                  onClick={() => {
                    signOut();
                    setMobileOpen(false);
                    router.replace("/");
                  }}
                  className="focus-ring flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-50"
                >
                  <LogOut size={18} />
                  Log out
                </button>
              ) : (
                <div className="space-y-2">
                  <Link
                    href="/login"
                    onClick={() => setMobileOpen(false)}
                    className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-3 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"
                  >
                    <LogIn size={16} /> Log in
                  </Link>
                  <Link
                    href="/register"
                    onClick={() => setMobileOpen(false)}
                    className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <UserPlus size={14} /> Start preparing
                  </Link>
                </div>
              )}
            </div>
          </aside>
        </div>
      )}

      {/* Main Content Area */}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200 bg-white/90 px-5 backdrop-blur md:px-8">
          <div className="flex items-center gap-3">
            <button
              className="focus-ring rounded-lg p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open menu"
            >
              <Menu size={20} />
            </button>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Prepwise Placement Platform
              </p>
              <h1 className="text-base font-bold text-slate-900 md:text-lg">
                {title || "Workspace"}
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => openPanel()}
              className="focus-ring flex items-center gap-2 rounded-xl border border-indigo-100 bg-indigo-50 px-3 py-1.5 text-sm font-semibold text-indigo-700 hover:bg-indigo-100"
            >
              <MessageCircle size={16} />
              <span className="hidden sm:inline">Ask Placo</span>
            </button>

            {isAuthenticated ? (
              <div className="flex items-center gap-3">
                <div className="hidden text-right sm:block">
                  <p className="text-sm font-semibold text-slate-900 leading-tight">
                    {user?.display_name || "Student"}
                  </p>
                  <p className="text-xs text-slate-500 leading-tight">{user?.email}</p>
                </div>
                <div className="grid h-9 w-9 place-items-center rounded-full bg-indigo-600 text-sm font-bold text-white shadow-sm">
                  {(user?.display_name || user?.email || "S").slice(0, 1).toUpperCase()}
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Link
                  href="/login"
                  className="rounded-xl px-3 py-1.5 text-sm font-semibold text-slate-600 hover:bg-slate-50"
                >
                  Log in
                </Link>
                <Link
                  href="/register"
                  className="rounded-xl bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
                >
                  Sign up
                </Link>
              </div>
            )}
          </div>
        </header>

        <main className="mx-auto max-w-[1440px] p-5 md:p-8">{children}</main>
      </div>

      <PlacoPanel />
    </div>
  );
}

function Brand({ isAuthenticated }: { isAuthenticated: boolean }) {
  return (
    <Link
      href={isAuthenticated ? "/dashboard" : "/"}
      className="flex items-center gap-2"
    >
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-indigo-600 text-white shadow-sm">
        <Sparkles size={18} />
      </span>
      <span className="text-lg font-bold tracking-tight text-slate-900">
        prepwise
      </span>
    </Link>
  );
}

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
}) {
  return (
    <button
      {...props}
      className={`focus-ring rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
        variant === "primary"
          ? "bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm"
          : variant === "secondary"
          ? "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
          : "text-slate-600 hover:bg-slate-100"
      } ${className}`}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "slate",
  className = "",
}: {
  children: React.ReactNode;
  tone?: "slate" | "green" | "amber" | "indigo";
  className?: string;
}) {
  const styles = {
    slate: "bg-slate-100 text-slate-600",
    green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700",
    indigo: "bg-indigo-50 text-indigo-700",
  };
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${styles[tone]} ${className}`}>
      {children}
    </span>
  );
}
