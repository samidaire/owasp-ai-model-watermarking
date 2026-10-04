/**
 * API contract for the watermark demo backend (demo/server.py), api_version 1.
 * Single source of truth: the reference UI (frontend/src/api.ts) imports these types, and
 * contract/fixtures/*.json are real responses captured from the server. See UI_INTEGRATION.md.
 */

export type Bits = number[]; // 64 entries, each 0 or 1

/** GET /api/steps  ·  POST /api/run {step} */
export type ServerStep = "evaluate" | "retrain" | "attacks" | "forgery" | "committed" | "zk" | "zk_hashed" | "all";

export interface StepInfo {
  id: ServerStep;
  /** Which demo panel the step belongs to; "*" = all panels. */
  panel: "A" | "B" | "C" | "D" | "E" | "*";
  label: string;
  /** Typical wall-clock duration on the RTX 5080 machine. */
  seconds: number;
  /** Non-null = show this text and ask the user to confirm before POSTing (retrain, zk_hashed). */
  confirm: string | null;
  /** Result files the step rewrites (relative to demo/results/). */
  writes: string[];
  description: string;
  /** Only "committed" has options: allowed values for the `tries` field of POST /api/run. */
  options?: { tries: number[] };
}

export interface StepsResponse { api_version: number; mode: "live" | "simulate"; steps: StepInfo[] }

/** GPU probe for the header badge. status "error" = the server's Python has no torch (fine for UI work). */
export interface Env {
  status: "probing" | "ok" | "error";
  python?: string;
  torch?: string;
  cuda?: string | null;
  gpu?: string | null;
  sm?: string;
  vram_gib?: number;
  error?: string;
}

/** Job status. Returned by POST /api/run (202), embedded in /api/state, and sent in the SSE "done" event. */
export interface JobInfo {
  id: string;
  step: ServerStep;
  running: boolean;
  /** null while running; 0 = success; anything else = failure. */
  code: number | null;
  /** Unix seconds. */
  started: number;
  ended: number | null;
  /** Number of output lines so far. */
  lines: number;
}

/** GET /api/jobs/{id}: JobInfo plus every output line so far. */
export interface JobDetail extends JobInfo { output: string[] }

// ---------------------------------------------------------------------------------- results (demo/results/*.json)

export interface ModelEval { accuracy: number; owner_ber: number; extracted_bits: Bits }

/** Demo A · results/train.json (steps: evaluate, retrain) */
export interface TrainResult {
  commitment: string;
  timestamp_utc: string;
  owner_id: string;
  scheme: string;
  device: string;
  epochs: number | null;
  /** Indicative BER acceptance threshold (8/64). Not a calibrated false-positive rate. */
  threshold: number;
  key_shape: number[];
  signature_bits: Bits;
  models: { clean: ModelEval; watermarked: ModelEval };
  nulls: { name: string; accuracy: number; owner_ber: number }[];
}

/** Demo B · results/attacks.json (step: attacks) */
export interface AttackRow {
  attack: string;
  /** baseline | prune | quantise | finetune | overwrite | permute */
  family: string;
  accuracy: number;
  owner_ber: number;
  survives: boolean;
}
export interface AttacksResult { commitment: string; threshold: number; rows: AttackRow[] }

export interface KeyStat {
  key: string; entry_mean: number; entry_std: number; ks_d: number; min_margin: number; median_margin: number;
}

/** Demo C · results/forgery.json (step: forgery) */
export interface ForgeryResult {
  commitment: string;
  threshold: number;
  owner: { ber: number; signature_bits: Bits; extracted_bits: Bits };
  thief: { target_text: string; target_bits: Bits; extracted_bits: Bits; ber: number; message: string };
  large_margin_ber: number;
  key_stats: KeyStat[];
  ks_critical: number;
  never_watermarked: { model: string; thief_ber: number }[];
  zkrownn: { xkey_shape: number[]; a_shape: number[]; rows: { model: string; satisfied: boolean; ber: number }[] };
}

/** Demo D · results/committed_seed.json (step: committed) */
export interface CommittedResult {
  commitment: string;
  threshold: number;
  signature_bits_T: number;
  d0: { commitment_matches: boolean; owner_ber: number; verified: boolean; timestamp_utc: string };
  d1: { wins: number; trials: number };
  d2: {
    tries: number; seconds: number; seeds_per_s: number; min_ber: number; mean_ber: number; accepted: number;
    p_per_try: number; log2_work: number; seeds_for_half: number; single_core_hours: number; log2_work_T256: number;
    /** 65 bins, one per possible BER k/64. */
    histogram: { ber: number; count: number }[];
  };
  nulls: { model: string; owner_ber: number }[];
}

/** Demo E · results/ezkl_{private|hashed}_{owner|thief}/summary.json (steps: zk, zk_hashed) */
export interface EzklSummary {
  params_visibility: "private" | "hashed";
  prover: "owner" | "thief";
  verified: boolean;
  logrows: number;
  srs: string;
  srs_file?: string;
  plain_score: number;
  /** [[ "64" ]]: the public score (number of agreeing bits), as a string. */
  public_outputs: string[][] | null;
  /** hashed only: [[ "0x…" ]], the Poseidon hash of the private key + signature. */
  param_commitment_poseidon?: string[][];
  proof_bytes: number;
  vk_bytes: number;
  pk_bytes: number;
  seconds: Record<string, number>;
  peak_rss_bytes: number;
  commitment?: string;
  min_margin?: number;
}

/** Demo E2 · results/vk_crosscheck.json (step: zk) */
export interface VkCross {
  commitment: string; owner_vk: string; thief_vk: string; identical: boolean; thief_verified_under_owner_vk: boolean;
}

/** GET /api/state: everything a UI needs to render every panel. Any result may be null if never run. */
export interface DemoState {
  api_version: number;
  /** "simulate" = runs replay recorded logs (server started with --simulate). Show this prominently. */
  mode: "live" | "simulate";
  env: Env;
  /** The owner's current SHA-256 seed commitment. A result whose .commitment differs is STALE. */
  commitment: string | null;
  results: {
    train: TrainResult | null;
    attacks: AttacksResult | null;
    forgery: ForgeryResult | null;
    committed_seed: CommittedResult | null;
    vk_crosscheck: VkCross | null;
    ezkl: Record<"private_owner" | "private_thief" | "hashed_owner" | "hashed_thief", EzklSummary | null>;
  };
  job: JobInfo | null;
}
