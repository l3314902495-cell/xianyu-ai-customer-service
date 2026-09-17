# 闲鱼 AI 智能客服 V1 开发任务

- [x] Phase 1：pnpm monorepo、PostgreSQL、Redis、FastAPI、Next.js、Docker、管理员登录
- [x] Phase 2：商品 CRUD、商品独立知识、FAQ、商品 Prompt
- [x] Phase 3：Conversation、Message、客服工作台、WebSocket
- [x] Phase 4：LLM Provider、PromptBuilder、结构化输出、AIReplyService
- [x] Phase 5：消息处理、Redis debounce/lock、幂等、AutoSendGuard
- [x] Phase 6：待人工、人工接管、恢复 AI、建议回复、知识沉淀
- [x] Phase 7：MockXianyuAdapter、RealXianyuAdapter 骨架、消息模拟器
- [x] Phase 8：AI/消息/风险日志、KnowledgeGap、仪表盘统计、通知
- [x] Phase 9：Alembic、Seed、测试、lint、typecheck、build、启动验证、README

## V1 验收

- [x] 登录、商品、知识、FAQ、Prompt、模型配置
- [x] 模拟消息经过真实后端业务链并显示 AI 回复
- [x] 商品知识严格隔离；知识不足、风险问题自动转人工
- [x] 人工接管/恢复、人工回复、知识沉淀
- [x] AI 测试台、日志、仪表盘、全局开关、紧急停止
- [x] 幂等、debounce、会话锁、Prompt 注入防护
- [x] Docker 配置、迁移、Seed、核心测试与完整 README
- [x] Docker Desktop 实机启动；PostgreSQL/Redis/API/Web 健康运行并完成接口级整链路验收
- [x] 多闲鱼账号管理、账号级 AI 开关、账号/商品/会话隔离、按账号选择 Adapter
- [x] OpenAI-compatible 模型配置、连接测试、商品专属 Prompt 动态加载与结构化决策展示
- [x] 模型设置增强：OpenAI/DeepSeek/自定义预设、当前表单无落库测试、密钥保留/替换/移除、连接错误诊断
- [x] 实验性真实账号扫码接入：多账号加密凭据、独立长连接、文本收发、限速与风控停止
- [ ] 使用用户本人闲鱼 App 完成一次真实扫码与现场文本收发验证

## 2026-08-26 可用性复验

- [x] 回复规则、系统运行参数和消息过滤均有真实数据库 API 与可操作页面
- [x] 商品完整资料、独立 Prompt、特殊/禁止规则、知识/FAQ 编辑启停和优先级可用
- [x] 工作台支持筛选、未读清零、AI 建议处理、关闭/重开、人工接管与恢复 AI
- [x] 通知中心可查看和标记已读；消息、AI、风险日志可查询并展开审计详情
- [x] AutoSendGuard 强制 ACTIVE_AI、受限 Intent 转人工、Prompt 注入后端检测、WebSocket JWT 鉴权
- [x] Redis 锁 180 秒、有限重试、故障 fail-closed 并安全转人工
- [x] Ruff 与后端全量 37 tests 通过；pnpm lint、typecheck、test、Next.js production build 通过
- [x] Docker 四服务健康；浏览器完成登录、配置页、商品规则、模拟消息、结构化决策和工作台显示验收
- [x] 商品级自动发货：默认关闭、卡密加密库存、HTTPS 图片、付款校验、订单幂等、失败退库、Mock 付款测试台
- [x] 真实账号卖家侧同步：只保留本人发布商品与对应买家会话，排除购买侧商品/会话，回填对方昵称与头像
- [x] 宽松自动发送策略：普通低/中风险回复默认直发、兼容缺字段 JSON、降低置信度阈值，仅保留严重业务与人工接管边界
- [x] 买家新消息提醒音：WebSocket 精确触发、顶部开关、浏览器持久化选择、AI/人工消息静音
- [x] 实时商品与知识自动同步：连接后同步、陌生商品消息触发刷新、平台事实生成商品独立知识、购买侧继续隔离
- [x] 独立闲鱼监听服务：API 重启不断线、Redis Stream 持久事件、命令回执、消费幂等与真实连接诊断
- [x] 定向会话补拉：只补拉最近活跃卖家会话、平台限流指数退避，不再依赖高频全量会话同步
- [x] 恢复实测：API 停机期间事件入队，恢复后 `pending=0`、`lag=0`，监听器容器全程未重启
- [x] 平台消息隔离：评价提醒、平台推广和 reminder 卡片统一按系统消息保存，不进入 AI 回复链路
- [x] 人工确认的真实商品发布：专用扫码账号、图片上传、类目识别、逐件复核、每账号每分钟一次、审计与未知结果保护
