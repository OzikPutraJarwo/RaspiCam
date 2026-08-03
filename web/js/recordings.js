import { api } from "./api.js";
import { store } from "./store.js";
import { bytes, clock, confirmAction, dayKey, duration, el, fail, on, openOverlay, toast } from "./ui.js";

let cameraId = null;
let date = dayKey(new Date());
let segments = [];
let dayStart = 0;
let current = null;
let availableDays = [];

const player = () => document.getElementById("rec-player");

function fillCameras(list) {
  const selector = document.getElementById("rec-camera");
  const previous = cameraId;
  selector.innerHTML = "";
  list.forEach((item) => {
    const option = el("option", { value: item.id, text: item.name });
    selector.append(option);
  });
  if (!list.length) {
    cameraId = null;
    return;
  }
  cameraId = list.some((item) => item.id === previous) ? previous : list[0].id;
  selector.value = cameraId;
  if (previous !== cameraId) load();
}

function renderTimeline() {
  const container = document.getElementById("rec-timeline");
  container.innerHTML = "";
  for (let hour = 0; hour <= 24; hour += 3) {
    container.append(
      el("div", { class: "timeline-tick", style: `left:${(hour / 24) * 100}%`, text: hour === 24 ? "" : `${String(hour).padStart(2, "0")}:00` })
    );
  }
  segments.forEach((segment) => {
    const offset = (segment.start_ts - dayStart) / 86400;
    const width = Math.max(segment.duration / 86400, 0.0012);
    const block = el("div", {
      class: `timeline-block${current && current.id === segment.id ? " active" : ""}`,
      style: `left:${offset * 100}%;width:${width * 100}%`,
      title: `${clock(segment.start_ts)} · ${duration(segment.duration)}`,
    });
    container.append(block);
  });
  container.append(el("div", { class: "timeline-head", id: "rec-head", style: "left:0;display:none" }));
}

function renderList() {
  const container = document.getElementById("rec-list");
  container.innerHTML = "";
  if (!segments.length) {
    container.append(el("div", { class: "empty", text: "No recordings for this day." }));
    return;
  }
  segments.forEach((segment) => {
    container.append(
      el("div", { class: `item${current && current.id === segment.id ? " selected" : ""}` }, [
        el("div", { class: "grow" }, [
          el("div", { class: "title", text: clock(segment.start_ts) }),
          el("div", { class: "meta", text: `${duration(segment.duration)} · ${bytes(segment.size)}` }),
        ]),
        el("button", { class: "btn small", text: "Play", onclick: () => play(segment, 0) }),
        el("a", { class: "btn small", text: "Save", href: `/api/recordings/${segment.id}/file?download=true`, download: "" }),
        el("button", {
          class: "btn small danger",
          text: "Delete",
          onclick: async () => {
            if (!confirmAction("Delete this recording?")) return;
            try {
              await api.del(`/api/recordings/${segment.id}`);
              await load();
            } catch (error) {
              fail(error);
            }
          },
        }),
      ])
    );
  });
}

function play(segment, offset) {
  current = segment;
  const video = player();
  video.src = `/api/recordings/${segment.id}/file`;
  video.load();
  const seek = () => {
    if (offset > 0) video.currentTime = Math.min(offset, Math.max(0, segment.duration - 0.5));
    video.play().catch(() => {});
    video.removeEventListener("loadedmetadata", seek);
  };
  video.addEventListener("loadedmetadata", seek);
  renderTimeline();
  renderList();
}

function seekToTimestamp(timestamp) {
  if (!segments.length) return;
  const containing = segments.find((segment) => timestamp >= segment.start_ts && timestamp < segment.start_ts + segment.duration);
  if (containing) {
    play(containing, timestamp - containing.start_ts);
    return;
  }
  const next = segments.find((segment) => segment.start_ts >= timestamp);
  if (next) play(next, 0);
  else toast("No footage at that time");
}

function updateHead() {
  const head = document.getElementById("rec-head");
  const label = document.getElementById("rec-position");
  if (!head || !current) return;
  const absolute = current.start_ts + player().currentTime;
  const ratio = (absolute - dayStart) / 86400;
  head.style.display = "block";
  head.style.left = `${Math.min(100, Math.max(0, ratio * 100))}%`;
  label.textContent = `Playing ${clock(absolute)}`;
}

export async function load() {
  if (!cameraId) {
    segments = [];
    dayStart = 0;
    renderTimeline();
    renderList();
    document.getElementById("rec-gallery").innerHTML = "";
    return;
  }
  try {
    const data = await api.get(`/api/recordings?camera=${cameraId}&date=${date}`);
    segments = data.segments;
    dayStart = data.start;
    availableDays = data.days || [];
    current = null;
    document.getElementById("rec-date").value = data.date;
    renderTimeline();
    renderList();
    await loadCaptures();
  } catch (error) {
    fail(error);
  }
}

async function loadCaptures() {
  const container = document.getElementById("rec-gallery");
  container.innerHTML = "";
  try {
    const data = await api.get(`/api/recordings/captures?camera=${cameraId}`);
    if (!data.captures.length) {
      container.append(el("div", { class: "empty", text: "No photos yet." }));
      return;
    }
    data.captures.forEach((capture) => {
      const source = `/api/recordings/captures/${cameraId}/${capture.name}`;
      container.append(
        el("figure", {}, [
          el("img", { src: source, alt: capture.name, loading: "lazy", onclick: () => openOverlay(capture.name, source, []) }),
          el("figcaption", {}, [
            el("span", { text: clock(capture.timestamp) }),
            el("button", {
              text: "×",
              title: "Delete",
              onclick: async () => {
                try {
                  await api.del(`/api/recordings/captures/${cameraId}/${capture.name}`);
                  await loadCaptures();
                } catch (error) {
                  fail(error);
                }
              },
            }),
          ]),
        ])
      );
    });
  } catch (error) {
    fail(error);
  }
}

function shiftDay(step) {
  const withFootage = step < 0 ? availableDays.filter((day) => day < date) : availableDays.filter((day) => day > date).reverse();
  if (withFootage.length) {
    date = withFootage[0];
  } else {
    const parts = date.split("-").map(Number);
    const value = new Date(parts[0], parts[1] - 1, parts[2]);
    value.setDate(value.getDate() + step);
    date = dayKey(value);
  }
  load();
}

export function init() {
  document.getElementById("rec-camera").addEventListener("change", (event) => {
    cameraId = event.target.value;
    load();
  });
  document.getElementById("rec-date").addEventListener("change", (event) => {
    date = event.target.value || dayKey(new Date());
    load();
  });
  document.getElementById("rec-prev").addEventListener("click", () => shiftDay(-1));
  document.getElementById("rec-next").addEventListener("click", () => shiftDay(1));
  document.getElementById("rec-today").addEventListener("click", () => {
    date = dayKey(new Date());
    load();
  });
  document.getElementById("rec-reload").addEventListener("click", load);
  document.getElementById("rec-timeline").addEventListener("click", (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    seekToTimestamp(dayStart + ratio * 86400);
  });
  player().addEventListener("timeupdate", updateHead);
  player().addEventListener("ended", () => {
    const index = segments.findIndex((segment) => current && segment.id === current.id);
    if (index >= 0 && index + 1 < segments.length) play(segments[index + 1], 0);
  });
  document.getElementById("rec-date").value = date;
  on("cameras", fillCameras);
  fillCameras(store.cameras);
}
