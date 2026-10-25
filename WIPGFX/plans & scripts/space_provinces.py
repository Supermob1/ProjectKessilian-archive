"""Space (sea) provinces redrawn smooth and fitted to the galaxy chart (the user, 2026-10-25: "redraw the space
provinces too so they both look smooth and also fit with the galactic map (colonies core etc)").

    python -B "WIPGFX/plans & scripts/space_provinces.py" preview   WIPGFX/Assets/space_provinces_preview.png only
    python -B "WIPGFX/plans & scripts/space_provinces.py" write     map/provinces.bmp + sea lines of map/unitstacks.txt
                                                                    (then run space_sectors.py write)

Province ids, colours and count stay the same. Three layers:
- shore band: sea within BAND px of land keeps its old province, so every land-sea adjacency (naval bases, coastal
  flags, hyperspace lanes) is unchanged;
- orbit: sea within ORBIT px of a planet, in the planet's chart region, goes to the nearest shore-band province
  (a planet's orbital provinces, with smooth medial borders and a round outer edge);
- deep space: the rest is cut into the old open-space provinces, shared out between the chart regions (Deep Core,
  Core Worlds, Colonies...; galaxy_regions.py, WIPGFX/Assets/galaxy_region_labels.npy) by area, as relaxed Voronoi
  cells inside each region, so their borders are straight or follow the region lines.
Slivers and stray pieces join the neighbour they touch most. Needs galaxy_regions.py chart run first.
"""
import collections, math, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REGION_NPY = os.path.join(ROOT, "WIPGFX/Assets/galaxy_region_labels.npy")
PREVIEW = os.path.join(ROOT, "WIPGFX/Assets/space_provinces_preview.png")
BAND = 6            # px of shore kept as is
ORBIT = 45          # px from land that a planet's orbital provinces reach
MIN_PIECE = 2500    # px: smaller deep-space pieces join a neighbour
LLOYD = 8           # relaxation rounds for the deep-space cells


def adjacency(lab, valid):
    """Counter {(a, b): shared border px} between labels where both sides are valid"""
    out = collections.Counter()
    for a, b, va, vb in ((lab[:, :-1], lab[:, 1:], valid[:, :-1], valid[:, 1:]), (lab[:-1], lab[1:], valid[:-1], valid[1:])):
        m = (a != b) & va & vb
        if m.any():
            pairs, n = np.unique(np.stack([np.minimum(a[m], b[m]), np.maximum(a[m], b[m])]), axis=1, return_counts=True)
            out.update({(int(p), int(q)): int(c) for (p, q), c in zip(pairs.T, n)})
    return out


def merge_pieces(lab, sea, keep_min, fixed):
    """every province one piece: its smaller pieces join the neighbour they touch most. Shore-band fragments move too
    (the naval base spawns that pointed at them are re-pointed by fix_spawns); `fixed` is unused, kept for callers"""
    for _round in range(6):
        moved = 0
        for p in np.unique(lab[sea]).tolist():
            m = (lab == p) & sea
            cc, n = ndi.label(m)
            if n <= 1:
                continue
            sizes = ndi.sum(m, cc, range(1, n + 1))
            main = int(np.argmax(sizes)) + 1
            for c in range(1, n + 1):
                if c == main:
                    continue
                piece = cc == c
                if not piece.any():
                    continue
                ring = ndi.binary_dilation(piece, iterations=1) & ~piece & sea & (lab != p)
                if ring.any():
                    lab[piece] = np.bincount(lab[ring]).argmax()
                    moved += 1
        if not moved:
            break
    return lab


def build():
    import planet_terrain_gen as g
    land, _, pid = g.load_provinces()
    H, W = land.shape
    sea = ~land
    region = np.load(REGION_NPY).repeat(2, 0).repeat(2, 1)[:H, :W]
    seas = np.unique(pid[sea])
    shore1 = sea & ndi.binary_dilation(land)                       # sea px touching land
    coastal = set(np.unique(pid[shore1]).tolist())
    dist_land, (iy, ix) = ndi.distance_transform_edt(sea, return_indices=True)
    land_region = region[iy, ix]                                   # chart region of the nearest planet

    lab = np.zeros_like(pid)
    shore = sea & (dist_land <= BAND) & np.isin(pid, list(coastal))
    lab[shore] = pid[shore]
    orbit = sea & ~shore & (dist_land <= ORBIT) & (region == land_region)
    _, (sy, sx) = ndi.distance_transform_edt(~shore, return_indices=True)
    lab[orbit] = lab[sy[orbit], sx[orbit]]

    deep = sea & (lab == 0)
    opens = [int(q) for q in seas if q not in coastal]
    # share the open provinces out between the chart regions by deep-space area (at least one per region with room)
    area = collections.Counter(region[deep].tolist())
    rids = [r for r, a in area.items() if a >= MIN_PIECE]
    quota = {r: max(1, round(len(opens) * area[r] / sum(area[r] for r in rids))) for r in rids}
    while sum(quota.values()) > len(opens):
        quota[max((r for r in quota if quota[r] > 1), key=lambda r: quota[r] / area[r])] -= 1
    while sum(quota.values()) < len(opens):
        quota[min(quota, key=lambda r: quota[r] / area[r])] += 1
    old_c = {q: np.argwhere(pid == q).mean(0) for q in opens}       # (row, col) of the old province
    rng = np.random.RandomState(1977)
    free = list(opens)
    for r in sorted((r for r in rids if quota[r]), key=lambda r: quota[r]):   # small regions pick first: the ids nearest them
        pts = np.argwhere(deep & (region == r))
        sub = pts[::17]
        seeds = sub[rng.choice(len(sub), quota[r], replace=False)].astype(float)
        tree = cKDTree(sub)
        for _ in range(LLOYD):                                       # Lloyd relaxation inside the region
            _, k = cKDTree(seeds).query(sub)
            seeds = np.array([sub[k == i].mean(0) if (k == i).any() else seeds[i] for i in range(len(seeds))])
        _, k = cKDTree(seeds).query(pts)
        cen = [pts[k == i].mean(0) for i in range(len(seeds))]
        for i, c in enumerate(cen):                                  # keep ids near where they were
            q = min(free, key=lambda q: np.hypot(*(old_c[q] - c)))
            free.remove(q)
            lab[pts[k == i, 0], pts[k == i, 1]] = q
    rest = sea & (lab == 0)                                          # regions too small for a province of their own
    if rest.any():
        _, (ry, rx) = ndi.distance_transform_edt(lab == 0, return_indices=True)
        lab[rest] = lab[ry[rest], rx[rest]]
    lab = merge_pieces(lab, sea, MIN_PIECE, shore)
    lab[land] = pid[land]
    missing = sorted(set(seas.tolist()) - set(np.unique(lab[sea]).tolist()))
    assert not missing, f"provinces left without pixels: {missing[:10]}"
    return lab, pid, land, region, coastal


def preview(lab, land, region):
    rng = np.random.RandomState(2)
    lut = rng.randint(50, 230, (int(lab.max()) + 1, 3)).astype(np.uint8)
    img = np.where(land[..., None], 15, lut[lab]).astype(np.uint8)
    edge = np.zeros(lab.shape, bool)
    edge[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    edge[1:] |= lab[1:] != lab[:-1]
    redge = np.zeros(lab.shape, bool)
    redge[:, 1:] |= region[:, 1:] != region[:, :-1]
    redge[1:] |= region[1:] != region[:-1]
    img[edge & ~land] = 255
    img[ndi.binary_dilation(redge, iterations=2) & ~land] = (255, 220, 60)
    Image.fromarray(img).resize((lab.shape[1] // 2, lab.shape[0] // 2), Image.NEAREST).save(PREVIEW)
    print("preview:", PREVIEW)


def unitstacks(lab, land, pid_old):
    """sea lines of map/unitstacks.txt rebuilt in the vanilla layout: 0/21 at the province's inner point, 1-8 and
    22-29 toward each neighbour (most border first), 11-18 / 30-37 further out, 9/10/38 to the west and east"""
    import planet_terrain_gen as g
    H = lab.shape[0]
    h = np.array(Image.open(os.path.join(ROOT, "map/heightmap.bmp")).convert("L"), np.float32)
    sea = ~land
    adj = adjacency(lab, np.ones_like(sea))
    nb = collections.defaultdict(list)
    for (a, b), n in adj.items():
        nb[a].append((n, b))
        nb[b].append((n, a))
    path = os.path.join(ROOT, "map/unitstacks.txt")
    lines = open(path, encoding="utf-8-sig", newline="").read().splitlines(keepends=True)
    seas = set(np.unique(lab[sea]).tolist())
    scale = {}
    keep = []
    for line in lines:
        q = line.split(";")
        if q[0].isdigit() and int(q[0]) in seas:
            scale.setdefault(int(q[0]), q[6].strip())
        else:
            keep.append(line)
    eol = "\r\n" if lines[0].endswith("\r\n") else "\n"
    objs = ndi.find_objects(lab)
    cen_all = {}
    out = []
    for p in sorted(seas):
        sl = objs[p - 1]
        m = lab[sl] == p
        dt = ndi.distance_transform_edt(np.pad(m, 1))[1:-1, 1:-1]
        r0, c0 = np.unravel_index(dt.argmax(), dt.shape)
        cy, cx = r0 + sl[0].start, c0 + sl[1].start
        cen_all[p] = (cy, cx, float(dt.max()))
    for p in sorted(seas):
        cy, cx, rad = cen_all[p]
        sl = objs[p - 1]
        x0, z0 = float(cx), float(H - 1 - cy)

        def put(t, x, z, rot):
            r_, c_ = min(max(int(round(H - 1 - z)), 0), H - 1), min(max(int(round(x)), 0), lab.shape[1] - 1)
            out.append(f"{p};{t};{x:.2f};{h[r_, c_] / 10:.2f};{z:.2f};{rot:.2f};{scale.get(p, '5.00')}{eol}")

        def rot_to(dx, dz):
            return math.atan(dz / dx) + (math.pi / 2 if dx > 0 else -math.pi / 2) if abs(dx) > 1e-6 else (0.0 if dz < 0 else math.pi)

        put(0, x0, z0, 0.0)
        put(21, x0, z0, 0.0)
        ns = [b for _n, b in sorted(nb[p], reverse=True) if b in seas][:8]
        while len(ns) < 3:
            ns.append(None)
        for k, b in enumerate(ns, 1):
            if b is None:                                            # fewer than 3 neighbours: spread round the centre
                a = 2 * math.pi * k / 3
                dx, dz = math.cos(a), math.sin(a)
            else:
                mb = ndi.binary_dilation(lab[sl] == b, iterations=1) & (lab[sl] == p)
                ys, xs = np.nonzero(mb)
                if len(ys):
                    dx, dz = xs.mean() + sl[1].start - cx, -(ys.mean() + sl[0].start - cy)
                else:
                    by, bx, _ = cen_all.get(b, (cy, cx + 1, 0))
                    dx, dz = bx - cx, -(by - cy)
                n_ = math.hypot(dx, dz) or 1.0
                dx, dz = dx / n_, dz / n_
            rot = rot_to(dx, dz)
            for t, f in ((k, 0.45), (k + 21, 0.45), (k + 10, 0.8), (k + 29, 0.8)):
                put(t, x0 + dx * rad * f, z0 + dz * rad * f, rot)
        put(9, x0 - rad * 0.6, z0, 1.57)
        put(10, x0 + rad * 0.6, z0, -1.57)
        put(38, x0 + rad * 0.6, z0, -1.57)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(keep) + "".join(out))
    print(f"unitstacks: {len(out)} sea lines for {len(seas)} provinces")


def fix_spawns(lab, land, pairs):
    """map/buildings.txt naval_base_spawn: the last column is the sea province the port opens on; where that land-sea
    pair no longer exists, the sea province of the nearest sea pixel to the port"""
    H = lab.shape[0]
    _, (iy, ix) = ndi.distance_transform_edt(land, return_indices=True)
    path = os.path.join(ROOT, "map/buildings.txt")
    out, n = [], 0
    for line in open(path, encoding="utf-8-sig", newline=""):
        body, end = line.rstrip("\r\n"), line[len(line.rstrip("\r\n")):]
        q = body.split(";")
        if len(q) > 6 and q[1] == "naval_base_spawn":
            r, c = min(max(int(round(H - 1 - float(q[4]))), 0), H - 1), min(max(int(round(float(q[2]))), 0), lab.shape[1] - 1)
            L, S = int(lab[r, c]), int(q[6])
            if land[r, c] and (min(L, S), max(L, S)) not in pairs:
                q[6] = str(int(lab[iy[r, c], ix[r, c]]))
                n += 1
        out.append(";".join(q) + end)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(out))
    print(f"buildings: {n} naval base spawns re-pointed")


def write_bmp(lab):
    import csv
    col = {}
    for row in csv.reader(open(os.path.join(ROOT, "map/definition.csv"), encoding="utf-8-sig"), delimiter=";"):
        if len(row) > 3 and row[0].isdigit():
            col[int(row[0])] = (int(row[1]), int(row[2]), int(row[3]))
    lut = np.zeros((int(lab.max()) + 1, 3), np.uint8)
    for i, c in col.items():
        if i <= lab.max():
            lut[i] = c
    Image.fromarray(lut[lab]).save(os.path.join(ROOT, "map/provinces.bmp"))
    print("wrote map/provinces.bmp")


def check(lab, pid_old, land, coastal):
    """every land-sea adjacency kept, every sea province one piece and present"""
    old = adjacency(pid_old, np.ones_like(land))
    new = adjacency(lab, np.ones_like(land))
    isl = np.zeros(int(pid_old.max()) + 1, bool)
    isl[np.unique(pid_old[land])] = True
    lost = [k for k in old if isl[k[0]] != isl[k[1]] and k not in new]
    coast_old = {a if isl[a] else b for a, b in old if isl[a] != isl[b]}
    coast_new = {a if isl[a] else b for a, b in new if isl[a] != isl[b]}
    assert coast_old == coast_new, f"coastal land provinces changed: {sorted(coast_old ^ coast_new)[:10]}"
    objs = ndi.find_objects(lab)
    split = [p for p in np.unique(lab[~land]).tolist() if ndi.label(lab[objs[p - 1]] == p)[1] > 1]
    print(f"check: every coastal land province still coastal; {len(lost)} of "
          f"{sum(isl[a] != isl[b] for a, b in old)} land-sea pairs moved to a neighbour; split sea provinces: {split or 'none'}")
    return {k for k in new if isl[k[0]] != isl[k[1]]}


if __name__ == "__main__":
    os.chdir(ROOT)
    lab, pid, land, region, coastal = build()
    preview(lab, land, region)
    pairs = check(lab, pid, land, coastal)
    if len(sys.argv) > 1 and sys.argv[1] == "write":
        write_bmp(lab)
        unitstacks(lab, land, pid)
        fix_spawns(lab, land, pairs)
