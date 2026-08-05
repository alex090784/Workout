# Cape Town Route Library — session-type → suggested location + link

**Purpose:** Every trail/road running session in Alexis's training plan MUST carry a suggested
run location and a route link. This was a standing convention that silently dropped when the
plan was rebuilt into the structured BigQuery + intervals.icu pipeline (the new `training_plan`
table schema had no route field). This file is the canonical mapping so the links never
disappear again.

**Established:** 2026-07-08 (restored after links went missing in the 2026-06-26 plan rebuild).

## Link sources
- **Visorando** — Alexis's preferred source, but its South Africa coverage is only TWO Cape Town
  routes: Table Mountain (`/en/walk-table-mountain-17/`) and Lion's Head (`/en/walk-lion-s-head-2/`).
  Use these for the iconic steep-climb / stair / VO2 / prologue sessions.
- **AllTrails** — the de-facto Cape Town trail-running source; use for everything Visorando
  doesn't cover (Silvermine, Tokai, Newlands, Constantia contour, Signal Hill, Constantiaberg).

## Where it lives
- BigQuery: `alexct-training.garmin_training.training_plan` — columns **`route_location`** (STRING)
  and **`route_url`** (STRING), added 2026-07-08. The suggested route is also appended to the
  `description` field so it flows through to intervals.icu on the next push and shows in the
  daily-feedback context.
- When (re)generating a plan, populate these two columns for EVERY non-rest, non-strength,
  non-race session using the mapping below. Also re-append to `description`.

## ⚠️ LOCATION AWARENESS — CHECK TRAVEL FIRST (do NOT default to Cape Town)

**Before assigning ANY route, determine where Alexis actually is on each session date.** He travels.
Cape Town is only the default when he is home. Check, in order: this file's travel table below →
Aria memory `domain_aria_fitness.md` "Plan adapted for travel" entries → Sam's travel memory
(`domain_sam_personal.md`) / `MEMORY.md`. Assigning Cape Town routes while he is abroad is a real
error that has happened (2026-07-08) — the itinerary was in memory and was missed.

**Known 2026 travel windows (extend/replace as itinerary updates):**
- **2026-07-03 → 2026-07-18: Provence, France** (Domaine du Golf de Pont Royal, Mallemort). Use **Visorando** (French home turf).
- **2026-07-19 → 2026-07-31: Menorca, Spain** (Sant Lluís / Mahón). Use **Wikiloc** (strong Menorca coverage; Visorando thin there).
- **2026-08-01 → 2026-08-13: Sanilhac-Sagriès (Uzès), Gard, France** — staying at "Les Boissieres", 30700 Sanilhac-Sagriès, on the Gorges du Gardon rim. Use **Visorando**. Route set below. (Itinerary updated 2026-08-04 — the earlier "back in Cape Town 31 Jul" plan changed.)
- **2026-08-14 onward: Cape Town** (home) — use the Cape Town table below.

### Uzès / Sanilhac-Sagriès route set (Visorando) — matches Garmin courses uploaded 2026-08-04
Trailheads ≤ ~11 min drive from Les Boissieres except Mont Bouquet (~35 min, long-run exception).
Terrain reality: garrigue plateau + gorge — max ~430 m sustained climb (Mont Bouquet); gorge loops give 200–400 m.

| Session type | Route (Visorando) | km / D+ | Trailhead (drive) | Link |
|---|---|---|---|---|
| tempo / threshold | Les Capitelles de Blauzac | 12.6 / 156 m | Place du 8 Mai 1945, Blauzac (~7 min) | https://www.visorando.com/en/walk-les-capitelles-de-blauzac/ |
| hill_repeats / double vertical | Boucle du Pont Saint-Nicolas (rim-to-river repeats) | 13.6 / ~360 m | Pont St-Nicolas parking, D979 (~11 min) | https://www.visorando.com/randonnee-boucle-du-pont-saint-nicolas/ |
| long_run | Mont Bouquet double loop: Seynes + Brouzet | 16.7/540 + 10.9/430 | Seynes mairie (~35 min) | https://www.visorando.com/en/walk-le-mont-bouquet-au-depart-de-seynes/ + https://www.visorando.com/en/walk-mont-bouquet-par-bouzet-les-ales/ |
| easy_trail / recovery | Vallon de l'Ermitage de Collias (shaded, river swim) | 10.2 / 193 m | Collias bridge car park (~10 min) | https://www.visorando.com/en/walk-vallon-de-l-ermitage-de-collias-et-crete/ |
| prologue_sim / TT | La Chapelle et Grotte de la Baume (steep technical) | 5.7 / 199 m | Sanilhac-Sagriès village square (2 min) | https://www.visorando.com/en/walk-la-chapelle-et-grotte-de-la-baume-a-part/ |

Also verified nearby (unused backups): Boucle de Collias 11.1/163; Carrières romaines Vers-Pont-du-Gard 13.4/114; Pont du Gard/aqueduc 13.5/316; Bois des Coufines 10.1/295 (technical, partly unmarked); Gorges du Gardon Russan→Collias 20.7/406 (point-to-point, needs pickup); Lussan/Concluses 23.2/413 (~30 min).

**Visorando GPX without login (discovered 2026-08-04):** the anonymous endpoint
`https://www.visorando.com/en/index.php?component=exportData&task=getRandoGeoJson&chartData=1&wholePointsData=1&idRandonnee=<ID>`
returns full track points + elevation profile (`chartdata`), no account needed. `<ID>` = numeric `idRandonnee` in the route page HTML. Pipeline script (GeoJSON→GPX→Garmin course): `~/projects/garmin/scripts/visorando_course_upload.py` (edit its `ROUTES` list, run with `--upload`; resumable via `course_results.json`); Garmin course save = POST `course-service/course/import` (multipart GPX) then POST `course-service/course` with `activityTypePk`, `sourceTypeId:3`, `coursePrivacy:{privacyRulePk:2}`, `startPoint` filled.

**intervals.icu → Garmin push (confirmed 2026-08-04):** a nightly job (~03:00 UTC) auto-creates each planned Run/WeightTraining workout in Garmin Connect ~6 days ahead, and re-pushes within seconds whenever the intervals event is edited. The Garmin workout description = ONLY the prose ABOVE the `---` separator in the intervals event description. So route/start-point lines MUST live in that prose block (above `---`), not appended at the bottom — direct edits to the Garmin workout get overwritten on next sync. Never manually create Garmin workouts for dates ≤6 days out — the push will duplicate them.

### Provence route set (Visorando) — matches routes already uploaded to Garmin Connect (2026-06-28)
| Session type | Location | Link |
|---|---|---|
| easy_road / strides | Durance river / canal path near Mallemort (flat) | https://www.visorando.com/en/walk-cavaillon.html |
| easy_trail technical / vert | Crête des Alpilles / Eygalières (technical limestone ridge) | https://www.visorando.com/en/walk-la-crete-des-alpilles/ |
| easy_trail low-vert / recovery | Colline Saint-Jacques, Cavaillon (easy, Durance views) | https://www.visorando.com/en/walk-la-colline-saint-jacques/ |
| tempo / threshold | Plateau d'Orgon / Alpilles foothills | https://www.visorando.com/en/walk-orgon.html |
| hill_repeats / long_run vert | Le Mourre Nègre via Cucuron, Luberon (1125m, best vert) | https://www.visorando.com/en/walk-le-mourre-negre-par-cucuron/ |

### Menorca route set (Wikiloc) — matches routes already uploaded to Garmin Connect (2026-06-28)
| Session type | Location | Link |
|---|---|---|
| easy_road / strides | Sant Lluís road loop (flat) | https://www.wikiloc.com/trails/outdoor/spain/balearic-islands/sant-lluis |
| easy_trail recovery / coastal | Camí de Cavalls: Punta Prima–Mahón (flat coastal) | https://www.wikiloc.com/trail-running-trails/menorca-cami-de-cavalls-etapa-6-punta-prima-mahon-14318792 |
| easy_trail technical | Camí de Cavalls: Es Grau–Favàritx (Es Grau Natural Park) | https://www.wikiloc.com/hiking-trails/gr-223-cami-de-cavalls-etapa-2-es-grau-favaritx-151147482 |
| tempo / threshold | Camí de Cavalls: Cala'n Porter–Punta Prima (rolling) | https://www.wikiloc.com/trail-running-trails/menorca-cami-de-cavalls-etapa-5-calan-porter-punta-prima-14307423 |
| hill_repeats | Monte Toro from Es Mercadal (358m — only real climb) | https://www.wikiloc.com/hiking-trails/menorca-es-mercadal-monte-toro-13979275 |
| long_run | Camí de Cavalls: Maó–Cap de Favàritx (long coastal) | https://es.wikiloc.com/rutas-senderismo/menorca-cami-de-cavalls-1a-etapa-mao-cap-de-favaritx-37077334 |

**Note:** Garmin already has these exact routes as private courses (Provence course IDs 480745xxx,
Menorca 480758xxx — see `domain_aria_fitness.md` 2026-06-28). The links above are the clickable
Visorando/Wikiloc equivalents. When the plan is re-pushed to intervals.icu, run the location-aware
fix (Provence Visorando / Menorca Wikiloc) rather than the Cape Town default for travel dates.

## Cape Town mapping (session type → location → URL) — use ONLY when he is home

| Session type | Location | Link |
|---|---|---|
| easy_road / road+strides | Sea Point Promenade / Lower Tokai (flat) | https://www.alltrails.com/trail/south-africa/western-cape/lower-tokai-walk |
| easy_trail / Run (vert ≥500m) | Silvermine Nature Reserve (technical singletrack + descents) | https://www.alltrails.com/poi/south-africa/western-cape/cape-town/silvermine-dam |
| easy_trail / Run (low vert, recovery) | Newlands Forest / Constantia Nek Contour Path | https://www.alltrails.com/trail/south-africa/western-cape/constantia-nek-to-kirstenbosch-via-contour-path |
| tempo / threshold / Quality (low vert) | Signal Hill Circuit (steady gradient) | https://www.alltrails.com/trail/south-africa/western-cape/signal-hill-circuit |
| hill_repeats / Quality (vert ≥400m) | Platteklip Gorge, Table Mountain (steep / stair reps) | https://www.visorando.com/en/walk-table-mountain-17/ |
| vo2max | Lion's Head lower slopes / Signal Hill | https://www.visorando.com/en/walk-lion-s-head-2/ |
| prologue_sim | Lion's Head (short, punchy, technical) | https://www.visorando.com/en/walk-lion-s-head-2/ |
| long_run / Long Run (vert ≥1000m) | Tokai–Silvermine traverse (Otter/UTCT-like) | https://www.alltrails.com/trail/south-africa/western-cape/tokai-silvermine |
| long_run (moderate vert) | Silvermine Dam – Elephant's Eye – Constantiaberg loop | https://www.alltrails.com/poi/south-africa/western-cape/constantiaberg |
| race_sim / Race Simulation | Tokai–Silvermine full traverse | https://www.alltrails.com/trail/south-africa/western-cape/tokai-silvermine |
| Recce (UTCT PT55) | PT55 course section — Table Mountain NP / Peninsula | https://www.alltrails.com/poi/south-africa/western-cape/cape-town/table-mountain |
| sharpener | Signal Hill Circuit (short pickups) | https://www.alltrails.com/trail/south-africa/western-cape/signal-hill-circuit |
| activation | Newlands Forest / Contour Path (pre-race shakeout) | https://www.alltrails.com/trail/south-africa/western-cape/constantia-nek-to-kirstenbosch-via-contour-path |
| rest / strength / race | — (no suggested route) | — |

**Note:** intervals.icu shows the link via the `description` field. The BQ columns are the
source of truth.

## Start-point Google Maps links (added 2026-07-08 — part of the convention)

Every non-race Run session also carries a **drive-to trailhead link** as a second description line:
```
Suggested route: <name> — <route url>
Start point (drive to): <trailhead name> — https://www.google.com/maps/search/?api=1&query=<lat>,<lon>
```
- Coordinate-based Google Maps links (`?api=1&query=<lat>,<lon>`) — most reliable for driving nav.
- BQ columns: **`start_point_name`, `start_coords`, `start_point_url`** on `training_plan`.
- **Source of truth for trailhead coords = the `ROUTE` dict in `~/projects/garmin/scripts/add_start_points.py`**
  (keyed by route_url → trailhead name + "lat,lon"). Coords are trailhead/parking points from the
  Visorando/Wikiloc/AllTrails pages and the GPX courses on Garmin. Add a new route there when a new
  route is introduced, then re-run the script.
- Run: `INTERVALS_API_KEY=$(gcloud secrets versions access latest --secret=intervals-api-key --project=abm2020) ~/garmin_venv/bin/python3 ~/projects/garmin/scripts/add_start_points.py`
  (idempotent — strips/replaces the `Start point (drive to):` line; keys off the route URL in each
  event's `Suggested route:` line, so the start point always matches the displayed route).

## Pushing routes to intervals.icu (WORKING — done 2026-07-08)

- Script: `~/projects/garmin/scripts/push_routes_to_intervals.py` — reads the BQ route columns,
  matches each to the same-date intervals.icu WORKOUT event of `type == "Run"`, and appends
  `Suggested route: … — <url>` to the event description. Idempotent (skips events already linked).
- Run it: `INTERVALS_API_KEY=$(gcloud secrets versions access latest --secret=intervals-api-key --project=abm2020) ~/garmin_venv/bin/python3 ~/projects/garmin/scripts/push_routes_to_intervals.py --dry-run` (then without `--dry-run`).
- **Credentials:** intervals.icu API key stored in Secret Manager: **`intervals-api-key`** (project `abm2020`). Athlete = Alex0907 / i624738.
- **intervals.icu API gotchas (all cost time on 2026-07-08 — remember them):**
  1. Use athlete id **`0`** ("me") in the path with a personal key. The explicit id `i624738` returns **403**.
  2. Must send a normal **User-Agent** header — the default `Python-urllib/*` UA gets **403**.
  3. Auth = HTTP Basic, username literally `API_KEY`, password = the key.
  4. Filter to `type == "Run"` so strength/`WeightTraining` events on the same day aren't tagged.
  5. The BQ Base-block dates and the intervals.icu calendar were **day-offset** in early July
     (plan regenerated on a slightly different schedule). Date-matching missed 6 real runs; a
     name-based fallback (Road→Sea Point/Lower Tokai, Technical→Silvermine, else→Newlands/Contour)
     linked them. If a re-push leaves non-race Run events unlinked, run the same name-based fallback.
- **Result 2026-07-08:** 88/91 Run events in range carry the link; the only 3 without are the
  actual race days (Otter prologue + main, UTCT PT55) — intentionally no training route.
