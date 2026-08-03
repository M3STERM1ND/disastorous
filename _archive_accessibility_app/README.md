# Grade

Auditing San Francisco's curb ramp inventory against street-level imagery, then routing around the gaps.

The city publishes a record of every curb ramp it believes exists. That dataset carries an explicit warning: it is a planning tool, there is no guarantee the attributes are accurate, and the system behind it refreshes roughly once a quarter. Grade checks those records against imagery captured recently, flags the ones that no longer match, and reweights the pedestrian network so routes avoid them.

## Files

```
index.html            Landing page — the problem and the method
auditor.html          The tool: map, record list, inspector, export
pipeline/audit.py     CRIS -> imagery -> detection -> verdicts -> audit.json
pipeline/route.py     audit.json -> weighted walk graph -> routes.geojson
pipeline/requirements.txt
```

## Running the frontend

No build step. Either open `index.html` directly, or serve it so `fetch` behaves:

```bash
python -m http.server 8000
# open http://localhost:8000
```

The auditor opens in **Sample audit** mode, which ships inside the page and needs no network. Use this for the actual demo. Switching the source to **Live CRIS** pulls real records from DataSF; they arrive as `unaudited` until you attach pipeline output.

## Running the pipeline

```bash
cd pipeline
pip install -r requirements.txt

# check the plumbing without downloading any models
python audit.py --area mission --dry-run --limit 10

# the real thing
export MAPILLARY_TOKEN="MLY|..."
python audit.py --area mission --limit 60 --out audit.json

# routing
python route.py --audit audit.json \
  --from 37.7650,-122.4196 --to 37.7522,-122.4184
```

Free token: <https://www.mapillary.com/developer>

## How detection works without training data

`audit.py` uses **OWLv2**, an open-vocabulary detector, prompted in plain English — "a curb ramp on a sidewalk", "yellow truncated dome tactile paving". Zero-shot, Apache 2.0, no labelled dataset needed. That is the only reason this fits in three days.

Slope estimation uses **Depth Anything 3** (`DA3-BASE`, Apache 2.0) to get metric depth from a single frame, then fits rise over run across the detected ramp.

If you have spare time on day three, fine-tune a detector using CRIS records as positives — the same data you are auditing doubles as your training set for the corners where the city happens to be right.

## Licensing

Everything is free. Two things to watch:

- **Depth Anything 3 weights are split.** `DA3-BASE` is Apache 2.0. `DA3-LARGE` and `DA3-GIANT` are CC BY-NC 4.0 — fine for a hackathon, not for a company. The pipeline pins BASE deliberately.
- **Mapillary imagery is CC BY-SA.** Attribution is in the page footer. Keep it there.

DataSF is public domain. OpenStreetMap is ODbL. OWLv2, SAM 2, OpenCV, MapLibre, OSMnx, NetworkX all permissive.

## Demo notes

1. **Precompute.** Run `audit.py` the night before, commit `audit.json`, demo from Sample mode. Nothing should call a model live while judges are watching.
2. **Check coverage first.** Mapillary is dense on Mission and SoMa arterials and thin on residential side streets. Verify your demo blocks on Mapillary's map before you commit to them.
3. **Lead with one corner.** Open on a single flagged record with the photo visible, then zoom out to the neighbourhood. The specific case lands; the heatmap only makes sense after it.
4. **Say the accuracy number out loud.** CRIS gives you free ground truth for the corners where it is right, so you can quote real precision and recall. Almost no hackathon project can.

## Limitations, stated plainly

- Slope from a single monocular frame is a **screening signal, not a measurement**. It assumes a roughly level camera. It tells you which corners deserve a real inclinometer.
- A verdict of `missing` can mean the ramp is absent, occluded by a parked vehicle, or outside the frame. Confidence is reported; treat low-confidence flags as leads.
- Imagery has its own staleness. A June capture is much fresher than a quarterly database sync, but it is not today.
- **This is not an ADA compliance determination** and should never be presented as one. It is a prioritised list of corners worth sending a human to look at.

Not affiliated with the City and County of San Francisco.
