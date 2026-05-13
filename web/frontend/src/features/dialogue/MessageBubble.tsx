import clsx from "clsx";
import type { DialogueMessage } from "../../types/dialogue";

export function MessageBubble({ message }: { message: DialogueMessage }) {
  return (
    <article className={clsx("message-bubble", `message-${message.role}`)}>
      <header>
        <strong>{roleLabel(message.role)}</strong>
        <span>{message.created_at ? new Date(message.created_at).toLocaleString() : ""}</span>
      </header>
      <p>{message.content}</p>
    </article>
  );
}

function roleLabel(role: string) {
  if (role === "assistant") return "模型";
  if (role === "user") return "作者";
  if (role === "system") return "系统";
  return role;
}
