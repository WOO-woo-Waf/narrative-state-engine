import { FileSearch, MessageSquareText, Shapes } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { submitJob } from "../../api/jobs";
import { IconButton } from "../../components/form/IconButton";
import { StatusPill } from "../../components/data/StatusPill";
import { SubmittedJobSummary } from "../jobs/SubmittedJobSummary";
import type { StateEnvironment } from "../../types/environment";

type CreationMode = "dialogue" | "analysis" | "template";

export function StateCreationPanel({
  environment,
  storyId,
  taskId,
  onOpenJobs
}: {
  environment?: StateEnvironment;
  storyId?: string;
  taskId?: string;
  onOpenJobs?: () => void;
}) {
  const [mode, setMode] = useState<CreationMode>("dialogue");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("新小说初始设定：人物、世界、冲突和第一章目标。");
  const [inputFile, setInputFile] = useState("novels_input/1.txt");
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => {
      const targetStoryId = environment?.story_id || storyId || toIdentifier(title || "workbench_new_story");
      const targetTaskId = environment?.task_id || taskId || `${targetStoryId}_state_creation`;
      if (mode === "analysis") {
        return submitJob("analyze-task", {
          story_id: targetStoryId,
          task_id: targetTaskId,
          file: inputFile,
          title: title || targetStoryId,
          persist: true
        });
      }
      if (mode === "template") {
        return submitJob("create-state", {
          story_id: targetStoryId,
          task_id: targetTaskId,
          title: title || targetStoryId,
          description: `从模板创建初始状态：${description}`,
          persist: true
        });
      }
      return submitJob("create-state", {
        story_id: targetStoryId,
        task_id: targetTaskId,
        title: title || targetStoryId,
        description,
        persist: true
      });
    },
    onSuccess: () => queryClient.invalidateQueries()
  });
  return (
    <div className="state-creation-panel">
      <section className="workflow-column">
        <h3>创建小说状态</h3>
        <div className="creation-mode-list">
          <ModeButton active={mode === "dialogue"} icon={<MessageSquareText size={18} />} title="对话创建" onClick={() => setMode("dialogue")} />
          <ModeButton active={mode === "analysis"} icon={<FileSearch size={18} />} title="分析原文" onClick={() => setMode("analysis")} />
          <ModeButton active={mode === "template"} icon={<Shapes size={18} />} title="模板创建" onClick={() => setMode("template")} />
        </div>
        <label className="field">
          <span>标题</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="新小说标题" />
        </label>
        {mode === "analysis" ? (
          <label className="field">
            <span>输入文件</span>
            <input value={inputFile} onChange={(event) => setInputFile(event.target.value)} />
          </label>
        ) : null}
        <label className="field">
          <span>{mode === "template" ? "模板说明" : "初始想法"}</span>
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <IconButton icon={<MessageSquareText size={16} />} label="创建状态候选" tone="primary" disabled={mutation.isPending} onClick={() => mutation.mutate()} />
        <SubmittedJobSummary job={mutation.data} error={mutation.error} title="状态创建任务" onOpenJobs={onOpenJobs} />
      </section>
      <section className="workflow-column">
        <h3>权威等级说明</h3>
        <div className="stack">
          <p>这是作者种子设定，不是原文证据。进入主状态前仍需要候选审计。</p>
          <div className="pill-row">
            <StatusPill value="author_seeded" tone="info" />
            <StatusPill value="author_confirmed" tone="good" />
            <StatusPill value="author_locked" tone="good" />
          </div>
          <p>前端不会直接写入主状态，只会启动后端任务或候选审计流程。</p>
        </div>
      </section>
    </div>
  );
}

function toIdentifier(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .replace(/^_+|_+$/g, "") || "workbench_new_story"
  );
}

function ModeButton({ active, icon, title, onClick }: { active: boolean; icon: ReactNode; title: string; onClick: () => void }) {
  return (
    <button className={active ? "active" : ""} type="button" onClick={onClick}>
      {icon}
      <span>{title}</span>
    </button>
  );
}
