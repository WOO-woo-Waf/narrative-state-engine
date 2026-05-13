import { Check, RotateCcw, X } from "lucide-react";
import type { DialogueAction } from "../../types/action";
import { provenanceFromMetadata, provenanceLabel } from "../provenance";
import type { RuntimeSelection } from "../types";

export function ActionDraftBlock({
  action,
  onConfirmAndExecute,
  onContinue,
  onCancel,
  selection,
  onOpenPlotPlanPicker
}: {
  action: DialogueAction;
  onConfirmAndExecute: (action: DialogueAction) => void;
  onContinue?: (action: DialogueAction) => void;
  onCancel: (action: DialogueAction) => void;
  selection?: RuntimeSelection;
  onOpenPlotPlanPicker?: () => void;
}) {
  const label = provenanceLabel(provenanceFromMetadata(action.metadata));
  const binding = generationBinding(action, selection);
  const executionBlocked = binding.isGeneration && !binding.hasPlotPlan;
  const confirmedButNotExecuted = ["confirmed", "confirmed_without_job"].includes(String(action.status || ""));
  const paramWarnings = generationParamWarnings(action, binding);
  return (
    <article className="agent-block agent-block-draft">
      <header>
        <strong>{action.title || action.action_type}</strong>
        <span className={`agent-source agent-source-${label.tone}`}>{label.label}</span>
        <span className="agent-source agent-source-neutral">{actionStatusLabel(action.status)}</span>
      </header>
      <p>{action.summary || action.preview || "后端返回了一个待确认动作草案。"}</p>
      {confirmedButNotExecuted ? (
        <div className="generation-binding blocked">
          <strong>已确认但尚未执行</strong>
          <p>该草案已经确认，但后端尚未返回执行结果。请继续执行或重试，不应视为已完成。</p>
        </div>
      ) : null}
      {binding.isGeneration ? (
        <div className={`generation-binding ${executionBlocked ? "blocked" : ""}`}>
          <strong>续写任务草案</strong>
          <span>使用剧情规划：{binding.plotPlanId || "未绑定"}</span>
          {binding.stateVersion ? <span>状态版本：{binding.stateVersion}</span> : null}
          {binding.targetWords ? <span>目标字数：{binding.targetWords}</span> : null}
          {binding.targetChars ? <span>目标字符：{binding.targetChars}</span> : null}
          {binding.branchCount ? <span>分支数：{binding.branchCount}</span> : null}
          {binding.rounds ? <span>轮次：{binding.rounds}</span> : null}
          <span>RAG：{binding.ragEnabled === undefined ? "未声明" : binding.ragEnabled ? "启用" : "关闭"}</span>
          {binding.outputPath ? <span>输出路径：{binding.outputPath}</span> : null}
          {paramWarnings.map((warning) => <p key={warning}>{warning}</p>)}
          {executionBlocked ? <p>缺少剧情规划绑定，不能执行续写。</p> : null}
        </div>
      ) : null}
      <div className="agent-inline-actions">
        {confirmedButNotExecuted ? (
          <button type="button" onClick={() => onContinue?.(action)} title="继续执行" disabled={executionBlocked || !onContinue}>
            <RotateCcw size={16} />
            继续执行
          </button>
        ) : (
          <button type="button" onClick={() => onConfirmAndExecute(action)} title={binding.isGeneration ? "确认并开始生成" : "确认并执行"} disabled={executionBlocked}>
            <Check size={16} />
            {binding.isGeneration ? "确认并开始生成" : "确认并执行"}
          </button>
        )}
        {executionBlocked ? (
          <button type="button" onClick={onOpenPlotPlanPicker}>
            选择剧情规划
          </button>
        ) : null}
        <button type="button" onClick={() => onConfirmAndExecute(action)} title="重试" disabled={!confirmedButNotExecuted && !String(action.status || "").includes("failed")}>
          重试
        </button>
        {confirmedButNotExecuted || String(action.status || "").includes("failed") ? <button type="button">查看错误</button> : null}
        <button type="button" disabled title="让模型修改">
          让模型修改
        </button>
        <button type="button" onClick={() => onCancel(action)} title="取消">
          <X size={16} />
          取消
        </button>
      </div>
    </article>
  );
}

function generationBinding(action: DialogueAction, selection?: RuntimeSelection) {
  const params = action.tool_params || {};
  const metadata = action.metadata || {};
  const result = action.result_payload || {};
  const text = `${action.action_type} ${action.tool_name || ""}`.toLowerCase();
  const isGeneration = text.includes("generation") || text.includes("continuation") || text.includes("create_generation_job");
  const plotPlanId = stringValue(params.plot_plan_id || params.plot_plan_artifact_id || metadata.plot_plan_id || result.plot_plan_id || selection?.selectedArtifacts?.plot_plan_id || selection?.selectedArtifacts?.plot_plan_artifact_id);
  return {
    isGeneration,
    hasPlotPlan: Boolean(plotPlanId),
    plotPlanId,
    stateVersion: stringValue(params.state_version_no || metadata.state_version_no || result.state_version_no),
    targetWords: stringValue(params.target_words || params.target_word_count || metadata.target_words || result.target_words),
    targetChars: stringValue(params.target_chars || params.target_char_count || metadata.target_chars || result.target_chars),
    branchCount: stringValue(params.branch_count || params.branches || params.num_branches || metadata.branch_count || result.branch_count),
    rounds: stringValue(params.rounds || params.max_rounds || params.round_limit || metadata.rounds || result.rounds),
    outputPath: stringValue(params.output_path || params.output_dir || params.destination || metadata.output_path || result.output_path),
    ragEnabled: booleanValue(params.rag_enabled ?? params.use_rag ?? metadata.rag_enabled ?? metadata.rag ?? result.rag_enabled)
  };
}

function generationParamWarnings(action: DialogueAction, binding: ReturnType<typeof generationBinding>): string[] {
  const warnings: string[] = [];
  const text = `${action.summary || ""} ${action.preview || ""}`;
  const numbers = [...text.matchAll(/\d+/g)].map((match) => match[0]);
  if (binding.targetWords && numbers.length && !numbers.includes(binding.targetWords)) {
    warnings.push(`提示：自然语言描述中的数字与 tool_params 不完全一致，以目标字数 ${binding.targetWords} 为准。`);
  }
  if (binding.branchCount && /(分支|branch)/i.test(text) && numbers.length && !numbers.includes(binding.branchCount)) {
    warnings.push(`提示：分支数量以 tool_params 的 ${binding.branchCount} 为准。`);
  }
  return warnings;
}

function booleanValue(value: unknown): boolean | undefined {
  if (value === true || value === "true" || value === 1 || value === "1") return true;
  if (value === false || value === "false" || value === 0 || value === "0") return false;
  return undefined;
}

function stringValue(value: unknown): string {
  return value === undefined || value === null || value === "" ? "" : String(value);
}

function actionStatusLabel(status: string): string {
  if (status === "draft" || status === "pending_confirmation" || status === "requires_confirmation") return "等待确认";
  if (status === "confirmed" || status === "confirmed_without_job") return "已确认但尚未执行";
  if (status === "running") return "执行中";
  if (status === "submitted") return "已提交";
  if (status === "succeeded") return "已执行";
  if (status === "failed" || status === "execution_failed") return "执行失败";
  if (status === "cancelled") return "已取消";
  return status || "状态待补齐";
}
