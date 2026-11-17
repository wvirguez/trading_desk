import { formatPrice, formatQuantity } from "@/lib/format";
import type { components } from "@/types/api";

type PaperOrderSchema = components["schemas"]["PaperOrderSchema"];

const AMOUNT_STEP = "0.01";
const NULL_VALUE = "—";

interface OrdersTableProps {
  orders: PaperOrderSchema[];
  tickSizes: Record<string, string>;
  lotSizes: Record<string, string>;
}

export function OrdersTable({ orders, tickSizes, lotSizes }: OrdersTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-700 text-left text-xs text-zinc-400">
            <th className="py-2 pr-3 font-medium">Símbolo</th>
            <th className="py-2 pr-3 font-medium">Dirección</th>
            <th className="py-2 pr-3 text-right font-medium">Unidades</th>
            <th className="py-2 pr-3 font-medium">Estado</th>
            <th className="py-2 pr-3 text-right font-medium">Fill</th>
            <th className="py-2 pr-3 text-right font-medium">Salida</th>
            <th className="py-2 pr-3 text-right font-medium">PnL</th>
            <th className="py-2 text-right font-medium">R</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const tick = tickSizes[order.symbol] ?? AMOUNT_STEP;
            const lot = lotSizes[order.symbol] ?? "0.00001";
            const directionColor = order.direction === "LONG" ? "text-green-400" : "text-red-400";
            return (
              <tr key={order.order_id} className="border-b border-zinc-800 font-mono">
                <td className="py-2 pr-3 text-white">{order.symbol}</td>
                <td className={`py-2 pr-3 ${directionColor}`}>{order.direction}</td>
                <td className="py-2 pr-3 text-right text-white">{formatQuantity(order.units, lot)}</td>
                <td className="py-2 pr-3 text-zinc-300">{order.status}</td>
                <td className="py-2 pr-3 text-right text-white">
                  {order.fill_price ? formatPrice(order.fill_price, tick) : NULL_VALUE}
                </td>
                <td className="py-2 pr-3 text-right text-white">
                  {order.exit_price ? formatPrice(order.exit_price, tick) : NULL_VALUE}
                </td>
                <td className="py-2 pr-3 text-right text-white">
                  {order.pnl ? formatPrice(order.pnl, AMOUNT_STEP) : NULL_VALUE}
                </td>
                <td className="py-2 text-right text-white">
                  {order.r_multiple ? formatPrice(order.r_multiple, AMOUNT_STEP) : NULL_VALUE}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
