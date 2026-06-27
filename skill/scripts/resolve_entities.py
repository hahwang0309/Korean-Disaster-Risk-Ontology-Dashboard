#!/usr/bin/env python3
"""Entity resolution (coreference) for the disaster-risk graph.

Same real-world entity often appears under variant strings ("제15호 태풍 루사",
"제15호 태풍 루사(RUSA)", "2002년 제15호 태풍 RUSA(루사)") and would otherwise become
separate nodes — fragmenting the graph and breaking cross-document merging. This step
canonicalizes node names through a GLOBAL entity-alias registry, exactly parallel to the
property bridge table. The hard "are these the same entity?" judgment is left to Claude;
the script handles the mechanical parts and surfaces candidates.

Usage:
    # dry-run: apply current registry, auto-merge trivial variants, REPORT review clusters
    python resolve_entities.py <triples.json> --registry <entity_aliases.json>

    # apply: rewrite node names to canonical and re-dedup triples in place
    python resolve_entities.py <triples.json> --registry <entity_aliases.json> --write

Registry format (entity_aliases.json):
    {"version": N, "entities": {
        "<canonical name>": {"type": "NaturalHazard", "aliases": ["...", "..."], "note": "..."}
    }}

Detection is TYPE-AWARE by default. Auto-merge (no manual step):
  * trivially-equal names (whitespace / full-width / quote spacing), AND
  * same-type names differing only by a TRAILING parenthetical qualifier when the shared base
    is substantial ('화재' <-> '화재(2008)', '루사' <-> '루사(RUSA)'). Year/scope as a PREFIX
    ('2010 산사태' vs '2011 산사태') yields different bases -> stays separate.
REVIEW clusters (token Jaccard >= threshold, containment, bracket-stripped equal) are printed
for Claude to confirm, add to the registry, then re-run with --write.

CROSS-TYPE: a registry entity with "merge_any_type": true absorbs same-named nodes regardless of
their type and RETYPES them to the canonical's type — fixes one real-world thing extracted under
two types (e.g. a fire typed as both ManmadeHazard and Event). Unhandled cross-type collisions
are reported as a '동일명 이종타입' warning for Claude to resolve.
"""
import sys, os, re, json, argparse, unicodedata
from collections import defaultdict

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
BRACKET_RE = re.compile(r"[\(\)\[\]（）「」『』{}<>]")
QUOTE_RE = re.compile(r"[''\"`´]")


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def trivial_norm(name):
    """Whitespace/full-width/quote normalization only — safe to auto-merge on."""
    s = nfkc(name).strip().casefold()
    s = QUOTE_RE.sub("'", s)
    s = re.sub(r"\s+", " ", s)
    return s


def loose_key(name):
    """Drop bracketed *content*, punctuation, spaces — for cluster hinting (NOT auto-merge)."""
    s = nfkc(name).casefold()
    s = re.sub(r"[\(\[（「『][^\)\]）」』]*[\)\]）」』]", "", s)  # remove (...) [...] etc
    s = re.sub(r"[^0-9a-z가-힣]", "", s)
    return s


PAREN_TRAIL_RE = re.compile(r"\s*[\(\[（「『][^\)\]）」』]*[\)\]）」』]\s*$")


def base_name(name):
    """Name with trailing parenthetical qualifier(s) stripped, normalized.
    e.g. '코리아2000 냉동창고 화재(2008)' -> '코리아2000 냉동창고 화재'. Used to
    auto-merge variants that differ only by a trailing (연도)/(약칭)/(전국)-style qualifier."""
    s = nfkc(name).strip()
    prev = None
    while prev != s:
        prev = s
        s = PAREN_TRAIL_RE.sub("", s).strip()
    return re.sub(r"\s+", " ", s).casefold()


def is_specific(base):
    """True if base is substantial enough that variants sharing it are safely the same
    entity. Guards against merging over-generic names (화재/정전/산사태 단독) that could
    collide across documents."""
    compact = re.sub(r"[^0-9a-z가-힣]", "", base)
    return len(compact) >= 6 or len(base.split()) >= 2


def tokens(name):
    return set(TOKEN_RE.findall(nfkc(name).casefold()))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class UF:
    def __init__(self, items):
        self.p = {x: x for x in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def load_registry(path):
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {"version": 1,
            "description": "전역 엔티티 별칭 레지스트리. 표기가 다른 같은 실세계 개체를 하나의 canonical name 으로 묶어 노드 분열·중복을 막고 문서 간 동일 개체를 합친다. consolidation 처럼 Claude 가 후보를 확정해 갱신한다.",
            "entities": {}}


def build_index(reg):
    """(trivial_norm(name), type) -> canonical name, for both canonical and aliases."""
    idx = {}
    for canon, meta in reg.get("entities", {}).items():
        ty = meta.get("type", "")
        idx[(trivial_norm(canon), ty)] = canon
        for al in meta.get("aliases", []):
            idx[(trivial_norm(al), ty)] = canon
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("triples")
    ap.add_argument("--registry", required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--jaccard", type=float, default=0.45)
    a = ap.parse_args()

    data = json.load(open(a.triples, encoding="utf-8"))
    triples = data.get("triples", [])
    reg = load_registry(a.registry)

    # collect distinct nodes (name,type) with frequency + degree
    freq = defaultdict(int)
    for t in triples:
        for r in ("subject", "object"):
            nd = t.get(r, {})
            if nd.get("name"):
                freq[(nd["name"], nd.get("type", "Other"))] += 1

    idx = build_index(reg)

    def canon_of(name, ty):
        return idx.get((trivial_norm(name), ty), name)

    # ---- auto-merge trivially-equal variants not yet in registry ----
    by_norm = defaultdict(list)
    for (nm, ty) in freq:
        by_norm[(trivial_norm(canon_of(nm, ty)), ty)].append((nm, ty))
    auto_added = 0
    for (_, ty), members in by_norm.items():
        forms = sorted({canon_of(nm, ty) for (nm, ty) in members})
        if len(forms) > 1:
            canonical = max(forms, key=lambda s: (freq.get((s, ty), 0), len(s)))
            ent = reg["entities"].setdefault(canonical, {"type": ty, "aliases": [], "note": "auto: trivial variant"})
            ent.setdefault("aliases", [])
            for f in forms:
                if f != canonical and f not in ent["aliases"]:
                    ent["aliases"].append(f)
                    auto_added += 1
    idx = build_index(reg)  # refresh after auto-merge

    # ---- stronger auto-merge: same-type names sharing a SUBSTANTIAL base, differing only
    #      by a trailing parenthetical qualifier ('화재' vs '화재(2008)', '루사' vs '루사(RUSA)').
    #      Year/scope as a PREFIX ('2010 산사태' vs '2011 산사태') yields different bases, so
    #      genuinely distinct events stay separate. Canonical = most frequent, then most specific. ----
    by_base = defaultdict(list)
    for (nm, ty) in freq:
        by_base[(base_name(canon_of(nm, ty)), ty)].append((nm, ty))
    paren_added = 0
    for (b, ty), members in by_base.items():
        if not b or not is_specific(b):
            continue
        forms = sorted({canon_of(nm, ty) for (nm, ty) in members})
        if len(forms) > 1:
            canonical = max(forms, key=lambda s: (freq.get((s, ty), 0), len(s)))
            ent = reg["entities"].setdefault(canonical, {"type": ty, "aliases": [], "note": "auto: 괄호 한정자 변형"})
            ent.setdefault("aliases", [])
            for f in forms:
                if f != canonical and f not in ent["aliases"]:
                    ent["aliases"].append(f)
                    paren_added += 1
    auto_added += paren_added
    idx = build_index(reg)

    # ---- cross-type detection: same base appearing under DIFFERENT types (typing inconsistency,
    #      e.g. 화재 as ManmadeHazard vs Event). Reported for Claude to unify via "merge_any_type". ----
    base_types = defaultdict(set)
    for (nm, ty) in freq:
        base_types[base_name(canon_of(nm, ty))].add(ty)
    handled = {base_name(c) for c, m in reg["entities"].items() if m.get("merge_any_type")}
    cross_type = []
    for b, tys in base_types.items():
        if b and is_specific(b) and len(tys) > 1 and b not in handled:
            forms = sorted({(canon_of(nm, ty), ty) for (nm, ty) in freq if base_name(canon_of(nm, ty)) == b})
            cross_type.append((b, forms))

    # ---- detect REVIEW clusters (type-aware) among current canonical names ----
    canon_nodes = defaultdict(set)  # type -> set(canonical names)
    for (nm, ty) in freq:
        canon_nodes[ty].add(canon_of(nm, ty))
    review = []
    for ty, nmset in canon_nodes.items():
        names = sorted(nmset)
        if len(names) < 2:
            continue
        toks = {nm: tokens(nm) for nm in names}
        lk = {nm: loose_key(nm) for nm in names}
        uf = UF(names)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                ni, nj = names[i], names[j]
                same_loose = lk[ni] and lk[ni] == lk[nj]
                contain = lk[ni] and lk[nj] and (lk[ni] in lk[nj] or lk[nj] in lk[ni])
                jac = jaccard(toks[ni], toks[nj])
                if same_loose or contain or jac >= a.jaccard:
                    uf.union(ni, nj)
        clusters = defaultdict(list)
        for nm in names:
            clusters[uf.find(nm)].append(nm)
        for members in clusters.values():
            if len(members) > 1:
                members.sort(key=lambda s: -freq.get((s, ty), 0))
                # skip if already fully captured as one registry entity
                canons = {canon_of(m, ty) for m in members}
                if len(canons) == 1:
                    continue
                review.append((ty, members))

    # cross-type index: entities flagged "merge_any_type" absorb same-named nodes regardless
    # of their type AND retype them to the canonical's type (fixes Hazard/Event 화재 split).
    idx_any = {}
    for canon, meta in reg["entities"].items():
        if meta.get("merge_any_type"):
            cty = meta.get("type", "Other")
            idx_any[trivial_norm(canon)] = (canon, cty)
            for al in meta.get("aliases", []):
                idx_any[trivial_norm(al)] = (canon, cty)

    # ---- apply (write) ----
    if a.write:
        for t in triples:
            for r in ("subject", "object"):
                nd = t.get(r, {})
                if not nd.get("name"):
                    continue
                hit = idx_any.get(trivial_norm(nd["name"]))
                if hit:
                    nd["name"], nd["type"] = hit          # cross-type unify + retype
                else:
                    nd["name"] = canon_of(nd["name"], nd.get("type", "Other"))
        # re-dedup triples by (subj,pred,obj)
        seen, out = set(), []
        for t in triples:
            s, o = t.get("subject", {}), t.get("object", {})
            p = t.get("predicate")
            code = p.get("code") if isinstance(p, dict) else p
            k = (re.sub(r"\s+", "", (s.get("name") or "")).lower(), code,
                 re.sub(r"\s+", "", (o.get("name") or "")).lower())
            if k in seen:
                continue
            seen.add(k)
            out.append(t)
        data["triples"] = out
        for i, t in enumerate(out, 1):
            t["id"] = f"T{i:04d}"
        json.dump(data, open(a.triples, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    reg["version"] = reg.get("version", 1) + (1 if auto_added else 0)
    json.dump(reg, open(a.registry, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ---- report ----
    if a.write:
        print(f"APPLIED: rewrote node names -> canonical, re-deduped to {len(data['triples'])} triples")
    print(f"registry: {len(reg['entities'])} canonical entities (auto-added aliases: {auto_added}, "
          f"그중 괄호-한정자 자동병합: {paren_added})")
    if cross_type:
        print(f"\n⚠ 동일명 이종타입 ({len(cross_type)}) — 같은 개체가 타입만 다르게 추출됨. 올바른 타입으로 통일하려면")
        print("  해당 canonical entity 에 \"merge_any_type\": true 를 추가하고 다른 타입 표기를 aliases 에 넣은 뒤 --write:")
        for b, forms in sorted(cross_type, key=lambda x: -len(x[1])):
            print(f"    base '{b}': " + ", ".join(f"{nm}[{ty}]" for nm, ty in forms))
    print(f"\nREVIEW CLUSTERS (type-aware, jaccard>={a.jaccard}): {len(review)}")
    for ty, members in sorted(review, key=lambda x: -len(x[1])):
        print(f"\n  [{ty}] 후보 ({len(members)}개) — 같은 개체면 canonical 1개 + 나머지 aliases:")
        for m in members:
            print(f"      ({freq.get((m, ty), 0)}회)  {m}")
    if review and not a.write:
        print("\n=> 같은 실세계 개체인 클러스터만 entity_aliases.json 의 entities 에")
        print("   {\"<canonical>\": {\"type\":\"...\",\"aliases\":[...]}} 로 추가한 뒤,")
        print("   --write 로 다시 실행해 트리플 노드명을 canonical 로 통일하세요.")


if __name__ == "__main__":
    main()
