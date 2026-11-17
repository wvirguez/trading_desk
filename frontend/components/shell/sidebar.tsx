"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

interface NavItem {
  path: string;
  label: string;
  badge?: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/desk", label: "Desk" },
  { path: "/backtest", label: "Backtest" },
  { path: "/agents", label: "Agentes" },
  { path: "/journal", label: "Diario" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className="w-64 border-r bg-zinc-950 h-screen flex flex-col" aria-label="Navegación principal">
      <ul className="flex-1 space-y-1 p-4 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.path;
          return (
            <li key={item.path}>
              <Link
                href={item.path}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                  isActive
                    ? "bg-zinc-800 text-white"
                    : "text-zinc-400 hover:text-white hover:bg-zinc-800",
                )}
              >
                <span aria-current={isActive ? "page" : undefined}>{item.label}</span>
                {item.badge && (
                  <span
                    className="ml-auto text-xs text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded"
                    aria-hidden="true"
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}