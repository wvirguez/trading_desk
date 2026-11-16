"use client";

import { cn } from "@/lib/utils";
import { useStream } from "@/hooks/use-stream";
import { useTerminalStore } from "@/store/terminal";

interface TopbarProps {
  children?: React.ReactNode;
}

function ConnectionIndicator() {
  const { symbol, timeframe } = useTerminalStore();
  const { connectionState } = useStream(symbol, timeframe, {});

  const getStateConfig = (state: string) => {
    switch (state) {
      case "Conectado":
        return { color: "text-green-400", dot: "bg-green-400", label: "Conectado" };
      case "Reconectando...":
        return { color: "text-yellow-400", dot: "bg-yellow-400", label: "Reconectando…" };
      case "Desconectado":
        return { color: "text-red-400", dot: "bg-red-400", label: "Desconectado" };
      default:
        return { color: "text-zinc-400", dot: "bg-zinc-400", label: state };
    }
  };

  const config = getStateConfig(connectionState);

  return (
    <div className="flex items-center gap-2" data-testid="connection-indicator">
      <span className={cn("w-2 h-2 rounded-full", config.dot)} />
      <span className={cn("text-xs font-mono", config.color)}>{config.label}</span>
    </div>
  );
}

export default function Topbar({ children = null }: TopbarProps) {
  return (
    <header className={cn("h-14 border-b bg-zinc-950 flex items-center justify-between px-4", "text-zinc-100")}>
      <div className="font-mono text-lg font-semibold tracking-tight">
        Terminal de Trading
      </div>
      <div className="flex items-center gap-4">
        {children}
        <ConnectionIndicator />
      </div>
    </header>
  );
}