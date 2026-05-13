import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { registerScenario } from "../../agentRuntime/scenarios/registry";
import type { RuntimeSelection, ScenarioRegistration } from "../../agentRuntime/types";
import { getStories } from "../../api/stories";
import { getTasks } from "../../api/tasks";
import { novelScenarioDefinition } from "./NovelScenarioDefinition";
import { BranchWorkspace } from "./workspaces/BranchWorkspace";
import { CandidateReviewWorkspace } from "./workspaces/CandidateReviewWorkspace";
import { EvidenceWorkspace } from "./workspaces/EvidenceWorkspace";
import { GraphWorkspace } from "./workspaces/GraphWorkspace";
import { JobWorkspace } from "./workspaces/JobWorkspace";
import { StateObjectsWorkspace } from "./workspaces/StateObjectsWorkspace";

const workspaceComponents = {
  "candidate-review": CandidateReviewWorkspace,
  "state-objects": StateObjectsWorkspace,
  graph: GraphWorkspace,
  evidence: EvidenceWorkspace,
  "branch-review": BranchWorkspace,
  jobs: JobWorkspace
};

export const novelScenarioRegistration: ScenarioRegistration = {
  ...novelScenarioDefinition,
  contextComponent: NovelContextControls,
  getThreadContext: (selection) => ({
    scenario_instance_id: selection.storyId,
    scenario_ref: {
      story_id: selection.storyId,
      task_id: selection.taskId
    },
    threadFilters: {
      story_id: selection.storyId,
      task_id: selection.taskId
    },
    createThreadInput: {
      story_id: selection.storyId,
      task_id: selection.taskId
    },
    messageEnvironment: {
      story_id: selection.storyId,
      task_id: selection.taskId
    }
  }),
  workspaces: novelScenarioDefinition.workspaces.map((workspace) => ({
    ...workspace,
    component: workspaceComponents[workspace.workspace_id as keyof typeof workspaceComponents]
  }))
};

export function registerNovelScenario() {
  registerScenario(novelScenarioRegistration);
}

function NovelContextControls({
  selection,
  onSelectionChange
}: {
  selection: RuntimeSelection;
  onSelectionChange: (selection: Partial<RuntimeSelection>) => void;
}) {
  const storiesQuery = useQuery({ queryKey: ["agent-runtime", "novel", "stories"], queryFn: getStories });
  const tasksQuery = useQuery({ queryKey: ["agent-runtime", "novel", "tasks"], queryFn: getTasks });

  useEffect(() => {
    if (selection.storyId) return;
    const storyId = storiesQuery.data?.default_story_id || storiesQuery.data?.stories[0]?.story_id;
    if (storyId) onSelectionChange({ storyId });
  }, [onSelectionChange, selection.storyId, storiesQuery.data]);

  useEffect(() => {
    if (selection.taskId) return;
    const taskId = tasksQuery.data?.default_task_id || tasksQuery.data?.tasks[0]?.task_id;
    if (taskId) onSelectionChange({ taskId });
  }, [onSelectionChange, selection.taskId, tasksQuery.data]);

  return (
    <>
      <label className="agent-field">
        <span>小说</span>
        <select value={selection.storyId || ""} onChange={(event) => onSelectionChange({ storyId: event.target.value, taskId: "" })}>
          <option value="">未选择</option>
          {storiesQuery.data?.stories.map((story) => (
            <option value={story.story_id} key={story.story_id}>
              {story.title || story.story_id}
            </option>
          ))}
        </select>
      </label>
      <label className="agent-field">
        <span>任务</span>
        <select value={selection.taskId || ""} onChange={(event) => onSelectionChange({ taskId: event.target.value })}>
          <option value="">未选择</option>
          {tasksQuery.data?.tasks.map((task) => (
            <option value={task.task_id} key={task.task_id}>
              {task.title || task.task_id}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
