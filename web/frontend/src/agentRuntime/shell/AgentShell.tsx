import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronRight, Info, Layers, Plus, X } from "lucide-react";
import { bindActionDraftArtifact, getContextEnvelopePreview, getPlotPlans, setThreadContextMode } from "../api/scenarios";
import {
  cancelDialogueActionDraft,
  confirmAndExecuteDialogueActionDraft,
  createDialogueThread,
  executeDialogueActionDraft,
  getDialogueActionDrafts,
  getDialogueArtifacts,
  getDialogueRunEvents,
  getDialogueThread,
  getDialogueThreads,
  sendDialogueThreadMessage,
  type DialogueArtifact,
  type DialogueRuntimeDetail
} from "../../api/dialogueRuntime";
import { formatApiError } from "../../api/client";
import type { DialogueAction } from "../../types/action";
import type { ScenarioRegistration, RuntimeSelection } from "../types";
import { ContextModeBar } from "../context/ContextModeBar";
import { getScenarioWorkspaces } from "../scenarios/registry";
import { ContextManifestCard } from "../context/ContextManifestCard";
import { PlotPlanPicker } from "../artifacts/WorkspaceArtifactPicker";
import { Composer } from "../thread/Composer";
import { ThreadViewport, type LocalRuntimeBlock } from "../thread/ThreadViewport";
import { ContextDrawer } from "./ContextDrawer";

export function AgentShell({ scenarios, defaultScenarioType = "novel_state_machine" }: { scenarios: ScenarioRegistration[]; defaultScenarioType?: string }) {
  const queryClient = useQueryClient();
  const [scenarioType, setScenarioType] = useState(defaultScenarioType);
  const scenario = scenarios.find((item) => item.scenario_type === scenarioType) || scenarios[0];
  const [sceneType, setSceneType] = useState(scenario?.scenes[0]?.scene_type || "state_maintenance");
  const [runtimeSelection, setRuntimeSelection] = useState<RuntimeSelection>({});
  const [threadId, setThreadId] = useState("");
  const [activeWorkspaceId, setActiveWorkspaceId] = useState("");
  const [contextOpen, setContextOpen] = useState(false);
  const [debugThreadsOpen, setDebugThreadsOpen] = useState(false);
  const [localBlocks, setLocalBlocks] = useState<LocalRuntimeBlock[]>([]);
  const [artifactDetail, setArtifactDetail] = useState<DialogueArtifact | undefined>();
  const [runtimePatch, setRuntimePatch] = useState<DialogueRuntimeDetail>({ messages: [], actions: [], events: [], artifacts: [] });
  const [lastSentMessage, setLastSentMessage] = useState("");
  const sendAbortControllerRef = useRef<AbortController | undefined>();
  const stopRequestedRef = useRef(false);
  const syncedThreadSceneRef = useRef("");

  const selection: RuntimeSelection = { ...runtimeSelection, sceneType };
  const threadContext = scenario?.getThreadContext?.(selection);
  const ContextComponent = scenario?.contextComponent;
  const threadsQuery = useQuery({
    queryKey: ["agent-runtime", "threads", scenarioType, threadContext?.threadFilters],
    queryFn: () => getDialogueThreads({ scenario_type: scenarioType, ...threadContext?.threadFilters }),
    enabled: Boolean(scenario)
  });
  const detailQuery = useQuery({
    queryKey: ["agent-runtime", "thread-detail", threadId],
    queryFn: () => getDialogueThread(threadId),
    enabled: Boolean(threadId)
  });
  const eventsQuery = useQuery({
    queryKey: ["agent-runtime", "thread-events", threadId],
    queryFn: () => getDialogueRunEvents(threadId),
    enabled: Boolean(threadId)
  });
  const draftsQuery = useQuery({
    queryKey: ["agent-runtime", "thread-drafts", threadId],
    queryFn: () => getDialogueActionDrafts(threadId),
    enabled: Boolean(threadId)
  });
  const artifactsQuery = useQuery({
    queryKey: ["agent-runtime", "thread-artifacts", threadId],
    queryFn: () => getDialogueArtifacts(threadId),
    enabled: Boolean(threadId)
  });
  const contextManifestQuery = useQuery({
    queryKey: ["agent-runtime", "context-manifest", selection.storyId, selection.taskId, threadId, sceneType],
    queryFn: () =>
      getContextEnvelopePreview({
        story_id: selection.storyId,
        task_id: selection.taskId,
        thread_id: threadId,
        context_mode: sceneType
      }),
    enabled: Boolean(scenario)
  });
  const plotPlansQuery = useQuery({
    queryKey: ["agent-runtime", "plot-plans", selection.storyId, selection.taskId],
    queryFn: () => getPlotPlans({ story_id: selection.storyId, task_id: selection.taskId }),
    enabled: Boolean(selection.storyId || selection.taskId)
  });

  useEffect(() => {
    setSceneType(scenario?.scenes[0]?.scene_type || "state_maintenance");
    setRuntimeSelection({});
    setActiveWorkspaceId("");
    setThreadId("");
    setRuntimePatch({ messages: [], actions: [], events: [], artifacts: [] });
  }, [scenario?.scenario_type]);

  useEffect(() => {
    const firstThread = threadsQuery.data?.threads[0]?.thread_id || "";
    if (!threadId && firstThread) {
      setThreadId(firstThread);
    }
  }, [threadsQuery.data, threadId]);

  const selectedThread = threadsQuery.data?.threads.find((thread) => thread.thread_id === threadId);
  useEffect(() => {
    const thread = selectedThread || detailQuery.data?.thread;
    if (!thread) return;
    if (thread.thread_id && syncedThreadSceneRef.current !== thread.thread_id) {
      syncedThreadSceneRef.current = thread.thread_id;
      if (thread.scene_type) setSceneType(String(thread.scene_type));
    }
    setRuntimeSelection((current) => {
      const nextStoryId = thread.story_id || current.storyId;
      const nextTaskId = thread.task_id || current.taskId;
      if (nextStoryId === current.storyId && nextTaskId === current.taskId) return current;
      return { ...current, storyId: nextStoryId, taskId: nextTaskId };
    });
  }, [detailQuery.data?.thread, selectedThread]);

  const detailRuntime = detailQuery.data || { messages: [], actions: [], events: [], artifacts: [] };
  const runtime: DialogueRuntimeDetail = {
    thread: detailRuntime.thread,
    messages: dedupeById([...detailRuntime.messages, ...runtimePatch.messages], (message) => message.message_id),
    actions: dedupeById([...detailRuntime.actions, ...(draftsQuery.data?.drafts || []), ...runtimePatch.actions], (action) => action.action_id),
    events: dedupeById([...detailRuntime.events, ...(eventsQuery.data?.events || []), ...runtimePatch.events], (event) => event.event_id),
    artifacts: dedupeById([...detailRuntime.artifacts, ...(artifactsQuery.data?.artifacts || []), ...runtimePatch.artifacts], (artifact) => artifact.artifact_id)
  };
  const workspaces = useMemo(() => getScenarioWorkspaces(scenario?.scenario_type || "", sceneType), [scenario?.scenario_type, sceneType]);
  const activeWorkspace = scenario?.workspaces.find((workspace) => workspace.workspace_id === activeWorkspaceId);
  const ActiveWorkspaceComponent = activeWorkspace?.component;
  const prompts = scenarioPromptShortcuts(scenario?.scenario_type || "", sceneType);
  const attachmentSummary = buildAttachmentSummary(activeWorkspace?.label, selection);
  const changeScene = useCallback((nextSceneType: string) => {
    if (nextSceneType === sceneType) return;
    setSceneType(nextSceneType);
    setLocalBlocks((blocks) => [
      ...blocks,
      {
        id: `context-mode-${Date.now()}`,
        kind: "context-mode",
        content: `上下文已切换为「${scenario?.scenes.find((scene) => scene.scene_type === nextSceneType)?.label || nextSceneType}」。主对话不会清空，新的上下文包将在可用时刷新。`,
        created_at: new Date().toISOString()
      }
    ]);
    setThreadContextMode(threadId, nextSceneType).then((result) => {
      if (!result.ok && result.fallback) {
        setLocalBlocks((blocks) => [
          ...blocks,
          { id: `context-mode-fallback-${Date.now()}`, kind: "context-mode", content: result.fallback || "后端接口暂缺，已仅在前端切换上下文模式。", created_at: new Date().toISOString() }
        ]);
      }
      queryClient.invalidateQueries({ queryKey: ["agent-runtime", "context-manifest"] });
    });
  }, [queryClient, scenario?.scenes, sceneType, threadId]);
  const updateSelection = useCallback((next: Partial<RuntimeSelection>) => {
    if (next.sceneType) changeScene(next.sceneType);
    setRuntimeSelection((current) => {
      const merged = { ...current, ...next, sceneType: undefined };
      if (
        merged.storyId === current.storyId &&
        merged.taskId === current.taskId &&
        merged.selectedArtifactId === current.selectedArtifactId &&
        sameRecord(merged.selectedArtifacts, current.selectedArtifacts) &&
        sameArray(merged.selectedCandidateIds, current.selectedCandidateIds) &&
        sameArray(merged.selectedObjectIds, current.selectedObjectIds) &&
        sameArray(merged.selectedBranchIds, current.selectedBranchIds)
      ) {
        return current;
      }
      return merged;
    });
  }, [changeScene]);
  const selectThread = useCallback((nextThreadId: string) => {
    const nextThread = threadsQuery.data?.threads.find((thread) => thread.thread_id === nextThreadId);
    if (nextThread?.scene_type) setSceneType(String(nextThread.scene_type));
    setRuntimeSelection((current) => ({
      ...current,
      storyId: nextThread?.story_id || current.storyId,
      taskId: nextThread?.task_id || current.taskId
    }));
    setRuntimePatch({ messages: [], actions: [], events: [], artifacts: [] });
    setThreadId(nextThreadId);
  }, [threadsQuery.data?.threads]);

  const createThreadMutation = useMutation({
    mutationFn: () =>
      createDialogueThread({
        scenario_type: scenario.scenario_type,
        scenario_instance_id: threadContext?.scenario_instance_id,
        scenario_ref: threadContext?.scenario_ref,
        scene_type: sceneType,
        ...threadContext?.createThreadInput
      }),
    onSuccess: (thread) => {
      setRuntimePatch({ messages: [], actions: [], events: [], artifacts: [] });
      setThreadId(thread.thread_id);
      queryClient.invalidateQueries({ queryKey: ["agent-runtime", "threads"] });
    }
  });

  const sendMutation = useMutation({
    mutationFn: async (message: string) => {
      const activeThreadId = threadId || (await createThreadMutation.mutateAsync()).thread_id;
      const inferredArtifacts = inferSelectedArtifacts(message, selection.selectedArtifacts, plotPlansQuery.data?.plans || []);
      const controller = new AbortController();
      sendAbortControllerRef.current = controller;
      stopRequestedRef.current = false;
      return sendDialogueThreadMessage(activeThreadId, {
        content: message,
        environment: buildMessageEnvironment(scenario.scenario_type, sceneType, threadContext?.messageEnvironment, activeWorkspaceId, activeWorkspace?.label, { ...selection, selectedArtifacts: inferredArtifacts }, activeThreadId)
      }, { signal: controller.signal });
    },
    onMutate: (message) => {
      setLastSentMessage(message);
      setLocalBlocks([
        { id: `local-user-${Date.now()}`, kind: "user", content: message, created_at: new Date().toISOString() },
        { id: `local-run-${Date.now()}`, kind: "run-placeholder", content: "已发送，等待后端运行结果。", created_at: new Date().toISOString() }
      ]);
    },
    onSuccess: (detail) => {
      if (detail.thread?.thread_id) setThreadId(detail.thread.thread_id);
      setRuntimePatch(detail);
      setLocalBlocks([]);
      queryClient.invalidateQueries({ queryKey: ["agent-runtime"] });
    },
    onError: (error) => {
      if (stopRequestedRef.current) {
        stopRequestedRef.current = false;
        sendAbortControllerRef.current = undefined;
        return;
      }
      setLocalBlocks((blocks) => [
        ...blocks.filter((block) => block.kind !== "run-placeholder"),
        { id: `local-error-${Date.now()}`, kind: "error", content: formatApiError(error), created_at: new Date().toISOString() }
      ]);
    },
    onSettled: () => {
      sendAbortControllerRef.current = undefined;
    }
  });

  const confirmAndExecuteMutation = useMutation({
    mutationFn: async (action: DialogueAction) => {
      if (isGenerationAction(action) && selection.selectedArtifacts?.plot_plan_id) {
        await bindActionDraftArtifact(action.action_id, {
          plot_plan_id: selection.selectedArtifacts.plot_plan_id,
          plot_plan_artifact_id: selection.selectedArtifacts.plot_plan_artifact_id
        });
      }
      return confirmAndExecuteDialogueActionDraft(action.action_id, { confirmation_text: confirmationText(action), reason: "author" });
    },
    onSuccess: (detail) => {
      setRuntimePatch(detail);
      queryClient.invalidateQueries({ queryKey: ["agent-runtime"] });
    }
  });
  const executeMutation = useMutation({
    mutationFn: async (action: DialogueAction) => {
      if (isGenerationAction(action) && selection.selectedArtifacts?.plot_plan_id) {
        await bindActionDraftArtifact(action.action_id, {
          plot_plan_id: selection.selectedArtifacts.plot_plan_id,
          plot_plan_artifact_id: selection.selectedArtifacts.plot_plan_artifact_id
        });
      }
      return executeDialogueActionDraft(action.action_id, { confirmation_text: "execute from Agent Runtime", reason: "author" });
    },
    onSuccess: (detail) => {
      setRuntimePatch(detail);
      queryClient.invalidateQueries({ queryKey: ["agent-runtime"] });
    }
  });
  const cancelMutation = useMutation({
    mutationFn: (action: DialogueAction) => cancelDialogueActionDraft(action.action_id),
    onSuccess: (detail) => {
      setRuntimePatch(detail);
      queryClient.invalidateQueries({ queryKey: ["agent-runtime"] });
    }
  });

  if (!scenario) return <div className="agent-shell"><div className="empty-state">没有注册任何 scenario。</div></div>;

  return (
    <div className="agent-shell">
      <aside className="agent-sidebar">
        <header className="agent-brand">
          <Bot size={20} />
          <div>
            <strong>Agent Runtime</strong>
            <span>通用对话壳</span>
          </div>
        </header>
        <Field label="场景类型">
          <select value={scenario.scenario_type} onChange={(event) => setScenarioType(event.target.value)}>
            {scenarios.map((item) => (
              <option value={item.scenario_type} key={item.scenario_type}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
        {ContextComponent ? <ContextComponent selection={selection} onSelectionChange={updateSelection} /> : null}
        <ContextModeBar scenario={scenario} value={sceneType} onChange={(nextSceneType) => updateSelection({ sceneType: nextSceneType })} />
        <PlotPlanPicker plans={plotPlansQuery.data?.plans || contextManifestQuery.data?.handoff?.available_artifacts.plot_plan || []} fallback={plotPlansQuery.data?.fallback} selection={selection} onSelectionChange={updateSelection} />
        <button className="agent-primary-button" type="button" onClick={() => createThreadMutation.mutate()} disabled={createThreadMutation.isPending}>
          <Plus size={16} />
          新建线程
        </button>
        <section className="agent-sidebar-section">
          <button className="agent-debug-toggle" type="button" onClick={() => setDebugThreadsOpen((open) => !open)}>
            历史 / 分支 / 调试
            <ChevronRight size={14} />
          </button>
          {debugThreadsOpen ? (
            <div className="agent-thread-list">
              {threadsQuery.data?.threads.map((thread) => (
                <button type="button" className={thread.thread_id === threadId ? "active" : ""} key={thread.thread_id} onClick={() => selectThread(thread.thread_id)}>
                  <span>{thread.title}</span>
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
          ) : null}
        </section>
        <section className="agent-sidebar-section">
          <h2>Workspaces</h2>
          <div className="agent-workspace-list">
            {workspaces.map((workspace) => (
              <button type="button" className={workspace.workspace_id === activeWorkspaceId ? "active" : ""} key={workspace.workspace_id} onClick={() => setActiveWorkspaceId(workspace.workspace_id)}>
                <Layers size={15} />
                {workspace.label}
              </button>
            ))}
          </div>
        </section>
      </aside>
      <section className="agent-main">
        <header className="agent-main-header">
          <div>
            <strong>{scenario.label}</strong>
            <span>{scenario.scenes.find((scene) => scene.scene_type === sceneType)?.label || sceneType}</span>
          </div>
          <div className="agent-main-actions">
            {detailQuery.isFetching || eventsQuery.isFetching || draftsQuery.isFetching || artifactsQuery.isFetching ? <span className="agent-source agent-source-info">刷新中</span> : null}
            <button type="button" onClick={() => setContextOpen(true)} title="上下文">
              <Info size={17} />
              上下文
            </button>
          </div>
        </header>
        <ContextManifestCard
          manifest={contextManifestQuery.data}
          contextModeLabel={scenario.scenes.find((scene) => scene.scene_type === sceneType)?.label || sceneType}
        />
        <ThreadViewport
          messages={runtime.messages}
          events={runtime.events}
          actions={runtime.actions}
          artifacts={runtime.artifacts}
          localBlocks={localBlocks}
          onConfirm={(action) => confirmAndExecuteMutation.mutate(action)}
          onConfirmAndExecute={(action) => confirmAndExecuteMutation.mutate(action)}
          onExecute={(action) => executeMutation.mutate(action)}
          onCancel={(action) => cancelMutation.mutate(action)}
          onOpenArtifact={(artifact) => {
            setArtifactDetail(artifact);
            setActiveWorkspaceId("");
          }}
          onOpenWorkspace={(workspaceId, nextSceneType, artifact) => {
            if (artifact) {
              setArtifactDetail(undefined);
              updateSelection({
                selectedArtifactId: artifact.artifact_id,
                selectedArtifacts: artifact.artifact_type === "plot_plan" ? { ...selection.selectedArtifacts, plot_plan_id: String(artifact.payload?.plot_plan_id || artifact.artifact_id), plot_plan_artifact_id: artifact.artifact_id } : selection.selectedArtifacts,
                selectedCandidateIds: artifact.related_candidate_ids || selection.selectedCandidateIds,
                selectedObjectIds: artifact.related_object_ids || selection.selectedObjectIds,
                selectedBranchIds: artifact.related_branch_ids || selection.selectedBranchIds
              });
            }
            if (nextSceneType && !artifact) changeScene(nextSceneType);
            setActiveWorkspaceId(workspaceId);
          }}
          onRetry={() => {
            if (lastSentMessage && !sendMutation.isPending) sendMutation.mutate(lastSentMessage);
          }}
          selection={selection}
          onOpenPlotPlanPicker={() => setDebugThreadsOpen(false)}
        />
        <Composer
          disabled={sendMutation.isPending}
          isSending={sendMutation.isPending}
          attachmentSummary={attachmentSummary}
          prompts={prompts}
          onSend={(message) => sendMutation.mutate(message)}
          onRetry={() => {
            if (lastSentMessage && !sendMutation.isPending) sendMutation.mutate(lastSentMessage);
            else queryClient.invalidateQueries({ queryKey: ["agent-runtime", "thread-detail", threadId] });
          }}
          onStop={() => {
            stopRequestedRef.current = true;
            sendAbortControllerRef.current?.abort();
            setLocalBlocks((blocks) => [
              ...blocks.filter((block) => block.kind !== "run-placeholder"),
              { id: `local-stop-${Date.now()}`, kind: "stopped", content: "已停止本地等待；后端运行若已开始，刷新线程可查看最新结果。", created_at: new Date().toISOString() }
            ]);
          }}
        />
      </section>
      {activeWorkspace || artifactDetail ? (
        <div className="agent-workspace-overlay">
          <header>
            <strong>{activeWorkspace?.label || artifactDetail?.title}</strong>
            <button type="button" onClick={() => { setActiveWorkspaceId(""); setArtifactDetail(undefined); }}>
              <X size={17} />
            </button>
          </header>
          <div className="agent-workspace-body">
            {ActiveWorkspaceComponent ? (
              <ActiveWorkspaceComponent
                scenario={scenario}
                thread={runtime.thread ? { ...runtime.thread, scenario_type: runtime.thread.scenario_type || scenario.scenario_type } : undefined}
                context={runtime}
                selection={selection}
                onSelectionChange={updateSelection}
                onSendMessage={(message) => sendMutation.mutate(message)}
                onClose={() => setActiveWorkspaceId("")}
              />
            ) : (
              <pre className="agent-json">{JSON.stringify(artifactDetail, null, 2)}</pre>
            )}
          </div>
        </div>
      ) : null}
      {contextOpen ? <ContextDrawer scenario={scenario} runtime={runtime} selection={selection} onClose={() => setContextOpen(false)} /> : null}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="agent-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function scenarioPromptShortcuts(scenarioType: string, sceneType: string): string[] {
  if (scenarioType === "mock_image") return ["细化提示词", "检查生成队列", "给出审稿意见"];
  if (sceneType === "branch_review") return ["审阅当前分支", "说明入主线风险", "生成重写建议"];
  if (sceneType === "plot_planning") return ["生成剧情规划", "列出冲突点", "补充证据需求"];
  return ["解释当前状态", "生成审计草案", "列出下一步"];
}

function dedupeById<T>(items: T[], keyFn: (item: T) => string | undefined): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  items.forEach((item) => {
    const key = keyFn(item);
    if (key && seen.has(key)) return;
    if (key) seen.add(key);
    result.push(item);
  });
  return result;
}

function sameArray(left?: string[], right?: string[]): boolean {
  const a = left || [];
  const b = right || [];
  return a.length === b.length && a.every((item, index) => item === b[index]);
}

function sameRecord(left?: Record<string, string | undefined>, right?: Record<string, string | undefined>): boolean {
  const leftKeys = Object.keys(left || {}).filter((key) => left?.[key]);
  const rightKeys = Object.keys(right || {}).filter((key) => right?.[key]);
  return leftKeys.length === rightKeys.length && leftKeys.every((key) => left?.[key] === right?.[key]);
}

function confirmationText(action: DialogueAction): string {
  const policyText = action.confirmation_policy?.confirmation_text;
  return typeof policyText === "string" && policyText ? policyText : "确认执行";
}

function buildAttachmentSummary(workspaceLabel: string | undefined, selection: RuntimeSelection): string {
  const parts = [
    workspaceLabel ? `workspace: ${workspaceLabel}` : "",
    selection.selectedArtifacts?.plot_plan_id ? `剧情规划 ${selection.selectedArtifacts.plot_plan_id}` : "",
    selection.selectedCandidateIds?.length ? `候选 ${selection.selectedCandidateIds.length}` : "",
    selection.selectedObjectIds?.length ? `对象 ${selection.selectedObjectIds.length}` : "",
    selection.selectedBranchIds?.length ? `分支 ${selection.selectedBranchIds.length}` : "",
    selection.selectedArtifactId ? "artifact 已附加" : ""
  ].filter(Boolean);
  return parts.length ? `附加上下文：${parts.join(" / ")}` : "";
}

export function buildMessageEnvironment(
  scenarioType: string,
  sceneType: string,
  baseEnvironment: Record<string, unknown> | undefined,
  activeWorkspaceId: string,
  activeWorkspaceLabel: string | undefined,
  selection: RuntimeSelection,
  mainThreadId?: string
): Record<string, unknown> {
  return {
    scenario_type: scenarioType,
    scene_type: sceneType,
    context_mode: sceneType,
    story_id: selection.storyId,
    task_id: selection.taskId,
    main_thread_id: mainThreadId,
    ...baseEnvironment,
    active_workspace_id: activeWorkspaceId || undefined,
    active_workspace_label: activeWorkspaceLabel || undefined,
    selected_artifacts: {
      plot_plan_id: selection.selectedArtifacts?.plot_plan_id,
      plot_plan_artifact_id: selection.selectedArtifacts?.plot_plan_artifact_id
    },
    selection: {
      story_id: selection.storyId,
      task_id: selection.taskId,
      scene_type: selection.sceneType,
      selected_candidate_ids: selection.selectedCandidateIds || [],
      selected_object_ids: selection.selectedObjectIds || [],
      selected_branch_ids: selection.selectedBranchIds || [],
      selected_artifact_id: selection.selectedArtifactId,
      selected_artifacts: selection.selectedArtifacts || {}
    }
  };
}

function inferSelectedArtifacts(message: string, current: RuntimeSelection["selectedArtifacts"], plans: Array<{ plot_plan_id?: string; artifact_id: string }>): RuntimeSelection["selectedArtifacts"] {
  if (current?.plot_plan_id || current?.plot_plan_artifact_id) return current;
  const plan = plans.find((item) => {
    const id = item.plot_plan_id || item.artifact_id;
    return id && (message.includes(id) || /-\d{2,4}\b/.test(message) && id.includes(message.match(/-\d{2,4}\b/)?.[0] || ""));
  });
  return plan ? { plot_plan_id: plan.plot_plan_id || plan.artifact_id, plot_plan_artifact_id: plan.artifact_id } : current;
}

function isGenerationAction(action: DialogueAction): boolean {
  const text = `${action.action_type} ${action.tool_name || ""}`.toLowerCase();
  return text.includes("generation") || text.includes("continuation") || text.includes("create_generation_job");
}
