import * as cameras from "./cameras.js";
import * as live from "./live.js";
import * as playback from "./recordings.js";
import * as settings from "./settings.js";
import * as storage from "./storage.js";
import * as tunnel from "./tunnel.js";
import { api } from "./api.js";
import { loadCameras, store } from "./store.js";
import { bytes, closeOverlay, closeSheet, fail } from "./ui.js";

let socket = null;
let currentView = "live";

function showView(name) {
  currentView = name;
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  document.querySelectorAll(".tabbar button").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  window.scrollTo({ top: 0 });
  if (name === "storage") storage.refresh();
  if (name === "tunnel") tunnel.refresh();
  if (name === "recordings") playback.load();
  if (name === "cameras") cameras.detect();
}

function updateChips(payload) {
  const info = payload.system;
  document.getElementById("chip-cpu").textContent = `CPU ${Math.round(info.cpu_percent)}%${info.cpu_temp ? ` · ${info.cpu_temp}°C` : ""}`;
  const disk = payload.storage;
  document.getElementById("chip-storage").textContent = disk.available
    ? `Disk ${bytes(disk.free)} free`
    : "No storage";
  const dot = document.getElementById("health-dot");
  dot.style.background = disk.available ? "var(--ok)" : "var(--warn)";
  dot.style.boxShadow = `0 0 8px ${disk.available ? "var(--ok)" : "var(--warn)"}`;
}

function handleEvent(event) {
  if (event.type === "stats") {
    updateChips(event);
    settings.renderStats(event);
    Object.entries(event.cameras || {}).forEach(([id, status]) => live.onStatus(id, status));
    return;
  }
  if (event.type === "camera") {
    live.onStatus(event.id, event.status);
    return;
  }
  if (event.type === "tunnel") {
    tunnel.onStatus(event.status);
    return;
  }
  if (event.type === "cameras") {
    loadCameras().catch(() => {});
    return;
  }
  if (event.type === "storage" && currentView === "storage") {
    storage.refresh();
  }
}

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/api/events`);
  socket.addEventListener("message", (message) => {
    try {
      handleEvent(JSON.parse(message.data));
    } catch (error) {
      return;
    }
  });
  socket.addEventListener("close", () => setTimeout(connect, 4000));
}

async function bootstrap() {
  live.init();
  cameras.init();
  playback.init();
  storage.init();
  tunnel.init();
  settings.init();

  document.getElementById("tabbar").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (button) showView(button.dataset.view);
  });
  document.getElementById("sheet-close").addEventListener("click", closeSheet);
  document.getElementById("sheet").addEventListener("click", (event) => {
    if (event.target.id === "sheet") closeSheet();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSheet();
      closeOverlay();
    }
  });

  try {
    const overview = await api.get("/api/system");
    updateChips(overview);
    settings.renderStats(overview);
    tunnel.onStatus(overview.tunnel);
    if (!overview.ffmpeg) fail(new Error("ffmpeg is not installed on this device"));
  } catch (error) {
    fail(error);
  }

  await loadCameras().catch(fail);
  await tunnel.refresh();
  connect();
}

bootstrap();
