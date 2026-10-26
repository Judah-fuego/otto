// otto's voice. xAI text to speech through /api/tts, falling back to the browser's own
// speech synthesis when the server or network can't produce audio.
// Browsers only allow audio after the page has had a click or a key press.

const PREFERRED = ["Samantha", "Google US English", "Daniel", "Karen", "Alex"];
const CACHE_MAX_CHARS = 40;

function pickVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  for (const name of PREFERRED) {
    const v = voices.find((x) => x.name.startsWith(name));
    if (v) return v;
  }
  return voices.find((v) => v.lang.startsWith("en")) ?? null;
}

/** Markdown to something a voice can read: no symbols, units spelled out where they trip it up. */
export function spoken(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, "")
    .replace(/[*_`#>]/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/(\d)\s?km\/s/g, "$1 kilometres per second")
    .replace(/(\d)\s?min\b/g, "$1 minutes")
    .replace(/(\d)\s?d\b/g, "$1 days")
    .replace(/(\d)\s?t\b/g, "$1 tonnes")
    .replace(/(\d)\s?kg\b/g, "$1 kilograms")
    .replace(/(\d)\s?%/g, "$1 percent")
    .replace(/→/g, " to ")
    .replace(/\n+/g, ". ")
    .replace(/\.\s*\./g, ".")
    .trim();
}

// Bumped by stop(); queued work from an older generation drops itself.
let generation = 0;
let queue: Promise<void> = Promise.resolve();
let playing: { audio: HTMLAudioElement; done: () => void } | null = null;
const cache = new Map<string, Promise<Blob | null>>();

function enqueue(step: () => Promise<void>): void {
  const g = generation;
  queue = queue.then(() => (g === generation ? step() : undefined)).catch(() => undefined);
}

// After a failed TTS call, stay on the browser voice for a while so otto doesn't switch voices clip to clip.
const TTS_RETRY_MS = 60_000;
let ttsDownUntil = 0;

function fetchClip(text: string, rate: number): Promise<Blob | null> {
  if (Date.now() < ttsDownUntil) return Promise.resolve(null);
  const key = `${rate}:${text}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const clip = fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, speed: rate }),
  })
    .then((r) => (r.ok ? r.blob() : null))
    .catch(() => null)
    .then((b) => {
      if (!b) ttsDownUntil = Date.now() + TTS_RETRY_MS;
      return b;
    });
  if (text.length <= CACHE_MAX_CHARS) {
    cache.set(key, clip);
    clip.then((b) => b || cache.delete(key));
  }
  return clip;
}

function playClip(blob: Blob): Promise<void> {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  return new Promise<void>((resolve) => {
    const done = () => {
      URL.revokeObjectURL(url);
      if (playing?.audio === audio) playing = null;
      resolve();
    };
    playing = { audio, done };
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);
  });
}

function synthesize(text: string, rate: number): Promise<void> {
  if (!window.speechSynthesis) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    const voice = pickVoice();
    if (voice) u.voice = voice;
    u.rate = rate;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    window.speechSynthesis.speak(u);
  });
}

let klaxonNodes: OscillatorNode[] = [];

function silenceKlaxon(): void {
  for (const osc of klaxonNodes) {
    try {
      osc.stop();
    } catch {
      // Already finished.
    }
  }
  klaxonNodes = [];
}

export function stop(): void {
  if (typeof window === "undefined") return;
  generation++;
  queue = Promise.resolve();
  silenceKlaxon();
  if (playing) {
    playing.audio.pause();
    playing.done();
  }
  window.speechSynthesis?.cancel();
}

export function speak(text: string, { interrupt = false, rate = 1.0 } = {}): void {
  if (typeof window === "undefined" || !text) return;
  if (interrupt) stop();
  const g = generation;
  const clip = fetchClip(text, rate);
  enqueue(async () => {
    const blob = await clip;
    if (g !== generation) return;
    await (blob ? playClip(blob) : synthesize(text, rate));
  });
}

let audio: AudioContext | null = null;

/** Two-tone klaxon, three times. */
function klaxon(): Promise<void> {
  audio ??= new AudioContext();
  const ctx = audio;
  const start = ctx.currentTime + 0.05;
  for (let i = 0; i < 3; i++) {
    for (const [j, freq] of [880, 660].entries()) {
      const t = start + i * 0.42 + j * 0.18;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.08, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.17);
      klaxonNodes.push(osc);
      osc.onended = () => {
        klaxonNodes = klaxonNodes.filter((n) => n !== osc);
      };
    }
  }
  return new Promise((done) => setTimeout(done, 1350));
}

/** Klaxon, then one clip: "Warning. Warning." and the details. Cuts off whatever was being said.
 *  One clip, not two, so a slow or failed second request can't switch to the browser's voice midway. */
export function warn(details: string): void {
  stop();
  enqueue(() =>
    klaxon().catch(() => {
      // No audio context, the words still carry it.
    }),
  );
  speak(`Warning. Warning. ${details}`);
}
