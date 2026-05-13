# 对话主入口开源参考

本文档记录本轮重构可参考的开源项目。结论先行：**不要直接整体搬一个 ChatGPT clone；更适合吸收 assistant-ui 的对话组件范式、CopilotKit 的应用状态与动作绑定范式，再参考 LibreChat/Open WebUI 的线程、模型、工具和插件组织方式。**

## 一、assistant-ui

链接：

```text
https://www.assistant-ui.com/
https://github.com/assistant-ui/assistant-ui
```

可借鉴点：

1. React/TypeScript 对话组件。
2. ChatGPT 风格线程体验。
3. 流式输出、自动滚动、可访问性、实时更新。
4. 组件可组合，不是单体大组件。
5. 适合我们把“对话线程 + 运行卡片 + 草案卡片”组合起来。

适合程度：

```text
高
```

原因：

```text
我们已有 React/Vite 前端，需要的是高质量对话主界面，而不是完整替换后端。
```

建议用法：

```text
优先参考其线程、消息、composer、运行状态和可组合组件结构。
不建议一开始引入其云服务或完整托管线程。
```

## 二、CopilotKit

链接：

```text
https://www.copilotkit.ai/
https://github.com/CopilotKit/CopilotKit
```

可借鉴点：

1. 应用内 AI 助手。
2. 模型能读取当前 UI/应用状态。
3. 模型能触发应用动作。
4. React hooks 暴露状态与动作。
5. 非常符合“模型在上下文环境中生成动作草案”的方向。

适合程度：

```text
高
```

原因：

```text
我们的核心不是普通聊天，而是让模型看到小说状态环境，并生成可确认的动作草案。
```

建议用法：

```text
参考 useReadable / useAction 的思想。
后端仍由我们自己的状态机和动作确认协议控制。
前端可以借鉴“当前页面状态暴露给助手”的组织方式。
```

## 三、LibreChat

链接：

```text
https://www.librechat.ai/about
https://github.com/danny-avila/LibreChat
```

可借鉴点：

1. 多模型统一对话界面。
2. 会话、预设、插件、Agent、MCP 等组织方式。
3. 自托管和多用户方向较成熟。
4. 多语言界面经验。
5. Artifacts、工具调用、代码解释器等交互模式值得参考。

适合程度：

```text
中
```

原因：

```text
它是完整 ChatGPT clone，功能很大。我们不需要整体替换工作台，但可以参考会话列表、模型选择、工具结果、Artifacts 展示。
```

建议用法：

```text
参考其“线程 + 工具 + artifacts + 多模型”的产品结构。
不建议直接迁移整套架构。
```

## 四、Open WebUI

链接：

```text
https://github.com/open-webui/open-webui
```

可借鉴点：

1. 自托管 AI 平台。
2. 支持 OpenAI-compatible API。
3. RAG、插件、Pipelines、工具扩展。
4. 离线部署和本地模型场景成熟。

适合程度：

```text
中低
```

原因：

```text
它偏完整 AI 平台和模型网关。我们的后端状态机已经存在，不能被替换。
```

注意：

```text
需关注许可证和品牌保留要求，不建议直接复制代码。
```

建议用法：

```text
参考其工具、RAG、模型连接、插件配置的产品组织方式。
不要直接依赖其 UI 或后端。
```

## 五、结论

本项目建议采用：

```text
assistant-ui 的对话组件思路
  + CopilotKit 的状态暴露和动作绑定思路
  + LibreChat 的线程/工具/artifact 产品经验
  + 自己已有的状态机、数据库、任务、审计、生成后端
```

不要做：

```text
直接把 Open WebUI/LibreChat 整套搬进来。
把模型对话做成独立聊天玩具。
让模型绕过状态机直接执行写库。
```

要做：

```text
对话线程成为主入口。
上下文环境由后端构建。
模型生成动作草案。
作者确认执行。
执行结果成为对话线程中的 artifact。
```

## 六、参考来源

```text
assistant-ui 官网说明其目标是把 ChatGPT 风格 UX 放入应用，并提供生产级 React AI chat 组件。
assistant-ui GitHub README 提到其处理 streaming、auto-scrolling、accessibility、real-time updates，并可与自定义后端配合。
CopilotKit 资料强调应用内 AI 助手能理解应用状态并触发动作。
LibreChat 官网说明其是开源、多模型、可扩展、自托管 AI 平台。
Open WebUI GitHub README 说明其是可扩展、自托管 AI 平台，支持 OpenAI-compatible API、RAG 和插件。
```
