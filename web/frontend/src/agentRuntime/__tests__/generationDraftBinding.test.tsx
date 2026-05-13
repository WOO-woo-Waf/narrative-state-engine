import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ActionDraftBlock } from "../drafts/ActionDraftBlock";

const generationAction = {
  action_id: "draft-generation",
  session_id: "thread-1",
  action_type: "create_generation_job",
  tool_name: "create_generation_job",
  title: "续写任务草案",
  summary: "启动续写，目标 20000 字。",
  risk_level: "medium",
  status: "draft",
  tool_params: { target_words: 30000, target_chars: 36000, branch_count: 2, max_rounds: 8, rag_enabled: true, output_path: "novels_output/next.txt" }
};

describe("generation draft binding", () => {
  it("disables execution when plot plan is missing", () => {
    const html = renderToStaticMarkup(<ActionDraftBlock action={generationAction} onConfirmAndExecute={vi.fn()} onContinue={vi.fn()} onCancel={vi.fn()} selection={{}} />);
    expect(html).toContain("缺少剧情规划绑定");
    expect(html).toContain("disabled");
    expect(html).toContain("选择剧情规划");
  });

  it("shows concrete plot plan when bound", () => {
    const html = renderToStaticMarkup(
      <ActionDraftBlock
        action={generationAction}
        onConfirmAndExecute={vi.fn()}
        onContinue={vi.fn()}
        onCancel={vi.fn()}
        selection={{ selectedArtifacts: { plot_plan_id: "author-plan-002", plot_plan_artifact_id: "artifact-002" } }}
      />
    );
    expect(html).toContain("使用剧情规划：author-plan-002");
    expect(html).not.toContain("缺少剧情规划绑定");
  });

  it("shows real create_generation_job tool_params and warns when summary differs", () => {
    const html = renderToStaticMarkup(
      <ActionDraftBlock
        action={generationAction}
        onConfirmAndExecute={vi.fn()}
        onContinue={vi.fn()}
        onCancel={vi.fn()}
        selection={{ selectedArtifacts: { plot_plan_id: "author-plan-002", plot_plan_artifact_id: "artifact-002" } }}
      />
    );
    expect(html).toContain("目标字数：30000");
    expect(html).toContain("目标字符：36000");
    expect(html).toContain("分支数：2");
    expect(html).toContain("轮次：8");
    expect(html).toContain("RAG：启用");
    expect(html).toContain("输出路径：novels_output/next.txt");
    expect(html).toContain("以目标字数 30000 为准");
  });
});
