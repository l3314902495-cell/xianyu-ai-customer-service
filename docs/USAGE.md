# 闲鱼 AI 智能客服管理系统 V1

一个可实际运行的单卖家 AI 客服后台。卖家为每件商品配置独立知识、FAQ 和 Prompt；买家消息经过商品识别、知识加载、结构化 AI 决策、后端安全检查后才可能自动发送。知识不足时根据回复策略进行澄清或转人工，高风险和模型异常会转人工，并保留消息、决策和风险日志。

## 已实现功能

- 管理员用户名/邮箱 + Argon2 密码登录，JWT HttpOnly Cookie。
- 多闲鱼账号管理、连接状态、账号级 AI 开关；商品和会话严格归属账号，同一商品外部 ID 可存在于不同账号且不会串数据。
- 商品完整资料 CRUD、快速 AI 开关、商品独立知识/FAQ/Prompt、特殊回复规则和禁止回答规则；知识与 FAQ 支持编辑、启停和优先级。
- 已连接的实验性真实账号支持人工确认后发布单件商品：上传 1–9 张图片、选择运费方式、调用闲鱼网页发布链路，并将成功返回的商品 ID 回写本地商品库。
- 三栏客服工作台、会话筛选与未读清零、AI/人工/系统消息标识、人工接管、人工回复、恢复 AI、关闭/重开会话，以及 AI 建议的一键发送、编辑后发送和忽略。
- Mock、OpenAI、DeepSeek 与自定义 OpenAI-compatible Provider 预设；Base URL、API Key、Model、Temperature、Max Tokens、Timeout；当前表单连接测试和密钥脱敏/加密存储。
- `PromptBuilder` 按全局规则、商品 Prompt、商品知识、FAQ、最近历史和最新消息组装上下文。
- Pydantic 结构化输出；真实 Provider 对非法 JSON 自动修复/重试一次，失败即禁止发送并转人工。
- 后端 `AutoSendGuard` 检查全局、账号、商品、会话状态、人工接管、受限 Intent、风险、知识缺口、置信度、禁止短语和模型决策；WebSocket 握手同样校验管理员 JWT。
- Redis 1500ms 消息聚合、`ai_reply_lock:{conversation_id}` 会话锁、外部消息幂等、回复 ID 防重复。
- Prompt 注入、退款/投诉/赔偿、砍价与知识缺失处理；KnowledgeGap 人工确认后写入对应商品知识库。
- Mock 闲鱼消息模拟器贯穿真实后端链路；每个 Mock 账号使用独立 Adapter 实例，WebSocket 推送消息和会话状态。
- 数据库仪表盘、可展开的消息/AI 决策/风险日志、Token/成本字段、可标记已读的通知中心。
- 回复规则页可配置自动发送最低置信度、店铺规则、砍价/知识缺失话术与禁止短语；系统设置页可配置 debounce、历史条数和消息过滤前缀。
- 全局 AI 开关与二次确认的紧急停止按钮。
- PostgreSQL、Redis、FastAPI、Next.js 的 Docker Compose 环境；Alembic 真实迁移和幂等 Seed。

## 技术架构

- Web：Next.js 15、React 19、TypeScript strict、Tailwind CSS、TanStack Query、Zustand、shadcn 风格组件。
- API：Python 3.12、FastAPI、SQLAlchemy 2 async、Pydantic 2、Alembic。
- 数据：PostgreSQL 16、Redis 7。
- AI：统一 `LLMProvider`，V1 提供 `MockLLMProvider` 和 `OpenAICompatibleProvider`。
- 平台：统一 `XianyuAdapter`，提供 `MockXianyuAdapter`、实验性 `ExperimentalWebXianyuAdapter` 和尚未配置的官方 `RealXianyuAdapter` 骨架。

详细链路见 [ARCHITECTURE.md](ARCHITECTURE.md)，历史开源调研见 [OPEN_SOURCE_AUDIT.md](../OPEN_SOURCE_AUDIT.md)，当前第三方来源见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 主要目录

```text
apps/
  api/                 FastAPI、SQLAlchemy、Alembic、Seed、pytest
  web/                 Next.js 管理后台
docker/                API/Web 镜像
docs/                  架构文档
docker-compose.yml
TASKS.md
```

## 环境要求

- Docker 24+ 与 Docker Compose v2（推荐）。
- 本地开发：Node.js 22+、pnpm（版本见根目录 `package.json`）、Python 3.12+、PostgreSQL 16、Redis 7。

## Docker 一键启动

Mock 模式不需要 API Key，也不强制创建 `.env`：

```bash
docker compose up --build
```

打开 `http://localhost:3000`。API 文档位于 `http://localhost:8000/docs`。

需要自定义配置时：

```bash
cp .env.example .env
docker compose up --build
```

容器启动顺序会等待 PostgreSQL/Redis 健康，通过 `alembic upgrade head` 建表，再执行幂等 Seed。

## 默认管理员

```text
用户名：admin
邮箱：admin@example.com
密码：Admin123!
```

首次登录后应修改默认密码和 `JWT_SECRET`；默认凭据只用于开发。Seed 管理员固定使用以上凭据，环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 不会覆盖它们。已有账号凭据的环境更换 `JWT_SECRET` 前请阅读 [安全说明](../SECURITY.md)。

## 商品级自动发货

后台进入「自动化 → 自动发货」，先选择具体商品，再单独开启。所有商品默认关闭，导入卡密也不会自动开启商品。

- 卡密：每行导入一条，后端加密保存；订单发送失败会退回可用库存。
- 图片：填写买家设备可访问的公网 HTTPS 图片地址。
- 触发：仅处理带订单号、商品 ID、买家 ID 且明确为“已付款/等待发货”的系统订单事件；“待付款”和普通聊天文字不会触发。
- 防重：同一账号下同一订单只会生成一条发货记录，不会重复扣减卡密。
- 测试：Mock 账号商品可使用页面右侧「模拟该商品已付款」；该按钮拒绝真实闲鱼账号。

当前真实账号采用实验性网页连接，卡密文本发送可使用现有文本通道；图片需使用公网 HTTPS 素材。任何验证、连接中断或平台发送失败都会停止本次发货并通知后台，不会绕过平台安全机制。
## 本地启动

以下命令从项目根目录开始。API 从当前工作目录读取 `.env`，不要直接把 Compose 的数据库主机名用于本地开发。可创建 `apps/api/.env`：

```env
DATABASE_URL=sqlite+aiosqlite:///./xianyu_dev.db
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=replace-with-a-long-random-secret
LLM_PROVIDER=mock
XIANYU_RUNTIME_MODE=embedded
```

安装并启动 Redis；如使用本地 PostgreSQL，将 `DATABASE_URL` 改为自己的连接地址。Docker 模式与本地模式分别使用各自的数据，不要同时占用相同 API/Web 端口。

```bash
pnpm install

cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

另一个终端，从项目根目录运行：

```bash
pnpm --filter @xianyu/web dev
```

本地没有 PostgreSQL 时，API 的开发默认值为 `sqlite+aiosqlite:///./xianyu_dev.db`，仅用于快速开发与测试；Docker 和正式环境使用 PostgreSQL。Redis 不可用时系统保守降级，消息仍落库，AI 并发/聚合能力不可用且高风险流程不会绕过 Guard。

## 环境变量

复制 `.env.example`，关键项：

```env
DATABASE_URL=postgresql+asyncpg://xianyu:xianyu@postgres:5432/xianyu_ai
REDIS_URL=redis://redis:6379/0
JWT_SECRET=replace-with-a-long-random-secret
LLM_PROVIDER=mock
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4.1-mini
NEXT_PUBLIC_API_URL=http://localhost:8000
```

真实密钥不得提交到 Git。

## 数据库迁移与 Seed

```bash
cd apps/api
alembic upgrade head
python -m app.seed
```

新增模型后生成迁移：

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

全新数据库的 Seed 创建 2 个 Mock 账号、3 个商品及不同知识/FAQ/Prompt、5 个会话和若干消息。Seed 可重复执行，不会重复插入。

## 配置大模型

1. 登录后台，打开「AI 管理 → 模型设置」。
2. Provider 选择 `OpenAI`、`DeepSeek` 或 `自定义 OpenAI Compatible`；预设会自动填写官方 Base URL。
3. 填写 Base URL、API Key、Model Name、Temperature、Max Tokens 和 Timeout。
4. 点击「测试当前配置」。测试直接使用当前表单但不会落库，成功后再点击「保存并启用」。
5. API Key 可保留、替换或主动移除，只在后端加密保存，页面和 API 只显示脱敏值。

不填密钥并保持 Provider=`mock` 时，完整 UI、模拟器、风控和人工流程仍可运行。

真实模型回复不是固定话术：每次请求都会动态组合全局 Prompt、当前商品专属 Prompt、当前商品知识与 FAQ、最近聊天历史和买家最新消息。Mock Provider 只用于无密钥时验收业务链；要获得自然、个性化的模型回复，需要在上述页面保存可用的 OpenAI-compatible 配置。

## 完整测试流程

1. 「系统设置 → 闲鱼账号」可添加多个账号并连接；每个账号可独立关闭 AI。
2. 「商品管理 → 新增商品」，选择所属账号，填写商品信息和商品专属 Prompt。
3. 在商品详情中添加独立知识和 FAQ。
4. 「开发工具 → 闲鱼消息模拟器」，选择账号、该账号下的商品和买家，发送“这个还有吗？”。
5. 打开「客服中心 → 在线会话」，查看经过 debounce、知识加载、结构化决策和 Guard 后的 AI 回复。
6. 再发送知识中没有的问题，例如“防水等级是 IPX7 吗？”，会话进入「待人工处理」。
7. 在工作台人工接管并回复；到「商品知识库」对 KnowledgeGap 点击“保存为商品知识”，人工确认标题和答案。
8. 回到会话点击「恢复 AI 托管」，再次提问验证新知识。
9. 在「AI 测试台」可查看 intent、confidence、risk、实际使用的商品 Prompt/知识和原始 JSON，且不会真实发送。

## 测试与质量命令

```bash
# Web
pnpm --filter @xianyu/web lint
pnpm --filter @xianyu/web typecheck
pnpm --filter @xianyu/web test
pnpm --filter @xianyu/web build

# API
cd apps/api
ruff check app tests
pytest -q
```

后端测试覆盖商品知识隔离、Prompt Builder、JSON 解析/修复、人工接管/恢复、幂等、KnowledgeGap、受限 Intent、Prompt 注入、WebSocket 鉴权、Redis 锁失败安全和自动发送判断；HTTP 级完整流程覆盖“创建商品 → 添加知识 → 模拟消息 → 自动回复 → 未知问题 → 人工 → 保存知识 → 恢复 AI”。

## 真实闲鱼接入说明

系统同时提供 `MockXianyuAdapter`、实验性 `ExperimentalWebXianyuAdapter` 和官方接入预留 `RealXianyuAdapter`。

连接本人真实账号：进入“系统设置 → 闲鱼账号”，点击“添加真实账号”，使用闲鱼 App 扫码并在手机上确认。系统会为每个账号建立一个固定且相互隔离的专用 Edge Profile；以后账号掉线时点击该账号的“恢复登录”，会复用同一浏览器身份和已有平台登录态。登录凭据只在 API 后端加密保存，前端和账号接口不会返回 Cookie。每个账号运行独立文本消息长连接并可分别启停 AI。

实验性接入不是闲鱼官方开放 API，不保证平台协议长期稳定。目前只允许本人账号通过系统创建的专用 Edge 主动登录和文本收发；系统不会读取日常浏览器 Profile、保存密码、处理验证码/滑块或规避平台风控。专用 Profile 保存在 `.runtime/xianyu-edge-profiles/`，程序和 Docker 重启不会删除它。不要手工清理该目录，也不要同时打开同一账号的两个专用登录窗口。

商品管理页的“发布到闲鱼”只对已连接的实验性真实账号开放。每次发布都需要先填写资料、再查看最终确认页并手动提交；系统不批量发布、不自动重试最终请求。同一账号一分钟只允许发一件。如最终请求超时或未返回商品 ID，记录会进入“结果待确认”并阻止继续发布，需先在闲鱼 App 核对或执行商品同步，避免重复上架。

旧账号首次使用“恢复登录”时会迁移到固定 Profile，因此可能需要最后完成一次扫码或扫脸；以后优先直接恢复已有登录态。平台仍有权在 Cookie 失效、异地网络、设备环境变化或命中风控时要求重新验证，本系统不会也不能绕过。验证完成后保持专用 Edge 窗口打开，系统检测到完整登录态后会自动绑定并安全关闭窗口。

收到本地尚未配置的商品消息时，系统会先刷新本人商品列表并核对归属，无法确认属于当前卖家的消息会跳过。请为已同步的商品补齐资料、知识、FAQ 和独立 Prompt，再开启 AI。

## V1 边界

### 真实账号同步范围

“同步商品与会话”只导入当前账号本人发布的商品，以及这些商品对应的卖家侧会话。购买侧商品和购买侧聊天不会保存到本系统。会话会尽量读取对方公开昵称和头像；平台接口只返回脱敏昵称时，后台按平台返回值显示，读取失败时才使用临时代号。

实时收到无法关联到本人商品的消息时，系统会记录并跳过，不再自动创建占位商品，避免购买记录混入商品管理。

### 自动发送策略

普通商品咨询、体验判断、澄清问题和不作承诺的知识不足回复默认直接发送，不需要人工审批。兼容模型只返回 `reply` 或遗漏部分结构化字段的情况，后端会补齐低风险决策后继续发送。退款、赔偿、投诉、订单修改、明确提示词注入、AI 服务完全失败以及人工主动接管仍保留安全边界。

### 实时商品与初始知识同步

真实账号的 IM 长连接建立后会自动同步本人发布的商品和卖家侧会话。实时消息引用本地尚未存在的商品时，系统会先节流刷新本人商品列表，再按闲鱼商品 ID 建立会话关联；刷新后仍不属于本人商品的消息会跳过。

平台明确返回的商品名称、当前售价、在售状态，以及可获得时的商品描述、分类和发货地，会以 `xianyu_product_sync` 来源写入该商品自己的基础知识。同步更新只修改这一来源的条目，不覆盖人工知识、FAQ 或商品 Prompt，也不会根据标题猜测平台未提供的事实。

- 不执行自动砍价、退款、赔偿、订单/地址修改；只识别并转人工。
- 不包含闲鱼官方生产接口、多租户、复杂 CRM、计费 SaaS 或向量数据库；已支持单管理员管理多个 Mock/实验性真实账号。
- 系统通知仅在后台展示，不含短信/微信推送。
