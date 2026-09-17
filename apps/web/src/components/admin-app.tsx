"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Bell, Bot, CheckCheck, LogOut, Search, Volume2, VolumeX, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { useConfirm } from "@/components/confirm-dialog";
import { Sidebar } from "@/components/sidebar";
import { useToast } from "@/components/toast";
import { apiUrl, request } from "@/lib/api";
import {
  isCustomerMessageEvent,
  loadChatSoundPreference,
  playChatNotificationSound,
  saveChatSoundPreference,
} from "@/lib/notification-sound";
import { syncRealtimeEvent } from "@/lib/realtime-sync";
import { useUI } from "@/lib/store";
import { AccountsView } from "@/views/accounts";
import { AISettingsView, AITestView, GlobalAISettingsView } from "@/views/ai";
import { AutoDeliveryView } from "@/views/auto-delivery";
import { ConversationsView } from "@/views/conversations";
import { DashboardView } from "@/views/dashboard";
import { GapsView } from "@/views/gaps";
import { LogsView } from "@/views/logs";
import { PlaceholderView } from "@/views/placeholder";
import { ProductsView } from "@/views/products";
import { ReplyRulesView, SystemSettingsView } from "@/views/settings";
import { SimulatorView } from "@/views/simulator";

interface NotificationItem { id: string; type: string; title: string; content: string; read: boolean; created_at: string }

const titleForPath = (path: string) => {
  const exact: Record<string, string> = {
    "/": "仪表盘", "/conversations": "在线会话", "/human": "待人工处理", "/history": "历史会话",
    "/products": "商品管理", "/knowledge": "商品知识库", "/ai/global": "全局 AI 设置", "/ai/model": "模型设置",
    "/ai/rules": "回复规则", "/ai/test": "AI 测试台", "/automation/delivery": "自动发货", "/accounts": "闲鱼账号",
    "/settings": "系统设置", "/simulator": "消息模拟器", "/logs/messages": "消息日志", "/logs/ai": "AI 回复日志", "/logs/risk": "风险日志",
  };
  return exact[path] ?? (path.startsWith("/products") ? "商品管理" : "闲鱼 AI 客服");
};

const notificationRoute = (type: string) => {
  if (type.includes("RISK")) return "/logs/risk";
  if (type.includes("HUMAN")) return "/human";
  if (type.includes("AI_")) return "/logs/ai";
  return "/logs/messages";
};

export function AdminApp() {
  const path = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const { collapsed, realtimeConnected: socketConnected, setRealtimeConnected } = useUI();
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const soundEnabledRef = useRef(true);
  const notificationRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const me = useQuery({ queryKey: ["me"], queryFn: () => request<{ username: string }>("/api/auth/me"), retry: false });
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: () => request<NotificationItem[]>("/api/notifications"), enabled: !!me.data, refetchInterval: socketConnected ? 30_000 : 3_000 });
  const aiSwitch = useQuery({ queryKey: ["switch"], queryFn: () => request<{ enabled: boolean }>("/api/system/ai-switch"), enabled: !!me.data });
  const unread = useMemo(() => notifications.data?.filter((item) => !item.read).length ?? 0, [notifications.data]);

  const markRead = useMutation({ mutationFn: (id: string) => request(`/api/notifications/${id}/read`, { method: "POST" }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }) });
  const readAll = useMutation({ mutationFn: () => request("/api/notifications/read-all", { method: "POST" }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }) });
  const updateAiSwitch = useMutation({
    mutationFn: (enabled: boolean) => request<{ enabled: boolean }>("/api/system/ai-switch", { method: "PUT", body: JSON.stringify({ enabled }) }),
    onSuccess: (result) => {
      queryClient.setQueryData(["switch"], result);
      queryClient.invalidateQueries({ queryKey: ["switch"] });
      toast({ title: result.enabled ? "AI 客服已开启" : "AI 客服已关闭", description: result.enabled ? "符合发送守卫的消息将恢复自动处理。" : "买家消息仍会保存，但不会调用模型或自动回复。", tone: "success" });
    },
    onError: (reason) => toast({ title: "AI 总开关切换失败", description: reason instanceof Error ? reason.message : "请稍后重试", tone: "error" }),
  });

  useEffect(() => { if (me.isError) router.replace("/login"); }, [me.isError, router]);
  useEffect(() => { document.title = `${titleForPath(path)} · 闲鱼 AI 客服`; }, [path]);
  useEffect(() => {
    if (path.startsWith("/products")) setSearchQuery(searchParams.get("q") || "");
  }, [path, searchParams]);
  useEffect(() => {
    const enabled = loadChatSoundPreference(window.localStorage);
    soundEnabledRef.current = enabled;
    setSoundEnabled(enabled);
  }, []);
  useEffect(() => {
    if (!notificationsOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!notificationRef.current?.contains(event.target as Node)) setNotificationsOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setNotificationsOpen(false); };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("pointerdown", onPointerDown); document.removeEventListener("keydown", onKeyDown); };
  }, [notificationsOpen]);

  useEffect(() => {
    if (!me.data) return;
    let stopped = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let reconnectAttempts = 0;
    const connect = () => {
      socket = new WebSocket(`${apiUrl.replace(/^http/, "ws")}/ws`);
      socket.onopen = () => {
        reconnectAttempts = 0;
        setRealtimeConnected(true);
        socket?.send("ready");
        for (const queryKey of [["notifications"], ["conversations"], ["messages"], ["accounts"]]) {
          queryClient.invalidateQueries({ queryKey });
        }
      };
      socket.onmessage = (message) => {
        syncRealtimeEvent(queryClient, message.data);
        if (soundEnabledRef.current && typeof message.data === "string" && isCustomerMessageEvent(message.data)) playChatNotificationSound();
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        setRealtimeConnected(false);
        if (stopped) return;
        reconnectAttempts += 1;
        const backoff = Math.min(1_000 * 2 ** (reconnectAttempts - 1), 15_000);
        const jitter = Math.round(Math.random() * 500);
        reconnectTimer = setTimeout(connect, backoff + jitter);
      };
    };
    connect();
    return () => {
      stopped = true;
      setRealtimeConnected(false);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [me.data, queryClient, setRealtimeConnected]);

  async function toggleGlobalAi() {
    const nextEnabled = !aiSwitch.data?.enabled;
    if (!nextEnabled) {
      const accepted = await confirm({ title: "关闭 AI 客服总开关？", description: "所有买家消息仍会保存，但系统不会调用模型或自动回复。你可以随时重新开启。", confirmLabel: "确认关闭", tone: "danger" });
      if (!accepted) return;
    }
    updateAiSwitch.mutate(nextEnabled);
  }
  async function logout() { await request("/api/auth/logout", { method: "POST" }); router.push("/login"); }
  function toggleSound() {
    const enabled = !soundEnabledRef.current;
    soundEnabledRef.current = enabled; setSoundEnabled(enabled);
    saveChatSoundPreference(window.localStorage, enabled);
    if (enabled) playChatNotificationSound();
    toast({ title: enabled ? "消息提醒音已开启" : "消息提醒音已关闭", tone: "info" });
  }
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    router.push(query ? `/products?q=${encodeURIComponent(query)}` : "/products");
  }
  function clearProductSearch() {
    setSearchQuery("");
    searchRef.current?.focus();
    if (!path.startsWith("/products") || !searchParams.has("q")) return;
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.delete("q");
    router.replace(nextParams.size ? `/products?${nextParams.toString()}` : "/products", { scroll: false });
  }
  function openNotification(item: NotificationItem) { if (!item.read) markRead.mutate(item.id); setNotificationsOpen(false); router.push(notificationRoute(item.type)); }

  if (me.isLoading) return <div className="grid min-h-screen place-items-center"><div className="w-64"><div className="mb-3 text-sm font-semibold">正在进入客服工作台</div><div className="skeleton h-1.5" /></div></div>;

  let view: React.ReactNode;
  if (path === "/") view = <DashboardView />;
  else if (path.startsWith("/products")) view = <ProductsView />;
  else if (path === "/conversations" || path === "/human" || path === "/history") view = <ConversationsView filter={path === "/human" ? "needs_human" : path === "/history" ? "CLOSED" : undefined} />;
  else if (path === "/simulator") view = <SimulatorView />;
  else if (path === "/automation/delivery") view = <AutoDeliveryView />;
  else if (path === "/accounts") view = <AccountsView />;
  else if (path === "/ai/model") view = <AISettingsView />;
  else if (path === "/ai/global") view = <GlobalAISettingsView />;
  else if (path === "/ai/rules") view = <ReplyRulesView />;
  else if (path === "/ai/test") view = <AITestView />;
  else if (path.startsWith("/logs")) view = <LogsView kind={path.split("/").pop() || "ai"} />;
  else if (path === "/knowledge") view = <GapsView />;
  else if (path === "/settings") view = <SystemSettingsView />;
  else view = <PlaceholderView title="页面未找到" />;
  const isConversationWorkspace = path === "/conversations" || path === "/human" || path === "/history";

  return <div className="app-shell" data-app-shell>
    <Sidebar />
    <div className="app-content" data-collapsed={collapsed}>
      <header className="app-header">
        <div className="header-leading">
          <form className="header-search" onSubmit={search} noValidate role="search">
            <button type="submit" className="header-search-submit" aria-label="提交商品搜索"><Search size={16} /></button>
            <label className="sr-only" htmlFor="global-product-search">搜索商品</label>
            <input ref={searchRef} id="global-product-search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索商品名称或商品 ID" />
            {searchQuery && <button type="button" className="header-search-clear" aria-label="清空搜索" onClick={clearProductSearch}><X size={14} /></button>}
          </form>
        </div>
        <div className="header-actions">
          <span className={`live-status ${socketConnected ? "is-online" : ""}`} title={socketConnected ? "实时消息已连接" : "实时消息正在重连"}><span /> <b>{socketConnected ? "实时在线" : "正在重连"}</b></span>
          <div className="ai-master-control">
            <Bot size={16} aria-hidden="true" />
            <span>AI 客服</span>
            <button type="button" aria-label="AI 客服总开关" aria-pressed={!!aiSwitch.data?.enabled} disabled={aiSwitch.isLoading || updateAiSwitch.isPending} onClick={toggleGlobalAi} className={`switch ${aiSwitch.data?.enabled ? "is-on" : ""}`}><span /></button>
          </div>
          <button type="button" onClick={toggleSound} className={`icon-btn sound-control ${soundEnabled ? "is-on" : ""}`} aria-pressed={soundEnabled} aria-label={soundEnabled ? "关闭消息提醒音" : "开启消息提醒音"} title={soundEnabled ? "消息提醒音已开启" : "消息提醒音已关闭"}>{soundEnabled ? <Volume2 size={17} /> : <VolumeX size={17} />}</button>
          <div className="notification-control" ref={notificationRef}>
            <button aria-label={`通知中心，${unread} 条未读`} aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen((open) => !open)} className="icon-btn notification-button"><Bell size={17} />{unread > 0 && <span>{unread > 99 ? "99+" : unread}</span>}</button>
            {notificationsOpen && <div className="notification-popover" role="dialog" aria-label="通知中心">
              <div className="notification-head"><div><b>通知中心</b><span>{unread} 条未读</span></div><button className="btn btn-sm" type="button" disabled={!unread || readAll.isPending} onClick={() => readAll.mutate()}><CheckCheck size={14} />全部已读</button></div>
              <div className="notification-list">
                {notifications.isLoading && <div className="loading-block"><div className="skeleton-line" /><div className="skeleton-line" /><div className="skeleton-line" /></div>}
                {notifications.isError && <button className="notification-empty is-error" type="button" onClick={() => notifications.refetch()}><AlertCircle size={20} />通知加载失败，点击重试</button>}
                {notifications.data?.map((item) => <button key={item.id} onClick={() => openNotification(item)} className={`notification-item ${item.read ? "is-read" : ""}`} type="button"><span className="notification-dot" /><span><b>{item.title}</b><small>{item.content}</small><time>{new Date(item.created_at).toLocaleString("zh-CN")}</time></span></button>)}
                {!notifications.isLoading && !notifications.data?.length && <div className="notification-empty"><Bell size={22} />暂无系统通知</div>}
              </div>
            </div>}
          </div>
          <span className="header-user">{me.data?.username}</span>
          <button onClick={logout} type="button" aria-label="退出登录" title="退出登录" className="icon-btn logout-button"><LogOut size={17} /></button>
        </div>
      </header>
      <main key={path} className={`app-main ${isConversationWorkspace ? "is-workspace" : ""}`}>{view}</main>
    </div>
  </div>;
}
