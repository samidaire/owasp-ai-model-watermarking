// Stroke icons from the design canvas (24 px grid, currentColor). Decorative: always aria-hidden.
const PATHS: Record<string, string[]> = {
  overview: ["M3 3h7.5v7.5H3z", "M13.5 3H21v7.5h-7.5z", "M3 13.5h7.5V21H3z", "M13.5 13.5H21V21h-7.5z"],
  models: ["M12 3l8 4.5v9L12 21l-8-4.5v-9z", "M4 7.5l8 4.5 8-4.5M12 12v9"],
  embed: ["M3 8c2-2.6 4-2.6 6 0s4 2.6 6 0 4-2.6 6 0", "M3 16c2-2.6 4-2.6 6 0s4 2.6 6 0 4-2.6 6 0"],
  verify: ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z", "M8.5 12l2.5 2.5 4.5-5"],
  bolt: ["M13 2L4 14h7l-1 8 9-12h-7z"],
  log: ["M9 6h12M9 12h12M9 18h12", "M4 6h.01M4 12h.01M4 18h.01"],
  key: ["M11 12l9-9M17 6l3 3M15 8l2 2", "M12 15a4 4 0 1 1-8 0 4 4 0 0 1 8 0z"],
  arrow: ["M5 12h14M13 6l6 6-6 6"],
  check: ["M5 12.5l4.5 4.5L19 7"],
  x: ["M6 6l12 12M18 6L6 18"],
  lock: ["M4 11h16v10H4z", "M8 11V7a4 4 0 0 1 8 0v4"],
  file: ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5"],
  code: ["M8 8l-4 4 4 4M16 8l4 4-4 4"],
  scissors: ["M8.6 7.6L20 18M8.6 16.4L20 6", "M9 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0z", "M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0z"],
  stairs: ["M3 20h4v-4h4v-4h4V8h4V4"],
  sliders: ["M4 7h16M4 17h16", "M11.5 7a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z", "M17.5 17a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z"],
  copy: ["M8 8h12v12H8z", "M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"],
  eyeoff: ["M3 3l18 18", "M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a17 17 0 0 1-2.8 3.3M6.6 6.6C4.2 8.2 3 12 3 12s4 6 9 6a9.4 9.4 0 0 0 4.4-1.1"],
  play: ["M7 5l12 7-12 7z"],
  refresh: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
  chain: ["M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1", "M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"],
  flask: ["M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"],
};

export function Icon({ name, size = 20, className }: { name: keyof typeof PATHS | string; size?: number; className?: string }) {
  return (
    <svg className={`ico${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      {(PATHS[name] ?? []).map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}

export function Logo({ size = 38 }: { size?: number }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 38 38" aria-hidden>
      <rect x="1" y="1" width="36" height="36" rx="11" fill="var(--espresso)" />
      <path d="M8 15c2.6-3.2 5.2-3.2 7.6 0s5 3.2 7.6 0 5-3.2 6.8 0" fill="none" stroke="var(--caramel)" strokeWidth="2.8" strokeLinecap="round" />
      <path d="M8 23c2.6-3.2 5.2-3.2 7.6 0s5 3.2 7.6 0 5-3.2 6.8 0" fill="none" stroke="var(--paper)" strokeWidth="2.8" strokeLinecap="round" />
    </svg>
  );
}
