import { Check, Eye } from "lucide-react";
import type { PlotPlanArtifact, RuntimeSelection } from "../types";

export function PlotPlanPicker({
  plans,
  selection,
  fallback,
  onSelectionChange
}: {
  plans: PlotPlanArtifact[];
  selection: RuntimeSelection;
  fallback?: string;
  onSelectionChange: (selection: Partial<RuntimeSelection>) => void;
}) {
  const selected = selection.selectedArtifacts?.plot_plan_artifact_id || selection.selectedArtifacts?.plot_plan_id;
  const selectedPlan = plans.find((plan) => plan.artifact_id === selected || plan.plot_plan_id === selected);
  return (
    <section className="plot-plan-picker">
      <header>
        <div>
          <strong>剧情规划</strong>
          <span>当前使用：{selectedPlan?.plot_plan_id || selectedPlan?.artifact_id || "未绑定"}</span>
        </div>
        <span className="agent-source agent-source-info">可用规划 {plans.length}</span>
      </header>
      {fallback ? <p className="muted-text">后端接口暂缺，无法加载 story/task 级剧情规划。</p> : null}
      {!plans.length ? <p className="muted-text">需要先确认剧情规划，续写草案会保持执行保护。</p> : null}
      <div className="plot-plan-list">
        {plans.slice(0, 6).map((plan) => {
          const active = plan.artifact_id === selected || plan.plot_plan_id === selected;
          return (
            <article key={plan.artifact_id} className={active ? "active" : ""}>
              <div>
                <strong>{plan.plot_plan_id || plan.artifact_id}</strong>
                <span>{plan.title}</span>
                <small>
                  {authorityLabel(plan.authority)} / {statusLabel(plan.status)}
                </small>
              </div>
              <div className="agent-inline-actions">
                <button type="button" onClick={() => onSelectionChange({ selectedArtifacts: { ...selection.selectedArtifacts, plot_plan_id: plan.plot_plan_id, plot_plan_artifact_id: plan.artifact_id } })}>
                  <Check size={15} />
                  使用此规划
                </button>
                <details>
                  <summary>
                    <Eye size={15} />
                    查看元数据
                  </summary>
                  <pre className="agent-json">{JSON.stringify({ artifact_id: plan.artifact_id, plot_plan_id: plan.plot_plan_id, status: plan.status, authority: plan.authority, metadata: plan.metadata }, null, 2)}</pre>
                </details>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function authorityLabel(value?: string): string {
  if (value === "author_confirmed" || value === "confirmed") return "作者已确认";
  if (value === "model_generated" || value === "proposed") return "模型草案";
  if (value === "system_generated" || value === "completed") return "系统执行产物";
  if (value === "superseded") return "已被替代";
  return value || "来源待补齐";
}

export function statusLabel(value?: string): string {
  if (value === "author_confirmed" || value === "confirmed") return "作者已确认";
  if (value === "model_generated" || value === "proposed") return "模型草案";
  if (value === "system_generated" || value === "completed") return "已完成";
  if (value === "superseded") return "已被替代";
  return value || "状态待补齐";
}

