// What the pages show. Every page starts empty ("nothing has happened yet") and fills in when a run of that demo
// finishes; Clear empties them again for a new test. This is a view only: the saved results in demo/results/ are
// never deleted, and "Show saved results" brings them all back at once (e.g. when nothing can run live).
import type { DemoState, ServerStep } from "./api";

export type ResultKey = "train" | "attacks" | "forgery" | "committed_seed" | "zk" | "zk_hashed" | "protocol_v2";
export const ALL_RESULTS: ResultKey[] = ["train", "attacks", "forgery", "committed_seed", "zk", "zk_hashed", "protocol_v2"];

/** The results a successful run of each step brings onto the pages. E3 (zk_hashed) is precomputed (it needs
 *  ~32 GB of RAM), so it appears together with E1 + E2. The verify_* steps re-check demo F's proof and add nothing. */
export const REVEALS: Partial<Record<ServerStep, ResultKey[]>> = {
  evaluate: ["train"], retrain: ["train"], attacks: ["attacks"], forgery: ["forgery"], committed: ["committed_seed"],
  zk: ["zk", "zk_hashed"], zk_hashed: ["zk_hashed"], protocol_v2: ["protocol_v2"],
  all: ["train", "attacks", "forgery", "committed_seed", "zk", "zk_hashed"],
};

const KEY = "sigil.shown";
const CLEARED = "sigil.clearedAt";

/** When Clear was last pressed (Unix seconds): runs that started earlier no longer show in the audit log. */
export function loadClearedAt(): number {
  try { return Number(localStorage.getItem(CLEARED)) || 0; } catch { return 0; }
}
export function saveClearedAt(t: number) {
  try { localStorage.setItem(CLEARED, String(t)); } catch { /* private window: not kept */ }
}

export function loadShown(): Set<ResultKey> {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return new Set(Array.isArray(v) ? v.filter((k): k is ResultKey => ALL_RESULTS.includes(k)) : []);
  } catch {
    return new Set();
  }
}

export function saveShown(shown: Set<ResultKey>) {
  try { localStorage.setItem(KEY, JSON.stringify([...shown])); } catch { /* private window: not kept */ }
}

/** The server's state with every result that hasn't been run (or shown) in this session blanked out. */
export function applyView(s: DemoState, shown: Set<ResultKey>, clearedAt: number): DemoState {
  const r = s.results;
  const pick = <T,>(k: ResultKey, v: T): T | null => (shown.has(k) ? v : null);
  return {
    ...s,
    job: s.job && s.job.started >= clearedAt ? s.job : null,
    results: {
      train: pick("train", r.train),
      attacks: pick("attacks", r.attacks),
      forgery: pick("forgery", r.forgery),
      committed_seed: pick("committed_seed", r.committed_seed),
      vk_crosscheck: pick("zk", r.vk_crosscheck),
      ezkl: {
        private_owner: pick("zk", r.ezkl.private_owner), private_thief: pick("zk", r.ezkl.private_thief),
        hashed_owner: pick("zk_hashed", r.ezkl.hashed_owner), hashed_thief: pick("zk_hashed", r.ezkl.hashed_thief),
      },
      protocol_v2: pick("protocol_v2", r.protocol_v2 ?? null),
    },
  };
}
