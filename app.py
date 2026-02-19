"""
Financial Forensics Engine — Money Muling Detection
Flask backend with graph-based fraud detection algorithms.
"""

import os
import io
import json
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import combinations

import pandas as pd
import networkx as nx
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

# ──────────────────────────────────────────────────────────────
#  ROUTES
# ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    start = time.time()

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "Only CSV files are accepted"}), 400

    try:
        raw = file.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(raw))
    except Exception as e:
        return jsonify({"error": f"Failed to parse CSV: {str(e)}"}), 400

    required = {"transaction_id", "sender_id", "receiver_id", "amount", "timestamp"}
    if not required.issubset(set(df.columns)):
        return jsonify({"error": f"Missing columns. Required: {required}"}), 400

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df.dropna(subset=["sender_id", "receiver_id", "amount", "timestamp"], inplace=True)

    engine = ForensicsEngine(df)
    result = engine.run()
    result["summary"]["processing_time_seconds"] = round(float(time.time() - start), 2)

    # Use json.dumps to guarantee field order from OrderedDicts
    json_str = json.dumps(result, ensure_ascii=False, indent=None)
    return Response(json_str, mimetype="application/json")


# ──────────────────────────────────────────────────────────────
#  DETECTION ENGINE
# ──────────────────────────────────────────────────────────────

class ForensicsEngine:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.G = nx.DiGraph()
        self.rings: list[dict] = []
        self.suspicious: dict[str, dict] = {}   # account_id → info
        self.ring_counter = 0
        self._build_graph()

    # ── graph construction ────────────────────────────────────
    def _build_graph(self):
        for _, row in self.df.iterrows():
            s, r = str(row["sender_id"]), str(row["receiver_id"])
            amt = float(row["amount"])
            ts = row["timestamp"]

            if not self.G.has_node(s):
                self.G.add_node(s, total_sent=0.0, total_received=0.0,
                                tx_count=0, send_count=0, recv_count=0,
                                senders=set(), receivers=set(),
                                timestamps=[])
            if not self.G.has_node(r):
                self.G.add_node(r, total_sent=0.0, total_received=0.0,
                                tx_count=0, send_count=0, recv_count=0,
                                senders=set(), receivers=set(),
                                timestamps=[])

            self.G.nodes[s]["total_sent"] += amt
            self.G.nodes[s]["tx_count"] += 1
            self.G.nodes[s]["send_count"] += 1
            self.G.nodes[s]["receivers"].add(r)
            self.G.nodes[s]["timestamps"].append(ts)

            self.G.nodes[r]["total_received"] += amt
            self.G.nodes[r]["tx_count"] += 1
            self.G.nodes[r]["recv_count"] += 1
            self.G.nodes[r]["senders"].add(s)
            self.G.nodes[r]["timestamps"].append(ts)

            if self.G.has_edge(s, r):
                self.G[s][r]["weight"] += amt
                self.G[s][r]["count"] += 1
                self.G[s][r]["timestamps"].append(ts)
            else:
                self.G.add_edge(s, r, weight=amt, count=1, timestamps=[ts])

    # ── helpers ───────────────────────────────────────────────
    def _next_ring_id(self):
        self.ring_counter += 1
        return f"RING_{self.ring_counter:03d}"

    def _is_merchant_or_payroll(self, node: str) -> bool:
        """Heuristic: high-volume with many unique senders but low unique
        receivers is likely a merchant; high fan-out to many receivers
        with regular amounts is likely payroll."""
        d = self.G.nodes[node]
        senders_count = len(d["senders"])
        receivers_count = len(d["receivers"])
        tx = d["tx_count"]

        # Merchant pattern: receives from 20+ unique senders, sends to <=3
        if senders_count >= 20 and receivers_count <= 3:
            return True

        # Payroll pattern: sends to 20+ unique receivers, receives from <=3
        if receivers_count >= 20 and senders_count <= 3:
            # Check if amounts are regular (low variance)
            out_edges = self.G.out_edges(node, data=True)
            amounts = []
            for _, _, ed in out_edges:
                amounts.append(ed["weight"] / max(ed["count"], 1))
            if len(amounts) >= 10:
                mean_a = sum(amounts) / len(amounts)
                if mean_a > 0:
                    variance = sum((a - mean_a) ** 2 for a in amounts) / len(amounts)
                    cv = (variance ** 0.5) / mean_a
                    if cv < 0.25:  # very regular amounts → payroll
                        return True
        return False

    def _flag_account(self, account_id: str, pattern: str, ring_id: str,
                      base_score: float):
        if account_id not in self.suspicious:
            self.suspicious[account_id] = {
                "account_id": account_id,
                "suspicion_score": 0.0,
                "detected_patterns": [],
                "ring_id": ring_id,
            }
        entry = self.suspicious[account_id]
        if pattern not in entry["detected_patterns"]:
            entry["detected_patterns"].append(pattern)
        # accumulate score, cap at 100
        entry["suspicion_score"] = min(100.0, entry["suspicion_score"] + base_score)
        # keep the ring with the higher implicit priority (first assigned wins)
        if not entry["ring_id"]:
            entry["ring_id"] = ring_id

    # ── 1. Cycle Detection (length 3-5) ──────────────────────
    def detect_cycles(self):
        found_cycles: list[tuple] = []
        nodes = list(self.G.nodes())

        # Use simple_cycles but limit to length 3-5
        try:
            for cyc in nx.simple_cycles(self.G, length_bound=5):
                if 3 <= len(cyc) <= 5:
                    # Normalise: rotate so smallest element first
                    canon = self._canonicalize_cycle(cyc)
                    if canon not in found_cycles:
                        found_cycles.append(canon)
        except Exception:
            # Fallback: DFS-based cycle detection
            found_cycles = self._dfs_cycles(nodes)

        # Deduplicate and register rings
        seen_sets = []
        for cyc in found_cycles:
            s = frozenset(cyc)
            if s in seen_sets:
                continue
            seen_sets.append(s)

            ring_id = self._next_ring_id()
            cycle_len = len(cyc)

            # Compute ring risk score
            total_flow = 0.0
            for i in range(len(cyc)):
                s_node, r_node = cyc[i], cyc[(i + 1) % len(cyc)]
                if self.G.has_edge(s_node, r_node):
                    total_flow += self.G[s_node][r_node]["weight"]

            risk = min(100.0, 60.0 + (total_flow / max(len(cyc), 1)) * 0.005 + cycle_len * 5)

            self.rings.append({
                "ring_id": ring_id,
                "member_accounts": list(cyc),
                "pattern_type": "cycle",
                "risk_score": round(risk, 1),
            })

            for acc in cyc:
                if not self._is_merchant_or_payroll(acc):
                    self._flag_account(acc, f"cycle_length_{cycle_len}", ring_id,
                                       base_score=float(40.0 + cycle_len * 5))

    @staticmethod
    def _canonicalize_cycle(cyc):
        min_idx = cyc.index(min(cyc))
        return tuple(cyc[min_idx:] + cyc[:min_idx])

    def _dfs_cycles(self, nodes):
        cycles = []
        for start in nodes:
            visited = {start: [start]}
            stack = [(start, [start], 0)]
            while stack:
                curr, path, depth = stack.pop()
                if depth >= 5:
                    continue
                for nbr in self.G.successors(curr):
                    if nbr == start and len(path) >= 3:
                        cycles.append(self._canonicalize_cycle(path))
                    elif nbr not in visited and depth < 4:
                        visited[nbr] = path + [nbr]
                        stack.append((nbr, path + [nbr], depth + 1))
        return cycles

    # ── 2. Smurfing Detection (Fan-in / Fan-out) ─────────────
    def detect_smurfing(self):
        for node in self.G.nodes():
            if self._is_merchant_or_payroll(node):
                continue

            d = self.G.nodes[node]
            in_degree = self.G.in_degree(node)
            out_degree = self.G.out_degree(node)
            senders_count = len(d["senders"])
            receivers_count = len(d["receivers"])

            # Fan-in: 10+ unique senders → 1 receiver
            if senders_count >= 10:
                # Temporal window analysis
                in_edges = list(self.G.in_edges(node, data=True))
                temporal_score = self._temporal_concentration(in_edges)
                base = 35.0 + min(senders_count, 50) * 0.6 + temporal_score * 15
                ring_id = self._next_ring_id()

                members = [node] + list(d["senders"])
                members = [m for m in members if not self._is_merchant_or_payroll(m)]

                if len(members) >= 3:
                    self.rings.append({
                        "ring_id": ring_id,
                        "member_accounts": members,
                        "pattern_type": "smurfing",
                        "risk_score": round(float(min(100.0, base)), 1),
                    })
                    for acc in members:
                        patterns = ["fan_in"]
                        if temporal_score > 0.5:
                            patterns.append("high_velocity")
                        for pat in patterns:
                            self._flag_account(acc, pat, ring_id, base_score=float(base * 0.7 / len(patterns)))

            # Fan-out: 1 sender → 10+ receivers
            if receivers_count >= 10:
                out_edges = list(self.G.out_edges(node, data=True))
                temporal_score = self._temporal_concentration(out_edges)
                base = 35.0 + min(receivers_count, 50) * 0.6 + temporal_score * 15
                ring_id = self._next_ring_id()

                members = [node] + list(d["receivers"])
                members = [m for m in members if not self._is_merchant_or_payroll(m)]

                if len(members) >= 3:
                    self.rings.append({
                        "ring_id": ring_id,
                        "member_accounts": members,
                        "pattern_type": "smurfing",
                        "risk_score": round(float(min(100.0, base)), 1),
                    })
                    for acc in members:
                        patterns = ["fan_out"]
                        if temporal_score > 0.5:
                            patterns.append("high_velocity")
                        for pat in patterns:
                            self._flag_account(acc, pat, ring_id, base_score=float(base * 0.7 / len(patterns)))

    def _temporal_concentration(self, edges) -> float:
        """Return 0-1 score for how concentrated timestamps are within 72h windows."""
        all_ts = []
        for edge in edges:
            edata = edge[2] if len(edge) == 3 else edge
            if "timestamps" in edata:
                all_ts.extend(edata["timestamps"])
        if len(all_ts) < 3:
            return 0.0
        all_ts.sort()
        window = timedelta(hours=72)
        max_in_window = 0
        for i, ts in enumerate(all_ts):
            count = sum(1 for t in all_ts[i:] if t - ts <= window)
            max_in_window = max(max_in_window, count)
        return min(1.0, max_in_window / len(all_ts))

    # ── 3. Layered Shell Network Detection ────────────────────
    def detect_shell_networks(self):
        # Find nodes with low transaction counts (2-3)
        shell_candidates = set()
        for node in self.G.nodes():
            tc = self.G.nodes[node]["tx_count"]
            if 2 <= tc <= 3:
                shell_candidates.add(node)

        if not shell_candidates:
            return

        # Find chains of 3+ hops through shell accounts
        visited_chains: list[frozenset] = []
        for start in self.G.nodes():
            if start in shell_candidates:
                continue
            # BFS to find chains through shell nodes
            self._find_shell_chains(start, shell_candidates, visited_chains)

    def _find_shell_chains(self, start, shell_candidates, visited_chains):
        stack = [(start, [start], 0)]
        while stack:
            curr, path, shell_count = stack.pop()
            if len(path) > 6:
                continue
            for succ in self.G.successors(curr):
                if succ in path:
                    continue
                new_path = path + [succ]
                new_shell = shell_count + (1 if succ in shell_candidates else 0)
                # Chain of 3+ hops where intermediates are shells
                intermediates = new_path[1:-1]
                if (len(new_path) >= 4 and
                        len(intermediates) >= 2 and
                        sum(1 for n in intermediates if n in shell_candidates) >= len(intermediates) * 0.6):
                    chain_set = frozenset(new_path)
                    if chain_set not in visited_chains:
                        visited_chains.append(chain_set)
                        ring_id = self._next_ring_id()
                        members = list(new_path)
                        shell_members = [n for n in intermediates if n in shell_candidates]

                        risk = min(100.0, 50.0 + len(shell_members) * 10 + len(new_path) * 3)
                        self.rings.append({
                            "ring_id": ring_id,
                            "member_accounts": members,
                            "pattern_type": "layering",
                            "risk_score": round(float(risk), 1),
                        })
                        for acc in members:
                            if not self._is_merchant_or_payroll(acc):
                                pat = "shell_intermediate" if acc in shell_candidates else "shell_endpoint"
                                self._flag_account(acc, pat, ring_id, base_score=float(30.0 + len(shell_members) * 5))
                if len(new_path) < 7:
                    stack.append((succ, new_path, new_shell))

    # ── Additional: High Velocity Detection ───────────────────
    def detect_high_velocity(self):
        """Flag accounts with suspiciously high transaction velocity."""
        for node in self.G.nodes():
            if self._is_merchant_or_payroll(node):
                continue
            d = self.G.nodes[node]
            ts_list = sorted(d["timestamps"])
            if len(ts_list) < 5:
                continue
            # Transactions per hour
            span = (ts_list[-1] - ts_list[0]).total_seconds()
            if span <= 0:
                span = 1
            tx_per_hour = len(ts_list) / (span / 3600)
            if tx_per_hour > 5:  # More than 5 tx/hour sustained
                if node in self.suspicious:
                    self.suspicious[node]["detected_patterns"].append("high_velocity")
                    self.suspicious[node]["suspicion_score"] = min(
                        100.0, self.suspicious[node]["suspicion_score"] + 15)

    # ── Run all detections ────────────────────────────────────
    def run(self) -> dict:
        self.detect_cycles()
        self.detect_smurfing()
        self.detect_shell_networks()
        self.detect_high_velocity()

        # ── Fix #3: Deduplicate ring membership ──────────────
        # Each account belongs to exactly ONE ring (the first / highest-priority one).
        # Remove accounts from later rings if already claimed.
        claimed_accounts: dict[str, str] = {}  # account_id → ring_id
        deduped_rings = []
        for ring in self.rings:
            unique_members = []
            for acc in ring["member_accounts"]:
                if acc not in claimed_accounts:
                    claimed_accounts[acc] = ring["ring_id"]
                    unique_members.append(acc)
            if len(unique_members) >= 2:
                ring["member_accounts"] = unique_members
                deduped_rings.append(ring)
        self.rings = deduped_rings

        # Update suspicious account ring_id to match their claimed ring
        for acc_id, entry in self.suspicious.items():
            if acc_id in claimed_accounts:
                entry["ring_id"] = claimed_accounts[acc_id]

        # Remove suspicious accounts that no longer belong to any ring
        self.suspicious = {k: v for k, v in self.suspicious.items()
                          if k in claimed_accounts}

        # ── Fix #1: Enforce exact field order ────────────────
        # ── Fix #4: Ensure all scores are proper floats ──────
        sus_list_raw = sorted(self.suspicious.values(),
                              key=lambda x: x["suspicion_score"], reverse=True)
        sus_list = []
        for s in sus_list_raw:
            sus_list.append(OrderedDict([
                ("account_id",       s["account_id"]),
                ("suspicion_score",  round(float(s["suspicion_score"]), 1)),
                ("detected_patterns", s["detected_patterns"]),
                ("ring_id",          s["ring_id"]),
            ]))

        # Enforce field order in fraud_rings too
        ordered_rings = []
        for r in self.rings:
            ordered_rings.append(OrderedDict([
                ("ring_id",          r["ring_id"]),
                ("member_accounts",  r["member_accounts"]),
                ("pattern_type",     r["pattern_type"]),
                ("risk_score",       round(float(r["risk_score"]), 1)),
            ]))

        # Build graph data for visualization
        nodes_data = []
        suspicious_ids = set(self.suspicious.keys())
        ring_membership = defaultdict(list)
        for ring in self.rings:
            for acc in ring["member_accounts"]:
                ring_membership[acc].append(ring["ring_id"])

        for node in self.G.nodes():
            d = self.G.nodes[node]
            nodes_data.append({
                "id": node,
                "total_sent": round(d["total_sent"], 2),
                "total_received": round(d["total_received"], 2),
                "tx_count": d["tx_count"],
                "suspicious": node in suspicious_ids,
                "rings": ring_membership.get(node, []),
                "score": round(float(self.suspicious[node]["suspicion_score"]), 1) if node in self.suspicious else 0.0,
            })

        edges_data = []
        for u, v, d in self.G.edges(data=True):
            edges_data.append({
                "source": u,
                "target": v,
                "amount": round(d["weight"], 2),
                "count": d["count"],
            })

        ordered_summary = OrderedDict([
            ("total_accounts_analyzed",  self.G.number_of_nodes()),
            ("suspicious_accounts_flagged", len(sus_list)),
            ("fraud_rings_detected",     len(ordered_rings)),
            ("processing_time_seconds",  0),  # filled by route
        ])

        return {
            "suspicious_accounts": sus_list,
            "fraud_rings": ordered_rings,
            "summary": ordered_summary,
            "graph": {
                "nodes": nodes_data,
                "edges": edges_data,
            },
        }


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)

