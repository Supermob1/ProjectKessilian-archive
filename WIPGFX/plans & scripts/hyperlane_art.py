"""Curved hyperlanes painted into space (the user, 2026-10-25: "improve the texture for straits and make curved
hyperlanes"). The engine draws each strait (sea adjacency in map/adjacencies.csv) as a straight strip of
map/terrain/strait.dds that no shader can bend, so the lanes are drawn here instead: one gentle curve per adjacency,
from the coast of its From province to the coast of its To province (the two nearest coast pixels), bent to the side
that crosses fewer planets. They are baked into the rgb of map/terrain/ice_diffuse.dds, which pdxwater.shader adds
to space at every zoom (the planets' atmospheres live there too), and strait.dds is made transparent so the straight
engine strip doesn't double them.

    python -B "WIPGFX/plans & scripts/hyperlane_art.py" preview    WIPGFX/Assets/hyperlanes_preview.png only
    python -B "WIPGFX/plans & scripts/hyperlane_art.py" write      ice_diffuse.dds rgb + strait.dds

The lanes are kept in WIPGFX/Assets/hyperlanes_rgb.npy; galaxy_regions.reinject() puts them back after
planet_terrain_gen.py rewrites the atmospheres. Run again after adding or moving lanes.
"""
import csv, math, os, sys
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ICE = os.path.join(ROOT, "map/terrain/ice_diffuse.dds")
STRAIT = os.path.join(ROOT, "map/terrain/strait.dds")
LANES_NPY = os.path.join(ROOT, "WIPGFX/Assets/hyperlanes_rgb.npy")
PREVIEW = os.path.join(ROOT, "WIPGFX/Assets/hyperlanes_preview.png")
COLOR = np.array([0.55, 0.82, 1.00])   # pale blue-white, the chart's palette
BEND = 0.18                            # control point offset, share of the lane's length
CORE_W = 0.8                           # half-res px: the bright thread
GLOW_W = 3.5                           # half-res px: the soft glow round it
GLOW = 0.35                            # glow strength against the core


def lanes():
    out = []
    for r in csv.reader(open(os.path.join(ROOT, "map/adjacencies.csv"), encoding="utf-8-sig"), delimiter=";"):
        if len(r) > 3 and r[0].isdigit() and r[2] == "sea":
            out.append((int(r[0]), int(r[1])))
    return out


def curves():
    """[(p0, control, p2)] in full-res (col, row) px"""
    import planet_terrain_gen as g
    land, _, pid = g.load_provinces()
    H, W = land.shape
    coast = land & ndi.binary_dilation(~land)
    ys, xs = np.nonzero(coast)
    by_prov = {}
    for p, y, x in zip(pid[ys, xs].tolist(), ys.tolist(), xs.tolist()):
        by_prov.setdefault(p, []).append((x, y))
    core = np.array([793.0, H - 1 - 1551.0])                     # galactic core (pdxwater.shader GALAXY_CORE), px
    res = []
    for a, b in lanes():
        if a not in by_prov or b not in by_prov:
            print(f"lane {a}-{b}: a province has no coast, skipped")
            continue
        A, B = np.array(by_prov[a], float), np.array(by_prov[b], float)
        d, j = cKDTree(B).query(A)
        i = int(np.argmin(d))
        p0, p2 = A[i], B[j[i]]
        L = float(np.hypot(*(p2 - p0)))
        if L < 2:
            continue
        n = np.array([-(p2 - p0)[1], (p2 - p0)[0]]) / L
        mid = (p0 + p2) / 2
        best = None
        for s in (1, -1):
            c = mid + n * s * BEND * L
            t = np.linspace(0.08, 0.92, 40)[:, None]
            pts = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * c + t ** 2 * p2
            r_, c_ = np.clip(pts[:, 1].astype(int), 0, H - 1), np.clip(pts[:, 0].astype(int), 0, W - 1)
            hits = int(land[r_, c_].sum())
            away = float(np.hypot(*(c - core)))                    # tie: bend away from the core
            key = (hits, -away)
            if best is None or key < best[0]:
                best = (key, c)
        res.append((p0, best[1], p2))
    return res, land


def render(cs, land):
    """half-res rgb canvas (h, w, 3) of the lanes, 0..1"""
    H, W = land.shape
    h, w = H // 2, W // 2
    mask = np.zeros((h, w), bool)
    for p0, c, p2 in cs:
        L = np.hypot(*(p2 - p0)) + np.hypot(*(c - p0))
        t = np.linspace(0, 1, int(L) + 2)[:, None]
        pts = ((1 - t) ** 2 * p0 + 2 * (1 - t) * t * c + t ** 2 * p2) / 2.0
        mask[np.clip(pts[:, 1].astype(int), 0, h - 1), np.clip(pts[:, 0].astype(int), 0, w - 1)] = True
    d = ndi.distance_transform_edt(~mask)
    v = np.exp(-(d / CORE_W) ** 2) + GLOW * np.exp(-(d / GLOW_W) ** 2)
    v *= ~land[::2, ::2][:h, :w]                                   # never over a planet
    return np.clip(v[..., None] * COLOR, 0, 1)


def apply(rgb):
    """max() of the lanes into ice_diffuse.dds rgb (uncompressed A8R8G8B8, rows top-down, bytes B G R A)"""
    import struct
    raw = bytearray(open(ICE, "rb").read())
    hh, ww = struct.unpack("<II", raw[12:20])
    assert (hh, ww) == rgb.shape[:2], ((hh, ww), rgb.shape)
    px = np.frombuffer(bytes(raw[128:128 + hh * ww * 4]), np.uint8).reshape(hh, ww, 4).copy()
    lane = np.rint(rgb * 255).astype(np.uint8)
    px[..., 2] = np.maximum(px[..., 2], lane[..., 0])
    px[..., 1] = np.maximum(px[..., 1], lane[..., 1])
    px[..., 0] = np.maximum(px[..., 0], lane[..., 2])
    raw[128:128 + px.nbytes] = px.tobytes()
    open(ICE, "wb").write(raw)


def reapply():
    """called by galaxy_regions.reinject after the atmospheres are rewritten"""
    if os.path.exists(LANES_NPY):
        apply(np.load(LANES_NPY) / 255.0)


def hide_strait():
    """strait.dds fully transparent: the engine's straight strip is not drawn over the curves"""
    from atlas_gen import save_dxt5_mips
    save_dxt5_mips(np.zeros((64, 64, 4), np.uint8), STRAIT)


def preview(rgb, land):
    from PIL import Image
    import galaxy_regions as gr
    chart = np.load(gr.CHART_NPY).astype(np.float32) / 255.0
    h, w = rgb.shape[:2]
    bg = 0.03 + chart[..., None] * np.array([0.42, 0.64, 0.76]) * 0.42
    img = bg + rgb * 0.3                                          # x0.3, as pdxwater.shader adds ice_diffuse rgb
    img = np.where(land[::2, ::2][:h, :w, None], np.array([0.30, 0.34, 0.28]), img)
    Image.fromarray((np.clip(img, 0, 1) ** (1 / 1.4) * 255).astype(np.uint8)).save(PREVIEW)
    print("preview:", PREVIEW)


if __name__ == "__main__":
    os.chdir(ROOT)
    cs, land = curves()
    rgb = render(cs, land)
    print(f"{len(cs)} lanes drawn")
    preview(rgb, land)
    if len(sys.argv) > 1 and sys.argv[1] == "write":
        np.save(LANES_NPY, np.rint(rgb * 255).astype(np.uint8))
        apply(rgb)
        hide_strait()
        print("wrote", ICE, "and", STRAIT)
