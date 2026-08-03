import { api } from "./api.js";
import { closeOverlay, el, fail, openOverlay, toast } from "./ui.js";

let data = null;

const STATE_CLASS = { online: "live", starting: "warn", reconnecting: "warn", error: "error" };

function autostartList() {
  return (data.settings && data.settings.autostart) || [];
}

async function saveAutostart(provider, enabled) {
  const current = new Set(autostartList());
  if (enabled) current.add(provider);
  else current.delete(provider);
  try {
    data.settings = await api.patch("/api/tunnel/settings", { autostart: [...current] });
  } catch (error) {
    fail(error);
  }
}

function urlRow(provider) {
  const url = provider.status.url;
  const link = el("a", {
    class: "mono url",
    text: url,
    href: url,
    target: "_blank",
    rel: "noopener",
  });
  const buttons = el("div", { class: "actions" }, [
    el("button", {
      class: "btn small",
      text: "Copy",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(url);
          toast("Link copied", "ok");
        } catch (error) {
          toast(url);
        }
      },
    }),
    provider.qr
      ? el("button", {
          class: "btn small",
          text: "QR",
          onclick: () =>
            openOverlay(url, provider.qr, [el("button", { class: "btn", text: "Close", onclick: closeOverlay })]),
        })
      : null,
  ]);
  return el("div", { style: "width:100%" }, [link, buttons]);
}

function renderProviders() {
  const container = document.getElementById("tunnel-providers");
  container.innerHTML = "";
  const autostart = autostartList();
  data.providers.forEach((provider) => {
    const status = provider.status;
    const running = Boolean(status) && status.state !== "stopped";
    const detail = provider.available ? status && status.error : `${provider.requires} is not installed`;
    const head = el("div", { class: "grow" }, [
      el("div", { class: "title", text: provider.label }),
      detail ? el("div", { class: "meta prose", text: detail }) : null,
    ]);
    const controls = [];
    if (status && status.state !== "stopped") {
      controls.push(el("span", { class: `badge ${STATE_CLASS[status.state] || ""}`.trim(), text: status.state }));
    }
    controls.push(
      el("label", { class: "switch", title: "Start automatically on boot" }, [
        el("input", {
          type: "checkbox",
          checked: autostart.includes(provider.id),
          disabled: !provider.available,
          onchange: (event) => saveAutostart(provider.id, event.target.checked),
        }),
        "auto",
      ])
    );
    controls.push(
      el("button", {
        class: `btn small${running ? " danger" : ""}`,
        text: running ? "Stop" : "Start",
        disabled: !provider.available,
        onclick: () => (running ? stop(provider.id) : start(provider.id)),
      })
    );
    const rows = [head, ...controls];
    if (status && status.url) rows.push(urlRow(provider));
    container.append(el("div", { class: `item${status && status.url ? " selected" : ""}` }, rows));
  });
}

function renderLog() {
  const container = document.getElementById("tunnel-log");
  const lines = [];
  data.providers.forEach((provider) => {
    if (!provider.status) return;
    provider.status.log.forEach((line) => lines.push(`[${provider.id}] ${line}`));
  });
  container.textContent = lines.slice(-40).join("\n") || "Nothing yet.";
  container.scrollTop = container.scrollHeight;
}

async function start(provider) {
  try {
    await api.post("/api/tunnel/start", { provider });
    toast("Starting tunnel", "ok");
    setTimeout(refresh, 1500);
  } catch (error) {
    fail(error);
  }
}

async function stop(provider) {
  try {
    await api.post("/api/tunnel/stop", { provider });
    await refresh();
  } catch (error) {
    fail(error);
  }
}

export function updateChip(sessions) {
  const chip = document.getElementById("tunnel-chip");
  const online = Object.values(sessions || {}).filter((session) => session.url);
  if (!online.length) {
    chip.hidden = true;
    return;
  }
  chip.hidden = false;
  chip.href = online[0].url;
  const label = online[0].url.replace(/^https?:\/\//, "");
  chip.textContent = online.length > 1 ? `${label} +${online.length - 1}` : label;
}

export function onSessions(sessions) {
  updateChip(sessions);
  if (!data) return;
  data.providers.forEach((provider) => {
    provider.status = sessions[provider.id] || null;
    if (!provider.status || !provider.status.url) provider.qr = null;
  });
  const missingQr = data.providers.some((provider) => provider.status && provider.status.url && !provider.qr);
  if (missingQr) {
    refresh();
    return;
  }
  renderProviders();
  renderLog();
}

export async function refresh() {
  try {
    data = await api.get("/api/tunnel");
    renderProviders();
    renderLog();
    updateChip(Object.fromEntries(data.providers.filter((p) => p.status).map((p) => [p.id, p.status])));
  } catch (error) {
    fail(error);
  }
}

export function init() {
  document.getElementById("tunnel-stop-all").addEventListener("click", async () => {
    try {
      await api.post("/api/tunnel/stop", {});
      toast("All tunnels stopped", "ok");
      await refresh();
    } catch (error) {
      fail(error);
    }
  });
}
