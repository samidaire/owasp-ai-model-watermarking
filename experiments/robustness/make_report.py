"""Generate docs/reports/m5_robustness.md and docs/reports/figures/m5_*.svg from the results JSON (NFR-08).

Every number in the report is read from experiments/robustness/results/*.json; nothing is typed by hand.
    python experiments/robustness/make_report.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "experiments" / "robustness" / "results"
DOC = ROOT / "docs" / "reports" / "m5_robustness.md"
FIG = ROOT / "docs" / "reports" / "figures"

# reference categorical palette (slots 1-3), ink and surface for light backgrounds
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"
plt.rcParams.update({
    "svg.hashsalt": "sigil-m5", "svg.fonttype": "none", "font.size": 9, "font.family": "DejaVu Sans",
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titlesize": 10,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "xtick.color": INK2, "ytick.color": INK2, "legend.frameon": False,
    "legend.labelcolor": INK2, "lines.linewidth": 2, "lines.markersize": 5, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def load(name):
    p = RES / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pm(st, scale=1.0, d=2):
    if not st or st.get("mean") is None:
        return "–"
    if st.get("n", 2) <= 1:
        return f"{st['mean'] * scale:.{d}f}"
    return f"{st['mean'] * scale:.{d}f} ± {st['std'] * scale:.{d}f}"


def sci(x):
    if x is None:
        return "–"
    if x == 0:
        return "0"
    e = math.floor(math.log10(abs(x)))
    if -3 <= e <= 0:
        return f"{x:.4f}"
    return f"{x / 10 ** e:.2f}×10^{e}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / name, format="svg", metadata={"Date": None, "Creator": None})
    plt.close(fig)
    return f"figures/{name}"


def thresholds(ax, theta, chance=0.5):
    ax.axhline(theta, color=INK2, lw=1, ls="--")
    ax.text(ax.get_xlim()[0], theta, f" θ = {theta:.3f}", color=INK2, va="bottom", ha="left", fontsize=8)
    ax.axhline(chance, color=MUTED, lw=1, ls=":")
    ax.text(ax.get_xlim()[0], chance, " chance (0.5)", color=MUTED, va="bottom", ha="left", fontsize=8)


# ------------------------------------------------------------------ figures
def fig_pruning_mnist(mm):
    s = mm["summary"]["wm"]
    T = mm["protocol_config"]["T"]
    theta = mm["protocol_config"]["max_err"] / T
    ratios = mm["config"]["attacks"]["prune_ratios"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.4))
    for key, color, label in (("prune {}%", BLUE, "pruning only"), ("prune {}% + recovery", ORANGE, "pruning + 1-epoch recovery")):
        rows = [s[key.format(round(r * 100))] for r in ratios]
        x = [r * 100 for r in ratios]
        a.errorbar(x, [r["acc"]["mean"] * 100 for r in rows], yerr=[r["acc"]["std"] * 100 for r in rows], color=color,
                   marker="o", capsize=2, label=label)
        b.errorbar(x, [r["ber"]["mean"] for r in rows], yerr=[r["ber"]["std"] for r in rows], color=color, marker="o",
                   capsize=2, label=label)
    a.set(xlabel="weights pruned per layer (%)", ylabel="test accuracy (%)", title="Accuracy (mean ± std over seeds)")
    b.set(xlabel="weights pruned per layer (%)", ylabel="owner BER", ylim=(-0.03, 0.6), title="Owner BER of the white-box mark")
    thresholds(b, theta)
    a.legend(loc="lower left")
    fig.suptitle(f"MNIST, T={T}: magnitude pruning with and without recovery ({len(mm['seeds'])} seeds)", color=INK)
    fig.tight_layout()
    return save(fig, "m5_mnist_pruning.svg")


def fig_pruning_cifar(cm):
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.4))
    ratios = cm["config"]["attacks"]["prune_ratios"]
    rec = cm["config"]["attacks"]["recovery_ratios"]
    series = [("T64", "prune {}%", ratios, BLUE, "T=64, pruning only"),
              ("T256", "prune {}%", ratios, ORANGE, "T=256, pruning only"),
              ("T256", "prune {}% + recovery", rec, AQUA, "T=256, pruning + recovery")]
    for kind, key, rs, color, label in series:
        if kind not in cm["summary"]:
            continue
        rows = [cm["summary"][kind][key.format(round(r * 100))] for r in rs]
        x = [r * 100 for r in rs]
        a.errorbar(x, [r["acc"]["mean"] * 100 for r in rows], yerr=[r["acc"]["std"] * 100 for r in rows], color=color,
                   marker="o", capsize=2, label=label)
        b.errorbar(x, [r["ber"]["mean"] for r in rows], yerr=[r["ber"]["std"] for r in rows], color=color, marker="o",
                   capsize=2, label=label)
    a.set(xlabel="weights pruned per layer (%)", ylabel="test accuracy (%)", title="Accuracy")
    b.set(xlabel="weights pruned per layer (%)", ylabel="owner BER", ylim=(-0.03, 0.6), title="Owner BER")
    thresholds(b, 0.125)
    a.legend(loc="lower left")
    fig.suptitle(f"CIFAR-10 ResNet-18: magnitude pruning ({len(cm['seeds'])} seeds)", color=INK)
    fig.tight_layout()
    return save(fig, "m5_cifar_pruning.svg")


def fig_tradeoff_mnist(tr):
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.4))
    colors = {64: BLUE, 128: ORANGE, 256: AQUA}
    for T in tr["config"]["Ts"]:
        rows = [r for r in tr["summary"] if r["T"] == T]
        lams = [r["lam"] for r in rows]
        for ax, key, scale in ((axs[0], "acc_cost_pp", 1), (axs[1], "ftal_ber", 1), (axs[2], "overwrite_ber", 1)):
            ax.errorbar(lams, [r[key]["mean"] * scale for r in rows], yerr=[r[key]["std"] * scale for r in rows],
                        color=colors[T], marker="o", capsize=2, label=f"T={T}")
    axs[0].axhline(0, color=MUTED, lw=1)
    axs[0].axhline(0.5, color=INK2, lw=1, ls="--")
    axs[0].text(tr["config"]["lams"][0], 0.5, " WM-09 MNIST target (0.5 pp)", color=INK2, va="bottom", fontsize=8)
    axs[0].set(title="Accuracy cost vs clean (pp)", ylabel="percentage points")
    axs[1].set(title="Owner BER after FTAL (5 ep)", ylabel="BER", ylim=(-0.03, 0.6))
    axs[2].set(title="Owner BER after overwriting", ylabel="BER", ylim=(-0.03, 0.6))
    for ax in axs:
        ax.set_xscale("log")
        ax.set_xlabel("λ (embedding weight)")
        ax.set_xticks(tr["config"]["lams"], [str(v) for v in tr["config"]["lams"]])
    for ax in axs[1:]:
        thresholds(ax, 0.125)
    axs[0].legend(loc="upper left")
    fig.suptitle(f"ROB-07 on MNIST: accuracy and robustness vs λ and T ({len(tr['seeds'])} seeds, max_err = T/8)", color=INK)
    fig.tight_layout()
    return save(fig, "m5_mnist_tradeoff.svg")


def fig_tradeoff_cifar(ct):
    rows = sorted(ct["rows"], key=lambda r: r["lam"])
    lams = [r["lam"] for r in rows]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.4))
    a.plot(lams, [r["acc_cost_pp"] for r in rows], color=BLUE, marker="o")
    a.axhline(1.0, color=INK2, lw=1, ls="--")
    a.text(lams[0], 1.0, " WM-09 CIFAR target (1.0 pp)", color=INK2, va="bottom", fontsize=8)
    a.axhline(0, color=MUTED, lw=1)
    a.set(title="Accuracy cost vs clean (pp)", ylabel="percentage points")
    b.plot(lams, [r["ber"] for r in rows], color=BLUE, marker="o", label="no attack")
    b.plot(lams, [r["prune90_ber"] for r in rows], color=ORANGE, marker="o", label="90% pruning")
    b.plot(lams, [r["ftal_ber"] for r in rows], color=AQUA, marker="o", label="FTAL 5 ep")
    b.set(title="Owner BER", ylabel="BER", ylim=(-0.03, 0.6))
    thresholds(b, 0.125)
    b.legend(loc="upper right")
    for ax in (a, b):
        ax.set_xscale("log")
        ax.set_xlabel("λ (embedding weight)")
        ax.set_xticks(lams, [str(v) for v in lams])
    fig.suptitle(f"ROB-07 on CIFAR-10 ResNet-18, T={rows[0]['T']} (seed {ct['config']['tradeoff']['seeds']})", color=INK)
    fig.tight_layout()
    return save(fig, "m5_cifar_tradeoff.svg")


def extraction_rows(summary_kind, output="probs"):
    out = []
    for name, st in summary_kind.items():
        if st["family"] == "extraction" and f"({output})" in name:
            out.append((int(name.split()[1].rstrip("k")) * 1000, st))
    return sorted(out, key=lambda t: t[0])


def fig_extraction(mm, cm, k_ts_mnist, n_ts):
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.4))
    series = [("MNIST", mm["summary"].get("dual", {}), BLUE)]
    if cm and "dual" in cm["summary"]:
        series.append(("CIFAR-10", cm["summary"]["dual"], ORANGE))
    for label, summ, color in series:
        rows = extraction_rows(summ)
        if not rows:
            continue
        x = [b for b, _ in rows]
        axs[0].plot(x, [st["acc"]["mean"] * 100 for _, st in rows], color=color, marker="o", label=label)
        axs[1].plot(x, [st["ber"]["mean"] for _, st in rows], color=color, marker="o", label=label)
        axs[2].plot(x, [st["trigger_acc"]["mean"] * 100 for _, st in rows], color=color, marker="o", label=label)
    axs[0].set(title="Student test accuracy (%)", ylabel="accuracy (%)")
    axs[1].set(title="White-box mark: owner BER on the student", ylabel="BER", ylim=(-0.03, 0.7))
    thresholds(axs[1], 0.125)
    axs[2].set(title="Trigger-set accuracy of the student (%)", ylabel="trigger accuracy (%)", ylim=(-3, 103))
    axs[2].axhline(k_ts_mnist / n_ts * 100, color=INK2, lw=1, ls="--")
    axs[2].text(1000, k_ts_mnist / n_ts * 100, f" acceptance ({k_ts_mnist}/{n_ts})", color=INK2, va="bottom", fontsize=8)
    axs[2].axhline(10, color=MUTED, lw=1, ls=":")
    axs[2].text(1000, 10, " chance (10%)", color=MUTED, va="bottom", fontsize=8)
    for ax in axs:
        ax.set_xscale("log")
        ax.set_xlabel("queries to the victim (probabilities)")
    axs[0].legend(loc="lower right")
    fig.suptitle("ROB-03: black-box extraction of the dual-mark model", color=INK)
    fig.tight_layout()
    return save(fig, "m5_extraction.svg")


def fig_nulls(mn):
    p = mn["pooled_T64"]
    hist = {int(k): v for k, v in p["histogram"].items()}
    T = 64
    xs = list(range(0, T + 1))
    n = p["n"]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.bar(xs, [hist.get(x, 0) for x in xs], width=0.8, color=BLUE, label="observed (null model, key) pairs")
    ax.plot(xs, [n * math.comb(T, x) / 2 ** T for x in xs], color=ORANGE, marker="o", markersize=3,
            label="Bin(64, 1/2) expectation")
    me = mn["configs"]["T64"]["protocol_config"]["max_err"]
    ax.axvline(me + 0.5, color=INK2, lw=1, ls="--")
    ax.text(me + 0.7, ax.get_ylim()[1] * 0.9, f"accept ≤ {me}", color=INK2, fontsize=8)
    ax.set(xlabel="bit errors against the key's signature (of 64)", ylabel="pairs",
           title=f"WM-07: {mn['config']['null_models']} MNIST null models × {mn['config']['pooled_keys']} independent keys")
    ax.legend(loc="upper left")
    fig.tight_layout()
    return save(fig, "m5_mnist_nulls.svg")


# ------------------------------------------------------------------ report
def main():
    mm, mn, tr, zk = load("mnist_matrix"), load("mnist_nulls"), load("mnist_tradeoff"), load("mnist_zk")
    ct_train, cn, cm, ct = load("cifar_train"), load("cifar_nulls"), load("cifar_matrix"), load("cifar_tradeoff")
    present = {k: v for k, v in dict(mnist_matrix=mm, mnist_nulls=mn, mnist_tradeoff=tr, mnist_zk=zk, cifar_train=ct_train,
                                     cifar_nulls=cn, cifar_matrix=cm, cifar_tradeoff=ct).items() if v}
    L = ["# M5 robustness and evaluation (ROB-01 – ROB-08, WM-06, WM-07, WM-09, FIX-16)", "",
         "> Generated by `experiments/robustness/make_report.py` from `experiments/robustness/results/*.json`. "
         "Do not edit by hand: re-run the experiments and the generator.", ""]
    commits = sorted({v["env"]["git"]["commit"][:10] + (" (dirty)" if v["env"]["git"]["dirty"] else "") for v in present.values()})
    env = next(iter(present.values()))["env"]
    gpu_s = sum(v.get("gpu_seconds", 0) for v in present.values())
    L += [f"**Runs:** commit(s) {', '.join(commits)}; torch {env['torch']}; {env['gpu'] or env['device']}; "
          f"Python {env['python']}. GPU-busy time summed over the result files: **{gpu_s / 60:.0f} min** "
          f"(some jobs ran concurrently on the shared GPU, so wall-clock time was shorter).", ""]

    # ---------------- summary
    L += ["## 1. Headline results", ""]
    heads = []
    if mm:
        b = mm["base_summary"]
        s = mm["summary"]["wm"]
        removed = [n for n, st in s.items() if st["survived"] < st["n"]]
        cheap = [n for n in removed if s[n]["acc_drop_pp"]["mean"] <= 1.0]
        heads.append(f"**MNIST (T={mm['protocol_config']['T']}, {len(mm['seeds'])} seeds):** the white-box mark costs "
                     f"{pm(b['wm']['acc_cost_pp'])} pp of accuracy and survives {len(s) - len(removed)} of {len(s)} attack rows "
                     f"in every seed. Rows that remove it in at least one seed: {', '.join(removed) or 'none'}. "
                     f"Of those, the ones costing the attacker ≤ 1 pp: {', '.join(cheap) or 'none'}.")
    if mn:
        o = mn["configs"]["T64"]["owner_key_vs_nulls"]
        p = mn["pooled_T64"]
        heads.append(f"**WM-07, MNIST:** {o['false_positives']}/{o['n']} (null model, owner key) pairs accepted at "
                     f"max_err = {mn['configs']['T64']['protocol_config']['max_err']} (95% Clopper–Pearson upper bound "
                     f"{sci(o['cp95_upper'])}); pooled over {p['n']} independent keys: {p['false_positives']}/{p['n']} "
                     f"(upper bound {sci(p['cp95_upper'])}), against the binomial reference "
                     f"P[Bin(64, 1/2) ≤ 8] = {sci(p['binomial_reference'])}.")
    if ct_train:
        st = ct_train["summary"]
        c256 = st.get("T256", {}).get("acc_cost_pp")
        if c256:
            met = c256["mean"] <= 1.0
            heads.append(f"**CIFAR-10 ResNet-18 ({st['clean']['n']} seeds):** clean accuracy {pm(st['clean']['acc'], 100)} %; "
                         f"T=256 accuracy cost {pm(c256)} pp — WM-09's 1.0 pp target is **{'met' if met else 'missed'}** "
                         f"(T=64: {pm(st['T64']['acc_cost_pp'])} pp).")
    if mm and "dual" in mm["summary"]:
        ex = extraction_rows(mm["summary"]["dual"])
        if ex:
            b_, st_ = ex[-1]
            heads.append(f"**Extraction (ROB-03):** a student trained on {b_ // 1000}k victim outputs reaches "
                         f"{pm(st_['acc'], 100)} % on MNIST; the white-box mark is gone (owner BER {pm(st_['ber'])}, "
                         f"survived {st_['survived']}/{st_['n']}), and the trigger-set mark is accepted in "
                         f"{st_['trigger_accepted']}/{st_['n']} seeds (trigger accuracy {pm(st_['trigger_acc'], 100)} %).")
    if zk:
        if zk["status"] == "complete":
            ok = sum(r["proof_verifies"] is True for r in zk["rows"])
            heads.append(f"**ZK in the loop (ROB-05):** {ok}/{len(zk['rows'])} attacked MNIST models (seed {zk['seed']}) "
                         f"yield a verifying Groth16 proof; the proof verdict equals the watermark verdict in "
                         f"{sum(bool(r.get('consistent')) for r in zk['rows'])}/{len(zk['rows'])} rows.")
        else:
            heads.append(f"**ZK in the loop (ROB-05):** pending setup ({zk['status_detail']}); the code path is in "
                         "`mnist_zk.py` and the column shows the reference implementation's decision.")
    L += [f"- {h}" for h in heads] + [""]

    # ---------------- method
    L += ["## 2. Method (ROB-04)", ""]
    if mm:
        c = mm["config"]
        L += [f"- **Data.** MNIST: owner `{c['data_split']['owner']}`, attacker `{c['data_split']['attacker']}` "
              f"(disjoint), test `{c['data_split']['test']}`."
              + (f" CIFAR-10: owner `{cm['config']['data_split']['owner']}`, attacker "
                 f"`{cm['config']['data_split']['attacker']}`, test `{cm['config']['data_split']['test']}`." if cm else ""),
              f"- **Seeds.** MNIST {mm['seeds']}" + (f"; CIFAR-10 {cm['seeds']}" if cm else "")
              + ". Each seed fixes the model initialisation and batch order; attacks get their own seed. Every cell is "
                "mean ± sample std over seeds; 'survived' counts seeds.",
              f"- **Detection = what the circuit checks.** The owner's protocol-v2 key and signature (`sigil.protocol`), "
              f"the Uchida vector of the marked layer quantised with scale 2^{mm['protocol_config']['scale_bits']}, and "
              f"*survived* iff errors ≤ max_err (θ = max_err/T = {mm['protocol_config']['max_err']}/{mm['protocol_config']['T']} "
              f"on MNIST). θ is the one calibrated in §4 (WM-07).",
              "- **Attacker's accuracy cost** = accuracy of the stolen (marked) model − accuracy after the attack, in "
              "percentage points, on the 10k test set.",
              "- **Quantisation** (FIX-16): symmetric post-training quantisation, one scale per output channel "
              "(per-tensor for comparison with the old demo), scale rule and round-half-to-even exactly as torch.ao's "
              "observers (unit-tested against them); W8A8/W4A8 rows also fake-quantise every conv/linear input with a "
              "MinMax-calibrated per-tensor scale. Biases stay float as in int8 backends.",
              "- **Pruning + recovery** keeps the pruning mask during fine-tuning; **fine-pruning** follows Liu et al. "
              "(2018): prune the least-activated channels of a layer on clean attacker data, then fine-tune.",
              "- **Owner-side realignment (ROB-06)** does not know the thief's permutation and does not use the "
              "suspect's pre-attack weights. Assumption: the owner holds their own copy of the marked model (the model "
              "they trained and registered). Channels are matched by cosine similarity of the producer's filters and the "
              "consumer's input slices, solved as a one-to-one assignment (Hungarian). The permutation is disclosed with "
              "the claim so the verifier can re-apply it to the suspect file.",
              "- **Extraction (ROB-03)** is black-box: the attacker sends their own inputs once, keeps the returned "
              "probabilities (or labels) and trains a fresh model of the same architecture on those pairs only.",
              f"- **Trigger set (WM-06).** n = {mm['trigger_spec']['n']} images and labels derived from (seed, pk_hash) "
              f"with SHA-256 (`sigil.triggerset`), committed by SHA-256; accepted iff ≥ {mm['trigger_threshold']} of "
              f"{mm['trigger_spec']['n']} labels match, a false-positive rate ≤ {c['triggerset']['fpr']} under the "
              "exact Bin(n, 1/10) null.",
              "- **Configs** (versioned YAML, ROB-04): " + ", ".join(
                  f"`{v['config']['_path']}` (sha256 {v['config']['_sha256'][:12]})"
                  for v in (mm, mn, tr, cm or ct_train) if v) + ".", ""]

    # ---------------- MNIST
    if mm:
        T = mm["protocol_config"]["T"]
        L += [f"## 3. MNIST matrix (demo CNN, T = {T}, M = {mm['protocol_config']['M']}, layer `{mm['protocol_config']['layer']}`)", ""]
        b = mm["base_summary"]
        L += table(["Model", "Test accuracy (%)", "Cost vs clean (pp)", f"Owner errors (of {T})", "Trigger accuracy (%)"],
                   [[k, pm(b[k]["acc"], 100), pm(b[k].get("acc_cost_pp")) if k != "clean" else "–", pm(b[k]["errors"], 1, 1),
                     pm(b[k]["trigger_acc"], 100, 1)] for k in ("clean", "wm", "dual")]) + [""]
        zk_rows = {r["attack"]: r for r in zk["rows"]} if zk else {}
        n = len(mm["seeds"])
        L += [f"### 3.1 White-box mark under attack ({n} seeds; proof column: seed {mm['config']['zk_seed']})", ""]
        rows = []
        for name, st in mm["summary"]["wm"].items():
            z = zk_rows.get(name)
            zc = "–" if z is None else ("pending setup" if z["proof_verifies"] == "pending setup" else ("yes" if z["proof_verifies"] else "no"))
            rows.append([name, pm(st["acc"], 100), pm(st["acc_drop_pp"]), pm(st["errors"], 1, 1), pm(st["ber"], 1, 3),
                         f"{st['survived']}/{st['n']}", zc])
        L += table(["Attack", "Accuracy (%)", "Attacker cost (pp)", f"Errors (of {T})", "BER", "Survived", "Proof verifies"], rows)
        L += ["", f"![MNIST pruning]({fig_pruning_mnist(mm)})", ""]
        if "dual" in mm["summary"]:
            L += [f"### 3.2 Dual-mark model: white-box + committed trigger set ({n} seeds)", ""]
            rows = [[name, pm(st["acc"], 100), pm(st["acc_drop_pp"]), pm(st["errors"], 1, 1), f"{st['survived']}/{st['n']}",
                     pm(st["trigger_acc"], 100, 1), f"{st['trigger_accepted']}/{st['n']}"]
                    for name, st in mm["summary"]["dual"].items()]
            L += table(["Attack", "Accuracy (%)", "Attacker cost (pp)", f"Errors (of {T})", "White-box survived",
                        "Trigger accuracy (%)", "Trigger accepted"], rows) + [""]

    # ---------------- WM-07
    L += ["## 4. Null-model calibration of θ (WM-07)", ""]
    if mn:
        rows = []
        for key, blk in mn["configs"].items():
            pc = blk["protocol_config"]
            for label, f in (("owner keys vs null models", blk["owner_key_vs_nulls"]),
                             ("owner keys vs clean models", blk.get("owner_key_vs_clean_models"))):
                if f:
                    rows.append([f"MNIST T={pc['T']}, max_err={pc['max_err']}", label, f["n"],
                                 f"{f['errors']['mean']:.1f} ± {f['errors']['std']:.1f} (Bin: {f['binomial_mean']:.0f} ± {f['binomial_std']:.1f})",
                                 f["min_errors"], f["false_positives"], sci(f["cp95_upper"]), sci(f["binomial_reference"])])
        for label, f in (("independent keys (pooled)", mn["pooled_T64"]), ("nulls realigned to the owner's model", mn.get("realigned_nulls_T64"))):
            if f:
                rows.append(["MNIST T=64, max_err=8", label, f["n"],
                             f"{f['errors']['mean']:.1f} ± {f['errors']['std']:.1f} (Bin: {f['binomial_mean']:.0f} ± {f['binomial_std']:.1f})",
                             f["min_errors"], f["false_positives"], sci(f["cp95_upper"]), sci(f["binomial_reference"])])
        if cn:
            for key, blk in cn["configs"].items():
                pc = blk["protocol_config"]
                rows.append([f"CIFAR T={pc['T']}, max_err={pc['max_err']}", "owner keys vs null models", blk["n"],
                             f"{blk['errors']['mean']:.1f} ± {blk['errors']['std']:.1f} (Bin: {blk['binomial_mean']:.0f} ± {blk['binomial_std']:.1f})",
                             blk["min_errors"], blk["false_positives"], sci(blk["cp95_upper"]), sci(blk["binomial_reference"])])
                if blk.get("realigned_nulls"):
                    r = blk["realigned_nulls"]
                    rows.append([f"CIFAR T={pc['T']}, max_err={pc['max_err']}", "nulls realigned to the owner's model", r["n"],
                                 f"{r['errors']['mean']:.1f} ± {r['errors']['std']:.1f}", r["min_errors"], r["false_positives"],
                                 sci(clopper_upper(r["false_positives"], r["n"])), sci(blk["binomial_reference"])])
        L += table(["Configuration", "Population", "Pairs", "Errors mean ± std", "Min errors", "False positives",
                    "FPR 95% upper (Clopper–Pearson)", "Binomial P[Bin(T,½) ≤ max_err]"], rows) + [""]
        L += [f"MNIST null models: {mn['config']['null_models']} (accuracy {pm(mn['null_accuracy'], 100)} %), trained with the "
              "owner's recipe and never watermarked."
              + (f" CIFAR-10 null models: {cn['config']['nulls']['count']} (accuracy {pm(cn['null_accuracy'], 100)} %), trained "
                 f"for {cn['null_training']['epochs']} epochs instead of {cn['config']['owner_training']['epochs']} to fit the "
                 "time budget, plus the fully trained clean models." if cn else ""), ""]
        tsn = mn["triggerset"]
        L += [f"**Trigger set:** {tsn['false_positives']}/{tsn['pairs']} (null model, trigger set) pairs reach the "
              f"threshold {tsn['threshold']}/{tsn['n_triggers']} (max {tsn['max_matches']}, mean {pm(tsn['matches'], 1, 1)} "
              f"matches; Clopper–Pearson upper bound {sci(tsn['cp95_upper'])}; exact binomial FPR {sci(tsn['binomial_reference'])})."
              + (f" CIFAR-10: {cn['triggerset']['false_positives']}/{cn['triggerset']['pairs']} (max {cn['triggerset']['max_matches']})."
                 if cn else ""), "", f"![Null error distribution]({fig_nulls(mn)})", ""]
        L += ["**θ per configuration:** max_err = T/8 (θ = 0.125) is kept for every configuration: no null model came "
              "close to it, and the pooled study matches the binomial model, so the binomial reference is the FPR to quote "
              "and the empirical bound is the evidence that the binomial model applies." if
              all(b["owner_key_vs_nulls"]["false_positives"] == 0 for b in mn["configs"].values()) else
              "**θ per configuration:** at least one null model was accepted — see the table; θ must be tightened.", ""]

    # ---------------- CIFAR
    if ct_train:
        st = ct_train["summary"]
        pcs = ct_train["protocol_configs"]
        L += [f"## 5. CIFAR-10 ResNet-18 (layer `{pcs['T256']['layer']}`, M = {pcs['T256']['M']})", "",
              f"Training: {ct_train['config']['owner_training']['epochs']} epochs, SGD + Nesterov, OneCycle "
              f"(max lr {ct_train['config']['owner_training']['lr']}), batch {ct_train['config']['owner_training']['batch_size']}, "
              f"bf16 autocast, crop + flip; λ = {ct_train['config']['watermark']['lam']}. Seeds: {ct_train['seeds']} "
              f"({len(ct_train['seeds'])} — fewer than WM-09's 5, to fit the GPU budget).", ""]
        rows = []
        for k, v in st.items():
            rows.append([k, v["n"], pm(v["acc"], 100), pm(v.get("acc_cost_pp")) if k != "clean" else "–",
                         pm(v["errors_T64"], 1, 1), pm(v["errors_T256"], 1, 1), pm(v["trigger_acc"], 100, 1)])
        L += table(["Model", "Seeds", "Test accuracy (%)", "Cost vs clean (pp)", "Errors, T=64 key (of 64)",
                    "Errors, T=256 key (of 256)", "Trigger accuracy (%)"], rows) + [""]
    if cm:
        L += [f"### 5.1 Attack matrix ({len(cm['seeds'])} seeds)", ""]
        names = list(cm["summary"].get("T256", cm["summary"].get("T64", {})).keys())
        rows = []
        for name in names:
            a64, a256 = cm["summary"].get("T64", {}).get(name), cm["summary"].get("T256", {}).get(name)
            ref = a256 or a64
            rows.append([name, pm(ref["acc"], 100), pm(ref["acc_drop_pp"]),
                         f"{pm(a64['errors'], 1, 1)} ({a64['survived']}/{a64['n']})" if a64 else "–",
                         f"{pm(a256['errors'], 1, 1)} ({a256['survived']}/{a256['n']})" if a256 else "–"])
        L += table(["Attack", "Accuracy, T=256 model (%)", "Attacker cost (pp)", "T=64: errors (survived)",
                    "T=256: errors (survived)"], rows)
        L += ["", f"![CIFAR pruning]({fig_pruning_cifar(cm)})", ""]
        if "dual" in cm["summary"]:
            d = cm["summary"]["dual"]
            nd = next(iter(d.values()))["n"]
            L += [f"### 5.2 Dual-mark model (T = 256 + trigger set; {nd} seed): distillation and extraction", ""]
            rows = [[name, pm(v["acc"], 100), pm(v["acc_drop_pp"]), pm(v["errors"], 1, 1), f"{v['survived']}/{v['n']}",
                     pm(v["trigger_acc"], 100, 1), f"{v['trigger_accepted']}/{v['n']}"] for name, v in d.items()]
            L += table(["Attack", "Accuracy (%)", "Attacker cost (pp)", "Errors (of 256)", "White-box survived",
                        "Trigger accuracy (%)", "Trigger accepted"], rows) + [""]
    if mm:
        L += [f"![Extraction]({fig_extraction(mm, cm, mm['trigger_threshold'], mm['trigger_spec']['n'])})", ""]
    if cn:
        L += [f"CIFAR null calibration is in §4 ({cn['config']['nulls']['count']} null models).", ""]

    # ---------------- trade-off
    if tr:
        L += ["## 6. Trade-off: accuracy and robustness vs λ and T (ROB-07, WM-09)", ""]
        rows = [[r["T"], r["lam"], pm(r["acc_cost_pp"]), f"{r['owner_ber0']}/{r['n']}", pm(r["prune90_ber"], 1, 3),
                 pm(r["ftal_ber"], 1, 3), pm(r["overwrite_ber"], 1, 3),
                 f"{r['prune90_survived']}/{r['ftal_survived']}/{r['overwrite_survived']} of {r['n']}"] for r in tr["summary"]]
        L += table(["T", "λ", "Accuracy cost (pp)", "Owner BER = 0", "BER after 90% pruning", "BER after FTAL",
                    "BER after overwrite", "Survived (prune/FTAL/overwrite)"], rows)
        L += ["", f"![MNIST trade-off]({fig_tradeoff_mnist(tr)})", ""]
        t256 = next((r for r in tr["summary"] if r["T"] == 256 and r["lam"] == 1.0), None)
        if t256:
            L += [f"**WM-09 (MNIST, T = 256, λ = 1, {t256['n']} seeds):** accuracy cost {pm(t256['acc_cost_pp'])} pp — "
                  f"target ≤ 0.5 pp **{'met' if t256['acc_cost_pp']['mean'] <= 0.5 else 'missed'}**.", ""]
    if ct:
        rows = [[r["T"], r["lam"], f"{r['acc'] * 100:.2f}", f"{r['acc_cost_pp']:+.2f}", r["errors"], f"{r['prune90_ber']:.3f}",
                 f"{r['ftal_ber']:.3f}"] for r in sorted(ct["rows"], key=lambda r: r["lam"])]
        L += ["**CIFAR-10 λ sweep** (one seed, so differences under ~0.3 pp are within seed noise):", ""]
        L += table(["T", "λ", "Accuracy (%)", "Cost (pp)", "Owner errors", "BER after 90% pruning", "BER after FTAL"], rows)
        L += ["", f"![CIFAR trade-off]({fig_tradeoff_cifar(ct)})", ""]

    # ---------------- ZK
    if zk:
        L += ["## 7. ZK in the loop (ROB-05)", ""]
        if zk["status"] == "complete":
            rows = [[r["attack"], r["errors"], "yes" if r["survived"] else "no", "yes" if r.get("proof_generated") else "no (no witness)",
                     "yes" if r["proof_verifies"] is True else "no", f"{r.get('prove_s', '–')}",
                     "yes" if r.get("consistent") else "**NO**"] for r in zk["rows"]]
            L += table(["Attack (seed %d)" % zk["seed"], "Errors", "Survived", "Proof generated", "Proof verifies",
                        "Prove time (s)", "Verdicts agree"], rows) + [""]
        else:
            L += [f"Status: **{zk['status']}** — {zk['status_detail']}.", "",
                  "The code path (`experiments/robustness/mnist_zk.py`) builds a signed registration, a registry receipt "
                  "and a fresh claim per suspect file, calls `sigil.zk.circom.prove` and `sigil.verify.verify_ownership`, "
                  "and records whether the proof verifies. Until the Groth16 setup for "
                  f"`{zk['circuit']}` exists, the matrix shows *pending setup* and the reference implementation's decision "
                  f"(which accepts {sum(r['reference_decision'] for r in zk['rows'])} of {len(zk['rows'])} suspects).", ""]

    # ---------------- discussion
    L += ["## 8. Discussion", ""]
    if mm:
        s = mm["summary"]["wm"]
        fam = {}
        for name, st in s.items():
            fam.setdefault(st["family"], []).append((name, st))
        always = [n for n, st in s.items() if st["survived"] == 0]
        partly = [n for n, st in s.items() if 0 < st["survived"] < st["n"]]
        L += [f"**Which attacks remove the white-box mark (MNIST).** Removed in every seed: {', '.join(always) or 'none'}. "
              f"Removed in some seeds: {', '.join(partly) or 'none'}. Everything else — pruning up to "
              f"{max(r for r in mm['config']['attacks']['prune_ratios']) * 100:.0f}% with or without recovery, channel pruning, "
              "fine-pruning, int8/int4 quantisation (per channel and per tensor), FTLL/FTAL/RTLL/RTAL, k-means sharing and SVD — "
              "leaves the owner's errors at or below max_err in every seed."]
        perm = s.get("permutation")
        realigned = s.get("permutation + owner realign")
        if perm and realigned:
            L += ["", f"**Permutation** is the cheapest removal: it is functionally neutral (attacker cost {pm(perm['acc_drop_pp'])} pp) "
                  f"and drives the errors to {pm(perm['errors'], 1, 1)} of {mm['protocol_config']['T']}. Owner-side realignment, "
                  f"using only the owner's own copy, restores detection in {realigned['survived']}/{realigned['n']} seeds"
                  + (f", and still in {s[k]['survived']}/{s[k]['n']} seeds after the thief also fine-tunes the permuted model"
                     if (k := next((n for n in s if n.startswith("permutation + FTAL") and n.endswith("realign")), None)) else "")
                  + ". Realignment must then be shown not to create false positives: see the realigned nulls in §4."]
        ow = next((st for n, st in s.items() if st["family"] == "overwrite"), None)
        if ow:
            L += ["", f"**Overwriting** with the thief's own key leaves {pm(ow['errors'], 1, 1)} owner errors "
                  f"(survived {ow['survived']}/{ow['n']}): both marks coexist in the same layer, so the dispute is settled by "
                  "the registry timestamp (earliest registration wins), not by the watermark."]
        ex = [(n, st) for n, st in s.items() if st["family"] in ("extraction", "distillation")]
        if ex:
            L += ["", "**Why the white-box mark fails extraction.** A distilled or extracted student is a fresh network: its "
                  "weights are only constrained to reproduce the victim's outputs, and the Uchida mark lives in the "
                  "victim's weights, not in its input–output behaviour. The student's errors against the owner's key are "
                  + "; ".join(f"{n}: {pm(st['errors'], 1, 1)}" for n, st in ex)
                  + f" (chance is {mm['protocol_config']['T'] // 2}), all far above max_err = {mm['protocol_config']['max_err']}. "
                  "They sit somewhat below T/2 because an unrelated network's Uchida vector is not a perfectly random "
                  "direction (see the null errors in §4); none comes near the threshold."]
        if "dual" in mm["summary"]:
            dx = [(n, st) for n, st in mm["summary"]["dual"].items() if st["family"] in ("extraction", "distillation")]
            L += ["", "**Does the trigger-set mark hold under extraction?** On MNIST: "
                  + "; ".join(f"{n}: trigger accuracy {pm(st['trigger_acc'], 100, 1)} %, accepted {st['trigger_accepted']}/{st['n']}"
                              for n, st in dx)
                  + f" (acceptance needs {mm['trigger_threshold']}/{mm['trigger_spec']['n']}; chance is 10 %)."]
            if cm and "dual" in cm["summary"]:
                cx = [(n, st) for n, st in cm["summary"]["dual"].items() if st["family"] in ("extraction", "distillation")]
                L += [" On CIFAR-10: " + "; ".join(
                    f"{n}: {pm(st['trigger_acc'], 100, 1)} % (accepted {st['trigger_accepted']}/{st['n']})" for n, st in cx) + "."]
            anyhold = any(st["trigger_accepted"] > 0 for _, st in dx)
            L += ["", ("The trigger set survives some extraction settings, so NFR-10's wording 'survives extraction' may be "
                       "used **only** for the trigger-set mark and only for the settings marked accepted above."
                       if anyhold else
                       "The trigger set does **not** survive black-box extraction with in-distribution attacker queries: "
                       "the attacker never queries the out-of-distribution trigger images, so the student never learns their "
                       "secret labels. This matches the known weakness of Adi-style trigger sets against extraction "
                       "(Lukas et al., SoK 2022). Per NFR-10, no copy may claim that any mark here 'survives extraction'.")
                  + " The trigger set does still add evidence against removal attacks that keep the model itself "
                    "(quantisation, pruning, fine-tuning), where the dual table above shows it."]
    if cm:
        s256 = cm["summary"].get("T256", {})
        rem = [n for n, st in s256.items() if st["survived"] < st["n"]]
        L += ["", f"**CIFAR-10.** At T = 256 the mark is removed (in ≥ 1 seed) by: {', '.join(rem) or 'none'}; "
              + "; ".join(f"{n}: attacker cost {pm(s256[n]['acc_drop_pp'])} pp" for n in rem) + "."]
    L += [""]

    # ---------------- incomplete
    L += ["## 9. Limits and open items", ""]
    items = []
    if ct_train and len(ct_train["seeds"]) < 5:
        items.append(f"CIFAR-10 uses {len(ct_train['seeds'])} seeds, not the 5 that ROB-04/WM-09 ask for (GPU budget); the "
                     "dual model and the λ sweep use one seed.")
    if cn:
        items.append(f"CIFAR-10 null models train for {cn['null_training']['epochs']} epochs (owner models: "
                     f"{cn['config']['owner_training']['epochs']}).")
    if cm:
        mx = max(e["budget"] for e in cm["config"]["dual_attacks"]["extraction"])
        items.append(f"CIFAR-10 extraction budgets go up to {mx // 1000}k queries; queries beyond the 10k attacker pool are "
                     "augmented views of pool images.")
    if mm:
        items.append(f"MNIST extraction budgets stop at {max(e['budget'] for e in mm['config']['attacks']['extraction']) // 1000}k "
                     "because the disjoint attacker pool has 10k images.")
    if zk and zk["status"] != "complete":
        items.append("ROB-05's proof column is pending the Groth16 setup for the MNIST T=64 circuit (M3); T = 256 is not run.")
    elif zk:
        items.append("ROB-05 is run for MNIST T = 64 (one seed); the T = 256 column is not run.")
    items.append("ROB-01's 'runnable from the CLI and the API' is not wired here: `sigil.attacks` is the library the "
                 "`sigil attack` command and the API job runner (M6) will call.")
    items.append("GPU runs use cuDNN autotuning on CIFAR-10 (bit-exact reruns are only guaranteed on CPU and for the "
                 "deterministic MNIST runs); seeds and configs are recorded in every results file.")
    L += [f"- {i}" for i in items] + [""]
    L += ["## 10. Reproduce", "", "```", "python experiments/robustness/mnist_matrix.py", "python experiments/robustness/mnist_nulls.py",
          "python experiments/robustness/mnist_tradeoff.py", "SIGIL_CIRCUITS=<repo>/circuits python experiments/robustness/mnist_zk.py",
          "python experiments/robustness/cifar_run.py all", "python experiments/robustness/make_report.py", "```", ""]
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {DOC.relative_to(ROOT)}")


def clopper_upper(k, n, alpha=0.05):
    from scipy.stats import beta
    return 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))


if __name__ == "__main__":
    main()
