import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { JsonPreview } from "../../components/data/JsonPreview";
import { Metric } from "../../components/data/Metric";
import { StatusPill } from "../../components/data/StatusPill";
import type { StateEnvironment } from "../../types/environment";
import { formatContextBudget, formatVersion } from "../../types/environment";
import { databaseLabel, sceneLabel, statusLabel } from "../../utils/labels";

export function StateEnvironmentPanel({ environment }: { environment?: StateEnvironment }) {
  if (!environment) return <div className="empty-state">请选择小说、任务和场景后加载状态环境。</div>;
  const summary = environment.summary || {};
  const database = (summary.database || {}) as { ok?: boolean; message?: string };
  const pending = Number(summary.pending_candidate_count ?? summary.pending ?? countCandidates(environment, "pending_review"));
  const accepted = Number(summary.accepted_candidate_count ?? summary.accepted ?? countCandidates(environment, "accepted"));
  const rejected = Number(summary.rejected_candidate_count ?? summary.rejected ?? countCandidates(environment, "rejected"));
  const conflicted = Number(summary.conflicted_candidate_count ?? summary.conflicted ?? countCandidates(environment, "conflicted"));
  return (
    <div className="stack environment-readable">
      <details open className="fold-section">
        <summary>状态总览</summary>
        <div className="metric-grid">
          <Metric label="状态对象" value={String(summary.state_object_count ?? environment.state_objects.length ?? "?")} />
          <Metric label="候选项" value={String(summary.candidate_item_count ?? environment.candidate_items.length ?? "?")} tone="warn" />
          <Metric label="分支" value={String(summary.branch_count ?? environment.branches.length ?? "?")} />
          <Metric label="上下文预算" value={formatContextBudget(environment.context_budget)} />
        </div>
        <section className="key-value-list">
          <div>
            <span>数据库</span>
            <StatusPill value={databaseLabel(database.ok)} tone={database.ok ? "good" : "warn"} />
          </div>
          <div>
            <span>小说编号 story_id</span>
            <strong>{environment.story_id}</strong>
          </div>
          <div>
            <span>任务编号 task_id</span>
            <strong>{environment.task_id}</strong>
          </div>
          <div>
            <span>场景</span>
            <StatusPill value={sceneLabel(environment.scene_type)} tone="info" />
          </div>
          <div>
            <span>基线版本</span>
            <strong>{formatVersion(environment.base_state_version_no)}</strong>
          </div>
          <div>
            <span>工作版本</span>
            <strong>{formatVersion(environment.working_state_version_no)}</strong>
          </div>
          <div>
            <span>对话会话</span>
            <strong>{environment.dialogue_session_id || "待创建"}</strong>
          </div>
        </section>
      </details>
      <details open className="fold-section">
        <summary>候选统计</summary>
        <div className="metric-grid">
          <Metric label="待审计" value={String(pending)} tone={pending ? "warn" : "good"} />
          <Metric label="已接受" value={String(accepted)} tone="good" />
          <Metric label="已拒绝" value={String(rejected)} />
          <Metric label="有冲突" value={String(conflicted)} tone={conflicted ? "warn" : undefined} />
        </div>
      </details>
      <details open className="fold-section">
        <summary>警告与冲突</summary>
        <section className="notice-list">
          {environment.warnings.length ? (
            environment.warnings.map((warning) => (
              <div className="notice notice-warn" key={warning}>
                <AlertTriangle size={16} />
                <span>{warning}</span>
              </div>
            ))
          ) : (
            <div className="notice notice-good">
              <CheckCircle2 size={16} />
              <span>暂无环境警告。</span>
            </div>
          )}
        </section>
      </details>
      <details className="fold-section">
        <summary>上下文分区</summary>
        <ActionPolicyList title="允许动作" items={environment.allowed_actions} />
        <ActionPolicyList title="需要确认" items={environment.required_confirmations} tone="warn" />
        <JsonPreview title="上下文分区原始数据" value={environment.context_sections} />
      </details>
      <details className="fold-section">
        <summary>原始调试数据</summary>
        <JsonPreview title="StateEnvironment 原始数据" value={environment} collapsed={false} />
      </details>
    </div>
  );
}

function ActionPolicyList({ title, items, tone = "info" }: { title: string; items: string[]; tone?: "info" | "warn" }) {
  return (
    <section>
      <h3 className="subheading">{title}</h3>
      <div className="pill-row wrap">
        {items.length ? items.map((item) => <StatusPill key={item} value={statusLabel(item)} tone={tone} />) : <span className="muted">无</span>}
      </div>
    </section>
  );
}

function countCandidates(environment: StateEnvironment, status: string): number {
  return environment.candidate_items.filter((item) => item.status === status).length;
}
