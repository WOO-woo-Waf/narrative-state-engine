import { FilePenLine, GitBranchPlus, SplitSquareVertical, TextCursorInput, Trash2 } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { submitJob } from "../../api/jobs";
import { IconButton } from "../../components/form/IconButton";
import type { Branch } from "../../types/branch";
import type { StateEnvironment } from "../../types/environment";

export function RevisionPanel({ environment, branches = [], selectedBranchIds = [] }: { environment?: StateEnvironment; branches?: Branch[]; selectedBranchIds?: string[] }) {
  const [instruction, setInstruction] = useState("保留已确认事实，改善节奏与人物动机，并抽取可能的状态变化候选。");
  const [selectedParagraphs, setSelectedParagraphs] = useState("1,2");
  const selectedBranch = branches.find((branch) => selectedBranchIds.includes(branch.branch_id)) || branches[0];
  const rewriteMutation = useMutation({
    mutationFn: () =>
      submitJob("author-session", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        branch_id: environment?.branch_id,
        seed: instruction,
        confirm: false,
        persist: true
      })
  });
  const extractMutation = useMutation({
    mutationFn: () =>
      submitJob("edit-state", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        author_input: `从当前修订结果中抽取状态变化候选，不自动合并到主线。作者批注：${instruction}`,
        confirm: false,
        persist: true
      })
  });
  const preserveMutation = useMutation({
    mutationFn: () =>
      submitJob("author-session", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        branch_id: selectedBranch?.branch_id || environment?.branch_id,
        seed: `修订草稿，并保留段落 ${selectedParagraphs}。${instruction}`,
        confirm: false,
        persist: true
      })
  });
  const removeBeatMutation = useMutation({
    mutationFn: () =>
      submitJob("author-session", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        branch_id: selectedBranch?.branch_id || environment?.branch_id,
        seed: `从草稿中移除选中的节拍或段落 ${selectedParagraphs}。${instruction}`,
        confirm: false,
        persist: true
      })
  });
  const revisionBranchMutation = useMutation({
    mutationFn: () =>
      submitJob("author-session", {
        story_id: environment?.story_id,
        task_id: environment?.task_id,
        branch_id: selectedBranch?.branch_id || environment?.branch_id,
        seed: `创建修订分支，不自动合并到主线。${instruction}`,
        confirm: false,
        persist: true
      })
  });
  return (
    <div className="revision-grid">
      <section>
        <h3>原草稿</h3>
        <div className="draft-pane">{selectedBranch?.preview || "请选择分支查看草稿预览。修订结果不会自动进入主线。"}</div>
      </section>
      <section>
        <h3>作者批注 / 模型对话</h3>
        <label className="field">
          <span>段落 / 节拍</span>
          <input value={selectedParagraphs} onChange={(event) => setSelectedParagraphs(event.target.value)} />
        </label>
        <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} />
        <div className="button-row">
          <IconButton icon={<FilePenLine size={16} />} label="重写草稿" tone="primary" disabled={!environment || rewriteMutation.isPending} onClick={() => rewriteMutation.mutate()} />
          <IconButton icon={<TextCursorInput size={16} />} label="保留段落" tone="secondary" disabled={!environment || preserveMutation.isPending} onClick={() => preserveMutation.mutate()} />
          <IconButton icon={<Trash2 size={16} />} label="移除节拍" tone="secondary" disabled={!environment || removeBeatMutation.isPending} onClick={() => removeBeatMutation.mutate()} />
          <IconButton icon={<GitBranchPlus size={16} />} label="创建修订分支" tone="secondary" disabled={!environment || revisionBranchMutation.isPending} onClick={() => revisionBranchMutation.mutate()} />
          <IconButton icon={<SplitSquareVertical size={16} />} label="抽取状态变化" tone="secondary" disabled={!environment || extractMutation.isPending} onClick={() => extractMutation.mutate()} />
        </div>
      </section>
      <section>
        <h3>修订结果</h3>
        <div className="draft-pane">后端完成重写或修订分支后，结果会通过分支审计和候选审计进入这里。</div>
      </section>
    </div>
  );
}
