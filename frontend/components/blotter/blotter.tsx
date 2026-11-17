"use client";

import { useBlotter } from "@/hooks/use-blotter";
import { useRefreshOrders } from "@/hooks/use-refresh-orders";
import { AccountSummary } from "./account-summary";
import { OrdersTable } from "./orders-table";

interface BlotterProps {
  tickSizes?: Record<string, string>;
  lotSizes?: Record<string, string>;
}

export function Blotter({ tickSizes = {}, lotSizes = {} }: BlotterProps) {
  const { data, error, isLoading, refetch } = useBlotter();
  const refresh = useRefreshOrders();

  if (isLoading) {
    return <div className="py-8 text-center text-sm text-zinc-500">Cargando blotter…</div>;
  }

  if (error || !data) {
    return (
      <div role="alert" className="space-y-3 py-8 text-center text-sm">
        <p className="text-red-400">
          {error?.detail ?? "No se pudo cargar el blotter"}
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="rounded border border-zinc-600 px-3 py-1 text-zinc-200 hover:bg-zinc-800"
        >
          Reintentar
        </button>
      </div>
    );
  }

  const hasPending = data.orders.some((order) => order.status === "PENDING_FILL");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-zinc-400">Paper trading simulado: sin costes ni slippage</p>
        <button
          type="button"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="rounded border border-zinc-600 px-3 py-1 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
        >
          {refresh.isPending ? "Actualizando…" : "Actualizar"}
        </button>
      </div>

      {refresh.error && (
        <p role="alert" className="text-sm text-red-400">
          {refresh.error.detail}
        </p>
      )}

      {data.daily_loss_limit_reached && (
        <p role="alert" className="rounded border border-amber-700 bg-amber-950/40 p-2 text-sm text-amber-300">
          Límite de pérdida diaria alcanzado: no se aceptarán nuevas ejecuciones hoy.
        </p>
      )}

      <AccountSummary blotter={data} />
      <p className="text-xs text-zinc-500">
        PnL no realizado = vs. último cierre ingerido (no es tiempo real)
      </p>

      {data.warnings.map((warning) => (
        <p key={warning} className="text-xs text-amber-400">
          {warning}
        </p>
      ))}

      {data.orders.length === 0 ? (
        <p className="py-6 text-center text-sm text-zinc-500">
          Sin órdenes simuladas. Ejecuta una señal aprobada.
        </p>
      ) : (
        <>
          <OrdersTable orders={data.orders} tickSizes={tickSizes} lotSizes={lotSizes} />
          {hasPending && (
            <p className="text-xs text-zinc-500">
              PENDING_FILL: orden ejecutada que aún espera una vela posterior para rellenarse.
              Pulsa «Actualizar» para avanzarla con las velas ya ingeridas.
            </p>
          )}
        </>
      )}
    </div>
  );
}
