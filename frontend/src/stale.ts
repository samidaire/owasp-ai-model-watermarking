// Staleness (UI_INTEGRATION.md §7), decided in ONE place for both the sidebar and the panels.
import type { DemoState } from "./api";

export type PanelKey = "A" | "B" | "C" | "D" | "E";
export type Freshness = "fresh" | "stale" | "unknown";
export type PanelStatus = Freshness | "missing";

/**
 * One result: stale when its `commitment` exists and differs from the owner's current one. A result without a
 * commitment field counts as fresh (§7). Without a current commitment (state.commitment null) nothing can be
 * compared, so freshness is "unknown": no stale badge, but not "up to date" either.
 */
export function freshness(result: string | null | undefined, current: string | null | undefined): Freshness {
  if (!current) return "unknown";
  return result && result !== current ? "stale" : "fresh";
}

/** The commitments of every result a panel shows. A panel is stale when any of them is. */
function commitmentsOf(k: PanelKey, s: DemoState): (string | null | undefined)[] {
  const r = s.results;
  switch (k) {
    case "A": return [r.train?.commitment];
    case "B": return [r.attacks?.commitment];
    case "C": return [r.forgery?.commitment];
    case "D": return [r.committed_seed?.commitment];
    case "E": return [
      r.ezkl?.private_owner?.commitment, r.ezkl?.private_thief?.commitment,
      r.ezkl?.hashed_owner?.commitment, r.ezkl?.hashed_thief?.commitment,
      r.vk_crosscheck?.commitment,
    ];
  }
}

/** Whether a panel has results to show (the same test the panel uses for its empty state). */
export function panelPresent(k: PanelKey, s: DemoState): boolean {
  const r = s.results;
  switch (k) {
    case "A": return Boolean(r.train);
    case "B": return Boolean(r.attacks);
    case "C": return Boolean(r.forgery);
    case "D": return Boolean(r.committed_seed);
    case "E": return Boolean(r.ezkl?.private_owner && r.ezkl?.private_thief);
  }
}

/** Freshness of everything a panel shows. */
export function panelFreshness(k: PanelKey, s: DemoState): Freshness {
  const all = commitmentsOf(k, s).map((c) => freshness(c, s.commitment));
  if (all.includes("stale")) return "stale";
  return s.commitment ? "fresh" : "unknown";
}

/** The panel's "Stale: re-run" badge. */
export const panelStale = (k: PanelKey, s: DemoState) => panelFreshness(k, s) === "stale";

/** The sidebar marker. */
export function panelStatus(k: PanelKey, s: DemoState | null): PanelStatus {
  if (!s || !panelPresent(k, s)) return "missing";
  return panelFreshness(k, s);
}
