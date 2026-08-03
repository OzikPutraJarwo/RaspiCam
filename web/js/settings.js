import { api } from "./api.js";
import { bytes, duration, el, fail, toast } from "./ui.js";

export function renderStats(payload) {
  const container = document.getElementById("settings-stats");
  if (!container || !payload) return;
  const info = payload.system;
  container.innerHTML = "";
  const entries = [
    [info.hostname, "Hostname"],
    [`${info.address}:${payload.port}`, "Local address"],
    [`${Math.round(info.cpu_percent)}%`, "CPU"],
    [info.cpu_temp === null ? "n/a" : `${info.cpu_temp}°C`, "Temperature"],
    [`${bytes(info.memory_used)} / ${bytes(info.memory_total)}`, "Memory"],
    [duration(info.uptime), "Uptime"],
    [payload.encoder, "Video encoder"],
    [info.version, "Version"],
  ];
  entries.forEach(([value, label]) => {
    container.append(el("div", { class: "stat" }, [el("b", { text: String(value) }), el("span", { text: label })]));
  });
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
}
