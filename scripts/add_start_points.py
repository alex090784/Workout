#!/usr/bin/env python3
"""Add a Google Maps trailhead/start-point link to every non-race Run session that has a route.
Keyed on the route URL so the start point always matches the displayed route. Updates BQ
(start_point_name / start_coords / start_point_url + description line) and re-pushes to
intervals.icu. Idempotent: strips/replaces the 'Start point (drive to):' line on re-run.

Coords are trailhead/parking points (drive-to), accurate to trailhead level.
Run: INTERVALS_API_KEY=... ~/garmin_venv/bin/python3 add_start_points.py [--bq-only|--intervals-only]
"""
import base64, json, os, re, subprocess, sys, urllib.request

# route_url -> (trailhead name, "lat,lon")
ROUTE = {
 # --- Cape Town ---
 "https://www.alltrails.com/trail/south-africa/western-cape/lower-tokai-walk": ("Tokai Forest / Arboretum parking", "-34.0672,18.4245"),
 "https://www.alltrails.com/poi/south-africa/western-cape/cape-town/silvermine-dam": ("Silvermine Gate 1 parking (Ou Kaapse Weg)", "-34.0919,18.4103"),
 "https://www.alltrails.com/poi/south-africa/western-cape/constantiaberg": ("Silvermine Gate 1 parking (Elephant's Eye)", "-34.0919,18.4103"),
 "https://www.alltrails.com/trail/south-africa/western-cape/constantia-nek-to-kirstenbosch-via-contour-path": ("Constantia Nek parking", "-34.0006,18.3855"),
 "https://www.alltrails.com/trail/south-africa/western-cape/signal-hill-circuit": ("Signal Hill upper parking", "-33.9152,18.4030"),
 "https://www.alltrails.com/trail/south-africa/western-cape/tokai-silvermine": ("Tokai Forest / Arboretum parking", "-34.0672,18.4245"),
 "https://www.alltrails.com/poi/south-africa/western-cape/cape-town/table-mountain": ("Table Mountain Lower Cableway parking (Tafelberg Rd)", "-33.9522,18.4033"),
 "https://www.visorando.com/en/walk-lion-s-head-2/": ("Lion's Head trailhead, Signal Hill Rd", "-33.9366,18.3889"),
 "https://www.visorando.com/en/walk-table-mountain-17/": ("Platteklip Gorge trailhead, Tafelberg Rd", "-33.9578,18.4052"),
 # --- Provence (Visorando) ---
 "https://www.visorando.com/en/walk-cavaillon.html": ("Cavaillon / Durance riverside parking", "43.8300,5.0335"),
 "https://www.visorando.com/en/walk-la-colline-saint-jacques/": ("Colline Saint-Jacques trailhead, Cavaillon", "43.8300,5.0335"),
 "https://www.visorando.com/en/walk-la-crete-des-alpilles/": ("Eygalieres / Alpilles trailhead", "43.7560,4.9510"),
 "https://www.visorando.com/en/walk-orgon.html": ("Orgon village parking", "43.7905,5.0435"),
 "https://www.visorando.com/en/walk-le-mourre-negre-par-cucuron/": ("Cucuron - Etang de Cucuron parking", "43.7717,5.4383"),
 # --- Menorca (Wikiloc) ---
 "https://www.wikiloc.com/trails/outdoor/spain/balearic-islands/sant-lluis": ("Sant Lluis town centre", "39.8503,4.2670"),
 "https://www.wikiloc.com/trail-running-trails/menorca-cami-de-cavalls-etapa-6-punta-prima-mahon-14318792": ("Punta Prima (Cami de Cavalls trailhead)", "39.8130,4.2660"),
 "https://www.wikiloc.com/hiking-trails/gr-223-cami-de-cavalls-etapa-2-es-grau-favaritx-151147482": ("Es Grau village parking", "39.9370,4.2665"),
 "https://www.wikiloc.com/trail-running-trails/menorca-cami-de-cavalls-etapa-5-calan-porter-punta-prima-14307423": ("Cala'n Porter (Cami de Cavalls trailhead)", "39.8720,4.1330"),
 "https://www.wikiloc.com/hiking-trails/menorca-es-mercadal-monte-toro-13979275": ("Es Mercadal (Monte Toro road base)", "39.9910,4.0913"),
 "https://es.wikiloc.com/rutas-senderismo/menorca-cami-de-cavalls-1a-etapa-mao-cap-de-favaritx-37077334": ("Mao (Mahon) port", "39.8885,4.2645"),
}
def maps(coords): return f"https://www.google.com/maps/search/?api=1&query={coords}"

TABLE = "alexct-training.garmin_training.training_plan"
BASE = "https://intervals.icu/api/v1"
STRIP = re.compile(r"\s*Start point \(drive to\):.*\Z", re.S)

def sql_str(s): return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

def update_bq():
    def case(idx):
        lines = []
        for url, (name, coords) in ROUTE.items():
            val = {0: name, 1: coords, 2: maps(coords)}[idx]
            lines.append(f"WHEN route_url = {sql_str(url)} THEN {sql_str(val)}")
        return "CASE " + " ".join(lines) + " ELSE NULL END"
    name_c, coords_c, url_c = case(0), case(1), case(2)
    sql = f"""
UPDATE `{TABLE}` SET
  start_point_name = {name_c},
  start_coords = {coords_c},
  start_point_url = {url_c},
  description = CONCAT(
    REGEXP_REPLACE(IFNULL(description,''), r' *Start point \\(drive to\\):.*$', ''),
    '  Start point (drive to): ', {name_c}, ' — ', {url_c})
WHERE plan_date >= '2026-07-08' AND route_url IN ({",".join(sql_str(u) for u in ROUTE)});
"""
    subprocess.run(["bq", "query", "--use_legacy_sql=false", "--format=csv", sql],
                   check=True, capture_output=True, text=True)
    print("BQ: start-point columns + description updated for all mapped routes.")

def api(method, path, key, body=None):
    auth = base64.b64encode(f"API_KEY:{key}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "aria-garmin-coach/1.0")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "null")

def update_intervals(key):
    events = api("GET", "/athlete/0/events?oldest=2026-07-08&newest=2026-11-21", key)
    per = {"cape": 0, "prov": 0, "meno": 0}
    updated = nomatch = 0
    for e in events:
        if e.get("category") != "WORKOUT" or e.get("type") != "Run":
            continue
        desc = e.get("description") or ""
        m = re.search(r"Suggested route:.*?—\s*(https?://\S+)", desc)
        if not m:
            continue
        url = m.group(1).strip()
        if url not in ROUTE:
            nomatch += 1
            print(f"  [no coord] {(e.get('start_date_local') or '')[:10]} {url}")
            continue
        name, coords = ROUTE[url]
        base = STRIP.sub("", desc).rstrip()
        new = base + f"\nStart point (drive to): {name} — {maps(coords)}"
        api("PUT", f"/athlete/0/events/{e['id']}", key, {"description": new})
        bucket = "prov" if "visorando" in url and coords.startswith("43") else \
                 "meno" if "wikiloc" in url else "cape"
        per[bucket] += 1
        updated += 1
    print(f"\nintervals.icu updated={updated} (Cape Town={per['cape']} Provence={per['prov']} Menorca={per['meno']}) no-coord={nomatch}")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode != "--intervals-only":
        update_bq()
    if mode != "--bq-only":
        key = os.environ.get("INTERVALS_API_KEY")
        if not key:
            sys.exit("ERROR: INTERVALS_API_KEY not set")
        update_intervals(key)
