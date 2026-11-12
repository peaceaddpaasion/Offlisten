(function () {
  "use strict";

  var statusEl = document.getElementById("status");
  var dotEl = document.getElementById("dot");
  var hintEl = document.getElementById("hint");
  var countEl = document.getElementById("count");
  var recentEl = document.getElementById("recent");
  var urlInput = document.getElementById("url");
  var currentUrl = "";
  var factsText = "";
  var factCount = 0;

  function setStatus(text, ok) {
    statusEl.textContent = text;
    dotEl.className = ok ? "dot ok" : "dot";
  }

  function ask(type, extra) {
    var payload = { type: type, url: currentUrl };
    if (extra) {
      for (var k in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, k)) { payload[k] = extra[k]; }
      }
    }
    return new Promise(function (resolve) {
      chrome.runtime.sendMessage(payload, function (reply) {
        resolve(reply || { ok: false, error: "service worker 没有返回内容" });
      });
    });
  }

  function clearFacts() {
    factsText = "";
    factCount = 0;
    countEl.textContent = "0 段";
    recentEl.textContent = "";
  }

  function stamp(e) {
    return "[" + e.ts + (e.rel === null || e.rel === undefined ? "" : " +" + e.rel + "s") + "]";
  }

  function renderRecent(segments) {
    recentEl.textContent = "";
    var list = segments.slice(-3);
    for (var i = 0; i < list.length; i++) {
      var e = list[i];
      var div = document.createElement("div");
      div.className = "line";
      var ts = document.createElement("span");
      ts.className = "ts";
      ts.textContent = stamp(e);
      var txt = document.createElement("span");
      txt.textContent = (e.kind === "trans" ? "译 " : "") + e.text;
      div.appendChild(ts);
      div.appendChild(txt);
      recentEl.appendChild(div);
    }
  }

  async function connect() {
    if (!currentUrl) {
      setStatus("未配置地址", false);
      return;
    }
    setStatus("正在连接本机服务", false);
    var s = await ask("status");
    if (!s.ok) {
      setStatus("连接失败", false);
      hintEl.textContent = s.error;
      clearFacts();
      return;
    }
    var f = await ask("facts");
    if (!f.ok) {
      setStatus("读取失败", false);
      hintEl.textContent = f.error;
      clearFacts();
      return;
    }
    factsText = f.text;
    factCount = f.segments.length;
    countEl.textContent = factCount + " 段";
    renderRecent(f.segments);
    setStatus("已连接 · 端口 " + s.port, true);
    hintEl.textContent = factCount === 0
      ? "服务已连接，还没有转写内容。开始说话，或用 --replay 回放一份文字稿。"
      : "复制全文后可直接粘进你已有的 AI 插件；live 页可以让插件直接读取。";
    refreshControl("");
  }

  document.getElementById("save").addEventListener("click", async function () {
    var raw = urlInput.value.trim();
    var u;
    try {
      u = new URL(raw);
    } catch (e) {
      setStatus("地址未通过校验", false);
      hintEl.textContent = "这不是完整 URL。请复制程序启动时打印的那一整行地址。";
      return;
    }
    if (u.protocol !== "http:" ||
        (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") ||
        !u.searchParams.get("token")) {
      setStatus("地址未通过校验", false);
      hintEl.textContent = "只接受带 token 的 127.0.0.1 / localhost 地址，避免把 token 发到别处。";
      return;
    }
    await chrome.storage.local.set({ liveUrl: raw });
    currentUrl = raw;
    hintEl.textContent = "";
    connect();
  });

  document.getElementById("refresh").addEventListener("click", connect);

  document.getElementById("open").addEventListener("click", function () {
    if (!currentUrl) {
      hintEl.textContent = "先保存本机服务地址，再打开 live 页。";
      return;
    }
    chrome.tabs.create({ url: currentUrl });
  });

  document.getElementById("copy").addEventListener("click", async function () {
    if (!factsText) {
      hintEl.textContent = "还没有可复制的转写内容，先连接并产生几段转写。";
      return;
    }
    var head = "# Offlisten 事实源\n" +
               "# 原文来自本机离线 ASR；标「译 」的行由 Argos 离线机器翻译生成，不是原文。\n\n";
    try {
      await navigator.clipboard.writeText(head + factsText);
      hintEl.textContent = "已复制 " + factCount + " 段到剪贴板。";
    } catch (e) {
      hintEl.textContent = "浏览器拒绝了剪贴板写入；请到 live 页点「复制全文」。";
    }
  });

  // 控制面（I-067）：扩展是入口，web live 页是完整前端；这里只放常用开关。
  // 没有运行核心时显示只读说明，不渲染点了没用的按钮。
  var controlEl = document.getElementById("control");
  var controlMode = document.getElementById("controlMode");
  var controlBody = document.getElementById("controlBody");
  var readonlyNote = document.getElementById("readonlyNote");
  var runBtn = document.getElementById("run");
  var engineSel = document.getElementById("engineSel");
  var sourceSel = document.getElementById("sourceSel");
  var translateChk = document.getElementById("translateChk");
  var controlHint = document.getElementById("controlHint");
  var controlAvailable = false;
  var controlBusy = false;

  function controlSay(msg, bad) {
    controlHint.textContent = msg || "";
    controlHint.style.color = bad ? "#a33a32" : "#3c4650";
  }

  function applyControlState(s) {
    controlMode.textContent = (s.running ? "运行中" : "待机") +
      " ｜ " + s.engine + " ｜ " + (s.source === "mic" ? "麦克风" : "系统声音");
    runBtn.textContent = s.running ? "停止转写" : "开始转写";
    runBtn.className = s.running ? "running" : "";
    engineSel.value = s.engine;
    sourceSel.value = s.source;
    translateChk.checked = !!s.translate;
  }

  function refreshControl(report) {
    return ask("controlState").then(function (reply) {
      controlEl.hidden = false;
      if (!reply.ok) {
        controlAvailable = false;
        controlBody.hidden = true;
        readonlyNote.hidden = false;
        controlMode.textContent = "读取失败";
        readonlyNote.textContent = reply.error;
        return;
      }
      var data = reply.data;
      if (!data.available) {
        controlAvailable = false;
        controlBody.hidden = true;
        readonlyNote.hidden = false;
        controlMode.textContent = "只读文本页";
        readonlyNote.textContent = (data.reason || "本实例没有运行核心") +
          "。仍可复制全文与打开 live 页；要在这里控制转写，请用 live --headless 启动本地后端。";
        return;
      }
      controlAvailable = true;
      controlBody.hidden = false;
      readonlyNote.hidden = true;
      applyControlState(data.state);
      if (report) { controlSay(report); }
    });
  }

  function controlAct(action, patch, label) {
    if (controlBusy || !controlAvailable) { return; }
    controlBusy = true;
    runBtn.disabled = true;
    controlSay("正在" + label + "…");
    ask("controlAction", { action: action, patch: patch || {} })
      .then(function (reply) {
        if (!reply.ok) { controlSay(reply.error, true); return refreshControl(""); }
        var data = reply.data;
        if (!data.ok) {
          controlSay(data.error || "操作失败", true);
          return refreshControl("");
        }
        return refreshControl(data.message || (label + "完成"));
      })
      .then(function () {
        controlBusy = false;
        runBtn.disabled = false;
      });
  }

  runBtn.addEventListener("click", function () {
    controlAct(runBtn.classList.contains("running") ? "stop" : "start", {}, "切换转写状态");
  });
  engineSel.addEventListener("change", function () {
    controlAct("configure", { engine: engineSel.value }, "切换引擎");
  });
  sourceSel.addEventListener("change", function () {
    controlAct("configure", { source: sourceSel.value }, "切换音源");
  });
  translateChk.addEventListener("change", function () {
    controlAct("configure", { translate: translateChk.checked }, "调整译文开关");
  });

  chrome.storage.local.get(["liveUrl"], function (data) {
    if (data.liveUrl) {
      urlInput.value = data.liveUrl;
      currentUrl = data.liveUrl;
      connect();
    } else {
      hintEl.textContent = "运行 run_transcriber.bat live --web-live，把程序打印的完整 URL 粘到上面。";
    }
  });
})();
