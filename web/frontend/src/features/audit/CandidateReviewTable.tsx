import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  ClipboardCheck,
  Copy,
  FileText,
  Lock,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  Trash2,
  X
} from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deriveReviewOutcome, formatReviewDetail, reviewCandidates, type CandidateReviewResponse, type ReviewOutcome } from "../../api/state";
import { formatApiError } from "../../api/client";
import { JsonPreview } from "../../components/data/JsonPreview";
import { IconButton } from "../../components/form/IconButton";
import { StatusPill } from "../../components/data/StatusPill";
import { authorityLabel, objectTypeLabel, operationLabel, sourceRoleLabel, statusLabel } from "../../utils/labels";
import type { CandidateItem, CandidateSet, EvidenceLink } from "../../types/state";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const QUICK_PROMPTS = ["帮我保守审计", "只处理低风险候选", "列出高风险问题", "生成三份审计草案", "解释当前冲突", "把人物关系全部保留待确认"];

type AuditTab = "assistant" | "candidates" | "drafts" | "results";
type RiskLevel = "low" | "medium" | "high" | "critical";
type RiskFilter = "" | RiskLevel | "conflict" | "missing_evidence" | "needs_author";
type DraftActionType = "accept" | "reject" | "conflict" | "keep";
type DraftStatus = "active" | "cancelled" | "executed";

type RiskInfo = {
  level: RiskLevel;
  label: string;
  tone: "good" | "warn" | "bad" | "info";
  reasons: string[];
  recommendedAction: DraftActionType;
  needsAuthor: boolean;
  missingEvidence: boolean;
  hasConflict: boolean;
};

type DraftAction = {
  id: string;
  candidateId: string;
  type: DraftActionType;
  risk: RiskInfo;
  reason: string;
  note: string;
};

type AuditDraft = {
  id: string;
  title: string;
  summary: string;
  risk: RiskLevel;
  status: DraftStatus;
  createdAt: string;
  questions: string[];
  actions: DraftAction[];
};

type AssistantMessage = {
  id: string;
  role: "author" | "assistant";
  text: string;
};

type ExecutionResult = {
  id: string;
  title: string;
  actionId?: string;
  accepted: number;
  rejected: number;
  conflicted: number;
  skipped: number;
  failed: number;
  transitionIds: string[];
  updatedObjectIds: string[];
  failures: Array<{ candidateId: string; reason: string; suggestion: string }>;
  responses: CandidateReviewResponse[];
};

export function CandidateReviewTable({
  storyId,
  taskId,
  candidateSets,
  candidates,
  evidence,
  selectedSetId,
  selectedCandidateIds,
  onSetChange,
  onCandidateOpen,
  onCandidateToggle,
  onCandidateSelectionChange
}: {
  storyId: string;
  taskId: string;
  candidateSets: CandidateSet[];
  candidates: CandidateItem[];
  evidence: EvidenceLink[];
  selectedSetId: string;
  selectedCandidateIds: string[];
  onSetChange: (id: string) => void;
  onCandidateOpen: (id: string) => void;
  onCandidateToggle: (id: string) => void;
  onCandidateSelectionChange?: (ids: string[]) => void;
}) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<AuditTab>("assistant");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [authorityFilter, setAuthorityFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("");
  const [minConfidence, setMinConfidence] = useState(0);
  const [evidenceFilter, setEvidenceFilter] = useState("");
  const [conflictFilter, setConflictFilter] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);
  const [assistantInput, setAssistantInput] = useState("");
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      text: "我会先按风险把候选压缩成可审计草案。你可以直接要求我保守审计、只处理低风险，或列出冲突。"
    }
  ]);
  const [drafts, setDrafts] = useState<AuditDraft[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState("");
  const [executionResults, setExecutionResults] = useState<ExecutionResult[]>([]);

  const setCandidates = useMemo(() => candidates.filter((item) => !selectedSetId || item.candidate_set_id === selectedSetId), [candidates, selectedSetId]);
  const riskMap = useMemo(() => new Map(candidates.map((item) => [item.candidate_item_id, evaluateRisk(item, evidence, candidateSets)])), [candidateSets, candidates, evidence]);
  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    return setCandidates.filter((item) => {
      const sourceRole = effectiveSourceRole(item, candidateSets);
      const authority = item.authority_request || "";
      const evidenceCount = evidenceCountForCandidate(item, evidence);
      const risk = riskMap.get(item.candidate_item_id) || evaluateRisk(item, evidence, candidateSets);
      if (statusFilter && (item.status || "pending_review") !== statusFilter) return false;
      if (typeFilter && (item.target_object_type || "") !== typeFilter) return false;
      if (sourceFilter && sourceRole !== sourceFilter) return false;
      if (authorityFilter && authority !== authorityFilter) return false;
      if (riskFilter && !matchesRiskFilter(risk, riskFilter)) return false;
      if (minConfidence && Number(item.confidence || 0) < minConfidence / 100) return false;
      if (evidenceFilter === "with" && !evidenceCount) return false;
      if (evidenceFilter === "without" && evidenceCount) return false;
      if (conflictFilter === "with" && !risk.hasConflict) return false;
      if (conflictFilter === "without" && risk.hasConflict) return false;
      if (needle && !candidateSearchText(item).includes(needle)) return false;
      return true;
    });
  }, [authorityFilter, candidateSets, conflictFilter, evidence, evidenceFilter, keyword, minConfidence, riskFilter, riskMap, setCandidates, sourceFilter, statusFilter, typeFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageItems = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const selectedCandidates = useMemo(
    () => candidates.filter((item) => selectedCandidateIds.includes(item.candidate_item_id)),
    [candidates, selectedCandidateIds]
  );
  const filteredSelectedCandidates = useMemo(
    () => filtered.filter((item) => selectedCandidateIds.includes(item.candidate_item_id)),
    [filtered, selectedCandidateIds]
  );
  const primaryCandidate = filteredSelectedCandidates[0] || selectedCandidates[0] || pageItems[0] || filtered[0];
  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) || drafts.find((draft) => draft.status === "active") || drafts[0];
  const stats = buildStats(candidates, riskMap);
  const auditProgress = buildAuditProgress(candidates);
  const selectedStats = buildStats(selectedCandidates, riskMap);

  useEffect(() => {
    setPage(1);
  }, [authorityFilter, conflictFilter, evidenceFilter, keyword, minConfidence, pageSize, riskFilter, selectedSetId, sourceFilter, statusFilter, typeFilter]);

  const reviewMutation = useMutation({
    mutationFn: (input: { action: DraftActionType; candidateIds: string[]; title: string }) => executeCandidateAction(input.action, input.candidateIds),
    onSuccess: (responses, variables) => {
      const result = buildExecutionResult(variables.title, responses, variables.action, candidates, variables.candidateIds);
      setExecutionResults((items) => [result, ...items].slice(0, 8));
      refreshWorkbenchQueries(queryClient);
      setActiveTab("results");
    }
  });
  const operationDisabled = reviewMutation.isPending || !selectedCandidateIds.length;

  const draftExecutionMutation = useMutation({
    mutationFn: (draft: AuditDraft) => executeDraft(draft),
    onSuccess: (result, draft) => {
      setExecutionResults((items) => [result, ...items].slice(0, 8));
      setDrafts((items) => items.map((item) => (item.id === draft.id ? { ...item, status: "executed" } : item)));
      refreshWorkbenchQueries(queryClient);
      setActiveTab("results");
    }
  });

  return (
    <div className="audit-page">
      <section className="audit-summary audit-summary-wide">
        <MetricCard label="候选总数" value={candidates.length} />
        <MetricCard label="审计进度" value={auditProgress.progressLabel} tone={stats.pending ? "warn" : "good"} />
        <MetricCard label="处理结果" value={auditProgress.resultLabel} />
        <MetricCard label="最终已接受" value={stats.accepted} tone="good" />
        <MetricCard label="低风险" value={stats.low} tone="good" />
        <MetricCard label="高风险" value={stats.high + stats.critical} tone={stats.high + stats.critical ? "warn" : undefined} />
        <MetricCard label="已选择" value={selectedCandidateIds.length} tone={selectedCandidateIds.length ? "warn" : undefined} />
      </section>

      <section className="audit-workspace-header">
        <div>
          <h3>模型辅助审计</h3>
          <p>
            当前任务：{taskId || "暂无"}，候选筛选后 {filtered.length} 条。建议先让模型生成草案，再执行低风险或已确认项。
          </p>
        </div>
        <IconButton icon={<RefreshCw size={15} />} label="刷新状态" onClick={() => refreshWorkbenchQueries(queryClient)} />
      </section>

      <nav className="audit-tabs" aria-label="候选审计标签">
        <TabButton active={activeTab === "assistant"} label="模型审计" count={drafts.filter((draft) => draft.status === "active").length} onClick={() => setActiveTab("assistant")} />
        <TabButton active={activeTab === "candidates"} label="候选列表" count={filtered.length} onClick={() => setActiveTab("candidates")} />
        <TabButton active={activeTab === "drafts"} label="草案记录" count={drafts.length} onClick={() => setActiveTab("drafts")} />
        <TabButton active={activeTab === "results"} label="执行结果" count={executionResults.length} onClick={() => setActiveTab("results")} />
      </nav>

      {activeTab === "assistant" ? (
        <div className="audit-assistant-layout">
          <section className="audit-assistant-panel">
            <AuditContextSummary storyId={storyId} taskId={taskId} stats={stats} />
            <div className="assistant-messages">
              {messages.map((message) => (
                <article key={message.id} className={`assistant-message ${message.role === "author" ? "author" : "assistant"}`}>
                  <strong>{message.role === "author" ? "作者" : "模型审计助手"}</strong>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>
            <div className="quick-prompts" aria-label="常用快捷指令">
              {QUICK_PROMPTS.map((prompt) => (
                <button key={prompt} type="button" onClick={() => submitAssistantPrompt(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
            <form className="assistant-input" onSubmit={(event) => {
              event.preventDefault();
              submitAssistantPrompt(assistantInput);
            }}>
              <textarea
                value={assistantInput}
                onChange={(event) => setAssistantInput(event.target.value)}
                placeholder="告诉模型你想怎么审计。例如：低风险设定先通过，人物关系保留待确认。"
              />
              <IconButton icon={<Send size={16} />} label="发送" tone="primary" disabled={!assistantInput.trim()} />
            </form>
          </section>

          <aside className="draft-side-panel">
            <div className="toolbar">
              <StatusPill value={`草案 ${drafts.length}`} tone="info" />
              <IconButton icon={<FileText size={15} />} label="生成三份审计草案" onClick={() => createDrafts("three")} />
            </div>
            <DraftCardList
              drafts={drafts}
              selectedDraftId={selectedDraft?.id || ""}
              onSelect={(draftId) => {
                setSelectedDraftId(draftId);
                setActiveTab("drafts");
              }}
              onExecute={(draft) => confirmAndExecuteDraft(draft)}
              onCopy={(draft) => copyDraft(draft)}
              onCancel={(draftId) => cancelDraft(draftId)}
              onRevise={(draft) => reviseDraft(draft)}
            />
          </aside>
        </div>
      ) : null}

      {activeTab === "candidates" ? (
        <>
          <CandidateFilters
            candidateSets={candidateSets}
            setCandidates={setCandidates}
            selectedSetId={selectedSetId}
            statusFilter={statusFilter}
            typeFilter={typeFilter}
            sourceFilter={sourceFilter}
            authorityFilter={authorityFilter}
            riskFilter={riskFilter}
            minConfidence={minConfidence}
            evidenceFilter={evidenceFilter}
            conflictFilter={conflictFilter}
            keyword={keyword}
            onSetChange={onSetChange}
            onStatusChange={setStatusFilter}
            onTypeChange={setTypeFilter}
            onSourceChange={setSourceFilter}
            onAuthorityChange={setAuthorityFilter}
            onRiskChange={setRiskFilter}
            onMinConfidenceChange={setMinConfidence}
            onEvidenceChange={setEvidenceFilter}
            onConflictChange={setConflictFilter}
            onKeywordChange={setKeyword}
          />
          <BulkSelectionBar
            filtered={filtered}
            pageItems={pageItems}
            selectedCandidateIds={selectedCandidateIds}
            selectedStats={selectedStats}
            riskMap={riskMap}
            onSelect={replaceSelection}
            onInvert={() => replaceSelection(invertSelection(filtered, selectedCandidateIds))}
            onCreateDraft={() => createDrafts("selected")}
            onAssistant={() => {
              createDrafts("selected");
              setActiveTab("assistant");
            }}
            onRun={(action) => confirmAndRunBatch(action)}
            disabled={reviewMutation.isPending}
          />
          <div className="audit-readable">
            <section className="audit-list-pane">
              <div className="toolbar audit-toolbar">
                <StatusPill value={`筛选后 ${filtered.length} 条`} tone={filtered.length ? "warn" : "info"} />
                <span className="muted-text">审计进度：{auditProgress.progressLabel}。处理结果：{auditProgress.resultLabel}（前端推导）</span>
              </div>
              <CandidateCardList
                items={pageItems}
                selectedCandidateIds={selectedCandidateIds}
                candidateSets={candidateSets}
                evidence={evidence}
                riskMap={riskMap}
                onCandidateOpen={onCandidateOpen}
                onCandidateToggle={onCandidateToggle}
              />
              <Pagination page={currentPage} totalPages={totalPages} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={setPageSize} />
            </section>

            <section className="audit-detail-pane">
              <OperationState mutationError={reviewMutation.error} />
              <CandidateDetail candidate={primaryCandidate} evidence={evidence} candidateSets={candidateSets} risk={primaryCandidate ? riskMap.get(primaryCandidate.candidate_item_id) : undefined} />
              <div className="audit-actions">
                <IconButton data-testid="candidate-review-accept" icon={<Check size={16} />} label={`批量接受（${selectedCandidateIds.length}）`} tone="good" disabled={operationDisabled} onClick={() => confirmAndRunBatch("accept")} />
                <IconButton data-testid="candidate-review-reject" icon={<X size={16} />} label={`批量拒绝（${selectedCandidateIds.length}）`} tone="danger" disabled={operationDisabled} onClick={() => confirmAndRunBatch("reject")} />
                <IconButton data-testid="candidate-review-conflict" icon={<ShieldAlert size={16} />} label={`标记冲突（${selectedCandidateIds.length}）`} disabled={operationDisabled} onClick={() => confirmAndRunBatch("conflict")} />
                <IconButton data-testid="candidate-review-lock" icon={<Lock size={16} />} label="锁定字段" disabled={operationDisabled} onClick={() => confirmAndRunBatch("accept", "author_locked")} />
              </div>
            </section>
          </div>
        </>
      ) : null}

      {activeTab === "drafts" ? (
        <div className="drafts-workspace">
          <DraftCardList
            drafts={drafts}
            selectedDraftId={selectedDraft?.id || ""}
            onSelect={setSelectedDraftId}
            onExecute={(draft) => confirmAndExecuteDraft(draft)}
            onCopy={(draft) => copyDraft(draft)}
            onCancel={(draftId) => cancelDraft(draftId)}
            onRevise={(draft) => reviseDraft(draft)}
          />
          <DraftDetail
            draft={selectedDraft}
            candidates={candidates}
            onActionChange={updateDraftAction}
            onActionRemove={removeDraftAction}
            onActionNote={updateDraftActionNote}
            onExecute={(draft) => confirmAndExecuteDraft(draft)}
            executing={draftExecutionMutation.isPending}
          />
        </div>
      ) : null}

      {activeTab === "results" ? (
        <ExecutionResults results={executionResults} latestReview={reviewMutation.data?.[0]} latestAction={reviewMutation.variables?.action} error={reviewMutation.error || draftExecutionMutation.error} />
      ) : null}
    </div>
  );

  function replaceSelection(ids: string[]) {
    const uniqueIds = [...new Set(ids)];
    if (onCandidateSelectionChange) {
      onCandidateSelectionChange(uniqueIds);
      return;
    }
    const current = new Set(selectedCandidateIds);
    const next = new Set(uniqueIds);
    selectedCandidateIds.filter((id) => !next.has(id)).forEach(onCandidateToggle);
    uniqueIds.filter((id) => !current.has(id)).forEach(onCandidateToggle);
  }

  function submitAssistantPrompt(rawPrompt: string) {
    const prompt = rawPrompt.trim();
    if (!prompt) return;
    setAssistantInput("");
    const generated = createDrafts(prompt.includes("三份") ? "three" : prompt.includes("低风险") ? "low" : prompt.includes("冲突") || prompt.includes("高风险") ? "risk" : "conservative");
    const response =
      generated.length > 0
        ? `已根据“${prompt}”生成 ${generated.length} 份审计草案。高风险和缺证据项默认保留待确认，低风险项可以直接执行。`
        : `已分析“${prompt}”。当前没有可生成草案的候选，请检查筛选条件或刷新候选。`;
    setMessages((items) => [
      ...items,
      { id: `author-${Date.now()}`, role: "author", text: prompt },
      { id: `assistant-${Date.now()}`, role: "assistant", text: response }
    ]);
  }

  function createDrafts(mode: "conservative" | "low" | "risk" | "three" | "selected"): AuditDraft[] {
    const source = selectedCandidates.length ? selectedCandidates : filtered.length ? filtered : setCandidates;
    const nextDrafts =
      mode === "three"
        ? [buildDraft("保守审计草案", source, "conservative", riskMap), buildDraft("只写入低风险草案", source, "low", riskMap), buildDraft("冲突隔离草案", source, "risk", riskMap)]
        : [buildDraft(mode === "low" ? "低风险通过草案" : mode === "risk" ? "高风险问题草案" : mode === "selected" ? "已选候选审计草案" : "保守审计草案", source, mode === "selected" ? "conservative" : mode, riskMap)];
    const activeDrafts = nextDrafts.filter((draft) => draft.actions.length);
    setDrafts((items) => [...activeDrafts, ...items]);
    if (activeDrafts[0]) setSelectedDraftId(activeDrafts[0].id);
    return activeDrafts;
  }

  function copyDraft(draft: AuditDraft) {
    const copied = {
      ...draft,
      id: `draft-${Date.now()}`,
      title: `${draft.title}（副本）`,
      status: "active" as DraftStatus,
      createdAt: new Date().toLocaleString("zh-CN"),
      actions: draft.actions.map((action) => ({ ...action, id: `${action.id}-copy-${Date.now()}` }))
    };
    setDrafts((items) => [copied, ...items]);
    setSelectedDraftId(copied.id);
  }

  function reviseDraft(draft: AuditDraft) {
    const revised = {
      ...draft,
      id: `draft-${Date.now()}`,
      title: `${draft.title}（模型修改版）`,
      summary: "已按更保守策略调整：高风险、缺证据、人物关系和剧情线默认保留待人工确认。",
      createdAt: new Date().toLocaleString("zh-CN"),
      status: "active" as DraftStatus,
      actions: draft.actions.map((action) => ({
        ...action,
        id: `${action.id}-revise-${Date.now()}`,
        type: action.risk.level === "low" ? action.type : "keep",
        reason: action.risk.level === "low" ? action.reason : "模型修改：该项需要作者确认，暂不写入主状态。"
      }))
    };
    setDrafts((items) => [revised, ...items]);
    setSelectedDraftId(revised.id);
  }

  function cancelDraft(draftId: string) {
    setDrafts((items) => items.map((item) => (item.id === draftId ? { ...item, status: "cancelled" } : item)));
  }

  function updateDraftAction(draftId: string, actionId: string, type: DraftActionType) {
    setDrafts((items) => items.map((draft) => (draft.id === draftId ? { ...draft, actions: draft.actions.map((action) => (action.id === actionId ? { ...action, type } : action)) } : draft)));
  }

  function updateDraftActionNote(draftId: string, actionId: string, note: string) {
    setDrafts((items) => items.map((draft) => (draft.id === draftId ? { ...draft, actions: draft.actions.map((action) => (action.id === actionId ? { ...action, note } : action)) } : draft)));
  }

  function removeDraftAction(draftId: string, actionId: string) {
    setDrafts((items) => items.map((draft) => (draft.id === draftId ? { ...draft, actions: draft.actions.filter((action) => action.id !== actionId) } : draft)));
  }

  function confirmAndRunBatch(action: DraftActionType, authority?: string) {
    if (!selectedCandidateIds.length) return;
    const preview = buildActionPreview(action, selectedCandidates, riskMap);
    const confirmation = window.prompt(`${preview}\n请输入“确认执行”继续。`);
    if (confirmation !== "确认执行") return;
    if (action === "keep") {
      const result = {
        id: `execution-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        title: `保留待审计 ${selectedCandidateIds.length} 个候选`,
        accepted: 0,
        rejected: 0,
        conflicted: 0,
        skipped: selectedCandidateIds.length,
        failed: 0,
        transitionIds: [],
        updatedObjectIds: [],
        failures: [],
        responses: []
      };
      setExecutionResults((items) => [result, ...items].slice(0, 8));
      setActiveTab("results");
      return;
    }
    if (authority === "author_locked") {
      const lockConfirmation = window.prompt(`将把 ${selectedCandidateIds.length} 个候选字段提升为作者锁定。请输入“确认锁定”继续。`);
      if (lockConfirmation !== "确认锁定") return;
    }
    reviewMutation.mutate({
      action: authority === "author_locked" ? "accept" : action,
      candidateIds: selectedCandidateIds,
      title: `${actionLabel(action)} ${selectedCandidateIds.length} 个候选`
    });
  }

  function confirmAndExecuteDraft(draft: AuditDraft) {
    if (draft.status !== "active") return;
    const summary = draftSummary(draft);
    const highRisk = draft.risk === "critical" || draft.risk === "high";
    const requiredText = highRisk ? "确认高风险写入" : "确认执行";
    const confirmation = window.prompt(
      `草案：${draft.title}\n将接受 ${summary.accept} 项，拒绝 ${summary.reject} 项，标记冲突 ${summary.conflict} 项，保留 ${summary.keep} 项。\n请输入“${requiredText}”以执行该审计草案。`
    );
    if (confirmation !== requiredText) return;
    draftExecutionMutation.mutate(draft);
  }

  async function executeDraft(draft: AuditDraft): Promise<ExecutionResult> {
    const actionable = draft.actions.filter((action) => action.type !== "keep");
    const responses: CandidateReviewResponse[] = [];
    for (const actionType of ["accept", "reject", "conflict"] as DraftActionType[]) {
      const ids = actionable.filter((action) => action.type === actionType).map((action) => action.candidateId);
      if (ids.length) {
        const actionResponses = await executeCandidateAction(actionType, ids);
        responses.push(...actionResponses);
      }
    }
    const skipped = draft.actions.filter((action) => action.type === "keep").length;
    return buildExecutionResult(draft.title, responses, "accept", candidates, actionable.map((action) => action.candidateId), skipped);
  }

  async function executeCandidateAction(action: DraftActionType, candidateIds: string[]) {
    if (action === "keep") return [];
    const operation = action === "conflict" ? "conflict" : action;
    const groups = groupCandidatesBySet(candidates.filter((candidate) => candidateIds.includes(candidate.candidate_item_id)));
    const responses: CandidateReviewResponse[] = [];
    for (const group of groups) {
      const response = await reviewCandidates(storyId, taskId, {
        candidate_set_id: group.candidate_set_id,
        action: operation,
        authority: "canonical",
        candidate_item_ids: group.candidate_item_ids,
        reason: `${actionLabel(action)} from audit workspace`
      });
      responses.push(response);
    }
    return responses;
  }
}

function CandidateFilters({
  candidateSets,
  setCandidates,
  selectedSetId,
  statusFilter,
  typeFilter,
  sourceFilter,
  authorityFilter,
  riskFilter,
  minConfidence,
  evidenceFilter,
  conflictFilter,
  keyword,
  onSetChange,
  onStatusChange,
  onTypeChange,
  onSourceChange,
  onAuthorityChange,
  onRiskChange,
  onMinConfidenceChange,
  onEvidenceChange,
  onConflictChange,
  onKeywordChange
}: {
  candidateSets: CandidateSet[];
  setCandidates: CandidateItem[];
  selectedSetId: string;
  statusFilter: string;
  typeFilter: string;
  sourceFilter: string;
  authorityFilter: string;
  riskFilter: RiskFilter;
  minConfidence: number;
  evidenceFilter: string;
  conflictFilter: string;
  keyword: string;
  onSetChange: (id: string) => void;
  onStatusChange: (value: string) => void;
  onTypeChange: (value: string) => void;
  onSourceChange: (value: string) => void;
  onAuthorityChange: (value: string) => void;
  onRiskChange: (value: RiskFilter) => void;
  onMinConfidenceChange: (value: number) => void;
  onEvidenceChange: (value: string) => void;
  onConflictChange: (value: string) => void;
  onKeywordChange: (value: string) => void;
}) {
  return (
    <section className="audit-filters">
      <label className="field compact">
        <span>候选集合</span>
        <select value={selectedSetId} onChange={(event) => onSetChange(event.target.value)}>
          <option value="">全部候选集合</option>
          {candidateSets.map((set) => (
            <option key={set.candidate_set_id} value={set.candidate_set_id}>
              {statusLabel(set.status)} / {set.source_id || shortId(set.candidate_set_id)}
            </option>
          ))}
        </select>
      </label>
      <FilterSelect label="状态" value={statusFilter} onChange={onStatusChange} options={uniqueValues(setCandidates, (item) => item.status || "pending_review")} render={statusLabel} />
      <FilterSelect label="类型" value={typeFilter} onChange={onTypeChange} options={uniqueValues(setCandidates, (item) => item.target_object_type || "")} render={objectTypeLabel} />
      <FilterSelect label="来源" value={sourceFilter} onChange={onSourceChange} options={uniqueValues(setCandidates, (item) => effectiveSourceRole(item, candidateSets))} render={sourceRoleLabel} />
      <FilterSelect label="权威等级" value={authorityFilter} onChange={onAuthorityChange} options={uniqueValues(setCandidates, (item) => item.authority_request || "")} render={authorityLabel} />
      <FilterSelect
        label="风险分组"
        value={riskFilter}
        onChange={(value) => onRiskChange(value as RiskFilter)}
        options={["low", "medium", "high", "critical", "conflict", "missing_evidence", "needs_author"]}
        render={riskFilterLabel}
      />
      <label className="field compact">
        <span>置信度不低于 {minConfidence}%</span>
        <input type="range" min={0} max={100} value={minConfidence} onChange={(event) => onMinConfidenceChange(Number(event.target.value))} />
      </label>
      <FilterSelect label="证据" value={evidenceFilter} onChange={onEvidenceChange} options={["with", "without"]} render={(value) => (value === "with" ? "有证据" : "无证据")} />
      <FilterSelect label="冲突" value={conflictFilter} onChange={onConflictChange} options={["with", "without"]} render={(value) => (value === "with" ? "有冲突" : "无冲突")} />
      <label className="field compact audit-search">
        <span>关键词搜索</span>
        <div className="input-with-icon">
          <Search size={15} />
          <input value={keyword} onChange={(event) => onKeywordChange(event.target.value)} placeholder="对象、字段、候选内容" />
        </div>
      </label>
    </section>
  );
}

function BulkSelectionBar({
  filtered,
  pageItems,
  selectedCandidateIds,
  selectedStats,
  riskMap,
  onSelect,
  onInvert,
  onCreateDraft,
  onAssistant,
  onRun,
  disabled
}: {
  filtered: CandidateItem[];
  pageItems: CandidateItem[];
  selectedCandidateIds: string[];
  selectedStats: ReturnType<typeof buildStats>;
  riskMap: Map<string, RiskInfo>;
  onSelect: (ids: string[]) => void;
  onInvert: () => void;
  onCreateDraft: () => void;
  onAssistant: () => void;
  onRun: (action: DraftActionType) => void;
  disabled: boolean;
}) {
  const selectedCount = selectedCandidateIds.length;
  const lowRiskIds = filtered.filter((item) => riskMap.get(item.candidate_item_id)?.level === "low").map((item) => item.candidate_item_id);
  const mediumRiskIds = filtered.filter((item) => riskMap.get(item.candidate_item_id)?.level === "medium").map((item) => item.candidate_item_id);
  const highRiskIds = filtered.filter((item) => ["high", "critical"].includes(riskMap.get(item.candidate_item_id)?.level || "")).map((item) => item.candidate_item_id);
  const missingEvidenceIds = filtered.filter((item) => riskMap.get(item.candidate_item_id)?.missingEvidence).map((item) => item.candidate_item_id);
  return (
    <section className="bulk-action-bar">
      <div className="bulk-selection-controls">
        <StatusPill value={`已选择 ${selectedCount}`} tone={selectedCount ? "warn" : "info"} />
        <button type="button" onClick={() => onSelect(pageItems.map((item) => item.candidate_item_id))}>
          全选当前页
        </button>
        <button type="button" onClick={() => onSelect(filtered.map((item) => item.candidate_item_id))}>
          全选当前筛选结果
        </button>
        <button type="button" onClick={() => onSelect([])}>
          取消选择
        </button>
        <button type="button" onClick={onInvert}>
          反选
        </button>
        <button type="button" onClick={() => onSelect(lowRiskIds)}>
          仅选择低风险
        </button>
        <button type="button" onClick={() => onSelect(mediumRiskIds)}>
          仅选择中风险
        </button>
        <button type="button" onClick={() => onSelect(highRiskIds)}>
          仅选择高风险
        </button>
        <button type="button" onClick={() => onSelect(missingEvidenceIds)}>
          仅选择缺证据项
        </button>
      </div>
      <div className="bulk-action-controls">
        <span className="muted-text">
          已选风险：低 {selectedStats.low} / 中 {selectedStats.medium} / 高 {selectedStats.high} / 极高 {selectedStats.critical}
        </span>
        <IconButton icon={<Check size={15} />} label={`批量接受（${selectedCount}）`} tone="good" disabled={disabled || !selectedCount} onClick={() => onRun("accept")} />
        <IconButton icon={<X size={15} />} label={`批量拒绝（${selectedCount}）`} tone="danger" disabled={disabled || !selectedCount} onClick={() => onRun("reject")} />
        <IconButton icon={<ShieldAlert size={15} />} label={`标记冲突（${selectedCount}）`} disabled={disabled || !selectedCount} onClick={() => onRun("conflict")} />
        <IconButton icon={<AlertTriangle size={15} />} label={`保留待审计（${selectedCount}）`} disabled={disabled || !selectedCount} onClick={() => onRun("keep")} />
        <IconButton icon={<ClipboardCheck size={15} />} label={`生成草案（${selectedCount}）`} disabled={!selectedCount} onClick={onCreateDraft} />
        <IconButton icon={<Bot size={15} />} label={`交给模型审计（${selectedCount}）`} tone="primary" disabled={!selectedCount} onClick={onAssistant} />
      </div>
    </section>
  );
}

function CandidateCardList({
  items,
  selectedCandidateIds,
  candidateSets,
  evidence,
  riskMap,
  onCandidateOpen,
  onCandidateToggle
}: {
  items: CandidateItem[];
  selectedCandidateIds: string[];
  candidateSets: CandidateSet[];
  evidence: EvidenceLink[];
  riskMap: Map<string, RiskInfo>;
  onCandidateOpen: (id: string) => void;
  onCandidateToggle: (id: string) => void;
}) {
  return (
    <div className="candidate-card-list" data-testid="candidate-list">
      {items.map((item) => {
        const selected = selectedCandidateIds.includes(item.candidate_item_id);
        const risk = riskMap.get(item.candidate_item_id) || evaluateRisk(item, evidence, candidateSets);
        const final = finalCandidateState(item);
        return (
          <article key={item.candidate_item_id} className={`candidate-summary-card candidate-final-${final.tone} ${selected ? "selected" : ""}`} onClick={() => onCandidateOpen(item.candidate_item_id)}>
            <label className="candidate-check" onClick={(event) => event.stopPropagation()} title="选择候选">
              <input type="checkbox" checked={selected} onChange={() => onCandidateToggle(item.candidate_item_id)} />
            </label>
            <div className="candidate-summary-main">
              <div className="candidate-summary-title">
                <strong>{candidateName(item)}</strong>
                <StatusPill value={final.label} tone={final.tone} />
              </div>
              <div className="candidate-summary-meta">
                <span>类型：{objectTypeLabel(item.target_object_type)}</span>
                <span>字段：{item.field_path || "payload"}</span>
                <span>操作：{operationLabel(item.operation || "upsert")}</span>
                <span>审计来源：{auditSourceLabel(item)}</span>
              </div>
              <p>{summarizeValue(item.proposed_value ?? item.proposed_payload)}</p>
              <div className="candidate-summary-meta">
                <span>置信度 {Math.round(Number(item.confidence || 0) * 100)}%</span>
                <span>来源 {sourceRoleLabel(effectiveSourceRole(item, candidateSets))}</span>
                <span>证据 {evidenceCountForCandidate(item, evidence)}</span>
                <span>原始风险：{risk.label}</span>
              </div>
            </div>
          </article>
        );
      })}
      {!items.length ? <div className="empty-state">当前任务无候选，或筛选条件下没有候选。</div> : null}
    </div>
  );
}

function CandidateDetail({ candidate, evidence, candidateSets, risk }: { candidate?: CandidateItem; evidence: EvidenceLink[]; candidateSets: CandidateSet[]; risk?: RiskInfo }) {
  if (!candidate) return <div className="empty-state">请选择一个候选查看修改前后、证据和完整数据。</div>;
  const linkedEvidence = evidenceForCandidate(candidate, evidence);
  const riskInfo = risk || evaluateRisk(candidate, evidence, candidateSets);
  const final = finalCandidateState(candidate);
  return (
    <article className="candidate-detail-card">
      <header>
        <div>
          <h3>候选详情</h3>
          <p>字段路径：{candidate.field_path || "payload"}</p>
        </div>
        <div className="pill-row">
          <StatusPill value={final.label} tone={final.tone} />
          <StatusPill value={`原始风险：${riskInfo.label}`} tone={riskInfo.tone} />
        </div>
      </header>
      <section className={`risk-explain risk-${riskInfo.level}`}>
        <strong>原始风险与审计前建议</strong>
        <p>{riskInfo.reasons.join("；") || "暂无风险原因。"}</p>
        <div className="candidate-summary-meta">
          <span>审计前建议：{actionLabel(riskInfo.recommendedAction)}</span>
          <span>审计来源：{auditSourceLabel(candidate)}</span>
          <span>需要作者确认：{riskInfo.needsAuthor ? "是" : "否"}</span>
          <span>作者锁定保护：{candidate.authority_request === "author_locked" ? "是" : "否"}</span>
          <span>参考文本覆盖主状态：{effectiveSourceRole(candidate, candidateSets).includes("reference") ? "可能涉及" : "未发现"}</span>
        </div>
      </section>
      <div className="key-value-list compact">
        <DetailRow label="候选编号 candidate_item_id" value={candidate.candidate_item_id} />
        <DetailRow label="候选集合 candidate_set_id" value={candidate.candidate_set_id} />
        <DetailRow label="目标对象 target_object_id" value={candidate.target_object_id || "-"} />
        <DetailRow label="对象类型" value={objectTypeLabel(candidate.target_object_type)} />
        <DetailRow label="操作类型" value={operationLabel(candidate.operation || "upsert")} />
        <DetailRow label="来源角色" value={sourceRoleLabel(effectiveSourceRole(candidate, candidateSets))} />
        <DetailRow label="权威等级" value={authorityLabel(candidate.authority_request)} />
        <DetailRow label="置信度" value={`${Math.round(Number(candidate.confidence || 0) * 100)}%`} />
      </div>
      {candidate.conflict_reason ? <div className="notice notice-warn">冲突原因：{candidate.conflict_reason}</div> : null}
      <div className="diff-grid">
        <section>
          <h4>修改前</h4>
          <pre>{formatValue(candidate.before_value)}</pre>
        </section>
        <section>
          <h4>修改后</h4>
          <pre>{formatValue(candidate.proposed_value ?? candidate.proposed_payload)}</pre>
        </section>
      </div>
      <section className="candidate-evidence-section">
        <h4>证据</h4>
        {linkedEvidence.length ? (
          <div className="candidate-evidence-list">
            {linkedEvidence.slice(0, 10).map((item) => (
              <article key={item.evidence_id} className="evidence-card">
                <header>
                  <strong>证据编号：{item.evidence_id}</strong>
                  <StatusPill value={item.support_type || item.evidence_type || "证据"} tone="info" />
                </header>
                <p>{item.quote_text || "暂无摘录文本。"}</p>
                <div className="candidate-summary-meta">
                  <span>来源文档：{item.source_document || "未知"}</span>
                  <span>字段：{item.field_path || "对象"}</span>
                  <span>置信度：{Math.round(Number(item.confidence ?? item.score ?? 0) * 100)}%</span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state compact-empty">暂无证据。缺证据项建议先保留待确认或补充检索。</div>
        )}
      </section>
      <JsonPreview title="展开完整候选内容" value={candidate} />
    </article>
  );
}

function DraftCardList({
  drafts,
  selectedDraftId,
  onSelect,
  onExecute,
  onCopy,
  onCancel,
  onRevise
}: {
  drafts: AuditDraft[];
  selectedDraftId: string;
  onSelect: (draftId: string) => void;
  onExecute: (draft: AuditDraft) => void;
  onCopy: (draft: AuditDraft) => void;
  onCancel: (draftId: string) => void;
  onRevise: (draft: AuditDraft) => void;
}) {
  if (!drafts.length) return <div className="empty-state">暂无草案。发送审计策略或点击“生成三份审计草案”。</div>;
  return (
    <div className="draft-card-list">
      {drafts.map((draft) => {
        const summary = draftSummary(draft);
        return (
          <article key={draft.id} className={`draft-card risk-${draft.risk} ${selectedDraftId === draft.id ? "selected" : ""}`}>
            <header>
              <div>
                <h4>{draft.title}</h4>
                <p>草案编号 draft_id：{draft.id}</p>
              </div>
              <StatusPill value={riskLabel(draft.risk)} tone={riskTone(draft.risk)} />
            </header>
            <p>{draft.summary}</p>
            <div className="draft-count-grid">
              <span>接受 {summary.accept}</span>
              <span>拒绝 {summary.reject}</span>
              <span>冲突 {summary.conflict}</span>
              <span>保留 {summary.keep}</span>
            </div>
            <div className="candidate-summary-meta">
              <span>预计状态写入：{summary.accept} 项</span>
              <span>预计迁移：{summary.accept + summary.reject + summary.conflict} 条</span>
              <span>状态：{draftStatusLabel(draft.status)}</span>
            </div>
            {draft.questions.length ? (
              <ul className="draft-question-list">
                {draft.questions.slice(0, 3).map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            ) : null}
            <div className="draft-actions">
              <IconButton icon={<FileText size={15} />} label="查看详情" onClick={() => onSelect(draft.id)} />
              <IconButton icon={<Play size={15} />} label="执行草案" tone="primary" disabled={draft.status !== "active"} onClick={() => onExecute(draft)} />
              <IconButton icon={<Copy size={15} />} label="复制为新草案" onClick={() => onCopy(draft)} />
              <IconButton icon={<Trash2 size={15} />} label="取消草案" disabled={draft.status !== "active"} onClick={() => onCancel(draft.id)} />
              <IconButton icon={<Bot size={15} />} label="让模型修改草案" disabled={draft.status !== "active"} onClick={() => onRevise(draft)} />
            </div>
          </article>
        );
      })}
    </div>
  );
}

function DraftDetail({
  draft,
  candidates,
  onActionChange,
  onActionRemove,
  onActionNote,
  onExecute,
  executing
}: {
  draft?: AuditDraft;
  candidates: CandidateItem[];
  onActionChange: (draftId: string, actionId: string, type: DraftActionType) => void;
  onActionRemove: (draftId: string, actionId: string) => void;
  onActionNote: (draftId: string, actionId: string, note: string) => void;
  onExecute: (draft: AuditDraft) => void;
  executing: boolean;
}) {
  if (!draft) return <div className="empty-state">请选择一份草案查看动作项。</div>;
  const summary = draftSummary(draft);
  return (
    <section className="draft-detail-panel">
      <header>
        <div>
          <h3>草案详情与人工调整</h3>
          <p>
            {draft.title}，接受 {summary.accept}，拒绝 {summary.reject}，冲突 {summary.conflict}，保留 {summary.keep}
          </p>
        </div>
        <IconButton icon={<Play size={15} />} label="执行草案" tone="primary" disabled={executing || draft.status !== "active"} onClick={() => onExecute(draft)} />
      </header>
      <div className="draft-action-list">
        {draft.actions.map((action) => {
          const candidate = candidates.find((item) => item.candidate_item_id === action.candidateId);
          return (
            <article key={action.id} className={`draft-action-item risk-${action.risk.level}`}>
              <div>
                <strong>{candidate ? candidateName(candidate) : action.candidateId}</strong>
                <p>候选编号 candidate_item_id：{action.candidateId}</p>
                <p>{action.reason}</p>
              </div>
              <div className="draft-action-controls">
                <StatusPill value={action.risk.label} tone={action.risk.tone} />
                <label>
                  动作类型
                  <select value={action.type} onChange={(event) => onActionChange(draft.id, action.id, event.target.value as DraftActionType)}>
                    <option value="accept">接受</option>
                    <option value="reject">拒绝</option>
                    <option value="conflict">冲突</option>
                    <option value="keep">保留</option>
                  </select>
                </label>
                <label>
                  备注
                  <input value={action.note} onChange={(event) => onActionNote(draft.id, action.id, event.target.value)} placeholder="给该动作加备注" />
                </label>
                <button type="button" onClick={() => onActionRemove(draft.id, action.id)}>
                  删除动作项
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ExecutionResults({
  results,
  latestReview,
  latestAction,
  error
}: {
  results: ExecutionResult[];
  latestReview?: CandidateReviewResponse;
  latestAction?: DraftActionType;
  error?: unknown;
}) {
  const outcome = latestReview ? deriveReviewOutcome(latestReview, latestAction) : undefined;
  return (
    <section className="execution-result-panel">
      <h3>执行结果</h3>
      {error ? (
        <div className="error-state readable-error">
          <pre>{formatApiError(error)}</pre>
        </div>
      ) : null}
      {outcome && latestReview ? <ReviewResult outcome={outcome} data={latestReview} /> : null}
      {!results.length ? <div className="empty-state">暂无执行结果。批量操作或执行草案后会在这里长期保留。</div> : null}
      {results.map((result) => (
        <article key={result.id} className="execution-result-card" data-testid="candidate-review-result">
          <header>
            <div>
              <strong>执行完成：{result.title}</strong>
              <p>动作编号 action_id：{result.actionId || "-"}</p>
            </div>
            <StatusPill value={result.failed ? "执行失败" : "执行完成"} tone={result.failed ? "bad" : "good"} />
          </header>
          <div className="draft-count-grid">
            <span>已接受：{result.accepted}</span>
            <span>已拒绝：{result.rejected}</span>
            <span>已标记冲突：{result.conflicted}</span>
            <span>已跳过：{result.skipped}</span>
            <span>失败：{result.failed}</span>
          </div>
          <div className="candidate-summary-meta">
            <span>迁移编号 transition_id：{result.transitionIds.length ? result.transitionIds.join(", ") : "-"}</span>
            <span>更新对象：{result.updatedObjectIds.length ? result.updatedObjectIds.join(", ") : "-"}</span>
          </div>
          {result.failures.length ? (
            <details>
              <summary>失败项展开</summary>
              {result.failures.map((failure) => (
                <div key={failure.candidateId} className="failure-row">
                  <strong>候选编号：{failure.candidateId}</strong>
                  <span>失败原因：{failure.reason}</span>
                  <span>建议下一步：{failure.suggestion}</span>
                </div>
              ))}
            </details>
          ) : null}
        </article>
      ))}
    </section>
  );
}

function AuditContextSummary({ storyId, taskId, stats }: { storyId: string; taskId: string; stats: ReturnType<typeof buildStats> }) {
  return (
    <section className="audit-context-summary">
      <header>
        <Bot size={18} />
        <strong>审计上下文摘要</strong>
      </header>
      <div className="key-value-list compact">
        <DetailRow label="当前小说" value={storyId || "暂无"} />
        <DetailRow label="当前任务" value={taskId || "暂无"} />
        <DetailRow label="候选总数" value={String(stats.total)} />
        <DetailRow label="待审计" value={String(stats.pending)} />
      </div>
      <div className="risk-distribution">
        <span>低风险：{stats.low}</span>
        <span>中风险：{stats.medium}</span>
        <span>高风险：{stats.high}</span>
        <span>极高风险：{stats.critical}</span>
      </div>
      <ol>
        <li>先接受低风险地点、术语、世界规则。</li>
        <li>人物整卡、关系和剧情线保留待人工确认。</li>
        <li>冲突和缺证据项先隔离，不直接写入主状态。</li>
      </ol>
    </section>
  );
}

function OperationState({ mutationError }: { mutationError: unknown }) {
  if (!mutationError) return null;
  return (
    <div className="error-state readable-error">
      <pre>{formatApiError(mutationError)}</pre>
    </div>
  );
}

function ReviewResult({ outcome, data }: { outcome: ReviewOutcome; data: CandidateReviewResponse }) {
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];
  const blocking = Array.isArray(data.blocking_issues) ? data.blocking_issues : [];
  return (
    <div className={`review-result review-result-${outcome.tone}`}>
      <strong>操作结果</strong>
      <span>动作编号 action_id：{String(data.action_id || "-")}</span>
      <span>已接受 {outcome.accepted}</span>
      <span>已拒绝 {outcome.rejected}</span>
      <span>有冲突 {outcome.conflicted}</span>
      <span>已跳过 {outcome.skipped}</span>
      <span>迁移数量 {outcome.transitionCount}</span>
      <span>更新对象 {outcome.updatedObjectCount}</span>
      {warnings.map((warning, index) => (
        <span key={`warning-${index}`}>警告：{formatReviewDetail(warning)}</span>
      ))}
      {blocking.map((issue, index) => (
        <span key={`blocking-${index}`}>阻塞：{formatReviewDetail(issue)}</span>
      ))}
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  pageSize,
  onPageChange,
  onPageSizeChange
}: {
  page: number;
  totalPages: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  return (
    <div className="pagination-bar">
      <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        上一页
      </button>
      <span>
        第 {page} 页 / 共 {totalPages} 页
      </span>
      <button type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
        下一页
      </button>
      <label>
        跳转页码
        <input type="number" min={1} max={totalPages} value={page} onChange={(event) => onPageChange(Math.min(totalPages, Math.max(1, Number(event.target.value) || 1)))} />
      </label>
      <label>
        每页数量
        <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size} 条
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  render = (item: string) => item
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  render?: (value: string) => string;
}) {
  return (
    <label className="field compact">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">全部</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {render(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function TabButton({ active, label, count, onClick }: { active: boolean; label: string; count: number; onClick: () => void }) {
  return (
    <button type="button" className={active ? "active" : ""} onClick={onClick} aria-pressed={active}>
      {label}
      <span>{count}</span>
    </button>
  );
}

function MetricCard({ label, value, tone }: { label: string; value: string | number; tone?: "good" | "warn" }) {
  return (
    <div className={`metric ${tone ? `metric-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

function evaluateRisk(candidate: CandidateItem, evidence: EvidenceLink[], candidateSets: CandidateSet[]): RiskInfo {
  const confidence = Number(candidate.confidence || 0);
  const evidenceCount = evidenceCountForCandidate(candidate, evidence);
  const objectType = candidate.target_object_type || "";
  const sourceRole = effectiveSourceRole(candidate, candidateSets);
  const hasConflict = Boolean(candidate.conflict_reason || candidate.status === "conflicted");
  const missingEvidence = evidenceCount <= 0;
  const broadType = ["relationship", "plot_thread", "character", "character_relation"].includes(objectType);
  const authorLocked = candidate.authority_request === "author_locked";
  const reasons: string[] = [];
  if (hasConflict) reasons.push(candidate.conflict_reason ? `存在冲突：${candidate.conflict_reason}` : "候选状态已标记为冲突");
  if (authorLocked) reasons.push("涉及作者锁定字段");
  if (missingEvidence) reasons.push("缺少证据支撑");
  if (confidence < 0.65) reasons.push("置信度低于 65%");
  if (broadType) reasons.push("涉及人物、关系或剧情线等高影响对象");
  if (sourceRole.includes("reference")) reasons.push("可能涉及参考文本覆盖主状态");
  if (!reasons.length) reasons.push("置信度和证据满足自动审计条件");

  if (hasConflict || authorLocked) {
    return { level: "critical", label: "极高风险", tone: "bad", reasons, recommendedAction: "conflict", needsAuthor: true, missingEvidence, hasConflict };
  }
  if (confidence >= 0.85 && !missingEvidence && !broadType) {
    return { level: "low", label: "低风险", tone: "good", reasons, recommendedAction: "accept", needsAuthor: false, missingEvidence, hasConflict };
  }
  if (confidence >= 0.65 && !missingEvidence && !broadType) {
    return { level: "medium", label: "中风险", tone: "warn", reasons, recommendedAction: "accept", needsAuthor: true, missingEvidence, hasConflict };
  }
  return { level: "high", label: "高风险", tone: "bad", reasons, recommendedAction: missingEvidence ? "keep" : "conflict", needsAuthor: true, missingEvidence, hasConflict };
}

function buildStats(items: CandidateItem[], riskMap: Map<string, RiskInfo>) {
  return {
    total: items.length,
    pending: items.filter((item) => ["pending_review", "candidate", ""].includes(item.status || "")).length,
    accepted: items.filter((item) => item.status === "accepted").length,
    rejected: items.filter((item) => item.status === "rejected").length,
    conflicted: items.filter((item) => item.status === "conflicted" || item.conflict_reason).length,
    low: items.filter((item) => riskMap.get(item.candidate_item_id)?.level === "low").length,
    medium: items.filter((item) => riskMap.get(item.candidate_item_id)?.level === "medium").length,
    high: items.filter((item) => riskMap.get(item.candidate_item_id)?.level === "high").length,
    critical: items.filter((item) => riskMap.get(item.candidate_item_id)?.level === "critical").length
  };
}

function buildAuditProgress(items: CandidateItem[]) {
  const accepted = items.filter((item) => item.status === "accepted").length;
  const rejected = items.filter((item) => item.status === "rejected").length;
  const conflicted = items.filter((item) => item.status === "conflicted" || item.conflict_reason).length;
  const pending = items.filter((item) => ["pending_review", "candidate", ""].includes(item.status || "")).length;
  const progressLabel = !items.length ? "无候选" : pending === 0 ? "已全部处理" : accepted || rejected || conflicted ? "部分处理" : "未处理";
  const resultLabel =
    pending === 0 && accepted === items.length
      ? "全部接受"
      : pending === 0 && rejected === items.length
        ? "全部拒绝"
        : `接受 ${accepted} / 拒绝 ${rejected} / 待审 ${pending}`;
  return { accepted, rejected, conflicted, pending, progressLabel, resultLabel };
}

function finalCandidateState(candidate: CandidateItem): { label: string; tone: "good" | "warn" | "bad" | "info" } {
  if (candidate.status === "accepted") return { label: "最终已接受", tone: "good" };
  if (candidate.status === "rejected") return { label: "最终已拒绝", tone: "bad" };
  if (candidate.status === "conflicted" || candidate.conflict_reason) return { label: "已标记冲突", tone: "warn" };
  return { label: "保留待审", tone: "info" };
}

function auditSourceLabel(candidate: CandidateItem): string {
  const extended = candidate as CandidateItem & { metadata?: Record<string, unknown> };
  const metadata = extended.metadata && typeof extended.metadata === "object" ? extended.metadata : {};
  const source = String(metadata.audit_source || metadata.review_source || metadata.confirmed_by || metadata.source || "");
  if (source === "author" || source === "author_action" || candidate.authority_request === "author_locked") return "作者确认";
  if (source.includes("model") || source.includes("llm")) return "模型草案";
  if (source.includes("batch") || source.includes("rule")) return "批量规则";
  if (candidate.status === "accepted" || candidate.status === "rejected" || candidate.status === "conflicted") return "手动按钮";
  return "尚未处理";
}

function buildDraft(title: string, items: CandidateItem[], mode: "conservative" | "low" | "risk", riskMap: Map<string, RiskInfo>): AuditDraft {
  const actions = items.map((candidate) => {
    const risk = riskMap.get(candidate.candidate_item_id) || evaluateRisk(candidate, [], []);
    let type: DraftActionType = risk.recommendedAction;
    if (mode === "low") type = risk.level === "low" ? "accept" : "keep";
    if (mode === "risk") type = risk.hasConflict ? "conflict" : risk.level === "high" || risk.level === "critical" ? "keep" : "accept";
    if (mode === "conservative" && risk.level !== "low") type = risk.hasConflict ? "conflict" : "keep";
    return {
      id: `${candidate.candidate_item_id}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      candidateId: candidate.candidate_item_id,
      type,
      risk,
      reason: risk.reasons.join("；"),
      note: ""
    };
  });
  const worstRisk = worstRiskLevel(actions.map((action) => action.risk.level));
  const summary = summarizeDraftActions(actions);
  return {
    id: `draft-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    title,
    summary,
    risk: worstRisk,
    status: "active",
    createdAt: new Date().toLocaleString("zh-CN"),
    questions: buildDraftQuestions(actions),
    actions
  };
}

function buildDraftQuestions(actions: DraftAction[]): string[] {
  const questions = [];
  if (actions.some((action) => action.risk.missingEvidence)) questions.push("缺证据项是否需要补充检索后再审计？");
  if (actions.some((action) => action.risk.level === "critical")) questions.push("极高风险冲突是否由作者确认后再写入？");
  if (actions.some((action) => action.type === "keep")) questions.push("保留项是否需要下一轮模型专门解释？");
  return questions;
}

function summarizeDraftActions(actions: DraftAction[]): string {
  const summary = draftSummary({ actions } as AuditDraft);
  return `本草案将接受 ${summary.accept} 项、拒绝 ${summary.reject} 项、标记冲突 ${summary.conflict} 项、保留 ${summary.keep} 项。`;
}

function draftSummary(draft: AuditDraft) {
  return {
    accept: draft.actions.filter((action) => action.type === "accept").length,
    reject: draft.actions.filter((action) => action.type === "reject").length,
    conflict: draft.actions.filter((action) => action.type === "conflict").length,
    keep: draft.actions.filter((action) => action.type === "keep").length
  };
}

function buildActionPreview(action: DraftActionType, selectedCandidates: CandidateItem[], riskMap: Map<string, RiskInfo>): string {
  const stats = buildStats(selectedCandidates, riskMap);
  const transitionEstimate = action === "accept" ? selectedCandidates.length : action === "keep" ? 0 : selectedCandidates.length;
  return `本次将${actionLabel(action)} ${selectedCandidates.length} 个候选。\n其中低风险 ${stats.low} 个，中风险 ${stats.medium} 个，高风险 ${stats.high} 个，极高风险 ${stats.critical} 个。\n预计产生 ${transitionEstimate} 条状态迁移。`;
}

function buildExecutionResult(title: string, responses: CandidateReviewResponse[], operation: DraftActionType, candidates: CandidateItem[], candidateIds: string[], skipped = 0): ExecutionResult {
  const outcomes = responses.map((response) => deriveReviewOutcome(response, operation));
  const accepted = outcomes.reduce((sum, item) => sum + item.accepted, 0);
  const rejected = outcomes.reduce((sum, item) => sum + item.rejected, 0);
  const conflicted = outcomes.reduce((sum, item) => sum + item.conflicted, 0);
  const responseSkipped = outcomes.reduce((sum, item) => sum + item.skipped, 0);
  const failures = responses.flatMap((response) => {
    const blocking = Array.isArray(response.blocking_issues) ? response.blocking_issues : [];
    return blocking.map((issue, index) => ({
      candidateId: candidateIds[index] || candidates[index]?.candidate_item_id || "-",
      reason: formatReviewDetail(issue),
      suggestion: "查看候选详情，补充证据或改为保留待审计。"
    }));
  });
  return {
    id: `execution-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    title,
    actionId: responses.map((response) => response.action_id).filter(Boolean).join(", "),
    accepted,
    rejected,
    conflicted,
    skipped: responseSkipped + skipped,
    failed: failures.length,
    transitionIds: responses.flatMap((response) => (Array.isArray(response.transition_ids) ? response.transition_ids : [])),
    updatedObjectIds: responses.flatMap((response) => (Array.isArray(response.updated_object_ids) ? response.updated_object_ids : [])),
    failures,
    responses
  };
}

function groupCandidatesBySet(items: CandidateItem[]) {
  const groups = new Map<string, string[]>();
  items.forEach((item) => {
    const current = groups.get(item.candidate_set_id) || [];
    current.push(item.candidate_item_id);
    groups.set(item.candidate_set_id, current);
  });
  return [...groups.entries()].map(([candidate_set_id, candidate_item_ids]) => ({ candidate_set_id, candidate_item_ids }));
}

function refreshWorkbenchQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["candidates"] });
  queryClient.invalidateQueries({ queryKey: ["environment"] });
  queryClient.invalidateQueries({ queryKey: ["state"] });
  queryClient.invalidateQueries({ queryKey: ["graph"] });
  queryClient.invalidateQueries({ queryKey: ["tasks"] });
  queryClient.invalidateQueries({ queryKey: ["jobs"] });
}

function matchesRiskFilter(risk: RiskInfo, filter: RiskFilter): boolean {
  if (!filter) return true;
  if (filter === "conflict") return risk.hasConflict;
  if (filter === "missing_evidence") return risk.missingEvidence;
  if (filter === "needs_author") return risk.needsAuthor;
  return risk.level === filter;
}

function invertSelection(items: CandidateItem[], selectedIds: string[]): string[] {
  const selected = new Set(selectedIds);
  return items.filter((item) => !selected.has(item.candidate_item_id)).map((item) => item.candidate_item_id);
}

function evidenceCountForCandidate(candidate: CandidateItem, evidence: EvidenceLink[]): number {
  return candidate.evidence_count ?? candidate.evidence_ids?.length ?? evidenceForCandidate(candidate, evidence).length;
}

function effectiveSourceRole(candidate: CandidateItem, candidateSets: CandidateSet[]): string {
  if (candidate.source_role) return candidate.source_role;
  const payload = candidate.proposed_payload || {};
  const fromPayload = payload.source_role || payload.sourceRole;
  if (fromPayload) return String(fromPayload);
  const set = candidateSets.find((item) => item.candidate_set_id === candidate.candidate_set_id);
  const metadata = set?.metadata || {};
  return String(metadata.source_role || metadata.sourceRole || set?.source_type || "");
}

function candidateName(candidate: CandidateItem): string {
  const payload = candidate.proposed_payload || {};
  return String(payload.display_name || payload.name || payload.title || candidate.target_object_id || summarizeValue(candidate.proposed_value ?? candidate.proposed_payload));
}

function candidateSearchText(candidate: CandidateItem): string {
  return [
    candidate.candidate_item_id,
    candidate.candidate_set_id,
    candidate.target_object_id,
    candidate.target_object_type,
    candidate.field_path,
    candidate.operation,
    candidate.status,
    candidate.authority_request,
    candidate.source_role,
    formatValue(candidate.proposed_value ?? candidate.proposed_payload),
    formatValue(candidate.before_value)
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function uniqueValues(items: CandidateItem[], getter: (item: CandidateItem) => string): string[] {
  return [...new Set(items.map(getter).filter(Boolean))].sort();
}

function summarizeValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "-";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 150 ? `${text.slice(0, 150)}...` : text;
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "-";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function evidenceForCandidate(candidate: CandidateItem, evidence: EvidenceLink[]): EvidenceLink[] {
  if (candidate.evidence_ids?.length) {
    const ids = new Set(candidate.evidence_ids);
    const direct = evidence.filter((item) => ids.has(item.evidence_id));
    if (direct.length) return direct;
  }
  return evidence.filter((item) => {
    const sameObject = candidate.target_object_id && item.object_id === candidate.target_object_id;
    const sameField = candidate.field_path && item.field_path === candidate.field_path;
    return Boolean((sameObject && (!candidate.field_path || sameField || !item.field_path)) || sameField);
  });
}

function shortId(value: string): string {
  return value.length > 28 ? `${value.slice(0, 12)}...${value.slice(-10)}` : value;
}

function actionLabel(action: DraftActionType): string {
  if (action === "accept") return "接受";
  if (action === "reject") return "拒绝";
  if (action === "conflict") return "标记冲突";
  return "保留待审计";
}

function riskLabel(risk: RiskLevel): string {
  if (risk === "low") return "低风险";
  if (risk === "medium") return "中风险";
  if (risk === "high") return "高风险";
  return "极高风险";
}

function riskTone(risk: RiskLevel): "good" | "warn" | "bad" | "info" {
  if (risk === "low") return "good";
  if (risk === "medium") return "warn";
  return "bad";
}

function riskFilterLabel(value: string): string {
  if (value === "conflict") return "冲突";
  if (value === "missing_evidence") return "缺证据";
  if (value === "needs_author") return "需要作者确认";
  return riskLabel(value as RiskLevel);
}

function draftStatusLabel(status: DraftStatus): string {
  if (status === "executed") return "已执行";
  if (status === "cancelled") return "已取消";
  return "待执行";
}

function worstRiskLevel(levels: RiskLevel[]): RiskLevel {
  if (levels.includes("critical")) return "critical";
  if (levels.includes("high")) return "high";
  if (levels.includes("medium")) return "medium";
  return "low";
}
