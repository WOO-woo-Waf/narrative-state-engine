import type { WorkspaceComponentProps } from "../../../agentRuntime/types";

const prompts = ["电影感夜景，冷暖对比", "角色设定三视图，干净背景", "封面构图，高冲突情绪", "分镜草图，动作连贯"];

export function PromptBoardWorkspace({ onSendMessage }: WorkspaceComponentProps) {
  return (
    <div className="agent-workspace-stack">
      <p className="muted">Mock 图片场景只验证 workspace 扩展入口，不调用真实图片生成。</p>
      <div className="agent-card-grid">
        {prompts.map((prompt) => (
          <article className="agent-mini-card" key={prompt}>
            <strong>{prompt}</strong>
            <button type="button" onClick={() => onSendMessage(`请基于这个图片提示词继续细化：${prompt}`)}>
              发送到对话
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
