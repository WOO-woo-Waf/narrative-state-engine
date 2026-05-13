import type { ReactNode } from "react";

export function LeftRail({ children }: { children: ReactNode }) {
  return <aside className="agent-left-rail">{children}</aside>;
}
