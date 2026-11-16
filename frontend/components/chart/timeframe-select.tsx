"use client";

import { useTerminalStore } from "@/store/terminal";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"] as const;

export default function TimeframeSelect() {
  const { timeframe, setTimeframe } = useTerminalStore();

  return (
    <div className="w-32">
      <Select value={timeframe} onValueChange={setTimeframe}>
        <SelectTrigger>
          <SelectValue placeholder="TF" />
        </SelectTrigger>
        <SelectContent>
          {TIMEFRAMES.map((tf) => (
            <SelectItem key={tf} value={tf}>
              {tf}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}