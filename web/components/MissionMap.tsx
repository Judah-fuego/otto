import type { Point, Trajectory } from "@/lib/types";
import { titleCase } from "@/lib/format";

type Props = { t: Trajectory; size?: number };

type Label = { text: string; at: Point; className: string; fontSize: number };
type Placed = { x: number; y: number; anchor: "start" | "middle" | "end"; label: Label };

const DIRECTIONS: Point[] = Array.from({ length: 12 }, (_, i) => [Math.cos((i * Math.PI) / 6), Math.sin((i * Math.PI) / 6)]);

/** Put each label on the side of its marker farthest from every other marker and label. */
function place(labels: Label[], markers: Point[], size: number): Placed[] {
  const placed: Placed[] = [];
  const centers: Point[] = [];
  for (const label of labels) {
    const w = label.text.length * label.fontSize * 0.62;
    let best: { score: number; p: Placed; center: Point } | null = null;
    for (const [dx, dy] of DIRECTIONS) {
      const x = label.at[0] + dx * 9;
      const y = label.at[1] + dy * 9 + label.fontSize * 0.35;
      const anchor = dx > 0.3 ? "start" : dx < -0.3 ? "end" : "middle";
      const cx = anchor === "start" ? x + w / 2 : anchor === "end" ? x - w / 2 : x;
      const center: Point = [cx, y - label.fontSize * 0.35];
      const inside = cx - w / 2 > 2 && cx + w / 2 < size - 2 && center[1] > 8 && center[1] < size - 4;
      const others = [...markers.filter((m) => m !== label.at), ...centers];
      const clearance = Math.min(...others.map((o) => Math.hypot((o[0] - center[0]) / (w / 2 + 6), (o[1] - center[1]) / 9)));
      const score = clearance - (inside ? 0 : 100);
      if (!best || score > best.score) best = { score, p: { x, y, anchor, label }, center };
    }
    placed.push(best!.p);
    centers.push(best!.center);
  }
  return placed;
}

/** The transfer flown so far, the ship, and the line home. Lunar trips are drawn around Earth. */
export function MissionMap({ t, size = 240 }: Props) {
  const c = size / 2;
  const r1 = t.orbits_au.earth;
  const r2 = t.orbits_au.destination;
  const lunar = t.frame === "earth";
  const outer = Math.max(r1, r2);
  // A lunar Hohmann is so eccentric that a linear scale hides the whole coast on top of Earth.
  // Square-root radius keeps the Moon orbit round and lets the path leave the parking orbit.
  const reach = c - 22;
  const radial = (r: number) => (lunar ? Math.sqrt(Math.max(r, 0) / outer) : r / outer) * reach;
  const xy = ([x, y]: Point): Point => {
    const r = Math.hypot(x, y);
    const s = radial(r);
    if (s === 0) return [c, c];
    return [c + (s * x) / r, c - (s * y) / r];
  };
  const homeAtCenter = Math.hypot(t.positions_au.earth[0], t.positions_au.earth[1]) < 1e-8;

  const a = (r1 + r2) / 2;
  const e = (r2 - r1) / (r2 + r1);
  const [sx, sy] = t.positions_au.ship;
  // The transfer runs 0 to π. Arrival can round to -π.
  const raw = Math.atan2(sy, sx);
  const shipAngle = raw < 0 ? Math.PI : raw;
  const arc = (from: number, to: number) =>
    Array.from({ length: 61 }, (_, i) => {
      const th = from + ((to - from) * i) / 60;
      const r = (a * (1 - e * e)) / (1 + e * Math.cos(th));
      const [px, py] = xy([r * Math.cos(th), r * Math.sin(th)]);
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    }).join(" ");

  const ship = xy(t.positions_au.ship);
  const earth = xy(t.positions_au.earth);
  const dest = xy(t.positions_au.destination);
  const shipOnEarth = Math.hypot(ship[0] - earth[0], ship[1] - earth[1]) < 26;
  const labels = place(
    [
      ...(shipOnEarth ? [] : [{ text: t.mission, at: ship, className: "fill-ink", fontSize: 10 }]),
      { text: "Earth", at: earth, className: "fill-dim", fontSize: 9 },
      { text: titleCase(t.destination), at: dest, className: "fill-dim", fontSize: 9 },
    ],
    [ship, earth, dest, [c, c]],
    size,
  );

  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }} className="shrink-0" role="img"
      aria-label={`${t.mission} is ${Math.round(t.progress * 100)}% of the way to ${t.destination}`}>
      <circle cx={c} cy={c} r={radial(r1)} fill="none" stroke="var(--color-ground)" strokeOpacity={0.35} strokeDasharray="2 3" />
      <circle cx={c} cy={c} r={radial(r2)} fill="none" stroke="var(--color-dim)" strokeOpacity={0.35} />
      <circle cx={c} cy={c} r={5} fill={t.frame === "earth" ? "var(--color-ground)" : "var(--color-crew)"} />

      <polyline points={arc(shipAngle, Math.PI)} fill="none" stroke="var(--color-auto)" strokeOpacity={0.45} strokeWidth={1.25} strokeDasharray="3 3" />
      <polyline points={arc(0, shipAngle)} fill="none" stroke="var(--color-auto)" strokeWidth={2} />

      <line x1={ship[0]} y1={ship[1]} x2={earth[0]} y2={earth[1]} stroke="var(--color-ground)" strokeOpacity={0.6} strokeDasharray="1 3" />

      {!homeAtCenter && <circle cx={earth[0]} cy={earth[1]} r={4} fill="var(--color-ground)" />}
      <circle cx={dest[0]} cy={dest[1]} r={4} fill="var(--color-alarm)" fillOpacity={0.8} />
      <circle cx={ship[0]} cy={ship[1]} r={9} fill="var(--color-auto)" fillOpacity={0.18} className="heartbeat" style={{ transformOrigin: `${ship[0]}px ${ship[1]}px` }} />
      <circle cx={ship[0]} cy={ship[1]} r={3.5} fill="var(--color-ink)" />

      {labels.map(({ x, y, anchor, label }) => (
        <text key={label.text} x={x} y={y} textAnchor={anchor} className={`${label.className} font-mono`} fontSize={label.fontSize}>
          {label.text}
        </text>
      ))}
    </svg>
  );
}
