"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  History,
  Loader2,
  MessageSquareWarning,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, ReactNode, useEffect, useState } from "react";

import { request } from "@/lib/api";

interface ReplyRules {
  minimum_confidence: number;
  shop_rules: string;
  price_negotiation_reply: string;
  knowledge_gap_reply: string;
  forbidden_reply_phrases: string[];
  smart_silence_enabled: boolean;
  silence_acknowledgements: boolean;
  silence_thanks: boolean;
  silence_emoji_only: boolean;
  silence_custom_phrases: string[];
  silence_confidence_threshold: number;
  greeting_cooldown_minutes: number;
}

interface RuntimeSettings {
  debounce_ms: number;
  history_limit: number;
  ignored_message_prefixes: string[];
}

const EMPTY_REPLY_RULES: ReplyRules = {
  minimum_confidence: 0.65,
  shop_rules: "",
  price_negotiation_reply: "",
  knowledge_gap_reply: "",
  forbidden_reply_phrases: [],
  smart_silence_enabled: true,
  silence_acknowledgements: true,
  silence_thanks: true,
  silence_emoji_only: true,
  silence_custom_phrases: [],
  silence_confidence_threshold: 0.85,
  greeting_cooldown_minutes: 10,
};

const EMPTY_RUNTIME_SETTINGS: RuntimeSettings = {
  debounce_ms: 1500,
  history_limit: 16,
  ignored_message_prefixes: [],
};

function uniqueLines(value: string): string[] {
  return [...new Set(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))];
}

function ErrorPanel({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="card max-w-5xl border-red-200 p-8 text-center">
      <AlertCircle className="mx-auto text-red-500" size={30} />
      <h2 className="mt-3 font-bold text-slate-900">配置加载失败</h2>
      <p className="mt-1 text-sm text-red-700">{message}</p>
      <button className="btn mt-5" type="button" onClick={retry}>
        <RefreshCw size={15} />重新加载
      </button>
    </div>
  );
}

function FormMessage({ error, notice }: { error: string; notice: string }) {
  if (error) {
    return (
      <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        <AlertCircle className="mt-0.5 shrink-0" size={16} />
        <span>{error}</span>
      </div>
    );
  }
  if (notice) {
    return (
      <div role="status" className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
        <CheckCircle2 className="mt-0.5 shrink-0" size={16} />
        <span>{notice}</span>
      </div>
    );
  }
  return null;
}

function Section({ icon, title, description, children }: { icon: ReactNode; title: string; description: string; children: ReactNode }) {
  return (
    <section className="border-b p-6 last:border-b-0">
      <div className="mb-5 flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700">{icon}</div>
        <div>
          <h2 className="font-bold text-slate-900">{title}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

export function ReplyRulesView() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ReplyRules>(EMPTY_REPLY_RULES);
  const [forbiddenLines, setForbiddenLines] = useState("");
  const [silenceLines, setSilenceLines] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const rules = useQuery({
    queryKey: ["reply-rules"],
    queryFn: () => request<ReplyRules>("/api/ai/reply-rules"),
    retry: 1,
  });

  useEffect(() => {
    if (!rules.data) return;
    setForm(rules.data);
    setForbiddenLines(rules.data.forbidden_reply_phrases.join("\n"));
    setSilenceLines(rules.data.silence_custom_phrases.join("\n"));
  }, [rules.data]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!Number.isFinite(form.minimum_confidence) || form.minimum_confidence < 0 || form.minimum_confidence > 1) {
      setError("最低置信度必须在 0 到 1 之间。");
      return;
    }
    if (!form.price_negotiation_reply.trim() || !form.knowledge_gap_reply.trim()) {
      setError("砍价回复和知识缺失回复不能为空。");
      return;
    }
    const forbiddenPhrases = uniqueLines(forbiddenLines);
    const silencePhrases = uniqueLines(silenceLines);
    if (forbiddenPhrases.length > 50) {
      setError("禁止发送短语最多可以配置 50 条。");
      return;
    }
    if (silencePhrases.length > 50) {
      setError("自定义静默短语最多可以配置 50 条。");
      return;
    }
    if (form.silence_confidence_threshold < 0.5 || form.silence_confidence_threshold > 1) {
      setError("静默置信度必须在 0.5 到 1 之间。");
      return;
    }

    setSaving(true);
    try {
      const result = await request<ReplyRules>("/api/ai/reply-rules", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          shop_rules: form.shop_rules.trim(),
          price_negotiation_reply: form.price_negotiation_reply.trim(),
          knowledge_gap_reply: form.knowledge_gap_reply.trim(),
          forbidden_reply_phrases: forbiddenPhrases,
          silence_custom_phrases: silencePhrases,
        }),
      });
      setForm(result);
      setForbiddenLines(result.forbidden_reply_phrases.join("\n"));
      setSilenceLines(result.silence_custom_phrases.join("\n"));
      setNotice("回复规则已保存，后续 AI 决策和自动发送会立即使用新规则。");
      await queryClient.invalidateQueries({ queryKey: ["reply-rules"] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "回复规则保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">回复规则</h1>
        <p className="mt-1 text-sm text-slate-500">控制 AI 自动发送门槛和兜底话术。模型给出建议，后端规则决定是否允许发送。</p>
      </div>
      {rules.isLoading ? (
        <div className="card max-w-5xl space-y-4 p-6"><div className="skeleton h-20" /><div className="skeleton h-56" /><div className="skeleton h-44" /></div>
      ) : rules.isError ? (
        <ErrorPanel message={rules.error instanceof Error ? rules.error.message : "无法读取回复规则。"} retry={() => rules.refetch()} />
      ) : (
        <form className="card max-w-5xl overflow-hidden" onSubmit={save} noValidate>
          <Section icon={<ShieldCheck size={20} />} title="自动发送门槛" description="低于门槛的回复不会自动发送，并交给人工确认。">
            <label className="block max-w-sm text-sm font-semibold">
              最低置信度
              <div className="mt-2 flex items-center gap-3">
                <input
                  aria-label="最低置信度"
                  className="input"
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  required
                  value={form.minimum_confidence}
                  onChange={(event) => setForm({ ...form, minimum_confidence: Number(event.target.value) })}
                />
                <span className="min-w-14 text-sm font-bold text-blue-700">{Math.round(form.minimum_confidence * 100)}%</span>
              </div>
              <span className="mt-1 block text-xs font-normal text-slate-400">建议保持在 0.60–0.80；越高越谨慎，转人工次数也会增加。</span>
            </label>
          </Section>

          <Section icon={<MessageSquareWarning size={20} />} title="智能静默" description="没有新问题时不打扰买家。静默会写入 AI 日志，但不会生成聊天气泡，也不会调用发送接口。">
            <div className="space-y-5">
              <label className="flex items-center gap-3 rounded-xl border p-4 text-sm font-semibold">
                <input type="checkbox" checked={form.smart_silence_enabled} onChange={(event) => setForm({ ...form, smart_silence_enabled: event.target.checked })} />
                开启智能静默
              </label>
              <div className="grid gap-3 md:grid-cols-3">
                {[
                  ["silence_acknowledgements", "确认类消息", "好的、收到、明白了"],
                  ["silence_thanks", "致谢类消息", "谢谢、辛苦了"],
                  ["silence_emoji_only", "纯表情或标点", "👍、😊、……"],
                ].map(([key, label, example]) => (
                  <label className="rounded-xl border p-4 text-sm" key={key}>
                    <span className="flex items-center gap-2 font-semibold">
                      <input
                        type="checkbox"
                        disabled={!form.smart_silence_enabled}
                        checked={Boolean(form[key as keyof ReplyRules])}
                        onChange={(event) => setForm({ ...form, [key]: event.target.checked })}
                      />
                      {label}
                    </span>
                    <span className="mt-2 block text-xs text-slate-400">例如：{example}</span>
                  </label>
                ))}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="text-sm font-semibold">
                  模型静默最低置信度
                  <input className="input mt-2" type="number" min={0.5} max={1} step={0.01} disabled={!form.smart_silence_enabled} value={form.silence_confidence_threshold} onChange={(event) => setForm({ ...form, silence_confidence_threshold: Number(event.target.value) })} />
                  <span className="mt-1 block text-xs font-normal text-slate-400">低于该值时宁可回复，避免漏答买家的真实问题。</span>
                </label>
                <label className="text-sm font-semibold">
                  重复问候冷却时间（分钟）
                  <input className="input mt-2" type="number" min={1} max={120} step={1} disabled={!form.smart_silence_enabled} value={form.greeting_cooldown_minutes} onChange={(event) => setForm({ ...form, greeting_cooldown_minutes: Number(event.target.value) })} />
                  <span className="mt-1 block text-xs font-normal text-slate-400">近期已回复过买家时，不再反复回应“在吗”“你好”。</span>
                </label>
              </div>
              <label className="block text-sm font-semibold">
                自定义静默短语
                <textarea className="resize-none input mt-2 min-h-28 leading-6" disabled={!form.smart_silence_enabled} value={silenceLines} onChange={(event) => setSilenceLines(event.target.value)} placeholder={"先这样\n晚点再说"} />
                <span className="mt-1 block text-xs font-normal text-slate-400">每行一个，仅完整匹配时静默；带有新问题或问号的消息不会被该规则拦截。</span>
              </label>
            </div>
          </Section>

          <Section icon={<Settings2 size={20} />} title="店铺业务规则" description="这些规则会与全局 Prompt、商品 Prompt 和商品知识一起提供给模型。">
            <label className="block text-sm font-semibold">
              店铺规则
              <textarea
                className="resize-none input mt-2 min-h-36 leading-6"
                maxLength={5000}
                value={form.shop_rules}
                onChange={(event) => setForm({ ...form, shop_rules: event.target.value })}
                placeholder="例如：不得承诺退款、赔偿、改价或修改订单。"
              />
              <span className="mt-1 block text-right text-xs font-normal text-slate-400">{form.shop_rules.length} / 5000</span>
            </label>
          </Section>

          <Section icon={<MessageSquareWarning size={20} />} title="固定兜底话术" description="命中砍价或知识缺失场景时使用，避免模型自行承诺或猜测。">
            <div className="grid gap-4 md:grid-cols-2">
              <label className="text-sm font-semibold">
                砍价回复
                <textarea
                  className="resize-none input mt-2 min-h-28 leading-6"
                  maxLength={500}
                  required
                  value={form.price_negotiation_reply}
                  onChange={(event) => setForm({ ...form, price_negotiation_reply: event.target.value })}
                />
              </label>
              <label className="text-sm font-semibold">
                知识缺失回复
                <textarea
                  className="resize-none input mt-2 min-h-28 leading-6"
                  maxLength={500}
                  required
                  value={form.knowledge_gap_reply}
                  onChange={(event) => setForm({ ...form, knowledge_gap_reply: event.target.value })}
                />
              </label>
            </div>
          </Section>

          <Section icon={<AlertCircle size={20} />} title="禁止发送短语" description="每行一个短语。AI 回复只要包含其中任意一项，后端就会阻止自动发送。">
            <label className="block text-sm font-semibold">
              禁止短语
              <textarea
                className="resize-none input mt-2 min-h-36 font-mono text-sm leading-6"
                value={forbiddenLines}
                onChange={(event) => setForbiddenLines(event.target.value)}
                placeholder={"保证退款\n绝对正品\n最低价承诺"}
              />
              <span className="mt-1 block text-xs font-normal text-slate-400">空行会被忽略，重复内容会在保存时自动合并，最多 50 条。</span>
            </label>
          </Section>

          <div className="space-y-4 border-t bg-slate-50/70 p-6">
            <FormMessage error={error} notice={notice} />
            <div className="flex justify-end">
              <button className="btn btn-primary" disabled={saving}>
                {saving ? <Loader2 className="animate-spin" size={15} /> : <Save size={15} />}
                {saving ? "保存中…" : "保存回复规则"}
              </button>
            </div>
          </div>
        </form>
      )}
    </>
  );
}

export function SystemSettingsView() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<RuntimeSettings>(EMPTY_RUNTIME_SETTINGS);
  const [ignoredPrefixes, setIgnoredPrefixes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const settings = useQuery({
    queryKey: ["runtime-settings"],
    queryFn: () => request<RuntimeSettings>("/api/system/settings"),
    retry: 1,
  });

  useEffect(() => {
    if (!settings.data) return;
    setForm(settings.data);
    setIgnoredPrefixes(settings.data.ignored_message_prefixes.join("\n"));
  }, [settings.data]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!Number.isInteger(form.debounce_ms) || form.debounce_ms < 1000 || form.debounce_ms > 3000) {
      setError("消息合并等待时间必须是 1000–3000 毫秒之间的整数。");
      return;
    }
    if (!Number.isInteger(form.history_limit) || form.history_limit < 10 || form.history_limit > 20) {
      setError("聊天历史条数必须是 10–20 之间的整数。");
      return;
    }
    const messagePrefixes = uniqueLines(ignoredPrefixes);
    if (messagePrefixes.length > 30) {
      setError("忽略消息前缀最多可以配置 30 条。");
      return;
    }

    setSaving(true);
    try {
      const result = await request<RuntimeSettings>("/api/system/settings", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          ignored_message_prefixes: messagePrefixes,
        }),
      });
      setForm(result);
      setIgnoredPrefixes(result.ignored_message_prefixes.join("\n"));
      setNotice("系统运行参数已保存，新收到的消息会立即使用这些设置。");
      await queryClient.invalidateQueries({ queryKey: ["runtime-settings"] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "系统设置保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">系统设置</h1>
        <p className="mt-1 text-sm text-slate-500">配置消息聚合、AI 上下文长度和无需处理的系统消息。</p>
      </div>
      {settings.isLoading ? (
        <div className="card max-w-5xl space-y-4 p-6"><div className="skeleton h-36" /><div className="skeleton h-48" /></div>
      ) : settings.isError ? (
        <ErrorPanel message={settings.error instanceof Error ? settings.error.message : "无法读取系统设置。"} retry={() => settings.refetch()} />
      ) : (
        <form className="card max-w-5xl overflow-hidden" onSubmit={save} noValidate>
          <Section icon={<Clock3 size={20} />} title="消息合并" description="买家连续发出的短消息会先聚合，再统一进入一次完整 AI 处理链。">
            <label className="block max-w-sm text-sm font-semibold">
              合并等待时间（毫秒）
              <input
                className="input mt-2"
                type="number"
                min={1000}
                max={3000}
                step={100}
                required
                value={form.debounce_ms}
                onChange={(event) => setForm({ ...form, debounce_ms: Number(event.target.value) })}
              />
              <span className="mt-1 block text-xs font-normal text-slate-400">范围 1000–3000ms，默认 1500ms。等待越长，越容易合并完整语句。</span>
            </label>
          </Section>

          <Section icon={<History size={20} />} title="聊天上下文" description="数据库保留完整历史；这里只控制每次发送给大模型的最近消息数量。">
            <label className="block max-w-sm text-sm font-semibold">
              最近消息条数
              <input
                className="input mt-2"
                type="number"
                min={10}
                max={20}
                step={1}
                required
                value={form.history_limit}
                onChange={(event) => setForm({ ...form, history_limit: Number(event.target.value) })}
              />
              <span className="mt-1 block text-xs font-normal text-slate-400">范围 10–20 条。更多上下文会增加 Token 消耗。</span>
            </label>
          </Section>

          <Section icon={<MessageSquareWarning size={20} />} title="消息过滤" description="每行一个前缀；以这些文字开头的外部消息只记录或忽略，不触发 AI 回复。">
            <label className="block text-sm font-semibold">
              忽略消息前缀
              <textarea
                className="resize-none input mt-2 min-h-40 font-mono text-sm leading-6"
                value={ignoredPrefixes}
                onChange={(event) => setIgnoredPrefixes(event.target.value)}
                placeholder={"系统通知：\n订单状态更新：\n平台提醒："}
              />
              <span className="mt-1 block text-xs font-normal text-slate-400">空消息和重复外部消息始终会被系统自动过滤；这里用于补充平台系统消息前缀。</span>
            </label>
          </Section>

          <div className="space-y-4 border-t bg-slate-50/70 p-6">
            <FormMessage error={error} notice={notice} />
            <div className="flex justify-end">
              <button className="btn btn-primary" disabled={saving}>
                {saving ? <Loader2 className="animate-spin" size={15} /> : <Save size={15} />}
                {saving ? "保存中…" : "保存系统设置"}
              </button>
            </div>
          </div>
        </form>
      )}
    </>
  );
}
