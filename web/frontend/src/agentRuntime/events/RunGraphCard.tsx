import { useState } from "react";
import type { DialogueArtifact, DialogueRunEvent } from "../../api/dialogueRuntime";
import { provenanceFromMetadata, provenanceLabel } from "../provenance";

export function RunGraphCard({ events, artifacts }: { events: DialogueRunEvent[]; artifacts: DialogueArtifact[] }) {
  const grouped = groupByRun(events);
  const [expandedRunId, setExpandedRunId] = useState("");
  if (!grouped.length) return null;
  return (
    <section className="agent-run-graph">
      {grouped.map((group) => {
        const first = group.events[0];
        const provenance = provenanceFromMetadata(first?.payload);
        const label = provenanceLabel(provenance);
        return (
          <article className="agent-run-card" key={group.runId}>
            <header>
              <strong>{first?.title || "运行"}</strong>
              <span className={`agent-source agent-source-${label.tone}`}>{label.label}</span>
            </header>
            <div className="agent-run-meta">
              <span>{group.events.length} 个事件</span>
              <span>{artifacts.length} 个 artifact</span>
              <span>{provenance.model_name || "模型未声明"}</span>
            </div>
            {provenance.fallback_reason ? <p>{provenance.fallback_reason}</p> : null}
            <button className="agent-run-detail-button" type="button" onClick={() => setExpandedRunId(expandedRunId === group.runId ? "" : group.runId)}>
              {expandedRunId === group.runId ? "收起详情" : "打开详情"}
            </button>
            {expandedRunId === group.runId ? (
              <ol className="agent-run-detail-list">
                {group.events.map((event) => (
                  <li key={event.event_id}>
                    <strong>{event.title || event.event_type}</strong>
                    <span>{event.summary || event.event_type}</span>
                  </li>
                ))}
              </ol>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}

function groupByRun(events: DialogueRunEvent[]) {
  const groups = new Map<string, DialogueRunEvent[]>();
  events.forEach((event) => {
    const key = event.run_id || event.event_id;
    groups.set(key, [...(groups.get(key) || []), event]);
  });
  return Array.from(groups.entries()).map(([runId, items]) => ({ runId, events: items }));
}
