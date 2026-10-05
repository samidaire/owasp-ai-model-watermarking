// "Model under test": the menu on top of every app page. Pick a model, press Test, and every page shows its result.
import type { ModelInfo, ModelTestResult } from "../api";
import type { PageProps } from "../App";
import { Icon } from "../components/icons";
import { Verdict } from "../components/ui";
import { pct } from "../format";
import type { RunCtl } from "../panels/Shell";
import { Link } from "../router";

/** The one-line verdict of a model test, with its chip tone. */
export function modelVerdict(r: ModelTestResult): { tone: "good" | "bad" | "warn"; text: string } {
  if (r.verdict === "proven") return { tone: "good", text: "Ownership proven" };
  if (r.verdict === "rejected") return { tone: "bad", text: "Proof rejected" };
  if (r.verdict === "unreadable") return { tone: "warn", text: "Can't test this file" };
  return { tone: "bad", text: "Not proven" };          // the owner's mark isn't there (the bits-wrong count says how far off)
}

/** Starts a model test; `id` defaults to the selected model. */
export function testModel(ctl: RunCtl, id = ctl.model) {
  if (id !== ctl.model) ctl.setModel(id);
  ctl.run("model_test", { model: id });
}

export function TestButton({ ctl, id, primary = true, label = "Test this model" }: {
  ctl: RunCtl; id?: string; primary?: boolean; label?: string;
}) {
  const target = id ?? ctl.model;
  const mine = ctl.running === "model_test" && ctl.runningModel === target;
  return (
    <button type="button" className={`btn${primary ? " primary" : ""}`} disabled={ctl.running !== null}
      title={ctl.steps.model_test?.description} onClick={() => testModel(ctl, target)}>
      {mine ? <span className="spinner" aria-hidden /> : <span aria-hidden>▶</span>}
      {mine ? "Testing…" : label}
    </button>
  );
}

/** Menu groups in catalogue order. */
export function grouped(models: ModelInfo[]): [string, ModelInfo[]][] {
  const out = new Map<string, ModelInfo[]>();
  for (const m of models) out.set(m.group, [...(out.get(m.group) ?? []), m]);
  return [...out];
}

export function ModelBar({ s, ctl }: PageProps) {
  const m = ctl.models.find((x) => x.id === ctl.model);
  const r = s.results.model_tests?.[ctl.model];
  const v = r ? modelVerdict(r) : null;
  return (
    <section className="box modelbar" aria-label="Model under test">
      <div className="mb-pick">
        <label htmlFor="model-under-test" className="eyebrow">Model under test</label>
        <div className="actions" style={{ gap: 10 }}>
          <select id="model-under-test" className="sel" value={ctl.model} disabled={ctl.running === "model_test"}
            onChange={(e) => ctl.setModel(e.target.value)}>
            {grouped(ctl.models).map(([g, ms]) => (
              <optgroup key={g} label={g}>
                {ms.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
              </optgroup>
            ))}
          </select>
          <TestButton ctl={ctl} />
        </div>
        {m && <p className="muted" style={{ margin: 0, fontSize: 13 }}>{m.note}</p>}
      </div>
      <div className="mb-result" aria-live="polite">
        {!r ? <span className="muted" style={{ fontSize: 14 }}>Not tested yet. Press <strong>Test this model</strong>: the result appears here and on every page.</span> : <>
          <Verdict tone={v!.tone}>{v!.text}</Verdict>
          {r.v2 && <span className="chip mono">{r.v2.errors}/64 bits wrong</span>}
          <span className="chip mono">{r.accuracy === null ? "accuracy n/a" : `${pct(r.accuracy)} accuracy`}</span>
          {r.proof?.made && r.proof.timing && <span className="chip mono">proof {r.proof.timing.prove_s.toFixed(2)} s</span>}
          <Link to="/app/verify" className="rowgo">Details <Icon name="arrow" size={16} /></Link>
        </>}
      </div>
    </section>
  );
}
