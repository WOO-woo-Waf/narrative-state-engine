export function statusLabel(value?: string | number | null): string {
  const text = String(value ?? "");
  const labels: Record<string, string> = {
    pending_review: "待审计",
    candidate: "候选",
    accepted: "已接受",
    rejected: "已拒绝",
    conflicted: "有冲突",
    canonical: "主状态",
    queued: "排队中",
    running: "运行中",
    succeeded: "已成功",
    failed: "已失败",
    draft: "草稿",
    active: "进行中",
    completed: "已完成",
    partially_reviewed: "部分审计"
  };
  return labels[text] || text || "未知";
}

export function sceneLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    state_creation: "状态创建",
    analysis_review: "状态分析",
    state_maintenance: "候选审计",
    plot_planning: "剧情规划",
    continuation_generation: "续写任务",
    branch_review: "分支审计",
    revision: "修订"
  };
  return labels[String(value || "")] || String(value || "未选择场景");
}

export function sourceRoleLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    primary_story: "主故事",
    same_world_reference: "同世界观参考",
    crossover_reference: "联动参考",
    style_reference: "风格参考",
    author_seeded: "作者种子",
    model_inferred: "模型推断"
  };
  return labels[String(value || "")] || String(value || "未知来源");
}

export function authorityLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    canonical: "主状态",
    author_confirmed: "作者确认",
    author_locked: "作者锁定",
    model_suggested: "模型建议"
  };
  return labels[String(value || "")] || String(value || "未指定");
}

export function operationLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    add: "新增",
    create: "新增",
    update: "更新",
    replace: "替换",
    delete: "删除",
    merge: "合并",
    upsert: "新增或更新",
    lock_field: "锁定字段",
    mark_conflicted: "标记冲突"
  };
  return labels[String(value || "")] || String(value || "未知操作");
}

export function objectTypeLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    character: "角色",
    relationship: "关系",
    scene: "场景",
    location: "地点",
    organization: "组织",
    object: "物件",
    world_rule: "世界规则",
    world_concept: "世界概念",
    terminology: "术语",
    plot_thread: "剧情线",
    foreshadowing: "伏笔",
    style: "风格",
    technique: "技法",
    resource: "资源",
    power_system: "功法体系",
    system_level: "体系等级",
    rule_mechanism: "规则机制"
  };
  return labels[String(value || "")] || String(value || "对象");
}

export function databaseLabel(ok?: boolean): string {
  if (ok === true) return "数据库在线";
  if (ok === false) return "数据库离线";
  return "正在检查数据库";
}
