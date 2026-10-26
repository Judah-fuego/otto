export type Authority = "auto" | "ask_crew" | "escalate";
export type Status = "executed" | "escalated" | "awaiting_crew" | "approved" | "rejected" | "timed_out";

export type AlertView = {
  alert_id: string;
  time: string;
  channel: string;
  subsystem: string;
  subsystem_key: string;
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
  /** Which crew procedure the console runs. Only crew decisions have one. */
  procedure: string | null;
  checklist: string[];
  if_not_done: string;
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
  missions: MissionChoice[];
  flight: Flight | null;
  ground_light_delay_s: number;
};

/** One row in the mission catalog. Selecting it sets the ship and the path. */
export type MissionChoice = {
  id: string;
  name: string;
  group: "flown" | "mars" | "jupiter" | "expedition";
  blurb: string;
  site: string;
  crew_names: string;
  year: number;
  origin: string;
  destination: string;
  crew: number;
  spacecraft_mass_kg: number;
  isp_s: number;
  launch_utc: string;
};

/** A sped-up run of the mission. `days_per_s` is 0 while paused, finished, or holding for the crew. */
export type Flight = {
  paused: boolean;
  finished: boolean;
  speed: number;
  speeds: number[];
  elapsed_days: number;
  transit_days: number;
  progress: number;
  days_per_s: number;
  hold_alert_id: string | null;
  decision_limit_s: number;
  /** Seconds left on the open crew decision. Running out loses the mission; pausing does not stop it. */
  decision_left_s: number | null;
  failed: { alert_id: string; text: string } | null;
  caution: { channel: string; text: string; in_days: number } | null;
  /** `response_s` is how long the crew took on a decision that held the ship. */
  events: { day: number; progress: number; alert_id: string; response_s: number | null }[];
  remaining_events: number;
  total_events: number;
};

export type Point = [number, number];

export type Trajectory = {
  id: string;
  mission: string;
  site: string;
  origin: string;
  destination: string;
  crew: number;
  spacecraft_mass_kg: number;
  isp_s: number;
  /** `earth` is a lunar transfer drawn around Earth. `sun` is a transfer between orbits. */
  frame: "sun" | "earth";
  /** `ready` means the ship is staged at departure until the crew launches. */
  phase: "ready" | "transit" | "arrived";
  launch_utc: string;
  arrival_utc: string;
  mission_day: number;
  transit_days: number;
  days_to_arrival: number;
  progress: number;
  distance_to_earth_km: number;
  one_way_light_delay_s: number;
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

/** `speech` is the short radio-style summary the voice reads instead of `content`. `live` means a headset call is still saying it. */
export type Message = { role: "user" | "assistant"; content: string; speech?: string; calls?: ToolCall[]; live?: boolean };

export type FeedEntry =
  | { kind: "message"; id: string; message: Message }
  | { kind: "alert"; id: string; alertId: string };
