# ER 图与实体关系

```mermaid
erDiagram
    STORIES ||--o{ STORY_VERSIONS : has
    STORIES ||--o{ THREADS : owns
    STORIES ||--o{ CHAPTERS : contains
    STORIES ||--o{ CHARACTER_PROFILES : defines
    STORIES ||--o{ WORLD_FACTS : stores
    STORIES ||--o{ PLOT_THREADS : tracks
    STORIES ||--o{ EPISODIC_EVENTS : records
    STORIES ||--o{ STYLE_PROFILES : applies
    STORIES ||--o{ USER_PREFERENCES : receives
    STORIES ||--o{ CONFLICT_QUEUE : accumulates

    THREADS ||--o{ CHECKPOINTS : creates
    THREADS ||--o{ VALIDATION_RUNS : produces
    THREADS ||--o{ COMMIT_LOG : writes
    THREADS ||--o{ CONFLICT_QUEUE : triggers

    CHAPTERS ||--o{ EPISODIC_EVENTS : includes

    STORIES {
        text story_id PK
        text title
        text premise
        text status
    }
    STORY_VERSIONS {
        bigint version_id PK
        text story_id FK
        int version_no
        jsonb snapshot
    }
    THREADS {
        text thread_id PK
        text story_id FK
        text last_checkpoint_id
        text status
    }
    CHECKPOINTS {
        text checkpoint_id PK
        text thread_id FK
        text node_name
        jsonb state_payload
    }
    CHAPTERS {
        text chapter_id PK
        text story_id FK
        int chapter_number
        text summary
        text content
    }
    CHARACTER_PROFILES {
        text character_id PK
        text story_id FK
        jsonb profile
    }
    WORLD_FACTS {
        bigint fact_id PK
        text story_id FK
        text fact_type
        text content
        bool conflict_mark
    }
    PLOT_THREADS {
        text plot_thread_id PK
        text story_id FK
        text status
        text next_expected_beat
    }
    EPISODIC_EVENTS {
        text event_id PK
        text story_id FK
        text chapter_id FK
        text summary
        bool is_canonical
    }
    STYLE_PROFILES {
        text profile_id PK
        text story_id FK
        jsonb profile
    }
    USER_PREFERENCES {
        bigint preference_id PK
        text story_id FK
        text thread_id FK
        text preference_key
        jsonb preference_value
        bool is_confirmed
    }
    VALIDATION_RUNS {
        bigint validation_id PK
        text thread_id FK
        text status
        jsonb consistency_issues
        jsonb style_issues
    }
    COMMIT_LOG {
        bigint commit_id PK
        text thread_id FK
        text commit_status
        jsonb accepted_changes
        jsonb rejected_changes
        jsonb conflict_changes
    }
    CONFLICT_QUEUE {
        bigint conflict_id PK
        text story_id FK
        text thread_id FK
        text change_id
        text update_type
        jsonb proposed_change
        text reason
        text status
    }
```

## 实体职责

- `stories`: 作品根对象
- `story_versions`: 完整状态快照版本
- `threads`: 多轮交互线程
- `checkpoints`: LangGraph 节点级检查点
- `chapters`: 章节正文与摘要
- `character_profiles`: 角色状态和口吻档案
- `world_facts`: 世界规则、设定事实和 conflict-marked fact
- `plot_threads`: 主支线和伏笔推进
- `episodic_events`: 规范化事件记忆
- `style_profiles`: 风格约束和 exemplar 统计
- `user_preferences`: 用户偏好与禁用项
- `validation_runs`: 每轮验证结果
- `commit_log`: 提交、回滚和 conflict 审计记录
- `conflict_queue`: 与旧设定冲突、待人工处理的 proposal 队列
