export const pct = (v: number, d = 2) => `${(v * 100).toFixed(d)}%`;
export const ber3 = (v: number) => v.toFixed(3);
export const int = (v: number) => Math.round(v).toLocaleString("en-US");
export const bitsWrong = (ber: number, T = 64) => Math.round(ber * T);

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
