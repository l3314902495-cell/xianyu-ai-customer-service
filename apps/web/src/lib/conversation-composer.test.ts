import { describe, expect, it } from "vitest";

import { shouldSendComposerMessage } from "./conversation-composer";

describe("shouldSendComposerMessage", () => {
  it("sends on Enter", () => {
    expect(shouldSendComposerMessage({ key: "Enter", altKey: false, isComposing: false })).toBe(true);
  });

  it("keeps Alt+Enter for a newline", () => {
    expect(shouldSendComposerMessage({ key: "Enter", altKey: true, isComposing: false })).toBe(false);
  });

  it("does not send while an IME composition is active", () => {
    expect(shouldSendComposerMessage({ key: "Enter", altKey: false, isComposing: true })).toBe(false);
    expect(shouldSendComposerMessage({ key: "Enter", altKey: false, isComposing: false, keyCode: 229 })).toBe(false);
  });

  it("ignores non-Enter keys", () => {
    expect(shouldSendComposerMessage({ key: "a", altKey: false, isComposing: false })).toBe(false);
  });
});
