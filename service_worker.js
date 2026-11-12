// 所有对 localhost 的请求都在这里发起（扩展自身 origin）。
// 不使用 content script：网页上下文发起的本地请求会受页面 CORS、混合内容与 LNA 约束。

function parseTarget(raw) {
  let u;
  try {
    u = new URL(raw);
  } catch (e) {
    return null;
  }
  if (u.protocol !== "http:") { return null; }
  if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") { return null; }
  const token = u.searchParams.get("token");
  if (!token) { return null; }
  return { base: u.origin, token: token };
}

async function fetchJson(path, target) {
  const sep = path.indexOf("?") === -1 ? "?" : "&";
  const res = await fetch(
    target.base + path + sep + "token=" + encodeURIComponent(target.token),
    {
      headers: { "X-Whisper-Token": target.token },
      signal: AbortSignal.timeout(4000)
    }
  );
  if (!res.ok) { throw new Error("HTTP " + res.status); }
  return res.json();
}

// 控制端点在 400 / 409 时也会回带原因的 JSON，不能按 HTTP 状态直接丢掉。
async function postControl(path, target, body) {
  const sep = path.indexOf("?") === -1 ? "?" : "&";
  const res = await fetch(
    target.base + path + sep + "token=" + encodeURIComponent(target.token),
    {
      method: "POST",
      headers: {
        "X-Whisper-Token": target.token,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(4000)
    }
  );
  return res.json();
}

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  (async function () {
    const target = parseTarget(msg.url || "");
    if (!target) {
      sendResponse({ ok: false, error: "地址不是带 token 的本机地址" });
      return;
    }
    try {
      if (msg.type === "status") {
        const data = await fetchJson("/health", target);
        sendResponse({ ok: true, segments: data.segments, port: data.port });
      } else if (msg.type === "facts") {
        const data = await fetchJson("/transcript.json", target);
        sendResponse({
          ok: true,
          segments: data.segments,
          text: data.text,
          note: data.note
        });
      } else if (msg.type === "controlState") {
        const data = await fetchJson("/api/control/state", target);
        sendResponse({ ok: true, data: data });
      } else if (msg.type === "controlAction") {
        const data = await postControl("/api/control/action", target, {
          action: msg.action,
          patch: msg.patch || {}
        });
        sendResponse({ ok: true, data: data });
      } else {
        sendResponse({ ok: false, error: "未知请求类型" });
      }
    } catch (e) {
      sendResponse({
        ok: false,
        error: "本机服务未响应（" + e.message + "）：程序可能已停止，或端口/token 变了，请重新复制启动时打印的完整 URL。"
      });
    }
  })();
  return true;
});
