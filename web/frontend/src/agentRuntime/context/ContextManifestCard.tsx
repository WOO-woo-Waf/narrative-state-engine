import type { ContextManifest } from "../types";
import { authorityLabel, statusLabel } from "../artifacts/WorkspaceArtifactPicker";

export function ContextManifestCard({ manifest, contextModeLabel }: { manifest?: ContextManifest; contextModeLabel?: string }) {
  if (!manifest || !manifest.available) {
    return (
      <section className="context-manifest-card">
        <header>
          <strong>当前上下文：{contextModeLabel || manifest?.context_mode || "未选择"}</strong>
          <span className="agent-source agent-source-neutral">上下文包暂不可见</span>
        </header>
        <p>{manifest?.unavailableReason || "上下文包暂不可见"}</p>
      </section>
    );
  }
  return (
    <section className="context-manifest-card">
      <header>
        <strong>当前上下文：{contextModeLabel || manifest.context_mode || "未选择"}</strong>
        <span className="agent-source agent-source-info">已装配</span>
      </header>
      <p>{manifest.summary || buildSummary(manifest)}</p>
      {manifest.handoff ? (
        <div className="handoff-summary">
          <strong>任务接力</strong>
          <span>剧情规划：{manifest.handoff.selected_artifacts.plot_plan_id || manifest.handoff.selected_artifacts.plot_plan_artifact_id || "未绑定"}</span>
          {manifest.handoff.available_artifacts.plot_plan?.length > 1 ? <span>存在 {manifest.handoff.available_artifacts.plot_plan.length} 个剧情规划，请确认当前使用项。</span> : null}
          {!manifest.handoff.selected_artifacts.plot_plan_id && !manifest.handoff.selected_artifacts.plot_plan_artifact_id ? <span>需要先确认剧情规划</span> : null}
        </div>
      ) : null}
      <details>
        <summary>查看上下文包</summary>
        <dl className="agent-context-list">
          <ContextRow label="状态版本" value={manifest.state_version_no === undefined ? "-" : String(manifest.state_version_no)} />
          <ContextRow label="Token 预算" value={budgetText(manifest)} />
          <ContextRow label="已纳入产物" value={manifest.included_artifacts.map((item) => item.title).join("，") || "-"} />
          <ContextRow label="已排除产物" value={manifest.excluded_artifacts.map((item) => `${item.title}${item.reason ? `：${item.reason}` : ""}`).join("，") || "-"} />
          <ContextRow label="证据" value={manifest.selected_evidence.map((item) => item.title || item.quote || item.id).join("，") || "-"} />
          <ContextRow label="警告" value={manifest.warnings.join("；") || "-"} />
          {manifest.handoff ? <ContextRow label="可用剧情规划" value={manifest.handoff.available_artifacts.plot_plan?.map((item) => `${item.plot_plan_id || item.artifact_id}（${authorityLabel(item.authority)} / ${statusLabel(item.status)}）`).join("，") || "-"} /> : null}
        </dl>
      </details>
    </section>
  );
}

function buildSummary(manifest: ContextManifest): string {
  const parts = [
    manifest.state_version_no !== undefined ? `当前状态版本 ${manifest.state_version_no}` : "",
    manifest.included_artifacts.length ? `已确认产物 ${manifest.included_artifacts.length} 条` : "",
    manifest.selected_evidence.length ? `相关证据 ${manifest.selected_evidence.length} 条` : "",
    manifest.warnings.length ? `警告 ${manifest.warnings.length} 条` : ""
  ].filter(Boolean);
  return parts.length ? `已装配：${parts.join("、")}` : "上下文包已生成，但后端未返回详细条目。";
}

function budgetText(manifest: ContextManifest): string {
  if (!manifest.token_budget && !manifest.token_estimate) return "-";
  if (manifest.token_budget && manifest.token_estimate) return `${manifest.token_estimate} / ${manifest.token_budget}`;
  return String(manifest.token_estimate || manifest.token_budget);
}

function ContextRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
