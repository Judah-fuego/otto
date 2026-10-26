import type { AlertView } from "@/lib/types";

type Props = { awaiting: AlertView[]; onReview: () => void };

/** Only crew decisions reach this bar. Auto-fixes stay in the log. */
export function WarningBar({ awaiting, onReview }: Props) {
  if (awaiting.length === 0) return null;
  const items = awaiting.map((a) => ({ id: a.alert_id, text: `${a.subsystem} ${a.channel} · ${a.proposed_action}` }));
  const run = (
    <span className="flex shrink-0 items-center gap-8 pr-8">
      {[0, 1].map((i) => (
        <span key={i} className="flex items-center gap-8">
          <span className="font-bold">⚠ WARNING ⚠ WARNING</span>
          <span>CREW DECISION REQUIRED</span>
          {items.map((t) => (
            <span key={`${i}-${t.id}`} className="font-normal normal-case tracking-normal">{t.text}</span>
          ))}
        </span>
      ))}
    </span>
  );
  return (
    <button
      type="button"
      onClick={onReview}
      role="alert"
      aria-label={`Warning: ${awaiting.length} crew decision${awaiting.length > 1 ? "s" : ""} required. Review.`}
      className="alarm-flash flex w-full items-stretch overflow-hidden border-y-2 border-white/40 bg-alarm text-left text-white shadow-[0_0_32px_rgba(255,40,40,0.55)]"
    >
      <span className="ticker flex min-w-0 flex-1 items-center overflow-hidden py-3 font-mono text-base font-semibold uppercase tracking-[0.18em]">
        <span className="ticker-track flex">
          {run}
          {run}
        </span>
      </span>
      <span className="flex shrink-0 items-center bg-black/40 px-5 font-mono text-sm font-bold uppercase tracking-[0.16em]">
        Review{awaiting.length > 1 ? ` (${awaiting.length})` : ""} →
      </span>
    </button>
  );
}
