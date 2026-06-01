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

### 核心表（SQLAlchemy，PostgreSQL / SQLite 双支持）

| 表 | 职责 |
|---|---|
| `items` | 统一内容条目（GitHub repo / Reddit post），跨源归一 |
| `scores` | QAG 评分记录（支持多版本历史） |
| `tags` | 命名空间标签：`domain=coding`、`domain=infra` 等 |
| `source_runs` | 每次抓取的元数据与游标（增量控制） |
| `raw_blobs` | 原始 API payload 全量留档（供重跑） |
| `reports` | 已生成报告的元数据与文件路径 |
| `incidents` | 告警事件（信号类型 / 严重级 / 处置状态） |

### `Item` 关键字段

```python
source: str           # "github" | "reddit"
external_id: str      # GitHub: "owner/repo", Reddit: post_id
url: str
title: str
content: str          # repo description / post body（截断到 1000 字）
platform_data: JSON   # GitHub: stars/forks/topics/... Reddit: ups/subreddit/...
fetched_at: datetime
```

### `Score` 关键字段

```python
evaluator: str        # "qag" | "domain_classifier"
score: float          # 综合分 0-1（pain×0.35 + market×0.30 + feasibility×0.20 + velocity×0.15）
dimensions: JSON      # {"pain": 0.9, "market": 0.8, "feasibility": 0.7, "velocity": 0.85, "reason": "..."}
llm_profile: str      # 打分时用的 LLM（"yunwu" / "zhipu" / "ollama"）
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
