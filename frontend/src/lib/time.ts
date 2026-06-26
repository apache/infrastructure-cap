export function secondsRemaining(closesAt: string): number {
  const target = Date.parse(closesAt);
  if (Number.isNaN(target)) return 0;
  return Math.max(0, Math.floor((target - Date.now()) / 1000));
}

export function formatCountdown(totalSeconds: number): string {
  if (totalSeconds <= 0) return "Closed";
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.floor((totalSeconds % 86400) / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function formatCountdownAria(totalSeconds: number): string {
  if (totalSeconds <= 0) return "Closed";
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.floor((totalSeconds % 86400) / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const parts: string[] = [];
  if (d > 0) parts.push(`${d} day${d === 1 ? "" : "s"}`);
  if (h > 0) parts.push(`${h} hour${h === 1 ? "" : "s"}`);
  if (m > 0 && d === 0) parts.push(`${m} minute${m === 1 ? "" : "s"}`);
  if (parts.length === 0) parts.push("less than a minute");
  return `Closes in ${parts.join(" ")}`;
}

export function formatLocal(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // Minute precision is enough for question/response timestamps; seconds
  // only add noise (see issue #26).
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diff = (t - Date.now()) / 1000;
  const abs = Math.abs(diff);
  const sign = diff < 0 ? "ago" : "from now";
  if (abs < 60) return `just now`;
  if (abs < 3600) return `${Math.round(abs / 60)}m ${sign}`;
  if (abs < 86400) return `${Math.round(abs / 3600)}h ${sign}`;
  if (abs < 86400 * 30) return `${Math.round(abs / 86400)}d ${sign}`;
  return new Date(t).toLocaleDateString();
}

// Convert an ISO UTC string to a value suitable for <input type="datetime-local">.
export function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

// Convert a <input type="datetime-local"> value (local time, no zone)
// back to an ISO UTC string the backend will accept.
export function localInputToIso(local: string): string {
  if (!local) return "";
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString();
}
