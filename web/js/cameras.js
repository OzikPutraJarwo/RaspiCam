import { api } from "./api.js";
import { camera, loadCameras, store } from "./store.js";
import { closeSheet, confirmAction, el, fail, field, input, on, openSheet, select, toast } from "./ui.js";

const FALLBACK_SIZES = [
  [640, 360],
  [640, 480],
  [800, 600],
  [1024, 576],
  [1280, 720],
  [1600, 900],
  [1920, 1080],
];
const FALLBACK_RATES = [30, 25, 20, 15, 10, 5];
const PREVIEW_WIDTHS = [320, 480, 640, 800, 1280];
const FORMAT_ALIASES = { MJPG: "mjpeg", H264: "h264", YUYV: "yuyv422", NV12: "nv12", GREY: "gray" };

let sources = [];

function sourceLabel(source) {
  if (source.type === "csi") return `${source.name} (CSI ${source.index})`;
  return `${source.name}`;
}

function renderSources() {
  const container = document.getElementById("cam-sources");
  container.innerHTML = "";
  if (!sources.length) {
    container.append(el("div", { class: "empty", text: "No unused cameras detected. Press Detect after plugging one in." }));
    return;
  }
  sources.forEach((source) => {
    const best = source.modes[0];
    container.append(
      el("div", { class: "item" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "title", text: sourceLabel(source) }),
          el("div", {
            class: "meta",
            text: `${source.type.toUpperCase()} · ${source.device} · up to ${best ? `${best.width}x${best.height}` : "unknown"}`,
          }),
        ]),
        el("button", {
          class: "btn small primary",
          text: "Add",
          onclick: () => addSource(source),
        }),
      ])
    );
  });
}

async function addSource(source) {
  try {
    await api.post("/api/cameras", { type: source.type, name: source.name, source });
    toast("Camera added", "ok");
    await Promise.all([detect(), loadCameras()]);
  } catch (error) {
    fail(error);
  }
}

function renderCameras() {
  const container = document.getElementById("cam-list");
  container.innerHTML = "";
  if (!store.cameras.length) {
    container.append(el("div", { class: "empty", text: "No cameras configured yet." }));
    return;
  }
  store.cameras.forEach((item) => {
    const status = item.status || {};
    container.append(
      el("div", { class: "item" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "title", text: item.name }),
          el("div", {
            class: "meta",
            text: `${item.type.toUpperCase()} · ${item.width}x${item.height} @ ${item.fps}fps · ${item.record_mode} recording`,
          }),
        ]),
        el("span", { class: `badge ${status.state === "live" ? "live" : status.state === "error" ? "error" : ""}`.trim(), text: status.state || "stopped" }),
        el("button", {
          class: "btn small",
          text: item.enabled ? "Stop" : "Start",
          onclick: () => togglePower(item),
        }),
        el("button", { class: "btn small", text: "Settings", onclick: () => openSettings(item.id) }),
      ])
    );
  });
}

async function togglePower(item) {
  try {
    await api.post(`/api/cameras/${item.id}/${item.enabled ? "stop" : "start"}`);
    await loadCameras();
  } catch (error) {
    fail(error);
  }
}

export async function detect() {
  try {
    const data = await api.get("/api/cameras/discover");
    sources = data.sources;
    renderSources();
  } catch (error) {
    fail(error);
  }
}

function modeOptions(modes, format) {
  const filtered = format ? modes.filter((mode) => mode.format === format) : modes;
  const seen = new Set();
  const options = [];
  filtered.forEach((mode) => {
    const key = `${mode.width}x${mode.height}`;
    if (seen.has(key)) return;
    seen.add(key);
    options.push({ value: key, label: key });
  });
  if (!options.length) {
    FALLBACK_SIZES.forEach(([width, height]) => options.push({ value: `${width}x${height}`, label: `${width}x${height}` }));
  }
  return options;
}

function rateOptions(modes, format, size) {
  const [width, height] = size.split("x").map(Number);
  const match = modes.find((mode) => (!format || mode.format === format) && mode.width === width && mode.height === height);
  const rates = match && match.rates && match.rates.length ? match.rates : FALLBACK_RATES;
  return rates.map((rate) => ({ value: rate, label: `${rate} fps` }));
}

export async function openSettings(cameraId) {
  const item = camera(cameraId);
  if (!item) return;
  let catalog = { modes: [], formats: [] };
  try {
    catalog = await api.get(`/api/cameras/${cameraId}/modes`);
  } catch (error) {
    catalog = { modes: [], formats: [] };
  }
  const body = el("div");
  const nameInput = input("text", item.name, { maxlength: 48 });
  body.append(field("Name", nameInput));

  let formatSelect = null;
  const currentFormat = catalog.formats.find((code) => FORMAT_ALIASES[code] === item.input_format) || catalog.formats[0] || "";
  if (item.type === "usb" && catalog.formats.length) {
    formatSelect = select(
      catalog.formats.map((code) => ({ value: code, label: `${code}${code === "MJPG" ? " (recommended)" : ""}` })),
      currentFormat
    );
    body.append(field("Pixel format", formatSelect, "MJPG uses the least CPU on a Raspberry Pi."));
  }

  const sizeSelect = select(modeOptions(catalog.modes, formatSelect ? formatSelect.value : null), `${item.width}x${item.height}`);
  body.append(field("Resolution", sizeSelect));
  const fpsSelect = select(rateOptions(catalog.modes, formatSelect ? formatSelect.value : null, sizeSelect.value), item.fps);
  body.append(field("Frame rate", fpsSelect));

  const rebuild = () => {
    const format = formatSelect ? formatSelect.value : null;
    const previous = sizeSelect.value;
    sizeSelect.innerHTML = "";
    modeOptions(catalog.modes, format).forEach((option) => {
      const node = el("option", { value: option.value, text: option.label });
      if (option.value === previous) node.selected = true;
      sizeSelect.append(node);
    });
    refreshRates();
  };
  const refreshRates = () => {
    const format = formatSelect ? formatSelect.value : null;
    const previous = fpsSelect.value;
    fpsSelect.innerHTML = "";
    rateOptions(catalog.modes, format, sizeSelect.value).forEach((option) => {
      const node = el("option", { value: option.value, text: option.label });
      if (String(option.value) === String(previous)) node.selected = true;
      fpsSelect.append(node);
    });
  };
  if (formatSelect) formatSelect.addEventListener("change", rebuild);
  sizeSelect.addEventListener("change", refreshRates);

  const bitrateInput = input("number", item.bitrate, { min: 300, max: 20000, step: 100 });
  body.append(field("Recording bitrate (kbps)", bitrateInput));

  const rotationSelect = select(
    [0, 90, 180, 270].map((value) => ({ value, label: `${value}°` })),
    item.rotation
  );
  body.append(field("Rotation", rotationSelect));

  const previewWidth = select(
    PREVIEW_WIDTHS.map((value) => ({ value, label: `${value}px wide` })),
    item.preview_width
  );
  body.append(field("Live view size", previewWidth, "Smaller previews keep remote access smooth."));

  const previewFps = input("number", item.preview_fps, { min: 1, max: 30, step: 1 });
  const previewQuality = input("number", item.preview_quality, { min: 2, max: 20, step: 1 });
  const previewRow = el("div", { class: "row" }, [field("Live view fps", previewFps), field("Live view quality", previewQuality)]);
  body.append(previewRow);

  const recordSelect = select(
    [
      { value: "off", label: "Off" },
      { value: "manual", label: "Manual only" },
      { value: "continuous", label: "Continuous (CCTV)" },
    ],
    item.record_mode
  );
  body.append(field("Recording mode", recordSelect, "Continuous keeps rolling segments until storage limits kick in."));

  if (item.type === "network") {
    const urlInput = input("text", item.url);
    body.append(field("Stream URL", urlInput));
    body.dataset.url = "1";
    body.urlInput = urlInput;
  }

  const save = el("button", {
    class: "btn primary",
    text: "Save",
    onclick: async () => {
      const [width, height] = sizeSelect.value.split("x").map(Number);
      const payload = {
        name: nameInput.value.trim() || item.name,
        width,
        height,
        fps: Number(fpsSelect.value),
        bitrate: Number(bitrateInput.value),
        rotation: Number(rotationSelect.value),
        preview_width: Number(previewWidth.value),
        preview_fps: Number(previewFps.value),
        preview_quality: Number(previewQuality.value),
        record_mode: recordSelect.value,
      };
      if (formatSelect) payload.input_format = FORMAT_ALIASES[formatSelect.value] || "mjpeg";
      if (body.urlInput) payload.url = body.urlInput.value.trim();
      save.disabled = true;
      try {
        await api.patch(`/api/cameras/${cameraId}`, payload);
        toast("Settings saved", "ok");
        closeSheet();
        await loadCameras();
      } catch (error) {
        fail(error);
        save.disabled = false;
      }
    },
  });

  const remove = el("button", {
    class: "btn danger",
    text: "Remove camera",
    onclick: async () => {
      if (!confirmAction(`Remove ${item.name}? Recorded files stay on disk.`)) return;
      try {
        await api.del(`/api/cameras/${cameraId}`);
        closeSheet();
        toast("Camera removed", "ok");
        await Promise.all([detect(), loadCameras()]);
      } catch (error) {
        fail(error);
      }
    },
  });

  body.append(el("div", { class: "actions" }, [save, remove]));
  openSheet(item.name, body);
}

function openNetworkSheet() {
  const body = el("div");
  const nameInput = input("text", "Network camera", { maxlength: 48 });
  const urlInput = input("text", "", { placeholder: "rtsp://user:pass@192.168.1.50:554/stream" });
  body.append(field("Name", nameInput));
  body.append(field("Stream URL", urlInput, "RTSP and HTTP streams are supported."));
  const button = el("button", {
    class: "btn primary",
    text: "Test and add",
    onclick: async () => {
      button.disabled = true;
      button.textContent = "Testing...";
      try {
        await api.post("/api/cameras", { type: "network", name: nameInput.value.trim() || "Network camera", url: urlInput.value.trim() });
        toast("Camera added", "ok");
        closeSheet();
        await loadCameras();
      } catch (error) {
        fail(error);
        button.disabled = false;
        button.textContent = "Test and add";
      }
    },
  });
  body.append(el("div", { class: "actions" }, [button]));
  openSheet("Add network camera", body);
}

export function init() {
  document.getElementById("cam-detect").addEventListener("click", detect);
  document.getElementById("cam-add-network").addEventListener("click", openNetworkSheet);
  on("cameras", renderCameras);
  detect();
}
