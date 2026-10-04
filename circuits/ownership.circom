pragma circom 2.1.9;

// Zero-knowledge proof of watermark ownership, protocol v2 (docs/protocol.md).
//
// Statement (all hashes are Poseidon over BN254, identical to sdk/src/sigil/protocol.py):
//   "I know a seed such that commitment = H(COMMIT, seed, pk_hash, config_hash), and the watermark
//    key X and signature b derived in-circuit from (seed, pk_hash) agree with the suspect model's
//    quantised Uchida vector w on at least T - MAX_ERR bits, where H(w) = w_hash and config_hash
//    describes exactly this circuit's parameters."
// Public:  pk_hash, config_hash, commitment, w_hash, nonce.
// Private: seed, w, scale_bits, layer_tag, norm_tag.
//
// Licence: GPL-3.0 (uses circomlib). See LICENSE in this folder.

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/bitify.circom";
include "circomlib/circuits/comparators.circom";

template Ownership(T, M, W_BITS, SUM_BITS, MAX_ERR, PRG_BITS) {
    // Domain separation tags and constants (must match protocol.py).
    var DOM_KEY = 1;
    var DOM_SIG = 2;
    var DOM_COMMIT = 3;
    var DOM_W = 4;
    var DOM_CFG = 6;
    var VERSION = 2;
    var W_CHUNK = 15;

    signal input seed;
    signal input w[M];
    signal input scale_bits;
    signal input layer_tag;
    signal input norm_tag;

    signal input pk_hash;
    signal input config_hash;
    signal input commitment;
    signal input w_hash;
    signal input nonce;

    // 1. config_hash must describe THIS circuit (T, M, W_BITS, MAX_ERR, PRG_BITS are compiled in),
    //    so a registration made for a strict threshold can't be proven with a lenient circuit.
    component cfg = Poseidon(10);
    cfg.inputs[0] <== DOM_CFG;
    cfg.inputs[1] <== VERSION;
    cfg.inputs[2] <== T;
    cfg.inputs[3] <== M;
    cfg.inputs[4] <== scale_bits;
    cfg.inputs[5] <== W_BITS;
    cfg.inputs[6] <== MAX_ERR;
    cfg.inputs[7] <== layer_tag;
    cfg.inputs[8] <== norm_tag;
    cfg.inputs[9] <== PRG_BITS;
    config_hash === cfg.out;

    // 2. Opening of the published commitment.
    component com = Poseidon(4);
    com.inputs[0] <== DOM_COMMIT;
    com.inputs[1] <== seed;
    com.inputs[2] <== pk_hash;
    com.inputs[3] <== config_hash;
    commitment === com.out;

    // 3. Range-check the suspect vector and bind the proof to it: |w_j| < 2^W_BITS, H(w) = w_hash.
    signal wpos[M];
    component wr[M];
    for (var j = 0; j < M; j++) {
        wpos[j] <== w[j] + (1 << W_BITS);
        wr[j] = Num2Bits(W_BITS + 1);
        wr[j].in <== wpos[j];
    }
    var NCH = (M + W_CHUNK - 1) \ W_CHUNK;
    component sponge[NCH];
    for (var c = 0; c < NCH; c++) {
        sponge[c] = Poseidon(W_CHUNK + 1);
        if (c == 0) {
            sponge[c].inputs[0] <== DOM_W;
        } else {
            sponge[c].inputs[0] <== sponge[c - 1].out;
        }
        for (var k = 0; k < W_CHUNK; k++) {
            if (c * W_CHUNK + k < M) {
                sponge[c].inputs[k + 1] <== wpos[c * W_CHUNK + k];
            } else {
                sponge[c].inputs[k + 1] <== 0;
            }
        }
    }
    component wfin = Poseidon(2);
    wfin.inputs[0] <== sponge[NCH - 1].out;
    wfin.inputs[1] <== M;
    w_hash === wfin.out;

    // 4. Key bit stream: low PRG_BITS bits of the canonical (strict) decomposition of each block.
    //    Num2Bits_strict rules out the alias x + p, so the prover can't choose different key bits.
    var KB = (T * M + PRG_BITS - 1) \ PRG_BITS;
    component kh[KB];
    component kbits[KB];
    for (var k = 0; k < KB; k++) {
        kh[k] = Poseidon(4);
        kh[k].inputs[0] <== DOM_KEY;
        kh[k].inputs[1] <== seed;
        kh[k].inputs[2] <== pk_hash;
        kh[k].inputs[3] <== k;
        kbits[k] = Num2Bits_strict();
        kbits[k].in <== kh[k].out;
    }

    // 5. Projections: X_ij = 2*bit - 1, so sum_j X_ij w_j = 2*sum_j bit*w_j - sum_j w_j.
    //    Extracted bit = 1 iff the projection >= 0, read as the top bit of (projection + 2^SUM_BITS).
    signal prod[T][M];
    component proj[T];
    var wsum = 0;
    for (var j = 0; j < M; j++) {
        wsum += w[j];
    }
    for (var i = 0; i < T; i++) {
        var s = 0;
        for (var j = 0; j < M; j++) {
            var e = i * M + j;
            prod[i][j] <== kbits[e \ PRG_BITS].out[e % PRG_BITS] * w[j];
            s += prod[i][j];
        }
        proj[i] = Num2Bits(SUM_BITS + 1);
        proj[i].in <== 2 * s - wsum + (1 << SUM_BITS);
    }

    // 6. Signature bit stream.
    var SB = (T + PRG_BITS - 1) \ PRG_BITS;
    component sh[SB];
    component sbits[SB];
    for (var k = 0; k < SB; k++) {
        sh[k] = Poseidon(4);
        sh[k].inputs[0] <== DOM_SIG;
        sh[k].inputs[1] <== seed;
        sh[k].inputs[2] <== pk_hash;
        sh[k].inputs[3] <== k;
        sbits[k] = Num2Bits_strict();
        sbits[k].in <== sh[k].out;
    }

    // 7. Count disagreements and enforce the acceptance threshold in-circuit (errors <= MAX_ERR).
    signal diff[T];
    var nerr = 0;
    for (var i = 0; i < T; i++) {
        diff[i] <== proj[i].out[SUM_BITS] + sbits[i \ PRG_BITS].out[i % PRG_BITS]
                    - 2 * proj[i].out[SUM_BITS] * sbits[i \ PRG_BITS].out[i % PRG_BITS];
        nerr += diff[i];
    }
    component ok = LessThan(11);
    ok.in[0] <== nerr;
    ok.in[1] <== MAX_ERR + 1;
    ok.out === 1;

    // 8. Bind the claim nonce: a public input that appears in no constraint is not bound by Groth16.
    signal nonce_sq;
    nonce_sq <== nonce * nonce;
}
