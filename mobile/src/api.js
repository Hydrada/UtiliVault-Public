// UtiliVault Field — API client.
// Talks to api_server.py on the UtiliVault PC (same Wi-Fi / LAN, or a
// port-forwarded address). Server URL + optional API key live in Settings.

import AsyncStorage from "@react-native-async-storage/async-storage";
import { DEFAULT_API_KEY, DEFAULT_SERVER_URL } from "./defaults";

const SETTINGS_KEY = "utilivault.settings";

let settings = { serverUrl: DEFAULT_SERVER_URL, apiKey: DEFAULT_API_KEY };

export async function loadSettings() {
  try {
    const raw = await AsyncStorage.getItem(SETTINGS_KEY);
    // A saved setting always wins over the build default; the build default
    // only fills in on first launch (nothing saved yet).
    if (raw) settings = { ...settings, ...JSON.parse(raw) };
  } catch (e) {
    console.warn("settings load failed", e);
  }
  return { ...settings };
}

export async function saveSettings(next) {
  settings = { ...settings, ...next };
  await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  return { ...settings };
}

export function getSettings() {
  return { ...settings };
}

function base() {
  let url = (settings.serverUrl || "").trim().replace(/\/+$/, "");
  if (url && !/^https?:\/\//i.test(url)) url = "http://" + url;
  return url;
}

export function headers(extra = {}) {
  const h = { ...extra };
  if (settings.apiKey) h["X-Api-Key"] = settings.apiKey;
  return h;
}

export function pageUrl(path) {
  // Absolute URL for a page-preview PNG, cache-busted per call site.
  return base() + path;
}

async function req(path, options = {}) {
  const url = base() + path;
  if (!base()) throw new Error("Set the server address in Settings first.");
  const res = await fetch(url, { ...options, headers: headers(options.headers) });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error */
  }
  if (!res.ok) {
    throw new Error((body && body.error) || `Server error ${res.status}`);
  }
  return body;
}

export const health = () => req("/api/health");
export const listCards = () => req("/api/cards");
export const getCard = (b) => req(`/api/cards/${encodeURIComponent(b)}`);

// Submit (create or regenerate) a card. fields: plain object of card fields.
// photoUri: local file uri from camera/library, or null to keep/skip.
// previousBase: set when editing, so a rename cleans up the old card.
export async function submitCard(fields, photoUri, previousBase) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => {
    if (v !== undefined && v !== null && String(v).trim() !== "") {
      fd.append(k, String(v).trim());
    }
  });
  if (previousBase) fd.append("previous_base", previousBase);
  if (photoUri) {
    const name = photoUri.split("/").pop() || "photo.jpg";
    const ext = (name.split(".").pop() || "jpg").toLowerCase();
    fd.append("photo", {
      uri: photoUri,
      name,
      type: ext === "png" ? "image/png" : "image/jpeg",
    });
  }
  return req("/api/cards", { method: "POST", body: fd });
}
