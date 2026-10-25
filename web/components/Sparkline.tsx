type Props = { values: number[]; color: string; height?: number };

/** Telemetry trace. The last quarter, where SafeMode judged the shift, is drawn brighter. */
export function Sparkline({ values, color, height = 72 }: Props) {
  const width = 320;
  const pad = 4;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / Math.max(1, values.length - 1)) * (width - 2 * pad);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - 2 * pad);
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const split = Math.max(1, Math.floor(values.length * 0.75));
  const last = values.length - 1;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <rect x={x(split)} y={0} width={width - x(split)} height={height} fill={color} opacity={0.06} />
      <line x1={x(split)} x2={x(split)} y1={0} y2={height} stroke={color} strokeOpacity={0.25} strokeDasharray="2 3" />
      <polyline points={points.slice(0, split + 1).join(" ")} fill="none" stroke="var(--color-dim)" strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
      <polyline points={points.slice(split).join(" ")} fill="none" stroke={color} strokeWidth={1.75} vectorEffect="non-scaling-stroke" />
      <circle cx={x(last)} cy={y(values[last])} r={2.5} fill={color} />
    </svg>
  );
}
