#!/usr/bin/env python3
"""Build an interactive HTML dashboard (9 views) from a validated triple JSON.

Usage:
    python visualize.py <doc_triples.json> <out.html> [--top 30] [--title "..."]

Produces ONE self-contained HTML file (Plotly.js + D3.js from CDN with SRI pins; all
graph metrics precomputed in Python and embedded as JSON — no Python installs needed):
   1. Network Connectivity Map  major risk-propagation paths (Hazard/RiskFactor -> ... -> Damage),
                                layered left->right by cascade depth; the diagram is the UNION of
                                the paths, edge weight = #paths through that edge (trunk = thick).
   2. Entity Type Distribution                  (row with 3)
   3. Entity Type Heatmap        square: entity-type x entity-type co-occurrence (same order both axes)
   4. Predicate Distribution                    (row with 5)
   5. Predicate Heatmap          subject-type x predicate (ALL predicates, frequency-ordered)
   6. Sankey Diagram             axis flow: subject axis -> predicate -> object axis
   7. Force-directed Graph       full graph, color=type, size=degree
   8. Centrality Ranking         degree centrality + PageRank                 (row with 9)
   9. Community Detection        label-propagation communities — TABLE ONLY (no network viz)
Each view carries a short, data-driven Korean interpretation line.
"""
import sys, os, json, argparse, html as _html
from collections import defaultdict, Counter

AXIS = {
    "NaturalHazard": "Hazard", "ManmadeHazard": "Hazard", "RiskFactor": "Hazard",
    "Region": "Exposure", "Facility": "Exposure", "Population": "Exposure",
    "Event": "Event", "Damage": "Damage",
    "ResponseAction": "Response", "ResponseActor": "Response", "Resilience": "Response",
    "Context": "Context", "Other": "Other",
}
TYPE_COLORS = {
    "NaturalHazard": "#e15759", "ManmadeHazard": "#b4453a", "RiskFactor": "#ff9da7",
    "Region": "#4e79a7", "Facility": "#76b7b2", "Population": "#59a14f",
    "Event": "#f28e2b", "Damage": "#9c27b0",
    "ResponseAction": "#edc948", "ResponseActor": "#bab0ac", "Resilience": "#86bcb6",
    "Context": "#a0cbe8", "Other": "#cccccc",
}
# forward risk-propagation relations used for the connectivity map
CAUSAL = {"TRIGGERS", "INCREASES_RISK_OF", "TRIGGERS_SECONDARY", "CASCADES_INTO",
          "CAUSES", "AMPLIFIES", "COMPOUNDS", "DERIVES_FROM", "MODIFIES_RISK_OF",
          "CONCURRENT_WITH", "PRECONDITIONS", "AFFECTS"}


def pagerank(nodes, adj, d=0.85, iters=60):
    n = len(nodes)
    if n == 0:
        return {}
    pr = {x: 1.0 / n for x in nodes}
    out_deg = {x: len(adj[x]) for x in nodes}
    for _ in range(iters):
        nxt = {x: (1 - d) / n for x in nodes}
        for x in nodes:
            if out_deg[x] == 0:
                share = d * pr[x] / n
                for y in nodes:
                    nxt[y] += share
            else:
                share = d * pr[x] / out_deg[x]
                for y in adj[x]:
                    nxt[y] += share
        pr = nxt
    return pr


def label_propagation(nodes, undirected_adj, iters=30):
    label = {x: i for i, x in enumerate(nodes)}
    for _ in range(iters):
        changed = False
        for x in nodes:
            if not undirected_adj[x]:
                continue
            cnt = Counter(label[y] for y in undirected_adj[x])
            best = max(cnt.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if label[x] != best:
                label[x] = best
                changed = True
        if not changed:
            break
    sizes = Counter(label.values())
    ranked = {old: new for new, (old, _) in enumerate(sizes.most_common())}
    return {x: ranked[label[x]] for x in nodes}


def top_causal_paths(nodes, cadj, deg, ntype, max_depth=6, max_paths=2500, keep=28):
    """Enumerate simple causal source->sink paths, rank by cascade depth then importance."""
    cout = {x: [v for v, _ in cadj[x]] for x in nodes}
    cin = defaultdict(int)
    for x in nodes:
        for v in cout.get(x, []):
            cin[v] += 1
    sources = [x for x in nodes if cin[x] == 0 and cout.get(x)]
    # prefer hazards/riskfactors/primary events as starting points; fall back to any source
    sources.sort(key=lambda x: (AXIS.get(ntype[x]) != "Hazard", -deg[x]))
    paths = []
    budget = [max_paths]

    def dfs(node, trail, seen):
        if budget[0] <= 0 or len(trail) > max_depth:
            return
        nxt = cout.get(node, [])
        is_sink = not nxt or AXIS.get(ntype[node]) == "Damage"
        if len(trail) >= 3 and is_sink:
            paths.append(list(trail))
            budget[0] -= 1
            if AXIS.get(ntype[node]) == "Damage":
                return
        for v in nxt:
            if v in seen:
                continue
            seen.add(v)
            trail.append(v)
            dfs(v, trail, seen)
            trail.pop()
            seen.discard(v)

    for s in sources:
        if budget[0] <= 0:
            break
        dfs(s, [s], {s})

    def score(p):
        return (len(p), sum(deg[n] for n in p))
    paths.sort(key=score, reverse=True)
    # dedup near-identical (same endpoints + length), keep most important
    seen_sig, chosen = set(), []
    for p in paths:
        sig = (p[0], p[-1], len(p))
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        chosen.append(p)
        if len(chosen) >= keep:
            break
    return chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--title", default="")
    ap.add_argument("--home", default="", help="목록(랜딩) 페이지 URL — 주면 '← 목록으로' 버튼 표시")
    a = ap.parse_args()

    data = json.load(open(a.src, encoding="utf-8"))
    triples = data.get("triples", [])
    title = a.title or data.get("metadata", {}).get("source_document", os.path.basename(a.src))

    ntype = {}
    edges = []
    adj = defaultdict(set)
    uadj = defaultdict(set)
    cadj = defaultdict(list)        # directed causal adjacency
    deg = Counter()
    type_pair = Counter()
    type_pred = Counter()
    pred_ct = Counter()
    sankey = Counter()

    def code_of(t):
        p = t.get("predicate")
        return (p.get("code") if isinstance(p, dict) else p) or "RELATED_TO"

    for t in triples:
        s, o = t.get("subject", {}), t.get("object", {})
        sn, on = s.get("name"), o.get("name")
        st, ot = s.get("type", "Other"), o.get("type", "Other")
        if not sn or not on:
            continue
        ntype[sn] = st
        ntype[on] = ot
        code = code_of(t)
        edges.append((sn, on, code))
        adj[sn].add(on)
        uadj[sn].add(on)
        uadj[on].add(sn)
        deg[sn] += 1
        deg[on] += 1
        type_pair[(st, ot)] += 1
        type_pred[(st, code)] += 1
        pred_ct[code] += 1
        sankey[(AXIS.get(st, "Other"), code, AXIS.get(ot, "Other"))] += 1
        if code in CAUSAL and sn != on:
            cadj[sn].append((on, code))

    nodes = list(ntype.keys())
    for x in nodes:
        adj.setdefault(x, set()); uadj.setdefault(x, set())
    n = len(nodes)

    type_ct = Counter(ntype.values())
    # unified entity-type order (by frequency) used on BOTH axes of heatmap #1
    all_types = [t for t, _ in type_ct.most_common()]
    preds_sorted = [p for p, _ in pred_ct.most_common()]

    # 1. square type x type
    h1 = [[type_pair.get((rt, ct), 0) for ct in all_types] for rt in all_types]
    # 2. subject type x predicate (all predicates, freq-ordered)
    subj_types = [t for t in all_types if any((t, p) in type_pred for p in preds_sorted)]
    h2 = [[type_pred.get((st, p), 0) for p in preds_sorted] for st in subj_types]

    # communities (needed for adjacency ordering + view 9)
    comm = label_propagation(nodes, uadj)
    pr = pagerank(nodes, adj)
    deg_cent = {x: deg[x] / (n - 1) if n > 1 else 0 for x in nodes}

    deg_seq = [deg[x] for x in nodes]

    cent_top = sorted(nodes, key=lambda x: (deg[x], pr.get(x, 0)), reverse=True)[:max(a.top, 20)]
    cent_rows = [{"name": x, "type": ntype[x], "degree": deg[x],
                  "deg_cent": round(deg_cent[x], 4), "pagerank": round(pr.get(x, 0), 5),
                  "community": comm[x]} for x in cent_top]

    n_comm = len(set(comm.values()))
    comm_sizes = Counter(comm.values())
    comm_rows = []
    for cid, sz in comm_sizes.most_common(15):
        members = sorted([x for x in nodes if comm[x] == cid], key=lambda x: -deg[x])[:6]
        mtypes = Counter(ntype[x] for x in nodes if comm[x] == cid)
        comm_rows.append({"id": cid, "size": sz, "top_members": members,
                          "dominant_types": [t for t, _ in mtypes.most_common(3)]})

    fg_nodes = [{"id": x, "type": ntype[x], "deg": deg[x], "comm": comm[x],
                 "color": TYPE_COLORS.get(ntype[x], "#999")} for x in nodes]
    fg_links = [{"source": s_, "target": o_, "code": c_} for (s_, o_, c_) in edges]

    # sankey
    axes_in = sorted({k[0] for k in sankey})
    preds_mid = sorted({k[1] for k in sankey})
    axes_out = sorted({k[2] for k in sankey})
    sk_labels = [f"◀{x}" for x in axes_in] + preds_mid + [f"{x}▶" for x in axes_out]
    sk_index = {}
    for i, x in enumerate(axes_in):
        sk_index[("in", x)] = i
    base = len(axes_in)
    for i, p in enumerate(preds_mid):
        sk_index[("mid", p)] = base + i
    base2 = base + len(preds_mid)
    for i, x in enumerate(axes_out):
        sk_index[("out", x)] = base2 + i
    flow_in, flow_out = Counter(), Counter()
    for (ai, p, ao), v in sankey.items():
        flow_in[(ai, p)] += v
        flow_out[(p, ao)] += v
    sk_src, sk_tgt, sk_val = [], [], []
    for (ai, p), v in flow_in.items():
        sk_src.append(sk_index[("in", ai)]); sk_tgt.append(sk_index[("mid", p)]); sk_val.append(v)
    for (p, ao), v in flow_out.items():
        sk_src.append(sk_index[("mid", p)]); sk_tgt.append(sk_index[("out", ao)]); sk_val.append(v)

    # 1. connectivity map — major causal paths (the diagram is the UNION of these paths;
    #    edge weight = how many major paths traverse that edge -> the trunk shows as thick lines)
    paths = top_causal_paths(nodes, cadj, deg, ntype)
    bb_nodes = {x for p in paths for x in p}
    edge_pw = Counter()     # edge -> #paths through it
    node_pw = Counter()     # node -> #paths through it
    for p in paths:
        for x in set(p):
            node_pw[x] += 1
        for i in range(len(p) - 1):
            edge_pw[(p[i], p[i + 1])] += 1
    code_lookup = {}
    for (s_, o_, c_) in edges:
        if c_ in CAUSAL:
            code_lookup.setdefault((s_, o_), c_)
    bb_edges = []
    bb_adj = defaultdict(list)
    seen_e = set()
    for p in paths:
        for i in range(len(p) - 1):
            e = (p[i], p[i + 1])
            if e in seen_e:
                continue
            seen_e.add(e)
            bb_edges.append({"source": e[0], "target": e[1], "code": code_lookup.get(e, ""),
                             "weight": edge_pw[e]})
            bb_adj[e[0]].append(e[1])
    cm_maxw = max((e["weight"] for e in bb_edges), default=1)
    trunk = max(bb_edges, key=lambda e: e["weight"], default=None)
    # layer = longest distance from a source within backbone
    layer = {x: 0 for x in bb_nodes}
    for _ in range(len(bb_nodes)):
        changed = False
        for u in bb_nodes:
            for v in bb_adj.get(u, []):
                if layer[v] < layer[u] + 1:
                    layer[v] = layer[u] + 1
                    changed = True
        if not changed:
            break
    maxlayer = max(layer.values()) if layer else 0
    layer_members = defaultdict(list)
    for x in sorted(bb_nodes, key=lambda x: -deg[x]):
        layer_members[layer[x]].append(x)
    cm_nodes = []
    for lyr, members in layer_members.items():
        for yi, x in enumerate(members):
            cm_nodes.append({"id": x, "type": ntype[x], "color": TYPE_COLORS.get(ntype[x], "#999"),
                             "deg": deg[x], "pw": node_pw[x], "layer": lyr, "yi": yi, "lcount": len(members)})
    # readable top chain
    def short(x):
        return (x[:16] + "…") if len(x) > 17 else x
    top_chain = " → ".join(short(x) for x in paths[0]) if paths else "—"

    # ---- data-driven interpretations ----
    def topcell(counter):
        return counter.most_common(1)[0] if counter else (("", ""), 0)
    tp_pair, tp_pair_v = topcell(type_pair)
    tp_typred, tp_typred_v = topcell(type_pred)
    top_type = type_ct.most_common(1)[0] if type_ct else ("", 0)
    top_pred = pred_ct.most_common(1)[0] if pred_ct else ("", 0)
    causal_share = sum(pred_ct[c] for c in pred_ct if c in CAUSAL)
    hub_node = cent_rows[0]["name"] if cent_rows else "—"
    hub_deg = cent_rows[0]["degree"] if cent_rows else 0
    big_comm = comm_rows[0] if comm_rows else {"size": 0, "dominant_types": []}
    n_haz_dmg = sum(1 for p in paths if AXIS.get(ntype[p[0]]) == "Hazard" and AXIS.get(ntype[p[-1]]) == "Damage")
    singleton = sum(1 for _, s in comm_sizes.items() if s == 1)

    interp = {
        "typeDist": f"총 {n}개 노드 중 가장 많은 타입은 <b>{top_type[0]}</b>({top_type[1]}회). 대응·사건·피해 비중이 높으면 그 문서가 대응·복구 서술 중심임을 뜻한다.",
        "predDist": f"가장 빈번한 관계는 <b>{top_pred[0]}</b>({top_pred[1]}건). 전체 {len(edges)}개 관계 중 인과·전파성 관계(TRIGGERS·CASCADES_INTO·CAUSES 등)가 <b>{causal_share}건</b>으로, 예측 그래프의 핵심 골격이다.",
        "hm1": f"행=subject 타입, 열=object 타입(두 축 동일 순서). 색이 짙은 칸이 자주 함께 등장하는 조합으로, 최다 조합은 <b>{tp_pair[0]}→{tp_pair[1]}</b>({tp_pair_v}건). 대각선 위/아래 비대칭은 방향성(누가 누구에게 작용하는지)을 보여준다.",
        "hm2": f"행=subject 타입, 열=관계(빈도순 전체 표시, 잘림 없음). 어떤 엔티티 타입이 어떤 관계의 출발점이 되는지 보여준다. 최다 칸은 <b>{tp_typred[0][0]} —{tp_typred[0][1]}→</b>({tp_typred_v}건).",
        "cent": f"연결중심성·PageRank 상위 노드가 재난 서사의 결절점이다. 1위 <b>{hub_node}</b>(연결도 {hub_deg}). 상위에 위험원·핵심 사건이 오르면 인과 흐름의 발원·분기점을 뜻한다.",
        "comm": f"커뮤니티 {n_comm}개(라벨전파). 최대 군집 크기 {big_comm['size']}, 주 타입 {', '.join(big_comm['dominant_types'])}. 단독(크기1) 노드 {singleton}개 — 문서가 누적돼 같은 기관·위험원이 여러 문서에서 합쳐지면 군집이 뚜렷해진다.",
        "sankey": f"좌(subject 축)→중(관계)→우(object 축) 흐름량. 위험원→사건→피해로 갈수록 폭이 모이면 인과 사슬이 뚜렷하다는 신호.",
        "fg": f"노드 {n}개·엣지 {len(edges)}개 전체 그래프. 색=엔티티 타입, 크기=연결도. 중심의 큰 노드가 허브다. 드래그·줌으로 탐색.",
        "connectivity": f"위험원/위험요인→…→피해 <b>주요 전파 경로 {len(paths)}개</b>의 <b>합집합(union)</b>을 cascade 깊이(좌→우)로 그린 것 — 그림의 선 개수는 경로 수({len(paths)})와 다르다(여러 경로가 공유하는 링크는 1개로 합쳐짐). <b>링크 두께·밝기 = 그 링크를 지나는 주요 경로 수(weight)</b>이므로 굵을수록 핵심 전파 통로(트렁크)다. 최다 통과 링크: <b>{_html.escape(trunk['source'][:18]+' →'+trunk['target'][:18]) if trunk else '—'}</b>(경로 {trunk['weight'] if trunk else 0}개 통과). 노드 크기=그 노드를 지나는 경로 수. 완결 경로(위험원→피해) {n_haz_dmg}개, 최장 연쇄 예: {_html.escape(top_chain)}.",
    }

    payload = {
        "title": title,
        "stats": {"nodes": n, "edges": len(edges), "types": len(type_ct),
                  "predicates": len(pred_ct), "communities": n_comm, "major_paths": len(paths)},
        "all_types": all_types, "h1": h1,
        "subj_types": subj_types, "preds_sorted": preds_sorted, "h2": h2,
        "type_ct": dict(type_ct.most_common()), "pred_ct": dict(pred_ct.most_common()),
        "type_colors": TYPE_COLORS,
        "cent_rows": cent_rows, "comm_rows": comm_rows,
        "fg_nodes": fg_nodes, "fg_links": fg_links,
        "sk_labels": sk_labels, "sk_src": sk_src, "sk_tgt": sk_tgt, "sk_val": sk_val,
        "cm_nodes": cm_nodes, "cm_edges": bb_edges, "cm_maxlayer": maxlayer, "cm_maxw": cm_maxw,
        "interp": interp,
    }

    home_html = (f'<a class="home" href="{_html.escape(a.home)}">← 목록으로</a>'
                 if a.home else "")
    html_out = (HTML_TEMPLATE
                .replace("__TITLE__", _html.escape(title))
                .replace("__HOME__", home_html)
                .replace("__DATA__", json.dumps(payload, ensure_ascii=False)))
    with open(a.out, "w", encoding="utf-8") as g:
        g.write(html_out)
    print(f"OK: {a.out}")
    print(f"  nodes={n} edges={len(edges)} types={len(type_ct)} predicates={len(pred_ct)} "
          f"communities={n_comm} major_paths={len(paths)}")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>재난위험 그래프 대시보드 — __TITLE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"
        integrity="sha384-cCVCZkAjYNxaYKbM8lsArLznDF/SvMFr1jcZrvOpSTCa0W40ZAdLzHCEulnUa5i7"
        crossorigin="anonymous"></script>
<script src="https://d3js.org/d3.v7.min.js"
        integrity="sha384-CjloA8y00+1SDAUkjs099PVfnY2KmDC2BZnws9kh8D/lX1s46w6EPhpXdqMfjK6i"
        crossorigin="anonymous"></script>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
       margin:0;background:#0f1115;color:#e6e6e6}
  header{padding:18px 24px;background:#161922;border-bottom:1px solid #2a2f3a}
  .home{display:inline-block;margin-bottom:10px;color:#9aa4b2;text-decoration:none;font-size:13px;
        background:#1d212b;border:1px solid #2a2f3a;border-radius:7px;padding:6px 12px}
  .home:hover{color:#e6e6e6;border-color:#4e79a7}
  h1{font-size:18px;margin:0 0 4px} .sub{color:#9aa4b2;font-size:13px}
  .stats{display:flex;gap:18px;margin-top:10px;flex-wrap:wrap}
  .stat{background:#1d212b;border:1px solid #2a2f3a;border-radius:8px;padding:8px 14px}
  .stat b{font-size:18px;color:#fff} .stat span{display:block;color:#9aa4b2;font-size:11px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 24px}
  .card{background:#161922;border:1px solid #2a2f3a;border-radius:10px;padding:12px;display:flex;flex-direction:column}
  .card h2{font-size:14px;margin:2px 0 8px;color:#cdd6e3}
  .card .desc{color:#8a93a3;font-size:11px;margin-bottom:8px}
  .full{grid-column:1 / -1}
  .plot{width:100%;height:380px} .tall{height:560px}
  .interp{margin-top:10px;padding:9px 11px;background:#12161f;border-left:3px solid #4e79a7;
          border-radius:0 6px 6px 0;font-size:12px;line-height:1.55;color:#b9c4d4}
  .interp b{color:#e6edf6}
  table{border-collapse:collapse;width:100%;font-size:12px}
  th,td{border-bottom:1px solid #262b36;padding:5px 8px;text-align:left}
  th{color:#9aa4b2;font-weight:600} td .pill{padding:1px 6px;border-radius:6px;color:#111;font-size:10px}
  #fg,#fgc{width:100%;height:560px;background:#0c0e13;border-radius:8px}
  #cmap{width:100%;height:520px;background:#0c0e13;border-radius:8px}
  .legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
  .legend span{font-size:10px;color:#cdd6e3;display:flex;align-items:center;gap:4px}
  .dot{width:9px;height:9px;border-radius:2px;display:inline-block}
  .tip{position:absolute;background:#000b;color:#fff;padding:4px 8px;border-radius:4px;
       font-size:11px;pointer-events:none;opacity:0;max-width:280px}
</style></head>
<body>
<header>
  __HOME__
  <h1>재난위험 인과·연쇄 그래프 대시보드</h1>
  <div class="sub">__TITLE__</div>
  <div class="stats" id="stats"></div>
</header>
<div class="grid">
  <div class="card full"><h2>1. Network Connectivity Map (주요 전파 경로)</h2>
     <div class="desc">위험원/위험요인 → 사건 → (연쇄) → 피해 · 좌→우 = cascade 깊이 · 색=타입 · <b>링크 두께·밝기 = 통과 경로 수(트렁크)</b></div>
     <div id="cmap"></div><div class="legend" id="cmapLegend"></div>
     <div class="interp" id="i_connectivity"></div></div>

  <div class="card"><h2>2. Entity Type Distribution</h2><div class="desc">엔티티 타입별 노드 멘션 분포</div>
     <div id="typeDist" class="plot"></div><div class="interp" id="i_typeDist"></div></div>
  <div class="card"><h2>3. Entity Type Heatmap</h2><div class="desc">엔티티 타입 × 엔티티 타입 (두 축 동일 순서)</div>
     <div id="hm1" class="plot"></div><div class="interp" id="i_hm1"></div></div>

  <div class="card"><h2>4. Predicate Distribution</h2><div class="desc">관계(predicate) 코드별 빈도</div>
     <div id="predDist" class="plot"></div><div class="interp" id="i_predDist"></div></div>
  <div class="card"><h2>5. Predicate Heatmap</h2><div class="desc">subject 타입 × 관계 (전체, 빈도순)</div>
     <div id="hm2" class="plot"></div><div class="interp" id="i_hm2"></div></div>

  <div class="card full"><h2>6. Sankey Diagram</h2><div class="desc">축 흐름: 위험원 축 → 관계 → 피해 축</div>
     <div id="sankey" class="plot"></div><div class="interp" id="i_sankey"></div></div>

  <div class="card full"><h2>7. Force-directed Graph</h2><div class="desc">전체 그래프 · 색=타입 · 크기=연결도 · 드래그/줌</div>
     <div id="fg"></div><div class="legend" id="fgLegend"></div><div class="interp" id="i_fg"></div></div>

  <div class="card"><h2>8. Centrality Ranking</h2><div class="desc">연결중심성·PageRank 상위 노드</div>
     <div id="cent" style="max-height:520px;overflow:auto"></div><div class="interp" id="i_cent"></div></div>
  <div class="card"><h2>9. Community Detection</h2><div class="desc">label propagation 커뮤니티 (표)</div>
     <div id="commTable" style="max-height:520px;overflow:auto"></div>
     <div class="interp" id="i_comm"></div></div>
</div>
<div class="tip" id="tip"></div>
<script>
const D = __DATA__;
const PL = {paper_bgcolor:'#161922',plot_bgcolor:'#161922',font:{color:'#cdd6e3',size:11},
            margin:{l:90,r:20,t:10,b:60}};
const CFG = {displayModeBar:false,responsive:true};
const tip=document.getElementById('tip');

document.getElementById('stats').innerHTML = Object.entries(D.stats)
  .map(([k,v])=>`<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('');
for(const [k,v] of Object.entries(D.interp)){const el=document.getElementById('i_'+k); if(el) el.innerHTML=v;}

Plotly.newPlot('typeDist', [{type:'bar', x:Object.values(D.type_ct), y:Object.keys(D.type_ct),
  orientation:'h', marker:{color:Object.keys(D.type_ct).map(t=>D.type_colors[t]||'#999')}}],
  {...PL, yaxis:{autorange:'reversed'}}, CFG);

Plotly.newPlot('predDist', [{type:'bar', x:Object.keys(D.pred_ct), y:Object.values(D.pred_ct),
  marker:{color:'#f28e2b'}}], {...PL, margin:{l:50,r:20,t:10,b:110}, xaxis:{tickangle:-45}}, CFG);

Plotly.newPlot('hm1', [{type:'heatmap', z:D.h1, x:D.all_types, y:D.all_types,
  colorscale:'YlOrRd', hoverongaps:false}], {...PL, xaxis:{tickangle:-45}, yaxis:{autorange:'reversed'}}, CFG);

Plotly.newPlot('hm2', [{type:'heatmap', z:D.h2, x:D.preds_sorted, y:D.subj_types, colorscale:'Viridis'}],
  {...PL, margin:{l:100,r:20,t:10,b:110}, xaxis:{tickangle:-45}, yaxis:{autorange:'reversed'}}, CFG);

Plotly.newPlot('sankey', [{type:'sankey', orientation:'h',
  node:{label:D.sk_labels, pad:12, thickness:14, color:'#4e79a7', line:{color:'#161922',width:0.5}},
  link:{source:D.sk_src, target:D.sk_tgt, value:D.sk_val, color:'rgba(120,160,200,0.3)'}}],
  {...PL, margin:{l:10,r:10,t:10,b:10}}, CFG);

(function(){let h='<table><tr><th>#</th><th>node</th><th>type</th><th>deg</th><th>deg-cent</th><th>PageRank</th><th>comm</th></tr>';
  D.cent_rows.forEach((r,i)=>{const c=D.type_colors[r.type]||'#999';
    h+=`<tr><td>${i+1}</td><td>${r.name}</td><td><span class="pill" style="background:${c}">${r.type}</span></td>`+
       `<td>${r.degree}</td><td>${r.deg_cent}</td><td>${r.pagerank}</td><td>${r.community}</td></tr>`;});
  document.getElementById('cent').innerHTML=h+'</table>';})();

(function(){let h='<table><tr><th>comm</th><th>size</th><th>dominant types</th><th>top members</th></tr>';
  D.comm_rows.forEach(r=>{h+=`<tr><td>${r.id}</td><td>${r.size}</td><td>${r.dominant_types.join(', ')}</td>`+
       `<td>${r.top_members.join(' · ')}</td></tr>`;});
  document.getElementById('commTable').innerHTML=h+'</table>';})();

document.getElementById('fgLegend').innerHTML = Object.keys(D.type_ct)
  .map(t=>`<span><i class="dot" style="background:${D.type_colors[t]||'#999'}"></i>${t}</span>`).join('');
document.getElementById('cmapLegend').innerHTML = document.getElementById('fgLegend').innerHTML;

const palette = d3.schemeTableau10.concat(d3.schemeSet3);
function forceGraph(sel, colorBy){
  const el=document.getElementById(sel); el.innerHTML='';
  const W=el.clientWidth, H=560;
  const svg=d3.select('#'+sel).append('svg').attr('width',W).attr('height',H);
  const g=svg.append('g');
  svg.call(d3.zoom().scaleExtent([0.2,4]).on('zoom',e=>g.attr('transform',e.transform)));
  const nodes=D.fg_nodes.map(d=>({...d})), links=D.fg_links.map(d=>({...d}));
  const sim=d3.forceSimulation(nodes)
    .force('link',d3.forceLink(links).id(d=>d.id).distance(40).strength(0.4))
    .force('charge',d3.forceManyBody().strength(-30))
    .force('center',d3.forceCenter(W/2,H/2))
    .force('collide',d3.forceCollide().radius(d=>3+Math.sqrt(d.deg)*1.5));
  const link=g.append('g').attr('stroke','#39414f').attr('stroke-opacity',0.5)
    .selectAll('line').data(links).join('line').attr('stroke-width',0.7);
  const node=g.append('g').selectAll('circle').data(nodes).join('circle')
    .attr('r',d=>3+Math.sqrt(d.deg)*1.5)
    .attr('fill',d=>colorBy==='comm'?palette[d.comm%palette.length]:d.color)
    .attr('stroke','#0c0e13').attr('stroke-width',0.5)
    .call(d3.drag()
      .on('start',(e,d)=>{if(!e.active)sim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;})
      .on('drag',(e,d)=>{d.fx=e.x;d.fy=e.y;})
      .on('end',(e,d)=>{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null;}))
    .on('mousemove',(e,d)=>{tip.style.opacity=1;tip.style.left=(e.pageX+10)+'px';
      tip.style.top=(e.pageY+10)+'px';tip.innerHTML=`<b>${d.id}</b><br>${d.type} · deg ${d.deg} · comm ${d.comm}`;})
    .on('mouseout',()=>tip.style.opacity=0);
  sim.on('tick',()=>{link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
        .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
    node.attr('cx',d=>d.x).attr('cy',d=>d.y);});
}
forceGraph('fg','type');

// 1. connectivity map — layered left->right by cascade depth; edge weight = #paths through it
(function(){
  const el=document.getElementById('cmap'); const W=el.clientWidth, H=560;
  const svg=d3.select('#cmap').append('svg').attr('width',W).attr('height',H);
  const g=svg.append('g');
  svg.call(d3.zoom().scaleExtent([0.3,3]).on('zoom',e=>g.attr('transform',e.transform)));
  const ml=Math.max(1,D.cm_maxlayer), padX=120, padY=28, maxw=Math.max(1,D.cm_maxw||1);
  const ewidth=w=>1 + 7*((w||1)-1)/Math.max(1,maxw-1);        // 1..8 px by path-traffic
  const ecolor=d3.interpolateRgb('#55617a','#ffd000');         // gray(weight1) -> gold(trunk)
  const eshade=w=>ecolor(maxw>1?(w-1)/(maxw-1):0);
  const pos={};
  D.cm_nodes.forEach(d=>{
    const x=padX + d.layer*((W-2*padX)/ml);
    const y=padY + (d.yi+1)*((H-2*padY)/(d.lcount+1));
    pos[d.id]={x,y,d};
  });
  svg.append('defs').append('marker').attr('id','arr').attr('viewBox','0 -5 10 10')
    .attr('refX',18).attr('refY',0).attr('markerWidth',5).attr('markerHeight',5).attr('orient','auto')
    .append('path').attr('d','M0,-5L10,0L0,5').attr('fill','#8893a6');
  g.append('g').attr('fill','none')
   .selectAll('path').data(D.cm_edges).join('path')
    .attr('stroke',e=>eshade(e.weight)).attr('stroke-opacity',e=>0.45+0.5*((e.weight-1)/Math.max(1,maxw-1)))
    .attr('stroke-width',e=>ewidth(e.weight)).attr('marker-end','url(#arr)')
    .attr('d',e=>{const a=pos[e.source],b=pos[e.target]; if(!a||!b)return'';
      const mx=(a.x+b.x)/2; return `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`;})
    .on('mousemove',(e2,e)=>{tip.style.opacity=1;tip.style.left=(e2.pageX+10)+'px';
      tip.style.top=(e2.pageY+10)+'px';
      tip.innerHTML=`<b>${e.source}</b><br>─${e.code}→ (경로 ${e.weight}개 통과)<br><b>${e.target}</b>`;})
    .on('mouseout',()=>tip.style.opacity=0);
  const nd=g.append('g').selectAll('g').data(D.cm_nodes).join('g')
    .attr('transform',d=>`translate(${pos[d.id].x},${pos[d.id].y})`);
  nd.append('circle').attr('r',d=>5+Math.sqrt(d.pw||1)*2.2).attr('fill',d=>d.color)
    .attr('stroke','#0c0e13').attr('stroke-width',0.8)
    .on('mousemove',(e,d)=>{tip.style.opacity=1;tip.style.left=(e.pageX+10)+'px';
      tip.style.top=(e.pageY+10)+'px';tip.innerHTML=`<b>${d.id}</b><br>${d.type} · layer ${d.layer} · 경로 ${d.pw}개 통과`;})
    .on('mouseout',()=>tip.style.opacity=0);
  nd.append('text').text(d=>d.id.length>16?d.id.slice(0,15)+'…':d.id)
    .attr('x',9).attr('y',3).attr('font-size','9px').attr('fill','#cdd6e3');
})();
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
