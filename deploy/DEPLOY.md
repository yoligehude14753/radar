# 部署 radar 到 yoliyoli.uk

radar 作为统一主站：左侧导航有「实测结果」页，聚合 heyi-eval 对热点项目/Skill 的自动评测。
公网通过 Cloudflare Tunnel 暴露，无需公网 IP / 端口转发。

```
公网用户 ──▶ yoliyoli.uk (Cloudflare 边缘, 自动 TLS)
                 │  Cloudflare Tunnel（cloudflared 主动外连）
                 ▼
        heyi 机器 127.0.0.1:7090  ──▶ radar (FastAPI)
                 │ 同机只读                 │ HTTP /api/items
                 ▼                          ▼
   /home/ai/heyi-eval-data/*_lane/runs   heyi-eval（评测引擎）
```

## 1. 准备机器（heyi）

```bash
# 代码
cd /home/ai && git clone https://github.com/yoligehude14753/radar.git
cd radar && python3.11 -m venv .venv && .venv/bin/pip install -e .
# 前端构建产物（FastAPI 托管 web/dist）
cd web && npm ci && npm run build && cd ..

# 环境变量（填 ZHIPU_API_KEY、DATABASE_URL 等）
sudo install -D -m 600 deploy/env.example /etc/radar/env
sudo nano /etc/radar/env

# 初始化数据库
set -a; source /etc/radar/env; set +a
.venv/bin/radar init
```

## 2. 起 radar 服务（systemd）

```bash
sudo cp deploy/systemd/radar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radar
curl -s http://127.0.0.1:7090/api/health   # {"status":"ok",...}
```

## 3. Cloudflare Tunnel → yoliyoli.uk

前置：yoliyoli.uk 的 DNS 必须托管在 Cloudflare（NS 指向 Cloudflare）。

```bash
# 安装 cloudflared（Debian/Ubuntu 官方包）
# 见 https://pkg.cloudflare.com/ ；然后：
cloudflared tunnel login                      # 浏览器授权，选 yoliyoli.uk 域
cloudflared tunnel create radar               # 记下 <TUNNEL_ID> 与凭证 json
cloudflared tunnel route dns radar yoliyoli.uk
cloudflared tunnel route dns radar www.yoliyoli.uk

# 配置
sudo mkdir -p /etc/cloudflared
sudo cp deploy/cloudflared/config.yml.example /etc/cloudflared/config.yml
sudo sed -i "s/<TUNNEL_ID>/<你的TUNNEL_ID>/g" /etc/cloudflared/config.yml
sudo cp ~/.cloudflared/<TUNNEL_ID>.json /etc/cloudflared/

# 起隧道
sudo cp deploy/systemd/cloudflared.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared
```

访问 https://yoliyoli.uk 即可看到 radar 主站 + 实测结果页。

## 4. 鉴权（保护写/触发接口）

只读页面对公网开放即可；但写/触发类接口（手动抓取、改设置、Token 管理）
不应裸奔。推荐用 **Cloudflare Access**（零代码、单点登录）：

- Cloudflare Zero Trust ▸ Access ▸ Applications，为 `yoliyoli.uk` 下的
  写路径建 Self-hosted 应用并加策略（仅允许你的邮箱/IdP）：
  - `yoliyoli.uk/api/sources/*/crawl`
  - `yoliyoli.uk/api/settings/*`
  - `yoliyoli.uk/api/tokens/*`
- 这样匿名访客能看页面/结果，但触发抓取、改配置需登录。

（应用层 token 鉴权是可选替代方案，但会改动现有前端调用，默认不启用。）

## 5. 持续运行 + 资源控制

- radar 自带 APScheduler：起服务即按计划抓取 GitHub/Reddit → LLM 打分 → 生成报告。
- 存储：`RAW_BLOB_RETENTION_DAYS=30` 周期清理原始 payload；DB 用 PostgreSQL 时注意磁盘。
- heyi-eval 侧的调度（radar-local 拉热点 + project/skill 评测循环）见
  `heyi-eval-v10/deploy/systemd/heyi-eval-{radar-local,project-loop,skill-loop}.{service,timer}`。
