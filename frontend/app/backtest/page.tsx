import Sidebar from "@/components/shell/sidebar";
import Topbar from "@/components/shell/topbar";
import BacktestView from "@/components/backtest/backtest-view";

export default function BacktestPage() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 p-6 overflow-auto">
          <h1 className="text-2xl font-semibold mb-6">Backtest</h1>
          <BacktestView />
        </main>
      </div>
    </div>
  );
}
