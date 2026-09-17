"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Eye, EyeOff, FlaskConical, KeyRound, Loader2, Save, ServerCog, ShieldCheck, Trash2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { CursorPage, request } from "@/lib/api";

type ProviderId = "mock" | "openai" | "deepseek" | "openai-compatible";

interface AIConfig {
  provider: ProviderId;
  base_url: string;
  api_key_masked: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  timeout: number;
}

interface AIConfigForm {
  provider: ProviderId;
  base_url: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  timeout: number;
}

const PROVIDERS: Record<ProviderId, { label: string; description: string; baseUrl: string; model: string }> = {
  mock: { label: "Mock（离线开发）", description: "不产生 API 费用，用于验证完整业务流程", baseUrl: "", model: "mock-v1" },
  openai: { label: "OpenAI", description: "OpenAI 官方 Chat Completions API", baseUrl: "https://api.openai.com/v1", model: "" },
  deepseek: { label: "DeepSeek", description: "DeepSeek 官方 OpenAI 兼容接口", baseUrl: "https://api.deepseek.com", model: "deepseek-chat" },
  "openai-compatible": { label: "自定义 OpenAI Compatible", description: "适用于提供标准 Chat Completions 的服务", baseUrl: "", model: "" },
};

const EMPTY_FORM: AIConfigForm = {
  provider: "mock",
  base_url: "",
  model_name: "mock-v1",
  temperature: 0.2,
  max_tokens: 800,
  timeout: 30,
};

export function AISettingsView() {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [form, setForm] = useState<AIConfigForm>(EMPTY_FORM);
  const config = useQuery({ queryKey: ["ai-config"], queryFn: () => request<AIConfig>("/api/ai/config") });

  useEffect(() => {
    if (!config.data) return;
    setForm({
      provider: config.data.provider,
      base_url: config.data.base_url,
      model_name: config.data.model_name,
      temperature: config.data.temperature,
      max_tokens: config.data.max_tokens,
      timeout: config.data.timeout,
    });
  }, [config.data]);

  const isMock = form.provider === "mock";

  function payload() {
    return { ...form, api_key: apiKey, clear_api_key: clearApiKey };
  }

  function selectProvider(provider: ProviderId) {
    const preset = PROVIDERS[provider];
    setNotice("");
    setError("");
    setClearApiKey(false);
    setForm((current) => ({
      ...current,
      provider,
      base_url: preset.baseUrl || (provider === "openai-compatible" ? "" : current.base_url),
      model_name: preset.model || (current.model_name === "mock-v1" ? "" : current.model_name),
    }));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await request("/api/ai/config", {
        method: "PUT",
        body: JSON.stringify(payload()),
      });
      setError("");
      setNotice("模型配置已加密保存，新的 AI 任务会立即使用该配置。");
      setApiKey("");
      setClearApiKey(false);
      await queryClient.invalidateQueries({ queryKey: ["ai-config"] });
    } catch (reason) {
      setNotice("");
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setTesting(true);
    try {
      const result = await request<{ success: boolean; message: string }>("/api/ai/test-connection", {
        method: "POST",
        body: JSON.stringify(payload()),
      });
      if (!result.success) throw new Error(result.message);
      setError("");
      setNotice(result.message);
    } catch (reason) {
      setNotice("");
      setError(reason instanceof Error ? reason.message : "连接失败");
    } finally {
      setTesting(false);
    }
  }

  return (
    <>
      <div className="mb-6"><h1 className="text-2xl font-bold">AI 模型设置</h1><p className="mt-1 text-sm text-slate-500">保存后，模拟器和真实消息处理链会调用这里配置的模型，不使用前端假回复。</p></div>
      <form onSubmit={save} className="card max-w-5xl overflow-hidden" noValidate>
        <div className="flex flex-wrap items-center justify-between gap-4 border-b p-6">
          <div className="flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-xl bg-blue-50 text-blue-700"><ServerCog /></div><div><b>模型服务</b><p className="text-xs text-slate-500">选择服务并验证当前表单，测试不会保存 API Key</p></div></div>
          <span className={`badge ${isMock ? "" : "badge-blue"}`}>{isMock ? "离线模式" : "真实模型"}</span>
        </div>
        {config.isLoading ? <div className="m-6 skeleton h-72" /> : config.isError ? (
          <div className="m-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">配置加载失败，请刷新页面重试。</div>
        ) : (
          <div className="space-y-6 p-6">
            <section>
              <div className="mb-3 text-sm font-semibold">Provider</div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {(Object.keys(PROVIDERS) as ProviderId[]).map((id) => (
                  <button key={id} type="button" onClick={() => selectProvider(id)} className={`rounded-xl border p-4 text-left transition ${form.provider === id ? "border-blue-500 bg-blue-50 ring-2 ring-blue-100" : "border-slate-200 hover:border-slate-300"}`}>
                    <span className="block text-sm font-bold">{PROVIDERS[id].label}</span>
                    <span className="mt-1 block text-xs leading-5 text-slate-500">{PROVIDERS[id].description}</span>
                  </button>
                ))}
              </div>
            </section>
            {!isMock && <section className="grid gap-4 border-t pt-6 md:grid-cols-2">
              <ControlledField label="Base URL" value={form.base_url} onChange={(value) => setForm({ ...form, base_url: value })} placeholder="https://api.example.com/v1" required />
              <ControlledField label="Model Name" value={form.model_name} onChange={(value) => setForm({ ...form, model_name: value })} placeholder="填写服务商提供的模型 ID" required list="model-suggestions" />
              <datalist id="model-suggestions"><option value="gpt-4.1-mini" /><option value="gpt-4.1" /><option value="deepseek-chat" /><option value="deepseek-reasoner" /></datalist>
              <label className="text-sm font-semibold md:col-span-2">API Key <span className="font-normal text-slate-400">当前：{clearApiKey ? "将在保存时移除" : config.data?.api_key_masked || "未设置"}</span>
                <div className="relative mt-2"><KeyRound className="absolute left-3 top-3 text-slate-400" size={16} /><input type={showKey ? "text" : "password"} className="input input-leading-icon input-trailing-icon" value={apiKey} onChange={(event) => { setApiKey(event.target.value); setClearApiKey(false); }} placeholder={config.data?.api_key_masked ? "留空表示继续使用已保存的 Key" : "请输入 API Key"} autoComplete="new-password" /><button type="button" aria-label={showKey ? "隐藏 API Key" : "显示 API Key"} className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-700" onClick={() => setShowKey(!showKey)}>{showKey ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
                {config.data?.api_key_masked && <button type="button" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-red-600" onClick={() => { setApiKey(""); setClearApiKey(true); }}><Trash2 size={13} />移除已保存密钥</button>}
              </label>
            </section>}
            <section className="grid gap-4 border-t pt-6 md:grid-cols-3">
              <NumberField label="Temperature" value={form.temperature} min={0} max={2} step={0.1} onChange={(value) => setForm({ ...form, temperature: value })} hint="越低越稳定，客服建议 0.1–0.4" />
              <NumberField label="Max Tokens" value={form.max_tokens} min={64} max={8192} step={1} onChange={(value) => setForm({ ...form, max_tokens: value })} hint="单次回复最大输出长度" />
              <NumberField label="Timeout（秒）" value={form.timeout} min={1} max={120} step={1} onChange={(value) => setForm({ ...form, timeout: value })} hint="超时后自动转人工" />
            </section>
            <div className="flex items-start gap-2 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-600"><ShieldCheck className="mt-0.5 shrink-0 text-emerald-600" size={17} /><span>API Key 仅提交给本系统后端，使用服务端密钥加密保存；接口响应和页面不会返回完整 Key。测试当前表单不会修改已保存配置。</span></div>
          </div>
        )}
        {error && <div className="mx-6 mb-5 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="mt-0.5 shrink-0" size={16} />{error}</div>}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-slate-50/70 px-6 py-4"><span className="text-sm text-emerald-700">{notice && <><CheckCircle2 size={15} className="mr-1 inline" />{notice}</>}</span><div className="flex gap-2"><button type="button" onClick={test} className="btn" disabled={testing || saving || config.isLoading}>{testing ? <Loader2 className="animate-spin" size={15} /> : <FlaskConical size={15} />}{testing ? "正在验证…" : "测试当前配置"}</button><button className="btn btn-primary" disabled={saving || testing || config.isLoading}>{saving ? <Loader2 className="animate-spin" size={15} /> : <Save size={15} />}{saving ? "保存中…" : "保存并启用"}</button></div></div>
      </form>
    </>
  );
}

function ControlledField({ label, value, onChange, placeholder, required, list }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; required?: boolean; list?: string }) {
  return <label className="text-sm font-semibold">{label}<input className="input mt-2" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} required={required} list={list} /></label>;
}

function NumberField({ label, value, min, max, step, onChange, hint }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void; hint: string }) {
  return <label className="text-sm font-semibold">{label}<input className="input mt-2" type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} required /><span className="mt-1 block text-xs font-normal text-slate-400">{hint}</span></label>;
}

export function GlobalAISettingsView() {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const prompt = useQuery({ queryKey: ["global-prompt"], queryFn: () => request<any>("/api/ai/global-prompt") });
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const result = await request<any>("/api/ai/global-prompt", { method: "PUT", body: JSON.stringify({ content: form.get("content") }) });
      setError(""); setNotice(`已保存 ${result.version}`);
      await queryClient.invalidateQueries({ queryKey: ["global-prompt"] });
    } catch (reason) { setNotice(""); setError(reason instanceof Error ? reason.message : "保存失败"); }
  }
  return <><div className="mb-6"><h1 className="text-2xl font-bold">全局 AI 设置</h1><p className="mt-1 text-sm text-slate-500">定义全店共同身份和安全原则；商品事实与个性化语气仍由每个商品独立配置。</p></div><form noValidate className="card max-w-4xl p-6" onSubmit={save}>{prompt.isLoading ? <div className="skeleton h-96" /> : <><div className="mb-3 flex justify-between"><b>全局 System Prompt</b><span className="badge badge-blue">{prompt.data?.version}</span></div><textarea className="resize-none input min-h-[430px] font-mono text-sm leading-6" name="content" defaultValue={prompt.data?.content} required /></>}{error && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}<div className="mt-5 flex items-center justify-between"><span className="text-sm text-emerald-700">{notice}</span><button className="btn btn-primary"><Save size={15} />保存新版本</button></div></form></>;
}

function Field({ label, name, value, type = "text", step }: { label: string; name: string; value: any; type?: string; step?: string }) {
  return <label className="text-sm font-semibold">{label}<input name={name} type={type} step={step} className="input mt-2" defaultValue={value} /></label>;
}

export function AITestView() {
  const searchParams = useSearchParams();
  const [testProductId, setTestProductId] = useState(searchParams.get("product_id") || "");
  const [result, setResult] = useState<any>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const products = useQuery({ queryKey: ["products"], queryFn: () => request<CursorPage<any>>("/api/products?limit=100") });
  useEffect(() => {
    if (!testProductId && products.data?.items[0]) setTestProductId(products.data.items[0].id);
  }, [products.data, testProductId]);
  async function test(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true);
    const form = new FormData(event.currentTarget);
    try { setResult(await request("/api/ai/test", { method: "POST", body: JSON.stringify({ product_id: form.get("product_id"), message: form.get("message") }), signal: AbortSignal.timeout(125000) })); setError(""); }
    catch (reason) {
      setResult(undefined);
      const timedOut = reason instanceof DOMException && (reason.name === "AbortError" || reason.name === "TimeoutError");
      setError(timedOut ? "测试请求超时，请先在模型设置中测试连接或更换响应更快的模型。" : reason instanceof Error ? reason.message : "测试失败");
    }
    finally { setLoading(false); }
  }
  return <><div className="mb-6"><h1 className="text-2xl font-bold">AI 测试台</h1><p className="mt-1 text-sm text-slate-500">真实调用当前 Provider，并展示商品 Prompt、知识和结构化决策；不会向买家发送。</p></div><div className="grid grid-cols-[420px_1fr] gap-5"><form noValidate onSubmit={test} className="card h-fit p-5"><label className="text-sm font-semibold">选择商品<select className="input mt-2" name="product_id" value={testProductId} onChange={(event) => setTestProductId(event.target.value)}>{products.data?.items.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}</select></label><label className="mt-4 block text-sm font-semibold">模拟用户消息<textarea className="resize-none input mt-2 min-h-36" name="message" defaultValue="这个商品适合我的设备吗？" /></label><button className="btn btn-warning mt-4 w-full" disabled={loading || !products.data?.items.length}>{loading ? <Loader2 className="animate-spin" size={16} /> : <FlaskConical size={16} />}测试</button>{error && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}</form><div className="space-y-4">{result ? <><section className="card p-5"><h2 className="font-bold">AI 最终回复</h2><p className="mt-3 rounded-xl bg-amber-50 p-4 text-sm leading-6">{result.decision.reply}</p></section><section className="card p-5"><h2 className="font-bold">AI 决策</h2><div className="mt-4 grid grid-cols-3 gap-3">{["intent", "confidence", "risk_level", "need_human", "need_clarification", "knowledge_gap", "missing_knowledge", "should_send", "risk_flag", "reason"].map((key) => <div key={key} className="rounded-lg border p-3"><div className="text-[11px] uppercase text-slate-500">{key}</div><b className="mt-1 block break-words text-sm">{result.decision[key] == null ? "—" : String(result.decision[key])}</b></div>)}</div></section><section className="card p-5"><h2 className="font-bold">本次使用的商品专属 Prompt</h2><pre className="mt-3 whitespace-pre-wrap rounded-lg bg-slate-50 p-4 text-sm leading-6">{result.used.product_prompt || "未配置"}</pre></section><section className="card p-5"><h2 className="font-bold">使用的知识与 FAQ</h2><div className="mt-3 space-y-2 text-sm">{result.used.knowledge.map((item: any) => <div className="rounded-lg border p-3" key={item.title}><b>{item.title}</b><p className="text-slate-600">{item.content}</p></div>)}{result.used.faqs.map((item: any) => <div className="rounded-lg border p-3" key={item.question}><b>FAQ · {item.question}</b><p className="text-slate-600">{item.answer}</p></div>)}{!result.used.knowledge.length && !result.used.faqs.length && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-800">本次没有匹配到商品知识或 FAQ。</p>}</div><details className="mt-4"><summary className="cursor-pointer text-sm font-semibold">原始 JSON</summary><pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(result.raw_json, null, 2)}</pre></details></section></> : <div className="card grid min-h-72 place-items-center text-center text-sm text-slate-400">运行一次测试后，这里会显示真实回复、决策、商品 Prompt、知识和原始 JSON。</div>}</div></div></>;
}
