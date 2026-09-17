# Third-Party Notices

## fancyboi999/goofish-cli

- 项目：https://github.com/fancyboi999/goofish-cli
- 版本/审计基线：0.3.0（2026-08-19 审计）
- 许可证：Apache License 2.0
- 使用范围：`apps/api/app/services/xianyu_protocol.py` 的会话、MTOP、WebSocket 文本收发流程，以及 `apps/api/app/services/xianyu_publish.py` 的图片上传、类目识别和单件发布载荷，参考其实现并重写裁剪。
- 修改说明：移除 CLI、MCP、浏览器 Cookie 抽取、Playwright、Cookie 文件与自动刷新；加入多账号隔离、数据库审计、前端逐件复核、幂等保护、每账号每分钟一次以及未知结果阻断。保留遇验证或风控立即停止的边界。

## dameng2026/xianyu-pilot

- 项目：https://github.com/dameng2026/xianyu-pilot
- 许可证：Apache License 2.0
- 使用范围：`apps/api/app/services/xianyu_qr.py` 的网页二维码登录流程参考其实现并重写裁剪。
- 修改说明：Cookie 仅在后端内部消费并加密保存；移除滑块、验证码和自动验证逻辑；要求验证时立即停止。
- 自动发货使用范围：参考其付款事件正负关键词校验、商品级规则、幂等退库策略及图片消息数据结构，在 `auto_delivery.py`、`xianyu_protocol.py` 中重新实现。
- 自动发货修改说明：数据库改为 PostgreSQL/SQLAlchemy；默认全商品关闭；仅 Mock 付款模拟器可人工触发；真实事件必须同时具有系统消息类型、明确付款状态、订单 ID、商品 ID 和买家 ID。

## 包管理器依赖

项目通过 Python 与 npm/pnpm 包管理器使用 FastAPI、SQLAlchemy、Next.js、React、TanStack Query、Zustand、Tailwind CSS 等第三方包。各包版权和许可证归原作者所有，准确版本由 `pyproject.toml`、`package.json` 和锁文件记录；发布镜像不改变其原始许可证。

## 明确排除

- `shaxiu/XianyuAutoAgent`（GPL-3.0）：未复制或链接其源码。
- `cv-cat/XianYuApis`（未发现明确许可证）：未复制或链接其源码。
- 验证码/滑块处理、浏览器 Cookie 抽取、密码登录、自动化风控规避：未引入。
