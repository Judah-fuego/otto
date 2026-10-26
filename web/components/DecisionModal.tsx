"use client";

import { useEffect } from "react";
import type { AlertView } from "@/lib/types";
import { AlertCard } from "./AlertCard";

type Props = {
  alert: AlertView;
  remaining: number;
  now: number;
  lightDelayS: number;
  /** Seconds before an unanswered decision loses the mission, during a flight. */
  decisionLeftS: number | null;
  onDecide: (approved: boolean) => Promise<void>;
  onReopen: () => Promise<void>;
  onNext: () => void;
  onClose: () => void;
};

/** One crew decision at a time. Clicking the backdrop does nothing: leaving is a deliberate "decide later". */
export function DecisionModal({ alert, remaining, now, lightDelayS, decisionLeftS, onDecide, onReopen, onNext, onClose }: Props) {
  const awaiting = alert.decision.status === "awaiting_crew";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const approved = alert.decision.status === "approved";
  const frame = approved
    ? { box: "border-auto/70 shadow-auto/10", bar: "border-auto/40 bg-auto/15", text: "text-auto" }
    : awaiting
      ? { box: "border-alarm/60 shadow-alarm/10", bar: "border-alarm/40 bg-alarm/10", text: "text-alarm" }
      : { box: "border-line shadow-black/20", bar: "border-line bg-panel", text: "text-dim" };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-6 pb-36 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="decision-title" className={`arrive w-full max-w-2xl rounded-xl border bg-void shadow-2xl transition-colors ${frame.box}`}>
        <div className={`flex items-center justify-between border-b px-5 py-3 transition-colors ${frame.bar}`}>
          <h2 id="decision-title" className={`flex items-center gap-2 font-mono text-xs font-medium uppercase tracking-[0.2em] ${frame.text}`}>
            {approved ? (
              <span className="text-sm leading-none" aria-hidden>✓</span>
            ) : (
              <span className={`h-2 w-2 rounded-full ${awaiting ? "bg-alarm heartbeat" : "bg-faint"}`} aria-hidden />
            )}
            {awaiting ? "Crew decision required" : approved ? "Approved · action carried out" : "Decision recorded"}
          </h2>
          <div className="flex items-center gap-4 font-mono text-xs tabular">
            {remaining > 0 && <span className="text-dim">{remaining} more waiting</span>}
            {awaiting && decisionLeftS !== null && (
              <span className={decisionLeftS <= 15 ? "heartbeat font-bold text-alarm" : "text-crew"}>
                {Math.ceil(decisionLeftS)} seconds to act
              </span>
            )}
          </div>
        </div>

        <div className="max-h-[70vh] overflow-y-auto p-5">
          <AlertCard alert={alert} now={now} lightDelayS={lightDelayS} onDecide={onDecide} onReopen={onReopen} />
        </div>

        <div className="flex justify-end gap-3 border-t border-line px-5 py-3">
          {awaiting ? (
            <button type="button" onClick={onClose} className="font-mono text-xs text-faint hover:text-dim">
              decide later (esc)
            </button>
          ) : remaining > 0 ? (
            <button type="button" onClick={onNext} className="rounded-md border border-alarm/60 px-4 py-1.5 text-sm text-alarm hover:bg-alarm/10">
              Next decision →
            </button>
          ) : (
            <button type="button" onClick={onClose} className="rounded-md border border-line px-4 py-1.5 text-sm text-dim hover:border-dim hover:text-ink">
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
