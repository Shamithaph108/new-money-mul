/* ═══════════════════════════════════════════════════════════════
   MULLING — Financial Forensics Engine
   Frontend JS: Upload, D3 Graph, Table, JSON Export
   ═══════════════════════════════════════════════════════════════ */

// ── STATE ──────────────────────────────────────────────────────
let analysisResult = null;
let simulation     = null;
let svgRoot        = null;
let graphGroup     = null;
let zoomBehavior   = null;
let highlightRings = true;
let currentFile    = null;

// ── DOM REFS ───────────────────────────────────────────────────
const $  = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ── INIT ───────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initUpload();
});

// ══════════════════════════════════════════════════════════════
//  UPLOAD HANDLING
// ══════════════════════════════════════════════════════════════
function initUpload() {
  const dropZone  = $("#drop-zone");
  const fileInput = $("#file-input");
  const uploadBtn = $("#upload-btn");
  const analyzeBtn = $("#analyze-btn");

  // Click to browse
  dropZone.addEventListener("click", () => fileInput.click());
  uploadBtn.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });

  // File selected
  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) pickFile(e.target.files[0]);
  });

  // Drag-and-drop
  ["dragenter", "dragover"].forEach(evt =>
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); })
  );
  ["dragleave", "drop"].forEach(evt =>
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.remove("drag-over"); })
  );
  dropZone.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) pickFile(e.dataTransfer.files[0]);
  });

  // Analyze
  analyzeBtn.addEventListener("click", runAnalysis);
}

function pickFile(file) {
  if (!file.name.endsWith(".csv")) {
    showToast("Please upload a .csv file");
    return;
  }
  currentFile = file;
  const info = $(".file-info");
  info.classList.add("show");
  info.textContent = `📎 ${file.name}  (${(file.size/1024).toFixed(1)} KB)`;
  $("#analyze-btn").style.display = "inline-flex";
}

async function runAnalysis() {
  if (!currentFile) return;
  showLoader(true);

  const form = new FormData();
  form.append("file", currentFile);

  try {
    const res = await fetch("/api/analyze", { method: "POST", body: form });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    analysisResult = data;
    renderResults(data);
  } catch (err) {
    showToast(err.message || "Analysis failed");
  } finally {
    showLoader(false);
  }
}

// ══════════════════════════════════════════════════════════════
//  RENDER RESULTS
// ══════════════════════════════════════════════════════════════
function renderResults(data) {
  // Compact upload
  $(".upload-section").classList.add("compact");
  const results = $(".results-section");
  results.classList.add("show");

  // Stats
  renderStats(data.summary);

  // Graph
  renderGraph(data.graph, data.fraud_rings);

  // Table
  renderRingTable(data.fraud_rings);

  // Wire action buttons
  $("#btn-download-json").addEventListener("click", downloadJSON);
  $("#btn-reset").addEventListener("click", resetApp);
}

function renderStats(summary) {
  $("#stat-accounts").textContent   = summary.total_accounts_analyzed;
  $("#stat-suspicious").textContent = summary.suspicious_accounts_flagged;
  $("#stat-rings").textContent      = summary.fraud_rings_detected;
  $("#stat-time").textContent       = summary.processing_time_seconds + "s";
}

// ══════════════════════════════════════════════════════════════
//  D3 FORCE GRAPH
// ══════════════════════════════════════════════════════════════
function renderGraph(graphData, rings) {
  const container = $("#graph-canvas");
  container.innerHTML = "";

  const width  = container.clientWidth;
  const height = container.clientHeight || 550;

  // Build ring membership lookup
  const ringMap = {};
  rings.forEach(r => r.member_accounts.forEach(a => {
    if (!ringMap[a]) ringMap[a] = [];
    ringMap[a].push(r.ring_id);
  }));

  // Color scale for rings
  const ringColors = {};
  const palette = ["#ef4444","#f59e0b","#a855f7","#ec4899","#f97316","#14b8a6","#6366f1","#84cc16"];
  rings.forEach((r, i) => { ringColors[r.ring_id] = palette[i % palette.length]; });

  const nodes = graphData.nodes.map(d => ({...d}));
  const links = graphData.edges.map(d => ({...d}));

  // SVG
  svgRoot = d3.select(container)
    .append("svg")
    .attr("width", width)
    .attr("height", height);

  // Defs → arrowheads
  const defs = svgRoot.append("defs");
  defs.append("marker")
    .attr("id", "arrow-normal")
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 22)
    .attr("refY", 0)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M0,-5L10,0L0,5")
    .attr("fill", "#334155");

  defs.append("marker")
    .attr("id", "arrow-suspicious")
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 28)
    .attr("refY", 0)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M0,-5L10,0L0,5")
    .attr("fill", "#ef4444");

  // Zoom
  zoomBehavior = d3.zoom()
    .scaleExtent([0.1, 8])
    .on("zoom", (event) => graphGroup.attr("transform", event.transform));
  svgRoot.call(zoomBehavior);

  graphGroup = svgRoot.append("g");

  // Links
  const link = graphGroup.append("g")
    .selectAll("line")
    .data(links)
    .join("line")
    .attr("stroke", d => {
      const srcSus = nodes.find(n => n.id === d.source || n.id === d.source?.id)?.suspicious;
      const tgtSus = nodes.find(n => n.id === d.target || n.id === d.target?.id)?.suspicious;
      return (srcSus && tgtSus) ? "#ef444466" : "#334155";
    })
    .attr("stroke-width", d => Math.min(Math.max(1, Math.sqrt(d.count)), 4))
    .attr("marker-end", d => {
      const srcSus = nodes.find(n => n.id === d.source || n.id === d.source?.id)?.suspicious;
      const tgtSus = nodes.find(n => n.id === d.target || n.id === d.target?.id)?.suspicious;
      return (srcSus && tgtSus) ? "url(#arrow-suspicious)" : "url(#arrow-normal)";
    });

  // Nodes
  const node = graphGroup.append("g")
    .selectAll("g")
    .data(nodes)
    .join("g")
    .call(d3.drag()
      .on("start", dragStart)
      .on("drag", dragging)
      .on("end", dragEnd));

  // Glow ring for suspicious
  node.filter(d => d.suspicious)
    .append("circle")
    .attr("r", d => nodeRadius(d) + 5)
    .attr("fill", "none")
    .attr("stroke", d => {
      const rids = ringMap[d.id] || [];
      return rids.length ? ringColors[rids[0]] : "#ef4444";
    })
    .attr("stroke-width", 2)
    .attr("stroke-dasharray", "4 2")
    .attr("opacity", 0.7)
    .classed("glow-ring", true);

  // Main circle
  node.append("circle")
    .attr("r", d => nodeRadius(d))
    .attr("fill", d => {
      if (!d.suspicious) return "#3b82f6";
      const rids = ringMap[d.id] || [];
      return rids.length ? ringColors[rids[0]] : "#ef4444";
    })
    .attr("stroke", d => d.suspicious ? "#fff" : "#1e293b")
    .attr("stroke-width", d => d.suspicious ? 2 : 1)
    .attr("opacity", d => d.suspicious ? 1 : 0.7);

  // Labels for suspicious
  node.filter(d => d.suspicious)
    .append("text")
    .text(d => d.id.length > 12 ? d.id.slice(-8) : d.id)
    .attr("text-anchor", "middle")
    .attr("dy", d => nodeRadius(d) + 14)
    .attr("fill", "#94a3b8")
    .attr("font-size", "8px")
    .attr("font-family", "'JetBrains Mono', monospace");

  // Tooltip
  const tooltip = $(".node-tooltip");
  node.on("mouseenter", (event, d) => {
    tooltip.innerHTML = buildTooltip(d, ringMap);
    tooltip.classList.add("visible");
  }).on("mousemove", (event) => {
    tooltip.style.left = (event.clientX + 14) + "px";
    tooltip.style.top  = (event.clientY - 10) + "px";
  }).on("mouseleave", () => {
    tooltip.classList.remove("visible");
  });

  // Simulation
  simulation = d3.forceSimulation(nodes)
    .force("link",    d3.forceLink(links).id(d => d.id).distance(80))
    .force("charge",  d3.forceManyBody().strength(-120))
    .force("center",  d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide().radius(d => nodeRadius(d) + 8))
    .on("tick", () => {
      link
        .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

  // Toolbar wiring
  $("#btn-zoom-in").onclick  = () => svgRoot.transition().call(zoomBehavior.scaleBy, 1.4);
  $("#btn-zoom-out").onclick = () => svgRoot.transition().call(zoomBehavior.scaleBy, 0.7);
  $("#btn-zoom-fit").onclick = () => svgRoot.transition().call(zoomBehavior.transform, d3.zoomIdentity);
  $("#btn-toggle-rings").onclick = () => {
    highlightRings = !highlightRings;
    d3.selectAll(".glow-ring").attr("opacity", highlightRings ? 0.7 : 0);
    $("#btn-toggle-rings").classList.toggle("active", highlightRings);
  };
}

function nodeRadius(d) {
  if (d.suspicious) return 8 + Math.min(d.score / 10, 6);
  return 4 + Math.min(d.tx_count, 6);
}

function buildTooltip(d, ringMap) {
  const rids = (ringMap[d.id] || []).join(", ") || "—";
  return `
    <div class="tooltip-row"><span class="tooltip-label">Account</span><span class="tooltip-val">${d.id}</span></div>
    <div class="tooltip-row"><span class="tooltip-label">Total Sent</span><span class="tooltip-val">$${d.total_sent.toLocaleString()}</span></div>
    <div class="tooltip-row"><span class="tooltip-label">Total Recv</span><span class="tooltip-val">$${d.total_received.toLocaleString()}</span></div>
    <div class="tooltip-row"><span class="tooltip-label">Transactions</span><span class="tooltip-val">${d.tx_count}</span></div>
    <div class="tooltip-row"><span class="tooltip-label">Suspicious</span><span class="tooltip-val ${d.suspicious ? 'danger' : 'safe'}">${d.suspicious ? 'YES — ' + d.score.toFixed(1) : 'NO'}</span></div>
    <div class="tooltip-row"><span class="tooltip-label">Rings</span><span class="tooltip-val">${rids}</span></div>
  `;
}

// Drag handlers
function dragStart(event, d) {
  if (!event.active) simulation.alphaTarget(0.3).restart();
  d.fx = d.x; d.fy = d.y;
}
function dragging(event, d) { d.fx = event.x; d.fy = event.y; }
function dragEnd(event, d) {
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null; d.fy = null;
}

// ══════════════════════════════════════════════════════════════
//  RING TABLE
// ══════════════════════════════════════════════════════════════
function renderRingTable(rings) {
  const tbody = $("#ring-table-body");
  tbody.innerHTML = "";

  if (!rings.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">No fraud rings detected</td></tr>';
    return;
  }

  rings.forEach(r => {
    const riskClass = r.risk_score >= 80 ? "risk-high" : (r.risk_score >= 50 ? "risk-med" : "risk-low");
    const badgeClass = r.pattern_type === "cycle" ? "badge-cycle" :
                       r.pattern_type === "smurfing" ? "badge-smurfing" :
                       r.pattern_type === "layering" ? "badge-layering" : "badge-cycle";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="color:var(--accent-cyan);font-weight:600">${r.ring_id}</td>
      <td><span class="badge ${badgeClass}">${r.pattern_type}</span></td>
      <td>${r.member_accounts.length}</td>
      <td class="${riskClass}">
        <span class="risk-bar"><span class="risk-bar-fill" style="width:${r.risk_score}%"></span></span>
        ${r.risk_score}
      </td>
      <td><div class="members-scroll">${r.member_accounts.join(", ")}</div></td>
    `;
    tbody.appendChild(tr);
  });
}

// ══════════════════════════════════════════════════════════════
//  JSON DOWNLOAD
// ══════════════════════════════════════════════════════════════
function downloadJSON() {
  if (!analysisResult) return;
  const output = {
    suspicious_accounts: analysisResult.suspicious_accounts,
    fraud_rings: analysisResult.fraud_rings,
    summary: analysisResult.summary,
  };
  const blob = new Blob([JSON.stringify(output, null, 2)], { type: "application/json" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = "forensics_report.json";
  a.click();
  URL.revokeObjectURL(url);
}

// ══════════════════════════════════════════════════════════════
//  HELPERS
// ══════════════════════════════════════════════════════════════
function showLoader(on) {
  $(".loader-overlay").classList.toggle("active", on);
}

function showToast(msg) {
  const t = $(".toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 4000);
}

function resetApp() {
  currentFile    = null;
  analysisResult = null;
  $(".results-section").classList.remove("show");
  $(".upload-section").classList.remove("compact");
  $(".file-info").classList.remove("show");
  $("#analyze-btn").style.display = "none";
  $("#file-input").value = "";
  if (simulation) simulation.stop();
  $("#graph-canvas").innerHTML = "";
}

