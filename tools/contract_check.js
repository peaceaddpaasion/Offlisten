#!/usr/bin/env node
// 扩展仓独立自检：验证正在运行的本机后端是否仍满足 docs/contract.md。
// 只发 GET/POST 探测请求，不读存档、不写文件、不打印 token。
//
//   node scripts/contract_check.js
//   node scripts/contract_check.js --url "http://127.0.0.1:47813/?token=..."
//   node scripts/contract_check.js --discovery D:\projects\whisper\web_live.json
const fs = require("fs");
const path = require("path");
const http = require("http");

const ROOT = path.resolve(__dirname, "..");
const DEFAULT_DISCOVERY = path.resolve(ROOT, "..", "whisper", "web_live.json");

function argOf(name) {
  const i = process.argv.indexOf(name);
  return i > -1 ? process.argv[i + 1] : null;
}

function readTarget() {
  const raw = argOf("--url");
  if (raw) { return { url: raw, from: "参数 --url" }; }
  const file = argOf("--discovery") || process.env.WHISPER_DISCOVERY || DEFAULT_DISCOVERY;
  if (!fs.existsSync(file)) { return { error: "找不到发现文件: " + file + "（后端没在跑，或用 --url 直接给地址）" }; }
  let data;
  try { data = JSON.parse(fs.readFileSync(file, "utf-8")); } catch (e) { return { error: "发现文件不是合法 JSON: " + e.message }; }
  if (!data.url || !data.token) { return { error: "发现文件缺 url 或 token" }; }
  return { url: data.url, from: file };
}

function parseUrl(raw) {
  let u;
  try { u = new URL(raw); } catch (e) { return null; }
  if (u.protocol !== "http:") { return null; }
  if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") { return null; }
  const token = u.searchParams.get("token");
  if (!token) { return null; }
  return { origin: u.origin, token: token };
}

// 用 http.request 而不是 fetch：需要能伪造 Host 头来验 DNS rebinding 防护。
function request(target, pathname, opts) {
  const o = opts || {};
  const sep = pathname.includes("?") ? "&" : "?";
  const full = target.origin + pathname + (o.noToken ? "" : sep + "token=" + encodeURIComponent(target.token));
  const headers = { "Content-Type": "application/json" };
  if (!o.noToken) { headers["X-Whisper-Token"] = target.token; }
  if (o.host) { headers["Host"] = o.host; }
  let body = null;
  if (o.body !== undefined) {
    body = JSON.stringify(o.body);
    headers["Content-Length"] = Buffer.byteLength(body);
  }
  return new Promise(function (resolve) {
    const req = http.request(full, { method: o.method || "GET", headers: headers, timeout: 4000 }, function (res) {
      let buf = "";
      res.setEncoding("utf-8");
      res.on("data", function (c) { buf += c; });
      res.on("end", function () {
        let json = null;
        try { json = JSON.parse(buf); } catch (e) { /* 有些端点是纯文本 */ }
        resolve({ status: res.statusCode, json: json, raw: buf });
      });
    });
    req.on("timeout", function () { req.destroy(new Error("timeout")); });
    req.on("error", function (e) { resolve({ status: 0, json: null, raw: "", error: e.message }); });
    if (body !== null) { req.write(body); }
    req.end();
  });
}

const results = [];
function check(name, ok, detail) {
  results.push({ name: name, ok: !!ok, detail: detail || "" });
  console.log("[%s] %s%s", ok ? "PASS" : "FAIL", name, detail ? "  -> " + detail : "");
}

async function main() {
  const found = readTarget();
  if (found.error) { console.log("FAIL  " + found.error); process.exit(2); }
  const target = parseUrl(found.url);
  if (!target) { console.log("FAIL  地址必须是带 token 的 127.0.0.1 / localhost http 地址"); process.exit(2); }
  console.log("目标 %s（来源：%s）\n", target.origin, found.from);

  // 1. /health 无 token 可达
  const health = await request(target, "/health", { noToken: true });
  check("/health 无 token 可达", health.status === 200, "status=" + health.status);
  check("/health 声明 whisper-web-live", health.json && health.json.service === "whisper-web-live", health.json && health.json.service);
  check("/health 带 segments 数字", health.json && typeof health.json.segments === "number", health.json && String(health.json.segments));
  check("/health 带 control 布尔", health.json && typeof health.json.control === "boolean", health.json && String(health.json.control));
  check("/health 带 port", health.json && Number.isInteger(health.json.port), health.json && String(health.json.port));

  // 2. Host 伪造必须被拒（DNS rebinding 防护）
  const evil = await request(target, "/health", { noToken: true, host: "evil.example.com" });
  check("伪造 Host 被拒", evil.status === 403, "status=" + evil.status);

  // 3. /transcript.json 缺 token 必须 403
  const noTok = await request(target, "/transcript.json", { noToken: true });
  check("/transcript.json 缺 token 返回 403", noTok.status === 403, "status=" + noTok.status);

  // 4. /transcript.json 契约字段
  const facts = await request(target, "/transcript.json");
  const f = facts.json;
  check("/transcript.json 可达", facts.status === 200, "status=" + facts.status);
  check("segments 是数组", f && Array.isArray(f.segments), f && (Array.isArray(f.segments) ? f.segments.length + " 段" : typeof f.segments));
  check("text 是字符串", f && typeof f.text === "string", f && typeof f.text);
  check("note 声明译文非原文", f && typeof f.note === "string" && f.note.indexOf("非原文") > -1, f && f.note);
  const seg = f && Array.isArray(f.segments) && f.segments[0];
  check("段字段 ts/rel/kind/text 齐全", !!seg && ["ts", "rel", "kind", "text"].every(function (k) { return k in seg; }),
    seg ? Object.keys(seg).join(",") : "无段可验（空转写属合法状态）");
  check("kind 只出现 final/trans", !f || !Array.isArray(f.segments) || f.segments.every(function (s) { return s.kind === "final" || s.kind === "trans"; }),
    f && Array.isArray(f.segments) ? Array.from(new Set(f.segments.map(function (s) { return s.kind; }))).join(",") : "");

  // 5. 控制面 state
  const state = await request(target, "/api/control/state");
  check("/api/control/state 可达", state.status === 200, "status=" + state.status);
  check("state 带 available 布尔", state.json && typeof state.json.available === "boolean", state.json && String(state.json.available));
  const canControl = state.json && state.json.available === true;
  if (canControl) {
    const s = state.json.state || {};
    check("有核心时 state 带 running/engine/source/translate",
      typeof s.running === "boolean" && typeof s.engine === "string" && typeof s.source === "string" && typeof s.translate === "boolean",
      [s.running, s.engine, s.source, s.translate].join(" / "));
  } else {
    check("只读时带 reason", state.json && typeof state.json.reason === "string" && state.json.reason.length > 0, state.json && state.json.reason);
  }

  // 6. 控制面 action
  const act = await request(target, "/api/control/action", { method: "POST", body: { action: "state" } });
  check("POST action=state 200 且 ok", act.status === 200 && act.json && act.json.ok === true, "status=" + act.status);
  const bad = await request(target, "/api/control/action", { method: "POST", body: { action: "explode" } });
  const badOk = canControl ? (bad.status === 400) : (bad.status === 409 || bad.status === 400);
  check("非法 action 被拒且带 error", badOk && bad.json && bad.json.ok === false && typeof bad.json.error === "string",
    "status=" + bad.status + " / " + (bad.json && bad.json.error));
  const wrongType = await request(target, "/api/control/action", { method: "POST", body: { action: "configure", patch: { engine: "nope" } } });
  const wrongOk = canControl ? (wrongType.status === 400 && wrongType.json && wrongType.json.ok === false) : (wrongType.status === 409);
  check("非法 engine 被拒", wrongOk, "status=" + wrongType.status);

  const passed = results.filter(function (r) { return r.ok; }).length;
  console.log("\n%d/%d 通过", passed, results.length);
  process.exit(passed === results.length ? 0 : 1);
}

main().catch(function (e) {
  console.log("FAIL  自检自身异常: " + e.message);
  process.exit(2);
});
