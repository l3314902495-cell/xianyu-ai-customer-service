"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, Cable, CircleOff, Plus, QrCode, RefreshCw, Trash2, Wifi } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { request } from "@/lib/api";
import { useConfirm } from "@/components/confirm-dialog";

type Account = {
  id: string;
  nickname: string;
  external_account_id: string;
  status: "CONNECTED" | "DISCONNECTED" | "CONNECTING" | "ERROR";
  adapter_type: "mock" | "real" | "experimental-web";
  adapter_available: boolean;
  credential_configured: boolean;
  runtime_connected: boolean;
  listener_alive: boolean;
  connection_state: string | null;
  connection_health: {
    updated_at?: string;
    connected_at?: string;
    last_message_at?: string;
    last_frame_age_seconds?: number;
    connection_age_seconds?: number;
    state?: string;
  };
  ai_enabled: boolean;
  last_error: string | null;
  product_count: number;
  conversation_count: number;
};

type QRStart = { session_id: string; qr_image: string; expires_in: number };
type QRPoll = {
  status: "new" | "scanned" | "processing" | "confirmed" | "expired" | "verification_required" | "waiting_helper" | "browser_opened" | "failed";
  verification_url?: string;
  connected?: boolean;
  message?: string;
};
type BrowserLoginStart = { session_id: string; pairing_token: string; profile_key: string; helper_url: string; expires_in: number };

export function AccountsView() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [showQR, setShowQR] = useState(false);
  const [showCookieImport, setShowCookieImport] = useState(false);
  const [qr, setQR] = useState<QRStart | null>(null);
  const [qrStatus, setQRStatus] = useState<QRPoll | null>(null);
  const [browserLogin, setBrowserLogin] = useState<BrowserLoginStart | null>(null);
  const [loginAccountId, setLoginAccountId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: () => request<Account[]>("/api/xianyu/accounts"),
    refetchInterval: 10000,
  });

  const run = useMutation({
    mutationFn: async ({ path, method = "POST", body }: { path: string; method?: string; body?: unknown }) =>
      request<{ warning?: string }>(path, { method, body: body ? JSON.stringify(body) : undefined }),
    onSuccess: async (result) => {
      setError("");
      setNotice(result.warning || "");
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (reason: Error) => {
      setNotice("");
      setError(reason.message);
    },
  });

  async function startQR() {
    setShowQR(true);
    setQR(null);
    setQRStatus(null);
    setError("");
    try {
      setQR(await request<QRStart>("/api/xianyu/accounts/experimental/qr/start", { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "生成二维码失败");
    }
  }

  async function startDedicatedBrowserLogin(accountId?: string) {
    const targetAccountId = accountId || null;
    setLoginAccountId(targetAccountId);
    setShowQR(true);
    setQR(null);
    setBrowserLogin(null);
    setQRStatus({ status: "waiting_helper", message: "正在启动专用 Edge 登录窗口" });
    setError("");
    try {
      const session = await request<BrowserLoginStart>("/api/xianyu/accounts/experimental/browser-login/start", {
        method: "POST",
        body: JSON.stringify(targetAccountId ? { account_id: targetAccountId } : {}),
      });
      setBrowserLogin(session);
      const response = await fetch(session.helper_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: session.session_id,
          pairing_token: session.pairing_token,
          profile_key: session.profile_key,
          api_url: "http://localhost:8000",
        }),
      });
      if (!response.ok) throw new Error("本机登录助手启动失败");
      setQRStatus({
        status: "browser_opened",
        message: targetAccountId
          ? "正在复用该账号的专用 Edge 登录态；仅在确实失效时才需要重新扫码"
          : "请在新打开的专用 Edge 窗口中完成首次登录",
      });
    } catch (reason) {
      setError(reason instanceof Error ? `${reason.message}。请用“一键启动闲鱼AI客服”重新启动系统。` : "启动专用 Edge 登录失败");
      setQRStatus({ status: "failed" });
    }
  }

  useEffect(() => {
    if (!browserLogin || !showQR || ["confirmed", "expired", "failed"].includes(qrStatus?.status ?? "")) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const result = await request<QRPoll>(`/api/xianyu/accounts/experimental/browser-login/${browserLogin.session_id}`);
        if (!active) return;
        setQRStatus(result);
        if (result.status === "confirmed") await queryClient.invalidateQueries({ queryKey: ["accounts"] });
        if (!["confirmed", "expired", "failed"].includes(result.status)) timer = window.setTimeout(poll, 2000);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "查询浏览器登录状态失败");
      }
    };
    timer = window.setTimeout(poll, 1000);
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [browserLogin, showQR, qrStatus?.status, queryClient]);

  useEffect(() => {
    if (!qr || !showQR || ["confirmed", "expired"].includes(qrStatus?.status ?? "")) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      let terminal = false;
      try {
        const result = await request<QRPoll>(`/api/xianyu/accounts/experimental/qr/${qr.session_id}`);
        if (!active) return;
        setQRStatus(result);
        if (result.status === "confirmed") {
          terminal = true;
          await queryClient.invalidateQueries({ queryKey: ["accounts"] });
        } else if (result.status === "expired") {
          terminal = true;
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "查询扫码状态失败");
      } finally {
        if (active && !terminal) timer = window.setTimeout(poll, 3000);
      }
    };
    timer = window.setTimeout(poll, 600);
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [qr, showQR, queryClient]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await request("/api/xianyu/accounts", {
        method: "POST",
        body: JSON.stringify({
          nickname: form.get("nickname"),
          external_account_id: form.get("external_account_id"),
          adapter_type: "mock",
          ai_enabled: true,
        }),
      });
      setShowCreate(false);
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    }
  }

  async function importCookie(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      await request("/api/xianyu/accounts/experimental/cookie", {
        method: "POST",
        body: JSON.stringify({ cookie_text: form.get("cookie_text") }),
      });
      setShowCookieImport(false);
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cookie 导入失败");
    }
  }

  return (
    <>
      <div className="accounts-heading mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold">闲鱼账号</h1>
          <p className="mt-1 text-sm text-slate-500">每个账号拥有独立连接、商品、会话与 AI 开关。</p>
        </div>
        <div className="accounts-actions flex gap-2">
          <button className="btn" onClick={() => setShowCreate(true)}><Plus size={16} /> 添加 Mock 账号</button>
          <button className="btn" onClick={() => setShowCookieImport(true)}><Cable size={16} /> 导入登录 Cookie</button>
          <button className="btn" onClick={startQR}><QrCode size={16} /> 兼容二维码</button>
          <button className="btn btn-primary" onClick={() => startDedicatedBrowserLogin()}><QrCode size={16} /> 添加真实账号</button>
        </div>
      </div>

      <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <AlertTriangle className="mt-0.5 shrink-0" size={18} />
        <div>
          <b>实验性非官方网页版接入</b>
          <p className="mt-1 leading-6">仅支持本人账号主动登录和文本收发。每个真实账号使用独立且持久的专用 Edge Profile，不读取日常 Edge 数据、不保存密码，也不绕过验证码、人脸或滑块。请遵守闲鱼规则并控制自动回复频率。</p>
        </div>
      </div>

      {error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {notice && <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{notice}</div>}
      <div className="account-grid grid grid-cols-2 gap-4">
        {accounts.data?.map((account) => <AccountCard key={account.id} account={account} busy={run.isPending} run={run.mutate} onRelogin={startDedicatedBrowserLogin} />)}
      </div>
      {accounts.isLoading && <div className="skeleton h-44" />}
      {!accounts.isLoading && !accounts.data?.length && <div className="card p-12 text-center text-sm text-slate-500">尚未添加账号。</div>}

      {showQR && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-6">
          <div className="card w-full max-w-md p-6 text-center shadow-2xl">
            <h2 className="text-lg font-bold">连接真实闲鱼账号</h2>
            <p className="mt-2 text-sm text-slate-500">{browserLogin ? (loginAccountId ? "系统会先尝试恢复该账号已保存的浏览器登录态。" : "请在专用 Edge 窗口中完成首次登录及平台要求的本人验证。") : "请使用闲鱼 App 扫码并在手机上确认登录。"}</p>
            {!qr && !browserLogin && !error && <div className="skeleton mx-auto mt-6 h-64 w-64" />}
            {qr && !["confirmed", "verification_required"].includes(qrStatus?.status ?? "") && <img src={qr.qr_image} alt="闲鱼登录二维码" className="mx-auto mt-5 h-64 w-64 rounded-xl border p-2" />}
            <p className="mt-4 text-sm font-semibold">{qrStatusText(qrStatus?.status)}</p>
            {qrStatus?.message && <p className="mt-2 text-sm leading-6 text-slate-600">{qrStatus.message}</p>}
            {browserLogin && !["confirmed", "failed", "expired"].includes(qrStatus?.status ?? "") && (
              <div className="mt-4 rounded-lg bg-blue-50 p-3 text-left text-sm leading-6 text-blue-900">
                每个账号会固定复用自己的专用浏览器资料。已有登录态有效时会直接恢复；失效后才进入扫码和本人验证。验证成功后系统会安全保存更新后的登录态并关闭专用窗口。
              </div>
            )}
            {qrStatus?.status === "verification_required" && (
              <div className="mt-4 rounded-lg bg-amber-50 p-3 text-left text-sm text-amber-900">
                平台要求本人完成人脸验证。验证页完成后可能停留在白屏，也不会自动跳回本系统，这是正常现象；验证完成后直接关闭该页面即可。
                {qrStatus.verification_url && <a className="btn btn-warning mt-3 w-full" href={qrStatus.verification_url} target="_blank" rel="noreferrer">打开人脸验证页面</a>}
                <p className="mt-3 font-semibold">本页会串行检测登录结果，最长等待 15 分钟，请不要关闭本弹窗或刷新账号页面。</p>
              </div>
            )}
            {qrStatus?.status === "confirmed" && (
              <div className={`mt-5 rounded-xl p-4 ${qrStatus.connected ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>
                {qrStatus.connected ? "账号已连接，正在接收闲鱼文本消息。" : "扫码凭据已保存，但长连接尚未建立，请在账号卡片中重试。"}
              </div>
            )}
            <div className="mt-6 flex justify-center gap-2">
              {qrStatus?.status === "expired" && <button className="btn btn-primary" onClick={browserLogin ? () => startDedicatedBrowserLogin(loginAccountId || undefined) : startQR}><RefreshCw size={15} /> 重新开始</button>}
              <button className="btn" onClick={() => setShowQR(false)}>关闭</button>
            </div>
          </div>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-6">
          <form onSubmit={create} className="card w-full max-w-lg p-6 shadow-2xl" noValidate>
            <h2 className="text-lg font-bold">添加 Mock 测试账号</h2>
            <label className="mt-5 block text-sm font-semibold">账号备注名<input className="input mt-2" name="nickname" placeholder="例如：数码店测试账号" required /></label>
            <label className="mt-4 block text-sm font-semibold">测试账号 ID<input className="input mt-2" name="external_account_id" placeholder="例如：mock-shop-02" required /></label>
            <div className="mt-6 flex justify-end gap-2"><button type="button" className="btn" onClick={() => setShowCreate(false)}>取消</button><button className="btn btn-primary">保存账号</button></div>
          </form>
        </div>
      )}

      {showCookieImport && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-6">
          <form onSubmit={importCookie} className="card w-full max-w-2xl p-6 shadow-2xl" noValidate>
            <h2 className="text-lg font-bold">导入闲鱼登录 Cookie</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              仅粘贴你本人账号在闲鱼网页版登录后的完整 Cookie 请求头。系统会先向闲鱼校验登录态，校验通过后再加密保存；页面和日志不会回显 Cookie。
            </p>
            <label className="mt-5 block text-sm font-semibold">
              Cookie
              <textarea
                className="resize-none input mt-2 min-h-44 font-mono text-xs"
                name="cookie_text"
                placeholder="unb=...; cookie2=...; _m_h5_tk=...; ..."
                autoComplete="off"
                required
              />
            </label>
            <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm leading-6 text-amber-900">
              Cookie 等同登录凭据，请勿发送给任何人。只应粘贴到本机 localhost 页面；如果部署到服务器，请先确认该服务器由你控制。
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" className="btn" onClick={() => setShowCookieImport(false)}>取消</button>
              <button className="btn btn-primary">校验并连接</button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}

function AccountCard({ account, busy, run, onRelogin }: { account: Account; busy: boolean; run: (value: { path: string; method?: string; body?: unknown }) => void; onRelogin: (accountId: string) => void }) {
  const confirm = useConfirm();
  const connected = account.status === "CONNECTED" && account.runtime_connected;
  return (
    <article className="card p-5">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`grid h-11 w-11 place-items-center rounded-xl ${connected ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}><Wifi size={21} /></div>
          <div><h2 className="font-bold">{account.nickname}</h2><p className="mt-1 font-mono text-xs text-slate-500">{account.external_account_id}</p></div>
        </div>
        <span className={`badge ${connected ? "badge-green" : account.status === "ERROR" ? "badge-red" : ""}`}>{connected ? "已连接" : account.status === "CONNECTED" ? "正在恢复连接" : statusLabel(account.status)}</span>
      </div>
      <div className="mt-5 grid grid-cols-3 gap-3 rounded-xl bg-slate-50 p-3 text-center">
        <div><b className="block">{account.product_count}</b><span className="text-xs text-slate-500">商品</span></div>
        <div><b className="block">{account.conversation_count}</b><span className="text-xs text-slate-500">会话</span></div>
        <div><b className="block text-xs uppercase">{account.adapter_type}</b><span className="text-xs text-slate-500">接入方式</span></div>
      </div>
      {account.last_error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-xs leading-5 text-red-700">{account.last_error}</p>}
      {account.adapter_type === "experimental-web" && (
        <div className="mt-3 grid grid-cols-2 gap-x-5 gap-y-2 rounded-lg border border-slate-200 bg-white p-3 text-xs">
          <div className="flex justify-between gap-2"><span className="text-slate-500">监听服务</span><b className={account.listener_alive ? "text-emerald-700" : "text-red-600"}>{account.listener_alive ? "运行中" : "未运行"}</b></div>
          <div className="flex justify-between gap-2"><span className="text-slate-500">平台长连接</span><b className={connected ? "text-emerald-700" : "text-amber-700"}>{connected ? "实时在线" : "恢复中"}</b></div>
          <div className="flex justify-between gap-2"><span className="text-slate-500">连接持续</span><b>{formatDuration(account.connection_health.connection_age_seconds)}</b></div>
          <div className="flex justify-between gap-2"><span className="text-slate-500">心跳帧</span><b>{formatFrameAge(account.connection_health.last_frame_age_seconds)}</b></div>
          <div className="col-span-2 flex justify-between gap-2"><span className="text-slate-500">最近收到真实消息</span><b>{formatHealthTime(account.connection_health.last_message_at)}</b></div>
        </div>
      )}
      <div className="mt-4 flex items-center justify-between border-t pt-4">
        <button className={`badge ${account.ai_enabled ? "badge-green" : ""}`} onClick={() => run({ path: `/api/xianyu/accounts/${account.id}`, method: "PATCH", body: { ai_enabled: !account.ai_enabled } })} disabled={busy}><Bot size={13} /> AI {account.ai_enabled ? "开启" : "关闭"}</button>
        <div className="flex gap-2">
          {account.adapter_type === "experimental-web" && connected && <button className="btn px-3 py-2" disabled={busy} onClick={() => run({ path: `/api/xianyu/accounts/${account.id}/sync` })}><RefreshCw size={14} /> 同步商品与会话</button>}
          {account.adapter_type === "experimental-web" && !connected && <button className="btn px-3 py-2" disabled={busy} onClick={() => onRelogin(account.id)}><QrCode size={14} /> 恢复登录</button>}
          <button className="btn px-3 py-2" disabled={busy || !account.adapter_available} onClick={() => run({ path: `/api/xianyu/accounts/${account.id}/${connected ? "disconnect" : "connect"}` })}>{connected ? <CircleOff size={14} /> : account.status === "ERROR" ? <RefreshCw size={14} /> : <Cable size={14} />}{connected ? "断开" : account.status === "ERROR" ? "重试" : "连接"}</button>
          <button className="btn btn-danger px-3 py-2" title="删除账号" disabled={busy} onClick={async () => { const accepted = await confirm({ title: "删除这个闲鱼账号？", description: "账号下仍有关联商品时系统会拒绝删除。此操作无法撤销。", confirmLabel: "删除账号", tone: "danger" }); if (accepted) run({ path: `/api/xianyu/accounts/${account.id}`, method: "DELETE" }); }}><Trash2 size={14} /></button>
        </div>
      </div>
    </article>
  );
}

function statusLabel(status: Account["status"]) {
  return { CONNECTED: "已连接", DISCONNECTED: "未连接", CONNECTING: "连接中", ERROR: "连接失败" }[status];
}

function formatDuration(seconds?: number) {
  if (seconds === undefined) return "等待状态上报";
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
}

function formatFrameAge(seconds?: number) {
  if (seconds === undefined) return "等待心跳";
  return seconds < 90 ? `${seconds} 秒前` : "较久，系统将重连";
}

function formatHealthTime(value?: string) {
  if (!value) return "尚未收到";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function qrStatusText(status?: QRPoll["status"]) {
  return { new: "等待扫码", scanned: "已扫码，请在手机上确认", processing: "正在加密保存并建立连接", confirmed: "登录已确认", expired: "登录会话已过期", verification_required: "请完成扫脸；完成后可直接关闭白屏页", waiting_helper: "正在连接本机登录助手", browser_opened: "专用 Edge 已打开", failed: "登录未完成" }[status ?? "new"];
}
