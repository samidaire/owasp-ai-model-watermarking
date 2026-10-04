// Generates Poseidon test vectors with circomlibjs (the JS twin of circomlib's circuits) so the
// Python implementation in sdk/src/sigil/poseidon.py can be checked bit for bit.
//   node circuits/scripts/poseidon_vectors.mjs > sdk/tests/vectors/poseidon_circomlibjs.json
import { buildPoseidon } from "circomlibjs";

const poseidon = await buildPoseidon();
const F = poseidon.F;
const P = F.p;

// Deterministic pseudo-random field elements (xorshift over BigInt) so the file is reproducible.
let s = 0x9e3779b97f4a7c15n;
function rnd() {
  let v = 0n;
  for (let k = 0; k < 4; k++) {
    s ^= (s << 13n) & 0xffffffffffffffffn;
    s ^= s >> 7n;
    s ^= (s << 17n) & 0xffffffffffffffffn;
    v = (v << 64n) | s;
  }
  return v % P;
}

const vectors = [];
for (let n = 1; n <= 16; n++) {
  const cases = [
    Array.from({ length: n }, (_, i) => BigInt(i + 1)),
    Array.from({ length: n }, () => 0n),
    Array.from({ length: n }, () => P - 1n),
    Array.from({ length: n }, () => rnd()),
  ];
  for (const inputs of cases) {
    vectors.push({ inputs: inputs.map(String), output: F.toObject(poseidon(inputs)).toString() });
  }
}
process.stdout.write(JSON.stringify({ generator: "circomlibjs@0.1.7 buildPoseidon", vectors }, null, 1));
