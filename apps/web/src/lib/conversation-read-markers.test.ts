import { describe, expect, it } from "vitest";

import {
  effectiveUnreadCount,
  loadConversationReadMarkers,
  markConversationsRead,
  saveConversationReadMarkers,
} from "./conversation-read-markers";

const conversation = {
  id: "conversation-1",
  updated_at: "2026-09-09T10:00:00Z",
  unread_count: 4,
};

describe("conversation read markers", () => {
  it("clears only the local unread presentation", () => {
    const markers = markConversationsRead({}, [conversation]);

    expect(effectiveUnreadCount(conversation, markers)).toBe(0);
    expect(conversation.unread_count).toBe(4);
  });

  it("shows only messages received after the local marker", () => {
    const markers = markConversationsRead({}, [conversation]);

    expect(effectiveUnreadCount({
      ...conversation,
      updated_at: "2026-09-09T10:01:00Z",
      unread_count: 6,
    }, markers)).toBe(2);
  });

  it("round-trips markers through browser storage", () => {
    let value = "";
    const storage = {
      getItem: () => value,
      setItem: (_key: string, next: string) => { value = next; },
    };
    const markers = markConversationsRead({}, [conversation]);

    saveConversationReadMarkers(storage, markers);

    expect(loadConversationReadMarkers(storage)).toEqual(markers);
  });
});
