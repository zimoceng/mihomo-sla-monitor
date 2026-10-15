# 来源与第三方软件

维护者说明：本项目的前后端主要由维护者与 AI 从头编写。整理时未在提供的项目目录中发现 .git 历史、第三方项目的整份源码或图片资源。保留原有功能模块命名和原创实现；这一检查不能取代对未知外部历史的核对。

## 项目许可证

原创代码使用仓库根目录的 MIT License，版权署名为“2026 Mihomo SLA Monitor contributors”。该署名不替换依赖包的版权和许可证。

## 直接依赖与运行组件

| 软件 | 用途 | 上游许可证/说明 |
| --- | --- | --- |
| [Vue](https://github.com/vuejs/core/blob/main/LICENSE) | 前端框架 | MIT |
| [Vite](https://github.com/vitejs/vite/blob/main/LICENSE) | 前端构建 | MIT；发行包另含第三方说明 |
| [@vitejs/plugin-vue](https://github.com/vitejs/vite-plugin-vue/blob/main/LICENSE) | 声明的前端开发依赖 | MIT |
| [FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE) | HTTP API | MIT |
| [Uvicorn](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) | ASGI 服务 | BSD-3-Clause |
| [httpx](https://github.com/encode/httpx/blob/master/LICENSE.md) | HTTP 客户端 | BSD-3-Clause |
| [PyYAML](https://github.com/yaml/pyyaml/blob/main/LICENSE) | YAML 解析 | MIT |
| [Mihomo](https://github.com/MetaCubeX/mihomo/blob/Meta/LICENSE) | 单独安装的代理/监控内核 | GPL-3.0；内核源码和二进制不包含在本仓库 |

Python 具体版本见 backend/requirements.lock.txt，前端具体版本见 frontend/package-lock.json。Pydantic、Starlette、AnyIO、Rollup、esbuild 等传递依赖也保留各自许可证；安装或重新分发它们时应保留相应发行包的版权和许可文件。本仓库只提交依赖声明及锁文件，不提交 venv、node_modules 或 dist。

本项目通过本地 HTTP API 与独立安装的 Mihomo 交互。仓库 MIT 许可证不对 Mihomo、Nginx、Python、Node.js 或其他软件重新授权。若今后加入或修改第三方源码/二进制，应重新核对其分发要求并更新本说明。

控制台使用现有自定义 CSS，未附带 Cloudflare 商标、Logo、远程字体或生产截图；本项目不代表上述软件或公司的官方产品。
