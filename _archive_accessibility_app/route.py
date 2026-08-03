"""
Grade — accessible routing.

Takes audit.json and turns it into two routes: the one a normal walking
router gives you, and the one that avoids every corner where the imagery
disagreed with the city. The gap between them is the demo.

    python route.py --audit audit.json \
        --from 37.7650,-122.4196 --to 37.7522,-122.4184

Writes routes.geojson, which auditor.html renders as the dashed and solid
lines in Route view.
"""

import argparse
import json
import math

import networkx as nx
import osmnx as ox

# How much detour is worth avoiding each kind of barrier, as a multiplier on
# the true length of the edge. A missing ramp is close to impassable in a
# wheelchair, so it carries a heavy penalty rather than an infinite one —
# infinity makes the router fail on blocks with no good option at all, which
# is worse than routing through and warning.
PENALTY = {
    "missing": 12.0,
    "slope": 5.0,
    "obstructed": 3.5,
    "unaudited": 1.15,   # mild aversion to unknowns
    "confirmed": 1.0,
}

BARRIER_RADIUS_M = 25   # a record applies to edges whose ends fall within this


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_records(path):
    with open(path) as fh:
        payload = json.load(fh)
    return payload["records"] if isinstance(payload, dict) else payload


def build_graph(origin, dest, margin=0.004):
    """Pedestrian network covering both endpoints with a little slack."""
    north = max(origin[0], dest[0]) + margin
    south = min(origin[0], dest[0]) - margin
    east = max(origin[1], dest[1]) + margin
    west = min(origin[1], dest[1]) - margin
    print(f"  building walk network over {south:.4f}..{north:.4f}")
    graph = ox.graph_from_bbox(bbox=(west, south, east, north), network_type="walk")
    return graph


def apply_penalties(graph, records):
    """Fold each audit verdict into the cost of the edges near it."""
    flagged = [r for r in records if r["verdict"] != "confirmed"]
    touched = 0

    for u, v, key, data in graph.edges(keys=True, data=True):
        length = data.get("length", 1.0)
        data["base_cost"] = length
        worst = 1.0
        reason = None

        mid_lat = (graph.nodes[u]["y"] + graph.nodes[v]["y"]) / 2
        mid_lng = (graph.nodes[u]["x"] + graph.nodes[v]["x"]) / 2

        for record in flagged:
            if haversine_m(mid_lat, mid_lng, record["lat"], record["lng"]) <= BARRIER_RADIUS_M:
                factor = PENALTY.get(record["verdict"], 1.0)
                if factor > worst:
                    worst, reason = factor, record
        if reason is not None:
            touched += 1
        data["access_cost"] = length * worst
        data["barrier"] = reason["id"] if reason else None
        data["barrier_kind"] = reason["verdict"] if reason else None

    print(f"  penalised {touched} edges from {len(flagged)} flagged records")
    return graph


def path_to_feature(graph, path, kind, records_by_id):
    coords, barriers, metres, penalised = [], [], 0.0, 0.0
    for node in path:
        coords.append([graph.nodes[node]["x"], graph.nodes[node]["y"]])
    for u, v in zip(path[:-1], path[1:]):
        data = min(graph[u][v].values(), key=lambda d: d.get("length", 1e9))
        metres += data.get("length", 0.0)
        penalised += data.get("access_cost", 0.0)
        if data.get("barrier"):
            barriers.append({"id": data["barrier"], "kind": data.get("barrier_kind")})

    seen, unique = set(), []
    for b in barriers:
        if b["id"] not in seen:
            seen.add(b["id"])
            unique.append(b)

    return {
        "type": "Feature",
        "properties": {
            "kind": kind,
            "metres": round(metres),
            "minutes": round(metres / 78.0, 1),   # ~4.7 km/h, unhurried
            "barriers_crossed": len(unique),
            "barrier_ids": [b["id"] for b in unique],
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def main():
    ap = argparse.ArgumentParser(description="Route around audited curb ramp barriers.")
    ap.add_argument("--audit", default="audit.json")
    ap.add_argument("--from", dest="origin", required=True, help="lat,lng")
    ap.add_argument("--to", dest="dest", required=True, help="lat,lng")
    ap.add_argument("--out", default="routes.geojson")
    args = ap.parse_args()

    origin = tuple(float(v) for v in args.origin.split(","))
    dest = tuple(float(v) for v in args.dest.split(","))

    records = load_records(args.audit)
    records_by_id = {r["id"]: r for r in records}
    print(f"Loaded {len(records)} audited records")

    graph = build_graph(origin, dest)
    graph = apply_penalties(graph, records)

    start = ox.nearest_nodes(graph, origin[1], origin[0])
    end = ox.nearest_nodes(graph, dest[1], dest[0])

    baseline = nx.shortest_path(graph, start, end, weight="base_cost")
    accessible = nx.shortest_path(graph, start, end, weight="access_cost")

    features = [
        path_to_feature(graph, baseline, "baseline", records_by_id),
        path_to_feature(graph, accessible, "accessible", records_by_id),
    ]

    with open(args.out, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, indent=2)

    b, a = features[0]["properties"], features[1]["properties"]
    print("\n  shortest route:   "
          f"{b['metres']} m, {b['minutes']} min, {b['barriers_crossed']} barriers crossed")
    print("  accessible route: "
          f"{a['metres']} m, {a['minutes']} min, {a['barriers_crossed']} barriers crossed")
    print(f"  cost of access:   +{a['metres'] - b['metres']} m, "
          f"+{round(a['minutes'] - b['minutes'], 1)} min")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
