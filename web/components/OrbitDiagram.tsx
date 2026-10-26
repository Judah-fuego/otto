// Orbit radii: AU around the Sun, kilometres around Earth for the Moon.
const ORBITS: Record<string, number> = {
  mercury: 0.387, venus: 0.723, mars: 1.524, jupiter: 5.204, saturn: 9.583,
  uranus: 19.218, neptune: 30.11, pluto: 39.482,
};
const LEO_KM = 6678;
const MOON_KM = 384_400;

type Props = { destination: string };

/** Hohmann transfer drawn on a square-root scale so Neptune and Earth fit on one card. */
export function OrbitDiagram({ destination }: Props) {
  const lunar = destination === "moon";
  const r1 = lunar ? LEO_KM : 1;
  const r2 = lunar ? MOON_KM : ORBITS[destination];
  if (!r2) return null;

  const size = 220;
  const c = size / 2;
  const outer = Math.max(r1, r2);
  const scale = (r: number) => (Math.sqrt(r / outer) * (c - 18));

  const a = (r1 + r2) / 2;
  const e = Math.abs(r2 - r1) / (r1 + r2);
  const outward = r2 > r1;
  const transfer = Array.from({ length: 121 }, (_, i) => {
    const th = (i / 120) * Math.PI;
    const r = (a * (1 - e * e)) / (1 + (outward ? e : -e) * Math.cos(th));
    const s = scale(r);
    return `${(c + s * Math.cos(th)).toFixed(1)},${(c - s * Math.sin(th)).toFixed(1)}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="h-[200px] w-[200px] shrink-0">
      <circle cx={c} cy={c} r={lunar ? 5 : 4} fill={lunar ? "var(--color-ground)" : "var(--color-crew)"} opacity={0.9} />
      <circle cx={c} cy={c} r={scale(r1)} fill="none" stroke="var(--color-ground)" strokeOpacity={0.55} strokeDasharray="2 3" />
      <circle cx={c} cy={c} r={scale(r2)} fill="none" stroke="var(--color-dim)" strokeOpacity={0.5} />
      <polyline points={transfer} fill="none" stroke="var(--color-auto)" strokeWidth={1.75} />
      <circle cx={c + scale(r1)} cy={c} r={3.5} fill="var(--color-ground)" />
      <circle cx={c - scale(r2)} cy={c} r={3.5} fill="var(--color-ink)" />
      <text x={c + scale(r1) + 6} y={c + 12} className="fill-dim font-mono" fontSize={9}>{lunar ? "Low Earth orbit" : "Earth"}</text>
      <text x={c - scale(r2) + 6} y={c + 12} className="fill-ink font-mono" fontSize={9}>{destination}</text>
    </svg>
  );
}
