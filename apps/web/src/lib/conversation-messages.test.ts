import { describe, expect, it } from "vitest";

import { isNearConversationBottom, isVisibleChatMessage, visibleConversationMessages } from "./conversation-messages";

describe("conversation scroll position", () => {
  it("keeps automatic scrolling only near the latest message", () => {
    expect(isNearConversationBottom({ scrollHeight: 1000, scrollTop: 620, clientHeight: 300 })).toBe(true);
    expect(isNearConversationBottom({ scrollHeight: 1000, scrollTop: 400, clientHeight: 300 })).toBe(false);
  });
});

describe("conversation message visibility", () => {
  it("hides handled AI suggestions from the chat timeline", () => {
    expect(isVisibleChatMessage("ai_suggestion_ignored")).toBe(false);
    expect(isVisibleChatMessage("ai_suggestion_sent")).toBe(false);
    expect(isVisibleChatMessage("platform_event")).toBe(false);
  });

  it("keeps ordinary and pending suggestion messages visible", () => {
    expect(isVisibleChatMessage("text")).toBe(true);
    expect(isVisibleChatMessage("image")).toBe(true);
    expect(isVisibleChatMessage("ai_suggestion")).toBe(true);
  });
});

describe("conversation message de-duplication", () => {
  const base = {
    message_type: "text",
    sent: true,
    created_at: "2026-09-03T12:43:00Z",
  } as const;

  it("keeps the sent AI row and hides its platform system echo", () => {
    const result = visibleConversationMessages([
      { ...base, id: "system", sender_type: "system", content: "可以直接拍下。" },
      { ...base, id: "ai", sender_type: "ai", content: "可以直接拍下。" },
    ]);
    expect(result.map((message) => message.id)).toEqual(["ai"]);
  });

  it("keeps repeated customer messages", () => {
    const result = visibleConversationMessages([
      { ...base, id: "buyer-1", sender_type: "customer", content: "在吗" },
      { ...base, id: "buyer-2", sender_type: "customer", content: "在吗" },
    ]);
    expect(result).toHaveLength(2);
  });
});
