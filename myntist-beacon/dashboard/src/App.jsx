import React, { useState, useEffect, useCallback } from "react";
import BeaconStatus from "./components/BeaconStatus.jsx";
import SurvivabilityGauge from "./components/SurvivabilityGauge.jsx";
import MetricsMatrix from "./components/MetricsMatrix.jsx";
import DNSStatus from "./components/DNSStatus.jsx";
import FeedHealth from "./components/FeedHealth.jsx";
import AuditLog from "./components/AuditLog.jsx";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const POLL_INTERVAL_MS = 30000;

function useApi(path, interval = POLL_INTERVAL_MS) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}${path}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, interval);
    return () => clearInterval(timer);
  }, [fetchData, interval]);

  return { data, error, loading };
}

export default function App() {
  const telemetry = useApi("/telemetry/latest");
  const historical = useApi("/telemetry/historical");
  const health = useApi("/health", 15000);

  const latest = telemetry.data;
  const records = historical.data?.records || [];

  return (
    <div className="min-h-screen bg-[#0f1c38] text-gray-100">
      {/* Top Bar */}
      <BeaconStatus
        latest={latest}
        loading={telemetry.loading}
        error={telemetry.error}
      />

      {/* Main Grid */}
      <div className="max-w-screen-2xl mx-auto p-4 space-y-4">
        {/* Row 1: Gauge + Matrix */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1">
            <SurvivabilityGauge latest={latest} loading={telemetry.loading} />
          </div>
          <div className="lg:col-span-2">
            <MetricsMatrix records={records} loading={historical.loading} />
          </div>
        </div>

        {/* Row 2: DNS + FeedHealth + AuditLog */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <DNSStatus health={health.data} loading={health.loading} error={health.error} />
          <FeedHealth latest={latest} loading={telemetry.loading} />
          <AuditLog records={records} loading={historical.loading} />
        </div>
      </div>

      {/* Footer */}
      <div className="text-center py-4 text-navy-400 text-xs opacity-50">
        Myntist Sovereign Beacon Core — Phase 1 · Polling every {POLL_INTERVAL_MS / 1000}s
      </div>
    </div>
  );
}
