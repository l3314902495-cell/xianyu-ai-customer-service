import { describe, expect, it } from "vitest";

import { isCustomerMessageEvent, loadChatSoundPreference, saveChatSoundPreference } from "./notification-sound";

describe("chat notification sound", () => {
  it("only accepts new customer message events", () => {
    expect(
      isCustomerMessageEvent(
        JSON.stringify({ event: "new_message", payload: { sender_type: "customer" } }),
      ),
    ).toBe(true);
    expect(
      isCustomerMessageEvent(
        JSON.stringify({ event: "ai_reply", payload: { sender_type: "ai" } }),
      ),
    ).toBe(false);
    expect(isCustomerMessageEvent("not-json")).toBe(false);
  });
});

describe("chat sound preference", () => {
  it("falls back safely when browser storage is unavailable", () => {
    const unavailable = {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    };
    expect(loadChatSoundPreference(unavailable)).toBe(true);
    expect(() => saveChatSoundPreference(unavailable, false)).not.toThrow();
  });
});
