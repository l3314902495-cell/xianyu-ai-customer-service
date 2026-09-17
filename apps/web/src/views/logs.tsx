"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { AlertCircle, ChevronDown, ChevronUp, RefreshCw, Search, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { CursorPage, request } from "@/lib/api";

interface MessageLog {
  id: string;
  conversation_id: string;
  sender_type: string;
  content: string;
  external_message_id?: string;
  sent: boolean;
  created_at: string;
}

interface AILog {
  id: string;
  conversation_id: string;
  product_id: string;
  user_message: string;
  prompt_version: string;
  provider: string;
  model: string;
  intent: string;
  confidence: number;
  risk_level: string;
  risk_flag?: string;
  knowledge_gap: boolean;
  missing_knowledge?: string;
  need_human: boolean;
  should_send: boolean;
  response_action: "REPLY" | "SILENT" | "ANALYZE_ONLY";
  silence_reason?: string;
  reply: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  error?: string;
  raw_json: Record<string, unknown>;
  created_at: string;
}

export function LogsView({ kind }: { kind: string }) {
  const isMessage = kind === "messages";
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const path = isMessage ? "/api/logs/messages" : kind === "risk" ? "/api/logs/risks" : "/api/logs/ai";
  const logs = useInfiniteQuery({
    queryKey: [isMessage ? "message-logs" : "ai-logs", kind],
    queryFn: ({ pageParam }) => request<CursorPage<MessageLog | AILog>>(
      `${path}${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`,
    ),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor || undefined,
  });
  const rows = useMemo(
    () => logs.data?.pages.flatMap((page) => page.items) ?? [],
    [logs.data],
  );
  const data = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => JSON.stringify(row).toLowerCase().includes(needle));
  }, [query, rows]);

  return (
    <>
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{isMessage ? "消息日志" : kind === "risk" ? "风险日志" : "AI 回复日志"}</h1>
          <p className="mt-1 text-sm text-slate-500">保留消息、模型决策、发送守卫与错误信息，便于审计和排障。</p>
        </div>
        <div className="relative block w-72">
          <Search className="absolute left-3 top-2.5 text-slate-400" size={16} />
          <label className="sr-only" htmlFor={`log-search-${kind}`}>搜索日志</label>
          <input
            ref={searchRef}
            id={`log-search-${kind}`}
            className="input input-leading-icon input-trailing-icon h-9 text-sm"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索会话、内容、模型或风险"
          />
          {query && <button type="button" className="icon-btn absolute right-1 top-0.5 h-8 w-8" aria-label="清空日志搜索" onClick={() => { setQuery(""); searchRef.current?.focus(); }}><X size={14} /></button>}
        </div>
      </div>

      {logs.isError ? (
        <div className="card p-10 text-center text-sm text-red-600">
          <AlertCircle className="mx-auto mb-2" />
          {logs.error instanceof Error ? logs.error.message : "日志加载失败"}
          <button className="btn mx-auto mt-4" onClick={() => logs.refetch()}><RefreshCw size={14} />重试</button>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table>
            <thead>
              <tr>
                {isMessage ? (
                  <><th>时间</th><th>发送方</th><th>内容</th><th>外部消息 ID</th><th>状态</th></>
                ) : (
                  <><th>时间</th><th>Provider / Model</th><th>Intent</th><th>风险</th><th>回复</th><th>发送结果</th><th>耗时</th><th /></>
                )}
              </tr>
            </thead>
            <tbody>
              {data?.map((row) => {
                if (isMessage) {
                  const item = row as MessageLog;
                  return (
                    <tr key={item.id}>
                      <td className="whitespace-nowrap text-xs">{new Date(item.created_at).toLocaleString("zh-CN")}</td>
                      <td><span className="badge">{item.sender_type}</span></td>
                      <td className="max-w-md whitespace-pre-wrap">{item.content}</td>
                      <td className="max-w-48 truncate font-mono text-xs" title={item.external_message_id}>{item.external_message_id || "—"}</td>
                      <td>{item.sent ? <span className="badge badge-green">已发送</span> : <span className="badge badge-amber">未发送</span>}</td>
                    </tr>
                  );
                }
                const item = row as AILog;
                const isExpanded = expanded === item.id;
                return (
                  <tr key={item.id} className="align-top">
                    <td className="whitespace-nowrap text-xs">{new Date(item.created_at).toLocaleString("zh-CN")}</td>
                    <td className="text-xs"><b>{item.provider}</b><div className="mt-1 text-slate-400">{item.model}</div></td>
                    <td><span className="badge">{item.intent}</span><div className="mt-1 text-xs">{item.confidence.toFixed(2)}</div></td>
                    <td>
                      <span className={`badge ${item.risk_level === "HIGH" ? "badge-red" : item.risk_level === "MEDIUM" ? "badge-amber" : "badge-green"}`}>{item.risk_level}</span>
                      {item.risk_flag && <div className="mt-1 max-w-40 text-xs text-red-600">{item.risk_flag}</div>}
                    </td>
                    <td className="max-w-sm">
                      <div className="line-clamp-3 whitespace-pre-wrap">{item.reply}</div>
                      {isExpanded && (
                        <div className="mt-3 space-y-2 rounded-lg bg-slate-50 p-3 text-xs">
                          <p><b>买家消息：</b>{item.user_message}</p>
                          <p><b>Prompt：</b>{item.prompt_version}</p>
                          <p><b>Token：</b>{item.input_tokens} 输入 / {item.output_tokens} 输出</p>
                          <p><b>预估成本：</b>¥{Number(item.estimated_cost || 0).toFixed(6)}</p>
                          {item.missing_knowledge && <p className="text-amber-700"><b>缺失知识：</b>{item.missing_knowledge}</p>}
                          {item.silence_reason && <p className="text-blue-700"><b>静默原因：</b>{item.silence_reason}</p>}
                          {item.error && <p className="text-red-600"><b>错误：</b>{item.error}</p>}
                          <details><summary className="cursor-pointer font-semibold">原始决策 JSON</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap">{JSON.stringify(item.raw_json, null, 2)}</pre></details>
                        </div>
                      )}
                    </td>
                    <td>
                      {item.response_action === "SILENT" ? <span className="badge badge-blue">智能静默</span> : item.should_send ? <span className="badge badge-green">Adapter 已发送</span> : <span className="badge badge-amber">后端已拦截</span>}
                      {item.silence_reason && <div className="mt-1 max-w-40 text-xs text-blue-700">{item.silence_reason}</div>}
                      {item.need_human && <div className="mt-1 text-xs text-amber-700">需人工</div>}
                    </td>
                    <td>{item.latency_ms}ms</td>
                    <td><button aria-label="展开日志" className="grid h-8 w-8 place-items-center rounded hover:bg-slate-100" onClick={() => setExpanded(isExpanded ? null : item.id)}>{isExpanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {logs.isLoading && <div className="p-12 text-center text-sm text-slate-400">正在加载日志…</div>}
          {!logs.isLoading && !data?.length && <div className="p-12 text-center text-sm text-slate-400">暂无符合条件的日志</div>}
          {logs.hasNextPage && (
            <div className="border-t border-slate-200 p-3 text-center">
              <button className="btn" type="button" disabled={logs.isFetchingNextPage} onClick={() => logs.fetchNextPage()}>
                {logs.isFetchingNextPage ? "正在加载…" : "加载更多日志"}
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
