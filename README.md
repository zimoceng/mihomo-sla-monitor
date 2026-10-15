# Mihomo SLA Monitor

面向自用节点的可用性、延迟、故障事件与监控覆盖率控制台。

前端采用 Vue 3 + Vite，后端采用 FastAPI + SQLite。独立 Mihomo 监控实例负责逐节点探测；现有主代理负责订阅下载和可选 Telegram 通知。管理界面默认仅通过本机或 SSH 隧道访问。

## 源码与安装

完整源码直接放在本仓库的 `main` 分支：

- [backend/](backend/)：FastAPI 后端、SQLite 采集与 Telegram 告警进程。
- [frontend/](frontend/)：Vue 3 页面和 Vite 构建配置。
- [deploy/](deploy/)：systemd 与 Nginx 部署模板。

**第一次安装请从 [Ubuntu 24.04 完整部署说明](docs/DEPLOYMENT.md) 第 1 步开始。** 文档依次介绍下载源码、安装依赖、配置代理、启动后端、构建前端和通过 SSH 隧道访问。需要自备 Ubuntu 服务器、Mihomo 内核和自己的节点/订阅；Telegram 告警为可选功能。

只想下载源码或二次开发，可以在电脑或服务器终端执行：

```bash
git clone https://github.com/zimoceng/mihomo-sla-monitor.git
cd mihomo-sla-monitor
```

也可以在仓库页面点击 **Code → Download ZIP** 获取源码。后续开发命令在项目根目录执行；作为服务器长期运行时，请使用部署说明中的 `/opt/mihomo-sla` 路径和服务配置。

## 功能

- 通过后端导入 HTTPS Mihomo YAML 订阅，原子保存节点并刷新 Provider。
- 自动采集探测成功率、平均延迟及 P50/P95/P99，按探测目标区分统计。
- 连续 3 次失败确认故障，连续 2 次成功确认恢复；监控间断记为未知。
- 展示监控覆盖率、已观测时间可用性及未知时间。
- 网页调整探测目标、间隔和超时；下一轮生效。
- 独立 Telegram 告警进程：首次建立历史基线，发送失败重试，成功后去重。

采样成功率和已观测时间可用性均不等于合同 SLA，监控缺口不能当成正常或故障。

## 架构

```text
浏览器 --SSH 隧道--> Nginx 127.0.0.1:8080
                         |-- 前端静态文件
                         '-- /api --> FastAPI 127.0.0.1:8000
                                        |-- SQLite
                                        |-- 监控 Mihomo 127.0.0.1:19091
                                        '-- 主代理 127.0.0.1:7890 --> 订阅源

Telegram worker --只读查询故障--> SQLite
                --经主代理发送--> Telegram
```

## 部署

详细步骤见 [Ubuntu 部署说明](docs/DEPLOYMENT.md)。

环境：Ubuntu 24.04、Python 3.12、兼容当前 Mihomo Provider API 的独立内核，以及 Node.js 22.12+（测试使用 Node 24）。Vite 的运行版本要求见[官方文档](https://vite.dev/guide/)。

本仓库不附带 Mihomo 内核、真实节点或可用订阅。请从 [Mihomo 官方发行页](https://github.com/MetaCubeX/mihomo/releases)单独安装并记录实际版本；按部署说明执行配置检查。示例 DIRECT 节点用于启动和配置校验，采集器会跳过它。

已有生产实例请先在新环境验证模板，不要直接覆盖当前配置。

## 本地开发（Linux）

先按上面的克隆命令取得源码，并进入项目根目录。以下三个服务分别在独立终端启动；每个终端都先进入同一个项目根目录。

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
cp .env.example .env
cp monitor/config.example.yaml monitor/config.yaml
cp monitor/nodes.example.yaml monitor/nodes.yaml
# 终端 1：需要已安装 Mihomo
mihomo -d "$PWD/monitor"
# 终端 2：在项目根目录加载本地环境，再启动后端
set -a; . ./.env; set +a
(cd backend && .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log)
# 终端 3
cd frontend
npm ci
npm run dev
```

Python 不会自动读取 `.env`。默认订阅下载代理是 `127.0.0.1:7890`；需要直连时将 `SLA_DOWNLOAD_PROXY` 设为空。主代理配置和凭据由使用者自行提供。

## 项目结构

| 目录 | 内容 |
| --- | --- |
| backend/ | 采集、分析、事件、覆盖率、设置及 Telegram 进程 |
| frontend/ | 控制台源码和前端依赖锁定文件 |
| monitor/ | 独立监控实例示例 |
| main/ | 可选主代理示例，供全新环境使用 |
| deploy/ | systemd、Nginx 和 Telegram 环境变量示例 |
| docs/ | 部署、安全发布和第三方说明 |
| tests/ | 使用临时数据和模拟请求的基础检查 |

源码保留原有 Day 1–Day 3.2 模块命名，便于对应已有实现。

## 检查

```bash
python -m compileall -q backend tests tools
python -m unittest discover -s tests -v
python tools/check_public_tree.py
cd frontend && npm ci && npm run build
```

测试不使用真实订阅、节点、生产数据库或 Telegram Token，也不发送告警。GitHub Actions 提供相同的基础检查；远端运行结果应在首次发布后确认。

## 安全与许可证

此版本没有内置登录鉴权，只适合可信管理员使用。保持管理端口绑定环回地址；通过隧道访问。详见 [SECURITY.md](SECURITY.md)。

原创项目代码按 [MIT](LICENSE) 发布。独立安装的 Mihomo 及其他依赖保留各自许可证；详见[第三方说明](docs/THIRD_PARTY.md)。
