# 第三方软件

项目代码采用 [MIT](../LICENSE) 许可证。下面这些依赖保留各自的版权和许可证：

| 软件 | 用途 | 上游许可证/说明 |
| --- | --- | --- |
| [Vue](https://github.com/vuejs/core/blob/main/LICENSE) | 前端框架 | MIT |
| [Vite](https://github.com/vitejs/vite/blob/main/LICENSE) | 前端构建 | MIT；发行包另含第三方说明 |
| [@vitejs/plugin-vue](https://github.com/vitejs/vite-plugin-vue/blob/main/LICENSE) | 前端开发依赖 | MIT |
| [FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE) | HTTP API | MIT |
| [Uvicorn](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) | ASGI 服务 | BSD-3-Clause |
| [httpx](https://github.com/encode/httpx/blob/master/LICENSE.md) | HTTP 客户端 | BSD-3-Clause |
| [PyYAML](https://github.com/yaml/pyyaml/blob/main/LICENSE) | YAML 解析 | MIT |
| [Mihomo](https://github.com/MetaCubeX/mihomo/blob/Meta/LICENSE) | 单独安装的代理/监控内核 | GPL-3.0；内核源码和二进制不包含在本仓库 |

Python 依赖版本见 `backend/requirements.lock.txt`，前端依赖版本见 `frontend/package-lock.json`。Pydantic、Starlette、AnyIO、Rollup、esbuild 等间接依赖，也按各自的许可证使用。

Mihomo 需要单独安装，仓库里没有附带它的源码或二进制。项目通过本机 HTTP API 调用它，项目的 MIT 许可证不替代 Mihomo 的 GPL-3.0 许可证。

如果后续打包或分发依赖、构建产物，需要保留相应的版权和许可文件。加入第三方源码时，也请补上来源和许可证。
