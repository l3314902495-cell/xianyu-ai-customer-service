"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Bot,
  Check,
  CheckCheck,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Loader2,
  MessageCircle,
  Package,
  PencilLine,
  RotateCcw,
  Send,
  UserRound,
  WandSparkles,
  ArrowDown,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { BuyerAvatar } from "@/components/buyer-avatar";
import { useToast } from "@/components/toast";
import { CursorPage, request } from "@/lib/api";
import {
  CONVERSATION_READ_STORAGE_KEY,
  ConversationReadMarkers,
  effectiveUnreadCount,
  loadConversationReadMarkers,
  markConversationsRead,
  saveConversationReadMarkers,
} from "@/lib/conversation-read-markers";
import { shouldSendComposerMessage } from "@/lib/conversation-composer";
import { isNearConversationBottom, visibleConversationMessages } from "@/lib/conversation-messages";
import { useUI } from "@/lib/store";
import { useConfirm } from "@/components/confirm-dialog";

type ConversationStatus = "ACTIVE_AI" | "NEEDS_HUMAN" | "ACTIVE_HUMAN" | "CLOSED";
type ConversationChip = "all" | Exclude<ConversationStatus, "CLOSED">;
type SenderType = "customer" | "ai" | "human" | "system";

interface ConversationSummary {
  id: string;
  buyer_nickname: string;
  buyer_avatar: string | null;
  external_conversation_id: string;
  status: ConversationStatus;
  ai_enabled: boolean;
  human_takeover: boolean;
  needs_human: boolean;
  unread_count: number;
  last_intent: string | null;
  last_confidence: number | null;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  updated_at: string;
}

interface ConversationDetail extends ConversationSummary {
  current_model: string;
  product: {
    id: string;
    external_product_id: string;
    name: string;
    price: number;
    image_url: string | null;
    ai_enabled: boolean;
    knowledge_count: number;
  } | null;
}

interface ConversationMessage {
  id: string;
  reply_id: string | null;
  sender_type: SenderType;
  content: string;
  message_type: string;
  sent: boolean;
  platform_read_state: "read" | "unread" | "unknown" | "not_applicable";
  platform_read_at: string | null;
  created_at: string;
}

interface ReplyVariables {
  content: string;
  suggestionId?: string;
}

const chipOptions: Array<{ value: ConversationChip; label: string }> = [
  { value: "all", label: "全部在线" },
  { value: "ACTIVE_AI", label: "AI 托管" },
  { value: "NEEDS_HUMAN", label: "待人工" },
  { value: "ACTIVE_HUMAN", label: "人工处理中" },
];

const statusPresentation: Record<ConversationStatus, { label: string; badge: string }> = {
  ACTIVE_AI: { label: "AI 托管", badge: "badge-green" },
  NEEDS_HUMAN: { label: "待人工", badge: "badge-amber" },
  ACTIVE_HUMAN: { label: "人工处理中", badge: "badge-blue" },
  CLOSED: { label: "已结束", badge: "" },
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试";
}

function formatMessageTime(value: string) {
  const date = new Date(value);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return new Intl.DateTimeFormat("zh-CN", {
    ...(sameDay ? {} : { month: "2-digit", day: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function ConversationsView({ filter }: { filter?: string }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const { realtimeConnected, selectedConversation, selectConversation } = useUI();
  const fallbackRefreshInterval = realtimeConnected ? 30_000 : 2_000;
  const [chip, setChip] = useState<ConversationChip>("all");
  const [draft, setDraft] = useState("");
  const [editingSuggestionId, setEditingSuggestionId] = useState<string | null>(null);
  const [hasNewMessagesBelow, setHasNewMessagesBelow] = useState(false);
  const [readMarkers, setReadMarkers] = useState<ConversationReadMarkers>({});
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const previousMessageCountRef = useRef(0);
  const previousConversationRef = useRef<string | null>(null);

  useEffect(() => {
    setReadMarkers(loadConversationReadMarkers(window.localStorage));
    const syncMarkers = (event: StorageEvent) => {
      if (event.key === CONVERSATION_READ_STORAGE_KEY) {
        setReadMarkers(loadConversationReadMarkers(window.localStorage));
      }
    };
    window.addEventListener("storage", syncMarkers);
    return () => window.removeEventListener("storage", syncMarkers);
  }, []);

  const pageFilter = filter === "CLOSED" ? "CLOSED" : filter === "needs_human" ? "needs_human" : "active";
  const apiFilter = pageFilter === "active" && chip !== "all" ? chip : pageFilter;

  const conversations = useInfiniteQuery({
    queryKey: ["conversations", apiFilter],
    queryFn: ({ pageParam }) => request<CursorPage<ConversationSummary>>(
      `/api/conversations?status=${apiFilter}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
    ),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor || undefined,
    refetchInterval: fallbackRefreshInterval,
  });
  const conversationItems = useMemo(
    () => conversations.data?.pages.flatMap((page) => page.items) ?? [],
    [conversations.data],
  );

  const activeConversationId = useMemo(() => {
    if (!conversationItems.length) return null;
    return conversationItems.some((item) => item.id === selectedConversation)
      ? selectedConversation
      : conversationItems[0].id;
  }, [conversationItems, selectedConversation]);

  useEffect(() => {
    if (activeConversationId && activeConversationId !== selectedConversation) {
      selectConversation(activeConversationId);
    }
  }, [activeConversationId, selectConversation, selectedConversation]);

  useEffect(() => {
    setDraft("");
    setEditingSuggestionId(null);
    setHasNewMessagesBelow(false);
    nearBottomRef.current = true;
  }, [activeConversationId]);

  const detail = useQuery({
    queryKey: ["conversation", activeConversationId],
    queryFn: () => request<ConversationDetail>(`/api/conversations/${activeConversationId}`),
    enabled: Boolean(activeConversationId),
    refetchInterval: fallbackRefreshInterval,
  });
  const messages = useInfiniteQuery({
    queryKey: ["messages", activeConversationId],
    queryFn: ({ pageParam }) => request<CursorPage<ConversationMessage>>(
      `/api/conversations/${activeConversationId}/messages${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`,
    ),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor || undefined,
    enabled: Boolean(activeConversationId),
    refetchInterval: fallbackRefreshInterval,
  });
  const messageItems = useMemo(
    () => [...(messages.data?.pages ?? [])].reverse().flatMap((page) => page.items),
    [messages.data],
  );
  const visibleMessages = useMemo(
    () => visibleConversationMessages(messageItems),
    [messageItems],
  );

  const selectedSummary = conversationItems.find((item) => item.id === activeConversationId);
  useEffect(() => {
    if (!selectedSummary || effectiveUnreadCount(selectedSummary, readMarkers) === 0) return;
    setReadMarkers((current) => {
      const next = markConversationsRead(current, [selectedSummary]);
      saveConversationReadMarkers(window.localStorage, next);
      return next;
    });
  }, [readMarkers, selectedSummary]);

  const localUnreadTotal = useMemo(
    () => conversationItems.reduce(
      (total, conversation) => total + effectiveUnreadCount(conversation, readMarkers),
      0,
    ),
    [conversationItems, readMarkers],
  );

  function markAllRead() {
    if (!conversationItems.length || localUnreadTotal === 0) return;
    setReadMarkers((current) => {
      const next = markConversationsRead(current, conversationItems);
      saveConversationReadMarkers(window.localStorage, next);
      return next;
    });
    toast({
      title: "本页会话已全部标记为已读",
      description: "仅清除当前浏览器中的未读提示，不会修改闲鱼上的状态。",
      tone: "success",
    });
  }

  useEffect(() => {
    const conversationChanged = previousConversationRef.current !== activeConversationId;
    const messageCount = visibleMessages.length;
    const receivedNewMessage = messageCount > previousMessageCountRef.current;

    if (conversationChanged || nearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ block: "end" });
      setHasNewMessagesBelow(false);
    } else if (receivedNewMessage) {
      setHasNewMessagesBelow(true);
    }

    previousConversationRef.current = activeConversationId;
    previousMessageCountRef.current = messageCount;
  }, [activeConversationId, visibleMessages.length]);

  function handleChatScroll() {
    const scroller = chatScrollRef.current;
    if (!scroller) return;
    nearBottomRef.current = isNearConversationBottom(scroller);
    if (nearBottomRef.current) setHasNewMessagesBelow(false);
  }

  function jumpToLatest() {
    nearBottomRef.current = true;
    messagesEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    setHasNewMessagesBelow(false);
  }

  const refreshConversation = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["conversation"] }),
      queryClient.invalidateQueries({ queryKey: ["conversations"] }),
      queryClient.invalidateQueries({ queryKey: ["messages"] }),
    ]);
  };

  const statusAction = useMutation({
    mutationFn: (action: "takeover" | "resume-ai" | "close" | "reopen") =>
      request(`/api/conversations/${activeConversationId}/${action}`, { method: "POST" }),
    onSuccess: refreshConversation,
  });

  const replyAction = useMutation({
    mutationFn: async ({ content, suggestionId }: ReplyVariables) => {
      const result = await request(`/api/conversations/${activeConversationId}/reply`, {
        method: "POST",
        body: JSON.stringify({ content, suggestion_id: suggestionId || null }),
      });
      return result;
    },
    onSuccess: async () => {
      setDraft("");
      setEditingSuggestionId(null);
      await refreshConversation();
    },
  });

  const ignoreAction = useMutation({
    mutationFn: (messageId: string) =>
      request(`/api/conversations/${activeConversationId}/messages/${messageId}/ignore`, {
        method: "POST",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages", activeConversationId] }),
  });

  function submitReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || !activeConversationId || detail.data?.status === "CLOSED") return;
    replyAction.mutate({ content, suggestionId: editingSuggestionId || undefined });
  }

  function editSuggestion(content: string, messageId: string) {
    setDraft(content);
    setEditingSuggestionId(messageId);
    requestAnimationFrame(() => editorRef.current?.focus());
  }

  async function closeConversation() {
    const accepted = await confirm({
      title: "结束当前会话？",
      description: "结束后将停止这个会话的 AI 自动回复。历史消息仍会保留，之后也可以重新开启。",
      confirmLabel: "结束会话",
      tone: "danger",
    });
    if (accepted) statusAction.mutate("close");
  }

  const mutationError = statusAction.error || replyAction.error || ignoreAction.error;
  const title = pageFilter === "needs_human" ? "待人工处理" : pageFilter === "CLOSED" ? "历史会话" : "在线会话";

  return (
    <div className="conversation-workspace">
      <section className="conversation-queue flex min-h-0 flex-col border-r">
        <div className="conversation-queue-toolbar border-b p-4">
          <div className="flex items-center justify-between">
            <h1 className="font-bold">{title}</h1>
            {!conversations.isLoading && (
              <button
                type="button"
                className="btn btn-sm"
                disabled={localUnreadTotal === 0}
                onClick={markAllRead}
                title="仅清除当前浏览器中的未读提示，不会修改闲鱼状态"
              >
                <CheckCheck size={14} />全部已读
                {localUnreadTotal > 0 && <span className="font-mono text-[10px]">{localUnreadTotal}</span>}
              </button>
            )}
          </div>
          {pageFilter === "active" && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {chipOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setChip(option.value)}
                  className={`conversation-filter-chip badge border ${chip === option.value ? "is-selected" : ""}`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {conversations.isLoading && <ListLoading />}
          {conversations.isError && (
            <QueryError message={errorText(conversations.error)} retry={() => conversations.refetch()} />
          )}
          {!conversations.isLoading && !conversations.isError && conversationItems.map((conversation) => {
            const status = statusPresentation[conversation.status];
            const unreadCount = effectiveUnreadCount(conversation, readMarkers);
            return (
              <button
                key={conversation.id}
                type="button"
                onClick={() => selectConversation(conversation.id)}
                className={`conversation-queue-item ${activeConversationId === conversation.id ? "is-selected" : ""}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <BuyerAvatar src={conversation.buyer_avatar} name={conversation.buyer_nickname} size="sm" />
                    <b className="truncate text-sm">{conversation.buyer_nickname}</b>
                  </div>
                  <span className="shrink-0 text-[10px] text-slate-400">{formatMessageTime(conversation.updated_at)}</span>
                </div>
                <p className="mt-2 truncate text-xs text-slate-500">
                  {conversation.last_intent ? `意图：${conversation.last_intent}` : "等待新消息"}
                </p>
                <div className="mt-2 flex items-center gap-1.5">
                  <span className={`badge ${status.badge}`}>{status.label}</span>
                  {conversation.risk_level !== "LOW" && <span className="badge badge-red">{conversation.risk_level}</span>}
                  {unreadCount > 0 && (
                    <span
                      className="conversation-unread ml-auto grid min-h-5 min-w-5 place-items-center rounded-full px-1 text-[10px] font-bold"
                      aria-label={`${unreadCount} 条本地未读消息`}
                    >
                      {unreadCount > 99 ? "99+" : unreadCount}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
          {!conversations.isLoading && !conversations.isError && !conversationItems.length && (
            <div className="p-10 text-center text-sm text-slate-400">没有符合条件的会话</div>
          )}
          {conversations.hasNextPage && (
            <div className="p-3 text-center">
              <button className="btn btn-sm" type="button" disabled={conversations.isFetchingNextPage} onClick={() => conversations.fetchNextPage()}>
                {conversations.isFetchingNextPage ? "正在加载…" : "加载更多会话"}
              </button>
            </div>
          )}
        </div>
      </section>

      <section className="conversation-chat relative flex min-h-0 min-w-0 flex-col">
        <div className="conversation-chat-header flex h-16 shrink-0 items-center justify-between border-b px-5">
          <div className="flex min-w-0 items-center gap-3">
            <BuyerAvatar src={detail.data?.buyer_avatar} name={detail.data?.buyer_nickname} />
            <div className="min-w-0"><b className="block truncate">{detail.data?.buyer_nickname || "选择会话"}</b>
            <p className="truncate text-xs text-slate-500">{detail.data?.external_conversation_id || "从左侧选择要处理的买家会话"}</p></div>
          </div>
          {detail.data && (
            <div className="flex items-center gap-2">
              {detail.data.status === "CLOSED" ? (
                <button
                  className="btn btn-primary"
                  disabled={statusAction.isPending}
                  onClick={() => statusAction.mutate("reopen")}
                >
                  {statusAction.isPending ? <Loader2 className="animate-spin" size={15} /> : <RotateCcw size={15} />}
                  重新开启
                </button>
              ) : (
                <>
                  <button
                    className={`btn ${detail.data.human_takeover ? "btn-warning" : "btn-primary"}`}
                    disabled={statusAction.isPending}
                    onClick={() => statusAction.mutate(detail.data.human_takeover ? "resume-ai" : "takeover")}
                  >
                    {statusAction.isPending ? <Loader2 className="animate-spin" size={15} /> : detail.data.human_takeover ? <Bot size={15} /> : <UserRound size={15} />}
                    {detail.data.human_takeover ? "恢复 AI 托管" : "人工接管"}
                  </button>
                  <button
                    className="btn"
                    disabled={statusAction.isPending}
                    onClick={closeConversation}
                  >
                    <XCircle size={15} />结束会话
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {mutationError && (
          <div className="flex items-center gap-2 border-b border-red-200 bg-red-50 px-5 py-2 text-xs text-red-700">
            <AlertCircle size={14} />{errorText(mutationError)}
          </div>
        )}

        <div ref={chatScrollRef} onScroll={handleChatScroll} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-6">
          {(detail.isLoading || messages.isLoading) && <MessageLoading />}
          {(detail.isError || messages.isError) && (
            <QueryError
              message={errorText(detail.error || messages.error)}
              retry={() => {
                void detail.refetch();
                void messages.refetch();
              }}
            />
          )}
          {messages.hasNextPage && (
            <div className="text-center">
              <button className="btn btn-sm" type="button" disabled={messages.isFetchingNextPage} onClick={() => messages.fetchNextPage()}>
                {messages.isFetchingNextPage ? "正在加载…" : "加载更早消息"}
              </button>
            </div>
          )}
          {!messages.isLoading && !messages.isError && visibleMessages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              busy={replyAction.isPending || ignoreAction.isPending}
              onSend={() => replyAction.mutate({ content: message.content, suggestionId: message.id })}
              onEdit={() => editSuggestion(message.content, message.id)}
              onIgnore={() => ignoreAction.mutate(message.id)}
            />
          ))}
          {!activeConversationId && !conversations.isLoading && (
            <div className="grid h-full place-items-center text-sm text-slate-400">选择左侧会话查看消息</div>
          )}
          {activeConversationId && !messages.isLoading && !messages.isError && !visibleMessages.length && (
            <div className="grid h-full place-items-center text-sm text-slate-400">这个会话还没有消息</div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {hasNewMessagesBelow && (
          <button type="button" className="jump-to-latest btn btn-primary" onClick={jumpToLatest}>
            <ArrowDown size={14} />查看新消息
          </button>
        )}

        {activeConversationId && (
          <form onSubmit={submitReply} className="conversation-composer shrink-0 border-t p-4" noValidate>
            <textarea
              ref={editorRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (!shouldSendComposerMessage({
                  key: event.key,
                  altKey: event.altKey,
                  isComposing: event.nativeEvent.isComposing,
                  keyCode: event.nativeEvent.keyCode,
                })) return;

                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }}
              aria-describedby="conversation-composer-shortcut"
              className="input min-h-20 resize-none"
              placeholder={detail.data?.status === "CLOSED" ? "会话已结束，请先重新开启" : "输入人工回复……发送后会自动保持人工接管"}
              disabled={detail.data?.status === "CLOSED" || replyAction.isPending}
            />
            <div className="mt-2 flex items-center justify-between">
              <span id="conversation-composer-shortcut" className="text-xs text-slate-400">回车发送 · Alt + 回车换行</span>
              <button className="btn btn-primary" disabled={!draft.trim() || detail.data?.status === "CLOSED" || replyAction.isPending}>
                {replyAction.isPending ? <Loader2 className="animate-spin" size={15} /> : <Send size={15} />}
                发送
              </button>
            </div>
          </form>
        )}
      </section>

      <aside className="conversation-context min-h-0 overflow-y-auto overscroll-contain border-l p-5">
        {detail.isLoading && <div className="h-28 animate-pulse rounded-xl bg-slate-100" />}
        {detail.data?.product ? (
          <>
            <div className="mb-5 flex items-center gap-3">
              {detail.data.product.image_url ? (
                <img src={detail.data.product.image_url} alt={detail.data.product.name} className="conversation-product-visual h-16 w-16 object-cover" />
              ) : (
                <div className="conversation-product-visual grid h-16 w-16 place-items-center"><Package /></div>
              )}
              <div className="min-w-0">
                <b className="block truncate text-sm">{detail.data.product.name}</b>
                <p className="conversation-product-price mt-1 text-sm font-bold">¥{detail.data.product.price}</p>
              </div>
            </div>
            <Info label="商品 ID" value={detail.data.product.external_product_id} />
            <Info label="商品 AI" value={detail.data.product.ai_enabled ? "已开启" : "已关闭"} />
            <Info label="商品知识" value={`${detail.data.product.knowledge_count} 条`} />
            <Info label="当前模型" value={detail.data.current_model} />
            <Info label="当前状态" value={statusPresentation[detail.data.status].label} />
            <Info label="Intent" value={detail.data.last_intent || "—"} />
            <Info label="Confidence" value={detail.data.last_confidence?.toFixed(2) || "—"} />
            <Info label="Risk level" value={detail.data.risk_level} />

            <div className="mt-5 grid gap-2">
              <Link className="btn" href={`/products?product_id=${detail.data.product.id}`}>
                <Package size={15} />查看商品与知识<ExternalLink size={13} />
              </Link>
              <Link className="btn" href={`/ai/test?product_id=${detail.data.product.id}`}>
                <WandSparkles size={15} />打开 AI 测试<ExternalLink size={13} />
              </Link>
            </div>

            <div className="conversation-guard-card mt-5 p-4">
              <div className="flex items-center gap-2 text-sm font-bold"><CheckCircle2 size={16} />后端发送守卫</div>
              <p className="mt-2 text-xs leading-5">只有账号、商品、会话、全局开关与风险规则全部通过后，AI 回复才会真正发送。</p>
            </div>
          </>
        ) : (
          !detail.isLoading && <div className="text-sm text-slate-400">暂无会话商品信息</div>
        )}
      </aside>
    </div>
  );
}

function MessageBubble({
  message,
  busy,
  onSend,
  onEdit,
  onIgnore,
}: {
  message: ConversationMessage;
  busy: boolean;
  onSend: () => void;
  onEdit: () => void;
  onIgnore: () => void;
}) {
  if (message.sender_type === "system") {
    return (
      <div className="flex justify-center">
        <div className="system-message px-4 py-2 text-center text-xs">
          {message.content}<span className="ml-2 text-slate-400">{formatMessageTime(message.created_at)}</span>
        </div>
      </div>
    );
  }

  const isCustomer = message.sender_type === "customer";
  const isSuggestion = message.sender_type === "ai" && !message.sent;
  const bubbleTone = isCustomer
    ? "is-customer"
    : message.sender_type === "human"
      ? "is-human"
      : isSuggestion
        ? "is-ai is-suggestion"
        : "is-ai";
  const label = message.sender_type === "ai" ? "AI" : message.sender_type === "human" ? "人工" : "买家";
  const icon = message.sender_type === "ai" ? <WandSparkles size={11} /> : message.sender_type === "human" ? <UserRound size={11} /> : <MessageCircle size={11} />;

  return (
    <div className={`flex ${isCustomer ? "justify-start" : "justify-end"}`}>
      <div className={`message-bubble ${bubbleTone}`}>
        <div className="message-meta mb-1 flex items-center gap-1 text-[10px] font-bold">
          {icon}{label}<span className="ml-auto pl-3 font-normal text-slate-400">{formatMessageTime(message.created_at)}</span>
        </div>
        <p className="whitespace-pre-wrap break-words leading-6">{message.content}</p>
        {!isCustomer && message.sent && message.platform_read_state !== "not_applicable" && (
          <div
            className={`mt-1.5 flex items-center justify-end gap-1 text-[10px] ${message.platform_read_state === "read" ? "text-blue-700" : "text-slate-500"}`}
            title={message.platform_read_at ? `闲鱼回执时间：${new Date(message.platform_read_at).toLocaleString("zh-CN", { hour12: false })}` : "该状态来自闲鱼消息回执"}
          >
            {message.platform_read_state === "read" ? <CheckCheck size={12} /> : message.platform_read_state === "unread" ? <Check size={12} /> : <Clock3 size={12} />}
            {message.platform_read_state === "read" ? "闲鱼已读" : message.platform_read_state === "unread" ? "闲鱼未读" : "闲鱼状态未知"}
          </div>
        )}
        {isSuggestion && (
          <div className="message-suggestion-actions mt-3 border-t pt-2">
            <div className="message-suggestion-label mb-2 text-[10px]">AI 建议，尚未发送给买家</div>
            <div className="flex flex-wrap gap-1.5">
              <button type="button" className="btn btn-primary px-2 py-1 text-xs" disabled={busy} onClick={onSend}><Send size={12} />一键发送</button>
              <button type="button" className="btn px-2 py-1 text-xs" disabled={busy} onClick={onEdit}><PencilLine size={12} />编辑后发送</button>
              <button type="button" className="btn px-2 py-1 text-xs" disabled={busy} onClick={onIgnore}>忽略</button>
            </div>
          </div>
        )}
        {!message.sent && message.sender_type === "human" && <div className="mt-2 text-[10px] text-red-700">发送失败</div>}
      </div>
    </div>
  );
}

function ListLoading() {
  return <div className="space-y-1 p-3">{[0, 1, 2, 3].map((item) => <div key={item} className="h-24 animate-pulse rounded-lg bg-slate-100" />)}</div>;
}

function MessageLoading() {
  return (
    <div className="space-y-4">
      <div className="h-20 w-2/3 animate-pulse rounded-2xl bg-slate-200" />
      <div className="ml-auto h-24 w-3/5 animate-pulse rounded-2xl bg-amber-100" />
      <div className="h-16 w-1/2 animate-pulse rounded-2xl bg-slate-200" />
    </div>
  );
}

function QueryError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="m-4 rounded-xl border border-red-200 bg-red-50 p-4 text-center text-sm text-red-700">
      <AlertCircle className="mx-auto mb-2" size={20} />
      <p>{message}</p>
      <button type="button" className="btn mt-3 px-3 py-1" onClick={retry}><RotateCcw size={13} />重试</button>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="conversation-info-row flex items-center justify-between gap-3 py-2.5 text-sm">
      <span className="shrink-0 text-slate-500">{label}</span>
      <b className="truncate text-right" title={value}>{value}</b>
    </div>
  );
}
