import type { WorkspaceComponentProps } from "../../../agentRuntime/types";

const queue = [
  { id: "mock-image-1", title: "角色概念图", status: "queued" },
  { id: "mock-image-2", title: "场景气氛图", status: "review" },
  { id: "mock-image-3", title: "章节封面", status: "done" }
];

export function ImageQueueWorkspace({ onSendMessage }: WorkspaceComponentProps) {
  return (
    <div className="agent-workspace-stack">
      {queue.map((item) => (
        <article className="agent-list-card" key={item.id}>
          <div>
            <strong>{item.title}</strong>
            <span className="muted">{item.id}</span>
          </div>
          <button type="button" onClick={() => onSendMessage(`请审阅图片任务 ${item.id}：${item.title}`)}>
            审阅
          </button>
        </article>
      ))}
    </div>
  );
}
