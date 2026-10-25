"use client";

import { useEffect } from "react";
import type { AlertView } from "@/lib/types";
import { AlertCard } from "./AlertCard";

type Props = {
  alert: AlertView;
  remaining: number;
  now: number;
  lightDelayS: number;
  onDecide: (approved: boolean) => Promise<void>;
  onReopen: () => Promise<void>;
  onNext: () => void;
  onClose: () => void;
};

/** One crew decision at a time. Clicking the backdrop does nothing: leaving is a deliberate "decide later". */
export function DecisionModal({ alert, remaining, now, lightDelayS, onDecide, onReopen, onNext, onClose }: Props) {
  const awaiting = alert.decision.status === "awaiting_crew";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-6 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="decision-title" className="arrive w-full max-w-2xl rounded-xl border border-alarm/60 bg-void shadow-2xl shadow-alarm/10">
        <div className="flex items-center justify-between border-b border-alarm/40 bg-alarm/10 px-5 py-3">
          <h2 id="decision-title" className="flex items-center gap-2 font-mono text-xs font-medium uppercase tracking-[0.2em] text-alarm">
            <span className="h-2 w-2 rounded-full bg-alarm heartbeat" aria-hidden />
            {awaiting ? "Crew decision required" : "Decision recorded"}
          </h2>
          {remaining > 0 && <span className="font-mono text-xs text-dim">{remaining} more waiting</span>}
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
