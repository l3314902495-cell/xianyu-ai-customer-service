const HIDDEN_CHAT_MESSAGE_TYPES = new Set([
  "ai_suggestion_ignored",
  "ai_suggestion_sent",
  "platform_event",
]);

export function isVisibleChatMessage(messageType: string): boolean {
  return !HIDDEN_CHAT_MESSAGE_TYPES.has(messageType);
}

interface TimelineMessage {
  id: string;
  sender_type: "customer" | "ai" | "human" | "system";
  content: string;
  message_type: string;
  sent: boolean;
  created_at: string;
}

export interface ScrollPosition {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}

export function isNearConversationBottom(position: ScrollPosition, threshold = 80): boolean {
  return position.scrollHeight - position.scrollTop - position.clientHeight <= threshold;
}

function outboundPriority(message: TimelineMessage): number {
  if (message.sender_type === "ai" && message.sent) return 4;
  if (message.sender_type === "human" && message.sent) return 3;
  if (message.sender_type === "system") return 1;
  return 0;
}

/**
 * Hide historical platform echoes of an outbound reply. The platform may
 * return the same sent text with another id and even a reminder-shaped sender.
 * Customer messages are never collapsed, including repeated short messages.
 */
export function visibleConversationMessages<T extends TimelineMessage>(messages: T[]): T[] {
  const visible: T[] = [];
  for (const message of messages) {
    if (!isVisibleChatMessage(message.message_type)) continue;
    if (message.sender_type === "customer") {
      visible.push(message);
      continue;
    }
    const createdAt = new Date(message.created_at).getTime();
    const duplicateIndex = visible.findIndex((candidate) => {
      if (candidate.sender_type === "customer" || candidate.content !== message.content) return false;
      const candidateAt = new Date(candidate.created_at).getTime();
      return Number.isFinite(createdAt) && Number.isFinite(candidateAt) && Math.abs(createdAt - candidateAt) <= 120_000;
    });
    if (duplicateIndex === -1) {
      visible.push(message);
    } else if (outboundPriority(message) > outboundPriority(visible[duplicateIndex])) {
      visible[duplicateIndex] = message;
    }
  }
  return visible;
}
