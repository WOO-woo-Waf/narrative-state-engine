import { X } from "lucide-react";
import type { DialogueRuntimeDetail } from "../../api/dialogueRuntime";
import type { RuntimeSelection, ScenarioRegistration } from "../types";

export function ContextDrawer({
  scenario,
  runtime,
  selection,
  onClose
}: {
  scenario: ScenarioRegistration;
  runtime: DialogueRuntimeDetail;
  selection: RuntimeSelection;
  onClose: () => void;
}) {
  const thread = runtime.thread;
  return (
    <aside className="agent-context-drawer" aria-label="上下文抽屉">
      <header>
        <strong>上下文</strong>
        <button type="button" onClick={onClose} title="关闭上下文">
          <X size={17} />
        </button>
      </header>
      <section>
        <h2>场景</h2>
        <dl className="agent-context-list">
          <div>
            <dt>类型</dt>
            <dd>{scenario.label}</dd>
          </div>
          <div>
            <dt>上下文模式</dt>
            <dd>{selection.sceneType || "-"}</dd>
          </div>
          <div>
            <dt>线程</dt>
            <dd>{thread?.title || thread?.thread_id || "未选择"}</dd>
          </div>
        </dl>
      </section>
      <section>
        <h2>选择项</h2>
        <dl className="agent-context-list">
          <ContextRow label="小说" value={selection.storyId} />
          <ContextRow label="任务" value={selection.taskId} />
          <ContextRow label="候选" value={selection.selectedCandidateIds?.join(", ")} />
          <ContextRow label="对象" value={selection.selectedObjectIds?.join(", ")} />
          <ContextRow label="分支" value={selection.selectedBranchIds?.join(", ")} />
          <ContextRow label="产物" value={selection.selectedArtifactId} />
        </dl>
      </section>
      <section>
        <h2>运行数据</h2>
        <div className="agent-context-metrics">
          <Metric label="消息" value={runtime.messages.length} />
          <Metric label="事件" value={runtime.events.length} />
          <Metric label="草案" value={runtime.actions.length} />
          <Metric label="产物" value={runtime.artifacts.length} />
        </div>
      </section>
    </aside>
  );
}

function ContextRow({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || "-"}</dd>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
