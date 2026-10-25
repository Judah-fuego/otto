import type { AlertView } from "@/lib/types";

type Props = { awaiting: AlertView[]; onReview: () => void };

/** Only crew decisions reach this bar. Everything SafeMode fixed on its own stays in the log. */
export function WarningBar({ awaiting, onReview }: Props) {
  if (awaiting.length === 0) return null;
  const items = awaiting.map((a) => `${a.subsystem} ${a.channel} · ${a.proposed_action}`);
  const run = (
    <span className="flex shrink-0 items-center gap-8 pr-8">
      {[0, 1].map((i) => (
        <span key={i} className="flex items-center gap-8">
          <span className="font-bold">⚠ WARNING ⚠ WARNING</span>
          <span>CREW DECISION REQUIRED</span>
          {items.map((t) => (
            <span key={t} className="font-normal normal-case tracking-normal">{t}</span>
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
      className="alarm-flash flex w-full items-stretch overflow-hidden border-y border-alarm bg-alarm text-left text-white"
    >
      <span className="ticker flex min-w-0 flex-1 items-center overflow-hidden py-2 font-mono text-sm font-medium uppercase tracking-[0.18em]">
        <span className="ticker-track flex">
          {run}
          {run}
        </span>
      </span>
      <span className="flex shrink-0 items-center bg-black/30 px-5 font-mono text-xs font-bold uppercase tracking-[0.16em]">
        Review{awaiting.length > 1 ? ` (${awaiting.length})` : ""} →
      </span>
    </button>
  );
}
