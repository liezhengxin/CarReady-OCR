"use strict";
/* ==========================================================================
   Shared prototype store
   ==========================================================================
   The inspector app and the dashboard are separate clients, exactly as they
   are in the real architecture (PWA and dashboard both talking to one API).
   This file stands in for that API: one versioned localStorage envelope both
   pages read and write, plus a change notification so a dashboard left open
   updates when an inspection is submitted in another tab.

   Two limitations worth stating rather than discovering:

   1. localStorage is per-origin. Open these pages over http (for example
      `python -m http.server` inside prototype/) - not as file:// URLs, where
      browsers disagree about whether two files share an origin.

   2. Nothing here is the pipeline. Submitting an inspection cannot produce a
      grade or a price, because vision and pricing have not run. The store
      keeps units at the status they have actually reached, and the dashboard
      is responsible for not rendering values that do not exist yet.
   ========================================================================== */

const CareadyStore = (() => {
  const KEY = "caready-prototype-v1";
  const VERSION = 1;

  /* Seeded dashboard units occupy CR-26-0401..0414. New codes start above
     that block so a submitted unit can never collide with a demo one. */
  const CODE_PREFIX = "CR-26-";
  const CODE_FLOOR = 500;

  const empty = () => ({ version: VERSION, units: [], updatedAt: null });

  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY));
      if (raw?.version === VERSION && Array.isArray(raw.units)) return raw;
    } catch { /* corrupt or unavailable - fall through to empty */ }
    return empty();
  }

  function save(data) {
    try {
      data.updatedAt = new Date().toISOString();
      localStorage.setItem(KEY, JSON.stringify(data));
      return true;
    } catch {
      /* Private window, blocked site data, or quota. The caller keeps working
         in memory; it must not pretend the write succeeded. */
      return false;
    }
  }

  function units() {
    return load().units;
  }

  /* Next free code, taking the caller's reserved list (the dashboard's seeded
     codes) into account so both pages agree on what is already taken. */
  function nextCode(reserved = []) {
    const taken = new Set([...reserved, ...units().map(u => u.code)]);
    let n = CODE_FLOOR;
    let code;
    do {
      code = CODE_PREFIX + String(n).padStart(4, "0");
      n += 1;
    } while (taken.has(code));
    return code;
  }

  function addUnit(unit) {
    const data = load();
    const at = data.units.findIndex(u => u.code === unit.code);
    if (at >= 0) data.units[at] = unit;
    else data.units.unshift(unit);
    const ok = save(data);
    /* The storage event only fires in *other* tabs, so notify this one too. */
    if (ok) window.dispatchEvent(new CustomEvent("caready:store", { detail: { code: unit.code } }));
    return ok;
  }

  /* Clearing the unit list without clearing the photos leaves orphaned blobs
     in IndexedDB that nothing will ever reference again - they accumulated
     across every rehearsal. CareadyPhotos is defined after this block, so it
     is looked up at call time rather than captured. */
  async function clear() {
    try { localStorage.removeItem(KEY); } catch { /* nothing to do */ }
    /* Direct reference, not globalThis: a top-level `const` in a classic
       script is not a property of the global object, so an optional chain
       through globalThis silently matched nothing and reported success.
       CareadyPhotos is defined further down this file but initialised long
       before any caller reaches here. */
    try { await CareadyPhotos.wipe(); }
    catch (e) { console.warn("foto tidak terhapus:", e); }
    window.dispatchEvent(new CustomEvent("caready:store", { detail: { cleared: true } }));
  }

  /* Fires for writes from this tab (CustomEvent) and from others (storage). */
  function subscribe(fn) {
    window.addEventListener("caready:store", fn);
    window.addEventListener("storage", e => { if (e.key === KEY) fn(e); });
  }

  return { load, save, units, nextCode, addUnit, clear, subscribe, KEY, VERSION };
})();

/* ==========================================================================
   Captured photos
   ==========================================================================
   Photos cannot live in the localStorage envelope: twelve captures per unit
   is far past the ~5MB origin quota once base64-encoded. They also cannot be
   passed as blob: URLs, which are scoped to the document that created them
   and die on navigation.

   So they go in IndexedDB, keyed by unit code and capture slot. That is also
   what config/capture.yaml specifies for the real offline queue
   (`offline.store: indexeddb`), so this is the architecture rather than a
   workaround for it.

   On PII: the STNK carries nama_pemilik, alamat and possibly NIK. The
   dashboard already masks those as *text* and requires pii:unmask to reveal
   them. Displaying the source image unmasked next to a masked text field
   would make the control theatre, so the STNK image is blurred by the same
   rule and reveals on the same action. docs/PDP.md describes exactly this for
   external OCR providers - region masking before the image goes anywhere.
   ========================================================================== */

const CareadyPhotos = (() => {
  const DB_NAME = "caready-photos";
  const STORE = "captures";
  const DB_VERSION = 1;

  let dbp = null;

  function db() {
    if (dbp) return dbp;
    dbp = new Promise((resolve, reject) => {
      let req;
      try { req = indexedDB.open(DB_NAME, DB_VERSION); }
      catch (e) { reject(e); return; }
      req.onupgradeneeded = () => {
        const d = req.result;
        if (!d.objectStoreNames.contains(STORE)) {
          const os = d.createObjectStore(STORE, { keyPath: "key" });
          os.createIndex("code", "code", { unique: false });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbp;
  }

  const tx = async (mode, fn) => {
    const d = await db();
    return new Promise((resolve, reject) => {
      const t = d.transaction(STORE, mode);
      const out = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(out?.result ?? out);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error);
    });
  };

  /* Re-encode before storing. A 6MB phone photo is wasted here - the longest
     edge the dashboard ever displays is well under 1280. */
  async function shrink(srcUrl, maxEdge = 1280, quality = 0.72) {
    const img = await new Promise((res, rej) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => rej(new Error("gambar tidak terbaca"));
      im.src = srcUrl;
    });
    const scale = Math.min(1, maxEdge / Math.max(img.naturalWidth, img.naturalHeight));
    const w = Math.round(img.naturalWidth * scale);
    const h = Math.round(img.naturalHeight * scale);
    const cv = document.createElement("canvas");
    cv.width = w; cv.height = h;
    cv.getContext("2d").drawImage(img, 0, 0, w, h);
    const blob = await new Promise(res => cv.toBlob(res, "image/jpeg", quality));
    return { blob, w, h };
  }

  async function put(code, capId, srcUrl, meta) {
    const { blob, w, h } = await shrink(srcUrl);
    await tx("readwrite", os => os.put({
      key: `${code}:${capId}`, code, capId,
      title: meta.title, kind: meta.kind, pii: !!meta.pii,
      ord: Number.isFinite(meta.ord) ? meta.ord : 999,
      blob, w, h, at: new Date().toISOString()
    }));
    return { capId, title: meta.title, kind: meta.kind, pii: !!meta.pii,
             ord: meta.ord ?? 999, w, h };
  }

  /* Metadata only - the caller asks for blobs one at a time, so opening a
     unit does not pull twelve images into memory at once.

     Ordered by the capture slot order the inspector recorded, not by id: the
     document slots read stnk, vin, engine, which sorts alphabetically as
     engine, stnk, vin and would put the STNK second. */
  async function manifest(code) {
    const rows = await tx("readonly", os => os.index("code").getAll(code));
    return (rows || [])
      .map(r => ({ capId: r.capId, title: r.title, kind: r.kind, pii: r.pii,
                   w: r.w, h: r.h, ord: r.ord ?? 999 }))
      .sort((a, b) => (a.kind === b.kind ? a.ord - b.ord : a.kind === "doc" ? -1 : 1));
  }

  async function objectUrl(code, capId) {
    const row = await tx("readonly", os => os.get(`${code}:${capId}`));
    return row?.blob ? URL.createObjectURL(row.blob) : null;
  }

  async function wipe() {
    await tx("readwrite", os => os.clear());
  }

  async function usage() {
    const rows = await tx("readonly", os => os.getAll());
    const bytes = (rows || []).reduce((n, r) => n + (r.blob?.size ?? 0), 0);
    return { count: (rows || []).length, bytes };
  }

  return { put, manifest, objectUrl, wipe, usage, shrink };
})();

/* ==========================================================================
   Simulated ICR
   ==========================================================================
   Stands in for the ICR worker until M2. It fabricates the fields an OCR read
   would produce, which means every value it writes is invented - so each unit
   it touches carries `synthetic: true` and `icrSimulated: true`, and the
   dashboard labels it.

   What it deliberately does NOT do:

     - It does not invent damages. Vision has not run, so `damages` stays
       empty and the unit stops at ICR_DONE rather than GRADED.
     - It does not invent otr or anchor. Those come from the variant catalog
       (M4); left null, so no price can be computed from them by accident.
     - It does not invent a mismatch. A fabricated fraud signal is worse than
       no signal, so identity fields agree and `defect` stays null.

   What it passes through untouched, because the inspector really did produce
   it: the odometer reading and the non-visual checklist answers.
   ========================================================================== */

const CareadySim = (() => {
  /* Deterministic PRNG so the same code always yields the same simulated
     read - a prototype that changes its own data on reload is untestable. */
  function mulberry32(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const seedFrom = s => {
    let h = 2166136261;
    for (const ch of String(s)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    return h >>> 0;
  };

  /* ISO 3779 excludes I, O and Q to remove the 1/l, 0/O and O/Q confusions.
     Generating within the legal charset keeps the dashboard's normaliser and
     cross-check logic exercised on realistic input. */
  const VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789";

  const COLOURS = ["Hitam", "Putih", "Silver", "Abu-abu", "Merah", "Biru Tua"];
  const BRANCHES = ["JKT-01", "JKT-02", "SBY-01", "BDG-01", "MDN-01"];
  /* Placeholder owner names. Synthetic by construction - see PDP.md: no real
     STNK PII belongs in a prototype fixture. */
  const NAMES = ["Agus Pratama", "Dewi Lestari", "Hendra Kusuma", "Rina Marlina",
                 "Yusuf Hidayat", "Sri Wahyuni", "Bambang Nugroho"];
  const STREETS = ["Jl. Kenanga", "Jl. Cempaka", "Jl. Bougenville", "Jl. Flamboyan", "Jl. Dahlia"];
  const CITIES = [["Jakarta Timur", "DKI Jakarta"], ["Bandung", "Jawa Barat"],
                  ["Surabaya", "Jawa Timur"], ["Medan", "Sumatera Utara"]];

  const pick = (rng, arr) => arr[Math.floor(rng() * arr.length)];
  const between = (rng, lo, hi) => lo + Math.floor(rng() * (hi - lo + 1));
  const chars = (rng, n) => Array.from({ length: n }, () => pick(rng, VIN_CHARS.split(""))).join("");

  /* The pool carries one free-text car string ("Toyota Avanza G"). Split it
     the way a catalog match would: first token is the brand, second the
     model, the remainder the trim. The STNK does not record transmission at
     all, which is why trans is left for the catalog to resolve. */
  function splitCar(car) {
    const parts = String(car).trim().split(/\s+/);
    return {
      merk: parts[0] ?? "",
      model: parts[1] ?? "",
      trim: parts.slice(2).join(" ") || "-"
    };
  }

  function icr(draft) {
    const rng = mulberry32(seedFrom(draft.code));
    const { merk, model, trim } = splitCar(draft.car);
    const [city, province] = pick(rng, CITIES);
    /* 17 characters: ISO 3779 length, so the dashboard's length and charset
       checks see a well-formed VIN rather than a short string. */
    const rangka = chars(rng, 11) + String(between(rng, 100000, 999999));
    const mesin = pick(rng, ["F", "K", "M", "N"]) + String(between(rng, 10000000, 99999999)).slice(0, 8);
    const taxYear = draft.year + between(rng, 7, 9);

    return {
      ...draft,
      status: "ICR_DONE",
      icrSimulated: true,
      synthetic: true,

      merk, model, trim,
      trans: null,                    // STNK does not record it; catalog resolves it (M4)
      year: draft.year,
      cc: pick(rng, [998, 1197, 1329, 1496, 1497, 1499]),
      colour: pick(rng, COLOURS),
      fuel: "Bensin",
      branch: pick(rng, BRANCHES),

      otr: null,                      // variant catalog (M4)
      anchor: null,                   // pricing reference (M5)

      tax: "ACTIVE",
      taxUntil: `${String(between(rng, 1, 28)).padStart(2, "0")}-${String(between(rng, 1, 12)).padStart(2, "0")}-${taxYear}`,

      pemilik: pick(rng, NAMES),
      alamat: `${pick(rng, STREETS)} No. ${between(rng, 1, 180)} RT ${String(between(rng, 1, 12)).padStart(2, "0")}/RW ${String(between(rng, 1, 14)).padStart(2, "0")}, ${city}, ${province}`,

      rangka,
      mesin,
      bpkb: `${between(rng, 100000, 999999)}-${between(rng, 10, 99)}`,

      /* Identity agrees. Inventing a mismatch would inject a fraud signal
         that no read actually produced. */
      platRangka: rangka,
      platMesin: mesin,
      plateCond: "CLEAN",

      damages: [],                    // vision has not run (M6)
      defect: null
    };
  }

  /* ======================================================================
     Demo scenarios
     ======================================================================
     Three pre-authored outcomes, one per demo vehicle, so the same inspection
     flow produces three different verdicts. Selected by plate.

     These carry a unit all the way to PENDING_APPROVAL - grade, damages and
     price included - because the demo needs to show a finished result rather
     than stopping at ICR_DONE.

     Two things keep this defensible:

       1. The damage findings are authored, but the grade and the price are
          NOT. The dashboard computes both from these findings using the real
          rubric in config/grading.yaml and the real pricing arithmetic. So
          "why is this Rp 160,5 juta?" has an answer: OTR x residual anchor,
          less the condition effect of a 28.7 damage score, at P30.

       2. Every unit still carries icrSimulated, so the dashboard labels it.
          The numbers are consistent, not real.

     Anything the inspector genuinely produced - the odometer reading, the
     checklist answers, the photo count - is taken from the submission and
     overrides nothing here.
     ====================================================================== */

  const SCENARIOS = {

    /* 1. The real document. A Toyota Hilux whose STNK came from the office,
          with the owner name and address redacted out of the image and
          replaced with synthetic values here - no third party's home address
          belongs in a fixture or on a client call.

          Every vehicle field below is what the document actually says, and
          the stamped chassis and engine plates were generated from the same
          numbers, so the cross-check genuinely matches rather than being
          told to pass.

          The finding is real too: the annual tax sheet reads BERLAKU S/D
          16-12-2024, over twelve months ago, which crosschecks.yaml treats
          as a WARNING and pricing.yaml charges Rp 4.500.000 against the
          floor price. Nothing on screen contradicts the photo. */
    "B 9369 VBA": {
      merk: "Toyota", model: "Hilux", trim: "2.4G DC 4x4", trans: "MT",
      year: 2021, cc: 2393, colour: "Putih", fuel: "Solar", branch: "JKT-01",
      otr: 575_000_000, anchor: 0.70,
      tax: "EXPIRED_GTE_12M", taxUntil: "16-12-2024",
      pemilik: "Bayu Nugroho",                       // synthetic
      alamat: "Jl. Puspita Raya No. 36, Serpong, Banten",   // generalised
      rangka: "MR0KB8CD1M1129592",
      mesin: "2GD5115932",
      bpkb: "T02770345",
      platRangka: "MR0KB8CD1M1129592",   // matches - the plates were made from it
      platMesin: "2GD5115932",
      plateCond: "CLEAN",
      defect: null,
      damages: [
        { panel: "rear_bumper", type: "baret",  sev: 2, area: 0.08, conf: 0.91 },
        { panel: "door_rl",     type: "penyok", sev: 2, area: 0.07, conf: 0.93 },
        { panel: "fender_fl",   type: "karat",  sev: 2, area: 0.06, conf: 0.88 },
        { panel: "tire_rl",     type: "baret",  sev: 1, area: 0.03, conf: 0.86 }
      ]
    },

    /* 2. The clean comparison. Synthetic throughout, so it can be shown
          without any redaction, and it is the contrast that makes the first
          car's finding legible: same flow, nothing flagged, small deduction,
          ready to approve. */
    "B 2914 RFK": {
      merk: "Honda", model: "Brio", trim: "1.2 Satya E", trans: "CVT",
      year: 2021, cc: 1199, colour: "Putih", fuel: "Bensin", branch: "JKT-01",
      otr: 185_000_000, anchor: 0.72,
      tax: "ACTIVE", taxUntil: "09-06-2027",
      pemilik: "Dewi Lestari",
      alamat: "Jl. Cempaka No. 28 RT 03/RW 07, Jakarta Timur, DKI Jakarta",
      rangka: "MHRGK8670MJ204418", mesin: "L12B71104227",
      bpkb: "714302-22",
      platRangka: "MHRGK8670MJ204418",
      platMesin: "L12B71104227",
      plateCond: "CLEAN",
      defect: null,
      damages: [
        { panel: "front_bumper", type: "baret", sev: 1, area: 0.03, conf: 0.93 },
        { panel: "door_rr",      type: "baret", sev: 1, area: 0.02, conf: 0.88 }
      ]
    }
  };

  const hasScenario = plat => Object.prototype.hasOwnProperty.call(SCENARIOS, plat);

  /* A finished unit for a demo vehicle; otherwise the honest ICR_DONE result. */
  function result(draft) {
    if (!hasScenario(draft.plat)) return icr(draft);
    return {
      ...draft,
      ...SCENARIOS[draft.plat],
      status: "PENDING_APPROVAL",
      icrSimulated: true,
      synthetic: true,
      /* The inspector's own output wins over anything authored above. */
      odo: draft.odo,
      checklist: draft.checklist ?? {},
      photos: draft.photos
    };
  }

  return { icr, result, splitCar, hasScenario, SCENARIOS };
})();