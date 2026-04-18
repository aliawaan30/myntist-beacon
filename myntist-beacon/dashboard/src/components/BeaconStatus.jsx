import React from "react";

function stateColor(S) {
  if (S === null || S === undefined) return "bg-gray-600 text-gray-100";
  if (S >= 0.85) return "bg-green-500 text-white";
  if (S >= 0.70) return "bg-amber-500 text-white";
  return "bg-red-600 text-white";
}

function stateTextColor(S) {
  if (S === null || S === undefined) return "text-gray-400";
  if (S >= 0.85) return "text-green-400";
  if (S >= 0.70) return "text-amber-400";
  return "text-red-400";
}

function formatTs(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return ts;
  }
}

export default function BeaconStatus({ latest, loading, error }) {
  const S = latest?.S ?? null;
  const field_state = latest?.field_state ?? "unknown";
  const timestamp = latest?.timestamp ?? null;

  return (
    <div className="bg-[#1F3864] border-b border-navy-700 px-6 py-3">
      <div className="max-w-screen-2xl mx-auto flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <span className="text-lg font-bold tracking-wider text-white uppercase">
            Myntist Sovereign Beacon
          </span>
          {error && (
            <span className="text-xs text-red-400 bg-red-900 bg-opacity-40 px-2 py-1 rounded">
              API unreachable — showing last known data
            </span>
          )}
        </div>

        <div className="flex items-center gap-6">
          {/* S Value */}
          <div className="text-center">
            <div className={`text-4xl font-mono font-bold ${stateTextColor(S)}`}>
              {loading && S === null ? "…" : S !== null ? S.toFixed(4) : "—"}
            </div>
            <div className="text-xs text-gray-400 uppercase tracking-widest mt-0.5">
              Survivability
            </div>
          </div>

          {/* Field State Badge */}
          <div className="text-center">
            <div className={`px-4 py-1.5 rounded-full text-sm font-semibold uppercase tracking-widest ${stateColor(S)}`}>
              {field_state}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">Field State</div>
          </div>

          {/* Last Updated */}
          <div className="text-center">
            <div className="text-sm font-mono text-gray-300">
              {formatTs(timestamp)}
            </div>
            <div className="text-xs text-gray-400 uppercase tracking-widest">Last Updated</div>
          </div>
        </div>
      </div>
    </div>
  );
}
