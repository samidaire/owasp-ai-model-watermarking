# OWASP AI Model Watermarking: Literature Review and Gap Analysis (v2)

*v1: 2026-10-04 (pass 1, abstracts only). **v2: 2026-10-05, pass 2.** In pass 2 I read the full texts of the core zero-knowledge papers, ran a forward-citation sweep, and checked every venue.*

*Rule used throughout: every claim cites a source that was opened and read this session. The verification column in Section 9 says how deeply each one was read (full text, abstract, or metadata only). Nothing is cited from memory.*

---

## 0. Executive summary

- **What the project is.** "OWASP AI Model Watermarking" is a real OWASP **Incubator** project. Its stated goal is **zero-knowledge (ZK) proof-based ownership verification** of AI model watermarks. Its GitHub repository holds **only website content, with no code**. [S1, S2]
- **What OWASP requires.** OWASP's own control text, **#MODEL WATERMARKING** in the AI Exchange, sets two requirements: watermarks must *"remain detectable even if the model is modified (for example through fine-tuning or pruning)"*, and must *"avoid ambiguity where multiple parties could plausibly claim ownership of the same model."* [S4]
- **How much research exists:**
  - Embedding watermarks and attacking them: **mature**. The robustness verdict is negative: "none of the surveyed watermarking schemes is robust in practice." [S7]
  - ZK-verified ownership: **very thin**. A forward-citation sweep of the founding paper (ZKROWNN, DAC 2023) found **2 follow-up systems** among about 13 citing works, and neither covers model weights.
- **Biggest gap.** ZKROWNN assumes a **semi-honest prover**. Its secret key, projection matrix and signature are all private and uncommitted, and it was **never evaluated against removal attacks**. [S8, full text] Three independent lines of work show that ownership claims can be forged:
  - ambiguity attacks [S16];
  - false claims built from transferable adversarial examples [S17];
  - random-key forgeability of regularised watermarks [S18].

  ZK makes this worse, because it *hides* the very key a verifier would need to inspect.
- **Proposed contribution.** A *committed-seed* ZK ownership protocol, evaluated under an OWASP-aligned attack suite:
  - **both the key and the signature are derived from one secret seed**, whose hash is committed and timestamped **at embedding time**;
  - ownership is proven in ZK at dispute time;
  - robustness is measured against SoK-style removal attacks [S7].
- **Fit with your machine.** It is feasible on your 32 GB / RTX 5080 machine. RoSeMary's published EZKL proof needed **about 2.6 GB of RAM and 7.2 s** [S9]. ZKROWNN's largest circuit (2.09M constraints) proved in 45 s, but on a 128 GB machine [S8].

---

## 1. Scope

| Item | Verified finding | Source |
|---|---|---|
| Project | OWASP AI Model Watermarking, **Incubator**, leader Krishanu Dhar | S1 |
| Objectives | (1) ZK-proof-based watermarking for several model types; (2) ZK ownership verification protocols; (3) an open-source, extensible app; (4) verification and extraction methods; (5) **resilience research against attacks**; (6) a proof of concept | S1 |
| Success criteria | Minimal performance impact; **watermark survival against model transformation attacks**; integration with ML frameworks | S1 |
| Code status | The repo holds Jekyll website files only (13 commits). **No implementation.** | S2 |
| Related OWASP project | **SecureML ("SecureAIML")**: model *signing* via OpenSSF Model Signing and Sigstore, plus Merkle fingerprinting. Its README does not mention ZK. | S3 |
| OWASP AI Exchange control | **#MODEL WATERMARKING** (owaspai.org/go/modelwatermarking). Description, requirements and limitations are quoted in Section 2. | S4 |
| OWASP ML Top 10 | **ML05:2023 Model Theft** lists "Adding a watermark to the model's code and training data" as a prevention measure | S5 |
| OWASP LLM Top 10 (2025) | **LLM10 Unbounded Consumption**: "Implement watermarking frameworks to embed and detect unauthorized use of LLM outputs" | S6 |

**In scope:**
- watermarks embedded in **the model**, for ownership verification;
- **ZK-verifiable** ownership claims.

**Out of scope, discussed only for contrast:**
- watermarks on model *outputs*, such as generated text, code or images;
- watermarks used for provenance of generated content.

---

## 2. OWASP's own requirements become project requirements

The AI Exchange **#MODEL WATERMARKING** control (PDF export generated 2026-10-03, pp. 230–231) gives the following requirements and limitations. [S4]

| Requirement | OWASP text (verbatim) | Becomes |
|---|---|---|
| **R1 Robustness** | "Watermarking techniques should be designed to remain detectable even if the model is modified (for example through fine-tuning or pruning)" | Attack suite with pass/fail thresholds (G2) |
| **R2 Non-ambiguity** | "…and to avoid ambiguity where multiple parties could plausibly claim ownership of the same model." | Forgery resistance (G1, the core gap) |
| **R3 Purpose** | "used to demonstrate ownership after a model has been stolen or replicated, rather than to prevent the theft itself" | Post-theft verification protocol |
| **L1 Limitation** | "Watermarking can be effective evidence for direct model theft, but is limited for model exfiltration … typical watermark approached are represented in data that would not be in distribution". It cites Entangled Watermarks [S19]. | An explicit scope limit (G4) |

The control is referenced under three threats:
- 2.4 Model exfiltration;
- development-time model theft;
- runtime model theft (model leak).

---

## 3. Verified literature

### 3.1 Core papers

| # | Paper | Venue | Read depth | Key verified content |
|---|---|---|---|---|
| P1 | Uchida, Nagai, Sakazawa, Satoh: *Embedding Watermarks into Deep Neural Networks* | ICMR 2017 | Abstract | White-box. A regulariser embeds bits into one layer's weights. Survives fine-tuning and **65% parameter pruning**. Code released. [S10] |
| P2 | Adi, Baum, Cisse, Pinkas, Keshet: *Turning Your Weakness Into a Strength: Watermarking DNNs by Backdooring* | **USENIX Security 2018** (venue checked via Semantic Scholar) | Abstract | Black-box trigger-set (backdoor) watermark. Negligible accuracy loss. [S11] |
| P3 | Rouhani, Chen, Koushanfar: *DeepSigns: A Generic Watermarking Framework for Protecting the Ownership of Deep Learning Models* | arXiv 1804.00750. ZKROWNN cites an ASPLOS 2019 version under a different title. | Title and authors from the PDF | Watermark embedded in the **activation-map distributions** (GMM means) of hidden layers. **This is the scheme ZKROWNN proves.** [S12] |
| P4 | Lukas, Jiang, Li, Kerschbaum: *SoK: How Robust is Image Classification DNN Watermarking?* | **IEEE S&P 2022** (stated in the arXiv text) | Full tables | Evaluates **11 schemes**, including Uchida, DeepSigns, Adi, Jia, DAWN and others, against a large attack suite: fine-tuning (FTAL/RTAL…), pruning, fine-pruning, weight quantisation, **weight shifting**, neural cleanse, overwriting, distillation, Knockoff Nets, retraining, and **smooth retraining**. Verdict: "none of the surveyed watermarking schemes is robust in practice." Code and data public. [S7] |
| P5 | Fan, Ng, Chan: *Rethinking DNN Ownership Verification: Embedding Passports to Defeat Ambiguity Attacks* | **NeurIPS 2019** | Abstract | Ambiguity attacks "aim to cast doubts on the ownership verification by forging counterfeit watermarks" and "pose serious threats to existing DNN watermarking methods". [S16] |
| P6 | Jia, Choquette-Choo, Chandrasekaran, Papernot: *Entangled Watermarks as a Defense against Model Extraction* | **USENIX Security 2021** | Abstract | Watermark features are entangled with task features, so removing the watermark costs accuracy. Ownership at 95% confidence with **fewer than 100 queries**; accuracy cost under 0.81 percentage points. **The OWASP control cites this paper.** [S19] |
| P7 | **Sheybani, Ghodsi, Kapila, Koushanfar: *ZKROWNN: Zero Knowledge Right of Ownership for Neural Networks*** | **DAC 2023** | **Full text** | See Section 3.2. [S8] |
| P8 | **Zhang, Javidnia, Sheybani, Koushanfar: *RoSeMary* (*Robust and Secure Code Watermarking for LLMs via ML/Crypto Codesign*; v3 PDF header: *Robust Zero Knowledge Verifiable Watermarking of Code LLMs with ML/Crypto Co-Design*)** | ACM TAISAP (arXiv v3, Aug 2026) | **Full text: threat model and ZK sections** | See Section 3.2. [S9] |
| P9 | **Ramakrishnan, Agarwal, S, Singh: *ZK-WAGON: Imperceptible Watermark for Image Generation Models using ZK-SNARKs*** | AI-ML Systems 2025 | **Full text** | See Section 3.2. [S13] |
| P10 | Sun, Li, Zhang: *zkLLM: Zero Knowledge Proofs for Large Language Models* | **ACM CCS 2024** | Full experiment table | ZK proofs of LLM **inference**, not of watermarks. Hardware: **A100 40 GB, 124.5 GB RAM, 12-core EPYC 7413.** Table 1 is reproduced in Section 6. [S14] |
| P11 | Liu, Zhang, Szyller, Ren, Asokan: *False Claims against Model Ownership Resolution* | **USENIX Security 2024** | Abstract | A *malicious accuser* can deviate undetected from the ownership-resolution process by using **transferable adversarial examples** as "evidence" against independent models. They demonstrate this against Amazon Rekognition, among others. [S17] |
| P12 | Choi, Wang, Choi, Sun: *ChainMarks: Securing DNN Watermark with Cryptographic Chain* | **ASIA CCS 2025** | Abstract | Trigger inputs are generated by **repeatedly hashing a secret key**, and target labels are derived from the owner's **digital signature**. Resists removal and ambiguity attacks. [S20] |
| P13 | Bui, Tran: *Beyond Robustness: On the Unforgeability Trade-offs in Statistical DNN Watermarking* | VCRIS 2025 (IEEE) | Abstract (Semantic Scholar) | Case study on the "DeepMark" framework (the abstract's term). Strong regularisation gives the owner's key **p ≈ 10⁻¹⁰²**, yet **a random key reaches p = 0.022**: an "ownership deadlock". The authors urge "cryptographically-grounded principles". [S18] |
| P14 | Xu, Wang, Ma, Koh, Xiao, Chen: *Instructional Fingerprinting of LLMs* | **NAACL 2024** | Abstract | Instruction-backdoor fingerprint, tested on 11 LLMs. Resists overclaiming and fingerprint guessing. [S25] |
| P15 | Russinovich, Cai, Salem: *Hey, That's My Model! Introducing Chain & Hash* | **ICLR 2026** (the arXiv page comment says "Published at ICLR 2026"; it also appears in ICLR 2026 proceedings search results) | Abstract | **Cryptographically binds** fingerprint prompts to their responses. Robust to fine-tuning and removal. Works on LoRA adapters. Code: github.com/microsoft/Chain-Hash. [S21] |
| P16 | Gloaguen, Jovanović, Staab, Vechev: *Towards Watermarking of Open-Source LLMs* | arXiv 2025 | Abstract | Open-weight LLM watermarks must survive **merging, quantisation and fine-tuning**. Current methods do not. [S22] |
| P17 | Liu et al.: *Implicit Identity Technologies for LLMs: Fingerprinting and Watermarking across Datasets, Models, and Generated Content* | **IJCAI-ECAI 2026** (survey) | Abstract | A lifecycle taxonomy of fingerprinting (intrinsic) versus watermarking (embedded) for ownership and provenance. Useful as the most recent survey anchor. [S23] |

### 3.2 The three ZK-watermarking systems, read in full

| | **ZKROWNN** [S8] | **RoSeMary** [S9] | **ZK-WAGON** [S13] |
|---|---|---|---|
| What is watermarked | **The model** (DeepSigns activation watermark) | LLM-generated **code** (output) | Generated **images** (output). The proof is hidden by LSB steganography. |
| What the ZK proof shows | The private key, run through the public model up to layer *l*, extracts a signature with BER ≤ θ | The committed decoder extracts the private signature from public code with BER ≤ θ | The selected generator layers produced this output |
| Circuit | Feed-forward to the watermarked layer, mean, Chebyshev sigmoid, threshold, BER | EZKL graph with a polynomial ReLU, a custom Halo2 zkBER, and fused composition | EZKL on "selected layers" (SL-ZKCC) |
| Proof system | Groth16 on BN128 (xJsnark + libsnark). Trusted setup per circuit. | Halo2 + KZG via a customised EZKL. Reuses a public universal SRS. | Halo2 via EZKL, run on EZKL's **Lilith cloud cluster** |
| Reported cost | **CIFAR-10 CNN:** 590,624 constraints; setup 32.4 s; **prover 11.2 s**; PK 117 MB; **proof 127 B**; **verify 1 ms**. **MNIST MLP:** 2.09M constraints; prover 45.1 s; PK 280 MB; VK 16 MB; verify 29.4 ms. | **Prove 7.15 s, about 2.62 GB RAM**; proof 17.12 KB; **verify 118.6 ms, about 222.5 MB RAM**; VK 577 KB. Moving logrows from 18 to 19 doubles proof and VK size. | **No timing, size or accuracy tables at all.** The proof JSON is about 1 MB, about 100 KB after gzip. |
| Hardware | **128 GB RAM, AMD "Ryzen 3990X"** desktop. Even so, part of the MLP's first layer had to be precomputed "due to memory constraints". | Training on RTX A6000 + Xeon Gold 6338. Proving hardware is not separately stated in the sections I read. | Cloud (Lilith) |
| Threat model | **Prover is semi-honest:** "P will not deviate from the protocol" | Adversary is a malicious end user. Assumes **honest setup** (the true decoder is committed in VK) and a semi-honest arbitrator. Adaptive and spoofing attacks are declared "orthogonal". | Not formalised |
| Removal attacks evaluated | **None.** It inherits DeepSigns' claims ("same BER and detection success as DeepSigns"). | **Yes, at the content level:** variable renaming (AUROC > 0.93 at 50% renamed), LLM refactoring, re-watermarking (AUROC 0.72), forgery (argued from ZK soundness) | **None.** LSB steganography is fragile by construction; the paper reports no robustness tests. |
| Forgery / ambiguity | **Not addressed.** Key, projection matrix *A* and signature are all private witnesses with no prior commitment. | Partly addressed. The VK commits to the decoder and zkBER binds the signature to {0,1}, but this relies on an honest setup. | Not addressed. It uses a secret-keyed SHA-256 of a perceptual hash. |
| Code | No code link in the paper | Customised EZKL. Release not confirmed. | Full-stack app described (FastAPI + Next.js). Release not confirmed. |

**Discrepancies worth recording (reviewers notice these):**
- **ZK-WAGON calls itself "the first to introduce ZK-WAGON, a novel system for watermarking image generation models using … ZK-SNARKs".** The claim is narrow, limited to image generators, and the paper itself cites ZKROWNN as prior ZK ownership work.
- **ZK-WAGON describes ZKROWNN** as "embedding watermarks in early layers altered model weights". ZKROWNN, however, states its scheme "does not modify the weights of the model at all". DeepSigns does the embedding; ZKROWNN only proves the extraction.
- **ZK-WAGON mislabels its own proof setup.** It calls Halo2 "transparent setup, eliminating the necessity for a trusted setup", yet also describes generating an SRS. RoSeMary, using the same EZKL stack, explicitly assumes "an honestly generated universal SRS whose toxic waste has been destroyed" (KZG).

### 3.3 Forward-citation sweep (method for the "very thin" claim)

**Method:** Semantic Scholar Graph API, `paper/arXiv:2309.06779/citations`, queried 2026-10-05. It returned **about 13 unique citing works (2023–2026)**. Screened by title, venue and DOI:

| Citing work | Year / venue | Type |
|---|---|---|
| ZK-WAGON | 2025, AI-ML Systems | **ZK + watermark system** (images) |
| RoSeMary | 2025, arXiv / TAISAP | **ZK + watermark system** (code) |
| Beyond Robustness: Unforgeability Trade-offs… | 2025, VCRIS | Forgery analysis (P13) |
| Survey on Verifiable Machine Learning | 2026, ACM Computing Surveys | Survey (metadata only) |
| SoK: Role of ZKPs in Confidential and Trustworthy AI | 2025, BCCA | Survey / SoK (metadata only) |
| ZKP Frameworks: A Systematic Survey | 2025, arXiv 2502.07063 | Survey (metadata only) |
| ZKP-Based Verifiable Decentralized ML: A Comprehensive Survey | IEEE COMST | Survey (metadata only) |
| Optimizing Privacy-Preserving Primitives to Support LLM-Scale Applications | 2025, arXiv 2509.25072 | Infrastructure |
| Gotta Hash 'Em All! Accelerating Hash Functions for ZKP Applications | 2025, ICCAD | Infrastructure |
| Watermarking LLMs and the Generated Content: Opportunities and Challenges | 2024, Asilomar | Position / overview |
| LLM-MARK; Older and Wiser (device aging + DNN IP) | 2024, DAC | Adjacent IP-protection work |

**Also found outside the sweep (not citing ZKROWNN):** Sato & Tanaka, *Protecting Ownership of Trained DNN Models with Zero-Knowledge Proofs*, ICISS 2024, Springer LNCS 2025, DOI 10.1007/978-3-031-80020-7_22. It is **closed access and the abstract is withheld**. ZK-WAGON describes it as using ZK-STARKs over Merkle roots with a risk of weight exposure; that is a secondary description, not one I verified.

**Conclusion:** among works citing the founding paper, **no system covers ZK-verified ownership of model weights under removal and forgery attacks.** Limits of this sweep:
- it covers one citation index;
- it misses papers that don't cite ZKROWNN;
- it was not repeated for Uchida, because the API rate-limited my requests.

---

## 4. Taxonomy and research density

```
Model ownership verification
├── White-box (weights/activations)  Uchida P1, DeepSigns P3 ──────┐
├── Black-box (queries)              Adi P2, Jia P6, ChainMarks P12 │ mature (2017+)
├── LLM fingerprints                 IF P14, Chain&Hash P15         │ growing
├── Removal attacks                  SoK P4, open-LLM P16 ──────────┘ mature; verdict NEGATIVE
├── Ownership FORGERY                Passports P5, False Claims P11,  ◄─ well established as a threat
│                                    Beyond Robustness P13
└── ZK-verified ownership            ZKROWNN P7 (weights)            ◄─ very thin; none combine
        ├── outputs only             RoSeMary P8 (code), ZK-WAGON P9    ZK with forgery resistance
        └── zkML infrastructure      zkLLM P10, EZKL                     and attack evaluation
```

---

## 5. Gap analysis (revised)

| ID | Gap | Evidence (verified) | FYP potential |
|---|---|---|---|
| **G1** | **Relaxing the semi-honest-prover assumption: uncommitted ZK ownership proofs are forgeable, and ZK hides the forgery.** *(This is my analysis, to be demonstrated in the project, not a finding stated in the literature.)* ZKROWNN **explicitly assumes** a semi-honest prover (S8 §III-A), so a malicious claimant is *outside its stated threat model*. That is a limitation of the assumption, not a bug they missed. The assumption is unrealistic in real disputes: P11 shows malicious accusers deviating undetected, and P5 and P13 show counterfeit or random keys passing verification. **Construction:** in ZKROWNN's Alg. 1, the projection matrix *A*, signature and trigger key are all private witnesses, and the bits are thresholds of sigmoid(µ·A). A claimant who sees the model can compute µ, pick any target bits, and for each column draw a random vector and flip its sign so that µ·aⱼ lands on the desired side. The result is BER 0 for a signature of their choosing, the same maths as the Uchida ambiguity attack applied to µ instead of w. ZK then hides the fitted *A* from the verifier. ChainMarks [P12] and Chain & Hash [P15] bind keys by hashing but have **no ZK**. RoSeMary commits its decoder in the VK, but **assumes an honest setup and watermarks outputs, not weights**. | S8 (threat model, Alg. 1), S9 §3.3, S16, S17, S18, S20, S21; OWASP R2 | **Core contribution.** A *committed-seed ZK ownership* protocol (§7). **Demonstrated live** in three steps: forgery succeeds without commitment; it still succeeds 100% when only the key is derived and the signature is free; it falls to roughly the null false-positive rate when the signature is also derived from the seed. |
| **G2** | **ZK-verified model watermarks have never been tested against removal attacks.** ZKROWNN inherits DeepSigns' claims; SoK [P4] showed that DeepSigns, Uchida and the other schemes fail under adaptive attacks. | S8 §IV, S7 Tables II–III; OWASP R1 | **Yes, and measurable.** Run a subset of SoK attacks (FTAL/RTAL, pruning, fine-pruning, quantisation, weight shifting, distillation) and record whether the ZK proof still verifies. |
| **G3** | **Binding the proof to the suspect model.** ZKROWNN takes the model as a *public* input (the VK grows to 16 MB for the MLP), so it needs white-box access to the suspect model. | S8 Alg. 1, §IV-A | **Yes.** Commit to the suspect weights by hash and make the hash public. Document that white-box access is required. |
| **G4** | **Exfiltration (API theft) is not covered by white-box watermarks.** OWASP's own limitation L1 says so. Entangled Watermarks [P6] is the cited direction. | S4 (L1), S19 | **Partly.** State it as a scope limit. Optional extension: a black-box ChainMarks-style trigger set. |
| **G5** | **No open, licence-clean implementation exists for the OWASP project.** The OWASP repo has no code [S2]. EZKL, the tool used by RoSeMary and ZK-WAGON, has **no open-source licence file**: the repo root has only `cla.md`, Cargo.toml and PyPI declare no licence, and the README only describes the CLA. | S2, S15 (checked via the GitHub API, Cargo.toml, PyPI JSON) | **Yes.** Build the PoC behind a backend-agnostic interface. Use EZKL for research, and assess a permissively licensed backend before contributing anything to OWASP. |
| **G6** | **Moving from CNNs to LLMs.** Open-weight LLM watermarks lack durability [P16]. zkLLM proves *inference*, not watermark extraction. Its reported memory is 1.88 GB (OPT-125M) to 23.1 GB (LLaMa-2-13B). | S22, S14 Table 1 | **Stretch only.** A fingerprint (P14/P15) on a ≤3B model is plausible. ZK over a transformer is research-level. |

**Correction from v1:** v1 claimed the sub-circuit idea was "the same idea ZKROWNN exploits". That was **wrong**:
- ZKROWNN proves **DeepSigns** extraction, which needs a **forward pass of the trigger inputs** up to the watermarked layer.
- The single matrix–vector product insight applies only to **Uchida-style** (weight-projection) watermarks.

ZKROWNN mentions the Uchida formula in its background section but **does not implement it**. A Uchida-style ZK circuit (projection, sigmoid or threshold, BER) is therefore *smaller* than ZKROWNN's, and has not been implemented in any of the ZK papers I read.

---

## 6. Feasibility on your machine (measured)

| Component | Detected (2026-10-04) |
|---|---|
| CPU | Ryzen 9 9950X3D, 16C/32T, L3 reported as 128 MB |
| GPU | RTX 5080, **16,303 MiB**, compute capability **12.0** (Blackwell), driver 617.14 |
| RAM | **32 GB** (2×16 GB DDR5-4800) |
| OS / tools | Win 11, WSL2 Ubuntu, Docker, Python 3.14, Node, Git. **No Rust, no nvcc.** |

**Software facts (pass 2, checked):**
- **PyTorch:** Blackwell support and CUDA 12.8 wheels arrived in **PyTorch 2.7** [S24]. **Windows CUDA wheels for Python 3.14 exist:** `torch-2.14.1+cu130-cp314-win_amd64` and `2.11.0+cu128-cp314` on download.pytorch.org (checked). *v1's "3.14 is likely too new" was wrong for PyTorch.*
- **EZKL:** PyPI `ezkl` 23.0.5 ships `cp37`-tagged wheels for win_amd64 and manylinux. These are probably abi3 builds, so they should install on 3.14; confirm with `pip install`. GPU acceleration is available via Icicle. Licence status: see G5.

**Reference points from the literature, scaled to your machine:**

| Workload | Published cost | Published hardware | Your machine |
|---|---|---|---|
| RoSeMary EZKL proof (small decoder) | 7.15 s, **2.62 GB RAM** | not stated | ✅ Comfortably within 32 GB |
| ZKROWNN CIFAR-10 CNN extraction (591K constraints) | Prover 11.2 s, PK 117 MB | 128 GB RAM, 3990X | ✅ Likely (different stack: Groth16/libsnark) |
| ZKROWNN MNIST MLP (2.09M constraints) | Prover 45.1 s; memory-constrained *even at 128 GB* | 128 GB RAM | ⚠️ Avoid. Use a Uchida-style circuit instead. |
| zkLLM OPT-125M / 1.3B / 2.7B inference proof | 1.88 / 3.71 / 6.60 GB; prover 74 / 221 / 352 s | A100 40 GB | ⚠️ Fits in 16 GB by reported memory, but the CUDA code needs an sm_120 build. Untested. |
| zkLLM OPT-6.7B / LLaMa-2-7B | 15.0 / 15.5 GB | A100 40 GB | ❌ Borderline at 16 GB; no headroom |
| zkLLM 13B | 22.9–23.1 GB | A100 40 GB | ❌ Exceeds your VRAM |

**Verdict:**

| Component | Implement | Demonstrate |
|---|---|---|
| Uchida white-box watermark (MNIST, CIFAR-10, ResNet-18) | ✅ | ✅ live |
| SoK-subset removal attacks | ✅ | ✅ live |
| **Ambiguity/forgery attack on uncommitted keys** (G1) | ✅ (pure PyTorch) | ✅ live, the highlight |
| **Committed-seed fix** (key *and* signature derived from the seed) | ✅ | ✅ live |
| ZK proof of Uchida extraction (EZKL/Halo2) | ✅ **Measured:** prove 0.63 s, verify 20 ms, 60 KB proof, 0.6 GiB RAM | ✅ live |
| Poseidon commitment to (X, s) in-circuit | ✅ **Measured:** logrows 20, prove ~36 s, pk 9.8 GiB, sampled peak RAM 2.6 GiB | ✅ live (precomputed) |
| Deriving X, s from the seed in-circuit (D2 level) | ⚠️ Not yet attempted; expected to be costly | Phase 3 |
| LLM fingerprint on a ≤3B model | ⚠️ Stretch | Recorded |
| ZK over an LLM | ❌ | ❌ |

**Phase-0 spike results (measured on this machine, 2026-10-05; code in `demo/`):**
- **Uncommitted proof (G1, confirmed cryptographically).** The thief's forged key produces an EZKL proof that **verifies under the owner's own verification key** (identical VK hash when the settings are equal). Without a commitment, a ZK ownership proof cannot tell owner from thief.
- **Poseidon-committed proof (`param_visibility="hashed"`).** The owner's public hash matches the published value and the thief's does not. This is the D1 level (direct commitment plus timestamp).
- **Cost of committing.** Committing raises logrows from 15 to 20 and proving time from 0.63 s to about 36 s. That trade-off is what RQ3 studies.
- **Removal attacks.** The Uchida watermark survives pruning past the point where the model is useless, plus FTAL, RTAL and int4. It is **erased by feature permutation at zero accuracy cost** (the SoK attack), and recovered by owner-side realignment. This is measured evidence for G2.

---

## 7. Proposed project (finalised after pass 2)

**Working title:** *Committed-Seed Zero-Knowledge Ownership Verification for Neural Network Watermarks: an OWASP AI Exchange-aligned reference implementation.*

**Research questions:**
1. **RQ1 (R2/G1):** Without a key commitment, how cheaply can an adversary forge a valid ZK ownership proof for a model they don't own? Does deriving both key and signature from a committed seed reduce forgery success to the null false-positive rate?
2. **RQ2 (R1/G2):** Under SoK-style removal attacks, at what attack strength does the ZK ownership proof stop verifying, and what accuracy cost does the attacker pay?
3. **RQ3 (G5, feasibility):** What do proving time, memory, proof size and verification time cost on a single workstation, as watermark length and layer size vary?

**Protocol sketch:**
- **Embed (at embedding time, not release; this also covers the development-time theft threat in §2):**
  - pick a secret seed *s*;
  - derive **both** the signature *b = H("sig" ‖ s ‖ owner_id)[:T]* **and** the key *X = PRG(H("key" ‖ s))*;
  - publish the commitment *C = H(s ‖ owner_id)* with a trusted timestamp (Sigstore/OpenSSF signing [S3] is a natural OWASP-native anchor);
  - embed *b* with the Uchida regulariser.
- **Dispute:** hash the suspect weights *W′* into a public value. The prover gives a ZK proof that they know *s* such that *H(s ‖ id) = C* and *BER(step(PRG(H("key"‖s))·w′), H("sig"‖s‖id)[:T]) ≤ θ*.
- **Why the signature must be derived too:** if *b* were a free choice, a thief who already holds the weights could pick any seed, derive *X*, *set b := extract(X, W)* and commit to that. They would get BER 0 every time. With *b* also fixed by *s*, the thief's only move is an adaptive **search over seeds** until extraction happens to match. Each try succeeds with roughly the null false-positive probability, which RQ1 measures. The **timestamp ordering** (earliest commitment wins) is defence in depth on top.
- **Choosing θ:** run the owner's key against independently trained "null" models. A handful of null models gives only an *indicative* threshold for the demo. The project needs enough null models to state a false-positive rate (this addresses P13's random-key result).
- **To verify in the Phase 0 spike:** the in-circuit hash and PRG (e.g. Poseidon via EZKL's hashed visibility) may dominate circuit size. A fallback is a hashed commitment to *X* and *b* directly.

**Phased plan (16 weeks):**

| Phase | Weeks | Output | Gate |
|---|---|---|---|
| 0. Spike | 1 | Environment ready. EZKL proves a toy Uchida circuit. RAM, time and logrows measured. | **Go/no-go on ZK backend** |
| 1. Baselines | 2–3 | Uchida + Adi watermarks; accuracy, BER and null-model FPR | Matches published behaviour |
| 2. Forgery study (RQ1) | 4–5 | Ambiguity attack vs uncommitted keys; free-signature vs derived-signature variants; committed-seed defence | Forgery success measured |
| 3. ZK circuit | 6–9 | Extraction + BER circuit, then the commitment opening | Proofs verify; costs logged |
| 4. Robustness × ZK (RQ2) | 10–11 | SoK-subset attack matrix with proof verified yes/no | Results tables |
| 5. Tool + API | 12–13 | CLI and Python API with a pluggable backend | Reproducible runs |
| 6. Stretch | 14 | LLM fingerprint (P14/P15) on a ≤3B model **or** a black-box ChainMarks-style variant | Optional |
| 7. Write-up | 15–16 | Report, dashboard, OWASP contribution proposal | Viva |

---

## 8. Pass-2 changes (claims corrected, removed or confirmed)

| v1 claim | v2 status |
|---|---|
| "Sub-circuit idea is the same one ZKROWNN exploits" | ❌ **Corrected.** ZKROWNN proves DeepSigns, including a forward pass. The single-layer insight is Uchida-only and unimplemented in the ZK work I read. |
| ZKROWNN: "<1 s verify, few KB" | ✅ **Confirmed and quantified:** 1 ms (CNN) / 29.4 ms (MLP) verify; 127 B proof; VK 34.7 KB / 16 MB |
| G2: ZK papers not evaluated against removal attacks | ✅ **Confirmed** for ZKROWNN and ZK-WAGON. ⚠️ **Refined** for RoSeMary: it evaluates content-level attacks (renaming, refactoring, re-watermarking), but on outputs, not weights. |
| G6: zkLLM "not a consumer-GPU workflow" | ⚠️ **Refined with data:** A100 40 GB; memory 1.88–23.1 GB. Small OPT models fit in 16 GB by reported memory. |
| "Python 3.14 likely too new" | ❌ **Corrected:** PyTorch CUDA wheels for cp314 on Windows exist |
| EZKL "licence via CLA, needs checking" | ⚠️ **Escalated:** no open-source licence file found; now gap G5 |
| P2, P3, P9 venues | ✅ **Confirmed:** USENIX Sec '18 (Semantic Scholar), IEEE S&P '22 (arXiv text), ICLR '26 (arXiv comment line) |
| (new) Forgery / ambiguity gap | ➕ **Added as G1** (core). Supported by P5, P11, P13, P12, P15, OWASP R2. |
| (new) OWASP AI Exchange control text | ➕ **Added.** R1/R2/L1 quoted verbatim. |
| (new) Phase-0 spike | ➕ **Added** (§6). EZKL works on this machine. A forged proof verifies under the owner's VK, and the Poseidon commitment separates owner from thief. Costs measured. |
| "No unified tool" | ✅ **Confirmed** by the forward-citation sweep (method and limits in §3.3) |

---

## 9. Sources (all opened 2026-10-04/05)

| ID | Source | Depth |
|---|---|---|
| S1 | OWASP AI Model Watermarking: https://owasp.org/projects/ai-model-watermarking | Full page |
| S2 | OWASP project repo: https://github.com/owasp/www-project-ai-model-watermarking | Repo listing |
| S3 | OWASP SecureML: https://github.com/OWASP/SecureML | README |
| S4 | OWASP AI Exchange, #MODEL WATERMARKING: https://owaspai.org/go/modelwatermarking (PDF export https://owaspai.org/OWASP-AI-Exchange.pdf, generated 2026-10-03, pp. 230–231) | **Verbatim** |
| S5 | OWASP ML Top 10, ML05:2023 Model Theft: https://owasp.github.io/www-project-machine-learning-security-top-10/docs/ML05_2023-Model_Theft | Full page |
| S6 | OWASP LLM Top 10 2025, LLM10: https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/ | Mitigation text |
| S7 | Lukas et al., SoK (IEEE S&P '22): https://arxiv.org/abs/2108.04974 | Full PDF tables |
| S8 | Sheybani et al., ZKROWNN (DAC '23): https://arxiv.org/abs/2309.06779 | **Full text** |
| S9 | Zhang et al., RoSeMary (TAISAP): https://arxiv.org/abs/2502.02068 | **Threat model, ZK and eval sections** |
| S10 | Uchida et al. (ICMR '17): https://arxiv.org/abs/1701.04082 | Abstract |
| S11 | Adi et al. (USENIX Sec '18): https://arxiv.org/abs/1802.04633 | Abstract + venue |
| S12 | Rouhani et al., DeepSigns: https://arxiv.org/abs/1804.00750 | PDF title page |
| S13 | Ramakrishnan et al., ZK-WAGON (AI-ML Systems '25): https://arxiv.org/abs/2510.01967 | **Full text** |
| S14 | Sun et al., zkLLM (CCS '24): https://arxiv.org/abs/2404.16109 | Setup + Table 1 |
| S15 | EZKL: https://github.com/zkonduit/ezkl; https://pypi.org/project/ezkl/ | README, root listing, Cargo.toml, PyPI JSON |
| S16 | Fan et al., Passports (NeurIPS '19): https://arxiv.org/abs/1909.07830 | Abstract |
| S17 | Liu et al., False Claims (USENIX Sec '24): https://arxiv.org/abs/2304.06607 | Abstract |
| S18 | Bui & Tran, Beyond Robustness (VCRIS '25): https://doi.org/10.1109/VCRIS68011.2025.11250570 | Abstract via Semantic Scholar |
| S19 | Jia et al., Entangled Watermarks (USENIX Sec '21): https://arxiv.org/abs/2002.12200 | Abstract |
| S20 | Choi et al., ChainMarks (ASIA CCS '25): https://arxiv.org/abs/2505.04977 | Abstract |
| S21 | Russinovich et al., Chain & Hash (ICLR '26): https://arxiv.org/abs/2407.10887 (venue from the arXiv comment; ICLR proceedings listing seen in search results only) | Abstract |
| S22 | Gloaguen et al.: https://arxiv.org/abs/2502.10525 | Abstract |
| S23 | Liu et al., Implicit Identity survey (IJCAI-ECAI '26): https://arxiv.org/abs/2605.29245 | Abstract |
| S24 | PyTorch 2.7 release: https://pytorch.org/blog/pytorch-2-7/ | Release notes |
| S25 | Xu et al., Instructional Fingerprinting (NAACL '24): https://arxiv.org/abs/2401.12255 | Abstract (cited as P14) |
| — | Sato & Tanaka (ICISS '24), DOI 10.1007/978-3-031-80020-7_22 | **Metadata only.** Closed access; not used as evidence. |
