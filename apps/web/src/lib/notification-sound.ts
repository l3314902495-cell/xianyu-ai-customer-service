export const CHAT_SOUND_STORAGE_KEY = "xianyu-chat-sound-enabled";

export function loadChatSoundPreference(storage: Pick<Storage, "getItem">): boolean {
  try {
    return storage.getItem(CHAT_SOUND_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

export function saveChatSoundPreference(
  storage: Pick<Storage, "setItem">,
  enabled: boolean,
): void {
  try {
    storage.setItem(CHAT_SOUND_STORAGE_KEY, String(enabled));
  } catch {
    // Keep the preference for this tab even if persistent storage is unavailable.
  }
}

export function isCustomerMessageEvent(raw: string): boolean {
  try {
    const message = JSON.parse(raw) as {
      event?: string;
      payload?: { sender_type?: string };
    };
    return message.event === "new_message" && message.payload?.sender_type === "customer";
  } catch {
    return false;
  }
}

export function playChatNotificationSound(): void {
  if (typeof window === "undefined") return;
  const AudioContextClass = window.AudioContext;
  if (!AudioContextClass) return;

  let context: AudioContext;
  try {
    context = new AudioContextClass();
  } catch {
    return;
  }
  const start = () => {
    const gain = context.createGain();
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.16, context.currentTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.42);
    gain.connect(context.destination);

    for (const [frequency, delay] of [[660, 0], [880, 0.1]] as const) {
      const oscillator = context.createOscillator();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(frequency, context.currentTime + delay);
      oscillator.connect(gain);
      oscillator.start(context.currentTime + delay);
      oscillator.stop(context.currentTime + delay + 0.24);
    }
    window.setTimeout(() => void context.close(), 650);
  };

  if (context.state === "suspended") {
    void context.resume().then(start).catch(() => void context.close());
  } else {
    start();
  }
}
