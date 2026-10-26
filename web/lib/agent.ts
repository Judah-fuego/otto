// Live Grok Voice call. The mic streams PCM to xAI; Otto talks back on the same socket.
// Tool calls come back here, run on our API, and the console draws the same cards as typed chat.

import { api } from "./api";
import type { ToolCall } from "./types";

const RATE = 24000;

export type Reply = { text: string; calls: ToolCall[]; final: boolean };

export type AgentHandlers = {
  onUser: (text: string) => void;
  onReply: (reply: Reply) => void;
  onLevel: (level: number) => void;
  onError: (message: string) => void;
  onStatus: (status: "listening" | "closed") => void;
};

export type Agent = {
  sendText: (text: string) => void;
  /** Speak a console event without adding a crew line. */
  notify: (text: string) => void;
  hangup: () => void;
};

export async function connectAgent(handlers: AgentHandlers): Promise<Agent> {
  const session = await api.voiceSession();
  const ws = new WebSocket(session.realtime_url, [`xai-client-secret.${session.value}`]);
  let closed = false;
  await new Promise<void>((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error("Voice call failed. Check the xAI key and the network."));
  });
  ws.onerror = () => {
    if (!closed) handlers.onError("Voice call dropped.");
  };

  let audio: AudioContext;
  try {
    audio = new AudioContext({ sampleRate: RATE });
  } catch {
    audio = new AudioContext();
  }
  if (audio.state === "suspended") await audio.resume();
  ws.send(JSON.stringify({ type: "session.update", session: session.session }));

  let capturing = false;
  let responseOpen = false;
  let waitingTools = 0;
  let continueQueued = false;
  let awaitingNext = false;
  let settled = false;
  let draft = "";
  let calls: ToolCall[] = [];
  let playAt = 0;
  const playing: AudioBufferSourceNode[] = [];
  let processor: ScriptProcessorNode | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let stream: MediaStream | null = null;

  const stopPlayback = () => {
    for (const node of playing) {
      try {
        node.stop();
      } catch {
        /* already stopped */
      }
    }
    playing.length = 0;
    playAt = audio.currentTime;
  };

  const cleanupMic = () => {
    capturing = false;
    processor?.disconnect();
    source?.disconnect();
    stream?.getTracks().forEach((track) => track.stop());
    processor = null;
    source = null;
    stream = null;
  };

  const hangup = () => {
    if (closed) return;
    closed = true;
    cleanupMic();
    stopPlayback();
    ws.onmessage = null;
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
    void audio.close();
  };

  const emit = (final: boolean) => {
    if (settled) return;
    if (!draft && calls.length === 0) {
      if (final) settled = true;
      return;
    }
    handlers.onReply({ text: draft, calls: [...calls], final });
    if (final) {
      settled = true;
      draft = "";
      calls = [];
    }
  };

  const maybeContinue = () => {
    if (closed || responseOpen || waitingTools > 0 || !continueQueued) return;
    continueQueued = false;
    awaitingNext = true;
    ws.send(JSON.stringify({ type: "response.create" }));
  };

  const maybeFinish = () => {
    if (responseOpen || waitingTools > 0 || continueQueued || awaitingNext) return;
    emit(true);
  };

  const pushText = (text: string) => {
    if (closed || ws.readyState !== WebSocket.OPEN) throw new Error("Voice call is down.");
    if (responseOpen) {
      ws.send(JSON.stringify({ type: "response.cancel" }));
      stopPlayback();
      responseOpen = false;
      emit(true);
    }
    ws.send(
      JSON.stringify({
        type: "conversation.item.create",
        item: { type: "message", role: "user", content: [{ type: "input_text", text }] },
      }),
    );
    ws.send(JSON.stringify({ type: "response.create" }));
  };

  const playPcm16 = async (b64: string) => {
    const bytes = b64ToBytes(b64);
    const samples = Math.floor(bytes.length / 2);
    if (!samples || closed) return;
    const buf = audio.createBuffer(1, samples, RATE);
    const ch = buf.getChannelData(0);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let i = 0; i < samples; i++) ch[i] = view.getInt16(i * 2, true) / 0x8000;
    const node = audio.createBufferSource();
    node.buffer = buf;
    node.connect(audio.destination);
    const start = Math.max(playAt, audio.currentTime);
    node.start(start);
    playAt = start + buf.duration;
    playing.push(node);
    node.onended = () => {
      const i = playing.indexOf(node);
      if (i >= 0) playing.splice(i, 1);
    };
  };

  const handleFunctionCall = async (event: { name?: string; call_id?: string; arguments?: unknown }) => {
    waitingTools += 1;
    continueQueued = true;
    let args: Record<string, unknown> = {};
    try {
      if (typeof event.arguments === "string") args = event.arguments ? JSON.parse(event.arguments) : {};
      else if (event.arguments && typeof event.arguments === "object") args = event.arguments as Record<string, unknown>;
    } catch {
      args = {};
    }
    const name = event.name || "tool";
    let result: Record<string, unknown>;
    try {
      result = await api.voiceTool(name, args);
    } catch (err) {
      result = { error: (err as Error).message };
    }
    calls = [...calls, { name, arguments: args, result }];
    emit(false);
    if (!closed && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "conversation.item.create",
          item: { type: "function_call_output", call_id: event.call_id, output: JSON.stringify(result) },
        }),
      );
    }
    waitingTools -= 1;
    maybeContinue();
    maybeFinish();
  };

  ws.onmessage = (raw) => {
    if (closed) return;
    const event = JSON.parse(raw.data as string);
    if (event.type === "response.created") {
      responseOpen = true;
      awaitingNext = false;
      settled = false;
    } else if (event.type === "response.done") {
      responseOpen = false;
      maybeContinue();
      maybeFinish();
    } else if (event.type === "response.function_call_arguments.done") {
      void handleFunctionCall(event);
    } else if (event.type === "response.output_audio.delta" || event.type === "response.audio.delta") {
      if (event.delta) void playPcm16(event.delta);
    } else if (event.type === "response.output_audio_transcript.delta") {
      draft += event.delta || "";
      emit(false);
    } else if (event.type === "response.output_audio_transcript.done") {
      if (!draft && event.transcript) draft = event.transcript;
      emit(false);
    } else if (event.type === "conversation.item.input_audio_transcription.completed") {
      if (event.transcript) handlers.onUser(event.transcript);
    } else if (event.type === "input_audio_buffer.speech_started") {
      stopPlayback();
    } else if (event.type === "error") {
      handlers.onError(event.error?.message || "Voice agent error");
    }
  };

  ws.onclose = () => {
    if (closed) return;
    closed = true;
    cleanupMic();
    stopPlayback();
    void audio.close();
    handlers.onStatus("closed");
  };

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    hangup();
    throw err;
  }

  source = audio.createMediaStreamSource(stream);
  processor = audio.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = (ev) => {
    if (!capturing || closed || ws.readyState !== WebSocket.OPEN) return;
    const input = ev.inputBuffer.getChannelData(0);
    let sum = 0;
    for (const x of input) sum += x * x;
    handlers.onLevel(Math.sqrt(sum / input.length));
    const resampled = resample(input, audio.sampleRate, RATE);
    const pcm = floatTo16(resampled);
    ws.send(
      JSON.stringify({
        type: "input_audio_buffer.append",
        audio: bytesToB64(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)),
      }),
    );
  };
  source.connect(processor);
  const mute = audio.createGain();
  mute.gain.value = 0;
  processor.connect(mute);
  mute.connect(audio.destination);
  capturing = true;
  handlers.onStatus("listening");

  return { sendText: pushText, notify: pushText, hangup };
}

function floatTo16(float32: Float32Array): Int16Array {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) out[i] = input[Math.floor(i * ratio)];
  return out;
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function bytesToB64(bytes: Uint8Array): string {
  let s = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    s += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + chunk)));
  }
  return btoa(s);
}
