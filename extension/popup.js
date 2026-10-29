const $ = (id) => document.getElementById(id);
const send = (op, extra = {}) => chrome.runtime.sendMessage({ op, ...extra });

const LABELS = { off: "Off", connecting: "Connecting…", connected: "On — the agent can use its tabs",
                 pairing: "Waiting for approval", error: "Problem" };

async function render() {
  const s = await chrome.storage.local.get({ armed: false, armedUntil: 0, deviceToken: "", autoOffMin: 60, serverUrl: "" });
  const r = await chrome.storage.session.get({ status: "off", pairCode: "", error: "" });
  const status = r.status;

  $("dot").className = "dot " + status;
  $("statusText").textContent = LABELS[status] || status;
  $("unpaired").hidden = !!s.deviceToken || status === "pairing" || status === "connecting";
  if (document.activeElement !== $("server")) $("server").value = s.serverUrl;
  $("pairing").hidden = status !== "pairing";
  $("code").textContent = r.pairCode || "···-···";
  $("paired").hidden = !s.deviceToken;
  $("serverShown").textContent = s.serverUrl;
  $("forgetWrap").hidden = !s.deviceToken;
  $("toggle").textContent = s.armed ? "Switch off" : "Switch on";
  $("toggle").className = s.armed ? "off" : "";
  $("autoOff").value = String(s.autoOffMin);
  $("until").textContent = s.armed && s.armedUntil
    ? "Switches off at " + new Date(s.armedUntil).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + "."
    : "";
  $("error").hidden = !r.error;
  $("error").textContent = r.error;
}

$("pair").onclick = async () => {
  const url = $("server").value.trim();
  const { serverUrl } = await chrome.storage.local.get({ serverUrl: "" });
  if (url !== serverUrl) await send("setServer", { url });
  send("pair");
};
$("cancelPair").onclick = () => send("cancelPair");
$("toggle").onclick = async () => {
  const { armed } = await chrome.storage.local.get({ armed: false });
  send(armed ? "disarm" : "arm");
};
$("autoOff").onchange = (e) => send("autoOff", { minutes: e.target.value });
$("forget").onclick = () => send("forget");

chrome.storage.onChanged.addListener(render);
render();
