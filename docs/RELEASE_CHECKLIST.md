# 发布检查

提交或发布前看一下这些内容：

- [ ] 后端测试和前端构建通过。
- [ ] 运行 `python tools/check_public_tree.py`，并查看 `git diff --cached` 和 `git ls-files`。
- [ ] 示例配置中没有真实订阅、节点凭据、Telegram Token / Chat ID 或 API 密钥。
- [ ] 没有把生产配置、数据库、日志、备份、依赖目录、构建产物和未脱敏截图放进提交。
- [ ] 检查要发布的分支和标签。如果曾提交过秘密，先轮换凭据，再清理所有受影响的历史；新增 `.gitignore` 不能代替这一步。
- [ ] 改动涉及部署时，在单独的 Ubuntu 环境检查服务启动、Mihomo Provider 刷新和 Telegram 通知。
- [ ] 更新受影响的文档、依赖版本和第三方许可证说明。

发布后查看 GitHub Actions 的结果。仓库设置中如果有秘密扫描和推送保护，也可以开启。

凭据处理见 [安全说明](../SECURITY.md)，安装步骤见 [部署文档](DEPLOYMENT.md)。
