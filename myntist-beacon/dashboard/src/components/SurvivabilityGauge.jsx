import React from "react";

const SIZE = 200;
const CX = SIZE / 2;
const CY = SIZE / 2;
const R = 80;
const STROKE = 12;

function polarToXY(angle, r) {
  const rad = (angle - 90) * (Math.PI / 180);
  return {
    x: CX + r * Math.cos(rad),
    y: CY + r * Math.sin(rad),
  };
}

function arcPath(startAngle, endAngle, r) {
  const start = polarToXY(startAngle, r);
  const end = polarToXY(endAngle, r);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

function gaugeColor(S) {
  if (S === null || S === undefined) return "#6b7280";
  if (S >= 0.85) return "#22c55e";
  if (S >= 0.70) return "#f59e0b";
  return "#ef4444";
}

export default function SurvivabilityGauge({ latest, loading }) {
  const S = latest?.S ?? null;
  const delta_S = latest?.delta_S ?? 0;
  const Q = latest?.Q ?? null;
  const tau = latest?.tau ?? null;

  const angle = S !== null ? -135 + S * 270 : -135;
  const color = gaugeColor(S);
  const trackPath = arcPath(-135, 135, R);
  const fillPath = S !== null ? arcPath(-135, angle, R) : null;

  const showPulse = delta_S > 0;

  return (
    <div className="bg-[#1F3864] rounded-xl p-5 border border-navy-700 h-full">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400 mb-4">
        Survivability Gauge
      </h2>

      <div className="flex flex-col items-center">
        {/* Circular SVG gauge */}
        <div className="relative">
          {showPulse && (
            <div
              className="absolute inset-0 rounded-full pulse-ring"
              style={{
                border: `3px solid ${color}`,
                opacity: 0.5,
              }}
            />
          )}
          <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
            {/* Track */}
            <path
              d={trackPath}
              fill="none"
              stroke="#1e3a5f"
              strokeWidth={STROKE}
              strokeLinecap="round"
            />
            {/* Fill */}
            {fillPath && (
              <path
                d={fillPath}
                fill="none"
                stroke={color}
                strokeWidth={STROKE}
                strokeLinecap="round"
              />
            )}
            {/* Center S value */}
            <text
              x={CX}
              y={CY - 8}
              textAnchor="middle"
              fill={color}
              fontSize="28"
              fontWeight="bold"
              fontFamily="monospace"
            >
              {loading && S === null ? "…" : S !== null ? S.toFixed(3) : "—"}
            </text>
            <text
              x={CX}
              y={CY + 14}
              textAnchor="middle"
              fill="#9ca3af"
              fontSize="10"
              fontFamily="sans-serif"
            >
              S SCORE
            </text>

            {/* Labels */}
            <text x={26} y={168} fill="#6b7280" fontSize="9" fontFamily="monospace">0.0</text>
            <text x={156} y={168} fill="#6b7280" fontSize="9" fontFamily="monospace">1.0</text>
          </svg>
        </div>

        {/* Metrics below gauge */}
        <div className="grid grid-cols-2 gap-3 w-full mt-4">
          <div className="bg-[#0f1c38] rounded-lg p-3 text-center">
            <div className="text-xs text-gray-400 uppercase tracking-widest mb-1">delta S</div>
            <div className={`text-lg font-mono font-bold ${delta_S > 0 ? "text-green-400" : delta_S < 0 ? "text-red-400" : "text-gray-400"}`}>
              {delta_S > 0 ? "▲" : delta_S < 0 ? "▼" : "—"}{" "}
              {Math.abs(delta_S).toFixed(4)}
            </div>
          </div>
          <div className="bg-[#0f1c38] rounded-lg p-3 text-center">
            <div className="text-xs text-gray-400 uppercase tracking-widest mb-1">Q</div>
            <div className="text-lg font-mono font-bold text-blue-300">
              {Q !== null ? Q.toFixed(3) : "—"}
            </div>
          </div>
          <div className="bg-[#0f1c38] rounded-lg p-3 text-center col-span-2">
            <div className="text-xs text-gray-400 uppercase tracking-widest mb-1">tau (τ)</div>
            <div className="text-lg font-mono font-bold text-purple-300">
              {tau !== null ? tau.toFixed(4) : "—"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
