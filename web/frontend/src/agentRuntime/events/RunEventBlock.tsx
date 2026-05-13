import { Activity } from "lucide-react";
import type { DialogueRunEvent } from "../../api/dialogueRuntime";
import { provenanceFromMetadata, provenanceLabel } from "../provenance";

export function RunEventBlock({ event }: { event: DialogueRunEvent }) {
  const label = provenanceLabel(provenanceFromMetadata(event.payload));
  return (
    <article className="agent-block agent-block-run">
      <header>
        <Activity size={16} />
        <strong>{event.title || event.event_type}</strong>
        <span className={`agent-source agent-source-${label.tone}`}>{label.label}</span>
      </header>
      <p>{event.summary || "运行事件已记录。"}</p>
      {label.detail ? <small>{label.detail}</small> : null}
    </article>
  );
}
