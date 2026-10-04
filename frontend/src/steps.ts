// The step catalogue (labels, durations, confirmation texts) comes from GET /api/steps at load.
// FALLBACK_STEPS is used only when that request fails; it mirrors contract/fixtures/steps.json, except that the
// confirmation texts keep the UI's earlier, longer wording.
import type { ServerStep, StepInfo, StepsResponse } from "./api";

export type StepCatalogue = Record<ServerStep, StepInfo>;

export const FALLBACK_STEPS: StepCatalogue = {
  evaluate: {
    id: "evaluate", panel: "A", label: "Re-verify live", seconds: 5, confirm: null, writes: ["train.json"],
    description: "Re-checks the saved owner models. Does not retrain.",
  },
  retrain: {
    id: "retrain", panel: "A", label: "Retrain with a new seed", seconds: 35, writes: ["public_commitment.json", "train.json"],
    description: "Starts over with a new owner key.",
    confirm: "Retraining creates a NEW owner seed and key.\n\n" +
      "Every other result (B–E) becomes stale, and E3's precomputed Poseidon proofs must be re-run " +
      "(about 3 minutes and ~10 GB of temporary disk).\n\nContinue?",
  },
  attacks: {
    id: "attacks", panel: "B", label: "Run attacks live", seconds: 10, confirm: null,
    writes: ["attacks.json", "attacks.csv", "attacks.png"], description: "Removal-attack suite.",
  },
  forgery: {
    id: "forgery", panel: "C", label: "Run forgery live", seconds: 3, confirm: null, writes: ["forgery.json"],
    description: "Counterfeit-key forgery and ZKROWNN relation check.",
  },
  committed: {
    id: "committed", panel: "D", label: "Run live", seconds: 3, confirm: null, options: { tries: [20000, 100000] },
    writes: ["committed_seed.json", "forgery_search.png"], description: "Committed-seed defence (D0-D2).",
  },
  zk: {
    id: "zk", panel: "E", label: "Run E1 + E2 live", seconds: 10, confirm: null,
    writes: ["ezkl_private_owner/summary.json", "ezkl_private_thief/summary.json", "vk_crosscheck.json"],
    description: "EZKL proofs without commitment (owner, thief) and the VK cross-check.",
  },
  zk_hashed: {
    id: "zk_hashed", panel: "E", label: "Re-run E3", seconds: 200,
    writes: ["ezkl_hashed_owner/summary.json", "ezkl_hashed_thief/summary.json"],
    description: "EZKL proofs with a Poseidon commitment to the private parameters.",
    confirm: "Re-run the Poseidon-committed proofs?\n\n" +
      "Takes about 3 minutes and writes a ~10 GB temporary proving key per proof (deleted afterwards). " +
      "The precomputed results are shown otherwise.\n\nContinue?",
  },
  protocol_v2: {
    id: "protocol_v2", panel: "F", label: "Run demo F live", seconds: 80, confirm: null,
    writes: ["protocol_v2.json", "protocol_v2/proof.json", "protocol_v2/public.json"],
    description: "Protocol v2 end to end: registration, Groth16 proof, verifier checks, thief, misuse, attacks and the overwrite dispute.",
  },
  all: {
    id: "all", panel: "*", label: "Run all live", seconds: 30, confirm: null, writes: [],
    description: "evaluate, attacks, forgery, committed, zk (E3 stays precomputed).",
  },
};

/** The server's catalogue, keyed by step id. A step the server doesn't list keeps its fallback entry. */
export function toCatalogue(r: StepsResponse): StepCatalogue {
  const out = { ...FALLBACK_STEPS };
  for (const st of r.steps ?? []) if (st.id in out) out[st.id] = st;
  return out;
}

/** What a running step is doing, for "Running forgery…" button texts (their accessible names). */
export const RUNNING_NAME: Record<ServerStep, string> = {
  evaluate: "re-verification", retrain: "retraining", attacks: "attacks", forgery: "forgery",
  committed: "seed search", zk: "E1 + E2 proofs", zk_hashed: "E3 proofs", protocol_v2: "demo F", all: "all demos",
};

/** "~10 s", "~3 min". */
export function about(seconds: number): string {
  return seconds < 90 ? `~${Math.max(1, Math.round(seconds))} s` : `~${Math.round(seconds / 60)} min`;
}
