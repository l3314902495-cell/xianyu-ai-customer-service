"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Bot, Clock3, Coins, MessageSquare, Sparkles, UserCheck } from "lucide-react";
import Link from "next/link";
import { BuyerAvatar } from "@/components/buyer-avatar";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { CursorPage, request } from "@/lib/api";

type Stats = { today_conversations: number; today_buyer_messages: number; ai_replies: number; human_takeovers: number; automation_rate: number; knowledge_gaps: number; high_risk: number; avg_response_ms: number; today_tokens: number; today_cost: number };
type ConversationSummary = { id: string; buyer_nickname: string; buyer_avatar?: string | null; last_intent?: string | null; needs_human: boolean; updated_at: string };
type GapSummary = { id: string; user_message: string; missing_knowledge?: string | null };

const number = new Intl.NumberFormat("zh-CN");

export function DashboardView() {
  const stats = useQuery({ queryKey: ["dashboard"], queryFn: () => request<Stats>("/api/dashboard") });
  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => request<CursorPage<ConversationSummary>>("/api/conversations?limit=7") });
  const gaps = useQuery({ queryKey: ["gaps"], queryFn: () => request<GapSummary[]>("/api/knowledge-gaps") });
  const primary = [
    { label: "今日会话", value: stats.data?.today_conversations ?? 0, icon: MessageSquare },
    { label: "买家消息", value: stats.data?.today_buyer_messages ?? 0, icon: Sparkles },
    { label: "AI 自动回复", value: stats.data?.ai_replies ?? 0, icon: Bot },
    { label: "人工接管", value: stats.data?.human_takeovers ?? 0, icon: UserCheck },
  ];

  return <>
    <PageHeader title="运营仪表盘" description="关注今天真正需要处理的会话、风险与 AI 运行状态。" actions={<span className="dashboard-live"><span />数据实时更新</span>} />
    {stats.isError && <div className="mb-5"><ErrorState message={stats.error instanceof Error ? stats.error.message : "无法读取仪表盘数据"} onRetry={() => stats.refetch()} /></div>}

    <section className="operations-strip" aria-label="今日核心指标">
      <div className="operations-metrics">
        {primary.map(({ label, value, icon: Icon }) => <div className="operation-metric" key={label}>
          <span className="operation-metric-icon"><Icon size={16} aria-hidden="true" /></span>
          <span><small>{label}</small>{stats.isLoading ? <span className="skeleton mt-2 block h-7 w-14" /> : <strong className="metric-value">{number.format(value)}</strong>}</span>
        </div>)}
      </div>
    </section>

    <section className="secondary-metrics" aria-label="服务质量指标">
      <div><small>自动处理率</small><strong className="data-number">{stats.data?.automation_rate ?? 0}<em>%</em></strong></div>
      <div><small>知识缺口</small><strong className="data-number">{number.format(stats.data?.knowledge_gaps ?? 0)}</strong></div>
      <div><small>高风险消息</small><strong className={`data-number ${(stats.data?.high_risk ?? 0) > 0 ? "text-danger" : ""}`}>{number.format(stats.data?.high_risk ?? 0)}</strong></div>
      <div><small>平均响应</small><strong className="data-number">{number.format(stats.data?.avg_response_ms ?? 0)}<em>ms</em></strong></div>
    </section>

    <div className="dashboard-grid">
      <section className="dashboard-section dashboard-conversations">
        <div className="dashboard-section-head"><div><span>实时队列</span><h2>最近会话</h2></div><Link href="/conversations" className="text-link">进入工作台 <ArrowRight size={14} /></Link></div>
        {convs.isError ? <ErrorState message="最近会话加载失败" onRetry={() => convs.refetch()} /> : <div className="conversation-summary-list">
          {convs.isLoading && Array.from({ length: 5 }, (_, index) => <div className="conversation-summary skeleton" key={index} />)}
          {convs.data?.items.map((conversation) => <Link href={`/conversations?conversation_id=${conversation.id}`} className="conversation-summary" key={conversation.id}>
            <BuyerAvatar src={conversation.buyer_avatar} name={conversation.buyer_nickname} />
            <span className="conversation-summary-copy"><b>{conversation.buyer_nickname || "未知买家"}</b><small>{conversation.last_intent ? `意图：${conversation.last_intent}` : "等待识别意图"}</small></span>
            <span className="conversation-summary-state"><span className={`badge ${conversation.needs_human ? "badge-amber" : "badge-green"}`}>{conversation.needs_human ? "待人工" : "AI 托管"}</span><time>{new Date(conversation.updated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></span>
          </Link>)}
          {!convs.isLoading && !convs.data?.items.length && <EmptyState title="还没有会话" description="收到买家消息后，会话会出现在这里。" />}
        </div>}
      </section>

      <section className="dashboard-section dashboard-attention">
        <div className="dashboard-section-head"><div><span>需要判断</span><h2>待人工问题</h2></div><Link href="/knowledge" className="text-link">查看全部 <ArrowRight size={14} /></Link></div>
        {gaps.isError ? <ErrorState message="待人工问题加载失败" onRetry={() => gaps.refetch()} /> : <div className="attention-list">
          {gaps.data?.slice(0, 5).map((gap, index) => <Link href="/knowledge" className="attention-item" key={gap.id}><span className="attention-index">{String(index + 1).padStart(2, "0")}</span><span><b>{gap.user_message}</b><small>{gap.missing_knowledge || "等待人工确认并补充知识"}</small></span></Link>)}
          {!gaps.isLoading && !gaps.data?.length && <EmptyState title="队列已清空" description="当前没有待处理的知识缺口。" />}
        </div>}
      </section>
    </div>

    <section className="usage-line">
      <span className="usage-symbol"><Coins size={19} /></span>
      <div><b>今日 AI 用量</b><small>Token 与成本来自 Provider Usage</small></div>
      <span><small>Token</small><strong className="data-number">{number.format(stats.data?.today_tokens ?? 0)}</strong></span>
      <span><small>预估成本</small><strong className="data-number">¥{(stats.data?.today_cost ?? 0).toFixed(4)}</strong></span>
      {(stats.data?.high_risk ?? 0) > 0 && <Link href="/logs/risk" className="usage-warning"><AlertTriangle size={15} />有高风险消息待复核</Link>}
      <Clock3 className="usage-clock" size={17} aria-hidden="true" />
    </section>
  </>;
}
