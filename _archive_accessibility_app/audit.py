"""
Grade — curb ramp audit pipeline.

Pulls San Francisco's official curb ramp records, finds recent street-level
imagery for each one, and checks whether the street agrees with the file.

Writes audit.json, which auditor.html can load directly.

    python audit.py --area mission --token "MLY|..." --limit 60

Nothing here is trained: detection is zero-shot via OWLv2, so you can run it
the hour you clone it. Fine-tuning on DataSF positives will beat it, but only
do that if you have time left over on day three.
"""

import argparse
import json
import math
import os
import time
from dataclasses import dataclass, asdict, field

import requests

# ----------------------------------------------------------------------------
# Study areas — bounding boxes over neighbourhoods with dense Mapillary coverage
# ----------------------------------------------------------------------------
AREAS = {
    "mission":    {"min_lat": 37.7480, "max_lat": 37.7690, "min_lng": -122.4250, "max_lng": -122.4050},
    "soma":       {"min_lat": 37.7730, "max_lat": 37.7880, "min_lng": -122.4130, "max_lng": -122.3930},
    "tenderloin": {"min_lat": 37.7800, "max_lat": 37.7890, "min_lng": -122.4200, "max_lng": -122.4090},
}

CRIS_ENDPOINT = "https://data.sfgov.org/resource/ch9w-7kih.json"
MLY_IMAGES = "https://graph.mapillary.com/images"

# Text prompts for zero-shot detection. Several phrasings per concept, because
# OWLv2 is sensitive to wording and the union is far more reliable than any one.
RAMP_PROMPTS = [
    "a curb ramp on a sidewalk",
    "a wheelchair ramp at a street corner",
    "yellow truncated dome tactile paving",
    "a sloped concrete cut in a curb",
]
BLOCKER_PROMPTS = [
    "a car parked over a sidewalk ramp",
    "construction plating on a sidewalk",
    "a garbage bin on a sidewalk",
    "a scooter lying on a sidewalk",
]

RAMP_THRESHOLD = 0.22      # OWLv2 scores run low; tune against DataSF positives
BLOCKER_THRESHOLD = 0.28
ADA_MAX_RUNNING_SLOPE = 8.33   # percent, the 1:12 federal limit


@dataclass
class Record:
    id: str
    corner: str
    quadrant: str
    lat: float
    lng: float
    verdict: str = "unaudited"
    cris: dict = field(default_factory=dict)
    found: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------
# 1. The city's claims
# ----------------------------------------------------------------------------
def fetch_cris(area: str, limit: int) -> list[Record]:
    box = AREAS[area]
    where = (
        f"latitude between {box['min_lat']} and {box['max_lat']} "
        f"AND longitude between {box['min_lng']} and {box['max_lng']}"
    )
    resp = requests.get(
        CRIS_ENDPOINT,
        params={"$limit": limit, "$where": where},
        timeout=30,
    )
    resp.raise_for_status()

    records = []
    for i, row in enumerate(resp.json()):
        if not row.get("latitude") or not row.get("longitude"):
            continue
        lat, lng = float(row["latitude"]), float(row["longitude"])
        exists = row.get("crexist") == "1"
        records.append(Record(
            id=f"RAMP-{row.get('locid') or row.get('cnn') or i}",
            corner=row.get("locationdescription") or "Unnamed segment",
            quadrant=" ".join(filter(None, [row.get("curbreturnloc"), row.get("positiononreturn")])) or "-",
            lat=lat, lng=lng,
            cris={
                "type": "Curb ramp" if exists else "Not present",
                "present": "Yes" if exists else "No",
                "slope": f"Range {row['sloperangeid']}" if row.get("sloperangeid") else "Not recorded",
                "updated": (row.get("lastupdate") or "Unknown")[:10],
            },
        ))
    print(f"  CRIS: {len(records)} records in {area}")
    return records


# ----------------------------------------------------------------------------
# 2. Recent eyes on that corner
# ----------------------------------------------------------------------------
def nearest_image(lat: float, lng: float, token: str, radius_deg: float = 0.0012):
    """Newest Mapillary image whose camera sits near this record."""
    bbox = f"{lng - radius_deg},{lat - radius_deg},{lng + radius_deg},{lat + radius_deg}"
    try:
        resp = requests.get(
            MLY_IMAGES,
            params={
                "access_token": token,
                "fields": "id,captured_at,thumb_1024_url,compass_angle,computed_geometry",
                "bbox": bbox,
                "limit": 8,
            },
            timeout=20,
        )
        resp.raise_for_status()
        images = [i for i in resp.json().get("data", []) if i.get("thumb_1024_url")]
    except requests.RequestException as exc:
        print(f"    mapillary error: {exc}")
        return None

    if not images:
        return None
    # Newest wins — the whole point is that the city's copy is stale.
    images.sort(key=lambda i: i.get("captured_at", 0), reverse=True)
    return images[0]


# ----------------------------------------------------------------------------
# 3 + 4. Vision: is the ramp there, is anything on it, how steep is it
# ----------------------------------------------------------------------------
class Vision:
    """Loaded lazily so --dry-run works on a laptop with no GPU."""

    def __init__(self, use_depth: bool = True):
        import torch
        from transformers import Owlv2Processor, Owlv2ForObjectDetection

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"  loading OWLv2 on {self.device}…")
        self.proc = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
        self.model = Owlv2ForObjectDetection.from_pretrained(
            "google/owlv2-base-patch16-ensemble"
        ).to(self.device).eval()

        self.depth = None
        if use_depth:
            try:
                # DA3-BASE is Apache 2.0. The LARGE and GIANT checkpoints are
                # CC BY-NC — fine for a hackathon, not for a company.
                from transformers import pipeline
                self.depth = pipeline(
                    "depth-estimation",
                    model="depth-anything/DA3-BASE",
                    device=0 if self.device == "cuda" else -1,
                )
                print("  loading Depth Anything 3 (BASE)…")
            except Exception as exc:
                print(f"  depth unavailable, slope checks disabled: {exc}")

    def detect(self, image, prompts, threshold):
        inputs = self.proc(text=[prompts], images=image, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            outputs = self.model(**inputs)
        target = self.torch.tensor([[image.height, image.width]]).to(self.device)
        results = self.proc.post_process_object_detection(
            outputs, threshold=threshold, target_sizes=target
        )[0]
        hits = []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            hits.append({
                "score": float(score),
                "prompt": prompts[int(label)],
                "box": [float(v) for v in box.tolist()],
            })
        return sorted(hits, key=lambda h: -h["score"])

    def slope_percent(self, image, box):
        """
        Rough running slope from a single frame.

        Take the metric depth map, sample it down the vertical centreline of
        the ramp box, and fit rise over run. This assumes a roughly level
        camera, which street-level capture mostly satisfies and occasionally
        does not. Treat the number as a screening signal that tells you which
        corners deserve a real inclinometer, not as a compliance measurement.
        """
        if self.depth is None:
            return None
        try:
            depth = self.depth(image)["predicted_depth"]
            arr = depth.squeeze().cpu().numpy()
        except Exception:
            return None

        h, w = arr.shape
        x0, y0, x1, y1 = box
        sx = int((x0 + x1) / 2 / image.width * w)
        y_top = max(0, int(y0 / image.height * h))
        y_bot = min(h - 1, int(y1 / image.height * h))
        if y_bot - y_top < 6:
            return None

        near, far = float(arr[y_bot, sx]), float(arr[y_top, sx])
        run = abs(far - near)
        if run < 1e-3:
            return None

        # Vertical pixel span converted to world rise via the depth at mid-ramp.
        # 1024px tall capture, ~70 degree vertical FOV is a reasonable default
        # for Mapillary action-cam sequences.
        mid_depth = (near + far) / 2
        vfov = math.radians(70)
        rise = (y_bot - y_top) / h * 2 * mid_depth * math.tan(vfov / 2)
        return round(min(rise / run * 100, 40.0), 1)


# ----------------------------------------------------------------------------
# Verdict
# ----------------------------------------------------------------------------
def judge(record: Record, image_meta, vision: "Vision | None") -> Record:
    if image_meta is None:
        record.verdict = "unaudited"
        record.found = {"present": "-", "slope": "-", "obstruction": "-",
                        "captured": "No imagery", "conf": None}
        return record

    captured = time.strftime("%Y-%m-%d", time.gmtime(image_meta.get("captured_at", 0) / 1000)) \
        if image_meta.get("captured_at") else "date unknown"

    if vision is None:  # --dry-run
        record.found = {"present": "-", "slope": "-", "obstruction": "-",
                        "captured": captured, "conf": None}
        return record

    from PIL import Image
    import io
    blob = requests.get(image_meta["thumb_1024_url"], timeout=25).content
    image = Image.open(io.BytesIO(blob)).convert("RGB")

    ramps = vision.detect(image, RAMP_PROMPTS, RAMP_THRESHOLD)
    blockers = vision.detect(image, BLOCKER_PROMPTS, BLOCKER_THRESHOLD)

    slope = vision.slope_percent(image, ramps[0]["box"]) if ramps else None
    confidence = ramps[0]["score"] if ramps else 0.0

    if not ramps:
        verdict = "missing"          # the city says yes, the street says no
    elif blockers:
        verdict = "obstructed"       # exists but unusable today
    elif slope is not None and slope > ADA_MAX_RUNNING_SLOPE:
        verdict = "slope"
    else:
        verdict = "confirmed"

    record.verdict = verdict
    record.found = {
        "present": "Yes" if ramps else "No",
        "slope": f"{slope}%" if slope is not None else "-",
        "obstruction": blockers[0]["prompt"] if blockers else "None",
        "captured": captured,
        "conf": round(confidence, 3) if ramps else None,
        "image_id": image_meta["id"],
        "image_url": image_meta["thumb_1024_url"],
    }
    return record


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Audit SF curb ramp records against street imagery.")
    ap.add_argument("--area", default="mission", choices=sorted(AREAS))
    ap.add_argument("--token", default=os.environ.get("MAPILLARY_TOKEN", ""))
    ap.add_argument("--limit", type=int, default=60, help="CRIS records to audit")
    ap.add_argument("--out", default="audit.json")
    ap.add_argument("--dry-run", action="store_true", help="skip model loading, test the data plumbing")
    ap.add_argument("--no-depth", action="store_true", help="detection only, no slope estimates")
    args = ap.parse_args()

    if not args.token and not args.dry_run:
        raise SystemExit("Need a Mapillary token: --token or MAPILLARY_TOKEN env var.")

    print(f"Auditing {args.area}")
    records = fetch_cris(args.area, args.limit)

    vision = None if args.dry_run else Vision(use_depth=not args.no_depth)

    for n, record in enumerate(records, 1):
        meta = nearest_image(record.lat, record.lng, args.token) if args.token else None
        judge(record, meta, vision)
        print(f"  [{n}/{len(records)}] {record.id} -> {record.verdict}")

    flagged = [r for r in records if r.verdict in ("missing", "obstructed", "slope")]
    payload = {
        "area": args.area,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(records),
        "flagged": len(flagged),
        "disagreement_rate": round(len(flagged) / len(records), 3) if records else 0,
        "records": [asdict(r) for r in records],
    }
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)

    print(f"\n{len(flagged)} of {len(records)} records disagree with CRIS")
    print(f"Wrote {args.out} — load it in auditor.html")


if __name__ == "__main__":
    main()
