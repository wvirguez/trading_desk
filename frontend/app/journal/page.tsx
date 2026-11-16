import Sidebar from "@/components/shell/sidebar";
import Topbar from "@/components/shell/topbar";

export default function JournalPage() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 p-6 overflow-auto">
          <h1 className="text-2xl font-semibold mb-6">Diario</h1>
          <p className="text-zinc-400">Pendiente: paso 4.9</p>
        </main>
      </div>
    </div>
  );
}