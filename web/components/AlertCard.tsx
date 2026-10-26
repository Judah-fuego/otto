"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { AlertView } from "@/lib/types";
import { clock, countdown } from "@/lib/format";
import { CrewTask } from "./CrewTask";
import { Sparkline } from "./Sparkline";

const TONE = {
  auto: { color: "var(--color-auto)", text: "text-auto", border: "border-auto/30", label: "Auto", blurb: "Reversible. SafeMode acted." },
  ask_crew: { color: "var(--color-alarm)", text: "text-alarm", border: "border-alarm/60", label: "Crew decision", blurb: "Cannot be undone. You decide." },
  escalate: { color: "var(--color-ground)", text: "text-ground", border: "border-ground/40", label: "Ground", blurb: "Not confident enough to act alone." },
} as const;

type Props = {
  alert: AlertView;
  now: number;
  lightDelayS: number;
  onDecide: (approved: boolean) => Promise<void>;
  onReopen: () => Promise<void>;
};

export function AlertCard({ alert, now, lightDelayS, onDecide, onReopen }: Props) {
  const tone = TONE[alert.authority];
  const status = alert.decision.status;
  const awaiting = status === "awaiting_crew";
  const approved = status === "approved";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFigure, setShowFigure] = useState(false);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const groundEta = Date.parse(alert.decision.time) + 2 * lightDelayS * 1000 - now;
  const sigma = alert.telemetry.shift_in_sigma;

  return (
    <article
      className={`arrive rounded-lg border transition-colors ${approved ? "border-auto/70 bg-auto/5" : `bg-panel ${tone.border}`} ${awaiting ? "alarm-glow" : ""}`}
      aria-live={awaiting ? "assertive" : "polite"}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-4 py-2.5">
        <div className="flex items-baseline gap-3 whitespace-nowrap">
          <span className={`font-mono text-[11px] uppercase tracking-[0.14em] ${approved ? "text-auto" : tone.text}`} title={tone.blurb}>
            {approved ? "✓ Crew approved" : tone.label}
          </span>
          <h3 className="text-sm font-medium">{alert.subsystem}</h3>
          <span className="font-mono text-xs text-dim">{alert.channel}</span>
        </div>
        <span className="font-mono text-xs text-faint tabular">{alert.alert_id} · {clock(alert.time)}</span>
      </header>

      <div className="grid grid-cols-[1fr_auto] gap-4 px-4 pt-3">
        <Sparkline values={alert.values} color={tone.color} />
        <dl className="grid content-start gap-2 font-mono text-xs tabular">
          <div>
            <dt className="text-faint">confidence</dt>
            <dd className="text-lg text-ink">{Math.round(alert.confidence * 100)}%</dd>
          </div>
          <div title="How far the latest readings moved from their earlier average, in multiples of the earlier normal variation (σ).">
            <dt className="text-faint">vs normal</dt>
            <dd className="text-ink">{Math.abs(sigma).toFixed(1)}σ {sigma > 0 ? "above" : "below"}</dd>
          </div>
        </dl>
      </div>

      <div className="space-y-3 px-4 py-3 text-sm leading-relaxed text-ink/90">
        {alert.narration ? (
          <ReactMarkdown>{alert.narration}</ReactMarkdown>
        ) : (
          <p className="text-dim">Likely: {alert.likely_causes}. otto is writing a summary…</p>
        )}
      </div>

      {approved && (
        <p className="arrive mx-4 mb-3 rounded-md border border-auto/50 bg-auto/10 px-3 py-2 text-sm text-auto">
          <span className="mr-2 font-mono text-xs font-bold uppercase tracking-[0.14em]">✓ Done</span>
          You approved this at {clock(alert.decision.time)}. The fix is carried out and the fault is cleared.
        </p>
      )}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.14em] text-faint">Proposed action</p>
          <p className="text-sm">{alert.proposed_action}</p>
          <p className="text-xs text-dim">{alert.authority_reason}</p>
        </div>

        {status === "executed" && <Stamp className="text-auto">Done · reversible</Stamp>}
        {status === "approved" && <Stamp className="text-auto">✓ Crew approved</Stamp>}
        {status === "timed_out" && <Stamp className="text-alarm">No crew decision in time · mission lost</Stamp>}
        {status === "rejected" && (
          <div className="flex items-center gap-3">
            <Stamp className="text-dim">Crew rejected · no action</Stamp>
            <button
              type="button"
              disabled={busy}
              onClick={() => run(onReopen)}
              className="rounded-md border border-line px-3 py-1.5 text-xs text-dim hover:border-crew/60 hover:text-crew disabled:opacity-40"
            >
              ↺ Reconsider
            </button>
          </div>
        )}
        {status === "escalated" && (
          <Stamp className="text-ground">
            {groundEta > 0 ? `Sent to ground · earliest reply ${countdown(groundEta / 1000)}` : "Awaiting ground reply"}
          </Stamp>
        )}
      </footer>

      {awaiting && (
        <CrewTask
          key={alert.alert_id}
          alert={alert}
          disabled={busy}
          onApprove={() => run(() => onDecide(true))}
          onReject={() => run(() => onDecide(false))}
        />
      )}

      {error && <p className="px-4 pb-3 text-xs text-alarm">{error}</p>}

      {alert.has_figure && (
        <div className="border-t border-line px-4 py-2">
          <button type="button" onClick={() => setShowFigure((v) => !v)} className="font-mono text-xs text-faint hover:text-dim">
            {showFigure ? "− hide" : "+ show"} Telemanom score chart
          </button>
          {showFigure && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`/api/figures/${alert.channel}`} alt={`Anomaly scores for ${alert.channel}`} className="mt-2 w-full rounded border border-line" />
          )}
        </div>
      )}
    </article>
  );
}

function Stamp({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`font-mono text-xs uppercase tracking-[0.12em] ${className}`}>{children}</span>;
}
