import type { DialogueMessage } from "../../types/dialogue";
import { MessageBubble } from "./MessageBubble";

export function AssistantMessage({ message }: { message: DialogueMessage }) {
  return <MessageBubble message={{ ...message, role: "assistant" }} />;
}
