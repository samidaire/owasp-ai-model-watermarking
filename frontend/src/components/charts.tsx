import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
}

// ---------------------------------------------------------------------------------------- line chart
export interface Pt { x: number; y: number }

export function LineChart({
  points, xTicks, yTicks, fmtX, fmtY, xLabel, threshold, color, ariaLabel, valueName, height = 220,
}: {
  points: Pt[]; xTicks: number[]; yTicks: number[]; fmtX: (x: number) => string; fmtY: (y: number) => string;
  xLabel: string; threshold?: { y: number; label: string }; color: string; ariaLabel: string; valueName: string;
  height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 48, r: 18, t: 16, b: 40 };
  const pw = Math.max(10, width - m.l - m.r);
  const ph = height - m.t - m.b;
  const [x0, x1] = [Math.min(...xTicks), Math.max(...xTicks)];
  const yMax = Math.max(...yTicks);
  const sx = (x: number) => m.l + ((x - x0) / (x1 - x0)) * pw;
  const sy = (y: number) => m.t + (1 - y / yMax) * ph;
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(p.x)},${sy(p.y)}`).join(" ");
  const last = points[points.length - 1];

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const bx = e.currentTarget.getBoundingClientRect().left;
    const px = e.clientX - bx + m.l;
    let best = 0;
    points.forEach((p, i) => { if (Math.abs(sx(p.x) - px) < Math.abs(sx(points[best].x) - px)) best = i; });
    setHover(best);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") { setHover((h) => Math.min(points.length - 1, (h ?? -1) + 1)); e.stopPropagation(); e.preventDefault(); }
    if (e.key === "ArrowLeft") { setHover((h) => Math.max(0, (h ?? 1) - 1)); e.stopPropagation(); e.preventDefault(); }
  };
  const hp = hover !== null ? points[hover] : null;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg height={height} role="img" aria-label={ariaLabel}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + pw} y1={sy(t)} y2={sy(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth="1" />
              <text className="tick" x={m.l - 8} y={sy(t)} dy="0.32em" textAnchor="end">{fmtY(t)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={t} className="tick" x={sx(t)} y={m.t + ph + 18} textAnchor="middle">{fmtX(t)}</text>
          ))}
          <text className="axislabel" x={m.l + pw / 2} y={height - 4} textAnchor="middle">{xLabel}</text>
          {threshold && (
            <g>
              <line x1={m.l} x2={m.l + pw} y1={sy(threshold.y)} y2={sy(threshold.y)} stroke="var(--text-secondary)"
                strokeWidth="1" strokeDasharray="4 3" />
              <text className="annot" x={m.l + 6} y={sy(threshold.y) - 6} textAnchor="start">{threshold.label}</text>
            </g>
          )}
          {hp && <line x1={sx(hp.x)} x2={sx(hp.x)} y1={m.t} y2={m.t + ph} stroke="var(--axis)" strokeWidth="1" />}
          <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {points.map((p, i) => (
            <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={hover === i ? 5.5 : 4} fill={color} stroke="var(--surface-1)" strokeWidth="2" />
          ))}
          {last && (
            <text className="annot" x={sx(last.x)} y={sy(last.y) - 10} textAnchor="end">{fmtY(last.y)}</text>
          )}
          <rect x={m.l} y={m.t} width={pw} height={ph} fill="transparent" tabIndex={0} aria-label={`${ariaLabel}: use arrow keys to read values`}
            onPointerMove={onMove} onPointerLeave={() => setHover(null)} onFocus={() => setHover(0)} onBlur={() => setHover(null)}
            onKeyDown={onKey} style={{ outline: "none" }} />
        </svg>
      )}
      {hp && (
        <div className="tooltip" style={{ left: sx(hp.x), top: sy(hp.y) }}>
          <div className="tv">{fmtY(hp.y)}</div>
          <div className="tl"><span className="key" style={{ background: color }} />{valueName} at {fmtX(hp.x)}</div>
        </div>
      )}
      <details className="tableview">
        <summary>Table view</summary>
        <table className="data">
          <thead><tr><th>{xLabel}</th><th className="num">{valueName}</th></tr></thead>
          <tbody>{points.map((p, i) => <tr key={i}><td>{fmtX(p.x)}</td><td className="num">{fmtY(p.y)}</td></tr>)}</tbody>
        </table>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------------------- histogram
export interface Marker { x: number; label: string; tone: "good" | "neutral" }

export function Histogram({ bins, markers, ariaLabel, tip, xLabel, height = 260 }: {
  bins: { x: number; count: number }[]; markers: Marker[]; ariaLabel: string; xLabel: string;
  tip: (b: { x: number; count: number }) => { value: string; label: string }; height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 52, r: 18, t: 46, b: 40 };
  const pw = Math.max(10, width - m.l - m.r);
  const ph = height - m.t - m.b;
  const band = pw / bins.length;
  const bw = Math.max(2, Math.min(24, band - 2));
  const yTicks = niceTicks(Math.max(...bins.map((b) => b.count)));
  const yMax = yTicks[yTicks.length - 1];
  const sx = (x: number) => m.l + x * (pw - band) + band / 2;   // bin centres for x in [0, 1]
  const sy = (y: number) => m.t + (1 - y / yMax) * ph;
  const base = sy(0);
  const barPath = (cx: number, top: number) => {
    const r = Math.min(4, bw / 2, base - top);
    const x = cx - bw / 2;
    return `M${x},${base} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${base} Z`;
  };
  const hb = hover !== null ? bins[hover] : null;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg height={height} role="img" aria-label={ariaLabel}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + pw} y1={sy(t)} y2={sy(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth="1" />
              <text className="tick" x={m.l - 8} y={sy(t)} dy="0.32em" textAnchor="end">{t.toLocaleString("en-US")}</text>
            </g>
          ))}
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <text key={t} className="tick" x={sx(t)} y={base + 18} textAnchor="middle">{t.toFixed(2)}</text>
          ))}
          <text className="axislabel" x={m.l + pw / 2} y={height - 4} textAnchor="middle">{xLabel}</text>
          {bins.map((b, i) => b.count > 0 && (
            <path key={i} d={barPath(sx(b.x), sy(b.count))} fill="var(--series-1)" opacity={hover === null || hover === i ? 1 : 0.55} />
          ))}
          {markers.map((mk, idx) => (
            <g key={mk.label}>
              <line x1={sx(mk.x)} x2={sx(mk.x)} y1={m.t - 18 - idx * 14} y2={base}
                stroke={mk.tone === "good" ? "var(--good)" : "var(--text-secondary)"}
                strokeWidth={mk.tone === "good" ? 3 : 1} strokeDasharray={mk.tone === "good" ? undefined : "4 3"} />
              <text className="annot" x={sx(mk.x) + 6} y={m.t - 8 - idx * 14} textAnchor="start">{mk.label}</text>
            </g>
          ))}
          {bins.map((b, i) => (
            <rect key={`h${i}`} x={sx(b.x) - band / 2} y={m.t} width={band} height={ph} fill="transparent"
              onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)} />
          ))}
        </svg>
      )}
      {hb && (
        <div className="tooltip" style={{ left: sx(hb.x), top: sy(hb.count) }}>
          <div className="tv">{tip(hb).value}</div>
          <div className="tl">{tip(hb).label}</div>
        </div>
      )}
      <details className="tableview">
        <summary>Table view</summary>
        <table className="data">
          <thead><tr><th>{xLabel}</th><th className="num">count</th></tr></thead>
          <tbody>{bins.filter((b) => b.count > 0).map((b) => (
            <tr key={b.x}><td>{b.x.toFixed(3)}</td><td className="num">{b.count.toLocaleString("en-US")}</td></tr>
          ))}</tbody>
        </table>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------------------- bit grid
/** 64 cells: filled = 1, light = 0; a ring and × mark bits that differ from `reference`. */
export function BitGrid({ bits, reference, label, columns }: {
  bits: number[]; reference?: number[]; label: string; columns?: number;
}) {
  const wrong = reference ? bits.filter((b, i) => b !== reference[i]).length : 0;
  return (
    <div className="bitgrid" role="img" aria-label={`${label}: ${bits.length} bits${reference ? `, ${wrong} differ` : ""}`}
      style={columns ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}>
      {bits.map((b, i) => {
        const bad = reference ? b !== reference[i] : false;
        return (
          <span key={i} className={`bit ${b ? "one" : "zero"}${bad ? " bad" : ""}`}
            title={`bit ${i}: ${b}${reference ? ` (expected ${reference[i]})` : ""}`} />
        );
      })}
    </div>
  );
}

export function BitLegend() {
  return (
    <div className="legendrow">
      <span><span className="sw" style={{ background: "var(--series-1)" }} />bit = 1</span>
      <span><span className="sw" style={{ background: "var(--bit-zero)" }} />bit = 0</span>
      <span><span className="sw" style={{ background: "var(--bit-zero)", boxShadow: "0 0 0 2px var(--critical)" }} />× differs from the expected signature</span>
    </div>
  );
}
