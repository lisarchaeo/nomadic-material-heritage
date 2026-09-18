#!/usr/bin/env python3
"""
Nomadic Material Heritage: data builder.

Reads the project's items from the Figshare API, applies the category
spreadsheet and corrections file, makes grid images and video stills,
and writes data/items.json for the website plus data/report.md.

Files Lisa edits (open in Excel, LibreOffice or Google Sheets, save as CSV UTF-8):
  data/categories.csv   one row per item: category, household, maker, reviewed
  data/corrections.csv  one row per fix: unique_id, field, value, note
  data/places.csv       one row per place spelling: how to display it

Files this script writes (do not edit by hand):
  data/items.json, data/report.md, data/cache.json, media/grid/*, media/stills/*
"""

import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape

from PIL import Image, ImageDraw

# ---------------------------------------------------------------- settings
PROJECT_ID = 274269
API = "https://api.figshare.com/v2"
PREVIEW_BASE = "https://drs.britishmuseum.org/ndownloader/files/{fid}/preview/{fid}/{name}"
EMBED_BASE = "https://widgets.figshare.com/articles/{id}/embed?show_title=1"
USER_AGENT = "NomadicMaterialHeritage-website/1.0 (GitHub Actions)"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
GRID_DIR = os.path.join(ROOT, "media", "grid")
STILL_DIR = os.path.join(ROOT, "media", "stills")

CATEGORIES_CSV = os.path.join(DATA, "categories.csv")
CORRECTIONS_CSV = os.path.join(DATA, "corrections.csv")
PLACES_CSV = os.path.join(DATA, "places.csv")
ITEMS_JSON = os.path.join(DATA, "items.json")
REPORT_MD = os.path.join(DATA, "report.md")
CACHE_JSON = os.path.join(DATA, "cache.json")

GRID_SIZE = 700          # square grid images, in pixels
STILL_MAX_WIDTH = 1280   # video poster images, never upscaled
JPEG_QUALITY = 80
DEFAULT_FRAME_TIME = 10  # seconds into a video for its still
REFRESH_DAYS = 28        # re-read each item's details this often
WORKERS = 4              # parallel downloads; kept low to be polite

# Display order matters: this is the order of the craft buttons.
CATEGORIES = [
    "Syrmaq", "Tus Kiiz", "Terme", "Skins & Leather", "Spindles",
    "Felt & Fibre", "Shi",
    "Craft Videos", "Interviews", "Behind The Scenes",
]

# Words that suggest a category, matched in lower-case titles and keywords.
CATEGORY_HINTS = {
    "Syrmaq": ["syrmaq", "syrmak", "sirmak", "shyrdak", "felt carpet", "сырмақ"],
    "Tus Kiiz": ["tus kiiz", "tus kigiz", "tuus kiiz", "tus kiz", "tuskiiz",
                 "wall hanging", "тұс кигіз", "тускиіз"],
    "Terme": ["terme", "терме"],
    "Skins & Leather": ["skin", "leather", "hide", "fur", "coat", "тері"],
    "Spindles": ["spindle", "ұршық"],
    "Felt & Fibre": ["felting", "felt making", "making felt", "felt blanket", "rolling felt",
                     "carding", "dye", "dyeing", "dyed", "spinning", "horsehair", "horse hair",
                     "киіз басу", "иіру"],
    "Shi": ["reed", "reed screen", "shi", "shym shi", "chiy", "tuyrlyk", "tuyrlyk bau",
            "tuurlyk", "шым ши"],
    "Behind The Scenes": ["work in progress", "behind the scenes", "collecting data",
                          "fieldwork", "field work", "documentation", "photographing",
                          "filming", "ger interior", "yurt interior", "interior of",
                          "animals", "livestock", "sheep", "goat", "camel"],
}

# Custom repository fields the script keeps.
KEEP_FIELDS = [
    "Unique ID", "Session", "Title alt", "Description alt", "Place",
    "Cultural group", "Date of creation", "Participants", "Item/object",
    "Techniques of production", "Materials", "Materials alt",
    "Cultural sensitivity",
]

# Fields the corrections file may change.
CORRECTABLE = {
    "title_en", "title_kk", "title_mn",
    "description_en", "description_kk", "description_mn",
    "credit", "maker", "contributors", "household", "place", "date",
    "cultural_group", "frame_time", "hide", "show_sensitive",
}

# old name -> current name, applied to categories.csv when it is read
RENAMED_CATEGORIES = {"tuyrlyk bau": "Shi"}

CATEGORY_COLUMNS = ["unique_id", "figshare_id", "type", "title", "keywords",
                    "participants_in_repository", "suggested_category",
                    "category", "household", "maker", "reviewed", "notes"]
CORRECTION_COLUMNS = ["unique_id", "field", "value", "note"]
PLACE_COLUMNS = ["place_in_repository", "display_en", "display_kk", "display_mn",
                 "province"]

log_lines = []


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- network
def http_get(url, binary=False, retries=3, byte_range=None):
    headers = {"User-Agent": USER_AGENT}
    if byte_range:
        headers["Range"] = byte_range
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                return body if binary else body.decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (404, 403, 410):
                raise
            wait = 5 * (attempt + 1)
        except Exception:
            wait = 5 * (attempt + 1)
        if attempt < retries - 1:
            time.sleep(wait)
    raise RuntimeError(f"Could not fetch {url}")


def fetch_project_list():
    items, page = [], 1
    while True:
        url = f"{API}/projects/{PROJECT_ID}/articles?page={page}&page_size=1000"
        batch = json.loads(http_get(url))
        items.extend(batch)
        log(f"  list page {page}: {len(batch)} items")
        if len(batch) < 1000:
            return items
        page += 1
        time.sleep(1)


def fetch_details(article_id):
    time.sleep(0.25)
    return json.loads(http_get(f"{API}/articles/{article_id}"))


# ---------------------------------------------------------------- helpers
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(iso):
    try:
        then = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).days
    except Exception:
        return 9999


def clean_html(text):
    text = re.sub(r"<br\s*/?>|</p>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def nice_name(name):
    name = (name or "").strip()
    if name and name.upper() == name:
        return " ".join(p.capitalize() for p in name.split())
    return name


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def parse_time(value):
    """'1:05', '65' or '0:01:05' -> seconds. Blank -> None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        parts = [float(p) for p in value.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def read_csv(path, columns):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in columns:
            r[c] = (r.get(c) or "").strip()
    return rows


def write_csv(path, columns, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def slim(detail):
    """Keep only what the site needs from a full Figshare record."""
    custom = {c["name"]: c.get("value") for c in detail.get("custom_fields", [])}
    files = [{"id": f["id"], "name": f.get("name", ""),
              "mimetype": f.get("mimetype", ""), "size": f.get("size", 0)}
             for f in detail.get("files", [])]
    return {
        "id": detail["id"],
        "title": detail.get("title", ""),
        "description": clean_html(detail.get("description", "")),
        "authors": [a.get("full_name", "") for a in detail.get("authors", [])],
        "keywords": detail.get("keywords") or detail.get("tags") or [],
        "type": detail.get("defined_type_name", ""),
        "doi": detail.get("doi", ""),
        "url": detail.get("url_public_html") or detail.get("figshare_url", ""),
        "license": detail.get("license") or {},
        "thumb": detail.get("thumb", ""),
        "files": files,
        "modified": detail.get("modified_date", ""),
        "custom": {k: (custom.get(k) or "") if not isinstance(custom.get(k), list)
                   else "; ".join(custom.get(k)) for k in KEEP_FIELDS},
    }


VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mts", ".mpg", ".mpeg", ".webm")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma")
IMAGE_EXT = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".dng", ".cr2", ".nef")


def media_kind(rec):
    """photo, video, audio, or None (not shown)."""
    if rec["type"] == "dataset":
        return None
    for f in rec["files"]:
        m = (f["mimetype"] or "").lower()
        name = (f["name"] or "").lower()
        if m.startswith("video/") or name.endswith(VIDEO_EXT):
            return "video"
        if m.startswith("audio/") or name.endswith(AUDIO_EXT):
            return "audio"
        if m.startswith("image/") or name.endswith(IMAGE_EXT):
            return "photo"
    if rec["type"] == "figure":
        return "photo"
    return None


def primary_file(rec, kind):
    prefix = {"photo": "image/", "video": "video/", "audio": "audio/"}[kind]
    exts = {"photo": IMAGE_EXT, "video": VIDEO_EXT, "audio": AUDIO_EXT}[kind]
    for f in rec["files"]:
        if (f["mimetype"] or "").lower().startswith(prefix) or (f["name"] or "").lower().endswith(exts):
            return f
    return rec["files"][0] if rec["files"] else None


def suggest_categories(rec, kind):
    title = norm(rec["title"])
    words = title + " | " + " | ".join(norm(k) for k in rec["keywords"])
    found = []
    if "interview" in words:
        found.append("Interviews")
    elif kind == "video":
        found.append("Craft Videos")
    for cat in CATEGORIES:
        if cat in found:
            continue
        for hint in CATEGORY_HINTS.get(cat, []):
            if re.search(r"(?<!\w)" + re.escape(hint) + r"s?(?!\w)", words):
                found.append(cat)
                break
    return [c for c in CATEGORIES if c in found]


def split_place(raw):
    """'Tsagaannuur Tosgon/Цагааннуур тосгон, Bayan Ölgii' -> parts."""
    raw = (raw or "").strip()
    if not raw:
        return "", "", ""
    main, province = raw, ""
    if ", " in raw:
        main, province = raw.rsplit(", ", 1)
    en, kk = main, ""
    if "/" in main:
        en, kk = main.split("/", 1)
    return en.strip(), kk.strip(), province.strip()


# ---------------------------------------------------------------- images
def square_crop(img, size):
    img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((size, size), Image.LANCZOS)


def save_jpeg(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)


def make_photo_grid(rec, f):
    url = PREVIEW_BASE.format(fid=f["id"], name="preview.jpg")
    data = http_get(url, binary=True)
    img = Image.open(io.BytesIO(data))
    save_jpeg(square_crop(img, GRID_SIZE), os.path.join(GRID_DIR, f"{rec['id']}.jpg"))
    return url


def make_video_images(rec, f, seconds):
    url = PREVIEW_BASE.format(fid=f["id"], name="video_preview.mp4")
    with tempfile.TemporaryDirectory() as tmp:
        frame = os.path.join(tmp, "frame.jpg")
        for t in ([seconds, 0] if seconds else [0]):
            cmd = ["ffmpeg", "-loglevel", "error", "-y"]
            if url.startswith("http"):
                cmd += ["-user_agent", USER_AGENT]
            cmd += ["-ss", str(t), "-i", url, "-frames:v", "1", "-q:v", "2", frame]
            subprocess.run(cmd, capture_output=True, timeout=180)
            if os.path.exists(frame) and os.path.getsize(frame) > 0:
                break
        if not os.path.exists(frame) or os.path.getsize(frame) == 0:
            raise RuntimeError("no frame")
        img = Image.open(frame).convert("RGB")
        save_jpeg(square_crop(img, GRID_SIZE), os.path.join(GRID_DIR, f"{rec['id']}.jpg"))
        if img.width > STILL_MAX_WIDTH:
            img = img.resize((STILL_MAX_WIDTH, round(img.height * STILL_MAX_WIDTH / img.width)),
                             Image.LANCZOS)
        save_jpeg(img, os.path.join(STILL_DIR, f"{rec['id']}.jpg"))
    return url


def make_audio_tile(rec):
    img = Image.new("RGB", (GRID_SIZE, GRID_SIZE), (138, 59, 92))
    d = ImageDraw.Draw(img)
    c, r = GRID_SIZE // 2, 90
    d.ellipse((c - r, c - r, c + r, c + r), fill=(247, 245, 240))
    d.polygon([(c - 30, c - 45), (c - 30, c + 45), (c + 45, c)], fill=(138, 59, 92))
    save_jpeg(img, os.path.join(GRID_DIR, f"{rec['id']}.jpg"))


# ---------------------------------------------------------------- main
def main():
    full_refresh = "--full" in sys.argv
    os.makedirs(DATA, exist_ok=True)
    cache = {}
    if os.path.exists(CACHE_JSON) and not full_refresh:
        with open(CACHE_JSON, encoding="utf-8") as f:
            cache = json.load(f)
    records = cache.setdefault("records", {})
    media_state = cache.setdefault("media", {})

    # 1. The project list
    log("Reading the project list")
    listing = fetch_project_list()
    ids = [str(a["id"]) for a in listing]
    log(f"  {len(ids)} items in the repository")

    # 2. Details for new or stale items
    todo = [i for i in ids if i not in records or age_days(records[i]["fetched"]) > REFRESH_DAYS]
    log(f"Reading details for {len(todo)} items")
    failed_details = []
    for n, i in enumerate(todo, 1):
        try:
            rec = slim(fetch_details(i))
            rec["fetched"] = now_iso()
            records[i] = rec
        except Exception as e:
            failed_details.append(i)
            log(f"  could not read item {i}: {e}")
        if n % 100 == 0:
            log(f"  {n}/{len(todo)}")
    for gone in [k for k in records if k not in ids]:
        del records[gone]

    # 3. Lisa's files
    corrections = {}
    for row in read_csv(CORRECTIONS_CSV, CORRECTION_COLUMNS):
        field = row["field"].lower()
        if row["unique_id"] and field:
            corrections.setdefault(row["unique_id"], {})[field] = row["value"]
    bad_fields = sorted({(u, f) for u, fs in corrections.items() for f in fs if f not in CORRECTABLE})

    places = {norm(r["place_in_repository"]): r for r in read_csv(PLACES_CSV, PLACE_COLUMNS)
              if r["place_in_repository"]}
    cat_rows = {r["unique_id"]: r for r in read_csv(CATEGORIES_CSV, CATEGORY_COLUMNS)
                if r["unique_id"]}

    # 4. Build items
    items, skipped, new_rows, sensitive, unknown_cats, jobs = [], {}, [], [], [], []
    unrecognised = []
    cat_lookup = {c.lower(): c for c in CATEGORIES}

    for i in ids:
        rec = records.get(i)
        if not rec:
            continue
        kind = media_kind(rec)
        if kind is None:
            skipped[rec["type"] or "unknown"] = skipped.get(rec["type"] or "unknown", 0) + 1
            if rec["type"] != "dataset":
                files = "; ".join(f"{f['name']} ({f['mimetype']})" for f in rec["files"]) or "no files"
                unrecognised.append((rec["custom"].get("Unique ID") or f"fs-{i}", rec["title"], files))
            continue
        cf = rec["custom"]
        uid = cf.get("Unique ID") or f"fs-{i}"
        fix = corrections.get(uid, {})
        if fix.get("hide", "").lower() in ("yes", "y", "true"):
            continue
        if cf.get("Cultural sensitivity") and fix.get("show_sensitive", "").lower() not in ("yes", "y", "true"):
            sensitive.append((uid, rec["title"], cf["Cultural sensitivity"]))
            continue

        # category spreadsheet row
        suggestion = suggest_categories(rec, kind)
        row = cat_rows.get(uid)
        info = {
            "unique_id": uid, "figshare_id": i, "type": kind, "title": rec["title"],
            "keywords": "; ".join(rec["keywords"]),
            "participants_in_repository": cf.get("Participants", ""),
            "suggested_category": "; ".join(suggestion),
        }
        if row is None:
            row = dict(info, category="; ".join(suggestion), household="", maker="",
                       reviewed="", notes="" if suggestion else "No suggestion: please choose")
            cat_rows[uid] = row
            new_rows.append(uid)
        else:
            row.update(info)
            # a row you have not filled in or reviewed picks up newer suggestions
            if not row["category"] and not row["reviewed"] and suggestion:
                row["category"] = "; ".join(suggestion)

        chosen = []
        for old_name, new_name in RENAMED_CATEGORIES.items():
            row["category"] = re.sub(r"(?i)(?<![\w])" + re.escape(old_name) + r"(?![\w])",
                                     new_name, row["category"])
        for c in re.split(r"[;,]", row["category"]):
            c = c.strip()
            if not c:
                continue
            key = RENAMED_CATEGORIES.get(c.lower(), c).lower()
            if key in cat_lookup:
                chosen.append(cat_lookup[key])
            else:
                unknown_cats.append((uid, c))
        chosen = [c for c in CATEGORIES if c in chosen]

        # place
        place_raw = fix.get("place") or cf.get("Place", "")
        en, kk, province = split_place(place_raw)
        prow = places.get(norm(en))
        if en and prow is None:
            prow = {"place_in_repository": en, "display_en": en, "display_kk": kk,
                    "display_mn": "", "province": province}
            places[norm(en)] = prow
        place = {
            "key": norm(prow["display_en"]) if prow else "",
            "en": prow["display_en"] if prow else "",
            "kk": (prow["display_kk"] or kk) if prow else "",
            "mn": prow["display_mn"] if prow else "",
            "province": (prow["province"] or province) if prow else "",
        }

        credit = fix.get("credit") or nice_name(rec["authors"][0] if rec["authors"] else "")
        f = primary_file(rec, kind)
        frame_time = parse_time(fix.get("frame_time"))
        if frame_time is None:
            frame_time = DEFAULT_FRAME_TIME

        item = {
            "id": int(i),
            "uid": uid,
            "type": kind,
            "title": {"en": fix.get("title_en") or rec["title"],
                      "kk": fix.get("title_kk") or cf.get("Title alt", ""),
                      "mn": fix.get("title_mn", "")},
            "description": {"en": fix.get("description_en") or rec["description"],
                            "kk": fix.get("description_kk") or clean_html(cf.get("Description alt", "")),
                            "mn": fix.get("description_mn", "")},
            "categories": chosen,
            "credit": credit,
            "maker": fix.get("maker") or row["maker"],
            "contributors": fix.get("contributors") or cf.get("Participants", ""),
            "household": fix.get("household") or row["household"],
            "place": place,
            "cultural_group": fix.get("cultural_group") or cf.get("Cultural group", ""),
            "date": fix.get("date") or cf.get("Date of creation", ""),
            "doi_url": f"https://doi.org/{rec['doi']}" if rec["doi"] else "",
            "repository_url": rec["url"],
            "licence": {"name": rec["license"].get("name", ""), "url": rec["license"].get("url", "")},
            "grid": f"media/grid/{i}.jpg",
            "poster": None,
            "preview": None,
            "embed": EMBED_BASE.format(id=i),
        }
        items.append(item)

        # media work needed?
        state = media_state.get(i, {})
        wanted = {"file": f["id"] if f else None, "frame": frame_time if kind == "video" else None}
        have_files = os.path.exists(os.path.join(ROOT, item["grid"])) and (
            kind != "video" or os.path.exists(os.path.join(STILL_DIR, f"{i}.jpg")))
        if state.get("file") == wanted["file"] and state.get("frame") == wanted["frame"] and have_files:
            item["preview"] = state.get("preview")
            if kind == "video" and state.get("preview"):
                item["poster"] = f"media/stills/{i}.jpg"
        else:
            jobs.append((item, rec, f, kind, frame_time, wanted))

    # 5. Make images
    log(f"Making images for {len(jobs)} items")
    broken = []

    def work(job):
        item, rec, f, kind, frame_time, wanted = job
        i = str(item["id"])
        try:
            if f is None:
                raise RuntimeError("no file")
            if kind == "photo":
                item["preview"] = make_photo_grid(rec, f)
            elif kind == "video":
                item["preview"] = make_video_images(rec, f, frame_time)
                item["poster"] = f"media/stills/{i}.jpg"
            else:
                make_audio_tile(rec)
                item["preview"] = None
            media_state[i] = dict(wanted, preview=item["preview"])
        except Exception as e:
            broken.append((item["uid"], item["title"]["en"], kind, str(e)[:80]))
            media_state.pop(i, None)
            item["preview"] = None
            # fall back to the small repository thumbnail for the grid
            try:
                if rec.get("thumb"):
                    img = Image.open(io.BytesIO(http_get(rec["thumb"], binary=True)))
                    save_jpeg(square_crop(img, GRID_SIZE), os.path.join(ROOT, item["grid"]))
                else:
                    item["grid"] = None
            except Exception:
                item["grid"] = None

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for _ in pool.map(work, jobs):
            done += 1
            if done % 50 == 0:
                log(f"  {done}/{len(jobs)}")

    # tidy images for items no longer shown
    shown = {str(it["id"]) for it in items}
    for folder in (GRID_DIR, STILL_DIR):
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                if name.split(".")[0] not in shown:
                    os.remove(os.path.join(folder, name))
    for k in [k for k in media_state if k not in shown]:
        del media_state[k]

    # 6. Write everything
    items.sort(key=lambda it: it["uid"])
    with open(ITEMS_JSON, "w", encoding="utf-8") as fh:
        json.dump({"generated": now_iso(), "count": len(items), "categories": CATEGORIES,
                   "items": items}, fh, ensure_ascii=False, indent=1)

    ordered_rows = sorted(cat_rows.values(), key=lambda r: r["unique_id"])
    write_csv(CATEGORIES_CSV, CATEGORY_COLUMNS, ordered_rows)
    if not os.path.exists(CORRECTIONS_CSV):
        write_csv(CORRECTIONS_CSV, CORRECTION_COLUMNS, [])
    write_csv(PLACES_CSV, PLACE_COLUMNS, sorted(places.values(), key=lambda r: norm(r["place_in_repository"])))

    cache["updated"] = now_iso()
    with open(CACHE_JSON, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, separators=(",", ":"))

    # 7. Report
    by_type, by_cat, uncategorised = {}, {c: 0 for c in CATEGORIES}, []
    for it in items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
        for c in it["categories"]:
            by_cat[c] += 1
        if not it["categories"]:
            uncategorised.append(it["uid"])
    unreviewed = sum(1 for r in cat_rows.values() if not r["reviewed"])

    L = [f"# Data update report", "", f"Updated {now_iso()}", "",
         "## Summary", "",
         f"- Items in the repository: {len(ids)}",
         f"- Items shown on the site: {len(items)} "
         + "(" + ", ".join(f"{k}: {v}" for k, v in sorted(by_type.items())) + ")",
         f"- Not shown because of their type: "
         + (", ".join(f"{v} {k}" for k, v in sorted(skipped.items())) or "none"),
         f"- New items this update: {len(new_rows)}",
         f"- Rows in categories.csv not yet marked reviewed: {unreviewed}",
         "", "## Items per category", ""]
    L += [f"- {c}: {n}" for c, n in by_cat.items()]
    L += [f"- No category: {len(uncategorised)}"]

    def section(title, rows, fmt):
        L.extend(["", f"## {title} ({len(rows)})", ""])
        if not rows:
            L.append("None.")
        for r in rows[:200]:
            L.append(fmt(r))
        if len(rows) > 200:
            L.append(f"- …and {len(rows) - 200} more")

    section("Needs a category", uncategorised, lambda u: f"- {u}")
    section("Unknown category names in categories.csv", unknown_cats,
            lambda r: f"- {r[0]}: \"{r[1]}\" (use one of: {', '.join(CATEGORIES)})")
    section("Held back: marked culturally sensitive", sensitive,
            lambda r: f"- {r[0]} {r[1]}: {r[2]} (to show it, add a correction: show_sensitive = yes)")
    section("Preview could not be made (item view uses the embed player)", broken,
            lambda r: f"- {r[0]} {r[1]} ({r[2]}): {r[3]}")
    section("Not shown: file type not recognised", unrecognised,
            lambda r: f"- {r[0]} {r[1]}: {r[2]}")
    section("Unknown fields in corrections.csv", bad_fields,
            lambda r: f"- {r[0]}: \"{r[1]}\" (allowed: {', '.join(sorted(CORRECTABLE))})")
    section("Items whose details could not be read (will retry next time)", failed_details,
            lambda r: f"- Figshare id {r}")

    with open(REPORT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("Done. See data/report.md")


if __name__ == "__main__":
    main()
