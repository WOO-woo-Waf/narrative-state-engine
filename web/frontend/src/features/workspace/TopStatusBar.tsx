import { Activity, Database, GitBranch, Layers, ListChecks, Maximize2, RefreshCw } from "lucide-react";
import { IconButton } from "../../components/form/IconButton";
import { StatusPill } from "../../components/data/StatusPill";
import type { HealthResponse } from "../../api/health";
import type { StateEnvironment } from "../../types/environment";
import { formatVersion } from "../../types/environment";
import type { Job } from "../../types/job";
import type { Story } from "../../types/story";
import type { Task } from "../../types/task";
import { databaseLabel, sceneLabel } from "../../utils/labels";

export type WorkbenchMode = "default" | "audit" | "graph" | "status";

export function TopStatusBar({
  story,
  task,
  environment,
  health,
  jobs,
  mode,
  refreshing,
  onModeChange,
  onRefresh
}: {
  story?: Story;
  task?: Task;
  environment?: StateEnvironment;
  health?: HealthResponse;
  jobs: Job[];
  mode: WorkbenchMode;
  refreshing?: boolean;
  onModeChange: (mode: WorkbenchMode) => void;
  onRefresh: () => void;
}) {
  const runningJobs = jobs.filter((job) => ["queued", "running"].includes(job.status));
  const database = health?.database || ((environment?.summary?.database || {}) as HealthResponse["database"]) || {};
  const databaseKnown = database.ok !== undefined;
  const pending = environment?.summary?.pending_candidate_count ?? 0;
  return (
    <header className="top-status">
      <div className="status-cluster">
        <span className="status-item status-title" title={story?.story_id || environment?.story_id}>
          <Layers size={16} />
          当前小说：{story?.title || environment?.story_id || "未选择小说"}
        </span>
        <span className="status-item" title={task?.task_id || environment?.task_id}>
          当前任务：{task?.title || environment?.task_id || "未选择任务"}
        </span>
        <StatusPill value={sceneLabel(environment?.scene_type)} tone="info" />
      </div>
      <div className="status-cluster">
        <span className="status-item">
          <GitBranch size={16} />
          当前分支：{environment?.branch_id || "主线"}
        </span>
        <span className="status-item">状态版本：{formatVersion(environment?.working_state_version_no)}</span>
        <span className="status-item" title={database.message || "状态来自 /api/health"}>
          <Database size={16} />
          <StatusPill
            value={databaseKnown ? databaseLabel(database.ok) : "正在检查数据库"}
            tone={databaseKnown ? (database.ok ? "good" : "bad") : "warn"}
          />
        </span>
        <span className="status-item">
          <Activity size={16} />
          <StatusPill value={`${runningJobs.length} 个运行中任务`} tone={runningJobs.length ? "warn" : "info"} />
        </span>
        <span className="status-item">
          <ListChecks size={16} />
          <span>{String(pending)} 个待审计候选</span>
        </span>
        <div className="mode-switch" aria-label="工作区模式">
          <ModeButton label="工作流" value="default" mode={mode} onModeChange={onModeChange} />
          <ModeButton label="候选审计" value="audit" mode={mode} onModeChange={onModeChange} />
          <ModeButton label="图谱" value="graph" mode={mode} onModeChange={onModeChange} />
          <ModeButton label="状态环境" value="status" mode={mode} onModeChange={onModeChange} />
        </div>
        <IconButton
          icon={refreshing ? <RefreshCw className="spin" size={15} /> : <RefreshCw size={15} />}
          label="刷新状态"
          tone="primary"
          onClick={onRefresh}
        />
      </div>
    </header>
  );
}

function ModeButton({
  label,
  value,
  mode,
  onModeChange
}: {
  label: string;
  value: WorkbenchMode;
  mode: WorkbenchMode;
  onModeChange: (mode: WorkbenchMode) => void;
}) {
  return (
    <button className={mode === value ? "active" : ""} type="button" onClick={() => onModeChange(value)} title={value === "default" ? "默认工作流布局" : `${label}大屏布局`}>
      {value === "default" ? null : <Maximize2 size={13} />}
      <span>{label}</span>
    </button>
  );
}
