import clsx from "clsx";

export function StatusPill({ value, tone }: { value?: string | number | boolean | null; tone?: "good" | "warn" | "bad" | "info" }) {
  const text = String(value ?? "unknown");
  const computed =
    tone ||
    (["succeeded", "ok", "active", "accepted", "canonical", "author_locked", "true"].includes(text) ? "good" : undefined) ||
    (["failed", "error", "critical", "rejected", "false"].includes(text) ? "bad" : undefined) ||
    (["running", "pending_review", "candidate", "high", "medium", "queued"].includes(text) ? "warn" : "info");
  return <span className={clsx("status-pill", `status-${computed}`)}>{text}</span>;
}
