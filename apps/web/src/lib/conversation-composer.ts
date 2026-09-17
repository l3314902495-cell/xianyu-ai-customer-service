interface ComposerKeyEvent {
  key: string;
  altKey: boolean;
  isComposing: boolean;
  keyCode?: number;
}

export function shouldSendComposerMessage(event: ComposerKeyEvent) {
  return event.key === "Enter" && !event.altKey && !event.isComposing && event.keyCode !== 229;
}
