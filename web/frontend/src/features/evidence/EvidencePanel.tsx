import { Virtuoso } from "react-virtuoso";
import { StatusPill } from "../../components/data/StatusPill";
import type { EvidenceLink } from "../../types/state";
import { sourceRoleLabel } from "../../utils/labels";

export function EvidencePanel({ evidence }: { evidence: EvidenceLink[] }) {
  if (!evidence.length) return <div className="empty-state">暂无证据，或当前选择没有关联证据。</div>;
  return (
    <div className="virtual-list evidence-list">
      <Virtuoso
        data={evidence}
        itemContent={(_, item) => (
          <article className="list-card">
            <header>
              <strong>{item.evidence_id}</strong>
              <StatusPill value={item.evidence_type || item.support_type} />
            </header>
            <p>{item.quote_text || "暂无摘录文本。"}</p>
            <div className="pill-row">
              <StatusPill value={sourceRoleLabel(String(item.source_role || item.metadata?.source_role || ""))} tone="info" />
              <StatusPill value={item.field_path || "对象"} />
              <StatusPill value={`${Math.round(Number(item.confidence ?? item.score ?? 0) * 100)}%`} tone="good" />
            </div>
          </article>
        )}
      />
    </div>
  );
}
