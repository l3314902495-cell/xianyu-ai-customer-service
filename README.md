# 闲鱼 AI 客服管理系统

面向卖家的 AI 客服后台：按商品组织知识与 FAQ，统一管理多个账号、买家会话、AI 回复和人工接管。提供不需要 API Key 或真实闲鱼账号的 Mock 演示模式。

**技术栈：** Next.js 15 / React 19 / TypeScript · FastAPI / SQLAlchemy / Alembic · PostgreSQL / Redis

## 功能

- 多账号管理，商品、知识和会话按账号隔离。
- 商品独立知识库、FAQ、Prompt 与回复规则。
- 在线会话、人工回复、人工接管、恢复 AI 和紧急停止。
- Mock、OpenAI、DeepSeek 及自定义 OpenAI-compatible 模型配置。
- AI 决策日志、风险检查、消息幂等与知识缺口处理。
- 商品级自动发货，支持卡密、图片与付款事件去重。
- 实验性真实账号登录、卖家商品和会话同步、文本消息收发，以及逐件人工确认的商品发布。

真实闲鱼连接使用实验性网页协议，**并非闲鱼官方 API**，可能随平台变化失效。专用 Edge 登录助手目前面向 Windows；跨平台用户可先使用 Mock 模式。项目与闲鱼及模型服务商无隶属关系。

## 快速体验

安装 Docker 与 Docker Compose v2。在项目根目录运行：

```bash
docker compose up --build
```

首次构建需要网络，容器会执行数据库迁移并初始化演示数据。

- 管理后台：<http://localhost:3000>
- API 文档：<http://localhost:8000/docs>
- 演示管理员：`admin` / `Admin123!`

登录后进入「开发工具 → 闲鱼消息模拟器」，选择 Mock 账号与商品发送消息，再到「客服中心 → 在线会话」查看回复和人工处理流程。

默认密码和 JWT 密钥仅用于本地演示。正式使用前修改管理员密码与密钥；已有加密凭据的环境更换密钥前请阅读 [安全说明](SECURITY.md)。

### Windows 一键启动

安装 Docker Desktop、Node.js 22+ 和 Microsoft Edge 后，双击根目录的 `一键启动闲鱼AI客服.cmd`。脚本会启动本地登录助手与 Docker 服务，并打开后台。也可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File start-xianyu-ai.ps1
```

### 自定义模型

在「AI 管理 → 模型设置」配置 Provider、Base URL、API Key 和 Model，测试成功后保存。保持 `mock` 时无需真实密钥。

环境配置模板为 [.env.example](.env.example)。其中数据库主机名适用于 Compose；本地直接运行 API 的配置见 [使用指南](docs/USAGE.md)。

## 项目结构

```text
apps/api/              FastAPI、数据库迁移、业务服务和后端测试
apps/web/              Next.js 管理后台和前端测试
docker/                容器构建与验证脚本
docs/                  使用、架构、实时监听与分享指南
tools/                 Edge 登录助手与源码导出工具
.github/workflows/     GitHub Actions CI
docker-compose.yml     PostgreSQL、Redis、API、监听进程和 Web
```

## 开发与文档

本地开发需要 Node.js 22+、pnpm（版本见 `package.json`）、Python 3.12+；完整并发和实时处理需要 Redis，生产数据库使用 PostgreSQL。

- [详细使用指南](docs/USAGE.md)：本地安装、配置、测试和功能边界。
- [架构说明](docs/ARCHITECTURE.md)与[实时监听说明](docs/REALTIME_LISTENER.md)。
- [真实账号接入](docs/REAL_XIANYU_INTEGRATION.md)：实验接入的限制和运行条件。
- [贡献指南](CONTRIBUTING.md)与[安全反馈](SECURITY.md)。
- [上传 GitHub](docs/GITHUB_SHARING.md)：网页上传、Git 推送和重新导出源码包。

## 许可证

本项目原创代码采用 [Apache License 2.0](LICENSE)，允许依照许可证修改和再分发，包括商业使用。第三方来源保留各自许可和归属，见 [NOTICE](NOTICE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
