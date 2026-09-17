# 架构与安全边界

```text
买家消息 / MockXianyuAdapter
  -> MessageProcessor（空消息/幂等）
  -> Redis Debounce（1500ms）
  -> Redis conversation lock
  -> ProductKnowledgeRepository（强制 product_id）
  -> PromptBuilder（全局 + 商品 + 知识 + FAQ + 最近历史）
  -> LLMProvider（Mock / OpenAI-compatible）
  -> Pydantic AIReplyDecision
  -> AutoSendGuard（全局/账号/商品/会话/风险/知识）
  -> Adapter send / 转人工
  -> Message、AIReplyLog、KnowledgeGap
  -> WebSocket /ws
```

## 权限边界

- LLM 只能提出 `should_send`，不能直接调用平台 Adapter。
- `AutoSendGuard` 是唯一自动发送授权点。
- 退款、赔偿、投诉、修改订单、修改地址、砍价不会执行任何业务动作。
- 人工接管只能由管理员开启/结束，AI 不会自行恢复。
- API Key 使用基于服务端 `JWT_SECRET` 派生的 Fernet key 加密，API 只返回脱敏值。
- `RealXianyuAdapter` 没有 URL、Cookie、Token、签名或私有协议实现。
