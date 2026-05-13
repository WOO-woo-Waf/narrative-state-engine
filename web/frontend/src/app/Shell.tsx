import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Boxes, Braces, GitBranch, ListChecks, Network, ScrollText, Settings2, X } from "lucide-react";
import { getBranches } from "../api/branches";
import { getEnvironment } from "../api/environment";
import { getHealth } from "../api/health";
import { getJobs, submitJob } from "../api/jobs";
import { getStories } from "../api/stories";
import { getCandidates, getState, reviewCandidates } from "../api/state";
import { getTasks } from "../api/tasks";
import { Panel } from "../components/layout/Panel";
import { ErrorState } from "../components/feedback/ErrorState";
import { LoadingState } from "../components/feedback/LoadingState";
import { TopStatusBar, type WorkbenchMode } from "../features/workspace/TopStatusBar";
import { WorkspaceNavigator } from "../features/workspace/WorkspaceNavigator";
import { DialogueThread } from "../features/dialogue/DialogueThread";
import { StateEnvironmentPanel } from "../features/environment/StateEnvironmentPanel";
import { StateObjectInspector } from "../features/environment/StateObjectInspector";
import { CandidateReviewTable } from "../features/audit/CandidateReviewTable";
import { CandidateDiffPanel } from "../features/audit/CandidateDiffPanel";
import { EvidencePanel } from "../features/evidence/EvidencePanel";
import { GraphPanel } from "../features/graph/GraphPanel";
import { PlotPlanningPanel } from "../features/planning/PlotPlanningPanel";
import { GenerationPanel } from "../features/generation/GenerationPanel";
import { BranchReviewPanel } from "../features/branches/BranchReviewPanel";
import { RevisionPanel } from "../features/revision/RevisionPanel";
import { StateCreationPanel } from "../features/stateCreation/StateCreationPanel";
import { GenerationContextInspector } from "../features/environment/GenerationContextInspector";
import { JobLogPanel } from "../features/jobs/JobLogPanel";
import { useSelectionStore } from "../stores/selectionStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import type { Branch } from "../types/branch";
import type { StateEnvironment } from "../types/environment";
import type { CandidateItem, CandidateSet, EvidenceLink, StateObject } from "../types/state";
import type { SceneType } from "../types/task";

type RightPanel = ReturnType<typeof useWorkspaceStore.getState>["rightPanel"];

export function Shell() {
  const workspace = useWorkspaceStore();
  const selection = useSelectionStore();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<WorkbenchMode>("default");
  const [inspectorOpen, setInspectorOpen] = useState(false);

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 5000,
    refetchOnWindowFocus: true
  });
  const storiesQuery = useQuery({ queryKey: ["stories"], queryFn: getStories });
  const tasksQuery = useQuery({ queryKey: ["tasks"], queryFn: getTasks });
  const branchesQuery = useQuery({
    queryKey: ["branches", workspace.storyId, workspace.taskId],
    queryFn: () => getBranches(workspace.storyId, workspace.taskId),
    enabled: Boolean(workspace.storyId && workspace.taskId)
  });
  const stateQuery = useQuery({
    queryKey: ["state", workspace.storyId, workspace.taskId],
    queryFn: () => getState(workspace.storyId, workspace.taskId),
    enabled: Boolean(workspace.storyId && workspace.taskId)
  });
  const candidatesQuery = useQuery({
    queryKey: ["candidates", workspace.storyId, workspace.taskId],
    queryFn: () => getCandidates(workspace.storyId, workspace.taskId),
    enabled: Boolean(workspace.storyId && workspace.taskId)
  });
  const environmentQuery = useQuery({
    queryKey: [
      "environment",
      workspace.storyId,
      workspace.taskId,
      workspace.sceneType,
      workspace.branchId,
      selection.selectedObjectIds,
      selection.selectedCandidateIds,
      selection.selectedEvidenceIds,
      selection.selectedBranchIds
    ],
    queryFn: () =>
      getEnvironment({
        story_id: workspace.storyId,
        task_id: workspace.taskId,
        scene_type: workspace.sceneType,
        branch_id: workspace.branchId,
        selected_object_ids: selection.selectedObjectIds,
        selected_candidate_ids: selection.selectedCandidateIds,
        selected_evidence_ids: selection.selectedEvidenceIds,
        selected_branch_ids: selection.selectedBranchIds
      }),
    enabled: Boolean(workspace.storyId && workspace.taskId)
  });
  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: getJobs,
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs || [];
      return jobs.some((job) => ["queued", "running"].includes(job.status)) ? 2500 : false;
    }
  });

  useEffect(() => {
    if (!workspace.storyId && storiesQuery.data?.default_story_id) workspace.setStoryId(storiesQuery.data.default_story_id);
  }, [storiesQuery.data?.default_story_id, workspace]);

  useEffect(() => {
    if (!workspace.taskId && tasksQuery.data?.default_task_id) workspace.setTaskId(tasksQuery.data.default_task_id);
  }, [tasksQuery.data?.default_task_id, workspace]);

  useEffect(() => {
    if (!selection.selectedCandidateSetId && candidatesQuery.data?.candidate_sets?.[0]?.candidate_set_id) {
      selection.setSelectedCandidateSetId(candidatesQuery.data.candidate_sets[0].candidate_set_id);
    }
  }, [candidatesQuery.data, selection]);

  const stories = storiesQuery.data?.stories || [];
  const tasks = tasksQuery.data?.tasks || [];
  const branches = branchesQuery.data?.branches || [];
  const jobs = jobsQuery.data?.jobs || [];
  const story = stories.find((item) => item.story_id === workspace.storyId);
  const task = tasks.find((item) => item.task_id === workspace.taskId);
  const stateObjects = (stateQuery.data?.state_objects || []) as StateObject[];
  const candidates = (candidatesQuery.data?.candidate_items || []) as CandidateItem[];
  const evidence = (candidatesQuery.data?.evidence || stateQuery.data?.state_evidence_links || []) as EvidenceLink[];
  const selectedObjects = stateObjects.filter((item) => selection.selectedObjectIds.includes(item.object_id));
  const selectedCandidate = candidates.find((item) => selection.selectedCandidateIds.includes(item.candidate_item_id));
  const selectedEvidence = evidence.filter((item) => {
    if (selection.selectedEvidenceIds.length) return selection.selectedEvidenceIds.includes(item.evidence_id);
    if (selectedCandidate?.evidence_ids?.length) return selectedCandidate.evidence_ids.includes(item.evidence_id);
    return !selectedCandidate || selectedCandidate.target_object_id === item.object_id || selectedCandidate.field_path === item.field_path;
  });
  const pendingCount = useMemo(() => candidates.filter((item) => ["pending_review", "candidate", ""].includes(item.status || "")).length, [candidates]);
  const refreshing =
    healthQuery.isFetching ||
    storiesQuery.isFetching ||
    tasksQuery.isFetching ||
    jobsQuery.isFetching ||
    environmentQuery.isFetching ||
    candidatesQuery.isFetching ||
    stateQuery.isFetching ||
    branchesQuery.isFetching;

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["health"] });
    queryClient.invalidateQueries({ queryKey: ["stories"] });
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["environment"] });
    queryClient.invalidateQueries({ queryKey: ["candidates"] });
    queryClient.invalidateQueries({ queryKey: ["state"] });
    queryClient.invalidateQueries({ queryKey: ["graph"] });
    queryClient.invalidateQueries({ queryKey: ["branches"] });
  };

  const handleModeChange = (nextMode: WorkbenchMode) => {
    setMode(nextMode);
    if (nextMode === "audit") {
      workspace.setSceneType("state_maintenance");
      workspace.setRightPanel("candidate");
      setInspectorOpen(false);
    } else if (nextMode === "graph") {
      workspace.setRightPanel("graph");
      setInspectorOpen(false);
    } else if (nextMode === "status") {
      workspace.setRightPanel("environment");
      setInspectorOpen(false);
    }
  };

  if (storiesQuery.error || tasksQuery.error) {
    return <ErrorState error={storiesQuery.error || tasksQuery.error} />;
  }

  return (
    <div className={`app-shell mode-${mode}`}>
      <TopStatusBar
        story={story}
        task={task}
        environment={environmentQuery.data}
        health={healthQuery.data}
        jobs={jobs}
        mode={mode}
        refreshing={refreshing}
        onModeChange={handleModeChange}
        onRefresh={refreshAll}
      />
      <div className="workspace-grid">
        <WorkspaceNavigator
          stories={stories}
          tasks={tasks}
          branches={branches}
          storyId={workspace.storyId}
          taskId={workspace.taskId}
          sceneType={workspace.sceneType}
          branchId={workspace.branchId}
          pendingCount={pendingCount}
          stateVersion={environmentQuery.data?.working_state_version_no}
          onStoryChange={(storyId) => {
            workspace.setStoryId(storyId);
            selection.clearSelections();
          }}
          onTaskChange={(taskId) => {
            workspace.setTaskId(taskId);
            selection.clearSelections();
          }}
          onSceneChange={(scene) => {
            workspace.setSceneType(scene);
            selection.clearSelections();
          }}
          onBranchChange={(branchId) => {
            workspace.setBranchId(branchId);
            selection.setSelectedBranchIds(branchId ? [branchId] : []);
          }}
          onCreateState={() => {
            workspace.setSceneType("state_creation");
            selection.clearSelections();
          }}
        />
        <main className="workbench-main">
          {mode === "graph" ? (
            <Panel title="图谱">
              <GraphPanel storyId={workspace.storyId} taskId={workspace.taskId} sceneType={workspace.sceneType} />
            </Panel>
          ) : mode === "status" ? (
            <Panel title="状态环境">
              {environmentQuery.isLoading ? <LoadingState label="正在加载状态环境" /> : null}
              {environmentQuery.error ? <ErrorState error={environmentQuery.error} /> : null}
              <StateEnvironmentPanel environment={environmentQuery.data} />
            </Panel>
          ) : mode === "audit" ? (
            <SceneWorkbench
              sceneType={workspace.sceneType}
              storyId={workspace.storyId}
              taskId={workspace.taskId}
              environment={environmentQuery.data}
              candidates={candidates}
              candidateSets={candidatesQuery.data?.candidate_sets || []}
              evidence={evidence}
              candidatesError={candidatesQuery.error}
              selectedCandidateSetId={selection.selectedCandidateSetId}
              selectedCandidateIds={selection.selectedCandidateIds}
              branches={branches}
              onCandidateSetChange={selection.setSelectedCandidateSetId}
              onCandidateOpen={(id) => {
                selection.setSelectedCandidateIds([id]);
                workspace.setRightPanel("candidate");
                setInspectorOpen(true);
              }}
              onCandidateToggle={selection.toggleCandidateId}
              onCandidateSelectionChange={selection.setSelectedCandidateIds}
              selectedBranchIds={selection.selectedBranchIds}
              onBranchSelect={(id) => {
                selection.setSelectedBranchIds([id]);
                workspace.setRightPanel("branch");
              }}
              onOpenContext={() => workspace.setRightPanel("context")}
              onOpenJobs={() => workspace.setRightPanel("jobs")}
              onStartGeneration={() => {
                workspace.setSceneType("continuation_generation");
                workspace.setRightPanel("jobs");
              }}
            />
          ) : (
            <>
              <Panel title="作者对话与动作">
                {environmentQuery.isLoading ? <LoadingState label="正在加载状态环境" /> : null}
                {environmentQuery.error ? <ErrorState error={environmentQuery.error} /> : null}
                <DialogueThread environment={environmentQuery.data} />
              </Panel>
              <SceneWorkbench
                sceneType={workspace.sceneType}
                storyId={workspace.storyId}
                taskId={workspace.taskId}
                environment={environmentQuery.data}
                candidates={candidates}
                candidateSets={candidatesQuery.data?.candidate_sets || []}
                evidence={evidence}
                candidatesError={candidatesQuery.error}
                selectedCandidateSetId={selection.selectedCandidateSetId}
                selectedCandidateIds={selection.selectedCandidateIds}
                branches={branches}
                onCandidateSetChange={selection.setSelectedCandidateSetId}
                onCandidateOpen={(id) => {
                  selection.setSelectedCandidateIds([id]);
                  workspace.setRightPanel("candidate");
                  setInspectorOpen(true);
                }}
                onCandidateToggle={selection.toggleCandidateId}
                onCandidateSelectionChange={selection.setSelectedCandidateIds}
                selectedBranchIds={selection.selectedBranchIds}
                onBranchSelect={(id) => {
                  selection.setSelectedBranchIds([id]);
                  workspace.setRightPanel("branch");
                }}
                onOpenContext={() => workspace.setRightPanel("context")}
                onOpenJobs={() => workspace.setRightPanel("jobs")}
                onStartGeneration={() => {
                  workspace.setSceneType("continuation_generation");
                  workspace.setRightPanel("jobs");
                }}
              />
            </>
          )}
        </main>
        <aside className={`inspector ${inspectorOpen ? "open" : ""}`}>
          <Panel
            title="详情抽屉"
            actions={
              <>
                <InspectorTabs value={workspace.rightPanel} onChange={workspace.setRightPanel} />
                <button className="drawer-close" type="button" aria-label="关闭详情" title="关闭详情" onClick={() => setInspectorOpen(false)}>
                  <X size={15} />
                </button>
              </>
            }
          >
            <RightInspector
              panel={workspace.rightPanel}
              storyId={workspace.storyId}
              taskId={workspace.taskId}
              sceneType={workspace.sceneType}
              environment={environmentQuery.data}
              selectedObjects={selectedObjects}
              selectedCandidate={selectedCandidate}
              selectedEvidence={selectedEvidence}
              branches={branches}
              selectedBranchIds={selection.selectedBranchIds}
            />
          </Panel>
        </aside>
      </div>
    </div>
  );
}

function SceneWorkbench(props: {
  sceneType: SceneType;
  storyId: string;
  taskId: string;
  environment?: StateEnvironment;
  candidates: CandidateItem[];
  candidateSets: CandidateSet[];
  evidence: EvidenceLink[];
  candidatesError?: unknown;
  selectedCandidateSetId: string;
  selectedCandidateIds: string[];
  branches: Branch[];
  onCandidateSetChange: (id: string) => void;
  onCandidateOpen: (id: string) => void;
  onCandidateToggle: (id: string) => void;
  onCandidateSelectionChange: (ids: string[]) => void;
  selectedBranchIds: string[];
  onBranchSelect: (id: string) => void;
  onOpenContext: () => void;
  onOpenJobs: () => void;
  onStartGeneration: () => void;
}) {
  if (props.sceneType === "state_creation") {
    return (
      <Panel title="状态创建">
        <StateCreationPanel environment={props.environment} storyId={props.storyId} taskId={props.taskId} onOpenJobs={props.onOpenJobs} />
      </Panel>
    );
  }
  if (props.sceneType === "analysis_review" || props.sceneType === "state_maintenance") {
    return (
      <Panel title="候选审计">
        {props.candidatesError ? <ErrorState error={props.candidatesError} /> : null}
        <CandidateReviewTable
          storyId={props.storyId}
          taskId={props.taskId}
          candidateSets={props.candidateSets}
          candidates={props.candidates}
          evidence={props.evidence}
          selectedSetId={props.selectedCandidateSetId}
          selectedCandidateIds={props.selectedCandidateIds}
          onSetChange={props.onCandidateSetChange}
          onCandidateOpen={props.onCandidateOpen}
          onCandidateToggle={props.onCandidateToggle}
          onCandidateSelectionChange={props.onCandidateSelectionChange}
        />
      </Panel>
    );
  }
  if (props.sceneType === "plot_planning") {
    return (
      <Panel title="剧情规划">
        <PlotPlanningPanel environment={props.environment} onOpenJobs={props.onOpenJobs} />
      </Panel>
    );
  }
  if (props.sceneType === "continuation_generation") {
    return (
      <Panel title="续写任务">
        <GenerationPanel environment={props.environment} onOpenContext={props.onOpenContext} onOpenJobs={props.onOpenJobs} />
      </Panel>
    );
  }
  if (props.sceneType === "branch_review") {
    return (
      <Panel title="分支审计">
        <BranchReviewPanel
          environment={props.environment}
          branches={props.branches}
          selectedBranchIds={props.selectedBranchIds}
          onSelect={props.onBranchSelect}
          onOpenJobs={props.onOpenJobs}
          onStartGeneration={props.onStartGeneration}
        />
      </Panel>
    );
  }
  return (
    <Panel title="修订">
      <RevisionPanel environment={props.environment} branches={props.branches} selectedBranchIds={props.selectedBranchIds} />
    </Panel>
  );
}

function InspectorTabs({ value, onChange }: { value: RightPanel; onChange: (value: RightPanel) => void }) {
  const items = [
    ["environment", Settings2, "环境"],
    ["object", Boxes, "对象"],
    ["candidate", ListChecks, "候选"],
    ["evidence", ScrollText, "证据"],
    ["graph", Network, "图谱"],
    ["branch", GitBranch, "分支"],
    ["context", Braces, "上下文"],
    ["jobs", BarChart3, "任务"]
  ] as const;
  return (
    <div className="inspector-tabs">
      {items.map(([key, Icon, label]) => (
        <button key={key} className={value === key ? "active" : ""} type="button" title={label} aria-label={label} onClick={() => onChange(key)}>
          <Icon size={15} />
        </button>
      ))}
    </div>
  );
}

function RightInspector(props: {
  panel: RightPanel;
  storyId: string;
  taskId: string;
  sceneType: SceneType;
  environment?: StateEnvironment;
  selectedObjects: StateObject[];
  selectedCandidate?: CandidateItem;
  selectedEvidence: EvidenceLink[];
  branches: Branch[];
  selectedBranchIds: string[];
}) {
  const selection = useSelectionStore();
  const queryClient = useQueryClient();
  const candidateMutation = useMutation({
    mutationFn: (input: { action: string; authority?: string }) => {
      if (!props.selectedCandidate) throw new Error("未选择候选");
      return reviewCandidates(props.storyId, props.taskId, {
        candidate_set_id: props.selectedCandidate.candidate_set_id,
        action: input.action,
        authority: input.authority || "canonical",
        candidate_item_ids: [props.selectedCandidate.candidate_item_id],
        reason: `${input.action} field from diff inspector`
      });
    },
    onSuccess: () => queryClient.invalidateQueries()
  });
  const evidenceMutation = useMutation({
    mutationFn: () => {
      const candidate = props.selectedCandidate;
      return submitJob("search-debug", {
        story_id: props.storyId,
        task_id: props.taskId,
        query: `请为对象 ${candidate?.target_object_id || ""} 的字段 ${candidate?.field_path || "payload"} 检索更多证据。`,
        log_run: true
      });
    },
    onSuccess: () => queryClient.invalidateQueries()
  });
  const editWithModelMutation = useMutation({
    mutationFn: () => {
      const candidate = props.selectedCandidate;
      return submitJob("author-session", {
        story_id: props.storyId,
        task_id: props.taskId,
        seed: `请为对象 ${candidate?.target_object_id || ""} 的字段 ${candidate?.field_path || ""} 创建模型编辑草案。候选值：${JSON.stringify(candidate?.proposed_value ?? candidate?.proposed_payload ?? null)}。不要直接写入主状态。`,
        confirm: false,
        persist: true
      });
    },
    onSuccess: () => queryClient.invalidateQueries()
  });
  const manualEditMutation = useMutation({
    mutationFn: (value: string) => {
      const candidate = props.selectedCandidate;
      return submitJob("edit-state", {
        story_id: props.storyId,
        task_id: props.taskId,
        author_input: `手动编辑候选字段，不直接写入主状态。对象：${candidate?.target_object_id || ""}；字段：${candidate?.field_path || ""}；新候选值：${value}`,
        confirm: false,
        persist: true
      });
    },
    onSuccess: () => queryClient.invalidateQueries()
  });

  if (props.panel === "object") return <StateObjectInspector objects={props.selectedObjects} />;
  if (props.panel === "candidate") {
    return (
      <CandidateDiffPanel
        candidate={props.selectedCandidate}
        evidence={props.selectedEvidence}
        onAccept={() => {
          if (!props.selectedCandidate) return;
          if (Number(props.selectedCandidate.confidence || 0) < 0.65) {
            const confirmation = window.prompt("该字段置信度较低。请输入“确认接受”继续。");
            if (confirmation !== "确认接受") return;
          }
          candidateMutation.mutate({ action: "accept" });
        }}
        onReject={() => props.selectedCandidate && candidateMutation.mutate({ action: "reject" })}
        onLock={() => {
          if (!props.selectedCandidate) return;
          const confirmation = window.prompt("将该字段提升为作者锁定。请输入“确认锁定”继续。");
          if (confirmation === "确认锁定") candidateMutation.mutate({ action: "lock_field", authority: "author_locked" });
        }}
        onRequestEvidence={() => props.selectedCandidate && evidenceMutation.mutate()}
        onEditWithModel={() => props.selectedCandidate && editWithModelMutation.mutate()}
        onEditManually={(value) => props.selectedCandidate && manualEditMutation.mutate(value)}
      />
    );
  }
  if (props.panel === "evidence") return <EvidencePanel evidence={props.selectedEvidence} />;
  if (props.panel === "graph") return <GraphPanel storyId={props.storyId} taskId={props.taskId} sceneType={props.sceneType} />;
  if (props.panel === "branch") {
    return (
      <BranchReviewPanel
        environment={props.environment}
        branches={props.branches}
        selectedBranchIds={props.selectedBranchIds}
        onSelect={(id) => selection.setSelectedBranchIds([id])}
      />
    );
  }
  if (props.panel === "context") return <GenerationContextInspector environment={props.environment} />;
  if (props.panel === "jobs") return <JobLogPanel />;
  return <StateEnvironmentPanel environment={props.environment} />;
}
