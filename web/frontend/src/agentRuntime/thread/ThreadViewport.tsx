import { useEffect, useRef } from "react";
import type { DialogueArtifact, DialogueRunEvent } from "../../api/dialogueRuntime";
import type { DialogueAction } from "../../types/action";
import type { DialogueMessage } from "../../types/dialogue";
import { ActiveDraftDock } from "../chat/ActiveDraftDock";
import { MessageBubble } from "../chat/MessageBubble";
import { TaskProgressCard } from "../chat/TaskProgressCard";
import { groupThreadBlocks } from "../runs/groupRuns";
import { RunPlaceholder } from "../runs/RunSummaryCard";
import type { RuntimeSelection } from "../types";

export type LocalRuntimeBlock =
  | { id: string; kind: "user"; content: string; created_at: string }
  | { id: string; kind: "run-placeholder"; content: string; created_at: string }
  | { id: string; kind: "context-mode"; content: string; created_at: string }
  | { id: string; kind: "stopped"; content: string; created_at: string }
  | { id: string; kind: "error"; content: string; created_at: string };

export function ThreadViewport({
  messages,
  events,
  actions,
  artifacts,
  localBlocks,
  onConfirm,
  onExecute,
  onConfirmAndExecute,
  onCancel,
  onOpenArtifact,
  onOpenWorkspace,
  onRetry,
  selection,
  onOpenPlotPlanPicker
}: {
  messages: DialogueMessage[];
  events: DialogueRunEvent[];
  actions: DialogueAction[];
  artifacts: DialogueArtifact[];
  localBlocks: LocalRuntimeBlock[];
  onConfirm: (action: DialogueAction) => void;
  onExecute: (action: DialogueAction) => void;
  onConfirmAndExecute?: (action: DialogueAction) => void;
  onCancel: (action: DialogueAction) => void;
  onOpenArtifact: (artifact: DialogueArtifact) => void;
  onOpenWorkspace: (workspaceId: string, sceneType?: string, artifact?: DialogueArtifact) => void;
  onRetry?: () => void;
  selection?: RuntimeSelection;
  onOpenPlotPlanPicker?: () => void;
}) {
  const hasContent = messages.length || events.length || actions.length || artifacts.length || localBlocks.length;
  const scrollRef = useRef<HTMLElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const blocks = groupThreadBlocks({ messages, events, actions, artifacts });
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !shouldStickToBottomRef.current) return;
    node.scrollTop = node.scrollHeight;
  }, [blocks.length, localBlocks.length]);
  if (!hasContent) {
    return (
      <main className="agent-thread" ref={scrollRef}>
        <div className="agent-empty-thread">
          <strong>准备好了。</strong>
          <p>选择小说和任务后，直接在底部输入你的下一步意图。运行事件会折叠成摘要，不会刷屏。</p>
        </div>
      </main>
    );
  }
  return (
    <main
      className="agent-thread"
      ref={scrollRef}
      onScroll={(event) => {
        const node = event.currentTarget;
        shouldStickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 96;
      }}
    >
      {blocks.map((block) => {
        if (block.type === "message") return <MessageBubble message={block.message} key={block.id} />;
        if (block.type === "active_action_draft") {
          return (
            <ActiveDraftDock
              action={block.action}
              key={block.id}
              onConfirmAndExecute={onConfirmAndExecute || onExecute}
              onContinue={onExecute}
              onCancel={onCancel}
              selection={selection}
              onOpenPlotPlanPicker={onOpenPlotPlanPicker}
            />
          );
        }
        if (block.type === "continuation_run" || block.type === "run_summary") return <TaskProgressCard run={block.run} key={block.id} onOpenArtifact={onOpenArtifact} onOpenWorkspace={onOpenWorkspace} onRetry={onRetry} />;
        return null;
      })}
      {localBlocks.map((block) => (
        <LocalBlock block={block} key={block.id} />
      ))}
    </main>
  );
}

function LocalBlock({ block }: { block: LocalRuntimeBlock }) {
  if (block.kind === "run-placeholder") return <RunPlaceholder content={block.content} />;
  return (
    <article className={`agent-block agent-block-${block.kind === "error" ? "error" : "local"}`}>
      <strong>{block.kind === "error" ? "本地错误" : block.kind === "context-mode" ? "上下文切换" : block.kind === "stopped" ? "已停止等待" : "你"}</strong>
      <p>{block.content}</p>
    </article>
  );
}
