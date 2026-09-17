"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Clock3, Send, Smartphone, Sparkles } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { CursorPage, request } from "@/lib/api";

interface SimulatorResult {
  accepted: boolean;
  conversation_id: string;
  external_message_id: string;
  debounce_ms: number;
  status: "queued" | "duplicate_or_filtered";
}

interface TraceResult {
  aiLog?: {
    intent: string;
    confidence: number;
    risk_level: string;
    risk_flag?: string;
    need_human: boolean;
    knowledge_gap: boolean;
    should_send: boolean;
    response_action: "REPLY" | "SILENT" | "ANALYZE_ONLY";
    silence_reason?: string;
    reply: string;
    error?: string;
  };
  messages: Array<{ id: string; sender_type: string; content: string; sent: boolean }>;
}

interface AccountSummary {
  id: string;
  nickname: string;
  status: string;
}

interface ProductSummary {
  id: string;
  account_id: string;
  name: string;
  status: "ACTIVE" | "DISABLED";
}

export function SimulatorView() {
  const [accountId, setAccountId] = useState("");
  const [productId, setProductId] = useState("");
  const [result, setResult] = useState<SimulatorResult>();
  const [trace, setTrace] = useState<TraceResult>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => request<AccountSummary[]>("/api/xianyu/accounts") });
  const products = useQuery({ queryKey: ["products", "ACTIVE"], queryFn: () => request<CursorPage<ProductSummary>>("/api/products?status=ACTIVE&limit=100") });
  const runtime = useQuery({ queryKey: ["runtime-settings"], queryFn: () => request<{ debounce_ms: number }>("/api/system/settings") });
  const accountProducts = useMemo(
    () => products.data?.items.filter((product) => product.account_id === accountId && product.status === "ACTIVE") || [],
    [products.data, accountId],
  );

  useEffect(() => {
    if (productId && !accountProducts.some((product) => product.id === productId)) {
      setProductId("");
    }
  }, [accountProducts, productId]);

  async function loadTrace(response: SimulatorResult) {
    setWaiting(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, response.debounce_ms + 300));
      for (let attempt = 0; attempt < 12; attempt += 1) {
        const [messages, logs] = await Promise.all([
          request<CursorPage<TraceResult["messages"][number]>>(`/api/conversations/${response.conversation_id}/messages`),
          request<CursorPage<NonNullable<TraceResult["aiLog"]>>>(`/api/logs/ai?conversation_id=${response.conversation_id}&limit=5`),
        ]);
        // The conversation is uniquely scoped by account/product/buyer. Using its newest
        // log avoids client/server timezone parsing differences for naive database dates.
        const aiLog = logs.items[0];
        setTrace({ messages: messages.items, aiLog });
        if (aiLog) return;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "处理结果读取失败");
    } finally {
      setWaiting(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setWaiting(false);
    setError("");
    setTrace(undefined);
    const form = new FormData(event.currentTarget);
    try {
      const response = await request<SimulatorResult>("/api/dev/simulator", {
        method: "POST",
        body: JSON.stringify({
          account_id: form.get("account_id"),
          product_id: form.get("product_id"),
          buyer_id: form.get("buyer_id"),
          buyer_nickname: form.get("buyer_nickname"),
          content: form.get("content"),
          external_message_id: String(form.get("external_message_id") || "").trim() || null,
        }),
      });
      setResult(response);
      if (response.accepted) void loadTrace(response);
    } catch (reason) {
      setResult(undefined);
      setError(reason instanceof Error ? reason.message : "发送失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="mb-6"><h1 className="text-2xl font-bold">闲鱼消息模拟器</h1><p className="mt-1 text-sm text-slate-500">消息经过与 Adapter 入站相同的落库、聚合、商品知识、模型决策、发送守卫和实时推送链路。</p></div>
      <div className="simulator-layout grid grid-cols-[minmax(0,1fr)_380px] gap-5">
        <div className="space-y-5">
          <form onSubmit={submit} className="card p-6" noValidate>
            <div className="mb-5 flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-lg bg-amber-50 text-amber-700"><Smartphone /></div><div><b>模拟买家发消息</b><p className="text-xs text-slate-500">先选择账号，再选择这个账号下的商品</p></div></div>
            <div className="grid grid-cols-2 gap-4">
              <label className="text-sm font-semibold">闲鱼账号<select required name="account_id" className="input mt-2" value={accountId} onChange={(event) => { setAccountId(event.target.value); setProductId(""); }}><option value="">请选择账号</option>{accounts.data?.map((account) => <option value={account.id} key={account.id}>{account.nickname} · {account.status}</option>)}</select></label>
              <label className="text-sm font-semibold">咨询商品<select required name="product_id" className="input mt-2" value={productId} onChange={(event) => setProductId(event.target.value)} disabled={!accountId}><option value="">请选择在售商品</option>{accountProducts.map((product) => <option value={product.id} key={product.id}>{product.name}</option>)}</select></label>
              <label className="text-sm font-semibold">买家 ID<input name="buyer_id" className="input mt-2" defaultValue="mock-buyer-1001" required /></label>
              <label className="text-sm font-semibold">买家昵称<input name="buyer_nickname" className="input mt-2" defaultValue="测试买家" required /></label>
              <label className="col-span-2 text-sm font-semibold">外部消息 ID（可选）<input name="external_message_id" className="input mt-2 font-mono" placeholder="留空自动生成；重复填写同一个值可验证幂等" /></label>
              <label className="col-span-2 text-sm font-semibold">买家消息<textarea name="content" className="resize-none input mt-2 min-h-32" defaultValue="这个还有吗？" required /></label>
            </div>
            <div className="mt-5 flex items-center justify-between"><span className="flex items-center gap-1 text-xs text-slate-500"><Clock3 size={13} />当前消息聚合 {runtime.data?.debounce_ms || 1500}ms</span><button className="btn btn-warning" disabled={loading || waiting || !accountProducts.length}><Send size={16} />{loading ? "正在提交…" : waiting ? "AI 处理中…" : "发送买家消息"}</button></div>
            {error && <div className="mt-4 flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700"><AlertCircle size={15} />{error}</div>}
            {result && !result.accepted && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">消息未触发处理：它是重复消息、空消息或命中了消息过滤规则。外部消息 ID：<code>{result.external_message_id}</code></div>}
            {result?.accepted && <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"><CheckCircle2 className="mr-2 inline" size={16} />消息已入队，会话 {result.conversation_id.slice(0, 8)}…，外部消息 ID：<code>{result.external_message_id}</code>。<Link href="/conversations" className="ml-2 font-bold underline">打开客服工作台</Link></div>}
          </form>

          {(waiting || trace) && <section className="card p-5"><div className="flex items-center justify-between"><h2 className="font-bold">本次真实处理结果</h2>{waiting && <span className="badge badge-blue">等待 AI 完成…</span>}</div>{trace?.aiLog ? <><p className="mt-4 rounded-xl bg-amber-50 p-4 text-sm leading-6">{trace.aiLog.reply}</p><div className="mt-4 grid grid-cols-4 gap-3">{[["Intent", trace.aiLog.intent], ["Confidence", trace.aiLog.confidence?.toFixed(2)], ["Risk", trace.aiLog.risk_level], ["发送", trace.aiLog.should_send ? "Adapter 已发送" : "后端已拦截"], ["需人工", String(trace.aiLog.need_human)], ["知识缺口", String(trace.aiLog.knowledge_gap)], ["风险标记", trace.aiLog.risk_flag || "—"], ["错误", trace.aiLog.error || "—"]].map(([label, value]) => <div className="rounded-lg border p-3" key={label}><div className="text-[10px] text-slate-400">{label}</div><b className="mt-1 block break-words text-xs">{value}</b></div>)}</div></> : !waiting && <p className="mt-4 text-sm text-slate-500">暂未读取到新的 AI 日志，可前往客服工作台或 AI 日志继续查看。</p>}</section>}
        </div>

        <div className="card h-fit p-5"><div className="flex items-center gap-2 font-bold"><Sparkles size={18} className="text-amber-600" />真实处理链路</div><div className="mt-5 space-y-0">{["账号对应 Adapter 接收", "外部消息幂等检查与落库", "Redis 动态消息聚合", "当前商品独立知识加载", "商品 Prompt + 聊天上下文", "当前 Provider 结构化决策", "后端 AutoSendGuard", "Adapter 发送与 WebSocket 推送"].map((item, index) => <div className="flex gap-3" key={item}><div className="flex flex-col items-center"><span className="grid h-6 w-6 place-items-center rounded-full bg-slate-900 text-[10px] text-white">{index + 1}</span>{index < 7 && <span className="h-7 w-px bg-slate-200" />}</div><span className="pt-1 text-sm">{item}</span></div>)}</div></div>
      </div>
    </>
  );
}
