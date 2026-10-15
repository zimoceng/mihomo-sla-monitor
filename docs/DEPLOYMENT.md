# Ubuntu 24.04 部署

下面按一台新的 Ubuntu 24.04 机器来安装。源码放在 `/opt/mihomo-sla`，配置和运行数据放在 `/etc`、`/var/lib`。已有服务请先核对目录和端口。

## 1. 安装依赖，下载源码

需要 Python 3.12、venv、Nginx、Git 和 Node.js 22.12+。Node.js 按[官方说明](https://nodejs.org/en/download)安装。

Mihomo 从[官方发行页](https://github.com/MetaCubeX/mihomo/releases)下载，核对校验值后放到 `/usr/local/bin/mihomo`，并加上执行权限。

安装后用 `python3 --version`、`node --version` 和 `mihomo -v` 看一下版本，排查问题时会用到。

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx git curl
# 首次安装时，/opt/mihomo-sla 应是尚不存在的新目录
sudo git clone --branch main https://github.com/zimoceng/mihomo-sla-monitor.git /opt/mihomo-sla
cd /opt/mihomo-sla
sudo useradd --system --home /var/lib/mihomo-sla --shell /usr/sbin/nologin mihomo-sla
sudo python3 -m venv backend/.venv
sudo backend/.venv/bin/pip install -r backend/requirements.lock.txt
sudo chown -R root:root /opt/mihomo-sla
sudo chmod -R a+rX /opt/mihomo-sla
```

已经下载到这个目录的话，从 `cd /opt/mihomo-sla` 继续。不要用这组命令覆盖正在运行的项目。

后端按 `requirements.lock.txt` 安装，前端按 `package-lock.json` 安装。更新依赖后先跑测试，再提交新的锁文件。

## 2. 配置 Mihomo

如果已有 Mihomo 在 `127.0.0.1:7890` 提供代理，可以直接复用，原有节点配置不用改。下面单独配置监控实例。

```bash
cd /opt/mihomo-sla
sudo install -d -o mihomo-sla -g mihomo-sla -m 0700 /var/lib/mihomo-sla-monitor
sudo install -o mihomo-sla -g mihomo-sla -m 0600 monitor/config.example.yaml /var/lib/mihomo-sla-monitor/config.yaml
sudo install -o mihomo-sla -g mihomo-sla -m 0600 monitor/nodes.example.yaml /var/lib/mihomo-sla-monitor/nodes.yaml
sudo -u mihomo-sla /usr/local/bin/mihomo -t -d /var/lib/mihomo-sla-monitor
```

监控实例的控制端口是 `127.0.0.1:19091`，不提供代理入站，也不开 TUN。Provider 名称要保留为 `all-nodes`，后端会用这个名称刷新节点。

装好后需要导入自己的订阅，确认当前内核能刷新文件型 Provider，网页能读到节点。

需要给监控 API 设置 `secret` 时，在服务器上修改配置，并把相同的值填进后端的 `MIHOMO_SECRET`。示例里的密钥为空，控制端口只绑定本机地址。

### 没有主代理时

没有现成主代理的话，可以按下面的示例另起一个实例。它和监控实例使用不同的目录与端口。

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

主代理监听 `127.0.0.1:7890`，控制 API 是 `127.0.0.1:19090`。把示例里的 DIRECT 换成自己的有效节点；保留 DIRECT 只能检查配置，不能代替实际代理。

## 3. 启动后端

```bash
sudo install -d -m 0750 -o root -g mihomo-sla /etc/mihomo-sla
sudo install -o root -g root -m 0600 .env.example /etc/mihomo-sla/backend.env
sudoedit /etc/mihomo-sla/backend.env
sudo install -m 0644 deploy/mihomo-sla-monitor.service deploy/mihomo-sla-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-sla-monitor mihomo-sla-backend
curl --fail http://127.0.0.1:8000/api/health
```

服务使用 `mihomo-sla` 用户运行。后端只开一个 Uvicorn worker，多个 worker 会重复采样。systemd 会创建数据目录：

| 文件 | 作用 |
| --- | --- |
| /var/lib/mihomo-sla/sla.db | 新部署自动创建的 SQLite |
| /var/lib/mihomo-sla/probe-settings.json | 网页保存的探测设置 |
| /var/lib/mihomo-sla-monitor/nodes.yaml | 导入后的私有节点 |
| /etc/mihomo-sla/backend.env | 后端环境变量 |

服务的路径由 systemd 单元设置，`.env.example` 中对应的变量默认注释掉了。手动填写这些变量后，会覆盖单元里的默认路径。Python 不会自动读取 `.env`，这里由 systemd 加载环境文件。

默认每 60 秒检测一次，超时 5000 毫秒，并发数为 5。在网页保存探测设置后，目标、间隔和超时会优先使用设置文件里的值，下一轮生效。新安装会自己建库，不需要复制旧数据库或 JSON。

## 4. 构建前端，配置 Nginx

下面在安装目录里构建前端，再把生成的文件复制到 Nginx 目录。也可以在自己的构建目录运行 npm，构建后只复制 `dist`。

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

Nginx 只监听 `127.0.0.1:8080`。在自己的电脑建立 SSH 隧道，把下面的主机、端口和用户名换成自己的：

```powershell
ssh -p YOUR_SSH_PORT -L 8080:127.0.0.1:8080 USER@YOUR_SERVER
```

打开 `http://127.0.0.1:8080`，导入自己的 HTTPS Mihomo YAML 订阅，查询节点列表后等一轮采集。订阅地址只用于这次下载，节点会保存到服务器的私有文件中。

只有示例 DIRECT 节点时，采集器会提示没有可监控的节点。导入后还要看实际探测结果，确认节点可用。

## 5. Telegram 通知（可选）

先在 BotFather 创建机器人，准备好 Token 和 Chat ID，然后写进服务器上的环境文件。

```bash
cd /opt/mihomo-sla
sudo install -o root -g root -m 0600 deploy/telegram.env.example /etc/mihomo-sla/telegram.env
sudoedit /etc/mihomo-sla/telegram.env
sudo install -m 0644 deploy/mihomo-sla-telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-sla-telegram
```

填好 `SLA_TG_BOT_TOKEN` 和 `SLA_TG_CHAT_ID` 再启动通知服务。`SLA_TG_PROXY` 默认使用主代理，留空或填 `direct` 可以直连。

通知进程第一次启动时会从当前事件开始，不补发旧记录。发送成功后才标记为已发送，网络失败会重试。如果消息已送达，但进程在写入状态前退出，可能会重复发送。删除状态数据库后会重新建立起点。

## 6. 排查问题

```bash
systemctl status mihomo-sla-monitor mihomo-sla-backend
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/incidents/health
journalctl -u mihomo-sla-backend -n 50 --no-pager
```

- 后端启动失败：先看日志，再检查虚拟环境、环境变量、数据目录权限和监控服务。
- 订阅下载失败：检查主代理是否可用，地址能否通过 HTTPS 访问，返回的是否为 Mihomo YAML。订阅导入禁用了重定向，也不支持 Base64 URI 列表。
- 节点已保存但刷新失败：检查 Mihomo 版本、监控端口、`MIHOMO_SECRET` 和 `all-nodes` Provider。后端要能写入节点文件，监控实例要能读取它。
- 改了环境变量后重启对应服务；在网页改探测设置则等下一轮生效。
- Telegram 不发旧事件是正常行为。新事件也没通知时，检查通知服务和环境文件。分享日志或截图前，先去掉节点信息、地址和凭据。

部署模板还需要在目标机器上检查。现有测试没有覆盖 systemd 启停、真实订阅刷新和 Telegram 投递，这几项建议先在单独的 Ubuntu 环境试一遍。

其他使用限制见 [安全说明](../SECURITY.md)。
