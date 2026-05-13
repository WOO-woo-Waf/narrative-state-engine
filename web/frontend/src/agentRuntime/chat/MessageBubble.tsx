import type { DialogueMessage } from "../../types/dialogue";
import { provenanceFromMetadata, provenanceLabel } from "../provenance";

export function MessageBubble({ message }: { message: DialogueMessage }) {
  const label = provenanceLabel(provenanceFromMetadata(message.metadata));
  const isUser = message.role === "user";
  return (
    <article className={`agent-message ${isUser ? "agent-message-user" : "agent-message-assistant"}`}>
      <header>
        <strong>{isUser ? "你" : "Agent"}</strong>
        {!isUser ? <span className={`agent-source agent-source-${label.tone}`}>{label.label}</span> : null}
      </header>
      <p>{message.content}</p>
      {!isUser && label.detail ? <small>{label.detail}</small> : null}
    </article>
  );
}
