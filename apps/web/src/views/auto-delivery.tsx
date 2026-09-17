"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, PackageCheck, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { request } from "@/lib/api";
import { useConfirm } from "@/components/confirm-dialog";
import { StatusBadge } from "@/components/interaction";

type DeliveryType = "card" | "image";
interface DeliveryProduct { product_id: string; product_name: string; external_product_id: string; enabled: boolean; delivery_type: DeliveryType; message_template: string; image_url: string | null; available_count: number; delivered_count: number }
interface InventoryItem { id: string; content_mask: string; status: string }
interface DeliveryRecord { id: string; product_name: string; external_order_id: string; content_mask: string; status: string; error: string | null; external_message_id?: string | null; created_at: string }

export function AutoDeliveryView() {
  const client = useQueryClient();
  const confirm = useConfirm();
  const products = useQuery({ queryKey: ["delivery-products"], queryFn: () => request<DeliveryProduct[]>("/api/auto-delivery/products") });
  const [selectedId, setSelectedId] = useState("");
  const selected = useMemo(() => products.data?.find((row) => row.product_id === selectedId), [products.data, selectedId]);
  const [enabled, setEnabled] = useState(false);
  const [deliveryType, setDeliveryType] = useState<DeliveryType>("card");
  const [template, setTemplate] = useState("感谢购买，您的卡密是：{content}");
  const [imageUrl, setImageUrl] = useState("");
  const [cards, setCards] = useState("");
  const [buyerId, setBuyerId] = useState("buyer-auto-delivery");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (!products.data) return;
    if (!products.data.length) {
      setSelectedId("");
      return;
    }
    if (!products.data.some((row) => row.product_id === selectedId)) {
      setSelectedId(products.data[0].product_id);
    }
  }, [products.data, selectedId]);
  useEffect(() => { if (selected) { setEnabled(selected.enabled); setDeliveryType(selected.delivery_type); setTemplate(selected.message_template); setImageUrl(selected.image_url || ""); } }, [selected]);
  const inventory = useQuery({ queryKey: ["delivery-inventory", selectedId], queryFn: () => request<InventoryItem[]>(`/api/auto-delivery/products/${selectedId}/inventory`), enabled: !!selectedId });
  const records = useQuery({ queryKey: ["delivery-records"], queryFn: () => request<DeliveryRecord[]>("/api/auto-delivery/records") });
  const refresh = async () => Promise.all([client.invalidateQueries({ queryKey: ["delivery-products"] }), client.invalidateQueries({ queryKey: ["delivery-inventory", selectedId] }), client.invalidateQueries({ queryKey: ["delivery-records"] })]);
  const save = useMutation({ mutationFn: () => request(`/api/auto-delivery/products/${selectedId}`, { method: "PUT", body: JSON.stringify({ enabled, delivery_type: deliveryType, message_template: template, image_url: imageUrl || null }) }), onSuccess: async () => { setNotice("此商品配置已保存"); await refresh(); }, onError: (error: Error) => setNotice(error.message) });
  const addCards = useMutation({ mutationFn: () => request(`/api/auto-delivery/products/${selectedId}/inventory/cards`, { method: "POST", body: JSON.stringify({ contents: cards.split(/\r?\n/).map((value) => value.trim()).filter(Boolean) }) }), onSuccess: async () => { setCards(""); setNotice("卡密已加密入库，商品不会因此自动开启"); await refresh(); }, onError: (error: Error) => setNotice(error.message) });
  const remove = useMutation({ mutationFn: (id: string) => request(`/api/auto-delivery/products/${selectedId}/inventory/${id}`, { method: "DELETE" }), onSuccess: refresh, onError: (error: Error) => setNotice(error.message) });
  const simulate = useMutation({ mutationFn: () => request<{ status: string; sent: boolean }>("/api/auto-delivery/simulate-paid", { method: "POST", body: JSON.stringify({ product_id: selectedId, buyer_id: buyerId }) }), onSuccess: async (result) => { setNotice(`模拟付款：${result.status}${result.sent ? "（已发送）" : ""}`); await refresh(); }, onError: (error: Error) => setNotice(error.message) });
  const resolve = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "mark_sent" | "release" }) => request(`/api/auto-delivery/records/${id}/resolve`, { method: "POST", body: JSON.stringify({ action }) }),
    onSuccess: refresh,
  });
  if (products.isLoading) return <div className="card p-8 text-sm text-slate-500">正在加载自动发货配置…</div>;
  return <div className="space-y-5">
    <div><h1 className="text-2xl font-bold">自动发货</h1><p className="mt-1 text-sm text-slate-500">按商品独立配置，全部默认关闭；只有明确开启的商品在确认付款后才会发货。</p></div>
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><div className="flex items-center gap-2 font-semibold"><AlertTriangle size={17} />不会影响普通实物商品</div><p className="mt-1 text-xs">未开启、待付款、无订单号、库存不足或发送失败时都不会发货；失败的卡密会退回库存。</p></div>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="card p-5"><label className="label" htmlFor="auto-delivery-product">选择在售商品</label>{products.data?.length ? <select id="auto-delivery-product" className="input" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{products.data.map((row) => <option key={row.product_id} value={row.product_id}>{row.product_name} · {row.external_product_id} · {row.enabled ? "自动发货已开启" : "自动发货未开启"}</option>)}</select> : <div className="mt-2 border-l-2 border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900">暂无可配置的在售商品。已下架商品不会显示，也不会触发自动发货。</div>}
        {selected && <div className="mt-5 space-y-5"><div className="flex items-center justify-between rounded-xl border p-4"><div><b>仅对此商品开启</b><p className="text-xs text-slate-500">不会改变其他商品。</p></div><button onClick={() => setEnabled(!enabled)} className={`rounded-full px-4 py-2 text-sm font-semibold ${enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{enabled ? "已开启" : "已关闭"}</button></div>
          <div className="grid gap-4 md:grid-cols-2"><label><span className="label">发货类型</span><select className="input" value={deliveryType} onChange={(event) => setDeliveryType(event.target.value as DeliveryType)}><option value="card">一次性卡密</option><option value="image">固定图片</option></select></label><div className="rounded-xl bg-slate-50 p-4"><b>{selected.available_count}</b> 条可用 · <b>{selected.delivered_count}</b> 条已发</div></div>
          {deliveryType === "card" ? <><label><span className="label">发货话术</span><textarea className="resize-none input min-h-24" value={template} onChange={(event) => setTemplate(event.target.value)} /><small className="text-slate-400">必须保留 {"{content}"} 占位符。</small></label><label><span className="label">导入卡密（每行一条）</span><textarea className="resize-none input min-h-36 font-mono" value={cards} onChange={(event) => setCards(event.target.value)} placeholder={"CARD-AAAA-1111\nCARD-BBBB-2222"} /></label><button className="btn" disabled={!cards.trim()} onClick={() => addCards.mutate()}>加密导入卡密</button></> : <label><span className="label">公网 HTTPS 图片地址</span><input className="input" value={imageUrl} onChange={(event) => setImageUrl(event.target.value)} placeholder="https://cdn.example.com/delivery.png" /><small className="text-slate-400">必须是买家设备可以访问的公网图片。</small></label>}
          <div className="flex items-center gap-3 border-t pt-5"><button className="btn btn-primary" onClick={() => save.mutate()}><PackageCheck size={16} />保存此商品配置</button>{notice && <span className="text-sm text-slate-600">{notice}</span>}</div></div>}
      </section>
      <aside className="space-y-5"><div className="card p-5"><b>安全模拟付款</b><p className="mt-1 text-xs text-slate-500">仅 Mock 账号可用。</p><label className="mt-4 block"><span className="label">买家 ID</span><input className="input" value={buyerId} onChange={(event) => setBuyerId(event.target.value)} /></label><button className="btn mt-3 w-full" onClick={() => simulate.mutate()}>模拟该商品已付款</button></div><div className="card overflow-hidden"><div className="border-b p-4 font-semibold">卡密库存（脱敏）</div><div className="max-h-72 overflow-y-auto">{inventory.data?.length ? inventory.data.map((item) => <div key={item.id} className="flex items-center justify-between border-b px-4 py-3 text-xs"><div><code>{item.content_mask}</code><div className={item.status === "AVAILABLE" ? "text-emerald-600" : "text-slate-400"}>{item.status}</div></div>{item.status === "AVAILABLE" && <button onClick={() => remove.mutate(item.id)}><Trash2 size={15} className="text-red-400" /></button>}</div>) : <div className="p-6 text-center text-xs text-slate-400">暂无卡密</div>}</div></div></aside>
    </div>
    <section className="card overflow-hidden"><div className="border-b p-4 font-semibold">最近发货记录</div><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="p-3">商品</th><th>订单</th><th>内容</th><th>结果</th><th>时间</th></tr></thead><tbody>{records.data?.map((row) => <tr key={row.id} className="border-t"><td className="p-3 font-medium">{row.product_name}</td><td className="font-mono text-xs">{row.external_order_id}</td><td>{row.content_mask}</td><td><StatusBadge tone={row.status === "SENT" ? "success" : row.status === "UNKNOWN" ? "warning" : row.status === "FAILED" ? "danger" : "info"}>{row.status === "SENT" ? <><CheckCircle2 size={14} />已发送</> : row.status === "UNKNOWN" ? "待人工确认" : row.status}</StatusBadge>{row.error && <p className="mt-1 max-w-64 text-xs text-red-600">{row.error}</p>}{row.status === "UNKNOWN" && <div className="mt-2 flex gap-2"><button className="btn btn-sm" disabled={resolve.isPending} onClick={() => confirm({ title: "确认消息已经发送？", description: "请先在闲鱼会话中核对。确认后卡密将标记为已使用。", confirmLabel: "标记已发送", action: () => resolve.mutateAsync({ id: row.id, action: "mark_sent" }) })}>标记已发送</button><button className="btn btn-sm btn-danger" disabled={resolve.isPending} onClick={() => confirm({ title: "确认消息没有发送？", description: "请先在闲鱼会话中核对。确认后预留卡密将重新释放到库存。", confirmLabel: "释放库存", tone: "danger", action: () => resolve.mutateAsync({ id: row.id, action: "release" }) })}>释放库存</button></div>}</td><td className="text-xs text-slate-500">{new Date(row.created_at).toLocaleString()}</td></tr>)}</tbody></table>{!records.data?.length && <div className="p-8 text-center text-sm text-slate-400">暂无发货记录</div>}</div></section>
  </div>;
}
