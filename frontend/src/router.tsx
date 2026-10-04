// A tiny client-side router: history API, no dependency. The demo server returns index.html for unknown
// paths (UI_INTEGRATION.md §3.2), so deep links like /app/verify work on reload.
import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

const EVENT = "sigil:navigate";

export function navigate(to: string) {
  if (to === window.location.pathname + window.location.hash) return;
  window.history.pushState({}, "", to);
  window.dispatchEvent(new Event(EVENT));
  if (!to.includes("#")) window.scrollTo({ top: 0, behavior: "instant" });   // a new page starts at the top, no smooth glide
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const on = () => setPath(window.location.pathname);
    window.addEventListener("popstate", on);
    window.addEventListener(EVENT, on);
    return () => { window.removeEventListener("popstate", on); window.removeEventListener(EVENT, on); };
  }, []);
  return path;
}

/** An <a> that navigates inside the app (modifier-clicks still open a new tab). */
export function Link({ to, onClick, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a href={to} {...rest} onClick={(e: MouseEvent<HTMLAnchorElement>) => {
      onClick?.(e);
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (to.startsWith("#")) return;           // in-page anchor: let the browser scroll
      e.preventDefault();
      navigate(to);
    }} />
  );
}
