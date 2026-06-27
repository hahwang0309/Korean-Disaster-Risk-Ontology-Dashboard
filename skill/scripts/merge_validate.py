#!/usr/bin/env python3
"""Merge per-chunk extraction JSONs into one validated triple set.

Usage:
    python merge_validate.py <chunks_dir> <out.json> \
        --glob 'meta_*.json' \
        --ontology <ontology_schema.json> \
        --bridge <property_bridge_table.json>   (optional) \
        --source-doc "<human label>"            (optional)

Steps: load all chunk JSONs -> normalize predicate/properties shape -> apply bridge
aliases to canonical keys (if bridge given) -> dedupe by (subject, predicate, object)
-> validate types & relation codes against the ontology -> assign stable IDs ->
compute the per-document emergent property schema -> write the final JSON.
Prints a validation report (counts + warnings) to stdout.
"""
import sys, os, re, json, glob, argparse


def norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def pred_code(t):
    p = t.get("predicate")
    return p.get("code") if isinstance(p, dict) else p


def pred_props(t):
    p = t.get("predicate")
    return (p.get("properties") or {}) if isinstance(p, dict) else {}


def node_props(node):
    return node.get("properties", node.get("attributes", {})) or {}


def apply_bridge(props, bridge_keys):
    """Rename alias keys -> canonical using the bridge alias map."""
    if not bridge_keys:
        return props
    out = {}
    for k, v in props.items():
        out[bridge_keys.get(k, k)] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chunks_dir")
    ap.add_argument("out")
    ap.add_argument("--glob", default="meta_*.json")
    ap.add_argument("--ontology", required=True)
    ap.add_argument("--bridge", default=None)
    ap.add_argument("--source-doc", default="")
    a = ap.parse_args()

    onto = json.load(open(a.ontology, encoding="utf-8"))
    VALID_TYPES = set(onto["entity_types"])
    VALID_REL = {r["code"] for r in onto["relations_phase1"]} | {r["code"] for r in onto["relations_phase2"]}

    # build alias->canonical map from bridge (if any)
    bridge_alias = {}
    if a.bridge and os.path.exists(a.bridge):
        b = json.load(open(a.bridge, encoding="utf-8"))
        for scope in ("node_keys", "relation_keys"):
            for canon, meta in b.get(scope, {}).items():
                for al in meta.get("aliases", []):
                    bridge_alias[al] = canon

    raw, warns = [], []
    for fp in sorted(glob.glob(os.path.join(a.chunks_dir, a.glob))):
        cid = re.sub(r"\D", "", os.path.basename(fp)) or os.path.basename(fp)
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception as e:
            warns.append(f"{os.path.basename(fp)}: JSON parse error: {e}")
            continue
        for t in data.get("triples", []):
            t["_chunk"] = cid
            raw.append(t)

    # dedupe
    seen, dedup = set(), []
    for t in raw:
        key = (norm(t.get("subject", {}).get("name")), pred_code(t), norm(t.get("object", {}).get("name")))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(t)

    ent_props, rel_props, type_ct, rel_ct = {}, {}, {}, {}
    final = []
    for i, t in enumerate(dedup, 1):
        s, o = t.get("subject", {}), t.get("object", {})
        code = pred_code(t)
        sp = apply_bridge(node_props(s), bridge_alias)
        op = apply_bridge(node_props(o), bridge_alias)
        rp = apply_bridge(pred_props(t), bridge_alias)
        for node, pr in ((s, sp), (o, op)):
            ty = node.get("type")
            if ty not in VALID_TYPES:
                warns.append(f"[chunk {t['_chunk']}] invalid entity type: {ty!r} (name={node.get('name')!r})")
            type_ct[ty] = type_ct.get(ty, 0) + 1
            d = ent_props.setdefault(ty, {})
            for k in pr:
                d[k] = d.get(k, 0) + 1
        if code not in VALID_REL:
            warns.append(f"[chunk {t['_chunk']}] non-enum relation code: {code!r}")
        rel_ct[code] = rel_ct.get(code, 0) + 1
        d = rel_props.setdefault(code, {})
        for k in rp:
            d[k] = d.get(k, 0) + 1
        final.append({
            "id": f"T{i:04d}",
            "subject": {"name": s.get("name"), "type": s.get("type"), "properties": sp},
            "predicate": {"code": code, "properties": rp},
            "object": {"name": o.get("name"), "type": o.get("type"), "properties": op},
            "evidence": t.get("evidence", ""),
            "source_chunk": t.get("_chunk"),
        })

    def sortd(d):
        return {k: dict(sorted(v.items(), key=lambda x: -x[1]))
                for k, v in sorted(d.items(), key=lambda x: -sum(x[1].values()))}

    doc = {
        "metadata": {
            "source_document": a.source_doc,
            "ontology": onto.get("source", "재난위험관리 온톨로지"),
            "ontology_version": onto.get("version", "v1"),
            "extraction_method": "chunked parallel LLM extraction with free-form metadata, merged & deduplicated",
            "triple_count": len(final),
            "entity_mention_distribution": dict(sorted(type_ct.items(), key=lambda x: -x[1])),
            "predicate_distribution": dict(sorted(rel_ct.items(), key=lambda x: -x[1])),
            "emergent_property_schema": {
                "entity_node_properties": sortd(ent_props),
                "relation_edge_properties": sortd(rel_props),
            },
        },
        "triples": final,
    }
    json.dump(doc, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"raw={len(raw)} deduped={len(final)} -> {a.out}")
    print("entity types:", dict(sorted(type_ct.items(), key=lambda x: -x[1])))
    print("relations:", dict(sorted(rel_ct.items(), key=lambda x: -x[1])))
    print(f"WARNINGS: {len(warns)}")
    for w in warns[:40]:
        print("  -", w)


if __name__ == "__main__":
    main()
