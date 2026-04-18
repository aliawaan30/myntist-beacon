import React from "react";

const DNS_RECORDS = [
  {
    name: "_s.v1",
    label: "Survivability Signal",
    description: "s={S};dS={delta_S};tau={tau};Q={Q};ts={unix_ts}",
  },
  {
    name: "_buoy.latest",
    label: "Buoy Status",
    description: "url=…/status.json;hash={hash}",
  },
  {
    name: "_ledger.anchor",
    label: "Ledger Anchor",
    description: "ipfs={CID};zenodo=doi:{DOI}",
  },
  {
    name: "_float.audit",
    label: "Float Audit",
    description: "stub=true",
  },
];

export default function DNSStatus({ health, loading, error }) {
  const apiOk = !!health && health.status === "ok";

  return (
    <div className="bg-[#1F3864] rounded-xl p-5 border border-navy-700">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400 mb-4">
        DNS Anchors
      </h2>

      <div className="space-y-3">
        {DNS_RECORDS.map((record) => (
          <div
            key={record.name}
            className="bg-[#0f1c38] rounded-lg p-3 flex items-center justify-between"
          >
            <div>
              <div className="font-mono text-xs text-blue-300">{record.name}</div>
              <div className="text-xs text-gray-500 mt-0.5">{record.label}</div>
              <div className="text-xs text-gray-600 mt-0.5 truncate max-w-[160px]">
                {record.description}
              </div>
            </div>
            <div className="flex flex-col items-end gap-1">
              {loading ? (
                <span className="text-gray-500 text-xs">…</span>
              ) : apiOk ? (
                <span className="text-green-400 text-lg">✓</span>
              ) : (
                <span className="text-red-400 text-lg">✗</span>
              )}
              <span className="text-xs text-gray-600">
                {apiOk ? "reachable" : error ? "unreachable" : "unknown"}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 text-xs text-gray-600 text-center">
        {error ? (
          <span className="text-red-400">API unreachable</span>
        ) : health ? (
          <span>API v{health.version} · {new Date(health.timestamp).toLocaleTimeString()}</span>
        ) : null}
      </div>
    </div>
  );
}
