"""Synthetic document and vehicle imagery (§9).

Produces:

  * STNK front images (clean / worn / glare / partially obscured)
  * VIN plate images in each of the plate conditions from §5.5, including
    TAMPERED_SUSPECTED cases
  * Odometer and engine-number close-ups
  * Nine-angle exterior sets with KNOWN damage labels

Nothing here is photographic. The images are drawn shapes and text that are
recognisably document-like and car-like at a glance. Their purpose is to
exercise the capture quality gate, the perceptual-hash reuse detector, the
OCR/vision stub providers, and the review UI - not to train or evaluate a real
model. A real detector run against these would learn nothing transferable.

Seeded defect cases are what make the M2 acceptance criterion testable: a
known VIN mismatch, a known engine-number mismatch, a known tampered plate,
and a known photo-reuse collision are planted at fixed indices so tests can
assert the pipeline produces the correct verdicts.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .common import stream

DOC_SIZE = (1600, 1067)      # 3:2, matches the STNK overlay aspect ratio
PLATE_SIZE = (1600, 500)     # 16:5, matches the VIN plate overlay
CLOSEUP_SIZE = (1600, 1200)  # 4:3
EXTERIOR_SIZE = (1600, 1200)


# --------------------------------------------------------------------------
# Degradation profiles
# --------------------------------------------------------------------------
# Each profile is a plausible field condition. The quality gate in
# config/capture.yaml should ACCEPT clean and worn, and REJECT blurred and
# dark - the seeded set therefore exercises both sides of every threshold.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Degradation:
    name: str
    blur_radius: float = 0.0
    glare_strength: float = 0.0
    brightness: float = 1.0
    noise: float = 0.0
    occlusion: float = 0.0
    #: Whether the capture quality gate is expected to reject this profile.
    expect_gate_rejection: bool = False


DEGRADATIONS: tuple[Degradation, ...] = (
    Degradation("clean"),
    Degradation("worn", noise=0.06, brightness=0.94),
    Degradation("glare", glare_strength=0.55),
    Degradation("partially_obscured", occlusion=0.18),
    Degradation("blurred", blur_radius=4.5, expect_gate_rejection=True),
    Degradation("dark", brightness=0.42, expect_gate_rejection=True),
)

DEGRADATION_SHARE = {
    "clean": 0.44,
    "worn": 0.24,
    "glare": 0.13,
    "partially_obscured": 0.09,
    "blurred": 0.06,
    "dark": 0.04,
}


@dataclass
class GeneratedImage:
    path: str
    sha256: str
    capture_type: str
    degradation: str
    expect_gate_rejection: bool
    #: Ground truth the stub OCR/vision provider returns for this image, and
    #: which tests assert against.
    truth: dict = field(default_factory=dict)


def _font(size: int) -> ImageFont.ImageFont:
    """A bundled font is not assumed. Pillow's default bitmap font is ugly but
    present everywhere, which matters more here than legibility."""
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _apply(img: Image.Image, deg: Degradation, rng) -> Image.Image:
    if deg.occlusion > 0:
        draw = ImageDraw.Draw(img, "RGBA")
        w, h = img.size
        bw, bh = int(w * deg.occlusion), int(h * deg.occlusion * 2.2)
        x, y = rng.randint(0, max(1, w - bw)), rng.randint(0, max(1, h - bh))
        draw.rectangle([x, y, x + bw, y + bh], fill=(30, 30, 30, 235))

    if deg.glare_strength > 0:
        # An elliptical blown-out highlight, like a phone flash on laminate.
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = img.size
        cx, cy = rng.randint(w // 4, 3 * w // 4), rng.randint(h // 4, 3 * h // 4)
        r = int(min(w, h) * 0.30)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, int(255 * deg.glare_strength)))
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=r // 3))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    if deg.noise > 0:
        px = img.load()
        w, h = img.size
        # Sparse sampling: full-image per-pixel noise on 16k images is slow and
        # adds nothing the gate can see.
        for _ in range(int(w * h * deg.noise * 0.05)):
            x, y = rng.randint(0, w - 1), rng.randint(0, h - 1)
            r, g, b = px[x, y]
            d = rng.randint(-45, 45)
            px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))

    if deg.brightness != 1.0:
        img = img.point(lambda v: max(0, min(255, int(v * deg.brightness))))

    if deg.blur_radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=deg.blur_radius))

    return img


def save_jpeg(img: Image.Image, path: Path) -> str:
    """Write the image and return its sha256 - the fixture lookup key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    data = buf.getvalue()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# STNK
# --------------------------------------------------------------------------

STNK_FIELDS = (
    ("NOMOR REGISTRASI", "nomor_registrasi"),
    ("NAMA PEMILIK", "nama_pemilik"),
    ("ALAMAT", "alamat"),
    ("MERK", "merk"),
    ("TIPE", "tipe"),
    ("JENIS", "jenis"),
    ("MODEL", "model"),
    ("TAHUN PEMBUATAN", "tahun_pembuatan"),
    ("ISI SILINDER", "isi_silinder"),
    ("NOMOR RANGKA", "nomor_rangka"),
    ("NOMOR MESIN", "nomor_mesin"),
    ("WARNA", "warna"),
    ("BAHAN BAKAR", "bahan_bakar"),
    ("WARNA TNKB", "warna_tnkb"),
    ("TAHUN REGISTRASI", "tahun_registrasi"),
    ("NOMOR BPKB", "nomor_bpkb"),
    ("KODE LOKASI", "kode_lokasi"),
)


def draw_stnk(values: dict, deg: Degradation, rng) -> Image.Image:
    img = Image.new("RGB", DOC_SIZE, (238, 235, 222))
    draw = ImageDraw.Draw(img)
    title_font, label_font, value_font = _font(34), _font(21), _font(25)

    draw.rectangle([0, 0, DOC_SIZE[0], 90], fill=(206, 200, 176))
    draw.text((40, 28), "SURAT TANDA NOMOR KENDARAAN BERMOTOR", font=title_font, fill=(40, 40, 40))
    draw.text((DOC_SIZE[0] - 330, 34), "[ DATA SINTETIS ]", font=label_font, fill=(150, 40, 40))

    y = 120
    for label, key in STNK_FIELDS:
        draw.text((48, y), label, font=label_font, fill=(90, 88, 78))
        draw.text((430, y - 4), str(values.get(key, "")), font=value_font, fill=(20, 20, 20))
        y += 44

    # Tax panel. The overlay copy insists this stays inside the frame because
    # it is the sole source of tax status - there is no Samsat integration.
    panel_top = DOC_SIZE[1] - 200
    draw.rectangle([40, panel_top, DOC_SIZE[0] - 40, DOC_SIZE[1] - 30], outline=(120, 118, 100), width=3)
    draw.text((60, panel_top + 14), "PANEL PAJAK", font=label_font, fill=(90, 88, 78))
    draw.text((60, panel_top + 56), "BERLAKU SAMPAI", font=label_font, fill=(90, 88, 78))
    draw.text((330, panel_top + 50), str(values.get("berlaku_sampai", "")), font=value_font, fill=(150, 30, 30))
    draw.text((60, panel_top + 110), "TANGGAL PAJAK", font=label_font, fill=(90, 88, 78))
    draw.text((330, panel_top + 104), str(values.get("tanggal_pajak", "")), font=value_font, fill=(20, 20, 20))

    return _apply(img, deg, rng)


# --------------------------------------------------------------------------
# VIN plate / engine number
# --------------------------------------------------------------------------

PLATE_CONDITION_STYLE = {
    "CLEAN": {"base": (150, 150, 155), "mottle": 0, "scratch": 0, "overpaint": False},
    "RUST_LIGHT": {"base": (140, 120, 100), "mottle": 60, "scratch": 0, "overpaint": False},
    "RUST_HEAVY": {"base": (120, 82, 58), "mottle": 220, "scratch": 0, "overpaint": False},
    "REPAINTED": {"base": (165, 165, 170), "mottle": 10, "scratch": 0, "overpaint": True},
    "SCRATCHED_OVER": {"base": (148, 148, 152), "mottle": 20, "scratch": 40, "overpaint": False},
    "TAMPERED_SUSPECTED": {"base": (145, 143, 148), "mottle": 35, "scratch": 14, "overpaint": True},
    "ILLEGIBLE": {"base": (128, 124, 126), "mottle": 300, "scratch": 70, "overpaint": False},
}


def draw_plate(text: str, condition: str, deg: Degradation, rng, label: str = "NO. RANGKA") -> Image.Image:
    style = PLATE_CONDITION_STYLE[condition]
    img = Image.new("RGB", PLATE_SIZE, style["base"])
    draw = ImageDraw.Draw(img)

    for _ in range(style["mottle"]):
        x, y = rng.randint(0, PLATE_SIZE[0]), rng.randint(0, PLATE_SIZE[1])
        r = rng.randint(4, 26)
        shade = rng.randint(-45, 25)
        base = style["base"]
        draw.ellipse(
            [x - r, y - r, x + r, y + r],
            fill=tuple(max(0, min(255, c + shade)) for c in base),
        )

    draw.rectangle([18, 18, PLATE_SIZE[0] - 18, PLATE_SIZE[1] - 18], outline=(70, 70, 75), width=5)
    draw.text((50, 48), label, font=_font(30), fill=(60, 60, 65))

    # Stamped-metal look: a light offset copy under the dark glyphs.
    stamp_font = _font(96)
    draw.text((52, 190), text, font=stamp_font, fill=(196, 196, 200))
    draw.text((50, 188), text, font=stamp_font, fill=(48, 48, 52))

    if style["overpaint"]:
        # A rectangle of fresh paint over part of the stamping - the visual
        # signature that separates REPAINTED from TAMPERED_SUSPECTED is that
        # the latter also has grinding marks, added below.
        x0 = rng.randint(40, PLATE_SIZE[0] // 2)
        draw.rectangle(
            [x0, 170, x0 + rng.randint(180, 420), 300],
            fill=tuple(min(255, c + 18) for c in style["base"]),
        )

    for _ in range(style["scratch"]):
        x0, y0 = rng.randint(0, PLATE_SIZE[0]), rng.randint(140, PLATE_SIZE[1] - 40)
        length = rng.randint(40, 260)
        angle = rng.uniform(-0.35, 0.35)
        draw.line(
            [x0, y0, x0 + int(length * math.cos(angle)), y0 + int(length * math.sin(angle))],
            fill=(95, 95, 100),
            width=rng.randint(1, 4),
        )

    return _apply(img, deg, rng)


def draw_odometer(km: int, deg: Degradation, rng) -> Image.Image:
    img = Image.new("RGB", CLOSEUP_SIZE, (28, 28, 32))
    draw = ImageDraw.Draw(img)
    draw.ellipse([180, 180, 1420, 1020], outline=(90, 90, 96), width=10)
    draw.rectangle([560, 720, 1060, 850], fill=(12, 14, 12), outline=(70, 80, 70), width=4)
    draw.text((590, 745), f"{km:,}".replace(",", " "), font=_font(72), fill=(150, 230, 150))
    draw.text((600, 880), "km", font=_font(40), fill=(120, 130, 120))
    return _apply(img, deg, rng)


# --------------------------------------------------------------------------
# Exterior set
# --------------------------------------------------------------------------

EXTERIOR_ANGLES = (
    "EXT_FRONT", "EXT_FRONT_34_LEFT", "EXT_LEFT", "EXT_REAR_34_LEFT", "EXT_REAR",
    "EXT_REAR_34_RIGHT", "EXT_RIGHT", "EXT_FRONT_34_RIGHT", "EXT_ROOF",
)

#: Which panels are visible from which angle. The vision stub only reports
#: damage on panels actually visible in the photo it was given, because a
#: provider that reported a rear bumper dent from a front photo would let a
#: broken attribution pass unnoticed.
ANGLE_PANELS: dict[str, tuple[str, ...]] = {
    "EXT_FRONT": ("front_bumper", "hood", "grille", "headlamp_l", "headlamp_r", "windshield"),
    "EXT_FRONT_34_LEFT": ("front_bumper", "hood", "fender_fl", "door_fl", "headlamp_l", "mirror_l", "wheel_fl"),
    "EXT_LEFT": ("door_fl", "door_rl", "fender_fl", "quarter_panel_l", "mirror_l", "wheel_fl", "wheel_rl", "tire_fl", "tire_rl"),
    "EXT_REAR_34_LEFT": ("rear_bumper", "trunk_tailgate", "quarter_panel_l", "taillamp_l", "door_rl", "wheel_rl"),
    "EXT_REAR": ("rear_bumper", "trunk_tailgate", "taillamp_l", "taillamp_r", "rear_glass"),
    "EXT_REAR_34_RIGHT": ("rear_bumper", "trunk_tailgate", "quarter_panel_r", "taillamp_r", "door_rr", "wheel_rr"),
    "EXT_RIGHT": ("door_fr", "door_rr", "fender_fr", "quarter_panel_r", "mirror_r", "wheel_fr", "wheel_rr", "tire_fr", "tire_rr"),
    "EXT_FRONT_34_RIGHT": ("front_bumper", "hood", "fender_fr", "door_fr", "headlamp_r", "mirror_r", "wheel_fr"),
    "EXT_ROOF": ("roof", "windshield", "rear_glass"),
}

COLOUR_RGB = {
    "Hitam": (34, 34, 38), "Putih": (238, 238, 240), "Silver": (178, 180, 184),
    "Abu-abu": (122, 124, 128), "Merah": (170, 40, 44), "Biru": (46, 78, 148),
    "Coklat": (108, 78, 52), "Champagne": (206, 190, 158), "Hijau": (52, 110, 74),
    "Kuning": (222, 190, 52), "Orange": (218, 118, 44), "Ungu": (96, 62, 132),
}

DAMAGE_RGBA = {
    "baret": (235, 235, 235, 190),
    "penyok": (60, 60, 66, 150),
    "karat": (128, 74, 40, 205),
    "cat_ulang": (255, 255, 255, 70),
    "retak": (40, 40, 44, 220),
    "pecah": (250, 250, 255, 230),
    "celah_panel": (18, 18, 20, 240),
    "komponen_hilang": (24, 24, 26, 255),
}


def draw_exterior(angle: str, colour: str, damages: list[dict], deg: Degradation, rng) -> Image.Image:
    """A schematic car body with damage marks drawn at recorded coordinates.

    The bounding boxes written to the label fixture are the boxes actually
    drawn, so a detector stub reading the fixture and a human looking at the
    image see the same thing.
    """
    body = COLOUR_RGB.get(colour, (150, 150, 155))
    img = Image.new("RGB", EXTERIOR_SIZE, (206, 212, 218))
    draw = ImageDraw.Draw(img)

    # Ground and a simple body silhouette. Deliberately schematic.
    draw.rectangle([0, 900, EXTERIOR_SIZE[0], EXTERIOR_SIZE[1]], fill=(150, 152, 150))
    draw.rounded_rectangle([200, 380, 1400, 880], radius=70, fill=body, outline=(40, 40, 44), width=5)
    draw.rounded_rectangle([380, 250, 1180, 430], radius=60, fill=(110, 130, 150), outline=(40, 40, 44), width=5)
    if angle != "EXT_ROOF":
        draw.ellipse([300, 800, 480, 980], fill=(28, 28, 30))
        draw.ellipse([1120, 800, 1300, 980], fill=(28, 28, 30))

    draw.text((40, 40), angle, font=_font(34), fill=(30, 30, 34))
    draw.text((40, 90), "DATA SINTETIS", font=_font(26), fill=(160, 40, 40))

    for dmg in damages:
        x, y, w, h = dmg["bbox_px"]
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        colour_rgba = DAMAGE_RGBA[dmg["damage_type"]]
        if dmg["damage_type"] == "celah_panel":
            od.line([x, y, x + w, y + h], fill=colour_rgba, width=max(3, dmg["severity"] * 4))
        elif dmg["damage_type"] == "baret":
            od.line([x, y, x + w, y + h // 3], fill=colour_rgba, width=max(2, dmg["severity"] * 3))
        else:
            od.ellipse([x, y, x + w, y + h], fill=colour_rgba)
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    return _apply(img, deg, rng)


def sample_damages(rng, angle: str, grade: str, celah: bool, rust: bool, repaint: bool) -> list[dict]:
    """Draw a damage set for one angle, consistent with the unit's grade."""
    panels = ANGLE_PANELS[angle]
    expected = {"A": 0.3, "B": 0.8, "C": 1.6, "D": 2.6, "E": 3.6}[grade]
    count = min(len(panels), _small_poisson(rng, expected))

    types = ["baret", "penyok", "cat_ulang", "retak", "pecah", "komponen_hilang"]
    weights = [0.42, 0.24, 0.14, 0.09, 0.06, 0.05]
    out: list[dict] = []
    for panel in rng.sample(list(panels), count):
        dtype = rng.choices(types, weights=weights, k=1)[0]
        severity = rng.choices([1, 2, 3], weights={"A": [0.9, 0.1, 0.0], "B": [0.7, 0.26, 0.04],
                                                   "C": [0.45, 0.42, 0.13], "D": [0.25, 0.45, 0.30],
                                                   "E": [0.12, 0.38, 0.50]}[grade], k=1)[0]
        w = rng.randint(60, 260) * severity // 2 + 40
        h = rng.randint(40, 180) * severity // 2 + 30
        x = rng.randint(220, 1380 - w)
        y = rng.randint(270, 870 - h)
        out.append({
            "panel": panel,
            "damage_type": dtype,
            "severity": severity,
            "bbox_px": [x, y, w, h],
            "bbox": [round(x / EXTERIOR_SIZE[0], 4), round(y / EXTERIOR_SIZE[1], 4),
                     round(w / EXTERIOR_SIZE[0], 4), round(h / EXTERIOR_SIZE[1], 4)],
            "area_ratio": round(min(0.95, (w * h) / (EXTERIOR_SIZE[0] * EXTERIOR_SIZE[1]) * 6.0), 4),
            "confidence": round(rng.uniform(0.55, 0.97), 3),
        })

    # The unit-level structural signals are attached to the angles that can
    # actually show them.
    if celah and angle in ("EXT_FRONT_34_LEFT", "EXT_FRONT_34_RIGHT", "EXT_REAR_34_LEFT", "EXT_REAR_34_RIGHT"):
        panel = rng.choice([p for p in panels if p.startswith(("door", "fender", "quarter"))] or list(panels))
        x, y = rng.randint(300, 1200), rng.randint(400, 800)
        out.append({
            "panel": panel, "damage_type": "celah_panel",
            "severity": rng.choices([1, 2, 3], weights=[0.3, 0.5, 0.2], k=1)[0],
            "bbox_px": [x, y, 18, 160], "bbox": [round(x / 1600, 4), round(y / 1200, 4), 0.011, 0.133],
            "area_ratio": 0.012, "confidence": round(rng.uniform(0.6, 0.95), 3),
        })
    if rust and angle in ("EXT_LEFT", "EXT_RIGHT", "EXT_REAR"):
        panel = rng.choice(list(panels))
        x, y = rng.randint(300, 1200), rng.randint(600, 850)
        out.append({
            "panel": panel, "damage_type": "karat",
            "severity": rng.choices([1, 2, 3], weights=[0.35, 0.4, 0.25], k=1)[0],
            "bbox_px": [x, y, 120, 90], "bbox": [round(x / 1600, 4), round(y / 1200, 4), 0.075, 0.075],
            "area_ratio": 0.055, "confidence": round(rng.uniform(0.6, 0.94), 3),
        })
    if repaint and angle in ("EXT_FRONT", "EXT_LEFT", "EXT_RIGHT", "EXT_REAR"):
        panel = rng.choice(list(panels))
        x, y = rng.randint(300, 1100), rng.randint(400, 700)
        out.append({
            "panel": panel, "damage_type": "cat_ulang",
            "severity": rng.choices([1, 2, 3], weights=[0.5, 0.4, 0.1], k=1)[0],
            "bbox_px": [x, y, 280, 180], "bbox": [round(x / 1600, 4), round(y / 1200, 4), 0.175, 0.15],
            "area_ratio": 0.16, "confidence": round(rng.uniform(0.5, 0.9), 3),
        })
    return out


def _small_poisson(rng, lam: float) -> int:
    target = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= target:
            return k
        k += 1
        if k > 20:
            return k


# --------------------------------------------------------------------------
# Fixture writing
# --------------------------------------------------------------------------


def write_fixtures(images: list[GeneratedImage], ocr_dir: Path, vision_dir: Path) -> None:
    """Write stub-provider fixtures keyed by image sha256.

    Keying on content hash rather than filename means the stub provider needs
    no extra plumbing: it hashes the bytes it was handed and looks up the
    answer. It also means an image that is re-saved or re-encoded stops
    matching, which is the correct behaviour - it is a different image.
    """
    ocr_dir.mkdir(parents=True, exist_ok=True)
    vision_dir.mkdir(parents=True, exist_ok=True)

    ocr_index: dict[str, dict] = {}
    vision_index: dict[str, dict] = {}
    for image in images:
        if image.capture_type.startswith("EXT_"):
            vision_index[image.sha256] = image.truth
        else:
            ocr_index[image.sha256] = image.truth

    (ocr_dir / "index.json").write_text(json.dumps(ocr_index, indent=2, default=str), encoding="utf-8")
    (vision_dir / "index.json").write_text(json.dumps(vision_index, indent=2, default=str), encoding="utf-8")


def manifest(images: list[GeneratedImage]) -> dict:
    return {
        "synthetic": True,
        "warning": (
            "All imagery is synthetic. It exercises capture, OCR, and vision code "
            "paths only and carries no evidential value for model accuracy."
        ),
        "count": len(images),
        "images": [asdict(i) for i in images],
    }
