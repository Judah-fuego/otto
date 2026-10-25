export function clock(iso: string): string {
  return iso.slice(11, 19) + "Z";
}

export function mass(kg: number): string {
  if (kg >= 1_000_000) return `${(kg / 1_000_000).toFixed(2)} kt`;
  if (kg >= 1_000) return `${(kg / 1_000).toFixed(1)} t`;
  return `${kg.toFixed(0)} kg`;
}

export function duration(days: number): string {
  if (days < 60) return `${days.toFixed(1)} d`;
  if (days < 730) return `${Math.round(days)} d`;
  return `${(days / 365.25).toFixed(1)} yr`;
}

export function countdown(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
