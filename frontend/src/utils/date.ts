/** The API returns naive UTC timestamps (no zone suffix); treat them as UTC when displaying. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  const date = new Date(hasZone ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}
