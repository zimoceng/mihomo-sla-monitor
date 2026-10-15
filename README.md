# Mihomo SLA Monitor

一个自用的 Mihomo 节点监控面板。

定时检查订阅里的节点，把成功率、延迟和故障记录保存在 SQLite 中。网页上可以看历史趋势、对比节点，也可以把故障和恢复通知发到 Telegram。

## 功能

- 导入 HTTPS Mihomo YAML 订阅，更新监控节点。
- 查看成功率、平均延迟和 P50 / P95 / P99，最多同时对比 3 个节点。
- 连续失败 3 次记为故障，连续成功 2 次记为恢复。
- 查看监控覆盖率，区分正常、故障和没有足够数据的时段。
- 在网页修改探测地址、间隔和超时，下一轮生效。
- 通过 Telegram 接收新故障和恢复通知。

这里的可用率来自定时探测，不是合同 SLA。采集器停机或数据缺失时，状态记为未知。

## 安装

服务部署在 Ubuntu 24.04 上，需要 Python 3.12、Node.js 22.12+ 和 Mihomo。具体步骤见 [安装文档](docs/DEPLOYMENT.md)。

仓库里有后端、前端和部署配置。下载源码：

```bash
git clone https://github.com/zimoceng/mihomo-sla-monitor.git
cd mihomo-sla-monitor
```

也可以用仓库页面的 **Code → Download ZIP** 下载。安装文档中的服务目录是 `/opt/mihomo-sla`，按文档部署时使用那个路径。

节点和订阅需要自己填写。示例中的 DIRECT 节点只用于检查配置，采集器会跳过它。Telegram 告警按需开启。

面板没有登录功能，默认只监听本机地址，通过 SSH 隧道访问。相关限制见 [安全说明](SECURITY.md)。

## 运行方式

项目使用两个 Mihomo 实例：

| 服务 | 默认地址 | 用途 |
| --- | --- | --- |
| 主代理 | 127.0.0.1:7890 | 下载订阅、发送 Telegram 消息 |
| 监控实例 | 127.0.0.1:19091 | 逐个节点发起探测 |
| FastAPI | 127.0.0.1:8000 | 采集、查询和设置 |
| Nginx | 127.0.0.1:8080 | 提供网页并转发 API 请求 |

主代理已有的话可以直接复用。监控实例单独运行，不开启 TUN。后端用 FastAPI，前端用 Vue 3 + Vite，数据保存在本机 SQLite 中。

## 源码目录

| 目录 | 内容 |
| --- | --- |
| [backend/](backend/) | 采集、统计、故障判断和 Telegram 通知 |
| [frontend/](frontend/) | 网页源码 |
| [monitor/](monitor/) | 监控实例的示例配置 |
| [main/](main/) | 主代理的示例配置 |
| [deploy/](deploy/) | systemd、Nginx 和环境变量示例 |
| [docs/](docs/) | 安装和维护说明 |
| [tests/](tests/) | 离线测试 |

## 本地开发

先克隆源码。下面的命令都从项目根目录开始执行。

准备后端和配置文件：

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
cp .env.example .env
cp monitor/config.example.yaml monitor/config.yaml
cp monitor/nodes.example.yaml monitor/nodes.yaml
```

然后分别打开三个终端，每个终端都先进入项目根目录。

监控实例：

```bash
mihomo -d "$PWD/monitor"
```

后端：

```bash
set -a; . ./.env; set +a
(cd backend && .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log)
```

前端：

```bash
cd frontend
npm ci
npm run dev
```

开发页面地址是 `http://127.0.0.1:5173`。Python 不会自动加载 `.env`，所以上面的后端命令先把它读入环境变量。

订阅默认通过 `127.0.0.1:7890` 下载。需要直连时，将 `SLA_DOWNLOAD_PROXY` 留空。

## 测试

在项目根目录执行：

```bash
backend/.venv/bin/python -m compileall -q backend tests tools
backend/.venv/bin/python -m unittest discover -s tests -v
backend/.venv/bin/python tools/check_public_tree.py
cd frontend && npm ci && npm run build
```

测试使用临时数据库和模拟请求，不会读取真实订阅或发送 Telegram 消息。GitHub Actions 会检查后端测试和前端构建。

## 许可证

项目代码采用 [MIT](LICENSE) 许可证。Mihomo 和其他依赖按各自的许可证使用，详见 [第三方软件](docs/THIRD_PARTY.md)。
