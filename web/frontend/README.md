# Author Workbench Frontend

React + TypeScript implementation of `docs/30_author_workbench_frontend_execution_plan.md`.

## Commands

```powershell
npm install
npm run dev
npm run build
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. Production builds use the `/workbench-v2/` base path so the backend can mount the generated `dist` directory there.

## Implemented Scope

- FE-A: Vite React project, API client, workspace store, three-column Shell, story/task/scene selectors.
- FE-B: StateEnvironment panel, dialogue session flow, message list, action card, confirm/cancel calls.
- FE-C: virtualized candidate review table, field diff viewer, evidence viewer, accept/reject/lock/request-evidence controls.
- FE-D: React Flow state, transition, analysis, and branch graph views with node selection linkage.
- FE-E: plot planning, generation, branch review, and revision panels.
- FE-F: candidate virtual scrolling, lazy Monaco JSON inspector, graph aggregation indicator, running-job-only polling behavior.

The frontend calls backend `/api` endpoints and does not invoke CLI commands directly.
