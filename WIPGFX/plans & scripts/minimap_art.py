"""gfx/minimap/minimap.dds drawn from the map (the user, 2026-10-25: a better minimap, 268x291): deep space with the
galaxy chart (galaxy_chart_alpha.npy: region fills brighter toward the Deep Core, outlines), the
hyperlanes (map/adjacencies.csv, planet edge to planet edge), and every planet as a small lit globe in its own colours
(map/terrain/colormap_rgb_cityemissivemask_a.dds). Rendered at 4x and downsampled. Uncompressed A8R8G8B8 like
vanilla's.

    python -B "WIPGFX/plans & scripts/minimap_art.py"     writes the dds + WIPGFX/Assets/minimap_preview.png
"""
import csv, math, os, struct, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT = os.path.join(ROOT, "gfx/minimap/minimap.dds")
PREVIEW = os.path.join(ROOT, "WIPGFX/Assets/minimap_preview.png")
W, H = 268, 291                    # the user's size (the map's aspect: 3072 x 3328)
SS = 4                             # supersampling


def render():
    import planet_terrain_gen as g
    import galaxy_regions as gr
    land, _, pid = g.load_provinces()
    MH, MW = land.shape
    w, h = W * SS, H * SS
    sx, sy = w / MW, h / MH
    yy, xx = np.mgrid[:h, :w].astype(np.float32)

    # space: navy, the galaxy chart (its fills, outlines and names: galaxy_chart_alpha.npy) as soft light
    chart = np.asarray(Image.fromarray(np.load(gr.CHART_NPY)).resize((w, h), Image.LANCZOS), np.float32) / 255.0
    chart = ndi.gaussian_filter(chart, 0.8 * SS)
    img = np.stack([0.020 + 0.26 * chart, 0.032 + 0.44 * chart, 0.065 + 0.62 * chart], -1)
    rng = np.random.RandomState(7)
    star = np.zeros((h, w), np.float32)
    star[rng.randint(0, h, 900), rng.randint(0, w, 900)] = rng.uniform(0.3, 1.0, 900)
    img += ndi.gaussian_filter(star, 0.7)[..., None] * np.array([0.8, 0.85, 1.0]) * 1.4

    # hyperlanes, planet edge to planet edge
    lab, n = ndi.label(land, np.ones((3, 3)))
    area = ndi.sum(land, lab, range(1, n + 1))
    cen = ndi.center_of_mass(land, lab, range(1, n + 1))
    body = {}
    ys, xs = np.nonzero(land)
    for p, b in zip(pid[ys, xs][::5].tolist(), lab[ys, xs][::5].tolist()):
        body.setdefault(p, b)
    lane = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(lane)
    for r in csv.reader(open(os.path.join(ROOT, "map/adjacencies.csv"), encoding="utf-8-sig"), delimiter=";"):
        if len(r) > 3 and r[0].isdigit() and r[2] == "sea":
            a, b = body.get(int(r[0])), body.get(int(r[1]))
            if not a or not b or a == b:
                continue
            pa, pb = np.array(cen[a - 1][::-1]), np.array(cen[b - 1][::-1])
            u = (pb - pa) / max(np.linalg.norm(pb - pa), 1e-6)
            ra, rb = math.sqrt(area[a - 1] / math.pi), math.sqrt(area[b - 1] / math.pi)
            s, t = pa + u * ra, pb - u * rb
            dr.line([(s[0] * sx, s[1] * sy), (t[0] * sx, t[1] * sy)], fill=255, width=SS)
    lv = np.asarray(lane, np.float32) / 255.0
    img += (ndi.gaussian_filter(lv, 0.5 * SS) * 0.55 + ndi.gaussian_filter(lv, 2.0 * SS) * 0.25)[..., None] \
        * np.array([0.55, 0.80, 1.00])

    # planets: own colours, lit as globes (light from the upper left), a thin bright rim
    col = np.asarray(Image.open(os.path.join(ROOT, "map/terrain/colormap_rgb_cityemissivemask_a.dds")).convert("RGB")
                     .resize((w, h), Image.LANCZOS), np.float32) / 255.0
    L = np.array(Image.fromarray(land.astype(np.uint8) * 255).resize((w, h), Image.LANCZOS), np.float32) / 255.0
    lab_s = np.array(Image.fromarray(lab.astype(np.int32)).resize((w, h), Image.NEAREST))
    cx_ = np.array([0.0] + [c[1] * sx for c in cen])
    cy_ = np.array([0.0] + [c[0] * sy for c in cen])
    rr = np.array([1.0] + [max(math.sqrt(a / math.pi) * sx, 1.0) for a in area])
    ox, oy = (xx - cx_[lab_s]) / rr[lab_s], (yy - cy_[lab_s]) / rr[lab_s]
    nz = np.sqrt(np.clip(1 - ox ** 2 - oy ** 2, 0, 1))
    light = np.clip(0.35 + 0.95 * (-0.45 * ox - 0.55 * oy + 0.70 * nz), 0.25, 1.35)
    globe = np.clip(col * 1.25, 0, 1) * light[..., None]
    rim = np.clip(1 - nz, 0, 1) ** 3 * 0.35
    globe += rim[..., None] * np.array([0.6, 0.8, 1.0])
    glow = ndi.gaussian_filter(L, 3.0 * SS)
    img += glow[..., None] * np.array([0.30, 0.45, 0.60]) * 0.35
    img = img * (1 - L[..., None]) + globe * L[..., None]

    img = np.clip(img, 0, 1) ** (1 / 1.15)
    out = Image.fromarray((img * 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    return np.asarray(out)


def write_dds(rgb, path):
    """uncompressed A8R8G8B8 (B G R A in memory), one mip, as vanilla's minimap.dds"""
    h, w = rgb.shape[:2]
    hdr = struct.pack("<4s7I44x", b"DDS ", 124, 0x100F, h, w, w * 4, 0, 1)
    pf = struct.pack("<2I4s5I", 32, 0x41, b"\0\0\0\0", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    caps = struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    bgra = np.dstack([rgb[..., 2], rgb[..., 1], rgb[..., 0], np.full((h, w), 255, np.uint8)])
    open(path, "wb").write(hdr + pf + caps + bgra.tobytes())


if __name__ == "__main__":
    os.chdir(ROOT)
    rgb = render()
    write_dds(rgb, OUT)
    Image.fromarray(rgb).save(PREVIEW)
    print(f"wrote {OUT} ({W}x{H}) and {PREVIEW}")
