import { api } from "./api.js";
import { el, fail, toast } from "./ui.js";

let data = null;
let selected = null;

function providerLabel(id) {
  const match = data.providers.find((provider) => provider.id === id);
  return match ? match.label : id;
}

function renderStatus() {
  const container = document.getElementById("tunnel-status");
  container.innerHTML = "";
  const status = data.status;
  const badgeClass = status.state === "online" ? "live" : status.state === "stopped" ? "" : "warn";
  container.append(
    el("div", { class: "item", style: "background:transparent;border:0;padding:0" }, [
      el("div", { class: "grow" }, [
        el("div", { class: "title", text: status.provider ? providerLabel(status.provider) : "No tunnel running" }),
        el("div", { class: "meta", text: status.error || `Dashboard port ${data.port}` }),
      ]),
      el("span", { class: `badge ${badgeClass}`.trim(), text: status.state }),
    ])
  );
  if (status.url) {
    container.append(
      el("div", { class: "field", style: "margin-top:12px" }, [
        el("label", { text: "Public address" }),
        el("div", { class: "actions" }, [
          el("a", { class: "btn", text: status.url, href: status.url, target: "_blank", rel: "noopener" }),
          el("button", {
            class: "btn small",
            text: "Copy",
            onclick: async () => {
              try {
                await navigator.clipboard.writeText(status.url);
                toast("Link copied", "ok");
              } catch (error) {
                toast(status.url);
              }
            },
          }),
        ]),
      ])
    );
    if (data.qr) {
      container.append(el("img", { src: data.qr, alt: "QR code", style: "margin-top:12px;width:170px;border-radius:10px" }));
    }
  }
  container.append(
    el("div", { class: "actions", style: "margin-top:12px" }, [
      el("button", {
        class: "btn primary",
        text: status.state === "stopped" ? "Start tunnel" : "Restart tunnel",
        disabled: !selected || !data.providers.some((provider) => provider.id === selected && provider.available),
        onclick: start,
      }),
      el("button", { class: "btn danger", text: "Stop", disabled: status.state === "stopped", onclick: stop }),
    ])
  );
}

function renderProviders() {
  const container = document.getElementById("tunnel-providers");
  container.innerHTML = "";
  data.providers.forEach((provider) => {
    container.append(
      el("div", { class: `item${selected === provider.id ? " selected" : ""}` }, [
        el("div", { class: "grow" }, [
          el("div", { class: "title", text: provider.label }),
          el("div", { class: "meta", text: provider.available ? provider.hint : `${provider.requires} is not installed. ${provider.hint}` }),
        ]),
        provider.available
          ? el("button", {
              class: `btn small${selected === provider.id ? " active" : ""}`,
              text: selected === provider.id ? "Selected" : "Select",
              onclick: () => {
                selected = provider.id;
                renderProviders();
                renderStatus();
              },
            })
          : el("span", { class: "badge", text: "Unavailable" }),
      ])
    );
  });
}

function renderLog() {
  const container = document.getElementById("tunnel-log");
  container.textContent = (data.status.log || []).join("\n") || "No output yet.";
  container.scrollTop = container.scrollHeight;
}

async function start() {
  if (!selected) return;
  try {
    await api.post("/api/tunnel/start", { provider: selected });
    toast("Tunnel starting", "ok");
    setTimeout(refresh, 1200);
  } catch (error) {
    fail(error);
  }
}

async function stop() {
  try {
    await api.post("/api/tunnel/stop");
    toast("Tunnel stopped", "ok");
    await refresh();
  } catch (error) {
    fail(error);
  }
}

export function onStatus(status) {
  if (!data) return;
  data.status = status;
  renderStatus();
  renderLog();
  updateChip(status);
}

function updateChip(status) {
  const chip = document.getElementById("tunnel-chip");
  if (status && status.url) {
    chip.hidden = false;
    chip.textContent = status.url.replace(/^https?:\/\//, "");
    chip.href = status.url;
    chip.target = "_blank";
  } else {
    chip.hidden = true;
  }
}

export async function refresh() {
  try {
    data = await api.get("/api/tunnel");
    const usable = data.providers.filter((provider) => provider.available).map((provider) => provider.id);
    const preferred = [selected, data.status.provider, data.settings && data.settings.provider].find((id) => usable.includes(id));
    selected = preferred || usable[0] || null;
    document.getElementById("tunnel-autostart").checked = Boolean(data.settings && data.settings.autostart);
    renderProviders();
    renderStatus();
    renderLog();
    updateChip(data.status);
  } catch (error) {
    fail(error);
  }
}

export function init() {
  document.getElementById("tunnel-autostart").addEventListener("change", async (event) => {
    try {
      await api.patch("/api/tunnel/settings", { autostart: event.target.checked, provider: selected || undefined });
      toast("Preference saved", "ok");
    } catch (error) {
      fail(error);
    }
  });
}
