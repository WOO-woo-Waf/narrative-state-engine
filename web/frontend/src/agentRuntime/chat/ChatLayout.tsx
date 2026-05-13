import type { ReactNode } from "react";

export function ChatLayout({ children }: { children: ReactNode }) {
  return <div className="agent-chat-layout">{children}</div>;
}
