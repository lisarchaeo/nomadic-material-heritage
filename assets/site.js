/* Nomadic Material Heritage — collection browser.
   Reads data/items.json (written by scripts/build_data.py) and shows the grid,
   the filters and the item view. Filters and the open item live in the web
   address, so any view can be shared. */

const PER_PAGE = 24;
const FEATURED_UID = "2021SG06-C04-1293";   // Unique ID of the home page photo

const CATEGORY_COLOURS = {
  "Syrmaq": ["#B8321F", "#fff"],
  "Tus Kiiz": ["#1E6B66", "#fff"],
  "Terme": ["#C98A12", "#1F1D1A"],
  "Skins & Leather": ["#1E2A4A", "#fff"],
  "Spindles": ["#4A7A2E", "#fff"],
  "Felt & Fibre": ["#5F7A6B", "#fff"],
  "Shi": ["#2F6D8F", "#fff"],
  "Craft Videos": ["#6A4A7A", "#fff"],
  "Interviews": ["#8A3B5C", "#fff"],
  "Behind The Scenes": ["#7D6340", "#fff"],
};

// buttons that are not a craft: shown in a lighter style
const UTILITY_BUTTONS = ["Craft Videos", "Interviews", "Behind The Scenes"];

const STRINGS = {
  en: {
    all: "All", place: "All places", household: "All households",
    photographer: "All photographers", maker: "Maker", place_row: "Place",
    household_row: "Household", group: "Cultural group", date: "Date taken",
    unavailable: "Unavailable", photo_by: "Photo", video_by: "Film",
    contributors: "Contributors",
    licence: "Licence", showing: "Showing {n} items", showing_one: "Showing 1 item",
    of: "{n} of {m} in this view", copied: "Link copied",
    mt_notice: "Some of this page is translated automatically and is still being checked. " +
      "Corrections are welcome.", no_preview:
      "This item has no preview in the repository. Open it there to see the original.",
    page: "Page {n}", next_page: "Next →", prev_page: "← Previous",
    not_ready: "This language is not ready yet, so the page is still in English. " +
      "Item titles appear in the language the repository recorded them in.",
  },
  kk: {}, // filled in when the Kazakh translations are ready
  mn: {},
};

const state = {
  lang: "en",
  items: [],
  categories: [],
  filtered: [],
  crafts: new Set(),
  place: "", household: "", photographer: "",
  page: 1,
  open: null,
};

const $ = (id) => document.getElementById(id);
const t = (key, vars) => {
  let s = (STRINGS[state.lang] && STRINGS[state.lang][key]) || STRINGS.en[key] || key;
  if (vars) for (const k in vars) s = s.replace("{" + k + "}", vars[k]);
  return s;
};
const text = (item, field) => {
  const v = item[field] || {};
  return v[state.lang] || v.en || "";
};

/* ---------------------------------------------------------------- start */
async function start() {
  try {
    const res = await fetch("data/items.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    state.items = data.items || [];
    state.categories = data.categories || Object.keys(CATEGORY_COLOURS);
  } catch (e) {
    $("grid").innerHTML =
      '<p class="empty">The collection could not be loaded just now. Please try again in a moment.</p>';
    return;
  }
  buildChips();
  buildSelects();
  readAddress();
  document.querySelectorAll("[data-lang]").forEach((b) =>
    b.addEventListener("click", () => setLanguage(b.dataset.lang)));
  $("reset").addEventListener("click", clearFilters);
  $("close").addEventListener("click", closeItem);
  $("prev").addEventListener("click", () => step(-1));
  $("next").addEventListener("click", () => step(1));
  document.querySelectorAll("[data-nav]").forEach((b) =>
    b.addEventListener("click", () => step(b.dataset.nav === "next" ? 1 : -1)));
  $("copy").addEventListener("click", copyLink);
  $("overlay").addEventListener("click", (e) => { if (e.target === $("overlay")) closeItem(); });
  document.addEventListener("keydown", onKey);
  window.addEventListener("popstate", () => { readAddress(); apply(false); });
  apply(false);
}

/* ---------------------------------------------------------------- filters */
function buildChips() {
  const wrap = $("chips");
  wrap.innerHTML = "";
  wrap.appendChild(chip(t("all"), "", null));
  state.categories.forEach((c) => wrap.appendChild(chip(c, c, CATEGORY_COLOURS[c])));
}

function chip(label, value, colours) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "chip" + (!value ? " util" : UTILITY_BUTTONS.includes(value) ? " kind" : "");
  b.textContent = label;
  b.dataset.craft = value;
  if (colours) {
    b.style.setProperty("--chip", colours[0]);
    b.style.setProperty("--chip-ink", colours[1]);
  }
  b.addEventListener("click", () => {
    if (!value) state.crafts.clear();
    else if (state.crafts.has(value)) state.crafts.delete(value);
    else state.crafts.add(value);
    state.page = 1;
    apply(true);
  });
  return b;
}

function buildSelects() {
  const places = new Map(), households = new Set(), photographers = new Set();
  state.items.forEach((i) => {
    if (i.place && i.place.key) places.set(i.place.key, i.place);
    if (i.household) households.add(i.household);
    if (i.credit) photographers.add(i.credit);
  });
  fill($("place"), t("place"), [...places.values()]
    .sort((a, b) => a.en.localeCompare(b.en))
    .map((p) => [p.key, placeLabel(p)]));
  fill($("household"), t("household"), [...households].sort().map((h) => [h, h]));
  fill($("photographer"), t("photographer"), [...photographers].sort().map((p) => [p, p]));
  [["place", "place"], ["household", "household"], ["photographer", "photographer"]]
    .forEach(([id, key]) => $(id).addEventListener("change", () => {
      state[key] = $(id).value; state.page = 1; apply(true);
    }));
}

function fill(select, blank, pairs) {
  const current = select.value;
  select.innerHTML = "";
  const o = document.createElement("option");
  o.value = ""; o.textContent = blank;
  select.appendChild(o);
  pairs.forEach(([value, label]) => {
    const opt = document.createElement("option");
    opt.value = value; opt.textContent = label;
    select.appendChild(opt);
  });
  select.value = current;
}

function placeLabel(p) {
  const name = (state.lang !== "en" && p[state.lang]) || p.en;
  return p.province ? `${name}, ${p.province}` : name;
}

function clearFilters() {
  state.crafts.clear();
  state.place = state.household = state.photographer = "";
  $("place").value = $("household").value = $("photographer").value = "";
  state.page = 1;
  apply(true);
}

/* ---------------------------------------------------------------- address */
function readAddress() {
  const p = new URLSearchParams(location.search);
  state.crafts = new Set((p.get("craft") || "").split(",").filter(Boolean));
  state.place = p.get("place") || "";
  state.household = p.get("household") || "";
  state.photographer = p.get("photographer") || "";
  state.page = Math.max(1, parseInt(p.get("page") || "1", 10) || 1);
  state.open = p.get("item") || null;
  const lang = p.get("lang");
  if (lang && STRINGS[lang]) state.lang = lang;
  $("place").value = state.place;
  $("household").value = state.household;
  $("photographer").value = state.photographer;
}

function writeAddress(push) {
  const p = new URLSearchParams();
  if (state.crafts.size) p.set("craft", [...state.crafts].join(","));
  if (state.place) p.set("place", state.place);
  if (state.household) p.set("household", state.household);
  if (state.photographer) p.set("photographer", state.photographer);
  if (state.page > 1) p.set("page", state.page);
  if (state.open) p.set("item", state.open);
  if (state.lang !== "en") p.set("lang", state.lang);
  const url = location.pathname + (p.toString() ? "?" + p : "");
  if (push) history.pushState({}, "", url);
  else history.replaceState({}, "", url);
}

/* ---------------------------------------------------------------- render */
function apply(push) {
  state.filtered = state.items.filter((i) =>
    (!state.crafts.size || i.categories.some((c) => state.crafts.has(c))) &&
    (!state.place || (i.place && i.place.key === state.place)) &&
    (!state.household || i.household === state.household) &&
    (!state.photographer || i.credit === state.photographer));

  const pages = Math.max(1, Math.ceil(state.filtered.length / PER_PAGE));
  if (state.page > pages) state.page = pages;

  document.querySelectorAll(".chip").forEach((b) => {
    const v = b.dataset.craft;
    b.setAttribute("aria-pressed", v ? state.crafts.has(v) : state.crafts.size === 0);
  });

  const n = state.filtered.length;
  $("count").textContent = n === 1 ? t("showing_one") : t("showing", { n });
  $("hero").hidden = state.crafts.size > 0 || !!state.place || !!state.household ||
    !!state.photographer || state.page > 1;

  drawGrid();
  drawPager(pages);
  writeAddress(push);
  if (state.open) showItem(state.open, false); else closeItem(false);
}

function drawGrid() {
  const grid = $("grid");
  grid.innerHTML = "";
  const slice = state.filtered.slice((state.page - 1) * PER_PAGE, state.page * PER_PAGE);
  $("empty").hidden = slice.length > 0;

  slice.forEach((item) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "card";
    const frame = document.createElement("div");
    frame.className = "frame";
    if (item.grid) {
      const img = document.createElement("img");
      img.src = item.grid;
      img.alt = text(item, "title");
      img.loading = "lazy";
      img.decoding = "async";
      frame.appendChild(img);
    } else {
      const p = document.createElement("p");
      p.className = "missing";
      p.textContent = text(item, "title");
      frame.appendChild(p);
    }
    if (item.type === "video") {
      const badge = document.createElement("span");
      badge.className = "play";
      badge.innerHTML = '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9-5.5z" fill="#171A2B"/></svg>';
      frame.appendChild(badge);
    }
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = text(item, "title");
    const meta = document.createElement("span");
    meta.className = "meta";
    const by = item.type === "video" ? t("video_by") : t("photo_by");
    meta.textContent = [item.place && item.place.en, item.categories[0], item.credit && `${by}: ${item.credit}`]
      .filter(Boolean).join(" · ");
    card.append(frame, title, meta);
    card.addEventListener("click", () => showItem(item.uid, true));
    grid.appendChild(card);
  });

  if (!$("hero").hidden) {
    const featured = state.items.find((i) => i.uid === FEATURED_UID) ||
      state.items.find((i) => i.type === "photo" && i.grid);
    if (featured) {
      const img = $("hero-img");
      img.src = featured.grid || featured.preview;
      // phones load the small grid image; wide screens the large preview
      if (featured.preview && featured.grid) {
        img.srcset = `${featured.grid} 700w, ${featured.preview} 2000w`;
        img.sizes = "100vw";
      }
      img.alt = text(featured, "title");
      const credit = $("hero-credit");
      if (credit) {
        const by = featured.type === "video" ? t("video_by") : t("photo_by");
        credit.textContent = featured.credit
          ? `${text(featured, "title")} · ${by}: ${featured.credit}` : "";
      }
    }
  }
}

function drawPager(pages) {
  const pager = $("pager");
  pager.innerHTML = "";
  if (pages < 2) return;
  const go = (n) => { state.page = n; apply(true); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const button = (label, n, current) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    if (current) b.setAttribute("aria-current", "page");
    b.addEventListener("click", () => go(n));
    return b;
  };
  const dots = () => {
    const s = document.createElement("span");
    s.className = "dots"; s.textContent = "…";
    return s;
  };
  if (state.page > 1) pager.appendChild(button(t("prev_page"), state.page - 1));
  const near = new Set([1, pages, state.page, state.page - 1, state.page + 1]);
  let last = 0;
  [...near].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b).forEach((n) => {
    if (n - last > 1) pager.appendChild(dots());
    pager.appendChild(button(String(n), n, n === state.page));
    last = n;
  });
  if (state.page < pages) pager.appendChild(button(t("next_page"), state.page + 1));
}

/* ---------------------------------------------------------------- item view */
function showItem(uid, push) {
  const index = state.filtered.findIndex((i) => i.uid === uid);
  const item = index >= 0 ? state.filtered[index] : state.items.find((i) => i.uid === uid);
  if (!item) return;
  state.open = uid;

  const stage = $("stage");
  [...stage.querySelectorAll("img, video, iframe, .fallback")].forEach((el) => el.remove());
  if (item.type === "video" && item.preview) {
    const v = document.createElement("video");
    v.src = item.preview;
    v.controls = true;
    v.playsInline = true;
    if (item.poster) v.poster = item.poster;
    stage.appendChild(v);
  } else if (item.type === "photo" && item.preview) {
    const img = document.createElement("img");
    img.src = item.preview;
    img.alt = text(item, "title");
    stage.appendChild(img);
  } else if (item.embed) {
    const frame = document.createElement("iframe");
    frame.src = item.embed;
    frame.title = text(item, "title");
    frame.allowFullscreen = true;
    stage.appendChild(frame);
  } else {
    const p = document.createElement("p");
    p.className = "fallback";
    p.textContent = t("no_preview");
    stage.appendChild(p);
  }

  const cat = item.categories[0];
  const tag = $("item-cat");
  tag.textContent = cat || "";
  tag.hidden = !cat;
  if (cat && CATEGORY_COLOURS[cat]) {
    tag.style.background = CATEGORY_COLOURS[cat][0];
    tag.style.color = CATEGORY_COLOURS[cat][1];
  }

  $("item-title").textContent = text(item, "title");
  const desc = text(item, "description");
  $("item-desc").textContent = desc;
  $("item-desc").hidden = !desc;

  const rows = [
    [t("maker"), item.maker || t("unavailable")],
    [t("contributors"), item.contributors],
    [t("place_row"), item.place && item.place.en ? placeLabel(item.place) : ""],
    [t("household_row"), item.household],
    [t("group"), item.cultural_group],
    [t("date"), item.date],
  ].filter(([, v]) => v);
  $("item-rows").innerHTML = rows.map(([k, v]) =>
    `<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join("");

  const by = item.type === "video" ? t("video_by") : t("photo_by");
  $("item-credit").innerHTML =
    `${escape(by)}: <strong>${escape(item.credit || "")}</strong><br>${escape(t("licence"))}: ` +
    `<a href="${escape(item.licence.url || "#")}" target="_blank" rel="noopener">${escape(item.licence.name || "")}</a>` +
    " · EMKP, British Museum";

  $("item-doi").href = item.doi_url || item.repository_url || "#";
  $("counter").textContent = index >= 0
    ? t("of", { n: index + 1, m: state.filtered.length }) : "";
  $("prev").hidden = $("next").hidden = index < 0;

  $("overlay").hidden = false;
  document.body.style.overflow = "hidden";
  $("close").focus();
  writeAddress(push);
}

function step(delta) {
  const index = state.filtered.findIndex((i) => i.uid === state.open);
  if (index < 0) return;
  const next = (index + delta + state.filtered.length) % state.filtered.length;
  showItem(state.filtered[next].uid, false);
}

function closeItem(push) {
  const overlay = $("overlay");
  if (overlay.hidden) return;
  overlay.hidden = true;
  [...$("stage").querySelectorAll("img, video, iframe, .fallback")].forEach((el) => el.remove());
  document.body.style.overflow = "";
  if (push !== false) { state.open = null; writeAddress(true); }
}

function onKey(e) {
  if ($("overlay").hidden) return;
  if (e.key === "Escape") closeItem();
  if (e.key === "ArrowLeft") step(-1);
  if (e.key === "ArrowRight") step(1);
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(location.href);
    $("copy").textContent = t("copied");
    setTimeout(() => { $("copy").textContent = t("copy_link") || "Copy link to this item"; }, 2000);
  } catch (e) { /* some browsers refuse; the address bar still holds the link */ }
}

/* ---------------------------------------------------------------- language */
function setLanguage(lang) {
  state.lang = lang;
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-lang]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  document.querySelectorAll("[data-t]").forEach((el) => {
    const key = el.dataset.t;
    const s = STRINGS[lang] && STRINGS[lang][key];
    if (s) el.textContent = s;
  });
  const notice = $("translation-notice");
  if (notice) {
    const translated = Object.keys(STRINGS[lang] || {}).length > 0;
    notice.hidden = lang === "en";
    notice.textContent = translated ? t("mt_notice") : STRINGS.en.not_ready;
  }
  buildChips();
  buildSelects();
  apply(true);
}

function escape(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

start();
