import { expect, test, type Page, type Route } from "@playwright/test";

test("workbench v2 main workflow smoke", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => pageErrors.push(`request failed: ${request.url()} ${request.failure()?.errorText}`));
  page.on("response", (response) => {
    if (response.status() >= 400) pageErrors.push(`HTTP ${response.status()}: ${response.url()}`);
  });
  page.on("console", (message) => {
    if (message.type() === "error") pageErrors.push(message.text());
  });

  await mockWorkbenchApi(page);
  await page.goto("/workbench-v2/");
  await expect(page.getByRole("banner").getByRole("button", { name: "刷新状态" })).toBeVisible();
  expect(pageErrors).toEqual([]);

  await expect(page.locator("select").first()).toHaveValue("story_workbench_s2");
  await page.locator(".scene-list").getByRole("button", { name: /候选审计/ }).click();
  await expect(page.getByText("模型辅助审计")).toBeVisible();
  await expect(page.getByText("审计上下文摘要")).toBeVisible();
  await page.getByLabel("生成三份审计草案").click();
  await expect(page.getByText("保守审计草案")).toBeVisible();

  await page.getByRole("button", { name: /候选列表/ }).click();
  await expect(page.getByText("候选详情")).toBeVisible();
  await expect(page.getByRole("heading", { name: "证据" })).toBeVisible();
  await expect(page.getByText("The clock tower keeps the memory.")).toBeVisible();

  await page.getByRole("button", { name: "仅选择低风险" }).click();
  page.once("dialog", (dialog) => dialog.accept("确认执行"));
  await page.getByRole("button", { name: "批量接受（1）" }).first().click();
  await expect(page.getByTestId("candidate-review-result")).toContainText("已接受：1");

  await page.getByRole("button", { name: /候选列表/ }).click();
  await page.locator(".candidate-summary-card").first().click();
  await expect(page.getByRole("button", { name: "接受字段" })).toBeVisible();

  await page.locator(".inspector-tabs button[aria-label='图谱']").click();
  await page.getByRole("button", { name: "分析图" }).click();
  await expect(page.getByText("降级投影")).toBeVisible();
  await expect(page.getByText("analysis graph route unavailable")).toBeVisible();

  await page.locator(".mode-switch").getByRole("button", { name: "候选审计" }).click();
  await expect(page.getByRole("heading", { name: "候选审计" })).toBeVisible();
  await expect(page.locator(".inspector")).toBeHidden();

  await page.locator(".mode-switch").getByRole("button", { name: "图谱" }).click();
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  await expect(page.getByRole("button", { name: "状态图" })).toBeVisible();

  await page.locator(".mode-switch").getByRole("button", { name: "状态环境" }).click();
  await expect(page.getByRole("heading", { name: "状态环境" })).toBeVisible();
  await expect(page.getByRole("main").getByText("状态总览")).toBeVisible();
});

test("refresh status updates database health", async ({ page }) => {
  let healthOk = false;
  await mockWorkbenchApi(page, {
    health: () => ({ ok: true, database: { ok: healthOk, message: healthOk ? "connected" : "offline" } })
  });

  await page.goto("/workbench-v2/");
  await expect(page.getByRole("banner").getByText("数据库离线")).toBeVisible();

  healthOk = true;
  await page.getByRole("banner").getByRole("button", { name: "刷新状态" }).click();
  await expect(page.getByRole("banner").getByText("数据库在线")).toBeVisible();
});

test("dialogue-first workbench sends through runtime only and renders backend LLM draft", async ({ page }) => {
  const pageErrors: string[] = [];
  const sessionRequests: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("/api/dialogue/sessions")) sessionRequests.push(request.url());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) pageErrors.push(`HTTP ${response.status()}: ${response.url()}`);
  });

  await mockWorkbenchApi(page, { runtimeSend: true, runtimeSendDelayMs: 600 });
  await page.goto("/workbench-v2/workbench-dialogue/");

  await expect(page.getByText("Agent Runtime")).toBeVisible();
  await expect(page.getByText("通用对话壳")).toBeVisible();
  await expect(page.locator(".agent-main-header").getByText("候选审计")).toBeVisible();
  await expect(page.getByPlaceholder("向 Agent 说明你的下一步意图...")).toBeVisible();

  await page.getByPlaceholder("向 Agent 说明你的下一步意图...").fill("帮我审计当前候选，低风险先生成通过草案。");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("已发送，等待后端运行结果。")).toBeVisible();

  await expect(page.getByText("候选审计草案", { exact: true })).toBeVisible();
  await expect(page.getByText("模型生成").first()).toBeVisible();
  await expect(page.getByText("分析任务").first()).toBeVisible();
  await expect(page.getByText("模型基于状态环境生成的低风险候选审计草案。")).toBeVisible();

  await page.getByRole("button", { name: "确认并执行" }).first().click();
  await expect(page.getByText("审计执行结果")).toBeVisible();
  await expect(page.getByText("后端执行草案完成：接受 1 项。")).toBeVisible();

  await page.getByRole("button", { name: "查看候选" }).last().click();
  await expect(page.locator(".agent-workspace-overlay").getByText("状态审计")).toBeVisible();
  await expect(page.locator(".agent-workspace-overlay").getByText("模型辅助审计")).toBeVisible();
  expect(sessionRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test("dialogue-first workbench renders backend runtime drafts and artifacts", async ({ page }) => {
  await mockWorkbenchApi(page, { runtime: true });
  await page.goto("/workbench-v2/workbench-dialogue/");

  await expect(page.getByRole("button", { name: /历史 \/ 分支 \/ 调试/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /后端审计线程/ })).toBeHidden();
  await page.getByRole("button", { name: /历史 \/ 分支 \/ 调试/ }).click();
  await expect(page.getByRole("button", { name: /后端审计线程/ })).toBeVisible();
  await expect(page.getByText("后端审计草案")).toBeVisible();

  await page.getByRole("button", { name: "确认并执行" }).first().click();
  await expect(page.getByText("后端审计结果")).toBeVisible();
  await expect(page.getByText("后端执行草案完成：接受 1 项。")).toBeVisible();

  const auditResult = page.locator(".agent-run-card").filter({ hasText: "后端审计结果" });
  await auditResult.getByRole("button", { name: "查看输出" }).click();
  await expect(page.locator(".agent-workspace-overlay > header").getByText("后端审计结果")).toBeVisible();
  await expect(page.locator(".agent-workspace-overlay").getByText("transition-runtime-1")).toBeVisible();
  await page.locator(".agent-workspace-overlay").getByRole("button").first().click();

  await auditResult.getByRole("button", { name: "打开图谱" }).click();
  await expect(page.locator(".agent-workspace-overlay > header").getByText("图谱")).toBeVisible();
  await expect(page.locator(".agent-workspace-overlay").getByText("当前图谱为空", { exact: false })).toBeVisible();
});

test("dialogue-first workbench supports planning continuation branch review and state return", async ({ page }) => {
  await mockWorkbenchApi(page, { runtimeFlow: true });
  await page.goto("/workbench-v2/workbench-dialogue/");

  await expect(page.getByRole("button", { name: /剧情规划续写线程/ })).toBeHidden();
  await page.getByRole("button", { name: /历史 \/ 分支 \/ 调试/ }).click();
  await expect(page.getByRole("button", { name: /剧情规划续写线程/ })).toBeVisible();
  await expect(page.locator(".agent-main-header").getByText("剧情规划")).toBeVisible();
  await expect(page.getByText("规划、续写和分支审稿链路已准备好。")).toBeVisible();
  await expect(page.getByText("剧情规划").first()).toBeVisible();
  await page.getByRole("button", { name: /使用此规划/ }).first().click();
  await expect(page.getByText("当前使用：plot-plan-runtime-1")).toBeVisible();
  await expect(page.getByRole("main").getByText("后端规划 artifact").first()).toBeVisible();
  await expect(page.getByText("接受分支入主线草案")).toBeVisible();

  await expect(page.getByText("续写任务")).toBeVisible();
  const branchArtifact = page.locator(".continuation-card").filter({ hasText: "后端续写分支" });
  await expect(branchArtifact).toBeVisible();
  await branchArtifact.getByRole("button", { name: /打开分支/ }).click();
  await expect(page.locator(".agent-workspace-overlay > header").getByText("分支")).toBeVisible();
  await expect(page.locator(".agent-workspace-overlay").getByRole("heading", { name: "branch-runtime-1" })).toBeVisible();
  await page.locator(".agent-workspace-overlay").getByRole("button").first().click();

  await branchArtifact.getByRole("button", { name: "打开图谱" }).click();
  await expect(page.locator(".agent-workspace-overlay > header").getByText("图谱")).toBeVisible();
  await page.locator(".agent-workspace-overlay").getByRole("button").first().click();

  const acceptDraft = page.locator(".agent-block-draft").filter({ hasText: "接受分支入主线草案" });
  await acceptDraft.getByRole("button", { name: "确认并执行" }).click();
  await expect(page.getByText("分支已接受").first()).toBeVisible();
  await expect(page.getByText("正文分支已入主线，等待状态回流审计。")).toBeVisible();
});

test("agent runtime switches to mock image scenario without shell changes", async ({ page }) => {
  await mockWorkbenchApi(page, { scenarios: true });
  await page.goto("/workbench-v2/workbench-dialogue/");

  await page.getByLabel("场景类型").selectOption("mock_image");
  await expect(page.locator(".context-mode-bar button.active")).toContainText("提示词生成");
  await expect(page.locator(".agent-workspace-list").getByRole("button", { name: /提示词板/ })).toBeVisible();
  await expect(page.locator(".agent-workspace-list").getByRole("button", { name: "生成队列" })).toBeVisible();

  await page.locator(".agent-workspace-list").getByRole("button", { name: /提示词板/ }).click();
  await expect(page.locator(".agent-workspace-overlay > header").getByText("提示词板")).toBeVisible();
  await expect(page.locator(".agent-workspace-overlay").getByText("电影感夜景，冷暖对比")).toBeVisible();
});

test("agent runtime route does not request legacy sessions and shows composer attachments", async ({ page }) => {
  const sessionRequests: string[] = [];
  let messageEnvironment: Record<string, unknown> = {};
  page.on("request", (request) => {
    if (request.url().includes("/api/dialogue/sessions")) sessionRequests.push(request.url());
  });
  await mockWorkbenchApi(page, {
    runtime: true,
    runtimeMessage: (body) => {
      messageEnvironment = (body.environment || {}) as Record<string, unknown>;
    }
  });
  await page.goto("/workbench-v2/workbench-dialogue/");

  await page.locator(".agent-workspace-list").getByRole("button", { name: "状态审计" }).click();
  await expect(page.locator(".agent-workspace-overlay > header").getByText("状态审计")).toBeVisible();
  await expect(page.getByText("附加上下文：workspace: 状态审计")).toBeVisible();
  const composer = page.getByPlaceholder("向 Agent 说明你的下一步意图...");
  await composer.fill("请带着当前工作区上下文总结。");
  await composer.press(process.platform === "darwin" ? "Meta+Enter" : "Control+Enter");
  await expect.poll(() => messageEnvironment.active_workspace_id).toBe("candidate-review");
  expect(messageEnvironment.selection).toMatchObject({ story_id: "story_workbench_s2", task_id: "task_workbench_s2", scene_type: "state_maintenance" });
  expect(sessionRequests).toEqual([]);
});

type MockOptions = {
  health?: () => unknown;
  runtime?: boolean;
  runtimeFlow?: boolean;
  runtimeSend?: boolean;
  runtimeSendDelayMs?: number;
  scenarios?: boolean;
  runtimeMessage?: (body: Record<string, unknown>) => void;
};

async function mockWorkbenchApi(page: Page, options: MockOptions = {}) {
  let runtimeSendCreated = false;
  let runtimeSendPosted = false;
  await page.route(/https?:\/\/127\.0\.0\.1:5173\/api\/.*/, async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    const method = route.request().method();

    if (pathname === "/api/health") {
      if (options.health) return json(route, options.health());
      return json(route, { ok: true, database: { ok: true, message: "connected" } });
    }
    if (pathname === "/api/stories") {
      return json(route, {
        default_story_id: "story_workbench_s2",
        stories: [{ story_id: "story_workbench_s2", title: "Workbench smoke story", status: "active" }]
      });
    }
    if (pathname === "/api/tasks") {
      return json(route, {
        default_task_id: "task_workbench_s2",
        tasks: [{ task_id: "task_workbench_s2", story_id: "story_workbench_s2", title: "Workbench smoke task", status: "active" }]
      });
    }
    if (options.scenarios && pathname === "/api/dialogue/scenarios") {
      return json(route, {
        scenarios: [
          {
            scenario_type: "novel_state_machine",
            label: "小说",
            scenes: [{ scene_type: "state_maintenance", label: "候选审计" }],
            workspaces: []
          },
          {
            scenario_type: "mock_image",
            label: "图片项目",
            scenes: [
              { scene_type: "prompt_generation", label: "提示词生成" },
              { scene_type: "image_generation", label: "图片生成" },
              { scene_type: "image_review", label: "图片审稿" }
            ],
            workspaces: [
              { workspace_id: "prompt-board", label: "提示词板", placement: "overlay" },
              { workspace_id: "image-queue", label: "生成队列", placement: "overlay" }
            ]
          }
        ]
      });
    }
    if (options.runtimeSend && pathname === "/api/dialogue/threads" && method === "GET") {
      return json(route, { threads: runtimeSendCreated ? [runtimeSendThread()] : [] });
    }
    if (options.runtimeSend && pathname === "/api/dialogue/threads" && method === "POST") {
      runtimeSendCreated = true;
      return json(route, runtimeSendThread());
    }
    if (options.runtimeSend && pathname === "/api/dialogue/threads/thread-runtime-send/messages" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.role).toBe("user");
      expect(body.content).toContain("帮我审计当前候选");
      runtimeSendPosted = true;
      if (options.runtimeSendDelayMs) await new Promise((resolve) => setTimeout(resolve, options.runtimeSendDelayMs));
      return json(route, runtimeSendDetail(true));
    }
    if (options.runtimeSend && pathname === "/api/dialogue/threads/thread-runtime-send") {
      return json(route, runtimeSendDetail(runtimeSendPosted));
    }
    if (options.runtimeSend && pathname === "/api/dialogue/threads/thread-runtime-send/events") {
      return json(route, { events: runtimeSendPosted ? runtimeSendEvents() : [] });
    }
    if (options.runtimeSend && pathname === "/api/dialogue/action-drafts" && method === "GET") {
      return json(route, { action_drafts: runtimeSendPosted ? [runtimeSendDraft()] : [] });
    }
    if (options.runtimeSend && pathname === "/api/dialogue/artifacts" && method === "GET") {
      return json(route, { artifacts: [] });
    }
    if (options.runtimeSend && pathname === "/api/dialogue/action-drafts/draft-runtime-send/confirm" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.confirmation_text).toBe("确认执行");
      return json(route, { ...runtimeSendDraft(), status: "confirmed" });
    }
    if (options.runtimeSend && pathname === "/api/dialogue/action-drafts/draft-runtime-send/confirm-and-execute" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.confirmation_text).toBe("确认执行");
      return json(route, {
        artifacts: [
          {
            artifact_id: "artifact-runtime-send",
            artifact_type: "audit_result",
            title: "审计执行结果",
            summary: "后端执行草案完成：接受 1 项。",
            payload: { provenance: { draft_source: "llm", llm_called: true, llm_success: true, model_name: "test-model" } },
            related_candidate_ids: ["item-2"],
            related_object_ids: ["obj-2"],
            related_transition_ids: ["transition-runtime-send"]
          }
        ],
        events: [{ event_id: "event-runtime-send-tool", event_type: "tool_completed", title: "执行完成", summary: "已更新状态。" }]
      });
    }
    if (options.runtimeSend && pathname === "/api/dialogue/action-drafts/draft-runtime-send/execute" && method === "POST") {
      return json(route, {
        artifacts: [
          {
            artifact_id: "artifact-runtime-send",
            artifact_type: "audit_result",
            title: "审计执行结果",
            summary: "后端执行草案完成：接受 1 项。",
            payload: { provenance: { draft_source: "llm", llm_called: true, llm_success: true, model_name: "test-model" } },
            related_candidate_ids: ["item-2"],
            related_object_ids: ["obj-2"],
            related_transition_ids: ["transition-runtime-send"]
          }
        ],
        events: [{ event_id: "event-runtime-send-tool", event_type: "tool_completed", title: "执行完成", summary: "已更新状态。" }]
      });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/threads" && method === "GET") {
      return json(route, {
        threads: [
          {
            thread_id: "thread-runtime-flow",
            story_id: "story_workbench_s2",
            task_id: "task_workbench_s2",
            scene_type: "plot_planning",
            title: "剧情规划续写线程",
            status: "active"
          }
        ]
      });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/threads/thread-runtime-flow") {
      return json(route, {
        thread: {
          thread_id: "thread-runtime-flow",
          story_id: "story_workbench_s2",
          task_id: "task_workbench_s2",
          scene_type: "plot_planning",
          title: "剧情规划续写线程",
          status: "active"
        },
        messages: [{ message_id: "runtime-flow-msg-1", thread_id: "thread-runtime-flow", role: "assistant", content: "规划、续写和分支审稿链路已准备好。" }],
        actions: [],
        events: [],
        artifacts: []
      });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/threads/thread-runtime-flow/events") {
      return json(route, { events: [{ event_id: "event-flow-1", event_type: "context_built", title: "构建规划上下文", summary: "已读取状态、伏笔和分支图谱。" }] });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/action-drafts" && method === "GET") {
      return json(route, {
        action_drafts: [
          {
            draft_id: "draft-plot-plan",
            thread_id: "thread-runtime-flow",
            tool_name: "create_plot_plan",
            title: "后端剧情规划草案",
            summary: "生成三种下一章规划，不写正文。",
            risk_level: "low",
            status: "draft",
            confirmation_policy: { confirmation_text: "确认执行" },
            requires_confirmation: true,
            expected_effect: "保存 plot_plan artifact。",
            expected_outputs: ["保存规划 artifact", "供续写任务引用"],
            target_object_ids: ["obj-1"]
          },
          {
            draft_id: "draft-generation-job",
            thread_id: "thread-runtime-flow",
            tool_name: "create_generation_job",
            title: "后端续写任务草案",
            summary: "引用规划生成一个续写分支。",
            risk_level: "medium",
            status: "draft",
            confirmation_policy: { confirmation_text: "确认执行中风险操作" },
            requires_confirmation: true,
            expected_effect: "生成 continuation_branch artifact。",
            expected_outputs: ["构建续写上下文", "保存分支 artifact"],
            target_object_ids: ["obj-1"],
            target_branch_ids: ["branch-runtime-1"]
          },
          {
            draft_id: "draft-accept-branch",
            thread_id: "thread-runtime-flow",
            tool_name: "accept_branch",
            title: "接受分支入主线草案",
            summary: "高风险接受分支入主线，必须确认入库。",
            risk_level: "high",
            status: "draft",
            confirmation_policy: { confirmation_text: "确认入库" },
            requires_confirmation: true,
            expected_effect: "接受分支并刷新 branch_graph。",
            expected_outputs: ["接受正文入主线", "刷新分支图谱"],
            target_branch_ids: ["branch-runtime-1"]
          }
        ]
      });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/artifacts" && method === "GET") {
      return json(route, {
        artifacts: [
          {
            artifact_id: "artifact-plot-plan",
            artifact_type: "plot_plan",
            title: "后端规划 artifact",
            summary: "规划 A 保守推进，规划 B 强化冲突，规划 C 铺垫伏笔。",
            payload: { plot_plan_id: "plot-plan-runtime-1", beats: ["保守推进", "强化冲突", "铺垫伏笔"] },
            related_object_ids: ["obj-1"]
          },
          {
            artifact_id: "artifact-continuation-branch",
            artifact_type: "continuation_branch",
            title: "后端续写分支",
            summary: "生成了一个待审稿的续写分支。",
            payload: { branch_id: "branch-runtime-1", affected_graphs: ["branch_graph"], graph_refresh_required: true },
            related_branch_ids: ["branch-runtime-1"],
            related_object_ids: ["obj-1"]
          }
        ]
      });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/action-drafts/draft-accept-branch/confirm" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.confirmation_text).toBe("确认入库");
      return json(route, {
        draft_id: "draft-accept-branch",
        thread_id: "thread-runtime-flow",
        tool_name: "accept_branch",
        title: "接受分支入主线草案",
        summary: "已确认入库。",
        risk_level: "high",
        status: "confirmed",
        confirmation_policy: { confirmation_text: "确认入库" }
      });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/action-drafts/draft-accept-branch/execute" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.actor).toBe("author");
      return json(route, {
        artifacts: [
          {
            artifact_id: "artifact-branch-acceptance",
            artifact_type: "branch_acceptance",
            title: "分支已接受",
            summary: "正文分支已入主线，等待状态回流审计。",
            related_branch_ids: ["branch-runtime-1"],
            related_object_ids: ["obj-1"]
          }
        ],
        events: [{ event_id: "event-branch-accepted", event_type: "tool_completed", title: "分支入库完成", summary: "branch_graph 已刷新。" }]
      });
    }
    if (options.runtimeFlow && pathname === "/api/dialogue/action-drafts/draft-accept-branch/confirm-and-execute" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.confirmation_text).toBe("确认入库");
      return json(route, {
        artifacts: [
          {
            artifact_id: "artifact-branch-acceptance",
            artifact_type: "branch_acceptance",
            title: "分支已接受",
            summary: "正文分支已入主线，等待状态回流审计。",
            related_branch_ids: ["branch-runtime-1"],
            related_object_ids: ["obj-1"]
          }
        ],
        events: [{ event_id: "event-branch-accepted", event_type: "tool_completed", title: "分支入库完成", summary: "branch_graph 已刷新。" }]
      });
    }
    if (options.runtime && pathname === "/api/dialogue/threads" && method === "GET") {
      return json(route, {
        threads: [
          {
            thread_id: "thread-runtime-1",
            story_id: "story_workbench_s2",
            task_id: "task_workbench_s2",
            scene_type: "state_maintenance",
            title: "后端审计线程",
            status: "active"
          }
        ]
      });
    }
    if (options.runtime && pathname === "/api/dialogue/threads" && method === "POST") {
      return json(route, {
        thread_id: "thread-runtime-2",
        story_id: "story_workbench_s2",
        task_id: "task_workbench_s2",
        scene_type: "state_maintenance",
        title: "新建后端线程",
        status: "active"
      });
    }
    if (options.runtime && pathname === "/api/dialogue/threads/thread-runtime-1") {
      return json(route, {
        thread: {
          thread_id: "thread-runtime-1",
          story_id: "story_workbench_s2",
          task_id: "task_workbench_s2",
          scene_type: "state_maintenance",
          title: "后端审计线程",
          status: "active"
        },
        messages: [{ message_id: "runtime-msg-1", thread_id: "thread-runtime-1", role: "assistant", content: "后端线程已准备好。" }],
        actions: [],
        events: [],
        artifacts: []
      });
    }
    if (options.runtime && pathname === "/api/dialogue/threads/thread-runtime-1/messages" && method === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      options.runtimeMessage?.(body);
      return json(route, {
        thread: {
          thread_id: "thread-runtime-1",
          story_id: "story_workbench_s2",
          task_id: "task_workbench_s2",
          scene_type: "state_maintenance",
          title: "后端审计线程",
          status: "active"
        },
        messages: [{ message_id: "runtime-msg-sent", thread_id: "thread-runtime-1", role: "assistant", content: "已收到工作区上下文。" }],
        actions: [],
        events: [],
        artifacts: []
      });
    }
    if (options.runtime && pathname === "/api/dialogue/threads/thread-runtime-1/events") {
      return json(route, { events: [{ event_id: "event-1", event_type: "context_built", title: "正在构建上下文", summary: "已读取状态环境。" }] });
    }
    if (options.runtime && pathname === "/api/dialogue/action-drafts" && method === "GET") {
      return json(route, {
        action_drafts: [
          {
            draft_id: "draft-runtime-1",
            thread_id: "thread-runtime-1",
            tool_name: "create_audit_action_draft",
            title: "后端审计草案",
            summary: "后端生成的低风险候选审计草案。",
            risk_level: "low",
            status: "draft",
            confirmation_policy: { confirmation_text: "确认执行" },
            requires_confirmation: true,
            expected_effect: "执行后端低风险候选写入。",
            expected_outputs: ["接受低风险候选", "生成状态迁移"],
            target_candidate_ids: ["item-2"],
            target_object_ids: ["obj-2"]
          }
        ]
      });
    }
    if (options.runtime && pathname === "/api/dialogue/artifacts" && method === "GET") {
      return json(route, { artifacts: [] });
    }
    if (options.runtime && pathname === "/api/dialogue/action-drafts/draft-runtime-1/confirm" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.confirmation_text).toBe("确认执行");
      return json(route, {
        draft_id: "draft-runtime-1",
        thread_id: "thread-runtime-1",
        tool_name: "create_audit_action_draft",
        title: "后端审计草案",
        summary: "后端生成的低风险候选审计草案。",
        risk_level: "low",
        status: "confirmed",
        confirmation_policy: { confirmation_text: "确认执行" }
      });
    }
    if (options.runtime && pathname === "/api/dialogue/action-drafts/draft-runtime-1/execute" && method === "POST") {
      return json(route, {
        artifacts: [
          {
            artifact_id: "artifact-runtime-1",
            artifact_type: "audit_result",
            title: "后端审计结果",
            summary: "后端执行草案完成：接受 1 项。",
            related_candidate_ids: ["item-2"],
            related_object_ids: ["obj-2"],
            related_transition_ids: ["transition-runtime-1"]
          }
        ],
        events: [{ event_id: "event-2", event_type: "tool_completed", title: "执行完成", summary: "已更新状态。" }]
      });
    }
    if (options.runtime && pathname === "/api/dialogue/action-drafts/draft-runtime-1/confirm-and-execute" && method === "POST") {
      const body = route.request().postDataJSON();
      expect(body.confirmation_text).toBe("确认执行");
      return json(route, {
        artifacts: [
          {
            artifact_id: "artifact-runtime-1",
            artifact_type: "audit_result",
            title: "后端审计结果",
            summary: "后端执行草案完成：接受 1 项。",
            related_candidate_ids: ["item-2"],
            related_object_ids: ["obj-2"],
            related_transition_ids: ["transition-runtime-1"]
          }
        ],
        events: [{ event_id: "event-2", event_type: "tool_completed", title: "执行完成", summary: "已更新状态。" }]
      });
    }
    if (pathname.endsWith("/environment")) {
      return json(route, environmentPayload(url.searchParams.get("scene_type") || "state_maintenance"));
    }
    if (pathname.endsWith("/state/candidates")) {
      return json(route, candidatesPayload());
    }
    if (pathname.endsWith("/state") && method === "GET") {
      return json(route, statePayload());
    }
    if (pathname.endsWith("/state/candidates/review") && method === "POST") {
      const body = route.request().postDataJSON();
      expect(["accept", "reject", "mark_conflicted"]).toContain(body.operation);
      expect(body.confirmed_by).toBe("author");
      const accepted = body.operation === "accept" ? body.candidate_item_ids.length : 0;
      const rejected = body.operation === "reject" ? body.candidate_item_ids.length : 0;
      const conflicted = body.operation === "mark_conflicted" ? body.candidate_item_ids.length : 0;
      return json(route, {
        status: "completed",
        action_id: "review-action-e2e",
        transition_ids: accepted ? ["transition-e2e"] : [],
        updated_object_ids: accepted ? ["obj-2"] : [],
        result: { accepted, rejected, conflicted, skipped: 0 },
        warnings: [],
        blocking_issues: []
      });
    }
    if (pathname.endsWith("/branches")) {
      if (options.runtimeFlow) {
        return json(route, {
          story_id: "story_workbench_s2",
          task_id: "task_workbench_s2",
          branches: [
            {
              branch_id: "branch-runtime-1",
              story_id: "story_workbench_s2",
              task_id: "task_workbench_s2",
              title: "后端续写分支",
              status: "ready_for_review",
              summary: "一个可审稿分支"
            }
          ]
        });
      }
      return json(route, { story_id: "story_workbench_s2", task_id: "task_workbench_s2", branches: [] });
    }
    if (pathname === "/api/dialogue/sessions") {
      if (method === "POST") return json(route, dialogueDetail().session);
      return json(route, { sessions: [dialogueDetail().session] });
    }
    if (pathname.includes("/api/dialogue/sessions/")) {
      return json(route, dialogueDetail());
    }
    if (pathname === "/api/jobs") {
      return json(route, { jobs: [] });
    }
    if (pathname.includes("/graph/analysis")) {
      return json(route, {
        story_id: "story_workbench_s2",
        task_id: "task_workbench_s2",
        nodes: [],
        edges: [],
        fallback: true,
        fallback_reason: "analysis graph route unavailable; using empty projection."
      });
    }
    if (pathname.includes("/graph/")) {
      return json(route, {
        story_id: "story_workbench_s2",
        task_id: "task_workbench_s2",
        nodes: [{ id: "obj-1", type: "state_object", label: "Lin Zhao", data: { object_type: "character", confidence: 0.9 } }],
        edges: []
      });
    }
    return json(route, {});
  });
}

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

function runtimeSendThread() {
  return {
    thread_id: "thread-runtime-send",
    story_id: "story_workbench_s2",
    task_id: "task_workbench_s2",
    scene_type: "state_maintenance",
    title: "运行时审计线程",
    status: "active"
  };
}

function runtimeSendDetail(posted: boolean) {
  return {
    thread: runtimeSendThread(),
    messages: posted
      ? [
          { message_id: "runtime-send-user", thread_id: "thread-runtime-send", role: "user", content: "帮我审计当前候选，低风险先生成通过草案。" },
          {
            message_id: "runtime-send-assistant",
            thread_id: "thread-runtime-send",
            role: "assistant",
            content: "已基于状态环境生成候选审计草案，等待确认。",
            metadata: {
              runtime_mode: "llm",
              model_invoked: true,
              model_name: "test-model",
              llm_called: true,
              llm_success: true,
              draft_source: "llm",
              context_hash: "ctx-runtime-send",
              candidate_count: 2,
              draft_count: 1,
              token_usage_ref: "usage-runtime-send"
            }
          }
        ]
      : [],
    actions: posted ? [runtimeSendDraft()] : [],
    events: posted ? runtimeSendEvents() : [],
    artifacts: []
  };
}

function runtimeSendEvents() {
  return [
    { event_id: "event-runtime-send-context", event_type: "context_built", title: "正在构建上下文", summary: "已读取状态环境。", payload: { llm_called: true, draft_source: "llm" } },
    { event_id: "event-runtime-send-llm-started", event_type: "llm_call_started", title: "正在调用模型", summary: "已发送 dialogue_audit_planning 请求。", payload: { llm_called: true, draft_source: "llm", model_name: "test-model" } },
    { event_id: "event-runtime-send-llm-completed", event_type: "llm_call_completed", title: "模型调用完成", summary: "模型返回 1 个候选审计草案。", payload: { llm_called: true, llm_success: true, draft_source: "llm", candidate_count: 2, draft_count: 1 } },
    { event_id: "event-runtime-send-draft", event_type: "draft_created", title: "模型生成审计草案", summary: "接受 1 项，保留 1 项。", payload: { llm_called: true, llm_success: true, draft_source: "llm", draft_count: 1 } }
  ];
}

function runtimeSendDraft() {
  return {
    draft_id: "draft-runtime-send",
    thread_id: "thread-runtime-send",
    tool_name: "create_audit_action_draft",
    title: "候选审计草案",
    summary: "模型基于状态环境生成的低风险候选审计草案。",
    risk_level: "low",
    status: "draft",
    confirmation_policy: { confirmation_text: "确认执行" },
    requires_confirmation: true,
    expected_effect: "接受 1 项低风险候选，保留 1 项继续审计。",
    expected_outputs: ["接受低风险候选", "记录审计事件"],
    target_candidate_ids: ["item-2"],
    target_object_ids: ["obj-2"],
    metadata: {
      runtime_mode: "llm",
      model_invoked: true,
      model_name: "test-model",
      llm_called: true,
      llm_success: true,
      draft_source: "llm",
      context_hash: "ctx-runtime-send",
      candidate_count: 2,
      draft_count: 1,
      token_usage_ref: "usage-runtime-send"
    }
  };
}

function environmentPayload(sceneType: string) {
  return {
    story_id: "story_workbench_s2",
    task_id: "task_workbench_s2",
    task_type: "StateMaintenanceTask",
    scene_type: sceneType,
    working_state_version_no: 2,
    selected_object_ids: [],
    selected_candidate_ids: [],
    selected_evidence_ids: [],
    selected_branch_ids: [],
    source_role_policy: {},
    authority_policy: {},
    context_budget: { max_objects: 80, max_candidates: 80 },
    retrieval_policy: {},
    compression_policy: {},
    allowed_actions: ["review_state_candidate"],
    required_confirmations: [],
    warnings: [],
    summary: { pending_candidate_count: 1, database: { ok: true } },
    context_sections: {}
  };
}

function candidatesPayload() {
  return {
    story_id: "story_workbench_s2",
    task_id: "task_workbench_s2",
    candidate_sets: [{ candidate_set_id: "set-1", status: "pending_review", source_id: "edit-state" }],
    candidate_items: [
      {
        candidate_item_id: "item-1",
        candidate_set_id: "set-1",
        target_object_id: "obj-1",
        target_object_type: "event",
        field_path: "summary",
        operation: "replace",
        before_value: "old",
        proposed_value: "new",
        authority_request: "author_confirmed",
        source_role: "author_seeded",
        evidence_count: 1,
        confidence: 0.8,
        status: "pending_review"
      },
      {
        candidate_item_id: "item-2",
        candidate_set_id: "set-1",
        target_object_id: "obj-2",
        target_object_type: "location",
        field_path: "summary",
        operation: "upsert",
        before_value: null,
        proposed_value: "Clock tower observatory",
        authority_request: "canonical",
        source_role: "author_seeded",
        evidence_count: 1,
        confidence: 0.95,
        status: "pending_review"
      }
    ],
    evidence: [
      { evidence_id: "ev-1", object_id: "obj-1", field_path: "summary", quote_text: "The clock tower keeps the memory." },
      { evidence_id: "ev-2", object_id: "obj-2", field_path: "summary", quote_text: "The observatory is inside the clock tower." }
    ]
  };
}

function statePayload() {
  return {
    story_id: "story_workbench_s2",
    task_id: "task_workbench_s2",
    state_objects: [{ object_id: "obj-1", display_name: "Lin Zhao", object_type: "character", confidence: 0.9 }],
    state_evidence_links: [],
    candidate_sets: candidatesPayload().candidate_sets,
    candidate_items: candidatesPayload().candidate_items
  };
}

function dialogueDetail() {
  return {
    session: {
      session_id: "session-1",
      story_id: "story_workbench_s2",
      task_id: "task_workbench_s2",
      scene_type: "state_maintenance",
      status: "active"
    },
    messages: [{ message_id: "msg-1", session_id: "session-1", role: "system", content: "ready" }],
    actions: []
  };
}
