export const pct = (v: number, d = 2) => `${(v * 100).toFixed(d)}%`;
export const ber3 = (v: number) => v.toFixed(3);
export const int = (v: number) => Math.round(v).toLocaleString("en-US");
export const bitsWrong = (ber: number, T = 64) => Math.round(ber * T);

/** A quantity of any magnitude with sensible precision: 257,463 · 71.5 · 0.42. No unit conversion. */
export function amount(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 100) return int(v);
  if (a >= 1) return v.toFixed(1);
  return a === 0 ? "0" : v.toPrecision(2);
}

export function bytes(n: number): string {
  if (n >= 2 ** 30) return `${(n / 2 ** 30).toFixed(1)} GiB`;
  if (n >= 2 ** 20) return `${(n / 2 ** 20).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

export function secs(s: number): string {
  if (s < 0.1) return `${Math.round(s * 1000)} ms`;
  if (s < 10) return `${s.toFixed(2)} s`;
  return `${s.toFixed(1)} s`;
}

export const short = (h: string | null | undefined, n = 12) => (h ? `${h.slice(0, n)}…` : "—");

export function sci(v: number): string {
  const [m, e] = v.toExponential(2).split("e");
  return `${m} × 10^${Number(e)}`;
}

export function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "medium" });
}
