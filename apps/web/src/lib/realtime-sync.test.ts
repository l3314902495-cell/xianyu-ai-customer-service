import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { syncRealtimeEvent } from "./realtime-sync";

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("realtime cache synchronization", () => {
  it("writes a new message immediately and refreshes only related domains", () => {
    const client = queryClient();
    client.setQueryData(["messages", "conversation-1"], []);
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();

    syncRealtimeEvent(client, JSON.stringify({
      event: "new_message",
      payload: {
        conversation_id: "conversation-1",
        content: "还有吗？",
        sender_type: "customer",
      },
    }));

    expect(client.getQueryData<Array<{ content: string }>>(["messages", "conversation-1"]))
      .toMatchObject([{ content: "还有吗？" }]);
    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toContainEqual(["messages", "conversation-1"]);
    expect(keys).toContainEqual(["conversations"]);
    expect(keys).not.toContainEqual(["accounts"]);
    expect(keys).not.toContainEqual(["products"]);
  });

  it("patches read receipts without refetching unrelated data", () => {
    const client = queryClient();
    client.setQueryData(["messages", "conversation-1"], [{
      id: "message-1",
      reply_id: null,
      sender_type: "human",
      content: "你好",
      message_type: "text",
      sent: true,
      platform_read_state: "unread",
      platform_read_at: null,
      created_at: "2026-09-12T00:00:00.000Z",
    }]);
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();

    syncRealtimeEvent(client, JSON.stringify({
      event: "message_read",
      payload: {
        conversation_id: "conversation-1",
        message_ids: ["message-1"],
        read: true,
        read_at: "2026-09-12T00:01:00.000Z",
      },
    }));

    expect(client.getQueryData<Array<{ platform_read_state: string }>>(["messages", "conversation-1"]))
      .toMatchObject([{ platform_read_state: "read" }]);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("updates the global switch directly and ignores malformed events", () => {
    const client = queryClient();
    client.setQueryData(["switch"], { enabled: true });

    expect(syncRealtimeEvent(client, "not-json")).toBeNull();
    syncRealtimeEvent(client, JSON.stringify({
      event: "global_ai_switch",
      payload: { enabled: false, emergency: true },
    }));

    expect(client.getQueryData(["switch"])).toEqual({ enabled: false, emergency: true });
  });
});
