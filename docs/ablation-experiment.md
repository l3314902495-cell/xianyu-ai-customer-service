# 工程消融实验记录

日期：2026-09-03

## 目标

本轮消融只减少没有运行价值的目录、配置和前端状态，不改变闲鱼消息接收、AI 决策、知识隔离、自动发送和人工接管等核心业务行为。

判断标准不是“文件越少越好”，而是：删除后功能边界仍清晰、测试仍通过、运行状态更少、维护成本更低。

## 本轮删除与简化

- 删除仅含说明文件、没有运行代码的 `packages/ai`、`packages/database`、`packages/xianyu-adapter` 占位目录。
- 删除未被引用的 `packages/shared` 工作区包及其空导出。
- 从 pnpm workspace 和 Next.js 配置中移除已经不存在的共享包引用。
- 删除未被调用的 `LoadingBlock` 组件。
- 按当前“仅做电脑端”的产品范围，删除移动侧栏的 Zustand 状态、关闭动作、Escape/路由/滚动锁副作用、遮罩层和移动端专用样式。
- 删除登录页的移动端专用品牌分支。
- 更新 `DESIGN.md` 与 `UX-CONTRACT.md`，把支持范围明确为桌面和笔记本电脑。

## 有意保留的核心边界

以下结构不是多余抽象，本轮明确保留：

- `XianyuAdapter`：隔离 Mock、实验性网页接入与未来合规接入方式。
- `LLMProvider`：避免业务逻辑绑定单一模型服务商。
- `PromptBuilder`：集中拼装全局规则、商品 Prompt、商品知识、FAQ 和聊天上下文。
- 商品作用域与 repository 边界：防止不同商品知识串库。
- Redis debounce、会话锁和幂等：防止连续消息触发多次回复或重复发送。
- 独立 listener/runtime 与 Redis Stream：避免 API 重启导致实时监听链路直接中断。
- 后端 AutoSendGuard 与全局停止屏障：模型只能建议发送，最终权限仍在后端。

## 结果

- workspace 中不再存在无运行内容的共享包 importer。
- 前端不再维护无法从当前产品进入的移动导航状态和相关副作用。
- 桌面端路由、页面、接口调用和业务组件保持不变。
- 源码中已经没有被删除符号和包名的残留引用。

## 验证

- 后端 Ruff：通过。
- 后端 pytest：93 项通过。
- 前端 ESLint：通过。
- TypeScript strict typecheck：通过。
- 前端 Vitest：4 项通过。
- Next.js production build：通过。
- Premium UI strict audit：0 warning，0 violation。
- `DESIGN.md` lint：0 error，0 warning。

验证期间出现的依赖安装缓慢并不像硬盘硬件故障：磁盘活动与队列很低，Node/pnpm 进程持续占用多核 CPU；使用 npm 进行相同依赖安装约一分钟完成。当前更符合 pnpm 链接/复制路径与 Windows 权限或安全软件交互异常。

## 环境限制

- 当前 Shell 找不到 Docker CLI，因此本轮没有重新构建正在运行的 Docker 容器；`localhost:3000` 与 `localhost:8000/health` 当时仍可访问。
- 最新构建在 Shell 中可启动并返回 HTTP 200，但应用内浏览器无法访问该临时端口，因此没有把该项记录为浏览器视觉验收。

## 下一轮候选（尚未执行）

- 给 `xianyu_runtime.py` 做职责与变更频率统计，只有在测试能够覆盖拆分边界时再做小步拆分。
- 统计重复的页面请求状态和提示反馈，再决定是否合并组件；不以“统一组件”为目的强行抽象。
- 为实时消息链路建立可观测指标后，再对轮询、定向补拉和 Stream 消费做对照实验。

下一轮仍不应删除 Adapter、Provider、商品知识隔离、Redis 幂等/锁或后端发送守卫。
