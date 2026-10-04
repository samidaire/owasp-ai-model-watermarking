// ZK-08: verify an ownership proof on a local EVM with the SnarkJS-exported Groth16 verifier.
//   VERIFIER=OwnershipVerifier_T64_M288_E8_W24 PROOF_DIR=<dir with proof.json, public.json> \
//     npx hardhat run scripts/verify_onchain.cjs
// Prints JSON: the honest proof must verify, a tampered public signal must not, plus gas figures.
const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const snarkjs = require("snarkjs");

async function main() {
  const dir = process.env.PROOF_DIR;
  const name = process.env.VERIFIER;
  if (!dir || !name) throw new Error("set PROOF_DIR and VERIFIER");
  const proof = JSON.parse(fs.readFileSync(path.join(dir, "proof.json"), "utf8"));
  const pub = JSON.parse(fs.readFileSync(path.join(dir, "public.json"), "utf8"));
  const args = JSON.parse("[" + (await snarkjs.groth16.exportSolidityCallData(proof, pub)) + "]");

  const Factory = await hre.ethers.getContractFactory(name);
  const verifier = await Factory.deploy();
  const receipt = await verifier.deploymentTransaction().wait();
  await verifier.waitForDeployment();

  const ok = await verifier.verifyProof(...args);
  const gas = await verifier.verifyProof.estimateGas(...args);

  const tampered = JSON.parse(JSON.stringify(args));
  const last = tampered[3].length - 1;
  tampered[3][last] = "0x" + (BigInt(tampered[3][last]) ^ 1n).toString(16).padStart(64, "0");
  const tamperedOk = await verifier.verifyProof(...tampered);

  console.log(JSON.stringify({
    verifier: name, chain_id: Number((await hre.ethers.provider.getNetwork()).chainId),
    verified: ok, tampered_public_signal_verified: tamperedOk,
    verify_gas: gas.toString(), deploy_gas: receipt.gasUsed.toString(),
    proof_pi_a0: String(proof.pi_a[0]),   // which proof was checked (the UI compares it with the current one)
  }));
}

main().catch((e) => { console.error(e); process.exit(1); });
