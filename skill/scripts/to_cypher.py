#!/usr/bin/env python3
"""Convert a validated triple JSON into a Neo4j Cypher import script.

Usage:
    python to_cypher.py <doc_triples.json> <out.cypher> [--doc-id "<label>"]

Design for a cascading-risk graph:
  * Each entity becomes a node MERGE'd on (name, type) so the same hazard/event/actor
    appearing across documents collapses into one node. The ontology axis (Hazard /
    Event / Damage / ...) is added as a second label for easy querying.
  * Properties are SET via += (non-destructive merge). A `sourceDocs` array accumulates
    provenance across documents.
  * Each triple becomes a relationship MERGE'd on its code, carrying its properties plus
    `evidence` and `sourceDoc`.
Run with: cypher-shell < out.cypher   (or paste into Neo4j Browser).
"""
import sys, os, re, json, argparse

AXIS = {
    "NaturalHazard": "Hazard", "ManmadeHazard": "Hazard", "RiskFactor": "Hazard",
    "Region": "Exposure", "Facility": "Exposure", "Population": "Exposure",
    "Event": "Event", "Damage": "Damage",
    "ResponseAction": "Response", "ResponseActor": "Response", "Resilience": "Response",
    "Context": "Context", "Other": "Other",
}


def cval(v):
    """Render a Python value as a Cypher literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").strip()
    return f"'{s}'"


def props_map(d, extra=None):
    items = dict(d or {})
    if extra:
        items.update(extra)
    if not items:
        return "{}"
    inner = ", ".join(f"{safe_key(k)}: {cval(v)}" for k, v in items.items() if v is not None and v != "")
    return "{" + inner + "}"


def safe_key(k):
    k = re.sub(r"[^0-9A-Za-z_]", "_", str(k))
    if not k or k[0].isdigit():
        k = "p_" + k
    return k


def node_key(node):
    return (node.get("name") or "", node.get("type") or "Other")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--doc-id", default="")
    a = ap.parse_args()

    data = json.load(open(a.src, encoding="utf-8"))
    doc_id = a.doc_id or data.get("metadata", {}).get("source_document", os.path.basename(a.src))
    triples = data.get("triples", [])

    # collect unique nodes (merge properties across triples within this doc)
    nodes = {}
    for t in triples:
        for role in ("subject", "object"):
            nd = t.get(role, {})
            k = node_key(nd)
            if k[0] == "":
                continue
            rec = nodes.setdefault(k, {})
            rec.update(nd.get("properties", {}) or {})

    lines = []
    lines.append("// Neo4j import — disaster-risk cascading graph")
    lines.append(f"// source: {doc_id}")
    lines.append(f"// nodes: {len(nodes)}  relationships: {len(triples)}")
    lines.append("")
    lines.append("// ---- nodes ----")
    nid = {}
    for i, (k, pr) in enumerate(nodes.items()):
        name, typ = k
        nid[k] = i
        axis = AXIS.get(typ, "Other")
        labels = typ if axis == typ else f"{axis}:{typ}"
        base = props_map(pr, extra={"name": name, "ekType": typ})
        lines.append(
            f"MERGE (n:{labels} {{name: {cval(name)}}}) "
            f"SET n += {base} "
            f"SET n.sourceDocs = coalesce(n.sourceDocs, []) + "
            f"CASE WHEN {cval(doc_id)} IN coalesce(n.sourceDocs, []) THEN [] ELSE [{cval(doc_id)}] END;"
        )
    lines.append("")
    lines.append("// ---- relationships ----")
    for t in triples:
        s, o = t.get("subject", {}), t.get("object", {})
        sk, ok = node_key(s), node_key(o)
        if sk[0] == "" or ok[0] == "":
            continue
        code = (t.get("predicate") or {}).get("code") or "RELATED_TO"
        code = re.sub(r"[^0-9A-Za-z_]", "_", code).upper()
        rp = (t.get("predicate") or {}).get("properties", {}) or {}
        rmap = props_map(rp, extra={"evidence": t.get("evidence", ""), "sourceDoc": doc_id, "tripleId": t.get("id", "")})
        lines.append(
            f"MATCH (a:{sk[1]} {{name: {cval(sk[0])}}}), (b:{ok[1]} {{name: {cval(ok[0])}}}) "
            f"MERGE (a)-[r:{code}]->(b) SET r += {rmap};"
        )

    with open(a.out, "w", encoding="utf-8") as g:
        g.write("\n".join(lines) + "\n")
    print(f"OK: {a.out}  ({len(nodes)} nodes, {len(triples)} relationships)")


if __name__ == "__main__":
    main()
