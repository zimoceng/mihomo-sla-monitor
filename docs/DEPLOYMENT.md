# Ubuntu 24.04 部署

以下步骤面向全新机器或隔离验证环境。源码位于 `/opt/mihomo-sla`；数据库和生产配置存放在 `/var/lib`、`/etc`，不进入仓库。

## 1. 准备依赖和源码

安装 Python 3.12、venv、Nginx、Git，以及 Node.js 22.12+。Node.js 安装方式见[官方发布页](https://nodejs.org/en/download)。Mihomo 内核从[官方发行页](https://github.com/MetaCubeX/mihomo/releases)单独获取，核对该发行版校验值、放到 `/usr/local/bin/mihomo` 并赋予执行权限。

记录 `python3 --version`、`node --version` 和 `mihomo -v`；不要直接运行来历不明的安装脚本。

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx git
# 将本仓库源码复制或克隆到 /opt/mihomo-sla
cd /opt/mihomo-sla
sudo useradd --system --home /var/lib/mihomo-sla --shell /usr/sbin/nologin mihomo-sla
sudo python3 -m venv backend/.venv
sudo backend/.venv/bin/pip install -r backend/requirements.lock.txt
sudo chown -R root:root /opt/mihomo-sla
sudo chmod -R a+rX /opt/mihomo-sla
```

依赖锁文件来自原有 Python 3.12 部署；前端使用已有 `package-lock.json`。需要更新依赖时应重新测试后再更新锁文件，不应随部署自动升级。

## 2. 主代理与独立监控实例

已有主 Mihomo 在 `127.0.0.1:7890` 可用时直接复用它。不要替换已有的 AnyTLS/Shadowsocks 配置。

```bash
cd /opt/mihomo-sla
sudo install -d -o mihomo-sla -g mihomo-sla -m 0700 /var/lib/mihomo-sla-monitor
sudo install -o mihomo-sla -g mihomo-sla -m 0600 monitor/config.example.yaml /var/lib/mihomo-sla-monitor/config.yaml
sudo install -o mihomo-sla -g mihomo-sla -m 0600 monitor/nodes.example.yaml /var/lib/mihomo-sla-monitor/nodes.yaml
sudo -u mihomo-sla /usr/local/bin/mihomo -t -d /var/lib/mihomo-sla-monitor
```

示例不含真实节点。监控端口为 `127.0.0.1:19091`，没有代理入站且 TUN 关闭；Provider 名称必须保持 `all-nodes`。API 对文件型 Provider 的刷新行为依赖所安装内核，首次部署需用自己的订阅验证刷新成功和节点列表。

如需设置监控 API 的 `secret`，只编辑本机生产配置，并在下一步的 `MIHOMO_SECRET` 中填写一致的值。空密钥示例仅配合环回绑定使用。

### 可选：全新机器的主代理

仅在没有已有主代理时执行本节。两个实例的目录、代理端口和控制端口互不冲突。

```bash
sudo useradd --system --home /var/lib/mihomo-sla-main --shell /usr/sbin/nologin mihomo-main
sudo install -d -o mihomo-main -g mihomo-main -m 0700 /var/lib/mihomo-sla-main
sudo install -o mihomo-main -g mihomo-main -m 0600 main/config.example.yaml /var/lib/mihomo-sla-main/config.yaml
sudo install -o mihomo-main -g mihomo-main -m 0600 main/nodes.example.yaml /var/lib/mihomo-sla-main/nodes.yaml
# 在本机编辑 nodes.yaml，填入自己的有效节点；不要提交该文件
sudoedit /var/lib/mihomo-sla-main/nodes.yaml
sudo -u mihomo-main /usr/local/bin/mihomo -t -d /var/lib/mihomo-sla-main
sudo install -m 0644 deploy/mihomo-sla-main.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-sla-main
```

主代理 `mixed-port` 为 `127.0.0.1:7890`，控制 API 为 `127.0.0.1:19090`。示例 DIRECT 节点不是可用的境外代理，必须替换为自己的节点。

## 3. 后端和探测设置

```bash
sudo install -d -m 0750 -o root -g mihomo-sla /etc/mihomo-sla
sudo install -o root -g root -m 0600 .env.example /etc/mihomo-sla/backend.env
sudoedit /etc/mihomo-sla/backend.env
sudo install -m 0644 deploy/mihomo-sla-monitor.service deploy/mihomo-sla-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-sla-monitor mihomo-sla-backend
curl --fail http://127.0.0.1:8000/api/health
```

systemd 以非 root 用户运行。后端单进程采集，不能启动多个 Uvicorn worker，否则会重复采样。目录由 StateDirectory 创建，运行时路径如下：

| 文件 | 作用 |
| --- | --- |
| /var/lib/mihomo-sla/sla.db | 新部署自动创建的 SQLite |
| /var/lib/mihomo-sla/probe-settings.json | 网页保存的探测设置 |
| /var/lib/mihomo-sla-monitor/nodes.yaml | 导入后的私有节点 |
| /etc/mihomo-sla/backend.env | 后端环境变量 |

`.env.example` 中路径变量默认被注释，systemd 单元提供部署路径。配置文件里手动取消注释的值会覆盖单元默认值。Python 本身不加载 `.env`。

初始探测参数为 60 秒、5000 毫秒超时、5 并发。网页保存后，设置文件优先于环境变量中的探测目标、间隔和超时；下一轮采集生效。新部署无需复制生产 JSON 或数据库。

## 4. 构建前端并配置 Nginx

在可写的构建工作区执行前端构建，再只复制静态产物。生产源码可以由 root 持有，应用用户无需写入它。

```bash
cd /opt/mihomo-sla/frontend
# 在全新测试机上可由管理员执行；已有机器请使用自己的构建账号/工作区
sudo npm ci --ignore-scripts
sudo npm run build
sudo install -d -m 0755 /var/www/mihomo-sla
sudo cp -R dist/. /var/www/mihomo-sla/
cd /opt/mihomo-sla
sudo install -m 0644 deploy/nginx.conf /etc/nginx/sites-available/mihomo-sla
sudo ln -s /etc/nginx/sites-available/mihomo-sla /etc/nginx/sites-enabled/mihomo-sla
sudo nginx -t
sudo systemctl reload nginx
```

Nginx 模板只监听 `127.0.0.1:8080`，不会将后台直接暴露到局域网或公网。浏览器访问前，在自己的电脑创建隧道（替换主机、端口和用户名）：

```powershell
ssh -p YOUR_SSH_PORT -L 8080:127.0.0.1:8080 USER@YOUR_SERVER
```

访问 `http://127.0.0.1:8080`，在页面中导入自己的 HTTPS Mihomo YAML 订阅。成功后查询节点列表，再等待采集产生数据。订阅 URL 只在本次请求中使用；持久化的是私有节点文件。

首次启动只有示例 DIRECT 节点时，采集器显示尚无真实节点是预期状态。不要把导入订阅成功与代理实际可用混为一谈。

## 5. 可选 Telegram 通知

先通过 BotFather 创建或轮换自己的 Bot Token，并确定目标 Chat ID。真实值只写入服务器环境文件，不能粘贴到 issue、截图或提交中。

```bash
cd /opt/mihomo-sla
sudo install -o root -g root -m 0600 deploy/telegram.env.example /etc/mihomo-sla/telegram.env
sudoedit /etc/mihomo-sla/telegram.env
sudo install -m 0644 deploy/mihomo-sla-telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-sla-telegram
```

填入 `SLA_TG_BOT_TOKEN` 和 `SLA_TG_CHAT_ID`。通过 `SLA_TG_PROXY` 使用主代理；空值或 `direct` 表示直连。不要启动模板中的空凭据服务来测试真实消息。

worker 首次记录当前最大事件编号作为基线，不补发旧事件；收到 Telegram 成功响应后才记录已发送状态。网络恢复后会重试；若消息已送达但本地状态写入前进程崩溃，仍可能重复投递。删除状态数据库会重新建立基线。

## 6. 检查与故障定位

```bash
systemctl status mihomo-sla-monitor mihomo-sla-backend
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/incidents/health
journalctl -u mihomo-sla-backend -n 50 --no-pager
```

- 后端无法启动：检查 venv、环境变量、数据目录权限和监控服务。
- 订阅下载失败：检查主代理、订阅 HTTPS 连通性，以及该订阅是否返回 Mihomo YAML。禁用 HTTP 重定向，不支持直接导入 Base64 URI 列表。
- 已保存但刷新失败：核对内核版本、监控实例端口、`MIHOMO_SECRET` 与 Provider 名称。节点文件必须可由后端写入并由监控实例读取。
- 修改环境变量后需要重启对应服务；网页探测设置下一轮生效。
- Telegram 不发旧事件属于预期行为；新事件故障需检查 worker 状态和本机环境文件。日志和截图也可能包含节点名称、探测地址，分享前需脱敏。

这些模板是在源码行为基础上新建的部署方案，不是现有服务器 systemd/Nginx 配置的备份。当前整理在 Windows 本地完成；Linux 服务启停、内核 Provider 刷新和真实 Telegram 投递仍需在隔离 Ubuntu 环境验收。不要在运行中的生产 NAS 上直接套用。
