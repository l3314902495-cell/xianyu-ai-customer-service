/**
 * Local human-assisted Xianyu login helper.
 *
 * It launches a dedicated Edge profile and reads cookies only from that
 * dedicated browser through Edge's documented DevTools protocol. It never
 * touches the user's normal Edge profile and does not solve or bypass any
 * verification challenge.
 */
import http from "node:http";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const HOST = "127.0.0.1";
const PORT = 8765;
const HELPER_VERSION = process.env.XIANYU_HELPER_VERSION || "development";
const MISSING_IDENTITY_LOGIN_DELAY_MS = 12_000;
const HOME_REFRESH_DELAY_MS = 18_000;
const EXISTING_IDENTITY_LOGIN_DELAY_MS = 60_000;
const REJECTED_SESSION_RENEWAL_DELAY_MS = 45_000;
const ROOT = join(process.cwd(), ".runtime", "xianyu-edge-profiles");
mkdirSync(ROOT, { recursive: true });
const activeProfiles = new Set();

function normalizeProfileKey(value) {
  const profileKey = String(value || "").trim();
  if (!/^[a-zA-Z0-9_-]{8,100}$/.test(profileKey)) {
    throw new Error("专用 Edge Profile 标识无效");
  }
  return profileKey;
}

function edgePath() {
  const candidates = [
    process.env["PROGRAMFILES(X86)"] && join(process.env["PROGRAMFILES(X86)"], "Microsoft", "Edge", "Application", "msedge.exe"),
    process.env.PROGRAMFILES && join(process.env.PROGRAMFILES, "Microsoft", "Edge", "Application", "msedge.exe"),
    process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Microsoft", "Edge", "Application", "msedge.exe"),
  ].filter(Boolean);
  const found = candidates.find(existsSync);
  if (!found) throw new Error("未找到 Microsoft Edge");
  return found;
}

function json(res, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "http://localhost:3000",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  });
  res.end(JSON.stringify(body));
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

async function waitForDebugger(port) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(`http://${HOST}:${port}/json/list`);
      if (response.ok) return await response.json();
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("专用 Edge 启动超时");
}

async function cdp(port, method, params = {}) {
  const pages = await waitForDebugger(port);
  const page = pages.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
  if (!page) throw new Error("未找到登录页面");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  const id = Math.floor(Math.random() * 1_000_000_000);
  ws.send(JSON.stringify({ id, method, params }));
  const result = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("读取登录状态超时")), 5000);
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id === id) {
        clearTimeout(timeout);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result || {});
      }
    });
  });
  ws.close();
  return result;
}

async function closeEdgeGracefully(debugPort, child) {
  try {
    await cdp(debugPort, "Browser.close");
  } catch {}
  for (let attempt = 0; attempt < 10 && child.exitCode === null; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (child.exitCode === null) child.kill();
}

async function runLogin({ session_id, pairing_token, profile_key, api_url }) {
  const profileKey = normalizeProfileKey(profile_key);
  if (activeProfiles.has(profileKey)) throw new Error("该账号的专用 Edge 已经打开");
  activeProfiles.add(profileKey);
  const debugPort = 9300 + Math.floor(Math.random() * 500);
  const profile = join(ROOT, profileKey);
  const existingProfile = existsSync(join(profile, "Local State"));
  mkdirSync(profile, { recursive: true });
  const loginUrl = "https://passport.goofish.com/mini_login.htm?lang=zh_cn&appName=xianyu&appEntrance=web&styleType=vertical&notLoadSsoView=false&notKeepLogin=false&isMobile=false&qrCodeFirst=true";
  const child = spawn(edgePath(), [
    `--user-data-dir=${profile}`,
    `--remote-debugging-port=${debugPort}`,
    "--remote-allow-origins=http://127.0.0.1",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "--disable-features=msEdgeFirstRunExperience,msEdgeSync",
    "--new-window",
    existingProfile ? "https://www.goofish.com/" : loginUrl,
  ], { detached: false, stdio: "ignore" });

  let openedHome = false;
  let refreshedHome = false;
  let openedLogin = !existingProfile;
  let rejectedCookieFingerprint = null;
  let sessionRenewalStartedAt = null;
  let sessionRenewalReloaded = false;
  const startedAt = Date.now();
  const deadline = Date.now() + 15 * 60 * 1000;
  try {
    while (Date.now() < deadline && child.exitCode === null) {
      try {
        const result = await cdp(debugPort, "Network.getAllCookies");
        const cookies = (result.cookies || []).filter((cookie) =>
          /(^|\.)((goofish|taobao)\.com)$/.test(String(cookie.domain || "").replace(/^\./, "")),
        );
        const names = new Set(cookies.map((cookie) => cookie.name));
        const hasIdentityCookies = names.has("unb") && names.has("cookie2");
        const hasSessionToken = names.has("_m_h5_tk");
        const elapsed = Date.now() - startedAt;
        if (hasIdentityCookies && !hasSessionToken && !openedHome) {
          openedHome = true;
          await cdp(debugPort, "Page.navigate", { url: "https://www.goofish.com/" });
        }
        if (
          hasIdentityCookies
          && !hasSessionToken
          && openedHome
          && !refreshedHome
          && elapsed > HOME_REFRESH_DELAY_MS
        ) {
          refreshedHome = true;
          await cdp(debugPort, "Page.reload");
        }
        if (hasIdentityCookies && hasSessionToken) {
          const cookieText = cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join("; ");
          const cookieFingerprint = cookies
            .map((cookie) => `${cookie.domain}\t${cookie.path}\t${cookie.name}\t${cookie.value}`)
            .sort()
            .join("\n");
          if (cookieFingerprint !== rejectedCookieFingerprint) {
            const response = await fetch(`${api_url}/api/xianyu/browser-login/complete`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ session_id, pairing_token, cookie_text: cookieText }),
            });
            if (response.ok) return;
            if (response.status === 422) {
              // The browser identity can remain valid while the short-lived API token
              // in its cookie jar is stale. Give the homepage a chance to rotate that
              // token before treating the whole browser login as expired.
              rejectedCookieFingerprint = cookieFingerprint;
              if (sessionRenewalStartedAt === null) {
                sessionRenewalStartedAt = Date.now();
                openedHome = true;
                refreshedHome = true;
                await cdp(debugPort, "Page.navigate", { url: "https://www.goofish.com/" });
              }
            } else {
              throw new Error(`API 拒绝登录态（HTTP ${response.status}）`);
            }
          }
        }
        if (
          sessionRenewalStartedAt !== null
          && !sessionRenewalReloaded
          && Date.now() - sessionRenewalStartedAt > HOME_REFRESH_DELAY_MS
        ) {
          sessionRenewalReloaded = true;
          await cdp(debugPort, "Page.reload", { ignoreCache: true });
        }
        const loginDelay = hasIdentityCookies
          ? EXISTING_IDENTITY_LOGIN_DELAY_MS
          : MISSING_IDENTITY_LOGIN_DELAY_MS;
        const renewalTimedOut = sessionRenewalStartedAt !== null
          && Date.now() - sessionRenewalStartedAt > REJECTED_SESSION_RENEWAL_DELAY_MS;
        const initialSessionTimedOut = sessionRenewalStartedAt === null && elapsed > loginDelay;
        if (existingProfile && !openedLogin && (renewalTimedOut || initialSessionTimedOut)) {
          openedLogin = true;
          await cdp(debugPort, "Page.navigate", { url: loginUrl });
        }
      } catch (error) {
        if (String(error).includes("API 拒绝")) throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  } finally {
    await closeEdgeGracefully(debugPort, child);
    activeProfiles.delete(profileKey);
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") return json(res, 204, {});
  if (req.method === "GET" && req.url === "/health") {
    return json(res, 200, { status: "ok", version: HELPER_VERSION });
  }
  if (req.method === "POST" && req.url === "/sessions") {
    try {
      const body = await readBody(req);
      if (!body.session_id || !body.pairing_token || !body.profile_key || body.api_url !== "http://localhost:8000") {
        return json(res, 422, { detail: "登录配对参数无效" });
      }
      body.profile_key = normalizeProfileKey(body.profile_key);
      if (activeProfiles.has(body.profile_key)) {
        return json(res, 409, { detail: "该账号的专用 Edge 已经打开" });
      }
      runLogin(body).catch((error) => process.stderr.write(`[edge-login] ${error.message}\n`));
      return json(res, 202, { status: "browser_opened" });
    } catch (error) {
      return json(res, 500, { detail: error.message });
    }
  }
  return json(res, 404, { detail: "not found" });
});

server.listen(PORT, HOST, () => process.stdout.write(`[edge-login] listening on http://${HOST}:${PORT}\n`));
