"use client";

import { ArrowRight, Eye, EyeOff, LockKeyhole } from "lucide-react";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { request } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError("");
    const data = new FormData(event.currentTarget);
    try {
      await request("/api/auth/login", { method: "POST", body: JSON.stringify({ username: data.get("username"), password: data.get("password") }) });
      router.push("/");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败，请检查账号和密码");
    } finally { setLoading(false); }
  }

  return <main className="login-page">
    <section className="login-brand-panel" aria-label="产品介绍">
      <div className="login-brand"><span>鱼</span><div><b>闲鱼 AI 客服</b><small>SIGNAL DESK</small></div></div>
      <div className="login-brand-content">
          <div className="login-kicker">卖家客服工作台</div>
        <h1>每条买家消息，<br />都有商品依据。</h1>
        <p>商品知识驱动回复，AI 负责理解和表达，人工始终拥有最终控制权。</p>
      </div>
      <div className="login-signal-path" aria-hidden="true"><span>买家消息</span><i /><span>商品知识</span><i /><span>AI 决策</span><i /><span>安全发送</span></div>
      <small className="login-version">Xianyu customer service control center · V1</small>
    </section>
    <section className="login-form-panel">
      <form onSubmit={submit} className="login-form" noValidate>
        <div className="login-heading"><span>管理员入口</span><h2>登录工作台</h2><p>继续管理会话、商品知识和 AI 自动客服。</p></div>
        <div className="field-group"><label htmlFor="username">用户名或邮箱</label><input id="username" className="input" name="username" autoComplete="username" defaultValue="admin" required /></div>
        <div className="field-group"><label htmlFor="password">密码</label><div className="password-field"><input id="password" className="input" name="password" type={showPassword ? "text" : "password"} autoComplete="current-password" defaultValue="Admin123!" required /><button type="button" className="icon-btn" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "隐藏密码" : "显示密码"}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></div>
        {error && <div className="login-error" role="alert"><LockKeyhole size={16} /><span>{error}</span></div>}
        <button className="btn btn-primary login-submit" disabled={loading} type="submit">{loading ? <><span className="button-spinner" />正在验证</> : <>登录后台 <ArrowRight size={16} /></>}</button>
        <div className="dev-credentials"><span>开发环境账号</span><code>admin / Admin123!</code></div>
      </form>
    </section>
  </main>;
}
