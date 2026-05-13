// Legacy sessions component. Do not use this for the dialogue-first Agent Runtime.
import { useEffect, useMemo, useState } from "react";
import { Send, Sparkles } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createDialogueSession, getDialogueSession, getDialogueSessions, sendDialogueMessage } from "../../api/dialogue";
import { IconButton } from "../../components/form/IconButton";
import { LoadingState } from "../../components/feedback/LoadingState";
import { ErrorState } from "../../components/feedback/ErrorState";
import { StatusPill } from "../../components/data/StatusPill";
import { MessageBubble } from "./MessageBubble";
import { ActionCard } from "./ActionCard";
import type { StateEnvironment } from "../../types/environment";

export function DialogueThread({ environment }: { environment?: StateEnvironment }) {
  const [draft, setDraft] = useState("");
  const [discussOnly, setDiscussOnly] = useState(false);
  const queryClient = useQueryClient();
  const enabled = Boolean(environment?.story_id && environment.task_id);
  const sessionsQuery = useQuery({
    queryKey: ["dialogue-sessions", environment?.story_id, environment?.task_id, environment?.scene_type, environment?.branch_id],
    queryFn: () =>
      getDialogueSessions({
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        scene_type: environment?.scene_type,
        branch_id: environment?.branch_id
      }),
    enabled
  });
  const activeSessionId = useMemo(
    () => environment?.dialogue_session_id || sessionsQuery.data?.sessions?.[0]?.session_id || "",
    [environment?.dialogue_session_id, sessionsQuery.data]
  );
  const createSessionMutation = useMutation({
    mutationFn: () =>
      createDialogueSession({
        story_id: environment?.story_id || "",
        task_id: environment?.task_id || "",
        scene_type: environment?.scene_type || "state_maintenance",
        branch_id: environment?.branch_id || ""
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dialogue-sessions"] })
  });

  useEffect(() => {
    if (enabled && sessionsQuery.isSuccess && !activeSessionId && !createSessionMutation.isPending) {
      createSessionMutation.mutate();
    }
  }, [activeSessionId, createSessionMutation, enabled, sessionsQuery.isSuccess]);

  const sessionQuery = useQuery({
    queryKey: ["dialogue-session", activeSessionId],
    queryFn: () => getDialogueSession(activeSessionId),
    enabled: Boolean(activeSessionId)
  });
  const sendMutation = useMutation({
    mutationFn: () =>
      sendDialogueMessage(activeSessionId, {
        content: draft,
        discuss_only: discussOnly,
        environment: environment as unknown as Record<string, unknown>
      }),
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({ queryKey: ["dialogue-session", activeSessionId] });
    }
  });

  if (!enabled || !environment) return <div className="empty-state">请选择小说和任务后进入对话。</div>;
  if (sessionsQuery.isLoading || sessionQuery.isLoading) return <LoadingState label="正在加载对话会话" />;
  if (sessionsQuery.error || sessionQuery.error) return <ErrorState error={sessionsQuery.error || sessionQuery.error} />;

  const session = sessionQuery.data?.session || sessionsQuery.data?.sessions?.[0];
  const messages = sessionQuery.data?.messages || session?.messages || [];
  const actions = sessionQuery.data?.actions || session?.actions || [];
  return (
    <div className="dialogue-thread">
      <div className="notice notice-warn">旧会话模式，不调用 Agent Runtime。</div>
      <div className="message-list">
        {messages.map((message) => (
          <MessageBubble key={message.message_id} message={message} />
        ))}
        {actions.map((action) => (
          <ActionCard key={action.action_id} action={action} storyId={environment.story_id} taskId={environment.task_id} />
        ))}
      </div>
      <form
        className="dialogue-input"
        onSubmit={(event) => {
          event.preventDefault();
          if (!draft.trim() || !activeSessionId) return;
          sendMutation.mutate();
        }}
      >
        <div className="input-meta">
          <StatusPill value={environment.scene_type} tone="info" />
          <label>
            <input type="checkbox" checked={discussOnly} onChange={(event) => setDiscussOnly(event.target.checked)} />
            只讨论，不生成动作
          </label>
          <span>可用动作：{environment.allowed_actions.slice(0, 4).join(" / ") || "等待状态环境"}</span>
        </div>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="和模型讨论当前状态、候选差异、分支风险或下一步作者动作..."
        />
        <div className="button-row">
          <IconButton icon={<Send size={16} />} label="发送" tone="primary" disabled={sendMutation.isPending || !draft.trim()} onClick={() => sendMutation.mutate()} />
          <IconButton icon={<Sparkles size={16} />} label="生成动作草案" tone="secondary" disabled={sendMutation.isPending || !draft.trim()} onClick={() => setDiscussOnly(false)} />
        </div>
      </form>
    </div>
  );
}
