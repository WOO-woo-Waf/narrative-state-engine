import { FileText } from "lucide-react";
import type { DialogueArtifact } from "../../api/dialogueRuntime";
import { provenanceFromMetadata, provenanceLabel } from "../provenance";

export function ArtifactBlock({
  artifact,
  onOpen,
  onOpenWorkspace
}: {
  artifact: DialogueArtifact;
  onOpen?: (artifact: DialogueArtifact) => void;
  onOpenWorkspace?: (workspaceId: string, sceneType?: string, artifact?: DialogueArtifact) => void;
}) {
  const payload = artifact.payload || {};
  const label = provenanceLabel(provenanceFromMetadata(payload.provenance && typeof payload.provenance === "object" ? (payload.provenance as Record<string, unknown>) : payload));
  return (
    <article className="agent-block agent-block-artifact">
      <header>
        <FileText size={16} />
        <strong>{artifact.title || artifact.artifact_type}</strong>
        <span className={`agent-source agent-source-${label.tone}`}>{label.label}</span>
      </header>
      <p>{artifact.summary || "Artifact 已生成。"}</p>
      <div className="agent-inline-actions">
        {onOpen ? (
          <button type="button" onClick={() => onOpen(artifact)}>
            打开详情
          </button>
        ) : null}
        {artifact.related_candidate_ids?.length ? (
          <button type="button" onClick={() => onOpenWorkspace?.("candidate-review", "state_maintenance", artifact)}>
            查看候选
          </button>
        ) : null}
        {artifact.related_object_ids?.length || artifact.related_transition_ids?.length ? (
          <button type="button" onClick={() => onOpenWorkspace?.("graph", undefined, artifact)}>
            打开图谱
          </button>
        ) : null}
        {artifact.related_branch_ids?.length || artifact.artifact_type === "continuation_branch" ? (
          <button type="button" onClick={() => onOpenWorkspace?.("branch-review", "branch_review", artifact)}>
            打开分支
          </button>
        ) : null}
      </div>
    </article>
  );
}
