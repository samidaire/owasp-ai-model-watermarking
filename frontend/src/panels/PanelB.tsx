import { isStale } from "../api";
import { LineChart } from "../components/charts";
import { Callout, Card, Empty, Meter, Notes, Verdict } from "../components/ui";
import { ber3, pct } from "../format";
import { PanelShell, RunButton, type PanelProps } from "./Shell";

const FAMILY: Record<string, string> = {
  baseline: "none", quantise: "quantisation", finetune: "fine-tuning", overwrite: "overwriting", permute: "permutation",
};

export function PanelB({ s, ctl, refreshing }: PanelProps) {
  const a = s.results.attacks;
  const pruning = a?.rows
    .filter((r) => r.family === "baseline" || r.family === "prune")
    .map((r) => ({ x: r.family === "baseline" ? 0 : Number(/(\d+)%/.exec(r.attack)?.[1] ?? 0), acc: r.accuracy, ber: r.owner_ber }))
    .sort((p, q) => p.x - q.x) ?? [];
  const others = a?.rows.filter((r) => r.family !== "prune") ?? [];
  const perm = a?.rows.find((r) => r.attack === "feature permutation");
  const realign = a?.rows.find((r) => r.attack.includes("realign"));
  const overwrite = a?.rows.find((r) => r.family === "overwrite");
  const pruneBreak = pruning.find((p) => p.acc < 0.9);

  return (
    <PanelShell
      letter="B" title="Removal attacks" reqs={["OWASP R1: remain detectable after modification", "Gap G2"]}
      claim="The thief tries to strip the watermark from the stolen model using the attack suite from Lukas et al. (SoK, IEEE S&P 2022), with 10,000 samples of their own data the owner never used."
      stale={isStale(a?.commitment, s.commitment)} refreshing={refreshing}
      actions={<RunButton ctl={ctl} step="attacks" label="Run attacks live" primary hint="~10 s on the GPU" />}
      notes={<Notes
        say={[
          "Under pruning, this watermark outlives the model: accuracy has collapsed long before the watermark breaks.",
          "Fine-tuning, re-training the last layer, and both quantisation levels don't touch it.",
          "But a functionally identical model with its channels reordered erases it for free. That is the SoK's point, OWASP R1, and my gap G2.",
          "I can undo the permutation here because I hold the original model. Making that work inside a ZK proof is Phase 4.",
          "Overwriting leaves two valid watermarks, which is the ambiguity problem again.",
        ]}
        caveats={["Attack subset only, on MNIST for live speed; the project moves to CIFAR-10 / ResNet-18."]}
      />}
    >
      {!a ? <Empty what="demo B" /> : <>
        <div className="grid2">
          <Card title="Test accuracy under pruning" sub="Per-layer magnitude pruning of every weight tensor">
            <LineChart points={pruning.map((p) => ({ x: p.x, y: p.acc }))} xTicks={[0, 20, 40, 60, 80, 100]}
              yTicks={[0, 0.25, 0.5, 0.75, 1]} fmtX={(x) => `${x}%`} fmtY={(y) => pct(y, 0)}
              xLabel="weights pruned per layer" color="var(--series-1)" valueName="test accuracy"
              ariaLabel="Test accuracy falls from 99% to under 10% as pruning increases" />
          </Card>
          <Card title="Owner BER under pruning" sub="Bit error rate of the owner's signature (lower is better)">
            <LineChart points={pruning.map((p) => ({ x: p.x, y: p.ber }))} xTicks={[0, 20, 40, 60, 80, 100]}
              yTicks={[0, 0.25, 0.5, 0.75, 1]} fmtX={(x) => `${x}%`} fmtY={(y) => y.toFixed(2)}
              threshold={{ y: a.threshold, label: `accept ≤ ${ber3(a.threshold)}` }}
              xLabel="weights pruned per layer" color="var(--series-2)" valueName="owner BER"
              ariaLabel="Owner BER stays near zero at every pruning level" />
          </Card>
        </div>
        {pruneBreak && (
          <Callout tone="good">
            <p><strong>The watermark outlives the model.</strong> At {pruneBreak.x}% pruning, accuracy is already {pct(pruneBreak.acc, 1)} while
              the owner BER is {ber3(pruneBreak.ber)}. Pruning is useless to the thief before it touches the watermark.</p>
          </Callout>
        )}

        <Card title="Other attacks" sub={`A watermark survives when the owner BER stays ≤ ${ber3(a.threshold)} (indicative threshold)`}>
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Attack</th><th>Type</th><th>Test accuracy</th><th>Owner BER</th><th>Outcome</th></tr></thead>
              <tbody>{others.map((r) => (
                <tr key={r.attack} className={r.survives ? undefined : "hl"}>
                  <td>{r.attack}</td>
                  <td style={{ color: "var(--text-secondary)" }}>{FAMILY[r.family] ?? r.family}</td>
                  <td><Meter value={r.accuracy} color="var(--series-1)" label={pct(r.accuracy)} /></td>
                  <td><Meter value={r.owner_ber} color="var(--series-2)" threshold={a.threshold} label={ber3(r.owner_ber)} /></td>
                  <td>{r.survives ? <Verdict tone="good">Survives</Verdict> : <Verdict tone="bad">Removed</Verdict>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Card>

        {perm && !perm.survives && (
          <Callout tone="bad">
            <p><strong>Feature permutation erases the watermark at zero accuracy cost</strong>: accuracy {pct(perm.accuracy)}, owner BER {ber3(perm.owner_ber)}.
              Reordering channels gives a functionally identical model whose weight vector no longer lines up with the key.
              {realign && <> Owner-side realignment restores it (BER {ber3(realign.owner_ber)}) because the owner holds the original model; doing that verifiably is Phase 4.</>}</p>
          </Callout>
        )}
        {overwrite && (
          <Callout tone="warn">
            <p><strong>Overwriting leaves two valid watermarks.</strong> The owner's survives (BER {ber3(overwrite.owner_ber)}) and the thief's own mark is embedded
              alongside it, so both parties can point to a watermark: the ambiguity problem again (demo C).</p>
          </Callout>
        )}
      </>}
    </PanelShell>
  );
}
