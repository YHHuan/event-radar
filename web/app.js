"use strict";

const STORAGE = {
  saved: "ake-event-radar:saved:v2",
  savedV1: "ake-event-radar:saved:v1",
  hidden: "ake-event-radar:hidden:v1",
};
const PAGE_SIZE = 18;
const MAX_SAVED = 200;
const LENS_ORDER = ["live_music", "theatre_dance", "film", "market_festival", "exhibition", "nature", "urban", "talks"];

const initialSaved = readSavedRecords();

const state = {
  events: [],
  today: "",
  generatedAt: "",
  view: "for-you",
  when: "90",
  city: "all",
  period: "all",
  lens: "all",
  query: "",
  visible: PAGE_SIZE,
  saved: initialSaved.items,
  legacySaved: initialSaved.exists ? new Set() : readSet(STORAGE.savedV1),
  pendingSavedIds: [],
  hidden: readSet(STORAGE.hidden),
};

const el = (id) => document.getElementById(id);
const list = el("event-list");
let statusTimer = null;

function readSavedRecords() {
  try {
    const raw = localStorage.getItem(STORAGE.saved);
    if (raw === null) return { exists: false, items: new Map() };
    const value = JSON.parse(raw);
    const items = Array.isArray(value?.items) ? value.items : [];
    return {
      exists: true,
      items: new Map(items.filter((item) => item && typeof item.id === "string").map((item) => [item.id, item])),
    };
  } catch {
    return { exists: false, items: new Map() };
  }
}

function readSet(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return new Set(Array.isArray(value) ? value : []);
  } catch {
    return new Set();
  }
}

function writeSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify([...value]));
    return true;
  } catch {
    return false;
  }
}

function writeSaved(value) {
  while (value.size > MAX_SAVED) value.delete(value.keys().next().value);
  const items = [...value.values()];
  try {
    localStorage.setItem(STORAGE.saved, JSON.stringify({
      schema: "ake-event-radar-saved/v2",
      items,
    }));
  } catch {
    return false;
  }
  // Keep the old ID-only representation as a rollback bridge.
  writeSet(STORAGE.savedV1, new Set(items.map((item) => item.id)));
  return true;
}

function announce(message, kind = "ok") {
  const status = el("save-status");
  if (!status) return;
  clearTimeout(statusTimer);
  status.textContent = message;
  status.dataset.kind = kind;
  status.hidden = false;
  statusTimer = setTimeout(() => { status.hidden = true; }, 4200);
}

function favoriteSnapshot(event, savedAt = new Date().toISOString()) {
  return {
    id: event.id,
    title: event.title || "已收藏活動",
    organizer: event.organizer || "",
    category: event.category || "活動",
    city: event.city || "地點待確認",
    source: event.source || "公開來源",
    url: event.url || "",
    image: event.image || "",
    firstStart: event.firstStart || "",
    lastStart: event.lastStart || event.firstStart || "",
    venue: event.venue || "",
    price: event.price || "",
    performances: Array.isArray(event.performances) ? event.performances.slice(0, 1) : [],
    performanceCount: event.performanceCount || 1,
    score: event.score || 0,
    scoreMode: event.scoreMode || "saved",
    tier: event.tier || "explore",
    reason: event.reason || "先前收藏",
    facets: Array.isArray(event.facets) ? event.facets.slice(0, 4) : [],
    lenses: Array.isArray(event.lenses) ? event.lenses.slice(0, 3) : [],
    confidence: event.confidence || "",
    tags: Array.isArray(event.tags) ? event.tags.slice(0, 8) : [],
    savedAt,
  };
}

function canonicalUrl(value) {
  try {
    const url = new URL(value);
    ["fbclid", "gclid", "utm_campaign", "utm_content", "utm_id", "utm_medium", "utm_source", "utm_term"]
      .forEach((key) => url.searchParams.delete(key));
    url.hash = "";
    url.pathname = url.pathname.replace(/\/$/, "") || "/";
    return url.toString();
  } catch {
    return "";
  }
}

function identityText(value) {
  return String(value || "").normalize("NFKC").replace(/臺/g, "台").toLocaleLowerCase("zh-Hant")
    .replace(/[\s\-–—_·,，。、!！?？:：()（）【】\[\]「」『』~～"'’“”/／|｜.]+/g, "");
}

function dayDistance(left, right) {
  const a = localDate(left);
  const b = localDate(right);
  return a && b ? Math.abs(Math.round((a - b) / 86400000)) : 9999;
}

function findCurrentFavorite(record, events) {
  const exact = events.find((event) => event.id === record.id);
  if (exact) return exact;
  const savedUrl = canonicalUrl(record.url);
  if (savedUrl) {
    const byUrl = events.find((event) => canonicalUrl(event.url) === savedUrl);
    if (byUrl) return byUrl;
  }
  const title = identityText(record.title);
  const city = identityText(record.city);
  if (!title) return null;
  return events.find((event) => identityText(event.title) === title
    && identityText(event.city) === city
    && dayDistance(event.firstStart, record.firstStart) <= 120) || null;
}

function reconcileSaved(events) {
  const reconciled = new Map();
  state.saved.forEach((record) => {
    const current = findCurrentFavorite(record, events);
    if (current) {
      reconciled.set(current.id, favoriteSnapshot(current, record.savedAt));
    } else {
      reconciled.set(record.id, record);
    }
  });
  state.legacySaved.forEach((id) => {
    const current = events.find((event) => event.id === id);
    if (current) reconciled.set(current.id, favoriteSnapshot(current));
  });
  return reconciled;
}

function importSharedFavorites(events) {
  if (!state.pendingSavedIds.length) return 0;
  const next = new Map(state.saved);
  let imported = 0;
  state.pendingSavedIds.forEach((id) => {
    const current = events.find((event) => event.id === id);
    if (current && !next.has(current.id)) {
      next.set(current.id, favoriteSnapshot(current));
      imported += 1;
    }
  });
  if (!imported) return 0;
  if (!writeSaved(next)) {
    announce("收藏沒有匯入，請確認瀏覽器允許網站儲存", "error");
    return 0;
  }
  state.saved = next;
  return imported;
}

function icon(name) {
  const image = document.createElement("img");
  image.src = `icons/${name}.svg`;
  image.alt = "";
  image.setAttribute("aria-hidden", "true");
  return image;
}

function iconButton(name, label, action, pressed = null) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button";
  button.dataset.action = action;
  button.setAttribute("aria-label", label);
  button.title = label;
  if (pressed !== null) button.setAttribute("aria-pressed", String(pressed));
  button.append(icon(name));
  return button;
}

function localDate(value) {
  if (!value) return null;
  const parts = value.slice(0, 10).split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
  return new Date(parts[0], parts[1] - 1, parts[2]);
}

function daysFromToday(value) {
  const start = localDate(value);
  const today = localDate(state.today);
  return start && today ? Math.round((start - today) / 86400000) : 9999;
}

function formatDate(value, withTime = true) {
  const d = localDate(value);
  if (!d) return "日期待確認";
  const datePart = new Intl.DateTimeFormat("zh-TW", {
    month: "numeric", day: "numeric", weekday: "short",
  }).format(d);
  const time = value.slice(11, 16);
  return withTime && time && time !== "00:00" ? `${datePart} ${time}` : datePart;
}

function weekendBounds() {
  const today = localDate(state.today);
  if (!today) return [0, 0];
  const day = today.getDay();
  if (day === 5) return [0, 2];
  if (day === 6) return [0, 1];
  if (day === 0) return [0, 0];
  return [5 - day, 7 - day];
}

function queryBlob(event) {
  return [
    event.title, event.organizer, event.category, event.city, event.venue, event.source,
    event.reason, ...(event.tags || []), ...(event.facets || []).map((item) => item.label),
    ...(event.lenses || []).map((item) => item.label),
  ].join(" ").toLocaleLowerCase("zh-Hant");
}

function matchesCity(event) {
  if (state.city === "all") return true;
  if (state.city === "north") return ["台北市", "新北市"].includes(event.city);
  if (state.city === "nearby") return ["桃園市", "基隆市"].includes(event.city);
  return event.city === state.city;
}

function matchesPeriod(event) {
  if (state.period === "all") return true;
  const time = String(event.firstStart || "").slice(11, 16);
  if (!/^\d{2}:\d{2}$/.test(time) || time === "00:00") return false;
  const hour = Number(time.slice(0, 2));
  return state.period === "day" ? hour < 18 : hour >= 18;
}

function filteredEvents() {
  const query = state.query.trim().toLocaleLowerCase("zh-Hant");
  const [weekendStart, weekendEnd] = weekendBounds();
  const candidates = state.view === "saved"
    ? [...new Map([
      ...[...state.saved.values()].filter((event) => event.title && event.url).map((event) => [event.id, event]),
      ...state.events.map((event) => [event.id, event]),
    ]).values()]
    : state.events;
  const result = candidates.filter((event) => {
    if (state.hidden.has(event.id)) return false;
    if (state.view === "saved" && !state.saved.has(event.id)) return false;
    if (state.view === "for-you" && !["pick", "strong"].includes(event.tier)) return false;
    const days = daysFromToday(event.firstStart);
    if (state.view === "weekend" && (days < weekendStart || days > weekendEnd)) return false;
    if (state.when !== "all" && days > Number(state.when)) return false;
    if (!matchesCity(event)) return false;
    if (!matchesPeriod(event)) return false;
    if (state.lens !== "all" && !(event.lenses || []).some((lens) => lens.key === state.lens)) return false;
    return !query || queryBlob(event).includes(query);
  });
  if (["all", "saved", "weekend"].includes(state.view)) {
    result.sort((a, b) => a.firstStart.localeCompare(b.firstStart) || b.score - a.score);
  } else {
    const tier = { pick: 0, strong: 1, explore: 2 };
    result.sort((a, b) => (tier[a.tier] - tier[b.tier]) || b.score - a.score || a.firstStart.localeCompare(b.firstStart));
  }
  return result;
}

function makeCard(event) {
  const card = document.createElement("article");
  card.className = "event-card";
  card.dataset.id = event.id;
  card.dataset.start = event.firstStart || "";

  const poster = document.createElement("a");
  poster.className = "event-card__poster";
  poster.href = event.url;
  poster.target = "_blank";
  poster.rel = "noopener noreferrer";
  poster.setAttribute("aria-label", `查看 ${event.title} 詳情`);
  const placeholder = document.createElement("span");
  placeholder.className = "event-card__placeholder";
  placeholder.textContent = event.lenses?.[0]?.label || event.category || "活動";
  poster.append(placeholder);
  if (event.image) {
    const image = document.createElement("img");
    image.src = event.image;
    image.alt = `${event.title} 活動主視覺`;
    image.loading = "lazy";
    image.decoding = "async";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("load", () => { placeholder.hidden = true; });
    image.addEventListener("error", () => { image.remove(); placeholder.hidden = false; });
    poster.append(image);
  }
  card.append(poster);

  const body = document.createElement("div");
  body.className = "event-card__body";
  const topline = document.createElement("div");
  topline.className = "event-card__topline";
  const date = document.createElement("span");
  date.className = "event-card__date";
  date.textContent = formatDate(event.firstStart);
  topline.append(date);
  if (event.tier === "pick") {
    const tier = document.createElement("span");
    tier.className = "event-card__tier";
    tier.textContent = "首選";
    topline.append(tier);
  }
  body.append(topline);

  const title = document.createElement("h3");
  const titleLink = document.createElement("a");
  titleLink.href = event.url;
  titleLink.target = "_blank";
  titleLink.rel = "noopener noreferrer";
  titleLink.textContent = event.title;
  title.append(titleLink);
  body.append(title);

  const venue = document.createElement("p");
  venue.className = "event-card__venue";
  venue.textContent = [event.city, event.venue].filter(Boolean).join(" · ");
  body.append(venue);

  const middle = document.createElement("div");
  const reason = document.createElement("p");
  reason.className = "event-card__reason";
  reason.textContent = event.reason;
  middle.append(reason);
  const tags = document.createElement("div");
  tags.className = "event-card__tags";
  [...(event.facets || []).slice(0, 2), ...(event.lenses || []).slice(0, 1)].forEach((item) => {
    const tag = document.createElement("span");
    tag.className = "event-card__tag";
    tag.textContent = item.label;
    tags.append(tag);
  });
  middle.append(tags);
  body.append(middle);

  const footer = document.createElement("div");
  footer.className = "event-card__footer";
  const source = document.createElement("span");
  source.className = "event-card__source";
  source.textContent = [event.source, event.price].filter(Boolean).join(" · ");
  footer.append(source);
  const actions = document.createElement("div");
  actions.className = "event-card__actions";
  actions.append(
    iconButton("heart", "收藏活動", "save", state.saved.has(event.id)),
    iconButton("calendar-plus", "加入行事曆", "calendar"),
    iconButton("eye-off", "隱藏活動", "hide"),
    iconButton("external-link", "開啟主辦頁面", "open"),
  );
  footer.append(actions);
  body.append(footer);
  card.append(body);
  return card;
}

function render() {
  const events = filteredEvents();
  const shown = events.slice(0, state.visible);
  list.replaceChildren(...shown.map(makeCard));
  el("result-count").textContent = `${events.length} 個結果`;
  el("empty").hidden = events.length !== 0;
  el("load-more").hidden = shown.length >= events.length;
  el("load-more").textContent = `再顯示 ${Math.min(PAGE_SIZE, events.length - shown.length)} 個`;
  el("clear-search").hidden = !state.query;
  updateControls();
  syncUrl();
}

function updateControls() {
  document.querySelectorAll("#views button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
  });
  document.querySelectorAll("#when-filters button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.value === state.when));
  });
  document.querySelectorAll("#city-filters button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.value === state.city));
  });
  document.querySelectorAll("#period-filters button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.value === state.period));
  });
  document.querySelectorAll("#lens-filters button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.value === state.lens));
  });
  const active = Number(state.when !== "90") + Number(state.city !== "all")
    + Number(state.period !== "all") + Number(state.lens !== "all");
  el("filter-count").hidden = active === 0;
  el("filter-count").textContent = String(active);
  el("restore-hidden").hidden = state.hidden.size === 0;
  el("saved-count").hidden = state.saved.size === 0;
  el("saved-count").textContent = String(state.saved.size);
  el("share-saved").hidden = state.saved.size === 0;
}

function syncUrl() {
  const params = new URLSearchParams();
  if (state.view !== "for-you") params.set("view", state.view);
  if (state.when !== "90") params.set("when", state.when);
  if (state.city !== "all") params.set("city", state.city);
  if (state.period !== "all") params.set("period", state.period);
  if (state.lens !== "all") params.set("lens", state.lens);
  if (state.query) params.set("q", state.query);
  const next = `${location.pathname}${params.size ? `?${params}` : ""}`;
  history.replaceState(null, "", next);
}

function loadUrlState() {
  const params = new URLSearchParams(location.search);
  const view = params.get("view");
  if (["for-you", "weekend", "all", "saved"].includes(view)) state.view = view;
  const when = params.get("when");
  if (["7", "30", "90", "all"].includes(when)) state.when = when;
  if (params.get("city")) state.city = params.get("city");
  const period = params.get("period");
  if (["day", "evening"].includes(period)) state.period = period;
  if (params.get("lens")) state.lens = params.get("lens");
  state.query = params.get("q") || "";
  state.pendingSavedIds = (params.get("favorites") || "").split(".")
    .filter((value) => /^[a-zA-Z0-9_-]{1,80}$/.test(value)).slice(0, MAX_SAVED);
  if (state.pendingSavedIds.length) {
    state.view = "saved";
    state.when = "all";
  }
  el("search").value = state.query;
}

async function shareSaved() {
  const ids = [...state.saved.keys()];
  if (!ids.length) return;
  const url = new URL(location.origin + location.pathname);
  url.searchParams.set("view", "saved");
  url.searchParams.set("when", "all");
  url.searchParams.set("favorites", ids.join("."));
  try {
    if (navigator.share) {
      await navigator.share({ title: "有空｜我的收藏", url: url.toString() });
      announce("收藏連結已分享");
    } else {
      await navigator.clipboard.writeText(url.toString());
      announce("收藏連結已複製");
    }
  } catch (error) {
    if (error?.name !== "AbortError") announce("無法分享收藏連結", "error");
  }
}

function buildLensFilters(events) {
  const labels = new Map();
  events.forEach((event) => (event.lenses || []).forEach((lens) => labels.set(lens.key, lens.label)));
  const buttons = [];
  const all = document.createElement("button");
  all.type = "button";
  all.dataset.value = "all";
  all.setAttribute("aria-pressed", "true");
  all.textContent = "全部";
  buttons.push(all);
  LENS_ORDER.filter((key) => labels.has(key)).forEach((key) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.value = key;
    button.setAttribute("aria-pressed", "false");
    button.textContent = labels.get(key);
    buttons.push(button);
  });
  el("lens-filters").replaceChildren(...buttons);
}

function resetFilters() {
  state.view = "for-you";
  state.when = "90";
  state.city = "all";
  state.period = "all";
  state.lens = "all";
  state.query = "";
  state.visible = PAGE_SIZE;
  el("search").value = "";
  render();
}

function downloadCalendar(event) {
  const start = event.firstStart.replace(/[-:]/g, "").replace("T", "T").slice(0, 15);
  const endRaw = event.performances?.[0]?.end || event.firstStart;
  const end = endRaw.replace(/[-:]/g, "").replace("T", "T").slice(0, 15);
  const escape = (value) => String(value || "").replace(/([,;\\])/g, "\\$1").replace(/\n/g, "\\n");
  const ics = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//A-Ke//Event Radar//ZH-TW",
    "BEGIN:VEVENT", `UID:${escape(event.id)}@ake-event-radar`,
    `DTSTART:${start}`, `DTEND:${end}`, `SUMMARY:${escape(event.title)}`,
    `LOCATION:${escape([event.city, event.venue].filter(Boolean).join(" "))}`,
    `DESCRIPTION:${escape(`${event.reason} ${event.url}`)}`, `URL:${event.url}`,
    "END:VEVENT", "END:VCALENDAR", "",
  ].join("\r\n");
  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${event.title.replace(/[\\/:*?"<>|]/g, "-").slice(0, 50)}.ics`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function bindEvents() {
  el("search").addEventListener("input", (event) => {
    state.query = event.target.value;
    state.visible = PAGE_SIZE;
    render();
  });
  el("clear-search").addEventListener("click", () => {
    state.query = "";
    el("search").value = "";
    el("search").focus();
    render();
  });
  el("views").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button) return;
    state.view = button.dataset.view;
    state.visible = PAGE_SIZE;
    render();
  });
  el("toggle-filters").addEventListener("click", () => {
    const open = el("filters").hidden;
    el("filters").hidden = !open;
    el("toggle-filters").setAttribute("aria-expanded", String(open));
  });
  [["when-filters", "when"], ["city-filters", "city"], ["period-filters", "period"], ["lens-filters", "lens"]].forEach(([id, key]) => {
    el(id).addEventListener("click", (event) => {
      const button = event.target.closest("button[data-value]");
      if (!button) return;
      state[key] = button.dataset.value;
      state.visible = PAGE_SIZE;
      render();
    });
  });
  el("reset-filters").addEventListener("click", resetFilters);
  el("empty-reset").addEventListener("click", resetFilters);
  el("restore-hidden").addEventListener("click", () => {
    const next = new Set();
    if (!writeSet(STORAGE.hidden, next)) {
      announce("瀏覽器未允許儲存變更", "error");
      return;
    }
    state.hidden = next;
    render();
  });
  el("share-saved").addEventListener("click", shareSaved);
  el("load-more").addEventListener("click", () => {
    state.visible += PAGE_SIZE;
    render();
  });
  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".event-card");
    const item = state.events.find((candidate) => candidate.id === card?.dataset.id)
      || state.saved.get(card?.dataset.id);
    if (!item) return;
    if (button.dataset.action === "save") {
      const next = new Map(state.saved);
      const removing = next.has(item.id);
      if (removing) next.delete(item.id);
      else {
        if (next.size >= MAX_SAVED) next.delete(next.keys().next().value);
        next.set(item.id, favoriteSnapshot(item));
      }
      if (!writeSaved(next)) {
        announce("收藏沒有寫入，請確認瀏覽器允許網站儲存", "error");
        return;
      }
      state.saved = next;
      announce(removing ? "已取消收藏" : "已收藏");
      render();
    } else if (button.dataset.action === "hide") {
      const next = new Set(state.hidden).add(item.id);
      if (!writeSet(STORAGE.hidden, next)) {
        announce("瀏覽器未允許儲存變更", "error");
        return;
      }
      state.hidden = next;
      render();
    } else if (button.dataset.action === "calendar") {
      downloadCalendar(item);
    } else if (button.dataset.action === "open") {
      window.open(item.url, "_blank", "noopener,noreferrer");
    }
  });
}

async function start() {
  loadUrlState();
  bindEvents();
  try {
    const response = await fetch("events.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.events = Array.isArray(data.events) ? data.events : [];
    state.today = data.today;
    state.generatedAt = data.generatedAt;
    const reconciled = reconcileSaved(state.events);
    if (writeSaved(reconciled)) {
      state.saved = reconciled;
      state.legacySaved.clear();
    }
    const imported = importSharedFavorites(state.events);
    buildLensFilters(state.events);
    const generated = new Date(data.generatedAt);
    el("freshness").textContent = `更新 ${new Intl.DateTimeFormat("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(generated)}`;
    el("pick-count").textContent = String(data.meta?.pickCount || 0);
    el("coverage").textContent = `${data.meta?.count || 0} 個候選 · ${Object.keys(data.meta?.sources || {}).length} 個來源`;
    render();
    if (imported) announce(`已匯入 ${imported} 個收藏`);
  } catch (error) {
    console.error(error);
    el("freshness").textContent = "資料暫時無法讀取";
    el("result-count").textContent = "載入失敗";
    el("empty").hidden = false;
  }
}

start();
