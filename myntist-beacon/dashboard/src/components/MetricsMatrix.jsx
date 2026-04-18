import React from "react";

function stateClass(state) {
  if (state === "stable") return "text-green-400";
  if (state === "excitation") return "text-amber-400";
  return "text-red-400";
}

function stateBadge(state) {
  if (state === "stable") return "bg-green-900 text-green-300";
  if (state === "excitation") return "bg-amber-900 text-amber-300";
  return "bg-red-900 text-red-300";
}

function formatTs(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return ts;
  }
}

export default function MetricsMatrix({ records, loading }) {
  const rows = (records || []).slice(0, 7);

  return (
    <div className="bg-[#1F3864] rounded-xl p-5 border border-navy-700 h-full">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400 mb-4">
        Metrics Matrix — Last 7 Readings
      </h2>

      {loading && rows.length === 0 ? (
        <div className="text-center text-gray-500 py-8">Loading...</div>
      ) : rows.length === 0 ? (
        <div className="text-center text-gray-500 py-8">No telemetry records yet</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-widest text-gray-500 border-b border-navy-700">
                <th className="py-2 px-2 text-left">Time</th>
                <th className="py-2 px-2 text-right">S</th>
                <th className="py-2 px-2 text-right">dS</th>
                <th className="py-2 px-2 text-right">Q</th>
                <th className="py-2 px-2 text-right">tau</th>
                <th className="py-2 px-2 text-right">MTTR</th>
                <th className="py-2 px-2 text-center">State</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={r.id || i}
                  className="border-b border-navy-800 hover:bg-navy-700 hover:bg-opacity-30 transition-colors"
                >
                  <td className="py-2 px-2 font-mono text-gray-400 text-xs">
                    {formatTs(r.recorded_at)}
                  </td>
                  <td className={`py-2 px-2 font-mono text-right font-bold ${stateClass(r.field_state)}`}>
                    {r.S?.toFixed(4) ?? "—"}
                  </td>
                  <td className={`py-2 px-2 font-mono text-right ${(r.delta_S ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {r.delta_S !== undefined && r.delta_S !== null
                      ? `${r.delta_S >= 0 ? "+" : ""}${r.delta_S.toFixed(4)}`
                      : "—"}
                  </td>
                  <td className="py-2 px-2 font-mono text-right text-blue-300">
                    {r.Q?.toFixed(3) ?? "—"}
                  </td>
                  <td className="py-2 px-2 font-mono text-right text-purple-300">
                    {r.tau?.toFixed(4) ?? "—"}
                  </td>
                  <td className="py-2 px-2 font-mono text-right text-gray-400">
                    {r.mttr !== null && r.mttr !== undefined ? `${r.mttr.toFixed(1)}m` : "—"}
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold uppercase tracking-widest ${stateBadge(r.field_state)}`}>
                      {r.field_state ?? "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
