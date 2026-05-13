import type { ReactNode } from "react";

export function RightDrawer({ open, children }: { open: boolean; children: ReactNode }) {
  if (!open) return null;
  return <aside className="agent-right-drawer">{children}</aside>;
}
