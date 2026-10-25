"""Space effects placed by planet name, written into gfx/FX/pdxwater.shader between the "space_fx begin/end" markers
(the user, 2026-10-25: rings, asteroid belts, hyperspace lane glow, comets, dying-star glow). The shader functions
(PlanetRing, AsteroidBelt, LaneGlow, StarPulse, Comet) are hand-written in the shader; this file only writes the calls
with each planet's centre and radius from WIPGFX/Assets/galaxy_planets.json, so they follow the planets if the map moves.

    python -B "WIPGFX/plans & scripts/space_fx.py"
"""
import json, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SHADER = os.path.join(ROOT, "gfx/FX/pdxwater.shader")
PLANETS = os.path.join(ROOT, "WIPGFX/Assets/galaxy_planets.json")

# planet: (angle rad, tilt = minor/major, tint) - Yavin IV and Endor are moons of ringed gas giants in canon
RINGS = {"Yavin IV": (0.35, 0.38, (0.80, 0.66, 0.48)), "Endor": (-0.25, 0.42, (0.62, 0.70, 0.78)),
         "Iego": (0.15, 0.34, (0.70, 0.60, 0.72)), "Nal Hutta": (-0.40, 0.40, (0.72, 0.70, 0.50)),
         "Saleucami": (0.55, 0.36, (0.78, 0.74, 0.66))}
# asteroid belts (canon: Hoth's belt, Kessel's asteroid fields, Geonosis' asteroid rings): planet: (tilt, tint)
BELTS = {"Hoth": (0.55, (0.62, 0.66, 0.72)), "Kessel": (0.50, (0.66, 0.55, 0.46)), "Geonosis": (0.45, (0.72, 0.52, 0.36))}
# hyperspace routes through the planets on this map (approximate: canon stops that exist here, in canon order)
LANES = {"Perlemian Trade Route": (["Coruscant", "Brentaal IV", "Chandrila", "Corsin", "Ord Cestus", "Ossus", "Lianna",
                                    "Raxus Prime"], (1.00, 0.80, 0.40)),
         "Hydian Way": (["Bonadan", "Corsin", "Brentaal IV", "Esseles", "Empress Teta", "Abregado-Rae", "Thyferria",
                         "Eriadu", "Terminus"], (0.40, 0.85, 1.00)),
         "Corellian Run": (["Coruscant", "Corellia", "Malastare", "Christophsis", "Ryloth"], (1.00, 0.45, 0.30)),
         "Rimma Trade Route": (["Abregado-Rae", "Thyferria", "Yag'Dhul", "Sullust", "Eriadu"], (0.50, 1.00, 0.55))}
# dying / unstable stars glowing behind a planet: planet: (tint, pulse period s)
STARS = {"Mustafar": ((1.00, 0.30, 0.10), 6.0)}


def f(v):
    return f"{v:.2f}f"


def v3(c):
    return f"float3( {f(c[0])}, {f(c[1])}, {f(c[2])} )"


def calls():
    ps = json.load(open(PLANETS, encoding="utf-8"))
    near, far = [], []          # near: drawn at every zoom (rings, belts); far: zoomed-out only (lanes, star glow)
    for p, (a, t, c) in RINGS.items():
        x, z, r = ps[p]
        near.append(f"vColor = ApplyRing( vColor, PlanetRing( vPos, float2( {f(x)}, {f(z)} ), {f(r)}, {f(a)}, {f(t)}, {v3(c)} ) );   // {p}")
    for p, (t, c) in BELTS.items():
        x, z, r = ps[p]
        near.append(f"vColor = ApplyRing( vColor, AsteroidBelt( vPos, float2( {f(x)}, {f(z)} ), {f(r)}, {f(t)}, {v3(c)}, vStarSize ) );   // {p}")
    for name, (stops, c) in LANES.items():
        for a, b in zip(stops, stops[1:]):
            (xa, za, _), (xb, zb, _) = ps[a], ps[b]
            far.append(f"vLane += {v3(c)} * LaneGlow( vPos, float2( {f(xa)}, {f(za)} ), float2( {f(xb)}, {f(zb)} ), vTime );   // {name}: {a} - {b}")
    for p, (c, per) in STARS.items():
        x, z, r = ps[p]
        far.append(f"vLane += {v3(c)} * StarPulse( vPos, float2( {f(x)}, {f(z)} ), {f(r)}, vTime, {f(per)} );   // {p}")
    return near, far


def main():
    near, far = calls()
    t = open(SHADER, encoding="utf-8").read()
    for tag, lines in (("near", near), ("far", far)):
        pat = re.compile(rf"(// space_fx {tag} begin[^\n]*\n)(.*?)(\s*// space_fx {tag} end)", re.S)
        m = pat.search(t)
        assert m, f"markers for {tag} missing in {SHADER}"
        indent = re.match(r"[\t ]*", t[t.rfind("\n", 0, m.start()) + 1:]).group(0)
        t = t[:m.start(2)] + "".join(indent + l + "\n" for l in lines).rstrip("\n") + t[m.end(2):]
    open(SHADER, "w", encoding="utf-8").write(t)
    print(f"{SHADER}: {len(near)} near calls, {len(far)} far calls")


if __name__ == "__main__":
    main()
