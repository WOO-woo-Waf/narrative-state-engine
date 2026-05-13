import { JsonPreview } from "../../components/data/JsonPreview";
import type { StateEnvironment } from "../../types/environment";
import { formatContextBudget } from "../../types/environment";

export function GenerationContextInspector({ environment }: { environment?: StateEnvironment }) {
  if (!environment) return <div className="empty-state">暂无上下文。</div>;
  const sections = environment.context_sections || {};
  return (
    <div className="stack">
      <section className="detail-card">
        <h3>上下文检查</h3>
        <div className="key-value-list">
          <div>
            <span>已选对象</span>
            <strong>{environment.selected_object_ids.length}</strong>
          </div>
          <div>
            <span>已选候选</span>
            <strong>{environment.selected_candidate_ids.length}</strong>
          </div>
          <div>
            <span>已选证据</span>
            <strong>{environment.selected_evidence_ids.length}</strong>
          </div>
          <div>
            <span>上下文预算</span>
            <strong>{formatContextBudget(environment.context_budget)}</strong>
          </div>
        </div>
      </section>
      <JsonPreview title="上下文分区" value={sections} collapsed={false} />
      <JsonPreview title="检索与压缩策略" value={{ retrieval_policy: environment.retrieval_policy, compression_policy: environment.compression_policy }} />
    </div>
  );
}
