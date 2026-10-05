// A select styled like the rest of the app (the browser's own option list can't be). ARIA listbox pattern:
// the button opens the list; ↑ ↓ Home End move, Enter or Space picks, Esc closes, typing jumps to a match.
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export interface DropOption {
  value: string;
  label: string;
  /** Options with the same group are listed under that heading, in order of first appearance. */
  group?: string;
  /** Shown at the right of the option (e.g. a small verdict chip). */
  badge?: ReactNode;
}

export function Dropdown({ value, options, onChange, disabled, labelledBy, minWidth = 300 }: {
  value: string; options: DropOption[]; onChange: (value: string) => void; disabled?: boolean;
  /** id of the visible label, so the button reads "<label> <value>". */
  labelledBy?: string; minWidth?: number;
}) {
  const id = useId().replace(/:/g, "");
  const [open, setOpen] = useState(false);
  const selected = Math.max(0, options.findIndex((o) => o.value === value));
  const [active, setActive] = useState(selected);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const typed = useRef({ text: "", at: 0 });

  // Close on a click outside, and when the control gets disabled (a run started).
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  useEffect(() => { if (open) list.current?.focus(); }, [open]);
  useEffect(() => {
    if (open) document.getElementById(`${id}-o${active}`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, id]);

  const show = () => { setActive(selected); setOpen(true); };
  const pick = (i: number) => {
    onChange(options[i].value);
    setOpen(false);
    button.current?.focus();
  };
  const jump = (key: string) => {
    const now = Date.now();
    typed.current = { text: (now - typed.current.at < 700 ? typed.current.text : "") + key.toLowerCase(), at: now };
    const q = typed.current.text;
    const order = [...options.keys()].map((k) => (active + 1 + k) % options.length);
    const hit = order.find((i) => options[i].label.toLowerCase().includes(q));
    if (hit !== undefined) setActive(hit);
  };
  const onButtonKey = (e: KeyboardEvent) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); show(); }
  };
  const onListKey = (e: KeyboardEvent) => {
    const last = options.length - 1;
    const keys: Record<string, () => void> = {
      ArrowDown: () => setActive((a) => Math.min(last, a + 1)), ArrowUp: () => setActive((a) => Math.max(0, a - 1)),
      Home: () => setActive(0), End: () => setActive(last), PageDown: () => setActive((a) => Math.min(last, a + 5)),
      PageUp: () => setActive((a) => Math.max(0, a - 5)), Enter: () => pick(active), " ": () => pick(active),
      Escape: () => { setOpen(false); button.current?.focus(); },
    };
    if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
    else if (e.key === "Tab") setOpen(false);
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) jump(e.key);
  };

  const groups: [string | undefined, number[]][] = [];
  options.forEach((o, i) => {
    const g = groups.find(([name]) => name === o.group);
    if (g) g[1].push(i); else groups.push([o.group, [i]]);
  });
  const cur = options[selected];

  return (
    <div className="dd" ref={root} style={{ minWidth: `min(${minWidth}px, 100%)` }}>
      <button type="button" ref={button} className="dd-btn" disabled={disabled} aria-haspopup="listbox" aria-expanded={open}
        aria-controls={`${id}-list`} aria-labelledby={labelledBy ? `${labelledBy} ${id}-v` : `${id}-v`}
        onClick={() => (open ? setOpen(false) : show())} onKeyDown={onButtonKey}>
        <span id={`${id}-v`} className="dd-value">{cur?.label ?? "—"}</span>
        {cur?.badge}
        <svg className="chev" width="18" height="18" viewBox="0 0 24 24" aria-hidden><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div id={`${id}-list`} ref={list} className="dd-list" role="listbox" tabIndex={-1} aria-labelledby={labelledBy}
          aria-activedescendant={`${id}-o${active}`} onKeyDown={onListKey}>
          {groups.map(([g, idx], gi) => (
            <div key={g ?? gi} role={g ? "group" : "presentation"} aria-labelledby={g ? `${id}-g${gi}` : undefined}>
              {g && <div id={`${id}-g${gi}`} className="dd-group">{g}</div>}
              {idx.map((i) => {
                const o = options[i];
                return (
                  <div key={o.value} id={`${id}-o${i}`} role="option" aria-selected={i === selected}
                    className={`dd-opt${i === active ? " active" : ""}`} onMouseEnter={() => setActive(i)}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => pick(i)}>
                    <span className="dd-check" aria-hidden>{i === selected && (
                      <svg width="16" height="16" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    )}</span>
                    <span className="dd-label">{o.label}</span>
                    {o.badge}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** A small verdict mark for an option row: ✓ good, ✕ bad, ! warn. */
export function MiniBadge({ tone, children }: { tone: "good" | "bad" | "warn"; children: ReactNode }) {
  return <span className={`dd-mini ${tone}`}>{tone === "good" ? "✓" : tone === "bad" ? "✕" : "!"} {children}</span>;
}
