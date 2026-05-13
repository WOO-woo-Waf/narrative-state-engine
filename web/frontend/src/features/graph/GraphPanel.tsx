import { useEffect, useMemo, useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useQuery } from "@tanstack/react-query";
import { getGraph } from "../../api/graph";
import { IconButton } from "../../components/form/IconButton";
import { SegmentedControl } from "../../components/form/SegmentedControl";
import { LoadingState } from "../../components/feedback/LoadingState";
import { ErrorState } from "../../components/feedback/ErrorState";
import { StatusPill } from "../../components/data/StatusPill";
import { useSelectionStore } from "../../stores/selectionStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { GraphKind, WorkbenchGraphNode } from "../../types/graph";
import type { SceneType } from "../../types/task";
import { authorityLabel, objectTypeLabel, sourceRoleLabel } from "../../utils/labels";

export function GraphPanel({
  storyId,
  taskId,
  sceneType,
  highlightIds = [],
  initialGraphKind
}: {
  storyId: string;
  taskId: string;
  sceneType: SceneType;
  highlightIds?: string[];
  initialGraphKind?: GraphKind;
}) {
  const graphKind = useSelectionStore((state) => state.graphKind);
  const setGraphKind = useSelectionStore((state) => state.setGraphKind);
  const setSelectedObjectIds = useSelectionStore((state) => state.setSelectedObjectIds);
  const setSelectedBranchIds = useSelectionStore((state) => state.setSelectedBranchIds);
  const setRightPanel = useWorkspaceStore((state) => state.setRightPanel);
  const [objectType, setObjectType] = useState("");
  const [authority, setAuthority] = useState("");
  const [status, setStatus] = useState("");
  const [sourceRole, setSourceRole] = useState("");
  const [minConfidence, setMinConfidence] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [selectedGraphNode, setSelectedGraphNode] = useState<WorkbenchGraphNode | undefined>();
  const highlightSet = useMemo(() => new Set(highlightIds.filter(Boolean)), [highlightIds]);
  useEffect(() => {
    if (initialGraphKind && initialGraphKind !== graphKind) setGraphKind(initialGraphKind);
  }, [graphKind, initialGraphKind, setGraphKind]);
  const query = useQuery({
    queryKey: ["graph", storyId, taskId, graphKind, sceneType],
    queryFn: () => getGraph(storyId, taskId, graphKind, sceneType),
    enabled: Boolean(storyId && taskId)
  });
  const filteredSourceNodes = useMemo(() => {
    return (query.data?.nodes || []).filter((node) => {
      const data = node.data || {};
      if (objectType && String(data.object_type || node.type || "") !== objectType) return false;
      if (authority && String(data.authority || "") !== authority) return false;
      if (status && String(data.status || "") !== status) return false;
      if (sourceRole && String(data.source_role || data.sourceRole || "") !== sourceRole) return false;
      if (minConfidence && Number(data.confidence || 0) < minConfidence / 100) return false;
      return true;
    });
  }, [authority, minConfidence, objectType, query.data, sourceRole, status]);
  const nodes = useMemo<Node[]>(() => {
    return filteredSourceNodes.map((node, index) => ({
      id: node.id,
      type: "default",
      className: isHighlightedGraphNode(node, highlightSet) ? "highlighted-flow-node" : undefined,
      position: { x: (index % 5) * 230, y: Math.floor(index / 5) * 120 },
      data: {
        label: (
          <div className="flow-node">
            <strong>{node.label || node.id}</strong>
            <span>{node.type || "node"}</span>
            {graphKind === "transition" ? <span>{node.data?.action_id ? `动作编号 ${String(node.data.action_id)}` : "缺少 action_id"}</span> : null}
          </div>
        ),
        raw: node.data,
        nodeType: node.type,
        sourceNode: node
      }
    }));
  }, [filteredSourceNodes, graphKind, highlightSet]);
  const visibleNodeIds = useMemo(() => new Set(nodes.map((node) => node.id)), [nodes]);
  const edges = useMemo<Edge[]>(
    () =>
      (query.data?.edges || [])
        .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
        .map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.label,
          animated: graphKind === "transition" || highlightSet.has(edge.id) || highlightSet.has(edge.source) || highlightSet.has(edge.target),
          className: highlightSet.has(edge.id) || highlightSet.has(edge.source) || highlightSet.has(edge.target) ? "highlighted-flow-edge" : undefined
        })),
    [graphKind, highlightSet, query.data, visibleNodeIds]
  );
  return (
    <div className={`graph-panel ${expanded ? "graph-expanded" : ""}`}>
      <div className="toolbar graph-toolbar">
        <SegmentedControl
          label="图谱类型"
          value={graphKind}
          onChange={setGraphKind}
          options={[
            { value: "state", label: "状态图" },
            { value: "transition", label: "迁移图" },
            { value: "analysis", label: "分析图" },
            { value: "branches", label: "分支图" }
          ]}
        />
        {query.data?.aggregated ? <StatusPill value="聚合视图" tone="warn" /> : null}
        {query.data?.fallback ? <StatusPill value="降级投影" tone="warn" /> : null}
        <IconButton icon={expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />} label={expanded ? "退出大图" : "大图查看"} onClick={() => setExpanded((value) => !value)} />
      </div>
      {highlightIds.length ? (
        <div className="notice notice-good">
          已高亮引用：{highlightIds.slice(0, 6).join(", ")}
          {highlightIds.length > 6 ? ` 等 ${highlightIds.length} 项` : ""}
        </div>
      ) : null}
      {query.data?.fallback_reason ? <div className="notice notice-warn">{query.data.fallback_reason}</div> : null}
      {graphKind === "transition" && selectedGraphNode ? (
        <div className={selectedGraphNode.data?.action_id ? "notice notice-good" : "notice notice-warn"}>
          {selectedGraphNode.data?.action_id ? `迁移动作编号 action_id：${String(selectedGraphNode.data.action_id)}` : "该迁移缺少 action_id，请记录为图谱动作链路问题。"}
        </div>
      ) : null}
      <div className="graph-filter-bar">
        <FilterSelect label="类型" value={objectType} options={uniqueValues(query.data?.nodes || [], "object_type", "type")} onChange={setObjectType} render={objectTypeLabel} />
        <FilterSelect label="权威等级" value={authority} options={uniqueValues(query.data?.nodes || [], "authority")} onChange={setAuthority} render={authorityLabel} />
        <FilterSelect label="状态" value={status} options={uniqueValues(query.data?.nodes || [], "status")} onChange={setStatus} />
        <FilterSelect label="来源角色" value={sourceRole} options={uniqueValues(query.data?.nodes || [], "source_role")} onChange={setSourceRole} render={sourceRoleLabel} />
        <label className="field compact">
          <span>置信度不低于 {minConfidence}%</span>
          <input type="range" min={0} max={100} value={minConfidence} onChange={(event) => setMinConfidence(Number(event.target.value))} />
        </label>
      </div>
      <div className="flow-wrap">
        {query.isLoading ? <LoadingState label="正在加载图谱" /> : null}
        {query.error ? <ErrorState error={query.error} /> : null}
        {query.data && !nodes.length ? <div className="empty-state">当前图谱为空，或筛选条件下没有节点。若 API 有节点但这里为空，请记录为前端图渲染问题。</div> : null}
        {query.data && nodes.length ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            onNodeClick={(_, node) => {
              setSelectedGraphNode(node.data.sourceNode as WorkbenchGraphNode);
              if (graphKind === "branches" || node.data.nodeType === "branch") {
                setSelectedBranchIds([node.id]);
                setRightPanel("branch");
              } else {
                setSelectedObjectIds([node.id]);
                setRightPanel("object");
              }
            }}
          >
            <Background />
            <Controls showInteractive fitViewOptions={{ padding: 0.2 }} />
            <MiniMap pannable zoomable />
          </ReactFlow>
        ) : null}
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  render = (value: string) => value
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

function uniqueValues(nodes: Array<{ type?: string; data?: Record<string, unknown> }>, key: string, fallbackKey?: "type"): string[] {
  const values = new Set<string>();
  nodes.forEach((node) => {
    const value = node.data?.[key] ?? (fallbackKey ? node[fallbackKey] : undefined);
    if (value !== undefined && value !== null && value !== "") values.add(String(value));
  });
  return [...values].sort();
}

function isHighlightedGraphNode(node: WorkbenchGraphNode, highlightSet: Set<string>): boolean {
  if (highlightSet.has(node.id)) return true;
  const data = node.data || {};
  return ["transition_id", "action_id", "candidate_item_id", "object_id", "branch_id", "evidence_id"].some((key) => {
    const value = data[key];
    if (Array.isArray(value)) return value.some((item) => highlightSet.has(String(item)));
    return value !== undefined && value !== null && highlightSet.has(String(value));
  });
}
