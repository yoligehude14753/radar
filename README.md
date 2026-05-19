# 🛰️ Radar — AI 需求趋势跟踪平台

Radar 是一个持续运行的 AI 需求抓取、趋势分析与可视化平台，自动从 GitHub 和 Reddit 采集 AI 相关项目与讨论，通过 LLM 评分和领域分类，生成可视化 HTML 报告，并提供 Web 监控仪表盘。

## 功能特性

- **持续抓取**：每 6 小时自动抓取 GitHub Trending + AI 关键词仓库、Reddit AI 子版块
- **LLM 智能评分**：QAG 四维度（痛点/市场/可行性/速度）打分，支持 Heyi GPU / 云雾 / Ollama
- **自动报告**：每天生成两份 HTML 报告：AI 项目分类图谱 + 社群资源地图
- **主动监控**：12 类告警信号（数据停滞、Token 过期、磁盘不足、LLM 不可达等），macOS 桌面通知 + Web 告警中心
- **Web 仪表盘**：React + Ant Design 暗色风格，覆盖仪表盘、报告、数据源、Token 管理、告警中心
- **macOS 自启动**：launchd plist 支持开机自启、崩溃重启、进程守护

## 快速上手

### 1. 安装依赖

```bash
git clone https://github.com/yourusername/radar.git
cd radar
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入以下必要配置：
# - GITHUB_TOKEN（GitHub Personal Access Token，强烈推荐）
# - LLM_PROFILE=yunwu（或 heyi / ollama）
# - 对应 LLM 的 API Key 和 Base URL
```

### 3. 初始化数据库

```bash
radar init
```

### 4. 启动服务

```bash
radar serve
# 访问 http://localhost:8000 查看 Web 仪表盘
```

### 5. 立即开始抓取

```bash
radar crawl github
radar crawl reddit
```

## 配置选项

### LLM Profile

| Profile | 描述 | 配置项 |
|---------|------|--------|
| `yunwu` | 云雾 OpenAI 兼容代理 | `YUNWU_API_KEY`, `YUNWU_BASE_URL` |
| `heyi` | 褐蚁本地 GPU (RTX 5090) | `HEYI_API_KEY`, `HEYI_BASE_URL` |
| `ollama` | 本地 Ollama | `OLLAMA_BASE_URL` (默认 localhost:11434) |
| `openai` | OpenAI 官方 | `OPENAI_API_KEY` |

### 数据库

- **PostgreSQL**（推荐）：设置 `DATABASE_URL=postgresql+asyncpg://...`
- **SQLite**（纯本地）：设置 `DATABASE_URL=sqlite+aiosqlite:///./radar.db`

## CLI 命令

```bash
radar serve          # 启动 Web 服务（含调度器）
radar init           # 初始化数据库
radar status         # 查看系统状态
radar crawl github   # 立即抓取 GitHub
radar crawl reddit   # 立即抓取 Reddit
radar score          # 手动触发 LLM 评分
radar incidents      # 查看告警列表
radar reports        # 查看报告列表
radar token github   # 配置 GitHub Token 向导
radar token reddit   # 配置 Reddit OAuth 向导
```

## macOS 自启动

```bash
pip install -e .
bash scripts/install-launchd.sh
# 卸载：bash scripts/uninstall-launchd.sh
```

## 输出报告

报告生成后存储于 `outputs/` 目录，并可通过 Web 仪表盘直接查看：

- `projects_YYYY-MM-DD.html` — AI 项目领域分类图谱（12 个领域）
- `communities_YYYY-MM-DD.html` — GitHub + Reddit 社群资源地图

## 项目结构

```
radar/
├── src/radar/
│   ├── sources/         # 数据源（GitHub / Reddit）
│   ├── analyzer/        # LLM 评分 + 领域分类
│   ├── outputs/         # HTML 报告渲染
│   ├── runtime/         # 调度器 + 监控引擎 + 修复动作
│   ├── auth/            # Token 向导 + 凭证管理
│   ├── storage/         # DB 模型 + 会话管理
│   ├── web/             # FastAPI 路由
│   ├── cli.py           # Typer CLI
│   ├── app.py           # FastAPI 应用
│   └── config.py        # 配置中心
├── web/                 # React 前端（Vite + Ant Design）
├── tests/e2e/           # 端到端测试（50 个用例）
├── scripts/             # launchd 安装脚本
├── launchd/             # macOS plist 模板
└── .env.example         # 环境变量模板
```

## 开发与测试

```bash
# 运行全部端到端测试
python -m pytest tests/e2e/ -v

# 运行特定模块测试
python -m pytest tests/e2e/test_github_pipeline.py -v
```

## 扩展接口

系统预留了以下扩展点：

- `radar/src/radar/outputs/` — 新增自定义 HTML 模板（类比 `projects.py` / `communities.py`）
- `radar/src/radar/sources/` — 新增数据源（参考 GitHub / Reddit 适配器模式）
- `radar/src/radar/runtime/actions.py` — 注册新的一键修复动作
- `radar/src/radar/runtime/watcher.py` — 添加新的监控信号

## 敏感信息管理

- `.env` 文件已在 `.gitignore` 中排除
- `outputs/`, `data/credentials/`, `data/cookies/` 均不提交
- 所有 API Key / Token 仅存在本地 `.env` 文件

## License

MIT
