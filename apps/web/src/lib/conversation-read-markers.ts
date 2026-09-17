export interface ConversationReadMarker {
  updatedAt: string;
  unreadCount: number;
}

export interface ReadTrackableConversation {
  id: string;
  updated_at: string;
  unread_count: number;
}

export type ConversationReadMarkers = Record<string, ConversationReadMarker>;

export const CONVERSATION_READ_STORAGE_KEY = "xianyu-ai:conversation-read-markers:v1";

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function effectiveUnreadCount(
  conversation: ReadTrackableConversation,
  markers: ConversationReadMarkers,
): number {
  const serverCount = Math.max(0, conversation.unread_count || 0);
  const marker = markers[conversation.id];
  if (!marker) return serverCount;
  if (
    marker.updatedAt === conversation.updated_at
    || timestamp(marker.updatedAt) >= timestamp(conversation.updated_at)
  ) {
    return 0;
  }
  if (serverCount <= 0) return 0;
  return serverCount > marker.unreadCount ? serverCount - marker.unreadCount : serverCount;
}

export function markConversationsRead(
  markers: ConversationReadMarkers,
  conversations: ReadTrackableConversation[],
): ConversationReadMarkers {
  const next = { ...markers };
  for (const conversation of conversations) {
    next[conversation.id] = {
      updatedAt: conversation.updated_at,
      unreadCount: Math.max(0, conversation.unread_count || 0),
    };
  }
  return next;
}

export function loadConversationReadMarkers(storage: Pick<Storage, "getItem">): ConversationReadMarkers {
  try {
    const parsed = JSON.parse(storage.getItem(CONVERSATION_READ_STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as ConversationReadMarkers
      : {};
  } catch {
    return {};
  }
}

export function saveConversationReadMarkers(
  storage: Pick<Storage, "setItem">,
  markers: ConversationReadMarkers,
): void {
  try {
    storage.setItem(CONVERSATION_READ_STORAGE_KEY, JSON.stringify(markers));
  } catch {
    // Local-only read state still works for the current tab if storage is unavailable.
  }
}
