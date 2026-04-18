import React from "react";

const FEEDS = [
  { key: "status", name: "status.json", path: "/api/field/v1/status.json" },
  { key: "matrix", name: "matrix.json", path: "/api/field/v1/matrix.json" },
  { key: "benchmarks", name: "benchmarks.json", path: "/api/field/v1/benchmarks.json" },
  { key: "pulse", name: "pulse.json", path: "/api/field/v1/pulse.json" },
];

const STALE_THRESHOLD_MS = 15 * 60 * 1000;

function isFresh(timestamp) {
  if (!timestamp) return false;
  try {
    const ts = new Date(timestamp).getTime();
    return Date.now() - ts < STALE_THRESHOLD_MS;
  } catch {
    return false;
  }
}

function formatAge(timestamp) {
  if (!timestamp) return "never";
  try {
    const diffMs = Date.now() - new Date(timestamp).getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "< 1m ago";
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  } catch {
    return "—";
  }
}

export default function FeedHealth({ latest, loading }) {
  const timestamp = latest?.timestamp ?? null;
  const feedsFresh = latest?.feeds_fresh ?? null;

  return (
    <div className="bg-[#1F3864] rounded-xl p-5 border border-navy-700">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400 mb-4">
        Feed Health
      </h2>

      <div className="space-y-3">
        {FEEDS.map((feed) => {
          const fresh = feed.key === "status" ? isFresh(timestamp) : feedsFresh ?? isFresh(timestamp);

          return (
            <div
              key={feed.key}
              className="bg-[#0f1c38] rounded-lg p-3 flex items-center justify-between"
            >
              <div>
                <div className="font-mono text-xs text-blue-300">{feed.name}</div>
                <div className="text-xs text-gray-500 mt-0.5 font-mono">{feed.path}</div>
              </div>
              <div className="flex flex-col items-end gap-1">
                {loading ? (
                  <span className="text-gray-500 text-xs">…</span>
                ) : fresh ? (
                  <span className="text-green-400 text-sm font-semibold">Fresh</span>
                ) : (
                  <span className="text-red-400 text-sm font-semibold">Stale</span>
                )}
                <span className="text-xs text-gray-600">
                  {feed.key === "status" ? formatAge(timestamp) : "—"}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 text-xs text-gray-600 text-center">
        Fresh = updated within 15 minutes
      </div>
    </div>
  );
}
