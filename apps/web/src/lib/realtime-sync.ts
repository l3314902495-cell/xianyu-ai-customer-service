import type { QueryClient, QueryKey } from "@tanstack/react-query";

type RealtimePayload = Record<string, unknown>;

interface RealtimeEnvelope {
  event: string;
  payload: RealtimePayload;
}

interface CachedMessage {
  id: string;
  reply_id: string | null;
  sender_type: "customer" | "ai" | "human" | "system";
  content: string;
  message_type: string;
  sent: boolean;
  platform_read_state: "read" | "unread" | "unknown" | "not_applicable";
  platform_read_at: string | null;
  created_at: string;
}

interface CachedConversation {
  id: string;
  [key: string]: unknown;
}

let transientMessageSequence = 0;

function parseEnvelope(raw: unknown): RealtimeEnvelope | null {
  if (typeof raw !== "string") return null;
  try {
    const value = JSON.parse(raw) as { event?: unknown; payload?: unknown };
    if (typeof value.event !== "string" || !value.payload || typeof value.payload !== "object") {
      return null;
    }
    return { event: value.event, payload: value.payload as RealtimePayload };
  } catch {
    return null;
  }
}

function conversationId(payload: RealtimePayload): string | null {
  return typeof payload.conversation_id === "string" && payload.conversation_id
    ? payload.conversation_id
    : null;
}

function invalidate(client: QueryClient, ...queryKeys: QueryKey[]): void {
  for (const queryKey of queryKeys) {
    void client.invalidateQueries({ queryKey });
  }
}

function patchConversationCaches(
  client: QueryClient,
  id: string,
  patch: RealtimePayload,
): void {
  client.setQueriesData<CachedConversation[]>({ queryKey: ["conversations"] }, (current) =>
    current?.map((item) => (item.id === id ? { ...item, ...patch, id } : item)),
  );
  client.setQueryData<CachedConversation>(["conversation", id], (current) =>
    current ? { ...current, ...patch, id } : current,
  );
}

function appendTransientMessage(
  client: QueryClient,
  payload: RealtimePayload,
  defaultSender?: CachedMessage["sender_type"],
): void {
  const id = conversationId(payload);
  const content = typeof payload.content === "string"
    ? payload.content
    : typeof payload.reply === "string"
      ? payload.reply
      : "";
  const rawSender = typeof payload.sender_type === "string" ? payload.sender_type : defaultSender;
  if (!id || !content || !["customer", "ai", "human", "system"].includes(rawSender ?? "")) return;

  const sender = rawSender as CachedMessage["sender_type"];
  const now = new Date();
  const message: CachedMessage = {
    id: `realtime-${id}-${now.getTime()}-${transientMessageSequence++}`,
    reply_id: null,
    sender_type: sender,
    content,
    message_type: sender === "system" ? "platform_event" : "text",
    sent: payload.sent !== false,
    platform_read_state:
      sender === "human" && payload.sent !== false ? "unknown" : "not_applicable",
    platform_read_at: null,
    created_at: now.toISOString(),
  };

  client.setQueryData<CachedMessage[]>(["messages", id], (current) => {
    if (!current) return current;
    const duplicate = current.some((item) =>
      item.sender_type === message.sender_type
      && item.content === message.content
      && Math.abs(now.getTime() - new Date(item.created_at).getTime()) < 15_000,
    );
    return duplicate ? current : [...current, message];
  });
}

function patchReadReceipts(client: QueryClient, payload: RealtimePayload): void {
  const id = conversationId(payload);
  const ids = Array.isArray(payload.message_ids)
    ? new Set(payload.message_ids.filter((item): item is string => typeof item === "string"))
    : new Set<string>();
  if (!id || ids.size === 0) return;
  const read = payload.read === true;
  const readAt = read && typeof payload.read_at === "string" ? payload.read_at : null;
  client.setQueryData<CachedMessage[]>(["messages", id], (current) =>
    current?.map((message) =>
      ids.has(message.id)
        ? {
            ...message,
            platform_read_state: read ? "read" : "unread",
            platform_read_at: readAt,
          }
        : message,
    ),
  );
}

/** Apply one server event to only the cache domains it can affect. */
export function syncRealtimeEvent(client: QueryClient, raw: unknown): RealtimeEnvelope | null {
  const envelope = parseEnvelope(raw);
  if (!envelope) return null;
  const { event, payload } = envelope;
  const id = conversationId(payload);

  switch (event) {
    case "new_message":
      appendTransientMessage(client, payload);
      if (id) invalidate(client, ["messages", id], ["conversation", id]);
      invalidate(client, ["conversations"], ["dashboard"], ["message-logs"]);
      break;
    case "human_reply":
      appendTransientMessage(client, payload, "human");
      if (id) invalidate(client, ["messages", id], ["conversation", id]);
      invalidate(client, ["conversations"], ["dashboard"], ["message-logs"]);
      if (payload.sent === false) invalidate(client, ["notifications"]);
      break;
    case "ai_reply":
      if (id) invalidate(client, ["messages", id], ["conversation", id]);
      invalidate(
        client,
        ["conversations"],
        ["dashboard"],
        ["ai-logs"],
        ["knowledge-gaps"],
        ["gaps"],
        ["notifications"],
      );
      break;
    case "ai_silenced":
      if (id) invalidate(client, ["conversation", id]);
      invalidate(client, ["conversations"], ["ai-logs"]);
      break;
    case "ai_suggestion_ignored":
      if (id) invalidate(client, ["messages", id]);
      break;
    case "message_read":
      patchReadReceipts(client, payload);
      break;
    case "conversation_status": {
      const statusId = typeof payload.id === "string" ? payload.id : id;
      if (!statusId) break;
      patchConversationCaches(client, statusId, payload);
      invalidate(client, ["conversations"], ["conversation", statusId], ["dashboard"]);
      break;
    }
    case "conversation_profile":
      if (!id) break;
      patchConversationCaches(client, id, payload);
      invalidate(client, ["conversations"], ["conversation", id]);
      break;
    case "global_ai_switch":
      if (typeof payload.enabled === "boolean") {
        client.setQueryData(["switch"], (current: unknown) => ({
          ...(current && typeof current === "object" ? current : {}),
          ...payload,
        }));
      } else {
        invalidate(client, ["switch"]);
      }
      break;
    case "all_conversations_takeover":
      invalidate(client, ["conversations"], ["conversation"], ["dashboard"], ["notifications"]);
      break;
    case "account_status":
      invalidate(client, ["accounts"], ["notifications"]);
      break;
    case "product_published":
    case "products_synced":
      invalidate(client, ["products"], ["accounts"], ["dashboard"]);
      break;
    case "products_ai_switch":
      invalidate(client, ["products"], ["conversations"], ["conversation"], ["dashboard"]);
      break;
    case "delivery.sent":
    case "delivery.failed":
      invalidate(
        client,
        ["delivery-products"],
        ["delivery-inventory"],
        ["delivery-records"],
        ["message-logs"],
        ["notifications"],
      );
      break;
    default:
      break;
  }

  return envelope;
}
