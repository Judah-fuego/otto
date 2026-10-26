import type { ReactNode } from "react";
import type { AlertView, Status } from "@/lib/types";
import { clock } from "@/lib/format";
import { AlertCard } from "./AlertCard";

const TONE = {
  auto: { border: "border-l-auto" },
  ask_crew: { border: "border-l-alarm" },
  escalate: { border: "border-l-ground" },
} as const;

export const STATUS: Record<Status, { label: string; text: string }> = {
  executed: { label: "done · reversible", text: "text-auto" },
  awaiting_crew: { label: "awaiting you", text: "text-alarm" },
  approved: { label: "✓ crew approved", text: "text-auto" },
  rejected: { label: "crew rejected", text: "text-dim" },
  timed_out: { label: "timed out", text: "text-alarm" },
  escalated: { label: "with ground", text: "text-ground" },
};

const MARK: Record<Status, string> = {
  executed: "Auto-fixed",
  awaiting_crew: "Awaiting you",
  approved: "Crew approved",
  rejected: "Crew rejected",
  timed_out: "Timed out",
  escalated: "With ground",
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
  onSpeak: () => void;
  onAsk: () => void;
};

/** One line in the chat per alert. The full card only opens on request. */
export function AlertNotice({ alert, expanded, now, lightDelayS, onToggle, onReview, onDecide, onReopen, onSpeak, onAsk }: Props) {
  const tone = TONE[alert.authority];
  const awaiting = alert.decision.status === "awaiting_crew";
  const approved = alert.decision.status === "approved";
  const open = awaiting ? onReview : onToggle;

  return (
    <div className="arrive">
      <div
        className={`cursor-pointer rounded-r border-l-2 px-3 py-2 text-xs transition-colors ${approved ? "border-l-auto bg-auto/10" : `${tone.border} bg-panel/70`}`}
        onClick={open}
      >
        <div className="flex items-center gap-2.5 whitespace-nowrap">
          <StatusMark status={alert.decision.status} className={approved ? "text-auto" : STATUS[alert.decision.status].text} />
          <span className="min-w-0 truncate font-medium text-ink">{alert.subsystem}</span>
          <span className="font-mono text-faint tabular">
            {alert.channel} · {Math.round(alert.confidence * 100)}%
          </span>
          <span className="ml-auto font-mono text-faint tabular">{clock(alert.time)}</span>
        </div>
        <div className="mt-1 flex items-center gap-2 pl-6">
          <span className="min-w-0 flex-1 truncate text-dim" title={alert.proposed_action}>{alert.proposed_action}</span>
          <div className="flex shrink-0 items-center gap-0.5">
            <IconButton label="Read this alert aloud" onClick={onSpeak}>
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                <path d="M2 6h3l4-3v10l-4-3H2z" fill="currentColor" stroke="none" />
                <path d="M11 5.5a3.5 3.5 0 0 1 0 5M12.5 3.5a6 6 0 0 1 0 9" strokeLinecap="round" />
              </svg>
            </IconButton>
            <IconButton label="Ask otto about this alert" onClick={onAsk}>
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                <path d="M2.75 3.25h10.5v7.2H6.1L2.75 13.1V3.25z" strokeLinejoin="round" />
              </svg>
            </IconButton>
            {awaiting ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onReview();
                }}
                className="ml-1 rounded border border-alarm/60 px-2 py-0.5 font-mono text-alarm hover:bg-alarm/10"
              >
                review
              </button>
            ) : (
              <IconButton label={expanded ? "Hide details" : "Show details"} onClick={onToggle} expanded={expanded}>
                <svg viewBox="0 0 16 16" className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                  <path d="M4 6.5 8 10.5 12 6.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </IconButton>
            )}
          </div>
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

function StatusMark({ status, className }: { status: Status; className: string }) {
  const title = MARK[status];
  const live = status === "awaiting_crew" || status === "timed_out";
  return (
    <span title={title} aria-label={title} className={`inline-flex h-3.5 w-3.5 shrink-0 ${className} ${live ? "heartbeat" : ""}`}>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
        {status === "approved" && <path d="M3.5 8.5 6.5 11.5 12.5 4.5" strokeLinecap="round" strokeLinejoin="round" />}
        {status === "executed" && <path d="M9 2.25 4.25 9h3.1L6.5 13.75 11.75 7H8.4L9 2.25z" strokeLinejoin="round" />}
        {status === "rejected" && <path d="M4.5 4.5 11.5 11.5M11.5 4.5 4.5 11.5" strokeLinecap="round" />}
        {status === "escalated" && <path d="M4.5 11.5 11.5 4.5M6.5 4.5h5v5" strokeLinecap="round" strokeLinejoin="round" />}
        {status === "timed_out" && (
          <>
            <circle cx="8" cy="8" r="5.25" />
            <path d="M8 5.25V8l2 1.5" strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}
        {status === "awaiting_crew" && <circle cx="8" cy="8" r="3.25" fill="currentColor" stroke="none" />}
      </svg>
    </span>
  );
}

function IconButton({ label, onClick, expanded, children }: { label: string; onClick: () => void; expanded?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-expanded={expanded}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="inline-flex h-5 w-5 items-center justify-center rounded text-faint hover:bg-line/70 hover:text-ink"
    >
      {children}
    </button>
  );
}
