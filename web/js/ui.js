const listeners = new Map();

export function on(event, handler) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(handler);
}

export function emit(event, payload) {
  (listeners.get(event) || []).forEach((handler) => handler(payload));
}

export function el(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attributes).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? "" : value);
  });
  (Array.isArray(children) ? children : [children]).forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    node.append(child.nodeType ? child : document.createTextNode(child));
  });
  return node;
}

let toastTimer = null;

export function toast(message, kind = "") {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  const node = el("div", { class: `toast ${kind}`.trim(), text: message });
  document.body.append(node);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), 3600);
}

export function fail(error) {
  toast(error && error.message ? error.message : String(error), "error");
}

export function bytes(value) {
  const size = Number(value) || 0;
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let index = -1;
  let current = size;
  do {
    current /= 1024;
    index += 1;
  } while (current >= 1024 && index < units.length - 1);
  return `${current.toFixed(current >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

export function duration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${rest}s`;
}

export function clock(timestamp) {
  return new Date(timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dayKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const sheet = () => document.getElementById("sheet");

export function openSheet(title, body) {
  const node = sheet();
  document.getElementById("sheet-title").textContent = title;
  const container = document.getElementById("sheet-body");
  container.innerHTML = "";
  container.append(body);
  node.classList.add("open");
}

export function closeSheet() {
  sheet().classList.remove("open");
}

export function openOverlay(title, source, actions = []) {
  const overlay = document.getElementById("overlay");
  document.getElementById("overlay-title").textContent = title;
  const image = document.getElementById("overlay-image");
  image.src = source;
  const foot = document.getElementById("overlay-actions");
  foot.innerHTML = "";
  actions.forEach((action) => foot.append(action));
  overlay.classList.add("open");
}

export function closeOverlay() {
  const overlay = document.getElementById("overlay");
  overlay.classList.remove("open");
  document.getElementById("overlay-image").src = "";
  document.getElementById("overlay-actions").innerHTML = "";
}

export function field(label, input, hint) {
  return el("div", { class: "field" }, [el("label", { text: label }), input, hint ? el("div", { class: "hint", text: hint }) : null]);
}

export function select(options, value) {
  const node = el("select");
  options.forEach((option) => {
    const item = el("option", { value: option.value, text: option.label });
    if (String(option.value) === String(value)) item.selected = true;
    node.append(item);
  });
  return node;
}

export function input(type, value, attributes = {}) {
  return el("input", Object.assign({ type, value: value === null || value === undefined ? "" : value }, attributes));
}

export function confirmAction(message) {
  return window.confirm(message);
}
