# 闲鱼实时监听可靠性

## 运行结构

Docker 环境将闲鱼平台连接与 FastAPI 拆为两个独立进程：

```text
闲鱼长连接
  -> xianyu-listener
  -> Redis Stream (xianyu:events)
  -> FastAPI consumer group (xianyu-api)
  -> PostgreSQL / AI 回复 / 后台 WebSocket
```

API 发消息、图片、连接、断开和手工同步时，通过 `xianyu:commands` 命令流请求监听器执行。监听器返回一次性回执，API 不再建立第二条平台连接。

## 可靠性机制

- `xianyu-listener` 独立重启策略，API 或 Web 重启不会中断平台监听。
- Redis Stream 使用消费组；业务处理完成后才 ACK，API 停机期间收到的事件会在恢复后继续消费。
- 数据库 `external_message_id` 唯一约束提供最终幂等，队列重投不会重复触发 AI。
- WebSocket 协议 Ping/Pong、应用心跳、90 秒无平台帧重连和 45 分钟主动轮换共同处理假连接。
- 历史补拉只检查数据库中最近活跃的 3 个卖家侧会话，不请求完整会话列表；被限流后指数退避。
- 账号页面显示监听服务、平台长连接、连接持续时间、最近平台帧和最近真实消息时间。

## Docker 服务

```bash
docker compose ps
docker compose logs -f xianyu-listener
docker compose restart xianyu-listener
```

正常运行时应有五个服务：`postgres`、`redis`、`api`、`xianyu-listener`、`web`。

## 环境模式

- Docker API：`XIANYU_RUNTIME_MODE=api`
- Docker Listener：`XIANYU_RUNTIME_MODE=listener`
- 直接本地开发：默认 `XIANYU_RUNTIME_MODE=embedded`

本地拆分运行时，需要分别启动 `uvicorn app.main:app` 和 `python -m app.listener_main`，并将两个进程配置为对应模式。

## 平台边界

该机制解决系统进程重启、半开连接、事件积压和重复消费问题，但不能消除平台主动限流、登录失效或协议调整。平台要求验证时系统仍会停止自动发送并要求人工重新登录，不会绕过验证与风控。
