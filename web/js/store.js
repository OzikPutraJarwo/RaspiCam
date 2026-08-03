import { api } from "./api.js";
import { emit } from "./ui.js";

export const store = {
  cameras: [],
  storageReady: false,
  system: null,
  tunnel: null,
};

export async function loadCameras() {
  const data = await api.get("/api/cameras");
  store.cameras = data.cameras;
  store.storageReady = data.storage;
  emit("cameras", store.cameras);
  return store.cameras;
}

export function camera(id) {
  return store.cameras.find((item) => item.id === id) || null;
}
