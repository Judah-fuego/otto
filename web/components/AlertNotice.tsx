import type { AlertView, Status } from "@/lib/types";
import { clock } from "@/lib/format";
import { AlertCard } from "./AlertCard";

const TONE = {
  auto: { text: "text-auto", border: "border-l-auto", label: "auto-fixed" },
  ask_crew: { text: "text-alarm", border: "border-l-alarm", label: "crew call" },
  escalate: { text: "text-ground", border: "border-l-ground", label: "to ground" },
} as const;

export const STATUS: Record<Status, { label: string; text: string }> = {
  executed: { label: "done · reversible", text: "text-auto" },
  awaiting_crew: { label: "awaiting you", text: "text-alarm" },
  approved: { label: "crew approved", text: "text-crew" },
  rejected: { label: "crew rejected", text: "text-dim" },
  escalated: { label: "with ground", text: "text-ground" },
};

type Props = {
  alert: AlertView;
  expanded: boolean;
  now: number;
  lightDelayS: number;
  onToggle: () => void;
  onReview: () => void;
  onDecide: (approved: boolean) => Promise<void>;
  onReopen: () => Promise<void>;
};

/** One line in the chat per alert. The full card only opens on request. */
export function AlertNotice({ alert, expanded, now, lightDelayS, onToggle, onReview, onDecide, onReopen }: Props) {
  const tone = TONE[alert.authority];
  const status = STATUS[alert.decision.status];
  const awaiting = alert.decision.status === "awaiting_crew";
  return (
    <div className="arrive">
      <div className={`rounded-r border-l-2 ${tone.border} bg-panel/70 px-3 py-2 text-xs`}>
        <div className="flex items-baseline gap-3 whitespace-nowrap">
          <span className={`font-mono uppercase tracking-[0.12em] ${tone.text}`}>{tone.label}</span>
          <span className="min-w-0 truncate font-medium text-ink">{alert.subsystem}</span>
          <span className="font-mono text-faint tabular">
            {alert.channel} · {Math.round(alert.confidence * 100)}%
          </span>
          <span className="ml-auto font-mono text-faint tabular">{clock(alert.time)}</span>
        </div>
        <div className="mt-1 flex items-baseline gap-3">
          <span className="min-w-0 flex-1 truncate text-dim" title={alert.proposed_action}>{alert.proposed_action}</span>
          <span className={`whitespace-nowrap font-mono uppercase tracking-[0.1em] ${status.text}`}>{status.label}</span>
          {awaiting ? (
            <button type="button" onClick={onReview} className="rounded border border-alarm/60 px-2 py-0.5 font-mono text-alarm hover:bg-alarm/10">
              review
            </button>
          ) : (
            <button type="button" onClick={onToggle} className="font-mono text-faint hover:text-dim" aria-expanded={expanded}>
              {expanded ? "hide" : "details"}
            </button>
          )}
        </div>
      </div>
      {expanded && !awaiting && (
        <div className="mt-2">
          <AlertCard alert={alert} now={now} lightDelayS={lightDelayS} onDecide={onDecide} onReopen={onReopen} />
        </div>
      )}
    </div>
  );
}
