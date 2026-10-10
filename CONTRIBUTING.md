# 参与贡献

感谢反馈问题和提交改进。先阅读 [README](README.md) 和 [架构说明](docs/ARCHITECTURE.md)，使用 Mock 账号开发和复现问题。

## 提交问题

请提供操作步骤、预期结果、实际结果、操作系统和运行方式。截图与日志请先去除 Cookie、Token、API Key、卡密和买家个人信息。凭据泄露或其他安全问题请按 [SECURITY.md](SECURITY.md) 处理。

## 开发与验证

安装和启动步骤见 [使用指南](docs/USAGE.md)。提交前执行：

```bash
pnpm --filter @xianyu/web lint
pnpm --filter @xianyu/web typecheck
pnpm --filter @xianyu/web test
pnpm --filter @xianyu/web build
cd apps/api
ruff check app tests
pytest -q
```

改动数据库模型时附带 Alembic 迁移。修改交互流程时，可运行 `pnpm --filter @xianyu/web test:e2e`；Windows 下默认使用 `apps/api/.venv` 的 Python，也可通过 `PYTHON` 环境变量指定解释器。

## Pull Request

- 说明解决的问题、最终行为和验证结果。
- 保持账号与商品数据隔离、发货幂等、人工接管和紧急停止行为。
- 不提交 `.env`、数据库、浏览器 Profile、客户聊天数据、卡密或真实账号凭据。
- 新增第三方代码时，记录来源和修改范围，并更新 `THIRD_PARTY_NOTICES.md`。
- 实验性平台接入不得增加自动验证、验证码处理或风控绕过功能。
