# Radar — 架构与设计文档

> 版本：0.1.0 · 更新于 2026-05-30

---

## 一句话定位

Radar 是一个**持续运行的 AI 需求热点发现与评测闭环平台**：从 GitHub 和 Reddit 持续抓取 AI 相关项目，用 LLM（yunwu MiniMax-M2.7）做需求打分和领域分类，把高分热点自动投入 heyi-eval 评测引擎实测，结果回流到统一 Web 站公开展示。

公网地址：**https://radar.yoliyoli.uk**（Cloudflare Tunnel，TLS 自动签发）

---

## 系统全局架构

```
                        ┌─────────────────────────────┐
                        │   Cloudflare 边缘 / HTTPS   │
                        │   radar.yoliyoli.uk          │
                        └──────────────┬──────────────┘
                                       │ Cloudflare Tunnel
                        ┌──────────────▼──────────────┐
                        │   heyi 本地机器               │
                        │                              │
                        │  ┌───────────────────────┐  │
  GitHub Search API ───▶│  │    radar              │  │
  Reddit JSON API  ───▶│  │    FastAPI + React    │  │
                        │  │    :7090 (内网)        │  │
                        │  │                       │  │
                        │  │ APScheduler 调度      │  │
                        │  │  ├─ GitHub 爬取 (6h)  │  │
                        │  │  ├─ Reddit 爬取 (1h)  │  │
                        │  │  ├─ LLM 打分 (30min)  │  │
                        │  │  └─ 报告渲染 (cron)   │  │
                        │  └───────┬───────────────┘  │
                        │          │ LLM API           │
                        │          ▼                   │
                        │  yunwu MiniMax-M2.7          │
                        │  (OpenAI 兼容 Cloud)         │
                        │                              │
                        │  ┌────────────────────────┐  │
                        │  │   heyi-eval-v10        │  │
                        │  │   project/skill lane   │  │
                        │  │   (m2b-claude-code)    │  │
                        │  └────────────────────────┘  │
                        │    ↑ GET /api/items           │
                        │    └─── 日频热点入队          │
                        └─────────────────────────────┘
```

---

## 模块结构

```
radar/
├── src/radar/
│   ├── app.py              # FastAPI 应用工厂 + lifespan 钩子
│   ├── config.py           # 全局配置（pydantic-settings，读 .env）
│   ├── cli.py              # CLI 入口（radar init/serve/crawl/score）
│   │
│   ├── sources/            # 数据抓取层
│   │   ├── github/         #   GitHub Search API 增量爬取
│   │   └── reddit/         #   Reddit JSON API 增量爬取
│   │
│   ├── analyzer/           # 分析层
│   │   ├── scorer.py       #   LLM QAG 四维度打分 + 领域分类
│   │   └── domain_meta.py  #   12 领域静态元数据（市场特征/关键词）
│   │
│   ├── outputs/            # 报告渲染层
│   │   ├── projects.py     #   AI 项目分类 HTML 报告
│   │   ├── communities.py  #   社群资源地图 HTML + JSON 快照
│   │   └── renderer.py     #   Jinja2 渲染工具
│   │
│   ├── runtime/            # 运行时
│   │   ├── scheduler.py    #   APScheduler（随 serve 启动）
│   │   └── watcher.py      #   12 类告警信号监控（每 5min 巡检）
│   │
│   ├── storage/            # 持久化
│   │   ├── models.py       #   SQLAlchemy ORM（Item/Score/Tag/...）
│   │   └── database.py     #   引擎初始化 + get_session
│   │
│   ├── eval/               # heyi-eval 结果回流（只读）
│   │   └── reader.py       #   扫描 lane runs 目录 → EvalResult
│   │
│   └── web/
│       └── api/            # FastAPI 路由层
│           ├── items.py    #   GET /api/items（scored 热点，供 heyi-eval）
│           ├── eval.py     #   GET /api/eval/results（评测结果回流）
│           ├── sources.py  #   数据源状态 + 手动触发抓取
│           ├── reports.py  #   报告列表 / 下载
│           ├── incidents.py#   告警事件
│           ├── tokens.py   #   凭证管理（GitHub Token / Reddit OAuth）
│           └── settings_api.py # 运行时配置热更新
│
├── web/                    # React 前端（Vite + TypeScript + Ant Design）
│   ├── src/
│   │   ├── App.tsx         #   路由 + 侧边栏 + 错误边界
│   │   ├── api/client.ts   #   全部后端接口封装
│   │   └── pages/
│   │       ├── Dashboard.tsx      # 仪表盘
│   │       ├── EvalResults.tsx    # 实测结果（heyi-eval 回流）★
│   │       ├── ReportsProjects.tsx
│   │       ├── ReportsCommunities.tsx
│   │       ├── Sources.tsx
│   │       ├── Tokens.tsx
│   │       ├── Settings.tsx
│   │       └── Incidents.tsx
│   └── dist/               #   构建产物（FastAPI 托管）
│
└── deploy/
    ├── systemd/
    │   ├── radar.service         # radar 本体（:7090）
    │   └── cloudflared.service   # Cloudflare Tunnel 系统服务
    ├── cloudflared/
    │   └── config.yml.example    # ingress 配置模板
    ├── env.example               # 生产环境变量模板
    └── DEPLOY.md                 # 完整部署指南
```

---

## 数据模型

技术栈：SQLAlchemy 2.x async ORM，PostgreSQL（生产）/ SQLite（默认，零依赖）双支持。共 8 张表。

```
source_runs ──< items >── scores
                  │
                  ├──< tags
                  └──< raw_blobs

reports（独立）
incidents >── incident_actions
```

---

### `source_runs` — 每次抓取任务记录

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `source` | varchar(64) NOT NULL | `"github"` / `"reddit"` |
| `cursor` | text | 增量游标（时间戳/ID），下次从此继续 |
| `status` | varchar(20) | `pending` / `running` / `done` / `failed` |
| `items_in` | int | 本次抓到的原始条目数（含重复） |
| `items_new` | int | 去重后实际入库的新增数 |
| `error` | text | 错误信息（`failed` 时填写） |
| `started_at` | timestamptz | 任务开始时间 |
| `finished_at` | timestamptz | 任务结束时间 |
| `created_at` | timestamptz | 记录创建时间 |

索引：`(source, created_at)`

---

### `items` — 统一内容条目

跨 GitHub / Reddit 所有源归一化，`url_hash` 全局唯一去重。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `source` | varchar(64) NOT NULL | `"github"` / `"reddit"` |
| `external_id` | varchar(256) NOT NULL | GitHub: `"owner/repo"`；Reddit: `post_id` |
| `url` | text NOT NULL | 条目链接 |
| `url_hash` | varchar(64) UNIQUE | SHA-256(url)，跨 run 去重用 |
| `title` | text | 仓库名 / 帖子标题 |
| `content` | text | repo description / 帖子正文（截断 ~1000 字） |
| `platform_data` | JSON | 平台专属字段（见下方展开） |
| `source_run_id` | varchar(36) FK→source_runs | 关联抓取任务（SET NULL on delete） |
| `item_at` | timestamptz | 内容发布时间（repo push_at / 帖子发布时间） |
| `fetched_at` | timestamptz | 入库时间 |
| `created_at` | timestamptz | 记录创建时间 |

唯一约束：`(source, external_id)`
索引：`url_hash`（unique）、`(source, fetched_at)`、`item_at`

**`platform_data` GitHub 字段**

```json
{
  "stars": 1052,
  "forks": 104,
  "language": "Python",
  "topics": ["fastapi", "ai-security"],
  "open_issues": 0,
  "license": "MIT",
  "owner_login": "beenuar",
  "owner_type": "User",
  "is_fork": false,
  "is_archived": false,
  "pushed_at": "2026-05-29T06:56:52Z",
  "updated_at": "2026-05-29T06:56:35Z",
  "watchers": 1052
}
```

**`platform_data` Reddit 字段**

```json
{
  "subreddit": "LocalLLaMA",
  "post_id": "t3_abc123",
  "author": "u/someone",
  "ups": 342,
  "upvote_ratio": 0.94,
  "num_comments": 87,
  "score": 342,
  "total_awards": 2,
  "is_self": true,
  "flair": "Discussion",
  "domain": "self.LocalLLaMA"
}
```

---

### `raw_blobs` — 原始 API Payload 留档

保留完整原始响应，供重跑评分时无需重新抓取。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `item_id` | varchar(36) UNIQUE FK→items | 一对一关联 |
| `payload` | text | JSON 序列化的原始 API 响应 |
| `content_type` | varchar(64) | 默认 `"application/json"` |
| `stored_at` | timestamptz | 存入时间 |

---

### `scores` — LLM 评分记录

同一 Item 支持多次历史评分（不同版本 LLM / 不同 evaluator），以 `scored_at` 最新为准。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `item_id` | varchar(36) FK→items | 关联条目（CASCADE delete） |
| `evaluator` | varchar(64) | `"qag"`（主评分）/ `"domain_classifier"` |
| `score` | float | 综合分 0-1（公式见下） |
| `dimensions` | JSON | 各维度细节（见下方展开） |
| `llm_profile` | varchar(32) | 打分时使用的 LLM：`"yunwu"` / `"zhipu"` / `"ollama"` |
| `scored_at` | timestamptz | 评分时间 |
| `created_at` | timestamptz | 记录创建时间 |

索引：`(item_id, evaluator)`、`scored_at`

**综合分公式**

```
score = pain × 0.35 + market × 0.30 + feasibility × 0.20 + velocity × 0.15
```

**`dimensions` 结构（evaluator=qag）**

```json
{
  "pain": 0.78,
  "market": 0.72,
  "feasibility": 0.82,
  "velocity": 0.68,
  "reason": "SOC告警疲劳是真实痛点，安全市场百亿级，开源+MIT许可降低落地门槛"
}
```

---

### `tags` — 命名空间标签

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `item_id` | varchar(36) FK→items | 关联条目（CASCADE delete） |
| `namespace` | varchar(64) | `"domain"` / `"category"` / `"keyword"` |
| `value` | varchar(256) | 如 `"coding"` / `"infra"` / `"rag"` 等 |
| `created_at` | timestamptz | 记录创建时间 |

唯一约束：`(item_id, namespace, value)`
索引：`(namespace, value)`

**当前使用的 namespace**

| namespace | 说明 | 典型 value |
|---|---|---|
| `domain` | 12 领域分类（由 LLM 打分时写入） | `coding` / `infra` / `rag` / `browser` / ... |

---

### `reports` — 报告渲染记录

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `template` | varchar(32) | `"projects"` / `"communities"` |
| `period_key` | varchar(16) | 数据窗口标识，如 `"2026-06-01"` |
| `params` | JSON | 渲染参数快照（domains 数量 / days_back / 文件大小等） |
| `file_path` | text | 磁盘绝对路径（`outputs/projects_20260601_0600.html`） |
| `item_count` | int | 本次报告包含的条目数 |
| `status` | varchar(16) | `"pending"` / `"ok"` / `"failed"` |
| `error` | text | 渲染失败时的错误信息 |
| `llm_profile` | varchar(32) | 渲染时使用的 LLM Profile |
| `generated_at` | timestamptz | 生成时间 |
| `expires_at` | timestamptz | 过期时间（超过保留天数后可清理） |
| `created_at` | timestamptz | 记录创建时间 |

唯一约束：`(template, period_key)`
索引：`(template, generated_at)`

---

### `incidents` — 监控告警事件

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `signal_type` | varchar(64) | 12 类信号（见下方） |
| `severity` | varchar(16) | `"info"` / `"warning"` / `"critical"` |
| `affected_resource` | varchar(256) | `"github"` / `"reddit"` / `"token:github"` 等 |
| `title` | text NOT NULL | 展示标题 |
| `detail` | text | 详细说明 |
| `context_data` | JSON | 发现时的现场数据快照 |
| `status` | varchar(16) | `"open"` / `"resolving"` / `"resolved"` / `"dismissed"` |
| `resolution` | varchar(128) | 使用了哪个 `action_key` 解决 |
| `resolution_note` | text | 解决备注 |
| `notified_at` | timestamptz | 最近一次发送通知的时间 |
| `detected_at` | timestamptz | 告警触发时间 |
| `resolved_at` | timestamptz | 解决时间 |
| `created_at` | timestamptz | 记录创建时间 |

索引：`(signal_type, affected_resource, status)`、`detected_at`

**12 类 signal_type**

| signal_type | 含义 |
|---|---|
| `data_stale` | 数据源超过阈值时间未更新（默认 2h） |
| `source_failing` | 数据源连续多次抓取失败 |
| `reddit_auth_fail` | Reddit 返回 403（需配置 OAuth） |
| `github_rate_limit` | GitHub API 触发速率限制 |
| `token_expiring` | Token 在 48h 内到期 |
| `token_expired` | Token 已过期 |
| `disk_low` | 磁盘剩余空间低于阈值（默认 5GB） |
| `llm_unavailable` | LLM 服务不可达 |
| `report_failed` | 报告渲染任务失败 |
| `score_queue_stuck` | 待评分条目积压超过阈值 |
| `db_slow` | 数据库响应时间过长 |
| `custom` | 自定义告警（预留） |

---

### `incident_actions` — 告警修复动作

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(36) PK | UUID |
| `incident_id` | varchar(36) FK→incidents | 关联告警（CASCADE delete） |
| `action_key` | varchar(64) | `"retry_source"` / `"refresh_token"` / `"clear_cache"` 等 |
| `label` | varchar(128) | 展示给用户的按钮文案 |
| `endpoint` | varchar(256) | 前端调用的 API 路径（如 `/tokens`） |
| `order` | int | 展示顺序（0 = 主推动作） |
| `last_error` | text | 执行失败时记录错误 |
| `executed_at` | timestamptz | 最近一次执行时间 |
| `created_at` | timestamptz | 记录创建时间 |

---

## heyi-eval 评测架构

heyi-eval-v10 是与 radar 并列运行的评测引擎，部署在同一台 heyi 机器（上海 GPU 服务器）上。radar 负责发现和打分热点，heyi-eval 负责对热点做自动实测，结果回流到 radar 的「实测结果」页。

### 信任域划分

heyi-eval 的最核心设计原则是**多层隔离**，避免评测代码影响产线服务：

```
┌──────────────────────────────────────────────────────────────────────┐
│  heyi 机器                                                           │
│                                                                      │
│  PROD 信任域                  ORCH 信任域                            │
│  ┌─────────────────────┐     ┌────────────────────────────────────┐  │
│  │ 产线 vLLM (GPU 0-3) │     │ orchestrator / curator / discover  │  │
│  │ minimax :10814       │◄───│ panel / backup / heyi_engine       │  │
│  │ 评测代码只能 HTTP 访问 │     │ 持有 docker socket + 数据全权     │  │
│  └─────────────────────┘     └────────────┬───────────────────────┘  │
│                                            │ docker spawn            │
│  EVAL 信任域                               ▼                         │
│  ┌────────────────────────────────────┐  ┌────────────────────────┐  │
│  │ e9-vllm-* / e9-sglang-* (GPU 5-7) │  │ m2b-claude-code        │  │
│  │ 评测容器，名称强制 e9-* 前缀        │  │ project/skill agent 沙箱│  │
│  │ 仅 DEPLOY 阶段创建，CLEANUP 销毁   │  │ uid=1100, 无 docker    │  │
│  └────────────────────────────────────┘  └────────────────────────┘  │
│                                                                      │
│  DATA 信任域                                                         │
│  /home/ai/heyi-eval-data/  ←  ORCH 全权                            │
│  /home/ai/heyi-eval-backups/  ←  INV-9: 备份在数据根之外            │
└──────────────────────────────────────────────────────────────────────┘
```

### 三条评测车道全景

```
                ┌─────────────────────────────────────────────┐
数据源          │  HuggingFace Hub API   agents-radar manifest  本地 SKILL.md
                └──────────┬──────────────────┬──────────────┬─┘
                           │                  │              │
                    discover/main.py   radar_ingest.py  skill_local_scan.py
                           │                  │              │
                           └──────────────────┴──────────────┘
                                              │
                                   project_candidates.jsonl
                                   skill_candidates.jsonl
                                   candidates.jsonl（model）
                                              │
                  ┌───────────────────────────┼───────────────────────────┐
                  │                           │                           │
            model_lane                 project_lane                skill_lane
         11 阶段 vLLM 评测         agent 实测 GitHub 项目       agent 评测 SKILL.md
                  │                           │                           │
                  ▼                           ▼                           ▼
          runs/<run_id>/           project_lane/runs/            skill_lane/runs/
         capability.json           state.json                   state.json
         perf_bench.json           report.json                  report.json
         showcase.json             agent.log                    agent.log
                  │                           │                           │
                  └───────────────────────────┴───────────────────────────┘
                                              │
                                   radar eval/reader.py 只读扫描
                                              │
                                   GET /api/eval/results
                                              │
                                   radar.yoliyoli.uk 实测结果页
```

### model_lane — 11 阶段 HF 模型评测

```
DISCOVER → CURATE → METADATA → ENGINE_SELECT → STAGE_MODEL
                                                     │
              ┌──────────────────────────────────────┘
              ▼
         DEPLOY → READY_WAIT → CAPABILITY → PERF_BENCH → SHOWCASE → CLEANUP
```

**分层说明**

- **run-level 阶段**（DISCOVER→STAGE_MODEL）：失败时从头整 run 重启，代价低（磁盘 IO 不涉及 GPU）
- **stage-level 阶段**（DEPLOY→CLEANUP）：保留 DEPLOY 结果，从上一个 OK 阶段续跑，避免浪费 60-120s vLLM 启动时间

**GPU 隔离**：产线 `minimax` 容器占 GPU 0-3，评测 `e9-*` 容器独占 GPU 5-7，INV-1 强制检查不重叠。

### project_lane + skill_lane — Agent 评测架构

project 和 skill 两条 lane 共用同一个 `agent_driver/` 执行层：

```
orchestrator project run / skill run
           │
           ▼
    agent_driver/
    ┌─────────────────────────────────────────────────────┐
    │                                                     │
    │  pool_manager          ccr_bridge                   │
    │  ┌──────────────┐      ┌──────────────────────────┐ │
    │  │ m2b-claude-code│     │ 生成 CCR config           │ │
    │  │ 容器池（1个）  │     │ Provider: yunwu M2.7     │ │
    │  │ uid=1100       │     │ Port: 3456 (容器内)       │ │
    │  │ 无 docker sock │     │ transformer: openai shim │ │
    │  └──────┬───────┘      └──────────────────────────┘ │
    │         │                                           │
    │  exec_runner                                        │
    │  ┌──────┴──────────────────────────────────────────┐│
    │  │ claude --print --permission-mode bypassPermissions││
    │  │ /home/agent/workspace/<run_id>/TASK.md           ││
    │  │                                                  ││
    │  │ budget_guard: 50k tokens, 900s 墙钟              ││
    │  │ watchdog thread: 每 15s 检查，超限 pkill claude  ││
    │  └──────────────────────┬───────────────────────────┘│
    │                         │ stream stdout               │
    │  report_extractor       ▼                            │
    │  ┌────────────────────────────────────────────────┐  │
    │  │ 1. 找 <<<HEYI_RUN_REPORT_JSON>>>...<<<END>>> 围栏│  │
    │  │ 2. 剥离 ```json 包装                           │  │
    │  │ 3. 若无围栏，救援：扫描最后一个 report 形 JSON │  │
    │  │ 4. jsonschema 校验 RunReport                   │  │
    │  └────────────────────────────────────────────────┘  │
    └─────────────────────────────────────────────────────┘
                         │
                         ▼
                 report.json + agent.log + state.json
```

**CCR（Claude Code Router）作用**

m2b-claude-code 容器内的 claude CLI 默认打向 `ANTHROPIC_BASE_URL=http://127.0.0.1:3456`（CCR 监听端口）。CCR 在容器内常驻，作为 Anthropic 协议 → OpenAI 协议的转换中间层：

```
claude CLI
(Anthropic SDK)
    │
    ▼
CCR :3456 (容器内)
  ├── transformer: openai（剥 cache_control / reasoning，把 content blocks 转 string）
  ├── transformer: maxtoken（cap 8192 tokens）
  └── transformer: strip-thinking（去掉 <think> 块）
    │
    ▼ HTTP /chat/completions
yunwu MiniMax-M2.7
(云端，OpenAI 兼容)
```

**watchdog 机制**

M2.7 在遭遇上游 429 风暴时，claude 的 stdout 可能长时间静默。为防止 run 永久挂死，`exec_runner` 启动一个守护线程，每 15 秒轮询 `budget_guard.check()`，超限时执行 `pkill -TERM -f 'claude --print'` 强制结束流，run 落地为 `EXCEEDED_WALL_CLOCK`。

### 沙箱安全（INV-S1 / INV-P*）

| 约束 | 机制 |
|---|---|
| skill agent 不能 clone 外部代码 | `detect_clone_attempt()` 扫描 agent.log，命中 `git clone / curl|bash` 则 outcome 强制 `skill_clone_attempt` |
| project agent 资源上限 | project repo 大小 ≤ 500MB（preflight 检查），磁盘写只在 workspace 子目录，clone 用 `--depth 1` |
| agent 与宿主隔离 | m2b-claude-code 容器 uid=1100，无 docker socket，无 root，workspace 目录 agent 专有 |
| token 预算 | `budget_guard`：50k output tokens + 900s 墙钟双重护栏；watchdog 线程确保静默超时也能终止 |
| 产物路径穿越防护 | `resolve_artifact()` 做 `relative_to(run_dir)` 验证，拒绝 `../` 跨目录访问 |

---

## heyi-eval 评测 Schema

heyi-eval-v10 负责对三类对象进行自动评测。数据**落盘在 heyi 文件系统**（不是 radar 的 DB），radar 通过 `eval/reader.py` 只读扫描并回流到 UI。

### 三条车道对比

| 维度 | model_lane | project_lane | skill_lane |
|---|---|---|---|
| 评测对象 | HuggingFace 模型权重 | GitHub 开源项目 | SKILL.md 规范 |
| 运行主体 | vLLM / transformers | m2b-claude-code agent | m2b-claude-code agent |
| LLM 调用 | 本机 GPU（eval vLLM） | 云端 yunwu M2.7 | 云端 yunwu M2.7 |
| run_id 格式 | `run-YYYYMMDD-<uuid>` | `proj-YYYYMMDD-<6hex>` | `skill-YYYYMMDD-<6hex>` |
| 落盘路径 | `$HEYI_EVAL_DATA/runs/` | `$HEYI_EVAL_DATA/project_lane/runs/` | `$HEYI_EVAL_DATA/skill_lane/runs/` |
| 索引 DB | `store/runs.sqlite` | `project_lane/runs.sqlite` | `skill_lane/runs.sqlite` |

---

### model_lane — 模型评测

**阶段流水线（11 阶段，顺序执行）**

```
DISCOVER → CURATE → METADATA → ENGINE_SELECT → STAGE_MODEL
         → DEPLOY → READY_WAIT → CAPABILITY → PERF_BENCH → SHOWCASE → CLEANUP
```

前 5 阶段（run-level）失败可从头重跑；后 6 阶段（stage-level）失败从 DEPLOY 续跑。

**`Run`（state_machine.py）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | str | UUID |
| `hf_id` | str | HuggingFace 模型 ID，如 `Qwen/Qwen3-235B-A22B` |
| `status` | RunStatus | `pending / in_progress / ok / failed / aborted` |
| `created_at` | float | Unix 时间戳 |
| `ended_at` | float | 结束时间戳 |
| `stages` | dict[str, StageInfo] | 每个阶段的状态（见下） |
| `failure_reason` | str | 最后一个失败阶段的错误信息 |

**`StageInfo`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | StageName | 阶段名（DISCOVER / CURATE / ... / CLEANUP） |
| `status` | StageStatus | `pending / in_progress / ok / failed / skipped` |
| `started_at` | float | 阶段开始时间戳 |
| `ended_at` | float | 阶段结束时间戳 |
| `duration_s` | float | 耗时秒数 |

**run 目录产物**（`$HEYI_EVAL_DATA/runs/<run_id>/`）

```
state.json          ← Run 序列化（上方字段）
_meta/
  curated.json      ← CURATE 阶段：结构化 README（summary / modalities / license / ...）
  metadata.json     ← METADATA 阶段：param_count / gpu_count / vram_gb
  engine_select.json ← ENGINE_SELECT：tp 数 / 是否 oversize
capability.json     ← CAPABILITY：13 类能力逐项分数（text/ASR/TTS/image/video/...）
perf_bench.json     ← PERF_BENCH：TTFT / TPS / VRAM 实测
showcase.json       ← SHOWCASE：cc-agent 对话示例 + 首印象评分
```

---

### project_lane — 项目评测

**`ProjectRun`（project_lane.py）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | str | `proj-YYYYMMDD-<6hex>` |
| `full_id` | str | GitHub owner/repo，如 `colbymchenry/codegraph` |
| `source_url` | str | `https://github.com/owner/repo` |
| `enqueued_at` | str | ISO8601 UTC |
| `candidate` | dict | `ProjectCandidate` 快照（含 `qag_score` / `stars_total` / `reason`） |
| `status` | ProjectStatus | 生命周期状态（见下） |
| `started_at` | str | agent 开始时间 |
| `ended_at` | str | 结束时间 |
| `failure_reason_zh` | str | 中文失败原因（展示给用户） |
| `preflight_json` | str | 产物文件名（`preflight.json`） |
| `agent_log` | str | 产物文件名（`agent.log`） |
| `report_json` | str | 产物文件名（`report.json`） |
| `judge_json` | str | 产物文件名（`judge.json`，预留） |
| `summary_outcome` | str | 摘要结论（`pass / partial / fail / timeout / ...`） |
| `summary_deploys` | bool | agent 是否成功部署/运行 |
| `summary_quickstart` | bool | 快速入门是否通过 |

**`ProjectStatus` 枚举**

| 值 | 含义 |
|---|---|
| `pending` | 等待执行 |
| `preflight` | 正在 preflight（调 GitHub API 检查仓库） |
| `agent_run` | agent 正在实测 |
| `done` | 已完成（terminal） |
| `preflight_error` | GitHub API 调用失败（可重试） |
| `not_found` | 仓库不存在或私有（terminal） |
| `oversize` | 仓库体积超过 500MB（terminal） |
| `no_readme` | 无 README（terminal） |
| `needs_gpu` | 需要 GPU 但不在 project 范围（terminal） |
| `timeout` | agent 超过 900s 墙钟（terminal） |
| `budget_exceeded` | agent 超过 token 预算（terminal） |
| `sandbox_dead` | 容器崩溃（terminal） |
| `report_parse_error` | agent 报告解析失败（terminal） |

**SQLite 索引表**（`project_lane/runs.sqlite`）

| 列 | 说明 |
|---|---|
| `run_id` TEXT PK | 主键 |
| `full_id` TEXT | 仓库 ID（加速按 full_id 查询） |
| `status` TEXT | 当前状态 |
| `enqueued_at` TEXT | 入队时间（排序用） |
| `ended_at` TEXT | 结束时间 |
| `summary_outcome` TEXT | 摘要结论 |
| `state_path` TEXT | state.json 绝对路径 |

**run 目录产物**（`project_lane/runs/proj-YYYYMMDD-xxx/`）

```
state.json          ← ProjectRun 序列化
preflight.json      ← GitHub API 仓库元数据（stars/size/topics/has_readme/...）
agent.log           ← agent 完整 stdout
report.json         ← RunReport（见下方通用报告结构）
bad_report.txt      ← 解析失败时的原始 stdout（调试用）
```

---

### skill_lane — Skill 评测

**`SkillRun`（skill_lane.py）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | str | `skill-YYYYMMDD-<6hex>` |
| `full_id` | str | Skill 命名 ID，如 `claude-user/mermaid` |
| `skill_path` | str | SKILL.md 的绝对文件路径 |
| `enqueued_at` | str | ISO8601 UTC |
| `candidate` | dict | `SkillCandidate` 快照（含 `name` / `source_root` / `version`） |
| `status` | SkillStatus | 生命周期状态 |
| `started_at` | str | agent 开始时间 |
| `ended_at` | str | 结束时间 |
| `failure_reason_zh` | str | 中文失败原因 |
| `agent_log` | str | 产物文件名 |
| `report_json` | str | 产物文件名 |
| `bad_report_txt` | str | 产物文件名（解析失败时留存） |
| `summary_outcome` | str | 摘要结论 |
| `summary_demos` | int | agent 演练的 demo 场景数量 |

**`SkillStatus` 枚举**（与 ProjectStatus 基本对称，少 oversize / no_readme / needs_gpu / preflight_error，多 `skill_clone_attempt`）

**SQLite 索引表**（`skill_lane/runs.sqlite`）

| 列 | 说明 |
|---|---|
| `run_id` TEXT PK | 主键 |
| `full_id` TEXT | Skill 命名 ID |
| `status` TEXT | 当前状态 |
| `enqueued_at` TEXT | 入队时间 |
| `ended_at` TEXT | 结束时间 |
| `summary_outcome` TEXT | 摘要结论 |
| `state_path` TEXT | state.json 绝对路径 |

**run 目录产物**（`skill_lane/runs/skill-YYYYMMDD-xxx/`）

```
state.json          ← SkillRun 序列化
agent.log           ← agent 完整 stdout
report.json         ← RunReport（见下方通用报告结构）
bad_report.txt      ← 解析失败时的原始 stdout
```

---

### 通用 Agent 报告结构（RunReport）

project_lane 和 skill_lane 的 agent 最终必须输出一段符合 `REPORT_JSON_SCHEMA` 的 JSON，落盘为 `report.json`。

**`RunReport`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | `"1.0"` | 固定 |
| `lane` | `"project"` \| `"skill"` | 所在车道 |
| `target_id` | str | `full_id`（owner/repo 或 skill 命名） |
| `outcome` | Outcome | 顶层结论（见下方枚举） |
| `steps` | list[Step] | 执行步骤列表 |
| `verdict` | Verdict | 结构化裁决 |
| `self_assessment_zh` | str | Agent 中文自评（≤1024 字） |
| `follow_ups` | list[str] | 改进建议（可选） |

**`Outcome` 枚举**

| 值 | 来源 | 含义 |
|---|---|---|
| `pass` | agent 自报 | 核心功能验证通过 |
| `partial` | agent 自报 | 部分通过（有 blockers 但主流程可跑） |
| `fail` | agent 自报 | 明确失败 |
| `report_parse_error` | 系统判定 | agent 未输出合规报告 |
| `timeout` | 系统判定 | 超过 900s 墙钟 |
| `budget_exceeded` | 系统判定 | 超过 token 预算 |
| `sandbox_dead` | 系统判定 | 容器在运行中崩溃 |
| `oversize` | 系统判定 | preflight 拒绝（仓库 >500MB） |
| `no_readme` | 系统判定 | preflight 拒绝（无 README） |
| `needs_gpu` | 系统判定 | preflight 拒绝（需 GPU，project 范围不提供） |
| `judge_unavailable` | 系统判定 | yunwu 429 风暴耗尽重试预算 |
| `skill_clone_attempt` | 系统判定 | SKILL.md 尝试 git clone（INV-S1 违规） |

**`Step`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 步骤名，如 `clone / install / smoke / demo_1` |
| `status` | StepStatus | `ok / partial / fail / skip` |
| `duration_s` | float | 耗时秒数（可选，缺省 0.0） |
| `note` | str | 简短说明 |
| `stdout_tail` | str | 步骤 stdout 尾部（≤2KB） |
| `artifacts` | list[str] | 产物相对路径列表 |

**`Verdict`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `deploys` | bool | 是否成功部署/启动 |
| `quickstart_works` | bool | 快速入门路径是否通过 |
| `core_features_demonstrated` | list[str] | 已验证的核心能力列表（PASS 要求 ≥1 条） |
| `blockers` | list[str] | 阻塞项（未解决的问题） |

**完整 `report.json` 示例**

```json
{
  "schema_version": "1.0",
  "lane": "project",
  "target_id": "colbymchenry/codegraph",
  "outcome": "pass",
  "steps": [
    {"name": "clone",   "status": "ok",      "duration_s": 4.2,  "note": "git clone --depth 1 ok"},
    {"name": "install", "status": "ok",      "duration_s": 31.5, "note": "npm install ok"},
    {"name": "smoke",   "status": "partial", "duration_s": 8.1,  "note": "CLI help ok, index demo skipped (Node 22.5+ required)"}
  ],
  "verdict": {
    "deploys": true,
    "quickstart_works": true,
    "core_features_demonstrated": ["cli_help", "search_nodes"],
    "blockers": ["index 初始化需要 Node.js 22.5+，当前 22.2"]
  },
  "self_assessment_zh": "项目 CLI 工具链完整，代码结构清晰，核心 API 设计合理；环境限制导致索引初始化 demo 无法演练，整体评为 partial。",
  "follow_ups": ["在 Node.js 22.5+ 环境中重新评测", "评估 MCP server 功能"]
}
```

---

## 核心功能详解

### 1. 数据发现（`sources/`）

**GitHub**
- 接口：GitHub REST Search API（非 Trending 页面爬虫）
- 关键词：`llm agent mcp openai claude gemini rag embedding` 等 AI 相关词组
- 增量：`SourceRun` 游标记录上次成功日期，`created:>{since_date}` 过滤
- 频率：默认每 6 小时（`GITHUB_CRAWL_INTERVAL=6h`）
- 认证：`GITHUB_TOKEN`（无 token 匿名 60 req/h）

**Reddit**
- 接口：Reddit JSON API（支持 OAuth，匿名常见 403）
- Subreddit：`LocalLLaMA / MachineLearning / ChatGPT / ClaudeAI / SideProject / ...` 13 个
- 策略：每个 subreddit 的 hot + new 各 25 条
- 频率：默认每 1 小时

**去重**：`url_hash`（SHA256）唯一约束，跨 run 不入库重复条目。

---

### 2. LLM 打分（`analyzer/scorer.py`）

每 30 分钟从未评分条目中取批量，调用 LLM 做 QAG 评分。

**四维度（QAG）**

| 维度 | 权重 | 含义 |
|---|---|---|
| pain（痛点强度） | 35% | 用户痛点有多强烈 |
| market（市场规模） | 30% | 潜在市场有多大 |
| feasibility（技术可行性） | 20% | 现有技术栈实现难度 |
| velocity（增速信号） | 15% | Stars 增长速度、社区热度 |

**综合分** = pain×0.35 + market×0.30 + feasibility×0.20 + velocity×0.15

**12 领域分类**：coding / infra / browser / rag / chatbot / ai4science / personal / finance / social / creative / multimodal / hardware

**Thinking 模型适配**：MiniMax-M2.7 会在 `<think>…</think>` 中输出推理链，scorer 用正则剥离后再提取 JSON；`max_tokens=4096` 保证推理空间充足。

**LLM Provider 切换**（`LLM_PROFILE` env）：

| Profile | 端点 | 模型 |
|---|---|---|
| `yunwu`（默认） | `https://yunwu.ai/v1` | `MiniMax-M2.7` |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.1` |
| `heyi` | `http://heyi.local:8000/v1` | 本地 GPU（可配） |
| `ollama` | `http://localhost:11434/v1` | 任意本地模型 |

---

### 3. 报告生成（`outputs/`）

每日 06:00（cron 可配）生成两份静态 HTML 报告，存入 `outputs/` 目录，FastAPI mount 后直接访问。

| 报告 | 内容 |
|---|---|
| `projects_latest.html` | 按 12 领域分类的 AI 项目图谱，含 stars / QAG 分 / 关键词 |
| `communities_latest.html` + `.json` | GitHub + Reddit 跨平台 AI 社群资源地图 |

---

### 4. 与 heyi-eval 的闭环集成

这是 radar 与 heyi-eval-v10 合并形成的核心环路：

```
radar 发现并打分
    │  GET /api/items?min_score=0.6
    ▼
heyi-eval discover/radar_local_ingest.py
    │  ingest → ProjectCandidate（含 qag_score）
    ▼
heyi-eval project_lane（m2b-claude-code + yunwu M2.7）
    │  agent 实测：deploy + smoke + verdict
    ▼
lane runs 落盘 HEYI_EVAL_DATA/
    │  radar/eval/reader.py 只读扫描
    ▼
GET /api/eval/results → 实测结果页（React EvalResults）
```

**接口**

| 路由 | 说明 |
|---|---|
| `GET /api/items` | 已打分热点，支持 `source/domain/min_score/scored_only/limit` 过滤，按综合分降序 |
| `GET /api/eval/results` | heyi-eval project/skill/model lane 结果，支持 `lane/outcome` 过滤，按入队时间倒序 |
| `GET /api/eval/results/{run_id}` | 单次评测详情：自评 + 步骤 + 阻塞 + agent 日志尾 |
| `GET /api/eval/artifact/{lane}/{run_id}/{path}` | 评测产物（图片/音频/视频）预览，含路径穿越防护 |

---

### 5. 监控与告警（`runtime/watcher.py`）

每 5 分钟巡检，命中信号后写入 `incidents` 表，并推送 macOS 桌面通知。

12 类信号包括：数据停滞（2h 无新 item）、GitHub / Reddit Token 过期预警、磁盘不足、LLM 不可达、报告渲染失败等。

---

## API 路由总览

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/health` | GET | 健康检查（版本 / DB / LLM profile）|
| `/api/system/health` | GET | 同上（完整版）|
| `/api/sources` | GET | 各源条目数 + 最近抓取状态 |
| `/api/sources/{source}/crawl` | POST | 手动触发抓取 |
| `/api/items` | GET | 已打分热点列表 ★ |
| `/api/eval/results` | GET | heyi-eval 实测结果列表 ★ |
| `/api/eval/results/{run_id}` | GET | 评测详情 ★ |
| `/api/eval/artifact/{lane}/{run_id}/{path}` | GET | 媒体产物预览 ★ |
| `/api/reports` | GET | 报告列表 |
| `/api/reports/latest/{template}` | GET | 最新报告元数据 |
| `/api/reports/{id}/file` | GET | 下载 HTML 报告 |
| `/api/incidents` | GET | 告警列表 |
| `/api/incidents/{id}/dismiss` | POST | 忽略告警 |
| `/api/tokens/status` | GET | 凭证配置状态 |
| `/api/tokens/github/save` | POST | 保存 GitHub Token |
| `/api/tokens/reddit/save` | POST | 保存 Reddit OAuth 凭证 |
| `/api/settings/overview` | GET | 运行时配置概览 |
| `/api/settings/llm` | POST | 热更新 LLM Provider |
| `/api/settings/report/trigger/{template}` | POST | 立即渲染报告 |

> ★ = radar×heyi-eval 合并新增接口

---

## 前端设计

**技术栈**：React 19 + TypeScript + Vite 8 + Ant Design 6 + TanStack Query + Zustand + React Router 7

**主题**：深色（GitHub 风格，`#0d1117` 背景 + `#58a6ff` 主色）

**7 个页面**

| 路由 | 页面 | 核心内容 |
|---|---|---|
| `/` | 仪表盘 | 系统健康 / 数据源摘要 / 最新告警 |
| `/eval` ★ | 实测结果 | heyi-eval 评测结果表格 + 详情抽屉 |
| `/reports/projects` | AI 项目报告 | iframe 嵌入日报 HTML |
| `/reports/communities` | 社群地图 | iframe 嵌入社群报告 HTML |
| `/sources` | 数据源 | 抓取状态 + 手动触发 |
| `/tokens` | 凭证管理 | GitHub Token + Reddit OAuth 配置 |
| `/settings` | 系统设置 | LLM Provider / 抓取频率 / 报告计划 |
| `/incidents` | 告警中心 | 告警列表 + 忽略操作 |

**EvalResults 页设计要点**（`pages/EvalResults.tsx`）
- 可筛选：车道（project / skill / model）× 结论（pass / partial / fail）
- 可排序：QAG 热度分、demos 数、完成时间
- 结论徽章：`通过/部分通过/失败/超时/报告解析失败/超规格` 等语义标色
- 行点击→详情抽屉：agent 自评中文 + 已验证能力 tags + 阻塞项 + 步骤状态 + 媒体产物预览（图片/音频/视频内嵌）+ agent.log 尾
- 顶部汇总：通过数 / 部分数 / 失败数 实时统计

---

## 调度与持续运行

### radar 内置调度（APScheduler，随 serve 启动）

| 任务 | 默认频率 | 环境变量 |
|---|---|---|
| GitHub 爬取 | 每 6h | `GITHUB_CRAWL_INTERVAL` |
| Reddit 爬取 | 每 1h | `REDDIT_CRAWL_INTERVAL` |
| LLM 自动打分 | 每 30min，每批 ≤50 | — |
| projects 报告渲染 | `0 6 * * *` | `REPORT_PROJECTS_CRON` |
| communities 报告渲染 | `0 6 * * *` | `REPORT_COMMUNITIES_CRON` |
| 系统监控巡检 | 每 5min | — |

### heyi 侧 systemd timer（驱动闭环评测）

| Unit | 频率 | 职责 |
|---|---|---|
| `heyi-eval-radar-local.timer` | 每日 | 从 `/api/items` 拉热点 → 项目队列 |
| `heyi-eval-project-loop.timer` | 每 30min | 评测 ≤5 个项目 run |
| `heyi-eval-skill-loop.timer` | 每 30min | 评测 ≤5 个 skill run |

---

## 部署

### 快速启动（本机）

```bash
git clone https://github.com/yoligehude14753/radar.git
cd radar && python3.11 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env   # 填 YUNWU_API_KEY + HEYI_EVAL_DATA
.venv/bin/radar init
.venv/bin/radar serve  # http://localhost:7090
```

### 生产（heyi + yoliyoli.uk）

```bash
# radar systemd 服务（:7090 内网）
sudo cp deploy/systemd/radar.service /etc/systemd/system/
sudo systemctl enable --now radar

# Cloudflare Tunnel → yoliyoli.uk
# 1. cloudflared tunnel create radar
# 2. 在 Cloudflare DNS 加 CNAME radar.yoliyoli.uk → <tunnel_id>.cfargotunnel.com
# 3. ~/.cloudflared/config.yml 加 ingress（见 deploy/cloudflared/config.yml.example）
# 4. systemctl --user restart cloudflared-echo
```

完整流程见 [`deploy/DEPLOY.md`](deploy/DEPLOY.md)。

---

## 关键设计决策

**1. 不爬 GitHub Trending 页面**
GitHub Trending 是 HTML 页面，结构频繁变化。radar 用 Search API + 关键词分批，结果更稳定、可控过滤、支持增量游标。

**2. heyi-eval 与 radar 不共享 Python 代码**
`eval/reader.py` 只扫描 heyi-eval 的落盘 JSON（`state.json / report.json / agent.log`），不 import heyi-eval 的 Python 包。两项目解耦，单独升级不互相破坏。

**3. thinking 模型的 JSON 提取**
yunwu MiniMax-M2.7 默认开 thinking，响应先输出 `<think>…</think>` 推理链。scorer 用 `re.sub` 剥离后再找 `{…}`，`max_tokens=4096` 给推理足够空间（原来 300 tokens 全花在思考上，JSON 根本没机会出现）。

**4. SQLite 作为默认 DB**
单机部署用 SQLite（`sqlite+aiosqlite`），零外部服务依赖；生产可无缝切 PostgreSQL，只需改 `DATABASE_URL`。

**5. LLM Provider 完全可插拔**
`LLMProfile` enum + `llm_*` 属性一键切换；scorer 用标准 `AsyncOpenAI(api_key=…, base_url=…)` 客户端，OpenAI 兼容层通杀四种 provider，无需改代码。

---

## 资源控制

- radar 本体：`MemoryMax=2G`（systemd）
- LLM 调用：云端，不占本地 GPU / 显存
- DB 存储：SQLite 文件增长线性；`RAW_BLOB_RETENTION_DAYS=30` 定期清理原始 payload
- heyi-eval cache：`HEYI_EVAL_CACHE_QUOTA_GB=100`（LRU 逐出，model_lane 模型权重）

---

## 测试覆盖

| 测试文件 | 覆盖内容 |
|---|---|
| `test_items_api.py` | `/api/items` 空库 / 排序 / 过滤 / 未评分 |
| `test_eval_api.py` | `/api/eval/results` 列表 / 过滤 / 详情 / 媒体预览 / 路径穿越防护 |
| `test_scoring_pipeline.py` | QAG 评分端到端（mock LLM）|
| `test_full_pipeline.py` | 全链路 E2E（爬取→存储→打分→报告）|
| `test_github_pipeline.py` | GitHub 爬取增量游标 / 去重 |
| 其余 e2e | 监控巡检 / 报告模板 / 调度器 / 用户流程 |

共 **60 个测试**，均使用 SQLite in-memory，CI 零外部依赖。
