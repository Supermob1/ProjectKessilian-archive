"""Space strategic regions redrawn as the canon sectors (the user, 2026-10-25: "in line with all the new planets and the
canon star wars sectors, not the colonies/core things but the real sector map").

    python -B "WIPGFX/plans & scripts/space_sectors.py" plan     report + WIPGFX/Assets/space_sectors_preview.png
    python -B "WIPGFX/plans & scripts/space_sectors.py" write    rewrites the space regions in map/strategicregions,
                                                                 their names in strategic_region_names_l_english.yml
                                                                 and their weather points in map/weatherpositions.txt
    python -B "WIPGFX/plans & scripts/space_sectors.py" labels   bakes the sector names faintly into the galaxy chart

Each planet's sector comes from its Wookieepedia infobox (cached in WIPGFX/research/<planet>/facts.json by
research_planet.py), with SECTOR_FIX for the planets whose infobox has none. Every space (sea) province goes to the
sector of the nearest planet in the same galaxy chart region (Deep Core, Core Worlds...; distance to the planet's edge); a sector split in pieces keeps its biggest piece and the
other pieces join the neighbour they touch most. Planet (land) regions and their ids are not touched.
"""
import collections, glob, json, math, os, re, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REG_DIR = os.path.join(ROOT, "map/strategicregions")
LOC = os.path.join(ROOT, "localisation/english/strategic_region_names_l_english.yml")
WEATHER = os.path.join(ROOT, "map/weatherpositions.txt")
PREVIEW = os.path.join(ROOT, "WIPGFX/Assets/space_sectors_preview.png")

# planet (localised name) -> research folder, where the slug differs
FOLDER = {"Falleen": "falleen_planet", "Shola": "shola_system", "Ciutric": "ciutric_iv", "Ord Trasi": "ord_trasi_system",
          "Telos": "telos_iv", "Mechis": "mechis_iii", "Mon Calamari": "mon_cala", "Yavin IV": "yavin_4",
          "Thyferria": "thyferra", "Rendilli": "rendili", "Lehon": "rakata_prime"}
# infobox has no sector (or a wrong one for this mod): the canon area instead; None = no canon sector known, the
# planet's space joins its neighbours'
SECTOR_FIX = {"Nal Hutta": "Hutt Space", "Nar Shaddaa": "Hutt Space", "Toydaria": "Hutt Space", "Nimban": "Hutt Space",
              "Quesh": "Hutt Space", "Byss": "Deep Core", "Foerost": "Deep Core", "Lehon": "Unknown Regions",
              "Drongar": None, "Abafar": "Sprizen sector", "Anoat": "Anoat sector", "Belsavis": "Ninth Quadrant",
              "Bothawui": "Bothan Space", "Wild Space": None, "Korriban": "Esstran sector", "Florrum": "Sertar sector"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def sector_of(planet):
    if planet in SECTOR_FIX:
        return SECTOR_FIX[planet]
    f = os.path.join(ROOT, "WIPGFX/research", FOLDER.get(planet, slug(planet)), "facts.json")
    if not os.path.exists(f):
        return None
    hits = [x for x in re.findall(r'sector: ([^"\\]+?)(?:\\n|"|,|;| \()', open(f, encoding="utf-8").read())
            if x not in ("None", "N/A")]
    return collections.Counter(hits).most_common(1)[0][0] if hits else None


def title(s):
    return s[0].upper() + s[1:].replace(" sector", " Sector")


def load():
    import planet_terrain_gen as g
    import galaxy_regions as gr
    land, _, pid = g.load_provinces()
    H = land.shape[0]
    sea = ~land
    n = int(pid.max()) + 1
    ys, xs = np.nonzero(sea)
    ids = pid[ys, xs]
    cnt = np.bincount(ids, minlength=n)
    cx = np.bincount(ids, xs, n) / np.maximum(cnt, 1)
    cz = H - 1 - np.bincount(ids, ys, n) / np.maximum(cnt, 1)
    seas = sorted(int(i) for i in np.nonzero(cnt)[0] if i > 0)
    adj = collections.Counter()                     # sea-sea shared border length
    for a, b in ((pid[:, :-1], pid[:, 1:]), (pid[:-1, :], pid[1:, :])):
        m = (a != b) & np.isin(a, seas) & np.isin(b, seas)
        for p, q in zip(a[m].tolist(), b[m].tolist()):
            adj[(min(p, q), max(p, q))] += 1
    region = np.load(gr.REGION_NPY).repeat(2, 0).repeat(2, 1)[:H, :pid.shape[1]]   # galaxy chart region per pixel
    sea_reg = {i: int(np.bincount(region[pid == i]).argmax()) for i in seas}
    ps = gr.planets()
    p_reg = {p: int(region[int(round(H - 1 - z)), int(round(x))]) for p, (x, z, r) in ps.items()}
    return ps, seas, {i: (cx[i], cz[i]) for i in seas}, adj, pid, sea, H, sea_reg, p_reg


def assign(planets, seas, cen, adj, sea_reg, p_reg):
    sec = {p: sector_of(p) for p in planets}
    named = [(p, xz) for p, xz in planets.items() if sec[p]]
    group = {}
    for i in seas:
        x, z = cen[i]
        same = [t for t in named if p_reg[t[0]] == sea_reg[i]] or named   # a sector stays inside its galaxy region
        p = min(same, key=lambda t: math.hypot(x - t[1][0], z - t[1][1]) - t[1][2])[0]
        group[i] = title(sec[p])
    nb = collections.defaultdict(collections.Counter)
    for (p, q), w in adj.items():
        nb[p][q] += w
        nb[q][p] += w
    lost = {title(s) for s in sec.values() if s} - set(group.values())
    for name in sorted(lost):                        # a sector squeezed out by its neighbours keeps the province nearest it
        mine = [xz for p, xz in planets.items() if sec[p] and title(sec[p]) == name]
        size = collections.Counter(group.values())
        cand = [i for i in seas if size[group[i]] > 1]
        i = min(cand, key=lambda i: min(math.hypot(cen[i][0] - x, cen[i][1] - z) - r for x, z, r in mine))
        group[i] = name
    changed = True
    while changed:                                   # stray pieces of a sector join the neighbour they touch most
        changed = False
        for name in sorted(set(group.values())):
            todo, comps = {i for i in seas if group[i] == name}, []
            while todo:
                stack, comp = [todo.pop()], set()
                while stack:
                    i = stack.pop()
                    comp.add(i)
                    for j in nb[i]:
                        if j in todo:
                            todo.discard(j)
                            stack.append(j)
                comps.append(comp)
            for comp in sorted(comps, key=len)[:-1]:
                border = collections.Counter()
                for i in comp:
                    for j, w in nb[i].items():
                        if j not in comp:
                            border[group[j]] += w
                if border:
                    for i in comp:
                        group[i] = border.most_common(1)[0][0]
                    changed = True
    return group, sec


def regions():
    """{id: (path, text, provinces)}"""
    out = {}
    for f in glob.glob(os.path.join(REG_DIR, "*.txt")):
        t = open(f, encoding="utf-8-sig", errors="ignore").read()
        rid = int(re.search(r"\bid\s*=\s*(\d+)", t).group(1))
        out[rid] = (f, t, [int(q) for q in re.search(r"provinces\s*=\s*\{([^}]*)\}", t).group(1).split()])
    return out


def plan(write_preview=True):
    planets, seas, cen, adj, pid, sea, H, sea_reg, p_reg = load()
    group, sec = assign(planets, seas, cen, adj, sea_reg, p_reg)
    names = sorted(set(group.values()))
    print(f"{len(seas)} space provinces -> {len(names)} sector regions")
    for nm in names:
        members = [p for p in planets if sec[p] and title(sec[p]) == nm]
        print(f"  {nm:28s} {sum(group[i] == nm for i in seas):3d} provinces  planets: {', '.join(members) or '-'}")
    lost = sorted({title(s) for s in sec.values() if s} - set(names))
    print("sectors with no space of their own (absorbed by neighbours):", ", ".join(lost) or "-")
    print("planets with no canon sector:", ", ".join(p for p in planets if not sec[p]))
    if write_preview:
        from PIL import Image, ImageDraw
        rng = np.random.RandomState(3)
        col = {nm: rng.randint(60, 230, 3) for nm in names}
        lut = np.zeros((int(pid.max()) + 1, 3), np.uint8)
        for i in seas:
            lut[i] = col[group[i]]
        img = np.where(sea[..., None], lut[pid], 25).astype(np.uint8)
        im = Image.fromarray(img).resize((pid.shape[1] // 2, pid.shape[0] // 2), Image.NEAREST)
        d = ImageDraw.Draw(im)
        for nm in names:
            pts = [cen[i] for i in seas if group[i] == nm]
            x, z = np.mean(pts, axis=0)
            d.text((x / 2 - 3 * len(nm), (H - 1 - z) / 2), nm, fill=(255, 255, 255))
        im.save(PREVIEW)
        print("preview:", PREVIEW)
    return group, cen, H


def write():
    group, cen, H = plan(write_preview=True)
    regs = regions()
    seas = set(group)
    template = None
    sea_only = []
    for rid, (f, t, provs) in sorted(regs.items()):
        if provs and all(p in seas for p in provs):
            sea_only.append(rid)
            template = template or t
            os.remove(f)
        elif any(p in seas for p in provs):         # mixed region: keep its land, its space goes to a sector
            keep = [p for p in provs if p not in seas]
            t = re.sub(r"provinces\s*=\s*\{[^}]*\}", "provinces={\n\t\t" + " ".join(map(str, keep)) + " \n\t}", t, count=1)
            open(f, "w", encoding="utf-8").write(t)
    names = sorted(set(group.values()))
    free = sorted(sea_only) + list(range(max(regs) + 1, max(regs) + 1 + len(names)))
    loc = open(LOC, encoding="utf-8-sig").read()
    weather = [l for l in open(WEATHER).read().splitlines() if l.strip()]
    used = {}
    for nm, rid in zip(names, free):
        used[rid] = nm
        provs = sorted(i for i in group if group[i] == nm)
        body = re.sub(r"\bid\s*=\s*\d+", f"id={rid}", template, count=1)
        body = re.sub(r'name\s*=\s*"[^"]*"', f'name="STRATEGICREGION_{rid}"', body, count=1)
        body = re.sub(r"provinces\s*=\s*\{[^}]*\}", "provinces={\n\t\t" + " ".join(map(str, provs)) + " \n\t}", body, count=1)
        fn = re.sub(r'[\\/:*?"<>|]', "", nm)
        open(os.path.join(REG_DIR, f"{rid}-{fn}.txt"), "w", encoding="utf-8").write(body)
        line = f' STRATEGICREGION_{rid}:0 "{nm}"'
        if re.search(rf"^\s*STRATEGICREGION_{rid}:", loc, re.M):
            loc = re.sub(rf"^\s*STRATEGICREGION_{rid}:.*$", line, loc, count=1, flags=re.M)
        else:
            loc = loc.rstrip("\n") + "\n" + line + "\n"
        x, z = np.mean([cen[i] for i in provs], axis=0)
        weather = [l for l in weather if l.split(";")[0] != str(rid)]
        weather.append(f"{rid};{x:.2f};9.50;{z:.2f};big")
    for rid in sea_only:                             # ids no longer used
        if rid not in used:
            loc = re.sub(rf"^\s*STRATEGICREGION_{rid}:.*\n", "", loc, flags=re.M)
            weather = [l for l in weather if l.split(";")[0] != str(rid)]
    open(LOC, "w", encoding="utf-8-sig").write(loc)
    open(WEATHER, "w").write("\n".join(weather) + "\n")
    print(f"wrote {len(names)} sector regions (ids {min(used)}..{max(used)}); removed {len(set(sea_only) - set(used))} old ids")


def labels():
    """the sector names, small and faint, baked into the galaxy chart (alpha of map/terrain/ice_diffuse.dds) at the
    roomiest spot of each sector's space, away from planets. Drawn over CHART_BASE, the chart without sector names
    (saved on the first run; galaxy_regions.py chart deletes it when it redraws the chart)"""
    from PIL import Image, ImageDraw, ImageFont
    from scipy import ndimage as ndi
    import galaxy_regions as gr
    import planet_terrain_gen as g
    base_path = os.path.join(ROOT, "WIPGFX/Assets/galaxy_chart_alpha_base.npy")
    if not os.path.exists(base_path):
        np.save(base_path, np.load(gr.CHART_NPY))
    base = np.load(base_path).astype(np.float32) / 255.0
    h, w = base.shape
    land, _, pid = g.load_provinces()
    loc = dict(re.findall(r'^\s*STRATEGICREGION_(\d+):\d*\s*"([^"]*)"', open(LOC, encoding="utf-8-sig").read(), re.M))
    reg = np.zeros(int(pid.max()) + 1, np.int32)
    for rid, (f, t, provs) in regions().items():
        reg[provs] = rid
    R = np.where(land, 0, reg[pid])[::2, ::2][:h, :w]                 # half res, like the chart
    font = None
    for name in ("DejaVuSans.ttf", "arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(name, 11)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    text = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(text)
    region_text = ndi.binary_dilation(base - ndi.gaussian_filter(base, 3.0) > 0.08, iterations=12)   # the region names
    room = ndi.distance_transform_edt(~(ndi.binary_dilation(land[::2, ::2][:h, :w], iterations=10) | region_text))
    n = 0
    for rid in np.unique(R[R > 0]).tolist():
        nm = loc.get(str(rid), "")
        if not nm or nm in gr.RINGS + gr.OTHER or rid not in reg[np.unique(pid[~land])]:   # same name as its region
            continue
        m = R == rid
        inner = ndi.distance_transform_edt(m) * np.minimum(room, 60)   # deep inside the sector and clear of planets
        y, x = np.unravel_index(inner.argmax(), inner.shape)
        label = nm.upper()
        x0, y0, x1, y1 = d.textbbox((0, 0), label, font=font)
        d.text((x - (x1 - x0) / 2, y - (y1 - y0) / 2), label, fill=255, font=font)
        n += 1
    a = np.clip(base + np.asarray(text, np.float32) / 255.0 * 0.22, 0, 1)    # added, so it shows on bright fills too
    gr.inject(os.path.join(ROOT, "map/terrain/ice_diffuse.dds"), a)
    Image.fromarray((a * 255).astype(np.uint8)).save(os.path.join(ROOT, "WIPGFX/Assets/galaxy_chart_sectors_preview.png"))
    print(f"labels: {n} sector names baked into the chart")


if __name__ == "__main__":
    os.chdir(ROOT)
    {"plan": plan, "write": write, "labels": labels}[sys.argv[1] if len(sys.argv) > 1 else "plan"]()
