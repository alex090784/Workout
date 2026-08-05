"""Fetch Visorando route geometry (public GeoJSON endpoint), build GPX, upload as Garmin courses."""
import json, math, re, time, urllib.request, os, sys
os.makedirs("/tmp/visorando_gpx", exist_ok=True)

SCRATCH = "/tmp/visorando_gpx"  # output dir for GPX files; created if missing
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
      "Accept-Language": "fr,en;q=0.8"}

ROUTES = [
    # key, page_url, garmin course name
    ("blauzac",  "https://www.visorando.com/en/walk-les-capitelles-de-blauzac/",           "Aug 5 Threshold - Capitelles de Blauzac"),
    ("pontstnic","https://www.visorando.com/randonnee-boucle-du-pont-saint-nicolas/",      "Aug 7 Double Vertical - Pont St-Nicolas"),
    ("seynes",   "https://www.visorando.com/en/walk-le-mont-bouquet-au-depart-de-seynes/", "Aug 9 Long Run P1 - Mont Bouquet (Seynes)"),
    ("brouzet",  "https://www.visorando.com/en/walk-mont-bouquet-par-bouzet-les-ales/",    "Aug 9 Long Run P2 - Mont Bouquet (Brouzet)"),
    ("ermitage", "https://www.visorando.com/en/walk-vallon-de-l-ermitage-de-collias-et-crete/", "Aug 10 Easy - Ermitage de Collias"),
    ("chapelle", "https://www.visorando.com/en/walk-la-chapelle-et-grotte-de-la-baume-a-part/", "Aug 12 Prologue TT - Chapelle-Baume Sanilhac"),
]

def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))

def build_gpx(key, page_url, name):
    html = get(page_url).decode("utf-8", "replace")
    m = re.search(r"idRandonnee=(\d+)", html)
    if not m:
        raise RuntimeError(f"no idRandonnee on {page_url}")
    rid = m.group(1)
    gj = json.loads(get(f"https://www.visorando.com/en/index.php?component=exportData&task=getRandoGeoJson&chartData=1&wholePointsData=1&idRandonnee={rid}"))
    pts = [f["geometry"]["coordinates"] for f in gj["geojson"]["features"] if f["geometry"]["type"] == "Point"]
    chart = gj.get("chartdata") or {}
    prof = chart.get("data") or []  # [ [km, ele_m], ... ]
    # cumulative distance per point (km)
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + haversine(pts[i-1][1], pts[i-1][0], pts[i][1], pts[i][0]) / 1000.0)
    total_km = cum[-1]
    # interpolate elevation from profile by distance
    def ele_at(km):
        if not prof:
            return None
        if km <= prof[0][0]: return prof[0][1]
        for j in range(1, len(prof)):
            if km <= prof[j][0]:
                d0, e0 = prof[j-1]; d1, e1 = prof[j]
                if d1 == d0: return e1
                return e0 + (e1 - e0) * (km - d0) / (d1 - d0)
        return prof[-1][1]
    # ascent from profile
    asc = sum(max(0, prof[j][1]-prof[j-1][1]) for j in range(1, len(prof))) if prof else None
    trkpts = []
    for (lon, lat), km in zip(pts, cum):
        e = ele_at(km)
        ele_tag = f"<ele>{e:.1f}</ele>" if e is not None else ""
        trkpts.append(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}">{ele_tag}</trkpt>')
    gpx = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<gpx version="1.1" creator="Visorando (route n.{rid})" xmlns="http://www.topografix.com/GPX/1/1">\n'
           f'<metadata><name>{name}</name><desc>Source: {page_url}</desc></metadata>\n'
           f'<trk><name>{name}</name><trkseg>\n' + "\n".join(trkpts) +
           f'\n</trkseg></trk></gpx>\n')
    path = f"{SCRATCH}/{key}.gpx"
    with open(path, "w") as f:
        f.write(gpx)
    print(f"{key}: rando {rid}, {len(pts)} pts, {total_km:.2f} km, ascent~{asc} m -> {path}")
    return path, rid, total_km, asc

def upload_course(path, name):
    import garth
    with open(path, "rb") as f:
        data = f.read()
    r = garth.client.post("connectapi", "course-service/course/import",
                          files={"file": (os.path.basename(path), data, "application/gpx+xml")}, api=True)
    course = r.json()
    course["courseName"] = name
    course["activityType"] = {"typeId": 6, "typeKey": "trail_running"}
    course["activityTypePk"] = 6
    course["rulePK"] = 2
    course["coursePrivacy"] = {"privacyRulePk": 2}
    course["sourceTypeId"] = 3
    course["startPoint"] = dict(course["geoPoints"][0])
    r2 = garth.client.post("connectapi", "course-service/course", json=course, api=True)
    saved = r2.json()
    print(f"SAVED course {saved.get('courseId')} | {saved.get('courseName')} | "
          f"{(saved.get('distanceMeter') or 0)/1000:.2f} km | {saved.get('elevationGainMeter')} m+")
    return saved.get("courseId")

if __name__ == "__main__":
    do_upload = "--upload" in sys.argv
    if do_upload:
        import garth
        garth.resume("/Users/alexct/.garth")
    res_path = f"{SCRATCH}/course_results.json"
    results = json.load(open(res_path)) if os.path.exists(res_path) else {}
    for key, url, name in ROUTES:
        if results.get(key, {}).get("course_id"):
            print(f"{key}: already uploaded as {results[key]['course_id']}, skipping")
            continue
        try:
            path, rid, km, asc = build_gpx(key, url, name)
            cid = upload_course(path, name) if do_upload else None
            results[key] = {"rando_id": rid, "km": round(km, 2), "ascent": asc, "gpx": path,
                            "course_id": cid, "url": url, "name": name}
            with open(res_path, "w") as f:
                json.dump(results, f, indent=1)
            time.sleep(2)
        except Exception as e:
            print(f"{key} FAILED: {str(e)[:200]}")
    print(json.dumps({k: {kk: v[kk] for kk in ('course_id','km','ascent')} for k, v in results.items()}, indent=1))
