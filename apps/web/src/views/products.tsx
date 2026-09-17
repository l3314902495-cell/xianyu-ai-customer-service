"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Bot,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Power,
  Search,
  Send,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { ChangeEvent, FormEvent, ReactNode, useMemo, useRef, useState } from "react";
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { CursorPage, request } from "@/lib/api";
import { useConfirm } from "@/components/confirm-dialog";
import { Drawer, FormField, StatusBadge, Tabs } from "@/components/interaction";
import { PageHeader } from "@/components/ui";
import { useToast } from "@/components/toast";

type Account = {
  id: string;
  nickname: string;
  status: string;
  adapter_type?: string;
  runtime_connected?: boolean;
};

type ProductDetails = Record<string, unknown> & {
  model?: string;
  color?: string;
  specification?: string;
  condition?: string;
  description?: string;
  selling_points?: string;
  defects?: string;
  accessories?: string;
  packaging?: string;
  purchase_time?: string;
  repair_history?: string;
  invoice?: string;
  warranty?: string;
  shipping_origin?: string;
  shipping_time?: string;
  shipping?: string;
  freight?: string;
  after_sales?: string;
  notes?: string;
  special_rules?: string;
  forbidden_rules?: string;
};

type Product = {
  id?: string;
  account_id: string;
  external_product_id?: string;
  name?: string;
  category?: string | null;
  image_url?: string | null;
  price?: number;
  status?: "ACTIVE" | "DISABLED";
  ai_enabled: boolean;
  ai_prompt?: string;
  details: ProductDetails;
  knowledge_count?: number;
  faq_count?: number;
  updated_at?: string;
};

type KnowledgeItem = {
  id: string;
  product_id?: string;
  title: string;
  content: string;
  category: string;
  priority: number;
  enabled: boolean;
  source: string;
};

type FAQItem = {
  id: string;
  question: string;
  answer: string;
  keywords: string[];
  enabled: boolean;
  priority: number;
};

type Notice = { type: "success" | "error"; text: string } | null;

const DETAIL_FIELDS = [
  ["model", "型号"],
  ["color", "颜色"],
  ["specification", "规格"],
  ["condition", "成色"],
] as const;

const DETAIL_TEXTAREAS = [
  ["description", "商品介绍", "如实描述商品用途、版本和主要情况"],
  ["selling_points", "商品卖点", "仅填写有事实依据的卖点"],
  ["defects", "商品瑕疵", "划痕、磕碰、功能异常等，请明确填写"],
  ["accessories", "配件", "随商品一同发出的配件清单"],
  ["packaging", "包装", "原包装、替代包装等"],
  ["repair_history", "维修情况", "没有记录时请留空，不要猜测"],
  ["after_sales", "售后政策", "支持或不支持的售后范围"],
  ["notes", "注意事项", "买家下单前需要了解的其他信息"],
] as const;

export function ProductsView() {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const router = useRouter();
  const searchParams = useSearchParams();
  const routeQuery = searchParams.get("q") || "";
  const routeAccountId = searchParams.get("account_id") || "";
  const routeStatus = searchParams.get("status") || (searchParams.get("product_id") ? "" : "ACTIVE");
  const [queryInput, setQueryInput] = useState(routeQuery);
  const [query, setQuery] = useState(routeQuery);
  const [queryComposing, setQueryComposing] = useState(false);
  const [accountId, setAccountId] = useState(routeAccountId);
  const [status, setStatus] = useState(routeStatus);
  const [editing, setEditing] = useState<Product | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [tab, setTab] = useState("basic");
  const [notice, setNotice] = useState<Notice>(null);
  const dismissedRouteProduct = useRef<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setQueryInput(routeQuery);
    setQuery(routeQuery);
  }, [routeQuery]);

  useEffect(() => {
    setAccountId(routeAccountId);
    setStatus(routeStatus);
  }, [routeAccountId, routeStatus]);

  useEffect(() => {
    if (queryComposing) return;
    const timer = window.setTimeout(() => setQuery(queryInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [queryComposing, queryInput]);

  useEffect(() => {
    if (query === routeQuery) return;
    const nextParams = new URLSearchParams(searchParams.toString());
    if (query) nextParams.set("q", query);
    else nextParams.delete("q");
    const nextQuery = nextParams.toString();
    router.replace(nextQuery ? `/products?${nextQuery}` : "/products", { scroll: false });
  }, [query, routeQuery, router, searchParams]);

  const updateRouteFilter = (key: "account_id" | "status", value: string) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (value && !(key === "status" && value === "ACTIVE")) nextParams.set(key, value);
    else nextParams.delete(key);
    const nextQuery = nextParams.toString();
    router.replace(nextQuery ? `/products?${nextQuery}` : "/products", { scroll: false });
  };

  const clearFilters = () => {
    setQueryInput("");
    setQuery("");
    setAccountId("");
    setStatus("ACTIVE");
    router.replace("/products", { scroll: false });
    searchRef.current?.focus();
  };

  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: () => request<Account[]>("/api/xianyu/accounts"),
  });
  const products = useInfiniteQuery({
    queryKey: ["products", query, accountId, status],
    queryFn: ({ pageParam }) =>
      request<CursorPage<Product>>(
        `/api/products?q=${encodeURIComponent(query)}&account_id=${encodeURIComponent(accountId)}&status=${encodeURIComponent(status)}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor || undefined,
  });
  const productItems = useMemo(
    () => products.data?.pages.flatMap((page) => page.items) ?? [],
    [products.data],
  );
  useEffect(() => {
    const requestedProduct = searchParams.get("product_id");
    if (!requestedProduct) {
      dismissedRouteProduct.current = null;
      return;
    }
    if (requestedProduct === dismissedRouteProduct.current || editing || !products.data) return;
    const product = productItems.find((item) => item.id === requestedProduct);
    if (product) {
      setEditing(product);
      setTab("basic");
    }
  }, [editing, productItems, products.data, searchParams]);
  const toggle = useMutation({
    mutationFn: (product: Product) =>
      request<Product>(`/api/products/${product.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ai_enabled: !product.ai_enabled }),
      }),
    onSuccess: (product) => {
      setNotice({ type: "success", text: `${product.name} 的 AI 自动回复已${product.ai_enabled ? "开启" : "关闭"}` });
      queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (error) => setNotice({ type: "error", text: errorMessage(error) }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => request(`/api/products/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setNotice({ type: "success", text: "商品已删除" });
      queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (error) => setNotice({ type: "error", text: errorMessage(error) }),
  });
  const bulkTakeover = useMutation({
    mutationFn: (mode: "human" | "ai") =>
      request<{ updated: number; enabled: boolean }>("/api/products/ai-switch-all", {
        method: "PUT",
        body: JSON.stringify({ enabled: mode === "ai" }),
      }),
    onSuccess: (result) => {
      setNotice({
        type: "success",
        text: result.enabled
          ? `已将 ${result.updated} 件商品切换为 AI 接管`
          : `已将 ${result.updated} 件商品切换为人工接管`,
      });
      queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (error) => setNotice({ type: "error", text: errorMessage(error) }),
  });

  const switchAllProducts = async (mode: "human" | "ai") => {
    const accepted = await confirm({
      title: mode === "ai" ? "全部商品切换为 AI 接管？" : "全部商品切换为人工接管？",
      description: mode === "ai" ? "已有会话和未来新会话都会按商品 AI 状态处理。" : "所有商品将停止 AI 自动回复，但买家消息仍会保存。",
      confirmLabel: mode === "ai" ? "全部 AI 接管" : "全部人工接管",
      tone: mode === "ai" ? "default" : "danger",
    });
    if (!accepted) return;
    bulkTakeover.mutate(mode);
  };

  const open = (product: Product, nextTab = "basic") => {
    dismissedRouteProduct.current = null;
    setEditing(product);
    setTab(nextTab);
  };

  const closePanel = () => {
    const requestedProduct = searchParams.get("product_id");
    dismissedRouteProduct.current = requestedProduct;
    setEditing(null);

    if (requestedProduct) {
      const nextParams = new URLSearchParams(searchParams.toString());
      nextParams.delete("product_id");
      const nextQuery = nextParams.toString();
      router.replace(nextQuery ? `/products?${nextQuery}` : "/products", { scroll: false });
    }
  };

  return (
    <>
      <PageHeader title="商品管理" description="每个商品拥有严格隔离的资料、知识、FAQ、Prompt 与回复规则。" actions={<>
          <button
            className="btn border-red-200 bg-red-50 text-red-700"
            disabled={bulkTakeover.isPending}
            onClick={() => switchAllProducts("human")}
          >
            <Power size={16} /> 全部人工接管
          </button>
          <button
            className="btn btn-warning"
            disabled={!accounts.data?.some((account) => account.adapter_type === "experimental-web" && account.status === "CONNECTED")}
            onClick={() => setPublishing(true)}
          >
            <Send size={16} /> 发布到闲鱼
          </button>
          <button
            className="btn btn-primary"
            disabled={bulkTakeover.isPending}
            onClick={() => switchAllProducts("ai")}
          >
            <Bot size={16} /> 全部 AI 接管
          </button>
          <button
            className="btn btn-primary"
            disabled={!accounts.data?.length}
            onClick={() =>
              open({
                account_id: accountId || accounts.data?.[0]?.id || "",
                details: {},
                ai_enabled: true,
                status: "ACTIVE",
                price: 0,
              })
            }
          >
            <Plus size={16} /> 新增商品
          </button>
        </>} />

      {notice && <InlineNotice notice={notice} onClose={() => setNotice(null)} />}

      <div className="product-table card overflow-hidden">
        <div className="product-filters items-center gap-3 border-b p-4">
          <select
            aria-label="按闲鱼账号筛选商品"
            className="input h-9 w-56 py-1"
            value={accountId}
            onChange={(event) => {
              setAccountId(event.target.value);
              updateRouteFilter("account_id", event.target.value);
            }}
          >
            <option value="">全部账号</option>
            {accounts.data?.map((account) => (
              <option key={account.id} value={account.id}>{account.nickname}</option>
            ))}
          </select>
          <select
            aria-label="按商品状态筛选"
            className="input h-9 w-36 py-1"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              updateRouteFilter("status", event.target.value);
            }}
          >
            <option value="ACTIVE">在售商品</option>
            <option value="DISABLED">已下架</option>
            <option value="">全部状态</option>
          </select>
          <div className="relative w-80">
            <Search className="absolute left-3 top-2.5 text-slate-400" size={16} />
            <label className="sr-only" htmlFor="product-search">搜索商品名称或商品 ID</label>
            <input
              ref={searchRef}
              id="product-search"
              className="input input-leading-icon input-trailing-icon h-9"
              value={queryInput}
              onChange={(event) => setQueryInput(event.target.value)}
              onCompositionStart={() => setQueryComposing(true)}
              onCompositionEnd={(event) => { setQueryComposing(false); setQueryInput(event.currentTarget.value); }}
              placeholder="搜索商品名称或商品 ID"
            />
            {queryInput && (
              <button
                type="button"
                className="icon-btn absolute right-1 top-0.5 h-8 w-8"
                aria-label="清空商品搜索"
                onClick={() => { setQueryInput(""); setQuery(""); searchRef.current?.focus(); }}
              >
                <X size={14} />
              </button>
            )}
          </div>
          <span className="ml-auto text-xs text-slate-500">已加载 {productItems.length} 件商品</span>
        </div>
        <div className="overflow-x-auto">
          <table>
            <thead>
              <tr><th>商品</th><th>所属账号</th><th>商品 ID</th><th>价格 / 状态</th><th>AI 状态</th><th>知识 / FAQ</th><th>最后更新</th><th>操作</th></tr>
            </thead>
            <tbody>
              {productItems.map((product) => (
                <tr key={product.id}>
                  <td>
                    <div className="flex items-center gap-3">
                      <ProductImage url={product.image_url} />
                      <div><b>{product.name}</b><p className="mt-1 text-xs text-slate-500">{product.category || "未分类"}</p></div>
                    </div>
                  </td>
                  <td>{accounts.data?.find((item) => item.id === product.account_id)?.nickname || "-"}</td>
                  <td className="font-mono text-xs">{product.external_product_id}</td>
                  <td><b>¥{product.price ?? 0}</b><div className="mt-1"><StatusBadge tone={product.status === "DISABLED" ? "danger" : "success"}>{product.status === "DISABLED" ? "已停用" : "在售"}</StatusBadge></div></td>
                  <td>
                    <button
                      onClick={() => toggle.mutate(product)}
                      disabled={toggle.isPending || product.status === "DISABLED"}
                      className={`badge ${product.ai_enabled ? "badge-green" : ""}`}
                    >
                      <Bot size={12} />{product.ai_enabled ? "自动回复 ON" : "自动回复 OFF"}
                    </button>
                  </td>
                  <td>{product.knowledge_count ?? 0} / {product.faq_count ?? 0}</td>
                  <td className="whitespace-nowrap text-xs text-slate-500">{product.updated_at ? new Date(product.updated_at).toLocaleString() : "-"}</td>
                  <td>
                    <div className="flex gap-2">
                      <button className="btn px-2 py-1" onClick={() => open(product)}><Pencil size={13} />编辑</button>
                      <button className="btn px-2 py-1" onClick={() => open(product, "knowledge")}><BookOpen size={13} />知识库</button>
                      <button
                        className="btn btn-danger p-2"
                        disabled={remove.isPending}
                        onClick={() => confirm({ title: "删除这个商品？", description: "商品知识与 FAQ 会一并删除；已有会话历史时后端会拒绝操作。", confirmLabel: "删除商品", tone: "danger", action: () => remove.mutateAsync(product.id!) })}
                        aria-label={`删除 ${product.name}`}
                      ><Trash2 size={13} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {products.isLoading && <div className="p-10 text-center text-sm text-slate-400">正在加载商品…</div>}
          {products.isError && <div className="p-10 text-center text-sm text-red-600">商品加载失败：{errorMessage(products.error)}</div>}
          {!products.isLoading && !products.isError && !productItems.length && (
            <div className="p-10 text-center text-sm text-slate-400">
              {query || accountId || status !== "ACTIVE" ? (
                <><p>没有符合当前条件的商品。</p><button type="button" className="btn mt-3" onClick={clearFilters}>清除筛选</button></>
              ) : "暂无商品，请先新增商品。"}
            </div>
          )}
          {products.hasNextPage && (
            <div className="border-t border-slate-200 p-3 text-center">
              <button className="btn" type="button" disabled={products.isFetchingNextPage} onClick={() => products.fetchNextPage()}>
                {products.isFetchingNextPage ? "正在加载…" : "加载更多商品"}
              </button>
            </div>
          )}
        </div>
      </div>

      {editing && (
        <ProductPanel
          product={editing}
          accounts={accounts.data || []}
          tab={tab}
          setTab={setTab}
          close={closePanel}
        />
      )}
      {publishing && (
        <PublishProductPanel
          accounts={(accounts.data || []).filter((account) => account.adapter_type === "experimental-web")}
          close={() => setPublishing(false)}
        />
      )}
    </>
  );
}

type PublishDraft = {
  accountId: string;
  title: string;
  description: string;
  price: string;
  originalPrice: string;
  delivery: "包邮" | "按距离计费" | "一口价" | "无需邮寄";
  postPrice: string;
  canSelfPickup: boolean;
};

function PublishProductPanel({ accounts, close }: { accounts: Account[]; close: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const idempotencyKey = useRef(crypto.randomUUID());
  const titleRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<"edit" | "review">("edit");
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState("");
  const [formError, setFormError] = useState("");
  const [draft, setDraft] = useState<PublishDraft>({
    accountId: accounts.find((account) => account.status === "CONNECTED")?.id || accounts[0]?.id || "",
    title: "",
    description: "",
    price: "",
    originalPrice: "",
    delivery: "无需邮寄",
    postPrice: "",
    canSelfPickup: true,
  });
  const previews = useMemo(() => files.map((file) => ({ file, url: URL.createObjectURL(file) })), [files]);
  const dirty = Boolean(draft.title || draft.description || draft.price || draft.originalPrice || draft.postPrice || files.length);

  useEffect(() => () => previews.forEach((preview) => URL.revokeObjectURL(preview.url)), [previews]);

  const mutation = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.set("account_id", draft.accountId);
      body.set("idempotency_key", idempotencyKey.current);
      body.set("title", draft.title.trim());
      body.set("description", draft.description.trim());
      body.set("price", draft.price);
      if (draft.originalPrice) body.set("original_price", draft.originalPrice);
      body.set("delivery", draft.delivery);
      body.set("post_price", draft.postPrice || "0");
      body.set("can_self_pickup", String(draft.canSelfPickup));
      files.forEach((file) => body.append("images", file));
      return request<{ status: string; product: Product }>("/api/products/publish", { method: "POST", body });
    },
    onSuccess: async ({ product }) => {
      await queryClient.invalidateQueries({ queryKey: ["products"] });
      toast({ title: "商品已发布", description: `闲鱼商品 ID：${product.external_product_id}`, tone: "success" });
      close();
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const requestClose = async () => {
    if (dirty) {
      const accepted = await confirm({
        title: "放弃未发布的商品？",
        description: "已填写的资料和已选择的图片会丢失。",
        confirmLabel: "放弃发布",
        tone: "danger",
      });
      if (!accepted) return;
    }
    close();
  };

  const update = <K extends keyof PublishDraft>(key: K, value: PublishDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setFormError("");
  };

  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files || []);
    event.target.value = "";
    const next = [...files, ...selected];
    if (next.length > 9) {
      setFileError("最多选择 9 张图片");
      return;
    }
    const invalid = selected.find((file) => !["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 10 * 1024 * 1024 || file.size === 0);
    if (invalid) {
      setFileError(`${invalid.name} 不符合要求：仅支持 JPG、PNG、WebP，单张不超过 10 MB`);
      return;
    }
    setFileError("");
    setFiles(next);
  };

  const review = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.accountId || !accounts.some((account) => account.id === draft.accountId && account.status === "CONNECTED")) {
      setFormError("请选择已连接的真实闲鱼账号");
      return;
    }
    if (draft.title.trim().length < 5) {
      setFormError("商品标题至少填写 5 个字符");
      titleRef.current?.focus();
      return;
    }
    if (draft.description.trim().length < 10) {
      setFormError("商品描述至少填写 10 个字符");
      return;
    }
    if (!(Number(draft.price) > 0)) {
      setFormError("请填写大于 0 的售价");
      return;
    }
    if (draft.delivery === "一口价" && !(Number(draft.postPrice) > 0)) {
      setFormError("选择一口价运费时，请填写运费");
      return;
    }
    if (!files.length) {
      setFileError("请至少选择 1 张商品图片");
      return;
    }
    setFormError("");
    setStep("review");
  };

  return (
    <Drawer
      title="发布到闲鱼"
      description={step === "edit" ? "填写真实商品资料" : "最终确认 · 提交后将对买家公开"}
      closeLabel="关闭发布商品"
      onClose={() => { void requestClose(); }}
      busy={mutation.isPending}
      widthClass="w-[760px] max-w-[95vw]"
      initialFocusRef={titleRef}
    >
        <div className="p-6">
          {step === "edit" ? (
            <form noValidate onSubmit={review} className="space-y-6">
              <div className="publish-warning" role="note"><b>这是外部公开操作</b><span>仅支持本人扫码连接的账号。系统不会自动重试；遇到验证或风控会立即停止。</span></div>
              {formError && <div className="form-error-banner" role="alert">{formError}</div>}
              <FormSection title="商品与账号">
                <div className="grid grid-cols-2 gap-4">
                  <label className="text-sm font-semibold">发布账号<select className="input mt-2" value={draft.accountId} onChange={(event) => update("accountId", event.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.nickname} · {account.status === "CONNECTED" ? "已连接" : "未连接"}</option>)}</select></label>
                  <label className="text-sm font-semibold">售价（元）<input className="input mt-2" type="number" min="0.01" step="0.01" value={draft.price} onChange={(event) => update("price", event.target.value)} /></label>
                  <label className="col-span-2 text-sm font-semibold">商品标题<input ref={titleRef} className="input mt-2" maxLength={60} value={draft.title} onChange={(event) => update("title", event.target.value)} aria-describedby="publish-title-help" /><small id="publish-title-help" className="field-help">5–60 个字符，闲鱼会根据标题和图片识别类目</small></label>
                  <label className="col-span-2 text-sm font-semibold">商品描述<textarea className="input mt-2 min-h-32 resize-none" maxLength={5000} value={draft.description} onChange={(event) => update("description", event.target.value)} /></label>
                  <label className="text-sm font-semibold">原价（选填）<input className="input mt-2" type="number" min="0.01" step="0.01" value={draft.originalPrice} onChange={(event) => update("originalPrice", event.target.value)} /></label>
                  <label className="text-sm font-semibold">发货方式<select className="input mt-2" value={draft.delivery} onChange={(event) => update("delivery", event.target.value as PublishDraft["delivery"])}><option>包邮</option><option>按距离计费</option><option>一口价</option><option>无需邮寄</option></select></label>
                  {draft.delivery === "一口价" && <label className="text-sm font-semibold">运费（元）<input className="input mt-2" type="number" min="0.01" step="0.01" value={draft.postPrice} onChange={(event) => update("postPrice", event.target.value)} /></label>}
                  <label className="mt-7 flex items-center gap-2 text-sm font-semibold"><input type="checkbox" checked={draft.canSelfPickup} onChange={(event) => update("canSelfPickup", event.target.checked)} />支持自提</label>
                </div>
              </FormSection>
              <FormSection title="商品图片" description="选择 1–9 张 JPG、PNG 或 WebP；单张不超过 10 MB。第一张为主图。">
                <label className="publish-upload"><Upload size={22} aria-hidden="true" /><b>选择商品图片</b><span>点击打开文件选择器</span><input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={chooseFiles} /></label>
                {fileError && <p className="field-error" role="alert">{fileError}</p>}
                {!!previews.length && <div className="publish-image-grid">{previews.map(({ file, url }, index) => <figure key={`${file.name}-${file.lastModified}`}><img src={url} alt={`待发布图片 ${index + 1}`} /><figcaption><span>{index === 0 ? "主图" : `${index + 1}`}</span><button type="button" onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label={`移除 ${file.name}`}><X size={14} /></button></figcaption></figure>)}</div>}
              </FormSection>
              <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-white/95 py-4 backdrop-blur"><button type="button" className="btn" onClick={() => { void requestClose(); }}>取消</button><button className="btn btn-primary">检查并继续</button></div>
            </form>
          ) : (
            <div className="space-y-6">
              {formError && <div className="form-error-banner" role="alert">{formError}</div>}
              <section className="publish-review" aria-label="发布内容确认"><div><span>账号</span><b>{accounts.find((account) => account.id === draft.accountId)?.nickname}</b></div><div><span>标题</span><b>{draft.title}</b></div><div><span>售价</span><b>¥{Number(draft.price).toFixed(2)}</b></div><div><span>发货</span><b>{draft.delivery}{draft.delivery === "一口价" ? ` · ¥${Number(draft.postPrice).toFixed(2)}` : ""}</b></div><div className="col-span-2"><span>描述</span><p>{draft.description}</p></div><div className="col-span-2"><span>图片</span><div className="publish-image-grid compact">{previews.map(({ file, url }, index) => <figure key={`${file.name}-${index}`}><img src={url} alt={`确认图片 ${index + 1}`} /></figure>)}</div></div></section>
              <div className="publish-final-note">点击“确认发布”后，商品会立即出现在闲鱼并可被买家看到。每个账号每分钟最多发布 1 件。</div>
              <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-white/95 py-4 backdrop-blur"><button type="button" className="btn" onClick={() => setStep("edit")} disabled={mutation.isPending}>返回修改</button><button type="button" className="btn btn-warning min-w-36" onClick={() => mutation.mutate()} disabled={mutation.isPending} aria-busy={mutation.isPending}>{mutation.isPending ? "正在发布…" : "确认发布到闲鱼"}</button></div>
            </div>
          )}
        </div>
    </Drawer>
  );
}

function ProductPanel({ product, accounts, tab, setTab, close }: { product: Product; accounts: Account[]; tab: string; setTab: (tab: string) => void; close: () => void }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [draft, setDraft] = useState(product);
  const [notice, setNotice] = useState<Notice>(null);
  const [editingKnowledge, setEditingKnowledge] = useState<KnowledgeItem | null>(null);
  const [editingFaq, setEditingFaq] = useState<FAQItem | null>(null);
  const [dirty, setDirty] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const requestClose = async () => {
    if (dirty) {
      const accepted = await confirm({
        title: "放弃未保存的修改？",
        description: "关闭后，本次尚未保存的商品修改会丢失。",
        confirmLabel: "放弃修改",
        tone: "danger",
      });
      if (!accepted) return;
    }
    close();
  };

  const changeTab = async (nextTab: string) => {
    if (nextTab === tab) return;
    if (dirty) {
      const accepted = await confirm({
        title: "切换并放弃未保存的修改？",
        description: "当前标签页中的未保存内容不会保留。",
        confirmLabel: "放弃并切换",
        tone: "danger",
      });
      if (!accepted) return;
      setDirty(false);
    }
    setTab(nextTab);
  };

  const knowledge = useQuery({
    queryKey: ["knowledge", draft.id],
    queryFn: () => request<KnowledgeItem[]>(`/api/products/${draft.id}/knowledge`),
    enabled: Boolean(draft.id),
  });
  const faqs = useQuery({
    queryKey: ["faqs", draft.id],
    queryFn: () => request<FAQItem[]>(`/api/products/${draft.id}/faqs`),
    enabled: Boolean(draft.id),
  });

  const saveProduct = useMutation({
    mutationFn: ({ id, body }: { id?: string; body: Record<string, unknown> }) =>
      request<Product>(id ? `/api/products/${id}` : "/api/products", {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (saved) => {
      setDraft((current) => ({ ...current, ...saved, details: saved.details || current.details }));
      setNotice({ type: "success", text: draft.id ? "商品配置已保存并立即生效" : "商品已创建，现在可以继续配置知识和 FAQ" });
      queryClient.invalidateQueries({ queryKey: ["products"] });
      setDirty(false);
      setFieldErrors({});
    },
    onError: (error) => setNotice({ type: "error", text: errorMessage(error) }),
  });

  const knowledgeMutation = useMutation({
    mutationFn: async (action: { kind: "save"; item: Omit<KnowledgeItem, "id" | "product_id">; id?: string } | { kind: "delete"; id: string }) => {
      if (action.kind === "delete") return request(`/api/products/${draft.id}/knowledge/${action.id}`, { method: "DELETE" });
      return request(action.id ? `/api/products/${draft.id}/knowledge/${action.id}` : `/api/products/${draft.id}/knowledge`, {
        method: action.id ? "PATCH" : "POST",
        body: JSON.stringify(action.item),
      });
    },
    onSuccess: (_, action) => {
      setNotice({ type: "success", text: action.kind === "delete" ? "知识已删除" : action.id ? "知识已更新" : "知识已添加" });
      setEditingKnowledge(null);
      queryClient.invalidateQueries({ queryKey: ["knowledge", draft.id] });
      queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (error) => setNotice({ type: "error", text: errorMessage(error) }),
  });

  const faqMutation = useMutation({
    mutationFn: async (action: { kind: "save"; item: Omit<FAQItem, "id">; id?: string } | { kind: "delete"; id: string }) => {
      if (action.kind === "delete") return request(`/api/products/${draft.id}/faqs/${action.id}`, { method: "DELETE" });
      return request(action.id ? `/api/products/${draft.id}/faqs/${action.id}` : `/api/products/${draft.id}/faqs`, {
        method: action.id ? "PATCH" : "POST",
        body: JSON.stringify(action.item),
      });
    },
    onSuccess: (_, action) => {
      setNotice({ type: "success", text: action.kind === "delete" ? "FAQ 已删除" : action.id ? "FAQ 已更新" : "FAQ 已添加" });
      setEditingFaq(null);
      queryClient.invalidateQueries({ queryKey: ["faqs", draft.id] });
      queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (error) => setNotice({ type: "error", text: errorMessage(error) }),
  });

  async function saveBasic(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const details: ProductDetails = { ...draft.details };
    const detailKeys = [
      ...DETAIL_FIELDS.map(([key]) => key),
      ...DETAIL_TEXTAREAS.map(([key]) => key),
      "purchase_time",
      "invoice",
      "warranty",
      "shipping_origin",
      "shipping_time",
      "freight",
    ];
    detailKeys.forEach((key) => { details[key] = String(form.get(key) || "").trim(); });
    const common = {
      name: String(form.get("name") || "").trim(),
      category: String(form.get("category") || "").trim() || null,
      image_url: String(form.get("image_url") || "").trim() || null,
      price: Number(form.get("price") || 0),
      details,
      ...(draft.id ? { status: form.get("status") } : {}),
    };
    const errors: Record<string, string> = {};
    if (!common.name) errors.name = "请输入商品名称";
    if (!Number.isFinite(common.price) || common.price < 0) errors.price = "请输入有效的非负价格";
    if (!draft.id && !String(form.get("external_product_id") || "").trim()) {
      errors.external_product_id = "请输入商品 ID";
    }
    if (Object.keys(errors).length) {
      setFieldErrors(errors);
      event.currentTarget.querySelector<HTMLElement>(`[name="${Object.keys(errors)[0]}"]`)?.focus();
      return;
    }
    const body = draft.id ? common : {
      ...common,
      account_id: String(form.get("account_id") || draft.account_id),
      external_product_id: String(form.get("external_product_id") || "").trim(),
      ai_enabled: true,
      ai_prompt: String(form.get("ai_prompt") || "").trim(),
    };
    await saveProduct.mutateAsync({ id: draft.id, body });
  }

  async function savePrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await saveProduct.mutateAsync({ id: draft.id, body: { ai_prompt: String(form.get("ai_prompt") || "").trim() } });
  }

  async function saveRules(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await saveProduct.mutateAsync({
      id: draft.id,
      body: {
        details: {
          ...draft.details,
          special_rules: String(form.get("special_rules") || "").trim(),
          forbidden_rules: String(form.get("forbidden_rules") || "").trim(),
        },
      },
    });
  }

  const updateKnowledge = (item: KnowledgeItem, changes: Partial<KnowledgeItem>) => {
    knowledgeMutation.mutate({ kind: "save", id: item.id, item: knowledgePayload({ ...item, ...changes }) });
  };
  const updateFaq = (item: FAQItem, changes: Partial<FAQItem>) => {
    faqMutation.mutate({ kind: "save", id: item.id, item: faqPayload({ ...item, ...changes }) });
  };

  const tabs = [
    ["basic", "基本信息"],
    ["knowledge", `商品知识 ${knowledge.data?.length ?? ""}`],
    ["faq", `FAQ ${faqs.data?.length ?? ""}`],
    ["prompt", "专属 Prompt"],
    ["rules", "回复规则"],
  ];

  return (
    <Drawer
      title={draft.id ? draft.name || "未命名商品" : "新增商品"}
      description="商品独立资料与 AI 配置"
      closeLabel="关闭商品编辑"
      onClose={() => { void requestClose(); }}
      busy={saveProduct.isPending || knowledgeMutation.isPending || faqMutation.isPending}
      headerAfter={draft.id ? <Tabs items={tabs.map(([value, label]) => ({ value, label }))} value={tab} onChange={(value) => { void changeTab(value); }} label="商品编辑栏目" panelId="product-editor-panel" /> : undefined}
    >
        <div id="product-editor-panel" role="tabpanel" className="p-6">
          {notice && <InlineNotice notice={notice} onClose={() => setNotice(null)} />}

          {tab === "basic" && (
            <form onSubmit={saveBasic} onChange={() => setDirty(true)} className="space-y-6" noValidate>
              <FormSection title="归属与展示" description="商品创建后，所属账号和商品 ID 只读，避免会话关联错乱。">
                <div className="grid grid-cols-2 gap-4">
                  <label className="text-sm font-semibold">所属账号
                    {draft.id ? <ReadOnlyValue value={accounts.find((account) => account.id === draft.account_id)?.nickname || draft.account_id} /> : <select className="input mt-2" name="account_id" defaultValue={draft.account_id} required>{accounts.map((account) => <option key={account.id} value={account.id}>{account.nickname} · {account.status}</option>)}</select>}
                  </label>
                  <label className="text-sm font-semibold">商品 ID
                    {draft.id ? <ReadOnlyValue value={draft.external_product_id || "-"} mono /> : <><input name="external_product_id" className="input mt-2" defaultValue={draft.external_product_id || ""} required aria-invalid={Boolean(fieldErrors.external_product_id)} aria-describedby={fieldErrors.external_product_id ? "product-external-id-error" : undefined} placeholder="闲鱼商品 ID 或内部唯一编号" />{fieldErrors.external_product_id && <p id="product-external-id-error" className="field-error">{fieldErrors.external_product_id}</p>}</>}
                  </label>
                  <Field name="name" label="商品名称" value={draft.name} required error={fieldErrors.name} />
                  <Field name="category" label="商品分类" value={draft.category} />
                  <Field name="image_url" label="商品图片 URL" value={draft.image_url} placeholder="https://…" />
                  <Field name="price" label="售价（元）" value={draft.price} type="number" min="0" step="0.01" error={fieldErrors.price} />
                  {draft.id && <label className="text-sm font-semibold">商品状态<select name="status" className="input mt-2" defaultValue={draft.status || "ACTIVE"}><option value="ACTIVE">在售</option><option value="DISABLED">停用</option></select></label>}
                </div>
              </FormSection>

              <FormSection title="规格与成色" description="字段为空时 AI 会明确表示未知，不会自行补全。">
                <div className="grid grid-cols-2 gap-4">{DETAIL_FIELDS.map(([key, label]) => <Field key={key} name={key} label={label} value={draft.details?.[key]} />)}</div>
              </FormSection>

              <FormSection title="商品说明">
                <div className="grid grid-cols-2 gap-4">{DETAIL_TEXTAREAS.slice(0, 5).map(([key, label, placeholder]) => <TextAreaField key={key} name={key} label={label} value={draft.details?.[key]} placeholder={placeholder} />)}</div>
              </FormSection>

              <FormSection title="购买、维修与保障">
                <div className="grid grid-cols-2 gap-4">
                  <Field name="purchase_time" label="购买时间" value={draft.details?.purchase_time} placeholder="例如：2025 年 11 月" />
                  <Field name="invoice" label="发票情况" value={draft.details?.invoice} />
                  <TextAreaField name="repair_history" label="维修情况" value={draft.details?.repair_history} />
                  <TextAreaField name="warranty" label="保修情况" value={draft.details?.warranty} />
                </div>
              </FormSection>

              <FormSection title="发货与售后">
                <div className="grid grid-cols-2 gap-4">
                  <Field name="shipping_origin" label="发货地" value={draft.details?.shipping_origin} />
                  <Field name="shipping_time" label="发货时间" value={draft.details?.shipping_time ?? draft.details?.shipping} placeholder="例如：付款后 24 小时内" />
                  <Field name="freight" label="运费" value={draft.details?.freight} />
                  {DETAIL_TEXTAREAS.slice(6).map(([key, label, placeholder]) => <TextAreaField key={key} name={key} label={label} value={draft.details?.[key]} placeholder={placeholder} />)}
                </div>
              </FormSection>

              {!draft.id && <FormSection title="商品专属 Prompt" description="只定义语气和回答方式；商品事实请在创建后录入知识库。"><TextAreaField name="ai_prompt" label="Prompt" value={draft.ai_prompt} rows={5} /></FormSection>}
              <FormActions close={() => { void requestClose(); }} pending={saveProduct.isPending} label={draft.id ? "保存商品资料" : "创建商品"} />
            </form>
          )}

          {tab === "knowledge" && draft.id && (
            <>
              <KnowledgeForm
                key={editingKnowledge?.id || "new-knowledge"}
                initial={editingKnowledge}
                pending={knowledgeMutation.isPending}
                onCancel={() => setEditingKnowledge(null)}
                onSave={(item) => knowledgeMutation.mutateAsync({ kind: "save", id: editingKnowledge?.id, item })}
              />
              {knowledge.isLoading && <PanelState>正在加载商品知识…</PanelState>}
              {knowledge.isError && <PanelState error>知识加载失败：{errorMessage(knowledge.error)}</PanelState>}
              <div className="space-y-3">
                {knowledge.data?.map((item) => (
                  <div key={item.id} className={`card p-4 ${item.enabled ? "" : "opacity-60"}`}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2"><b>{item.title}</b><span className="badge">{categoryLabel(item.category)}</span><span className="badge">优先级 {item.priority}</span><span className={`badge ${item.enabled ? "badge-green" : ""}`}>{item.enabled ? "已启用" : "已禁用"}</span></div>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{item.content}</p>
                        <p className="mt-2 text-[11px] text-slate-400">来源：{item.source || "manual"}</p>
                      </div>
                      <ItemActions
                        pending={knowledgeMutation.isPending}
                        enabled={item.enabled}
                        onToggle={() => updateKnowledge(item, { enabled: !item.enabled })}
                        onUp={() => updateKnowledge(item, { priority: item.priority + 1 })}
                        onDown={() => updateKnowledge(item, { priority: item.priority - 1 })}
                        onEdit={() => setEditingKnowledge(item)}
                        onDelete={() => confirm({ title: "删除这条商品知识？", description: "删除后 AI 将不再使用这条事实。", confirmLabel: "删除知识", tone: "danger", action: () => knowledgeMutation.mutateAsync({ kind: "delete", id: item.id }) })}
                      />
                    </div>
                  </div>
                ))}
              </div>
              {!knowledge.isLoading && !knowledge.data?.length && <PanelState>还没有商品知识，请添加第一条。</PanelState>}
            </>
          )}

          {tab === "faq" && draft.id && (
            <>
              <FAQForm
                key={editingFaq?.id || "new-faq"}
                initial={editingFaq}
                pending={faqMutation.isPending}
                onCancel={() => setEditingFaq(null)}
                onSave={(item) => faqMutation.mutateAsync({ kind: "save", id: editingFaq?.id, item })}
              />
              {faqs.isLoading && <PanelState>正在加载 FAQ…</PanelState>}
              {faqs.isError && <PanelState error>FAQ 加载失败：{errorMessage(faqs.error)}</PanelState>}
              <div className="space-y-3">
                {faqs.data?.map((item) => (
                  <div key={item.id} className={`card p-4 ${item.enabled ? "" : "opacity-60"}`}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2"><b>Q：{item.question}</b><span className="badge">优先级 {item.priority}</span><span className={`badge ${item.enabled ? "badge-green" : ""}`}>{item.enabled ? "已启用" : "已禁用"}</span></div>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">A：{item.answer}</p>
                        {!!item.keywords?.length && <div className="mt-2 flex flex-wrap gap-1">{item.keywords.map((keyword) => <span className="badge" key={keyword}>{keyword}</span>)}</div>}
                      </div>
                      <ItemActions
                        pending={faqMutation.isPending}
                        enabled={item.enabled}
                        onToggle={() => updateFaq(item, { enabled: !item.enabled })}
                        onUp={() => updateFaq(item, { priority: item.priority + 1 })}
                        onDown={() => updateFaq(item, { priority: item.priority - 1 })}
                        onEdit={() => setEditingFaq(item)}
                        onDelete={() => confirm({ title: "删除这条 FAQ？", description: "删除后 AI 将不再使用这组问答。", confirmLabel: "删除 FAQ", tone: "danger", action: () => faqMutation.mutateAsync({ kind: "delete", id: item.id }) })}
                      />
                    </div>
                  </div>
                ))}
              </div>
              {!faqs.isLoading && !faqs.data?.length && <PanelState>还没有 FAQ，请添加常见问题。</PanelState>}
            </>
          )}

          {tab === "prompt" && draft.id && (
            <form onSubmit={savePrompt} onChange={() => setDirty(true)} className="space-y-5" noValidate>
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-900">这里定义当前商品的客服语气、表达风格和回答偏好。价格、参数、成色等事实请写入商品知识或 FAQ；字段为空时 AI 不会脑补。</div>
              <TextAreaField name="ai_prompt" label="商品专属 Prompt" value={draft.ai_prompt} rows={16} placeholder="例如：回答配置问题时专业直接；询问成色时主动说明已有瑕疵；不要使用夸张销售语言。" />
              <FormActions close={() => { void requestClose(); }} pending={saveProduct.isPending} label="保存 Prompt" />
            </form>
          )}

          {tab === "rules" && draft.id && (
            <form onSubmit={saveRules} onChange={() => setDirty(true)} className="space-y-5" noValidate>
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">商品规则会与全局规则共同交给 AI，并由后端发送守卫再次校验。规则不能授予退款、赔偿、改价等业务权限。</div>
              <TextAreaField name="special_rules" label="特殊回复规则" value={draft.details?.special_rules} rows={9} placeholder="例如：买家询问成色时，必须明确提及右下角的小磕碰。" />
              <TextAreaField name="forbidden_rules" label="禁止回答规则" value={draft.details?.forbidden_rules} rows={9} placeholder="例如：没有记录电池健康度时禁止给出具体百分比；禁止承诺包邮。" />
              <FormActions close={() => { void requestClose(); }} pending={saveProduct.isPending} label="保存回复规则" />
            </form>
          )}
        </div>
    </Drawer>
  );
}

function KnowledgeForm({ initial, pending, onSave, onCancel }: { initial: KnowledgeItem | null; pending: boolean; onSave: (item: Omit<KnowledgeItem, "id" | "product_id">) => Promise<unknown>; onCancel: () => void }) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    await onSave({
      title: String(form.get("title") || "").trim(),
      content: String(form.get("content") || "").trim(),
      category: String(form.get("category") || "other"),
      priority: Number(form.get("priority") || 0),
      enabled: form.get("enabled") === "on",
      source: initial?.source || "manual",
    });
    if (!initial) element.reset();
  }
  return <form noValidate onSubmit={submit} className="card mb-5 grid grid-cols-2 gap-3 bg-slate-50 p-4"><div className="col-span-2 flex items-center justify-between"><b>{initial ? "编辑商品知识" : "新增商品知识"}</b>{initial && <button type="button" className="text-xs text-slate-500" onClick={onCancel}>取消编辑</button>}</div><Field name="title" label="标题" value={initial?.title} required /><label className="text-sm font-semibold">分类<select name="category" className="input mt-2" defaultValue={initial?.category || "parameter"}><option value="parameter">参数</option><option value="condition">成色</option><option value="shipping">发货</option><option value="after_sales">售后</option><option value="compatibility">兼容性</option><option value="usage">使用</option><option value="manual">说明书</option><option value="other">其他</option></select></label><label className="col-span-2 text-sm font-semibold">内容<textarea name="content" className="resize-none input mt-2 min-h-24" defaultValue={initial?.content || ""} required /></label><Field name="priority" label="优先级（越大越优先）" value={initial?.priority ?? 0} type="number" step="1" /><label className="mt-7 flex items-center gap-2 text-sm font-semibold"><input type="checkbox" name="enabled" defaultChecked={initial?.enabled ?? true} />启用这条知识</label><button disabled={pending} className="btn btn-primary col-span-2">{pending ? "正在保存…" : initial ? "保存修改" : "添加知识"}</button></form>;
}

function FAQForm({ initial, pending, onSave, onCancel }: { initial: FAQItem | null; pending: boolean; onSave: (item: Omit<FAQItem, "id">) => Promise<unknown>; onCancel: () => void }) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    await onSave({
      question: String(form.get("question") || "").trim(),
      answer: String(form.get("answer") || "").trim(),
      keywords: String(form.get("keywords") || "").split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
      priority: Number(form.get("priority") || 0),
      enabled: form.get("enabled") === "on",
    });
    if (!initial) element.reset();
  }
  return <form noValidate onSubmit={submit} className="card mb-5 grid grid-cols-2 gap-3 bg-slate-50 p-4"><div className="col-span-2 flex items-center justify-between"><b>{initial ? "编辑 FAQ" : "新增 FAQ"}</b>{initial && <button type="button" className="text-xs text-slate-500" onClick={onCancel}>取消编辑</button>}</div><Field name="question" label="问题" value={initial?.question} required /><Field name="keywords" label="关键词（逗号分隔）" value={initial?.keywords?.join("，")} /><label className="col-span-2 text-sm font-semibold">答案<textarea name="answer" className="resize-none input mt-2 min-h-24" defaultValue={initial?.answer || ""} required /></label><Field name="priority" label="优先级（越大越优先）" value={initial?.priority ?? 0} type="number" step="1" /><label className="mt-7 flex items-center gap-2 text-sm font-semibold"><input type="checkbox" name="enabled" defaultChecked={initial?.enabled ?? true} />启用这条 FAQ</label><button disabled={pending} className="btn btn-primary col-span-2">{pending ? "正在保存…" : initial ? "保存修改" : "添加 FAQ"}</button></form>;
}

function ItemActions({ pending, enabled, onToggle, onUp, onDown, onEdit, onDelete }: { pending: boolean; enabled: boolean; onToggle: () => void; onUp: () => void; onDown: () => void; onEdit: () => void; onDelete: () => void }) {
  return <div className="flex shrink-0 items-center gap-1"><button className="btn p-2" disabled={pending} onClick={onUp} title="提高优先级"><ChevronUp size={14} /></button><button className="btn p-2" disabled={pending} onClick={onDown} title="降低优先级"><ChevronDown size={14} /></button><button className="btn p-2" disabled={pending} onClick={onToggle} title={enabled ? "禁用" : "启用"}><Power size={14} /></button><button className="btn p-2" disabled={pending} onClick={onEdit} title="编辑"><Pencil size={14} /></button><button className="btn btn-danger p-2" disabled={pending} onClick={onDelete} title="删除"><Trash2 size={14} /></button></div>;
}

function FormSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <section className="rounded-xl border border-slate-200 p-5"><div className="mb-4"><h3 className="font-bold">{title}</h3>{description && <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>}</div>{children}</section>;
}

function FormActions({ close, pending, label }: { close: () => void; pending: boolean; label: string }) {
  return <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-white/95 py-4 backdrop-blur"><button type="button" className="btn" onClick={close}>关闭</button><button disabled={pending} className="btn btn-primary">{pending ? "正在保存…" : label}</button></div>;
}

function Field({ name, label, value, type = "text", required = false, placeholder, min, step, error }: { name: string; label: string; value?: unknown; type?: string; required?: boolean; placeholder?: string; min?: string; step?: string; error?: string }) {
  return <FormField id={`product-${name}`} label={label} required={required} error={error}><input name={name} type={type} min={min} step={step} className="input mt-2" defaultValue={displayValue(value)} placeholder={placeholder} /></FormField>;
}

function TextAreaField({ name, label, value, placeholder, rows = 3 }: { name: string; label: string; value?: unknown; placeholder?: string; rows?: number }) {
  return <FormField id={`product-${name}`} label={label}><textarea name={name} rows={rows} className="resize-none input mt-2 leading-6" defaultValue={displayValue(value)} placeholder={placeholder} /></FormField>;
}

function ReadOnlyValue({ value, mono = false }: { value: string; mono?: boolean }) {
  return <div className={`input mt-2 cursor-not-allowed bg-slate-100 text-slate-500 ${mono ? "font-mono text-xs" : ""}`}>{value}</div>;
}

function ProductImage({ url }: { url?: string | null }) {
  return url ? <div className="h-12 w-12 shrink-0 rounded-lg bg-slate-100 bg-cover bg-center" style={{ backgroundImage: `url(${JSON.stringify(url)})` }} /> : <div className="grid h-12 w-12 shrink-0 place-items-center rounded-lg bg-slate-100 text-lg">📦</div>;
}

function InlineNotice({ notice, onClose }: { notice: NonNullable<Notice>; onClose: () => void }) {
  return <div className={`mb-4 flex items-center justify-between rounded-xl border px-4 py-3 text-sm ${notice.type === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-700"}`}><span>{notice.text}</span><button onClick={onClose} aria-label="关闭提示"><X size={15} /></button></div>;
}

function PanelState({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={`my-6 rounded-xl border border-dashed p-8 text-center text-sm ${error ? "border-red-200 text-red-600" : "border-slate-200 text-slate-400"}`}>{children}</div>;
}

function knowledgePayload(item: KnowledgeItem): Omit<KnowledgeItem, "id" | "product_id"> {
  return { title: item.title, content: item.content, category: item.category, priority: item.priority, enabled: item.enabled, source: item.source || "manual" };
}

function faqPayload(item: FAQItem): Omit<FAQItem, "id"> {
  return { question: item.question, answer: item.answer, keywords: item.keywords || [], priority: item.priority, enabled: item.enabled };
}

function categoryLabel(category: string) {
  return ({ parameter: "参数", condition: "成色", shipping: "发货", after_sales: "售后", compatibility: "兼容性", usage: "使用", manual: "说明书", other: "其他" } as Record<string, string>)[category] || category;
}

function displayValue(value: unknown) {
  return typeof value === "string" || typeof value === "number" ? value : "";
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试";
}
