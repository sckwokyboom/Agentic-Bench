# tests/test_rcc_path_clusters.py
from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
from abench.rcc_path_clusters import (chain_distance, cluster_chains,
                                      greedy_kmedoids, normalize_chain,
                                      weighted_lcs_distance)


def _g():
    # target put; direct caller addRow; upstream join/synopsis; several tests
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.addRow", type="method", fqn="C.addRow"),
          MgVertex(id="method:H.join", type="method", fqn="H.join"),
          MgVertex(id="method:H.syn", type="method", fqn="H.syn")]
    tests = ["HT.a1", "HT.a2", "HT.a3", "HT.join1", "HT.syn1"]
    for t in tests:
        vs.append(MgVertex(id=f"test:{t}", type="test", fqn=f"picocli.{t}"))
    es = [MgEdge(src="method:C.addRow", tgt="method:C.put", type="CALLS")]  # addRow direct caller
    # chains: three near-identical direct addRow paths, one join path, one synopsis path
    chains = [
        MgChain(id="p1", test_fqn="picocli.HT.a1",
                node_ids=["test:HT.a1", "method:C.addRow", "method:C.put"]),
        MgChain(id="p2", test_fqn="picocli.HT.a2",
                node_ids=["test:HT.a2", "method:C.addRow", "method:C.put"]),
        MgChain(id="p3", test_fqn="picocli.HT.a3",
                node_ids=["test:HT.a3", "method:C.addRow", "method:C.put"]),
        MgChain(id="p4", test_fqn="picocli.HT.join1",
                node_ids=["test:HT.join1", "method:H.join", "method:C.addRow", "method:C.put"]),
        MgChain(id="p5", test_fqn="picocli.HT.syn1",
                node_ids=["test:HT.syn1", "method:H.syn", "method:H.join",
                          "method:C.addRow", "method:C.put"]),
    ]
    return MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=chains)


def test_weighted_lcs_distance_bounds():
    g = _g()
    a = normalize_chain(g, g.chains[0])
    assert weighted_lcs_distance(a, a) == 0.0                 # identical
    b = normalize_chain(g, g.chains[3])                        # shared …addRow→put suffix
    d = weighted_lcs_distance(a, b)
    assert 0.0 < d < 1.0                                       # similar but not identical
    # disjoint sequences → ~1
    x = [("z1", 1.0), ("z2", 1.0)]
    assert weighted_lcs_distance(x, a) > 0.9


def test_greedy_kmedoids_returns_k_clusters_and_real_medoids():
    items = list("abcdef")
    dist = lambda i, j: 0.0 if i == j else abs(ord(i) - ord(j)) / 10
    clusters = greedy_kmedoids(items, dist, 3)
    assert len(clusters) == 3
    assert all(c["medoid"] in items for c in clusters)        # medoids are real items
    assert sum(len(c["members"]) for c in clusters) == len(items)


def test_cluster_chains_separates_direct_from_deep_paths():
    g = _g()
    from abench.rcc_graph_layers import annotate_status
    annotate_status(g, failed_ids={"picocli.HT.a1"})          # p1 failed; rest unknown
    res = cluster_chains(g, k_unknown=2)
    assert res["forced_paths"] == ["p1"]                      # failed force-included
    clusters = res["clusters"]
    assert len(clusters) >= 2
    # the deep synopsis path (p5) and a direct addRow path (p2/p3) are NOT in the same cluster
    def cluster_of(pid):
        return next(c["cluster_id"] for c in clusters if pid in c["member_ids"])
    assert cluster_of("p5") != cluster_of("p2")
    # each cluster summary carries a real medoid path + a readable shape
    c0 = clusters[0]
    assert c0["medoid_path_id"] in {"p2", "p3", "p4", "p5"}
    assert "put" in c0["path_shape"] and "→" in c0["path_shape"]
    assert c0["size"] >= 1 and "selection_reason" in c0


def test_weighted_lcs_distance_is_symmetric():
    g = _g()
    a = normalize_chain(g, g.chains[0])   # test → addRow → put
    b = normalize_chain(g, g.chains[4])   # test → syn → join → addRow → put
    assert abs(weighted_lcs_distance(a, b) - weighted_lcs_distance(b, a)) < 1e-9


def test_score_used_as_within_cluster_priority():
    g = _g()
    from abench.rcc_graph_layers import annotate_status
    annotate_status(g, failed_ids={"picocli.HT.a1"})
    res = cluster_chains(g, k_unknown=2)
    assert all("top_scored_test" in c for c in res["clusters"])   # score wired in
