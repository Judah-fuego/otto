"use client";

import { useEffect, useRef, useState } from "react";

type Props = { label: string; holdMs?: number; disabled?: boolean; onConfirm: () => void };

/** An irreversible action needs a deliberate two-second hold, not a click. */
export function HoldButton({ label, holdMs = 2000, disabled, onConfirm }: Props) {
  const [progress, setProgress] = useState(0);
  const start = useRef<number | null>(null);
  const frame = useRef<number | null>(null);

  const stop = () => {
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = null;
    start.current = null;
    setProgress(0);
  };

  const tick = (t: number) => {
    if (start.current === null) start.current = t;
    const p = Math.min(1, (t - start.current) / holdMs);
    setProgress(p);
    if (p >= 1) {
      stop();
      onConfirm();
      return;
    }
    frame.current = requestAnimationFrame(tick);
  };

  const begin = () => {
    if (disabled || frame.current) return;
    frame.current = requestAnimationFrame(tick);
  };

  useEffect(() => stop, []);

  return (
    <button
      type="button"
      disabled={disabled}
      onPointerDown={begin}
      onPointerUp={stop}
      onPointerLeave={stop}
      onKeyDown={(e) => (e.key === " " || e.key === "Enter") && !e.repeat && begin()}
      onKeyUp={stop}
      className="relative overflow-hidden rounded-md border border-alarm/70 px-4 py-2 text-sm font-medium text-alarm select-none touch-none disabled:opacity-40"
    >
      <span className="absolute inset-y-0 left-0 bg-alarm/25" style={{ width: `${progress * 100}%` }} aria-hidden />
      <span className="relative">{progress > 0 ? `Keep holding… ${Math.ceil((1 - progress) * (holdMs / 1000))} seconds` : label}</span>
    </button>
  );
}
