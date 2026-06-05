export function formatUSD(v: number, opts?: { compact?: boolean }): string {
  if (!Number.isFinite(v)) return "—";
  if (opts?.compact && Math.abs(v) >= 1000) {
    return v.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: 1,
    });
  }
  return v.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Price formatting that keeps small-cap crypto prices legible. */
export function formatPrice(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const digits = abs >= 1 ? 2 : abs >= 0.01 ? 4 : 8;
  return v.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  });
}

export function formatPct(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

export function formatQty(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const digits = abs >= 1 ? 4 : 8;
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function formatDateTime(ts: string | number | Date): string {
  return new Date(ts).toLocaleString();
}

export function formatDate(ts: string | number | Date): string {
  return new Date(ts).toLocaleDateString();
}

/** Compact relative time, e.g. "3m ago", "2h ago", "5d ago". */
export function formatTimeAgo(ts: string | number | Date): string {
  const then = new Date(ts).getTime();
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

const STATUS_LABEL: Record<string, string> = {
  live: "live",
  last_close: "at last close",
  stale_unlisted: "stale / unlisted",
  unpriced: "unpriced",
};

export function priceStatusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** Whether a price_status represents a data problem (vs. a normal value). */
export function isProblemStatus(status: string): boolean {
  return status === "stale_unlisted" || status === "unpriced";
}
