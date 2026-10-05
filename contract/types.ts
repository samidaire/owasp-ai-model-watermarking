/**
 * API contract for the watermark demo backend (demo/server.py), api_version 1.
 * Single source of truth: the reference UI imports these types directly (frontend/src/api.ts re-exports them),
 * and contract/fixtures/*.json are real responses captured from the server. See UI_INTEGRATION.md.
 *
 * Newer servers add POST /api/jobs/{id}/cancel (body {}): 202 JobInfo if the job was running,
 * 409 ErrorBody {error: "job not running", job} otherwise, 404 for an unknown id. Older servers answer 404 for
 * that path, so a UI must treat a 404/405 there as "cancel not supported".
 */

export type Bits = number[]; // 64 entries, each 0 or 1

/** GET /api/steps  ·  POST /api/run {step} */
export type ServerStep = "evaluate" | "retrain" | "attacks" | "forgery" | "committed" | "zk" | "zk_hashed" | "protocol_v2" | "all"
  // the Verify page re-checks demo F's saved proof live, honestly or with one misuse (writes nothing)
  | "verify_honest" | "verify_replay" | "verify_model" | "verify_tamper" | "verify_registry"
  // "Model under test": watermark readout, accuracy and a proof for one model (POST body needs `model`)
  | "model_test";

export interface StepInfo {
  id: ServerStep;
  /** Which demo panel the step belongs to; "*" = all panels. */
  panel: "A" | "B" | "C" | "D" | "E" | "F" | "*";
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
  /** Wall-clock limit in seconds; the server stops the job after it (JobInfo.timed_out, code -3). Newer servers only. */
  timeout?: number;
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

/**
 * Job status. Returned by POST /api/run (202) and POST /api/jobs/{id}/cancel (202), embedded in /api/state,
 * and sent in the SSE "done" event.
 */
export interface JobInfo {
  id: string;
  step: ServerStep;
  running: boolean;
  /** null while running; 0 = success; -2 = cancelled; -3 = timed out; anything else = failure. */
  code: number | null;
  /** Unix seconds. */
  started: number;
  ended: number | null;
  /** Number of output lines so far. */
  lines: number;
  /** The job was stopped by POST /api/jobs/{id}/cancel (code -2). Always present on servers with cancel; treat missing as false. */
  cancelled?: boolean;
  /** The job was stopped after its step's `timeout` (code -3). Always present on servers with cancel; treat missing as false. */
  timed_out?: boolean;
  /** The model id a `model_test` job tests (null for other steps; missing on older servers). */
  model?: string | null;
}

/**
 * Error body of every 4xx response. `job` is set on the 409 of POST /api/run ("another demo is running":
 * the job that is running) and of POST /api/jobs/{id}/cancel ("job not running": the finished job).
 */
export interface ErrorBody { error: string; job?: JobInfo }

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
  /** EZKL's public parameter hashes: [[ "0x…" ]] for hashed runs (same value as param_commitment_poseidon), null for private runs. */
  public_param_hashes?: string[][] | null;
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
/** Demo F · results/protocol_v2.json (step: protocol_v2): sigil SDK + Circom/SnarkJS, docs/protocol.md */
export interface ProtocolV2Verdict { accepted: boolean; reasons: string[] }
export interface ProtocolV2Result {
  protocol: 2;
  config: { protocol: 2; T: number; M: number; layer: string; scale_bits: number; w_bits: number; max_err: number; norm: string; prg_bits: number };
  circuit: string;
  owner_public_key: string;          // Ed25519, hex
  commitment: string;                // Poseidon commitment, decimal field element
  registration_sha256: string;
  registered_at: string;             // registry receipt time (UTC)
  registry_public_key: string;
  accuracy: { watermarked_v2: number };
  owner_detection: { errors: number; ber: number; max_err: number; accepted: boolean };
  owner_proof: {
    accepted: boolean;
    checks: Record<string, boolean>; // registration_valid, receipt_valid, ..., public_w_hash, public_nonce, snark_valid
    timing: { witness_s: number; prove_s: number };
    public_signals: Record<"pk_hash" | "config_hash" | "commitment" | "w_hash" | "nonce", string>;
    proof_json_bytes: number;
  };
  thief: { own_key: string; owner_commitment: string; own_key_errors: number };
  misuse: Record<string, ProtocolV2Verdict>;   // replay, different model, tampered proof, untrusted registry
  robustness: { attack: string; accuracy: number; errors: number; proof_accepted: boolean; reason: string | null }[];
  overwrite_dispute: { parties: { party: "owner" | "thief"; registered_at: string; errors: number; proof_accepted: boolean }[];
                       winner: "owner" | "thief" | null };
}

/** GET /api/models: what the "Model under test" menu offers (demo/model_catalogue.py). */
export interface ModelInfo {
  /** Built-in id ("watermarked_v2", "prune65", "clean", …) or "file:<name>" for a file in demo/models/. */
  id: string;
  group: string;
  label: string;
  /** Path relative to demo/, or null for a stolen copy made live from the owner's model. */
  file: string | null;
  derived: boolean;
  note: string;
}
export interface ModelsResponse { api_version: number; models: ModelInfo[] }

/** results/model_tests/<model>.json: one run of 10_test_model.py. */
export interface ModelTestResult {
  model: string;
  label: string;
  group: string;
  derived: boolean;
  file: string | null;
  sha256: string;
  /** On the 10,000 MNIST test images; null when the file isn't the demo's network. */
  accuracy: number | null;
  /** False when no conv2 layer of M = 288 values could be read (then `error` says why). */
  readable: boolean;
  error: string | null;
  /** Protocol v2 owner (Ed25519): bits wrong out of 64, accepted at <= max_err. */
  v2: { errors: number; ber: number; max_err: number; accepted: boolean } | null;
  /** Protocol v1 owner (owner:yash): bit error rate, accepted at <= 0.125. */
  v1: { ber: number; accepted: boolean } | null;
  proof: {
    made: boolean;
    accepted: boolean;
    checks: Record<string, boolean>;
    reasons: string[];
    timing: { witness_s: number; prove_s: number } | null;
    proof_bytes: number | null;
    nonce: string | null;
  } | null;
  /** proven: proof made and every check passed; no_proof: the mark isn't there; rejected: a check failed. */
  verdict: "proven" | "no_proof" | "rejected" | "unreadable";
  tested_at: string;
}

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
    /** Demo F; absent on servers older than protocol v2. */
    protocol_v2?: ProtocolV2Result | null;
    /** "Model under test" results keyed by model id; absent on older servers. */
    model_tests?: Record<string, ModelTestResult>;
  };
  job: JobInfo | null;
}
