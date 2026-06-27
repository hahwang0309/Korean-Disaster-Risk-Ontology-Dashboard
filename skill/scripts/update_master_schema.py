#!/usr/bin/env python3
"""Accumulate a document's emergent property schema into the GLOBAL master schema,
and surface keys that may need consolidation into the bridge (alias) table.

Usage:
    python update_master_schema.py <doc_triples.json> \
        --master <master_property_schema.json> \
        --bridge <property_bridge_table.json> \
        --doc-id "<label>"

What it does (all deterministic — the fuzzy "are these the same concept?" judgment is
left to Claude in the consolidation step described in SKILL.md):
  1. Reads the doc's metadata.emergent_property_schema.
  2. Canonicalizes keys through the current bridge alias map.
  3. Adds counts into the master schema (per entity type / per relation code),
     recording first_seen / docs_seen for each key.
  4. Prints NEW keys (not canonical, not a known alias) — these are consolidation
     candidates Claude should review and either fold into an existing canonical key
     (add as alias in the bridge) or promote to a new canonical key.
"""
import sys, os, json, argparse


def load(path, default):
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return default


def alias_map(bridge):
    m = {}
    for scope in ("node_keys", "relation_keys"):
        for canon, meta in bridge.get(scope, {}).items():
            m[scope] = m.get(scope, {})
            m[scope][canon] = canon
            for al in meta.get("aliases", []):
                m[scope][al] = canon
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("--master", required=True)
    ap.add_argument("--bridge", required=True)
    ap.add_argument("--doc-id", default="")
    a = ap.parse_args()

    doc = json.load(open(a.doc, encoding="utf-8"))
    emergent = doc.get("metadata", {}).get("emergent_property_schema", {})
    master = load(a.master, {"version": 1, "docs": [], "node_keys": {}, "relation_keys": {}})
    bridge = load(a.bridge, {"version": 1, "node_keys": {}, "relation_keys": {}})
    amap = alias_map(bridge)

    doc_id = a.doc_id or doc.get("metadata", {}).get("source_document", os.path.basename(a.doc))
    if doc_id not in master["docs"]:
        master["docs"].append(doc_id)

    new_keys = {"node_keys": {}, "relation_keys": {}}
    pairs = [
        ("node_keys", emergent.get("entity_node_properties", {})),
        ("relation_keys", emergent.get("relation_edge_properties", {})),
    ]
    for scope, groups in pairs:
        m = master.setdefault(scope, {})
        smap = amap.get(scope, {})
        for owner, keys in groups.items():          # owner = entity type or relation code
            for k, cnt in keys.items():
                canon = smap.get(k, k)              # canonicalize via bridge
                rec = m.setdefault(canon, {"count": 0, "owners": {}, "docs": [], "first_seen": doc_id})
                rec["count"] += cnt
                rec["owners"][owner] = rec["owners"].get(owner, 0) + cnt
                if doc_id not in rec["docs"]:
                    rec["docs"].append(doc_id)
                if k not in smap:                   # unseen, not a known alias/canonical
                    nk = new_keys[scope].setdefault(canon, {"count": 0, "owners": set()})
                    nk["count"] += cnt
                    nk["owners"].add(owner)

    json.dump(master, open(a.master, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    n_node = len(new_keys["node_keys"])
    n_rel = len(new_keys["relation_keys"])
    print(f"master updated: {a.master}")
    print(f"  node canonical keys total: {len(master['node_keys'])}")
    print(f"  relation canonical keys total: {len(master['relation_keys'])}")
    print(f"NEW (consolidation candidates) — node: {n_node}, relation: {n_rel}")
    for scope in ("node_keys", "relation_keys"):
        for k, v in sorted(new_keys[scope].items(), key=lambda x: -x[1]["count"]):
            print(f"  [{scope}] {k}  (count={v['count']}, owners={sorted(v['owners'])})")
    if n_node + n_rel:
        print("\n=> Review these in SKILL.md's consolidation step: fold each into an existing")
        print("   canonical key (add as alias in the bridge) or promote to a new canonical key.")


if __name__ == "__main__":
    main()
