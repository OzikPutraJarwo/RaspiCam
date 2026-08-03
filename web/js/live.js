import { api } from "./api.js";
import { openSettings } from "./cameras.js";
import { camera, loadCameras, store } from "./store.js";
import { closeOverlay, el, fail, on, openOverlay, toast } from "./ui.js";

const tiles = new Map();
const POLL_INTERVAL = 1500;
let mode = localStorage.getItem("raspicam-live-mode") === "poll" ? "poll" : "stream";
let pollTimer = null;

function streamUrl(id) {
  return `/api/cameras/${id}/stream?t=${Date.now()}`;
}

function snapshotUrl(id) {
  return `/api/cameras/${id}/snapshot.jpg?t=${Date.now()}`;
}

function buildTile(item) {
  const image = el("img", { alt: item.name, class: "hidden" });
  const note = el("div", { class: "tile-note" });
  const tags = el("div", { class: "tile-tag" });
  const media = el("div", { class: "tile-media", onclick: () => expand(item.id) }, [image, note, tags]);
  const name = el("div", { class: "tile-name", text: item.name });
  const recordButton = el("button", { class: "btn small", text: "Record", onclick: (event) => toggleRecord(event, item.id) });
  const photoButton = el("button", { class: "btn small", text: "Photo", onclick: (event) => capture(event, item.id) });
  const powerButton = el("button", { class: "btn small", text: "Stop", onclick: (event) => togglePower(event, item.id) });
  const settingsButton = el("button", { class: "btn small", text: "Setup", onclick: (event) => { event.stopPropagation(); openSettings(item.id); } });
  const bar = el("div", { class: "tile-bar" }, [
    name,
    el("div", { class: "tile-actions" }, [photoButton, recordButton, powerButton, settingsButton]),
  ]);
  const root = el("article", { class: "tile", dataset: { id: item.id } }, [media, bar]);
  return { root, image, note, tags, name, recordButton, photoButton, powerButton, attached: "none" };
}

function detach(tile) {
  tile.image.src = "";
  tile.image.classList.add("hidden");
  tile.attached = "none";
}

function attach(tile, item) {
  const status = item.status || {};
  const running = status.state === "live";
  if (!running) {
    if (tile.attached !== "none") detach(tile);
    return;
  }
  if (mode === "stream" && tile.attached !== "stream") {
    tile.image.src = streamUrl(item.id);
    tile.image.classList.remove("hidden");
    tile.attached = "stream";
  } else if (mode === "poll" && tile.attached !== "poll") {
    tile.image.src = snapshotUrl(item.id);
    tile.image.classList.remove("hidden");
    tile.attached = "poll";
  }
}

function updateTile(item) {
  const tile = tiles.get(item.id);
  if (!tile) return;
  const status = item.status || {};
  tile.name.textContent = item.name;
  tile.tags.innerHTML = "";
  if (status.state === "live") {
    tile.tags.append(el("span", { class: "badge live", text: `LIVE ${status.fps ? `${status.fps}fps` : ""}`.trim() }));
  } else if (status.state === "starting") {
    tile.tags.append(el("span", { class: "badge warn", text: "Starting" }));
  } else if (status.state === "error") {
    tile.tags.append(el("span", { class: "badge error", text: "Error" }));
  }
  if (status.recording) tile.tags.append(el("span", { class: "badge rec", text: "REC" }));
  tile.powerButton.textContent = item.enabled ? "Stop" : "Start";
  tile.recordButton.classList.toggle("active", Boolean(status.recording));
  tile.recordButton.disabled = status.state !== "live" || item.record_mode === "off";
  tile.photoButton.disabled = status.state !== "live" && !item.enabled;
  if (status.state === "live") {
    tile.note.textContent = "";
    tile.note.hidden = true;
  } else {
    tile.note.hidden = false;
    tile.note.textContent = item.enabled
      ? status.error || "Connecting to camera..."
      : "Camera is off. Tap Start to begin.";
  }
  attach(tile, item);
}

function render(list) {
  const grid = document.getElementById("live-grid");
  const empty = document.getElementById("live-empty");
  empty.hidden = list.length > 0;
  const ids = new Set(list.map((item) => item.id));
  tiles.forEach((tile, id) => {
    if (!ids.has(id)) {
      detach(tile);
      tile.root.remove();
      tiles.delete(id);
    }
  });
  list.forEach((item) => {
    let tile = tiles.get(item.id);
    if (!tile) {
      tile = buildTile(item);
      tiles.set(item.id, tile);
      grid.append(tile.root);
    }
    updateTile(item);
  });
}

async function togglePower(event, id) {
  event.stopPropagation();
  const item = camera(id);
  if (!item) return;
  try {
    await api.post(`/api/cameras/${id}/${item.enabled ? "stop" : "start"}`);
    await loadCameras();
  } catch (error) {
    fail(error);
  }
}

async function toggleRecord(event, id) {
  event.stopPropagation();
  const item = camera(id);
  if (!item) return;
  const active = !(item.status && item.status.recording);
  try {
    await api.post(`/api/cameras/${id}/record`, { active });
    toast(active ? "Recording started" : "Recording stopped", "ok");
    await loadCameras();
  } catch (error) {
    fail(error);
  }
}

async function capture(event, id) {
  event.stopPropagation();
  try {
    const result = await api.post(`/api/cameras/${id}/capture`);
    toast(`Photo saved as ${result.name}`, "ok");
  } catch (error) {
    fail(error);
  }
}

function expand(id) {
  const item = camera(id);
  if (!item || !item.status || item.status.state !== "live") return;
  const recordButton = el("button", {
    class: "btn",
    text: item.status.recording ? "Stop recording" : "Start recording",
    onclick: async (event) => {
      await toggleRecord(event, id);
      closeOverlay();
    },
  });
  const photoButton = el("button", { class: "btn", text: "Take photo", onclick: (event) => capture(event, id) });
  const setupButton = el("button", {
    class: "btn",
    text: "Settings",
    onclick: () => {
      closeOverlay();
      openSettings(id);
    },
  });
  openOverlay(item.name, streamUrl(id), [photoButton, recordButton, setupButton]);
}

function applyMode() {
  const button = document.getElementById("live-mode");
  button.classList.toggle("active", mode === "poll");
  button.textContent = mode === "poll" ? "Low bandwidth on" : "Low bandwidth";
  tiles.forEach((tile) => detach(tile));
  render(store.cameras);
  clearInterval(pollTimer);
  if (mode === "poll") {
    pollTimer = setInterval(() => {
      tiles.forEach((tile, id) => {
        if (tile.attached === "poll") tile.image.src = snapshotUrl(id);
      });
    }, POLL_INTERVAL);
  }
}

export function onStatus(id, status) {
  const item = camera(id);
  if (!item) return;
  item.status = status;
  updateTile(item);
}

export function init() {
  document.getElementById("live-refresh").addEventListener("click", () => {
    tiles.forEach((tile) => detach(tile));
    loadCameras().catch(fail);
  });
  document.getElementById("live-mode").addEventListener("click", () => {
    mode = mode === "poll" ? "stream" : "poll";
    localStorage.setItem("raspicam-live-mode", mode);
    applyMode();
  });
  document.getElementById("overlay-close").addEventListener("click", closeOverlay);
  on("cameras", render);
  applyMode();
}
