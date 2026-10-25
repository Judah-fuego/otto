export type Authority = "auto" | "ask_crew" | "escalate";
export type Status = "executed" | "escalated" | "awaiting_crew" | "approved" | "rejected";

export type AlertView = {
  alert_id: string;
  time: string;
  channel: string;
  subsystem: string;
  likely_causes: string;
  confidence: number;
  telemetry: {
    baseline_mean: number;
    recent_mean: number;
    shift_in_sigma: number;
    direction: "rising" | "falling";
    last_value: number;
    samples: number;
  };
  proposed_action: string;
  reversible: boolean;
  authority: Authority;
  authority_reason: string;
  values: number[];
  decision: { status: Status; time: string };
  narration: string | null;
  has_figure: boolean;
};

export type LogEntry = {
  time: string;
  kind: "auto" | "crew" | "ground";
  alert_id: string;
  text: string;
};

export type SafeModeStatus = {
  running: boolean;
  note?: string;
  progress?: number | null;
  alerts_emitted?: number;
  alert_source: "queue" | "mock";
  channels?: string[];
};

export type State = {
  now: string;
  safemode: SafeModeStatus;
  alerts: AlertView[];
  log: LogEntry[];
  mission: Trajectory;
  ground_light_delay_s: number;
};

export type Point = [number, number];

export type Trajectory = {
  mission: string;
  origin: string;
  destination: string;
  crew: number;
  phase: "transit" | "arrived";
  launch_utc: string;
  arrival_utc: string;
  mission_day: number;
  transit_days: number;
  days_to_arrival: number;
  progress: number;
  distance_to_earth_km: number;
  one_way_light_delay_min: number;
  orbits_au: { earth: number; destination: number };
  positions_au: { earth: Point; ship: Point; destination: Point };
};

export type Supply = {
  remaining_kg: number;
  remaining_fraction: number;
  days_left_at_current_use: number;
  margin_days_after_arrival: number;
};

export type SystemItem = { subsystem: string; action: string; authority: Authority; status: Status };

export type MissionStatus = {
  overall: "nominal" | "watch" | "action_needed";
  trajectory: Trajectory;
  consumables: Record<string, Supply>;
  systems: { awaiting_crew: SystemItem[]; with_ground: SystemItem[]; crew_declined: SystemItem[]; handled: SystemItem[] };
  safemode_running: boolean;
};

export type VoyageResult = {
  origin: string;
  destination: string;
  delta_v_m_s: number;
  travel_time_days: number;
  propellant_kg: number;
  launch_window_utc: string | null;
  crew: number;
  oxygen_kg: number;
  water_kg: number;
  food_kg: number;
};

export type ToolCall = {
  name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
};

/** `speech` is the short radio-style summary the voice reads instead of `content`. */
export type Message = { role: "user" | "assistant"; content: string; speech?: string; calls?: ToolCall[] };

export type FeedEntry =
  | { kind: "message"; id: string; message: Message }
  | { kind: "alert"; id: string; alertId: string };
