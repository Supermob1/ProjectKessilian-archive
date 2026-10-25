"""Hyperlanes (sea adjacencies in map/adjacencies.csv) redrawn as one clean network (the user, 2026-10-25: "redo the
adjacencies so planets are well connected with each other").

    python -B "WIPGFX/plans & scripts/lane_network.py" plan     report + WIPGFX/Assets/lane_network_preview.png
    python -B "WIPGFX/plans & scripts/lane_network.py" write    rewrites the sea rows of map/adjacencies.csv
then:  python tools/hoi4_country_editor/gen_hyperlanes.py .    (rule names, comments, adjacency_rules.txt)

Planets = land bodies. Links, shortest gap (edge to edge) first, a link is kept only if it crosses no kept link and
passes no other planet closer than MARGIN px:
  1. neighbours: Gabriel pairs (no other planet centre inside the circle on the pair) up to GAP px apart, at most
     MAX_DEGREE links per planet;
  2. no dead ends: a planet with fewer than 2 links gets its next clear link up to 2.5 x GAP;
  3. one network: what is still apart is joined by its shortest clear link (then by any link).
Each link becomes one lane: From / To = the provinces at the two nearest coast pixels of the two planets (moved to
the nearest coast pixel of a province in a state if needed), Through = the space province just off the From coast
toward the To planet (the game only needs one end next to Through: fix_lanes.py).
"""
import collections, csv, glob, math, os, re, sys
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ADJ = os.path.join(ROOT, "map/adjacencies.csv")
PREVIEW = os.path.join(ROOT, "WIPGFX/Assets/lane_network_preview.png")
GAP = 110.0          # px edge to edge for a neighbour link
MAX_DEGREE = 5       # links per planet in step 1-2
MARGIN = 12.0        # px a lane keeps clear of other planets
MIN_AREA = 500       # px: smaller land bodies are not planets


def crosses(a, b, c, d):
    o = lambda p, q, r: np.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]))
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def network(P, R, B):
    PA = np.array([P[i] for i in B])
    RA = np.array([R[i] for i in B])
    idx = {b: k for k, b in enumerate(B)}

    def clearance(a, b):
        ab = P[b] - P[a]
        t = np.clip(((PA - P[a]) @ ab) / (ab @ ab), 0, 1)
        d = np.linalg.norm(PA - P[a] - t[:, None] * ab, axis=1) - RA
        d[[idx[a], idx[b]]] = 1e9
        return float(d.min())

    cand = []
    for x in range(len(B)):
        for y in range(x + 1, len(B)):
            a, b = B[x], B[y]
            gap = float(np.linalg.norm(P[a] - P[b]) - R[a] - R[b])
            m, rad = (P[a] + P[b]) / 2, float(np.linalg.norm(P[a] - P[b])) / 2
            inside = np.linalg.norm(PA - m, axis=1) < rad * 0.9
            inside[[x, y]] = False
            cand.append((gap, a, b, not inside.any(), clearance(a, b)))
    cand.sort()
    E, deg, par = [], collections.Counter(), {i: i for i in B}

    def root(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def free(a, b):
        return (a, b) not in E and (b, a) not in E and not any(
            crosses(P[a], P[b], P[c], P[d]) for c, d in E if len({a, b, c, d}) == 4)

    def add(a, b):
        E.append((a, b))
        deg[a] += 1
        deg[b] += 1
        par[root(a)] = root(b)

    for gap, a, b, gab, cl in cand:
        if gab and cl > MARGIN and gap <= GAP and deg[a] < MAX_DEGREE and deg[b] < MAX_DEGREE and free(a, b):
            add(a, b)
    for gap, a, b, gab, cl in cand:
        if (deg[a] < 2 or deg[b] < 2) and cl > MARGIN and gap <= GAP * 2.5 and deg[a] < MAX_DEGREE \
                and deg[b] < MAX_DEGREE and free(a, b):
            add(a, b)
    for strict in (True, False):
        for gap, a, b, gab, cl in cand:
            if root(a) != root(b) and (cl > MARGIN or not strict) and free(a, b):
                add(a, b)
    assert len({root(i) for i in B}) == 1, "network in pieces"
    return E, deg


def build():
    import planet_terrain_gen as g
    land, _, pid = g.load_provinces()
    H, W = land.shape
    lab, n = ndi.label(land, np.ones((3, 3)))
    names = g.planet_names(lab, n, pid)
    area = ndi.sum(land, lab, range(1, n + 1))
    cen = ndi.center_of_mass(land, lab, range(1, n + 1))
    B = [i for i in range(1, n + 1) if area[i - 1] >= MIN_AREA]
    P = {i: np.array([cen[i - 1][1], cen[i - 1][0]]) for i in B}
    R = {i: math.sqrt(area[i - 1] / math.pi) for i in B}
    E, deg = network(P, R, B)

    state = {}
    for f in glob.glob(os.path.join(ROOT, "history/states/*.txt")):
        s = open(f, encoding="utf-8-sig", errors="replace").read()
        m = re.search(r"provinces\s*=\s*\{([^}]*)\}", s)
        sid = re.search(r"\bid\s*=\s*(\d+)", s)
        for p in (m.group(1).split() if m and sid else []):
            state[int(p)] = int(sid.group(1))
    coast = land & ndi.binary_dilation(~land)
    cy, cx = np.nonzero(coast)
    keep = np.array([int(pid[y, x]) in state for y, x in zip(cy, cx)])
    cy, cx = cy[keep], cx[keep]
    cb = lab[cy, cx]
    pts = {i: np.stack([cx[cb == i], cy[cb == i]], 1).astype(float) for i in B}
    lanes = []
    for a, b in E:
        d, j = cKDTree(pts[b]).query(pts[a])
        k = int(np.argmin(d))
        pa, pb = pts[a][k], pts[b][j[k]]
        fa, fb = int(pid[int(pa[1]), int(pa[0])]), int(pid[int(pb[1]), int(pb[0])])
        u = (pb - pa) / max(np.linalg.norm(pb - pa), 1e-6)
        through = None
        for s_ in np.arange(1.0, 40.0, 0.5):                     # the first space pixel off the From coast
            x, y = int(round(pa[0] + u[0] * s_)), int(round(pa[1] + u[1] * s_))
            if 0 <= x < W and 0 <= y < H and not land[y, x]:
                through = int(pid[y, x])
                break
        if through is None:
            print(f"no space province off {names[a]} toward {names[b]}: skipped")
            continue
        lanes.append((fa, fb, through, names[a].split(" - ")[0], names[b].split(" - ")[0]))
    return lanes, E, deg, P, R, B, names, (H, W)


def preview(E, deg, P, R, B, names, shape):
    from PIL import Image, ImageDraw
    H, W = shape
    img = Image.new("RGB", (W // 2, H // 2), (10, 14, 22))
    d = ImageDraw.Draw(img)
    for a, b in E:
        u = (P[b] - P[a]) / np.linalg.norm(P[b] - P[a])
        d.line([tuple((P[a] + u * R[a]) / 2), tuple((P[b] - u * R[b]) / 2)], fill=(90, 170, 230), width=2)
    for i in B:
        x, y = P[i] / 2
        r = R[i] / 2
        d.ellipse([x - r, y - r, x + r, y + r], outline=(200, 200, 160) if deg[i] > 1 else (255, 120, 60))
        d.text((x - 12, y - 4), names[i].split(" - ")[0][:12], fill=(255, 255, 255))
    img.save(PREVIEW)
    print("preview:", PREVIEW)


def write(lanes):
    raw = open(ADJ, encoding="utf-8-sig").read()
    lines = raw.splitlines()
    kept = [l for l in lines if not (l.split(";")[0].isdigit() and len(l.split(";")) > 2 and l.split(";")[2] == "sea")]
    end = kept.index("-1;-1;;-1;-1;-1;-1;-1;-1") if "-1;-1;;-1;-1;-1;-1;-1;-1" in kept else len(kept)
    rows = [f"{a};{b};sea;{t};-1;-1;-1;-1;HOD_lane_{a}_{b};{na} to {nb}" for a, b, t, na, nb in lanes]
    out = kept[:end] + rows + kept[end:]
    open(ADJ, "w", encoding="utf-8").write("\n".join(out))
    print(f"wrote {len(rows)} lanes to {ADJ}")


if __name__ == "__main__":
    os.chdir(ROOT)
    lanes, E, deg, P, R, B, names, shape = build()
    hist = sorted(collections.Counter(deg[i] for i in B).items())
    print(f"{len(B)} planets, {len(E)} links, {len(lanes)} lanes; links per planet: {hist}")
    preview(E, deg, P, R, B, names, shape)
    if len(sys.argv) > 1 and sys.argv[1] == "write":
        write(lanes)
