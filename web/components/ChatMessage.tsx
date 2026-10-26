import ReactMarkdown from "react-markdown";
import type { Message, MissionStatus, VoyageResult } from "@/lib/types";
import { speak, spoken } from "@/lib/voice";
import { MissionCard } from "./MissionCard";
import { VoyageCard } from "./VoyageCard";

const CARDS = ["voyage_calculate", "mission_status"];

export function ChatMessage({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="arrive flex justify-end">
        <p className="max-w-[75%] rounded-lg bg-raised px-4 py-2.5 text-sm">{message.content}</p>
      </div>
    );
  }
  const cards = (message.calls ?? []).filter((c) => CARDS.includes(c.name) && !("error" in c.result));
  const others = (message.calls ?? []).filter((c) => !cards.includes(c));
  return (
    <div className="arrive space-y-3">
      {cards.map((c, i) =>
        c.name === "mission_status" ? (
          <MissionCard key={i} m={c.result as unknown as MissionStatus} />
        ) : (
          <VoyageCard key={i} v={c.result as unknown as VoyageResult} />
        ),
      )}
      {(message.content || others.length > 0) && (
        <div className="flex gap-3">
          <span className="mt-1 font-mono text-[11px] uppercase tracking-[0.14em] text-faint">otto</span>
          <div className="prose-otto min-w-0 flex-1 space-y-2 text-sm leading-relaxed">
            {message.content && <ReactMarkdown>{message.content}</ReactMarkdown>}
            <p className="flex gap-3 font-mono text-[11px] text-faint">
              {message.content && !message.live && (
                <button type="button" onClick={() => speak(message.speech ?? spoken(message.content), { interrupt: true })} className="hover:text-dim">
                  ▶ speak
                </button>
              )}
              {message.live && <span>on the call</span>}
              {others.length > 0 && <span>used {others.map((c) => c.name).join(", ")}</span>}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
