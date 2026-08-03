import { api } from "./api.js";
import { loadCameras } from "./store.js";
import { bytes, duration, el, fail, toast } from "./ui.js";

let overview = null;

function usageBar(percent) {
  const level = percent > 92 ? "danger" : percent > 78 ? "warn" : "";
  return el("div", { class: "bar" }, [el("span", { class: level, style: `width:${Math.min(100, percent)}%` })]);
}

function renderSummary() {
  const container = document.getElementById("storage-summary");
  container.innerHTML = "";
  const summary = overview.summary;
  const stats = overview.recordings;
  if (!summary.configured || !summary.available) {
    container.append(
      el("div", { class: "empty", text: "No storage selected yet. Pick a location below to start recording." })
    );
    return;
  }
  container.append(el("h2", { text: "Current location" }));
  container.append(el("div", { class: "title", text: summary.root }));
  container.append(
    el("div", { class: "meta", text: `${bytes(summary.used)} used of ${bytes(summary.total)} · ${bytes(summary.free)} free` })
  );
  container.append(usageBar(summary.percent));
  container.append(
    el("div", { class: "stat-grid", style: "margin-top:14px" }, [
      el("div", { class: "stat" }, [el("b", { text: String(stats.count || 0) }), el("span", { text: "Segments" })]),
      el("div", { class: "stat" }, [el("b", { text: bytes(stats.size) }), el("span", { text: "Recorded" })]),
      el("div", { class: "stat" }, [el("b", { text: duration(stats.duration) }), el("span", { text: "Footage" })]),
    ])
  );
}

function renderMounts() {
  const container = document.getElementById("storage-mounts");
  container.innerHTML = "";
  if (!overview.mounts.length) {
    container.append(el("div", { class: "empty", text: "No writable storage detected." }));
    return;
  }
  overview.mounts.forEach((mount) => {
    const label = mount.label || mount.model || mount.name || mount.path;
    container.append(
      el("div", { class: `item${mount.selected ? " selected" : ""}` }, [
        el("div", { class: "grow" }, [
          el("div", { class: "title", text: `${label} · ${mount.path}` }),
          el("div", {
            class: "meta",
            text: `${mount.kind.toUpperCase()} · ${mount.fstype || "unknown"} · ${bytes(mount.free)} free of ${bytes(mount.total)}`,
          }),
          usageBar(mount.percent),
        ]),
        mount.selected
          ? el("span", { class: "badge live", text: "In use" })
          : el("button", {
              class: "btn small primary",
              text: "Use",
              disabled: !mount.writable,
              onclick: () => selectMount(mount.path),
            }),
      ])
    );
  });
}

function renderSettings() {
  const settings = overview.summary.settings || {};
  document.getElementById("storage-segment").value = Math.round((settings.segment_seconds || 300) / 60);
  document.getElementById("storage-retention").value = settings.retention_percent || 85;
  document.getElementById("storage-free").value = settings.min_free_gb || 2;
}

async function selectMount(path) {
  try {
    await api.post("/api/storage/select", { path });
    toast("Storage location updated", "ok");
    await refresh();
    await loadCameras();
  } catch (error) {
    fail(error);
  }
}

export async function refresh() {
  try {
    overview = await api.get("/api/storage");
    renderSummary();
    renderMounts();
    renderSettings();
  } catch (error) {
    fail(error);
  }
}

export function init() {
  document.getElementById("storage-scan").addEventListener("click", async () => {
    try {
      const result = await api.post("/api/storage/scan");
      toast(`Indexed ${result.added} new segments`, "ok");
      await refresh();
    } catch (error) {
      fail(error);
    }
  });
  document.getElementById("storage-save").addEventListener("click", async () => {
    const payload = {
      segment_seconds: Number(document.getElementById("storage-segment").value) * 60,
      retention_percent: Number(document.getElementById("storage-retention").value),
      min_free_gb: Number(document.getElementById("storage-free").value),
    };
    try {
      await api.patch("/api/storage/settings", payload);
      toast("Rules saved", "ok");
      await refresh();
    } catch (error) {
      fail(error);
    }
  });
}
