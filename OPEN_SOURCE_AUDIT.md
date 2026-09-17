# 开源项目审计

审计日期：2026-08-19。原则：只从许可证清晰且兼容的项目吸收通用实现模式；本项目代码按既定 domain/service/repository/adapter/schema 架构重新实现，不接入任何逆向、验证码绕过、风控规避或未经确认的闲鱼私有协议。

| 候选项目 | 许可证与维护 | 源码/依赖检查 | 可借鉴内容 | 风险 | 决定 |
| --- | --- | --- | --- | --- | --- |
| [haoyiyin/basjoo](https://github.com/haoyiyin/basjoo) | MIT；约 360 commits，含测试与 E2E | FastAPI、Next.js、Redis、多 Provider、会话接管；依赖 Qdrant/抓取服务，超出 V1 | Provider 解耦、配置密钥脱敏、知识隔离、会话接管、服务降级、Docker 健康检查 | 原项目同时使用 SQLite/Qdrant，数据模型不适配商品维度 | 参考架构与安全模式，未复制源码；在 PostgreSQL/Redis 架构内独立实现 |
| [jawwad-ali/ai-customer-support-agent](https://github.com/jawwad-ali/ai-customer-support-agent) | MIT；约 73 commits，测试目录完整 | FastAPI、PostgreSQL/pgvector、Redis、Next.js；源码按 agent/api/database/tests 分层 | 知识无匹配即升级人工、Redis 不可用时降级、薄 API 层、全链路日志/关联 ID | 使用 OpenAI Agents SDK 与多渠道 CRM，复杂度和数据域不同 | 采用“规则拥有最终权限、AI 失败安全转人工”的设计思想，独立实现 |
| [dameng2026/xianyu-pilot](https://github.com/dameng2026/xianyu-pilot) | Apache-2.0；近期活跃，含安全与迁移文档 | FastAPI/Vue/MySQL/Redis，多账号、WebSocket、AI/RAG、审计日志；另含 Playwright 滑块模块 | 会话级 AI 开关、消息/AI 分支原子落库、租约/去重、Docker 运维结构 | 含滑块求解、Cookie/平台自动化、MySQL/Vue，部分功能与合规边界冲突 | 仅参考合规的状态机、幂等、审计和运维模式；明确排除爬虫/滑块/私有连接 |
| [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent) | GPL-3.0；较多提交与用户，但强 copyleft | Python 单体 Agent、Prompt 分类、上下文；依赖 Cookie/非官方通信 | 只参考意图分流与上下文窗口的概念 | GPL 不作为直接复用来源；依赖非官方接口、Cookie 与模拟人工行为 | 不复制代码、不引入依赖；仅做概念对照 |
| [cv-cat/XianYuApis](https://github.com/cv-cat/XianYuApis) | 仓库未提供可识别 LICENSE | 实际源码含逆向签名、私有 WebSocket/HTTP、Cookie 和协议解析 | Adapter 边界的反例验证：平台连接必须与业务隔离 | 无许可证；逆向/私有协议/登录态和合规风险，与明确要求冲突 | 完全不复用、不接入；`RealXianyuAdapter` 只保留空骨架 |

## 真实账号连接专项复审（2026-08-19）

用户明确提出连接自有真实闲鱼账号后，对近期活跃仓库做了第二轮实际源码审查。审查使用浅克隆，不执行仓库脚本、不导入 Cookie、不连接真实账号。

| 项目 | 许可证 / 活跃度 | 实际实现 | 优点 | 风险与决定 |
| --- | --- | --- | --- | --- |
| [fancyboi999/goofish-cli](https://github.com/fancyboi999/goofish-cli) | Apache-2.0；审计时最新提交 2026-08-19；约 23 个测试文件 | Playwright 可见浏览器扫码；Cookie 加密；MTOP 签名；私有 LWP WebSocket 收发；限流和风控熔断 | 当前工程质量最好的非官方连接候选，模块边界清楚 | 使用逆向 Web IM 协议；会读取浏览器 Cookie；浏览器模块含自动化特征隐藏逻辑。仅参考“可见扫码、密钥加密、限流、熔断”的通用设计，不复制或接入私有协议代码 |
| [zhinianboke/xianyu-auto-reply](https://github.com/zhinianboke/xianyu-auto-reply) | AGPL-3.0；审计时最新提交 2026-08-17 | 多服务架构、Cookie/密码登录、WebSocket、Playwright/Patchright、Cookie 续期、滑块处理 | 功能和后台较完整 | AGPL 与当前分发策略不兼容；包含密码保存、自动滑块、真人鼠标/远程打码等高风险模块；不复制、不依赖 |
| [11273/goofish-client](https://github.com/11273/goofish-client) | GPL-3.0；审计时最新提交 2026-07-15 | TypeScript 二维码登录、Cookie、MTOP、私有 WebSocket IM | 客户端抽象较清晰 | GPL 强 copyleft；协议分析产物，非官方授权 API；不复制、不依赖 |
| [laozuzhen/xianyu-openclaw-channel](https://github.com/laozuzhen/xianyu-openclaw-channel) | 未发现 LICENSE | Python 私有 WebSocket Bridge + TS 插件；Playwright 发布；多账号 | Bridge/Adapter 形态可参考 | 无许可证，且文档提及第三方打码和私有协议；不复制、不依赖 |
| [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent) | GPL-3.0 | Cookie + 固定私有 WebSocket 地址、消息解密与 ACK、AI 回复 | 能证明技术链路可运行 | GPL；单体代码；私有协议和 Cookie 风险；不复制、不依赖 |

### 专项结论

1. GitHub 上“个人闲鱼账号实时收发消息”的项目，核心都不是公开官方客服 API，而是 Cookie、网页端 MTOP 和私有 WebSocket 协议。
2. 工程质量首选是 `goofish-cli`，功能完整度首选是 `xianyu-pilot`，但两者都不能消除账号风控、协议变更和平台条款风险。
3. `xianyu-pilot` 和 `zhinianboke/xianyu-auto-reply` 含自动滑块/验证处理，明确不引入。
4. 2026-09-10 用户明确要求增加真实商品发布；项目在 `experimental-web` Adapter 下启用逐件人工复核发布，`RealXianyuAdapter` 仍只代表尚未配置的官方授权接口。
5. 实验接入的安全边界是：仅自有账号、可见浏览器人工扫码、人工完成任何验证、Cookie 加密、独立账号隔离、严格限流与熔断、可随时停用；不读取其他浏览器数据、不保存密码、不自动解验证码、不批量发布、不自动改价或退款。最终发布请求不自动重试，未知结果必须先同步确认。

## 最终采用的工程模式

1. API 路由保持薄层，核心在 service/domain；AI、平台发送、存储分别有明确边界。
2. AI 输出先结构化校验，再经过后端 `AutoSendGuard`，模型永远没有最终发送权。
3. Redis 负责 debounce、幂等和会话锁；Redis 故障时保守降级为转人工，不绕过安全检查。
4. 商品知识查询始终带 `product_id`，并以自动测试验证跨商品隔离。
5. 高风险、知识缺失、模型异常或非法 JSON 都以“禁止自动发送 + 转人工 + 记录日志”结束。

## 依赖与安全结论

- 未导入候选仓库的验证码、滑块、Cookie、签名、WebSocket 私有协议、反爬或风控绕过代码。
- 未直接复制 GPL、无许可证项目代码。
- V1 不引入向量库和 Agent SDK；商品知识规模下优先使用确定性的商品外键隔离与完整知识上下文，降低额外运维面。
- 运行时第三方库由 `pyproject.toml`、各 `package.json` 与锁文件固定，并通过 lint、typecheck、test、build 验证。

## 2026-08-28 自动发货专项审计

- `dameng2026/xianyu-pilot`（Apache-2.0）实际源码包含商品级发货规则、付款状态识别、订单幂等、卡密占用/回滚和图片消息结构。
- 采用的设计：每个商品独立开关且默认关闭；`contentType=26` 仍不能单独证明付款，必须排除“待付款”并命中“已付款/等待发货”；订单号唯一约束和发货记录双重防重；发送失败释放卡密。
- 图片消息结构按 Apache-2.0 源码重写并适配现有 Adapter。仅接受公网 HTTPS 素材，不引入图片抓取、风控绕过、滑块或验证码逻辑。
- 未复制其 Vue/MySQL 业务层；本项目使用 FastAPI、SQLAlchemy、PostgreSQL、Next.js，并重新实现 `service/schema/adapter` 边界。

## 2026-09-10 商品发布专项审计

- 重新核对 `fancyboi999/goofish-cli` 当前 Apache-2.0 源码中的 `item/publish.py`、`media/upload.py`、`category/recommend.py` 与 `location/default.py`。
- 采用的链路：上传本地图片到闲鱼 CDN、由平台识别类目、单次调用 `mtop.idle.pc.idleitem.publish`。没有采用固定上海坐标的默认地址请求，避免错误表达商品所在地；地址字段留空，由平台账号与发布规则处理。
- 本项目新增数据库发布审计、请求幂等键、每账号每分钟一次、前端编辑/复核两步确认、图片 MIME 与文件签名双重验证，并禁止最终发布请求自动重试。
- 未引入批量发布、Playwright 隐身、滑块/验证码处理、设备伪造、自动改价或退款。
