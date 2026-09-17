"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BookPlus, CheckCircle2, Database, X } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

import { CursorPage, request } from "@/lib/api";
import { useConfirm } from "@/components/confirm-dialog";

interface Gap {
  id: string;
  product_id: string;
  conversation_id: string;
  user_message: string;
  missing_knowledge?: string;
  ai_reply: string;
  status: "pending" | "resolved" | "ignored";
  created_at: string;
}

interface ProductSummary { id: string; name: string; external_product_id: string }

const categories = [
  ["parameter", "参数"], ["condition", "成色"], ["shipping", "发货"],
  ["after_sales", "售后"], ["compatibility", "兼容性"], ["usage", "使用方法"],
  ["manual", "说明书"], ["other", "其他"],
];

export function GapsView() {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [status, setStatus] = useState<Gap["status"]>("pending");
  const [selected, setSelected] = useState<Gap | null>(null);
  const [error, setError] = useState("");
  const gaps = useQuery({
    queryKey: ["knowledge-gaps", status],
    queryFn: () => request<Gap[]>(`/api/knowledge-gaps?status=${status}`),
  });
  const products = useQuery({ queryKey: ["products"], queryFn: () => request<CursorPage<ProductSummary>>("/api/products?limit=100") });
  const productNames = useMemo(() => new Map(products.data?.items.map((item) => [item.id, item]) || []), [products.data]);
  const ignore = useMutation({
    mutationFn: (id: string) => request(`/api/knowledge-gaps/${id}/ignore`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge-gaps"] }),
    onError: (reason) => setError(reason instanceof Error ? reason.message : "忽略失败"),
  });

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await request(`/api/knowledge-gaps/${selected.id}/save-knowledge`, {
        method: "POST",
        body: JSON.stringify({
          title: String(data.get("title") || "").trim(),
          content: String(data.get("content") || "").trim(),
          category: data.get("category"),
        }),
      });
      setSelected(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["knowledge-gaps"] }),
        queryClient.invalidateQueries({ queryKey: ["products"] }),
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    }
  }

  return (
    <>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold">知识缺口处理</h1>
          <p className="mt-1 text-sm text-slate-500">AI 不知道时由人工确认；只有确认后的答案才会进入对应商品知识库。</p>
        </div>
        <div className="flex rounded-lg border bg-white p-1">
          {(["pending", "resolved", "ignored"] as const).map((item) => (
            <button key={item} className={`rounded-md px-3 py-1.5 text-xs font-semibold ${status === item ? "bg-slate-900 text-white" : "text-slate-500"}`} onClick={() => setStatus(item)}>
              {item === "pending" ? "待处理" : item === "resolved" ? "已沉淀" : "已忽略"}
            </button>
          ))}
        </div>
      </div>
      {error && <div role="alert" className="mb-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle size={15} />{error}<button className="ml-auto" onClick={() => setError("")}><X size={14} /></button></div>}
      <div className="card">
        <div className="flex items-center gap-3 border-b p-5">
          <Database className="text-amber-600" />
          <div><b>{status === "pending" ? "待处理知识缺口" : status === "resolved" ? "已保存知识" : "已忽略记录"}</b><p className="text-xs text-slate-500">知识读取和保存均按 product_id 严格隔离</p></div>
        </div>
        {gaps.isError ? (
          <button className="w-full p-12 text-sm text-red-600" onClick={() => gaps.refetch()}>加载失败，点击重试</button>
        ) : (
          <div className="divide-y">
            {gaps.data?.map((gap) => {
              const product = productNames.get(gap.product_id);
              return (
                <div key={gap.id} className="knowledge-gap-row grid grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)_auto] items-start gap-5 p-5">
                  <div><span className="text-xs text-slate-500">对应商品</span><p className="mt-1 truncate text-sm font-semibold" title={product?.name}>{product?.name || gap.product_id}</p><p className="mt-1 text-[10px] text-slate-400">{product?.external_product_id}</p></div>
                  <div><span className="text-xs text-slate-500">买家问题</span><p className="mt-1 text-sm font-semibold">{gap.user_message}</p><p className="mt-2 text-xs text-slate-400">{new Date(gap.created_at).toLocaleString("zh-CN")}</p></div>
                  <div><span className="text-xs text-slate-500">缺少知识 / AI 建议</span><p className="mt-1 text-sm text-amber-800">{gap.missing_knowledge || "未明确"}</p><p className="mt-2 line-clamp-2 text-xs text-slate-500">{gap.ai_reply}</p></div>
                  {gap.status === "pending" ? (
                    <div className="flex gap-2"><button className="btn" onClick={() => { setError(""); setSelected(gap); }}><BookPlus size={15} />保存为知识</button><button disabled={ignore.isPending} className="btn" onClick={async () => { const accepted = await confirm({ title: "忽略这个知识缺口？", description: "忽略后不会写入商品知识库，记录仍会保留以便审计。", confirmLabel: "确认忽略" }); if (accepted) ignore.mutate(gap.id); }}>忽略</button></div>
                  ) : <span className={`badge ${gap.status === "resolved" ? "badge-green" : ""}`}>{gap.status === "resolved" ? "已处理" : "已忽略"}</span>}
                </div>
              );
            })}
            {gaps.isLoading && <div className="p-12 text-center text-sm text-slate-400">正在加载知识缺口…</div>}
            {!gaps.isLoading && !gaps.data?.length && <div className="p-12 text-center text-sm text-slate-400"><CheckCircle2 className="mx-auto mb-2" />当前列表为空</div>}
          </div>
        )}
      </div>

      {selected && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-6">
          <form className="w-full max-w-xl rounded-2xl bg-white shadow-2xl" onSubmit={save} noValidate>
            <div className="flex items-center justify-between border-b p-5"><div><b>保存为商品知识</b><p className="mt-1 text-xs text-slate-500">{productNames.get(selected.product_id)?.name}</p></div><button type="button" onClick={() => setSelected(null)}><X size={18} /></button></div>
            <div className="space-y-4 p-5">
              <div className="rounded-lg bg-slate-50 p-3 text-sm"><span className="text-xs text-slate-400">买家问题</span><p className="mt-1">{selected.user_message}</p></div>
              <label className="block text-sm font-semibold">标题<input className="input mt-2" name="title" required defaultValue={selected.missing_knowledge || "补充知识"} /></label>
              <label className="block text-sm font-semibold">人工确认的正确答案<textarea className="resize-none input mt-2 min-h-32" name="content" required placeholder="只填写已经核实的事实，不要复制未经确认的 AI 猜测。" /></label>
              <label className="block text-sm font-semibold">分类<select className="input mt-2" name="category">{categories.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              {error && <p className="text-sm text-red-600">{error}</p>}
            </div>
            <div className="flex justify-end gap-2 border-t bg-slate-50 p-4"><button className="btn" type="button" onClick={() => setSelected(null)}>取消</button><button className="btn btn-primary"><BookPlus size={15} />确认保存</button></div>
          </form>
        </div>
      )}
    </>
  );
}
