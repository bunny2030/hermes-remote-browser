// Hermes Remote Browser: while switched on, keeps one outbound websocket to your relay and runs
// the agent's commands on the tabs in the "Hermes" tab group only. Off at every browser start.
// Chrome 116+ keeps a service worker alive while its websocket is active; the ping every 20s
// is that activity.

const GROUP_TITLE = "Hermes";
const AUTO_OFF_DEFAULT_MIN = 60;
const PAGE_TIMEOUT_MS = 20000;

let ws = null;
let pingTimer = null;
let reconnectTimer = null;

// ---- state shared with the popup ---------------------------------------------------------

async function local() {
  return chrome.storage.local.get({ armed: false, armedUntil: 0, deviceToken: "", deviceId: "",
                                    autoOffMin: AUTO_OFF_DEFAULT_MIN, lastTabId: 0, serverUrl: "" });
}

// "wss://bridge.example.com" or a full ".../ext" URL -> the websocket endpoint. ws:// is only
// accepted for localhost testing.
function endpoint(serverUrl) {
  let u;
  try { u = new URL(serverUrl.trim()); } catch (e) { return null; }
  if (u.protocol === "https:") u.protocol = "wss:";
  if (u.protocol === "http:") u.protocol = "ws:";
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(u.hostname);
  if (u.protocol !== "wss:" && !(u.protocol === "ws:" && local)) return null;
  if (!u.pathname.endsWith("/ext")) u.pathname = u.pathname.replace(/\/$/, "") + "/ext";
  return u.toString();
}

async function setStatus(status, extra = {}) {
  await chrome.storage.session.set({ status, pairCode: "", error: "", ...extra });
  const badge = { connected: ["ON", "#16a34a"], connecting: ["…", "#ca8a04"],
                  pairing: ["PAIR", "#7c3aed"], error: ["!", "#dc2626"] }[status];
  await chrome.action.setBadgeText({ text: badge ? badge[0] : "" });
  if (badge) await chrome.action.setBadgeBackgroundColor({ color: badge[1] });
}

// ---- connection --------------------------------------------------------------------------

function closeSocket() {
  clearInterval(pingTimer);
  clearTimeout(reconnectTimer);
  pingTimer = reconnectTimer = null;
  if (ws) {
    ws.onclose = null;
    try { ws.close(); } catch (e) {}
    ws = null;
  }
}

function openSocket(url, hello) {
  closeSocket();
  const sock = new WebSocket(url);
  ws = sock;
  sock.onopen = () => {
    sock.send(JSON.stringify({ type: "hello", ...hello }));
    pingTimer = setInterval(() => {
      if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "ping" }));
    }, 20000);
  };
  sock.onmessage = (ev) => onServerMessage(sock, ev.data);
  sock.onclose = async () => {
    if (ws !== sock) return;
    clearInterval(pingTimer);
    ws = null;
    const s = await local();
    const { status } = await chrome.storage.session.get({ status: "off" });
    if (s.armed && s.deviceToken && status !== "pairing") {
      await setStatus("connecting");
      reconnectTimer = setTimeout(connect, 5000);
    } else if (status === "pairing") {
      await setStatus("error", { error: "Pairing ended before it was approved. Try again." });
    }
  };
}

async function connect() {
  const s = await local();
  if (!s.armed || !s.deviceToken) return;
  if (ws && ws.readyState <= WebSocket.OPEN) return;
  const url = endpoint(s.serverUrl);
  if (!url) return setStatus("error", { error: "Set a valid server address first." });
  await setStatus("connecting");
  openSocket(url, { device_token: s.deviceToken });
}

async function onServerMessage(sock, raw) {
  let msg;
  try { msg = JSON.parse(raw); } catch (e) { return; }
  if (msg.type === "pair_code") {
    await setStatus("pairing", { pairCode: msg.code });
  } else if (msg.type === "paired") {
    await chrome.storage.local.set({ deviceToken: msg.device_token, deviceId: msg.device_id });
    await arm();
  } else if (msg.type === "ready") {
    await setStatus("connected");
  } else if (msg.type === "unpaired") {
    // The server no longer knows this browser (revoked): forget the token and switch off.
    await chrome.storage.local.set({ deviceToken: "", deviceId: "", armed: false });
    closeSocket();
    await setStatus("off", { error: "This browser was unpaired on the server. Pair it again." });
  } else if (msg.type === "error") {
    await setStatus("error", { error: msg.error || "Server error" });
  } else if (msg.type === "cmd") {
    let reply;
    try {
      reply = { ok: true, data: await runCommand(msg.action, msg.params || {}) };
    } catch (e) {
      reply = { ok: false, error: String(e && e.message || e) };
    }
    if (sock.readyState === WebSocket.OPEN) {
      sock.send(JSON.stringify({ type: "result", id: msg.id, ...reply }));
    }
  }
}

async function arm() {
  const s = await local();
  const until = s.autoOffMin > 0 ? Date.now() + s.autoOffMin * 60000 : 0;
  await chrome.storage.local.set({ armed: true, armedUntil: until });
  if (ws && ws.readyState === WebSocket.OPEN) await setStatus("connected");
  else await connect();
}

async function disarm(reason = "") {
  await chrome.storage.local.set({ armed: false, armedUntil: 0 });
  closeSocket();
  await setStatus("off", reason ? { error: reason } : {});
}

async function startPairing() {
  const s = await local();
  const url = endpoint(s.serverUrl);
  if (!url) return setStatus("error", { error: "Enter your relay address (wss://…) first." });
  await chrome.storage.local.set({ armed: false });
  await setStatus("connecting");
  openSocket(url, { pair: true, name: "Chrome on " + (navigator.userAgentData?.platform || "PC") });
}

// ---- tabs in the Hermes group ------------------------------------------------------------

async function agentGroupIds() {
  const groups = await chrome.tabGroups.query({ title: GROUP_TITLE });
  return groups.map((g) => g.id);
}

async function agentTabs() {
  const ids = await agentGroupIds();
  const tabs = [];
  for (const id of ids) tabs.push(...await chrome.tabs.query({ groupId: id }));
  return tabs;
}

async function targetTab(tabId) {
  const tabs = await agentTabs();
  if (tabId) {
    const t = tabs.find((x) => x.id === Number(tabId));
    if (!t) throw new Error("That tab is not in the Hermes tab group.");
    return t;
  }
  const { lastTabId } = await local();
  const t = tabs.find((x) => x.id === lastTabId) || tabs.find((x) => x.active) || tabs[0];
  if (!t) throw new Error("No tab is in the Hermes tab group. Use action \"open\" with a url, or ask the user to drag a tab into the purple Hermes group.");
  return t;
}

async function addToGroup(tab) {
  const groups = await chrome.tabGroups.query({ title: GROUP_TITLE, windowId: tab.windowId });
  if (groups.length) {
    await chrome.tabs.group({ tabIds: [tab.id], groupId: groups[0].id });
  } else {
    const gid = await chrome.tabs.group({ tabIds: [tab.id], createProperties: { windowId: tab.windowId } });
    await chrome.tabGroups.update(gid, { title: GROUP_TITLE, color: "purple" });
  }
}

function waitForLoad(tabId) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listener); clearTimeout(timer); resolve(); };
    const listener = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const timer = setTimeout(done, PAGE_TIMEOUT_MS);
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then((t) => { if (t.status === "complete" && !t.pendingUrl) done(); }).catch(done);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function inPage(tab, func, args = []) {
  const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func, args });
  if (res && res.result && res.result.error) throw new Error(res.result.error);
  return res ? res.result : null;
}

function tabInfo(t) {
  return { tab_id: t.id, title: t.title, url: t.url, active: t.active };
}

// ---- commands ----------------------------------------------------------------------------

async function runCommand(action, p) {
  const s = await local();
  if (!s.armed) throw new Error("Hermes Remote Browser is switched off.");
  switch (action) {
    case "tabs":
      return { tabs: (await agentTabs()).map(tabInfo) };

    case "open": {
      const url = String(p.url || "");
      if (!/^https?:\/\//i.test(url)) throw new Error("Only http(s) URLs can be opened.");
      let tab;
      if (p.new_tab === false || p.tab_id) {
        tab = await targetTab(p.tab_id).catch(() => null);
      }
      if (tab) {
        await chrome.tabs.update(tab.id, { url });
      } else {
        const win = await chrome.windows.getLastFocused({ windowTypes: ["normal"] }).catch(() => null);
        tab = await chrome.tabs.create({ url, active: false, ...(win ? { windowId: win.id } : {}) });
        await addToGroup(tab);
      }
      await chrome.storage.local.set({ lastTabId: tab.id });
      await waitForLoad(tab.id);
      return tabInfo(await chrome.tabs.get(tab.id));
    }

    case "snapshot": {
      const tab = await targetTab(p.tab_id);
      await chrome.storage.local.set({ lastTabId: tab.id });
      const data = await inPage(tab, pageSnapshot, [Number(p.max_chars) || 6000]);
      return { tab_id: tab.id, ...data };
    }

    case "click": case "type": case "select": case "scroll": case "key": {
      const tab = await targetTab(p.tab_id);
      await chrome.storage.local.set({ lastTabId: tab.id });
      const out = await inPage(tab, pageAction, [action, p]);
      await sleep(700);
      await waitForLoad(tab.id);
      const t = await chrome.tabs.get(tab.id);
      return { ...out, ...tabInfo(t) };
    }

    case "back": {
      const tab = await targetTab(p.tab_id);
      try {
        await chrome.tabs.goBack(tab.id);
      } catch (e) {
        // Form submits in background tabs don't always register with tabs.goBack.
        await inPage(tab, () => { history.back(); return {}; });
        await sleep(700);
      }
      await waitForLoad(tab.id);
      return tabInfo(await chrome.tabs.get(tab.id));
    }

    case "screenshot": {
      const tab = await targetTab(p.tab_id);
      // captureVisibleTab only sees the window's active tab, so bring the agent's tab forward.
      if (!tab.active) { await chrome.tabs.update(tab.id, { active: true }); await sleep(400); }
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 70 });
      return { tab_id: tab.id, title: tab.title, url: tab.url, image: dataUrl };
    }

    case "close": {
      const tab = await targetTab(p.tab_id);
      await chrome.tabs.remove(tab.id);
      return { closed: tab.id };
    }

    default:
      throw new Error("Unknown action: " + action);
  }
}

// ---- injected into the page (must be self-contained) -------------------------------------

function pageSnapshot(maxChars) {
  const SEL = "a[href],button,input,textarea,select,summary,[contenteditable=''],[contenteditable='true']," +
              "[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem]," +
              "[role=option],[role=switch],[role=textbox],[role=combobox],[role=searchbox],[onclick]";
  document.querySelectorAll("[data-hermes-ref]").forEach((el) => el.removeAttribute("data-hermes-ref"));
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && cs.opacity !== "0";
  };
  const clip = (s, n) => (s || "").replace(/\s+/g, " ").trim().slice(0, n);
  const elements = [];
  let n = 0;
  for (const el of document.querySelectorAll(SEL)) {
    if (n >= 300 || !visible(el)) continue;
    n += 1;
    el.setAttribute("data-hermes-ref", String(n));
    const tag = el.tagName.toLowerCase();
    const label = clip(el.getAttribute("aria-label") || el.innerText || el.getAttribute("placeholder") ||
                       el.getAttribute("title") || el.getAttribute("alt") ||
                       el.querySelector?.("img[alt]")?.getAttribute("alt") || el.name || "", 80);
    const item = { ref: n, tag, label };
    const role = el.getAttribute("role"); if (role) item.role = role;
    if (tag === "a") item.href = clip(el.href, 150);
    if (tag === "input") {
      item.type = el.type;
      if (el.type === "password") item.value = "(password field: off-limits)";
      else if (["checkbox", "radio"].includes(el.type)) item.checked = el.checked;
      else if (el.value) item.value = clip(el.value, 60);
    }
    if (tag === "textarea" && el.value) item.value = clip(el.value, 60);
    if (tag === "select") item.value = clip(el.options[el.selectedIndex]?.text, 60);
    const r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) item.offscreen = true;
    elements.push(item);
  }
  const text = (document.body?.innerText || "").replace(/\n{3,}/g, "\n\n");
  return {
    title: document.title, url: location.href,
    scroll: { y: Math.round(scrollY), page_height: document.documentElement.scrollHeight, viewport: innerHeight },
    text: text.slice(0, maxChars), text_truncated: text.length > maxChars, elements,
  };
}

function pageAction(action, p) {
  const find = () => {
    const el = document.querySelector(`[data-hermes-ref="${Number(p.ref)}"]`);
    if (!el) return null;
    el.scrollIntoView({ block: "center", inline: "center" });
    return el;
  };
  if (action === "scroll") {
    const dy = { up: -1, down: 1 }[p.direction] ?? 1;
    if (p.direction === "top") scrollTo(0, 0);
    else if (p.direction === "bottom") scrollTo(0, document.documentElement.scrollHeight);
    else scrollBy(0, dy * (Number(p.pixels) || Math.round(innerHeight * 0.8)));
    return { scrolled: p.direction || "down", y: Math.round(scrollY) };
  }
  if (action === "key") {
    const el = document.activeElement || document.body;
    const key = String(p.key || "Enter");
    for (const type of ["keydown", "keypress", "keyup"]) {
      el.dispatchEvent(new KeyboardEvent(type, { key, code: key, bubbles: true, cancelable: true }));
    }
    if (key === "Enter" && el.form) el.form.requestSubmit?.();
    return { pressed: key };
  }
  const el = find();
  if (!el) return { error: `No element [${p.ref}]. Take a new snapshot; refs change when the page changes.` };
  if (el.tagName === "INPUT" && el.type === "password") {
    return { error: "Password fields are off-limits. Ask the user to type it themselves." };
  }
  if (action === "click") {
    el.focus?.();
    el.click();
    return { clicked: p.ref };
  }
  if (action === "type") {
    el.focus();
    const text = String(p.text ?? "");
    if (el.isContentEditable) {
      if (p.clear !== false) document.execCommand("selectAll");
      document.execCommand("insertText", false, text);
    } else {
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, (p.clear === false ? el.value : "") + text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (p.submit) {
      for (const type of ["keydown", "keypress", "keyup"]) {
        el.dispatchEvent(new KeyboardEvent(type, { key: "Enter", code: "Enter", keyCode: 13, bubbles: true, cancelable: true }));
      }
      if (el.form) el.form.requestSubmit?.();
    }
    return { typed: p.ref, submitted: !!p.submit };
  }
  if (action === "select") {
    if (el.tagName !== "SELECT") return { error: `[${p.ref}] is not a dropdown.` };
    const want = String(p.value ?? "").toLowerCase();
    const opt = [...el.options].find((o) => o.value.toLowerCase() === want || o.text.trim().toLowerCase() === want);
    if (!opt) return { error: "No option matches. Options: " + [...el.options].map((o) => o.text.trim()).join(" | ").slice(0, 400) };
    el.value = opt.value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return { selected: opt.text.trim() };
  }
  return { error: "Unknown action " + action };
}

// ---- lifecycle ---------------------------------------------------------------------------

chrome.runtime.onStartup.addListener(() => disarm());
chrome.runtime.onInstalled.addListener(() => disarm());
chrome.alarms.create("tick", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name !== "tick") return;
  const s = await local();
  if (s.armed && s.armedUntil && Date.now() > s.armedUntil) await disarm("Switched off automatically.");
  else if (s.armed) await connect();
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.op === "arm") await arm();
    else if (msg.op === "disarm") await disarm();
    else if (msg.op === "pair") await startPairing();
    else if (msg.op === "cancelPair") { closeSocket(); await setStatus("off"); }
    else if (msg.op === "forget") { await disarm(); await chrome.storage.local.set({ deviceToken: "", deviceId: "" }); }
    else if (msg.op === "setServer") {
      // A different relay means a different pairing.
      await disarm();
      await chrome.storage.local.set({ serverUrl: String(msg.url || "").trim(), deviceToken: "", deviceId: "" });
      if (msg.url && !endpoint(msg.url)) await setStatus("error", { error: "Use wss://your-relay-host (ws:// only for localhost)." });
    }
    else if (msg.op === "autoOff") {
      await chrome.storage.local.set({ autoOffMin: Number(msg.minutes) });
      const s = await local();
      if (s.armed) await chrome.storage.local.set({ armedUntil: s.autoOffMin > 0 ? Date.now() + s.autoOffMin * 60000 : 0 });
    }
    sendResponse({ ok: true });
  })();
  return true;
});

// A restarted service worker picks the connection back up if it was switched on.
connect();
