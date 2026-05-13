import { FilePlus2, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { IconButton } from "../../components/form/IconButton";
import { Panel } from "../../components/layout/Panel";
import { StatusPill } from "../../components/data/StatusPill";
import { SCENE_OPTIONS, type SceneType, type Task } from "../../types/task";
import type { Story } from "../../types/story";
import type { Branch } from "../../types/branch";

export function WorkspaceNavigator({
  stories,
  tasks,
  branches,
  storyId,
  taskId,
  sceneType,
  branchId,
  pendingCount,
  stateVersion,
  onStoryChange,
  onTaskChange,
  onSceneChange,
  onBranchChange,
  onCreateState
}: {
  stories: Story[];
  tasks: Task[];
  branches: Branch[];
  storyId: string;
  taskId: string;
  sceneType: SceneType;
  branchId: string;
  pendingCount: number;
  stateVersion?: number | null;
  onStoryChange: (storyId: string) => void;
  onTaskChange: (taskId: string) => void;
  onSceneChange: (sceneType: SceneType) => void;
  onBranchChange: (branchId: string) => void;
  onCreateState?: () => void;
}) {
  const queryClient = useQueryClient();
  const storyTasks = tasks.filter((task) => !storyId || task.story_id === storyId);
  return (
    <aside className="workspace-nav">
      <Panel
        title="任务菜单"
        actions={<IconButton icon={<RefreshCw size={15} />} label="刷新" onClick={() => queryClient.invalidateQueries()} />}
      >
        <label className="field">
          <span>小说</span>
          <select value={storyId} onChange={(event) => onStoryChange(event.target.value)}>
            <option value="">选择小说</option>
            {stories.map((story) => (
              <option key={story.story_id} value={story.story_id}>
                {story.title || story.story_id}
              </option>
            ))}
          </select>
        </label>
        {!stories.length ? (
          <div className="empty-state compact">
            <p>暂无小说。</p>
            {onCreateState ? <IconButton icon={<FilePlus2 size={15} />} label="创建或导入" tone="primary" onClick={onCreateState} /> : null}
          </div>
        ) : null}
        <label className="field">
          <span>任务</span>
          <select value={taskId} onChange={(event) => onTaskChange(event.target.value)}>
            <option value="">选择任务</option>
            {storyTasks.map((task) => (
              <option key={task.task_id} value={task.task_id}>
                {task.title || task.task_id}
              </option>
            ))}
          </select>
        </label>
        {storyId && !storyTasks.length ? (
          <div className="empty-state compact">
            <p>当前小说暂无任务。</p>
            {onCreateState ? <IconButton icon={<FilePlus2 size={15} />} label="创建任务" tone="primary" onClick={onCreateState} /> : null}
          </div>
        ) : null}
        <div className="scene-list" aria-label="任务页面切换">
          {SCENE_OPTIONS.map((scene) => (
            <button key={scene.value} className={scene.value === sceneType ? "active" : ""} type="button" onClick={() => onSceneChange(scene.value)}>
              <strong>{scene.label}</strong>
              <span>{scene.taskType}</span>
            </button>
          ))}
        </div>
        <label className="field">
          <span>分支</span>
          <select value={branchId} onChange={(event) => onBranchChange(event.target.value)}>
            <option value="">主线</option>
            {branches.map((branch) => (
              <option key={branch.branch_id} value={branch.branch_id}>
                {branch.branch_id}
              </option>
            ))}
          </select>
        </label>
        <div className="nav-metrics">
          <div>
            <span>状态版本</span>
            <strong>{stateVersion === null || stateVersion === undefined ? "未知" : `v${stateVersion}`}</strong>
          </div>
          <div>
            <span>待审计</span>
            <StatusPill value={pendingCount} tone={pendingCount ? "warn" : "good"} />
          </div>
          <div>
            <span>分支数</span>
            <strong>{branches.length}</strong>
          </div>
        </div>
      </Panel>
    </aside>
  );
}
