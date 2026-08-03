import { api } from "./api.js";
import { bytes, closeSheet, confirmAction, duration, el, fail, openSheet, toast } from "./ui.js";

let removable = false;

export function renderStats(payload) {
  const container = document.getElementById("settings-stats");
  if (!container || !payload || !payload.system) return;
  const info = payload.system;
  container.innerHTML = "";
  const entries = [
    ["Device", info.model.length > 34 ? info.model.slice(0, 34) + "…" : info.model],
    ["Hostname", info.hostname],
    ["Local address", `${info.address}:${payload.port}`],
    ["CPU load", `${Math.round(info.cpu_percent)}%`],
    ["Temperature", info.cpu_temp === null ? "n/a" : `${info.cpu_temp}°C`],
    ["Memory", `${bytes(info.memory_used)} / ${bytes(info.memory_total)}`],
    ["Uptime", duration(info.uptime)],
    ["Encoder", payload.encoder],
    ["Version", info.version],
  ];
  entries.forEach(([label, value]) => {
    container.append(el("div", { class: "stat" }, [el("span", { text: label }), el("b", { text: String(value) })]));
  });
  if (typeof payload.removable === "boolean") removable = payload.removable;
}

function farewell() {
  document.body.innerHTML = "";
  document.body.append(
    el("div", { class: "farewell" }, [
      el("div", { class: "brand", html: "Raspi<em>Cam</em>" }),
      el("h1", { text: "RaspiCam has been removed" }),
      el("p", { text: "The service, its files and its settings are gone. You can close this tab." }),
    ])
  );
  setTimeout(() => {
    window.open("", "_self");
    window.close();
  }, 1500);
}

function openUninstall() {
  const body = el("div");
  body.append(
    el("p", {
      style: "margin:0 0 14px;color:var(--muted);font-size:13px",
      text:
        "This stops the service and deletes the program files, your settings and the tunnel clients installed with RaspiCam. " +
        "System packages such as ffmpeg and Node.js are left alone because other software may need them.",
    })
  );
  const media = el("input", { type: "checkbox" });
  body.append(el("label", { class: "switch", style: "margin-bottom:16px" }, [media, "Also delete every recording and photo"]));
  const button = el("button", {
    class: "btn danger",
    text: "Remove RaspiCam",
    onclick: async () => {
      const warning = media.checked
        ? "Remove RaspiCam and permanently delete all recorded video?"
        : "Remove RaspiCam from this device?";
      if (!confirmAction(warning)) return;
      button.disabled = true;
      button.textContent = "Removing...";
      try {
        await api.post("/api/system/uninstall", { media: media.checked });
        closeSheet();
        farewell();
      } catch (error) {
        fail(error);
        button.disabled = false;
        button.textContent = "Remove RaspiCam";
      }
    },
  });
  body.append(el("div", { class: "actions" }, [button]));
  openSheet("Uninstall", body);
}

export function init() {
  document.getElementById("pw-save").addEventListener("click", async () => {
    const current = document.getElementById("pw-current").value;
    const password = document.getElementById("pw-new").value;
    if (password.length < 6) {
      toast("New password must be at least 6 characters", "error");
      return;
    }
    try {
      await api.post("/api/auth/password", { current, password });
      document.getElementById("pw-current").value = "";
      document.getElementById("pw-new").value = "";
      toast("Password updated", "ok");
    } catch (error) {
      fail(error);
    }
  });
  document.getElementById("settings-restart").addEventListener("click", async () => {
    try {
      await api.post("/api/system/restart");
      toast("Restarting, this page will reconnect shortly", "ok");
    } catch (error) {
      fail(error);
    }
  });
  document.getElementById("settings-logout").addEventListener("click", async () => {
    await api.post("/api/auth/logout").catch(() => {});
    window.location.href = "/login";
  });
  document.getElementById("settings-uninstall").addEventListener("click", () => {
    if (!removable) {
      toast("Run: sudo raspicam uninstall", "error");
      return;
    }
    openUninstall();
  });
}
