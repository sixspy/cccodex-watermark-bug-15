(() => {
  const view = document.getElementById("view");
  const msgEl = document.getElementById("msg");
  let tab = "batches";
  let templates = [];
  let batches = [];
  let reports = [];
  let selected = null;
  let stampValue = "";
  let traceValue = "WM-ORD-131";
  let traceResult = null;
  let overview = null;
  let gateInfo = null;

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (r.status === 401) {
      location.href = "/login";
      throw new Error("未登录");
    }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  function setMsg(t) {
    msgEl.textContent = t || "";
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  async function refresh() {
    const meta = await api("/api/meta");
    document.getElementById("lab-name").textContent = meta.lab_name || "血缘水印台";
    templates = (await api("/api/templates")).items || [];
    batches = (await api("/api/batches")).items || [];
    reports = (await api("/api/gap-reports")).items || [];
    overview = await api("/api/release/overview");
    gateInfo = await api("/api/gate");
  }

  function syncDock() {
    document.querySelectorAll(".dock [data-tab]").forEach((btn) => {
      btn.classList.toggle("on", btn.dataset.tab === tab);
    });
  }

  function renderTemplates() {
    return `
      <h2>水印模板</h2>
      <table>
        <thead><tr><th>表</th><th>列</th><th>版本</th><th>状态</th></tr></thead>
        <tbody>
          ${templates
            .map(
              (t) => `<tr>
            <td>${esc(t.table_name)}</td>
            <td>${esc(t.column_name)}</td>
            <td>${t.version_no}</td>
            <td><span class="chip">${esc(t.status)}</span></td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function renderBatches() {
    return `
      <h2>运行批次</h2>
      <p class="muted">主链：选批盖印 → 用水印追索下游 → 缺口对账</p>
      <table>
        <thead><tr><th>编号</th><th>表</th><th>运行码</th><th>业务日</th><th>状态</th><th>水印</th><th></th></tr></thead>
        <tbody>
          ${batches
            .map(
              (b) => `<tr>
            <td>${b.id}</td>
            <td>${esc(b.table_name)}</td>
            <td>${esc(b.run_code)}</td>
            <td>${esc(b.biz_date)}</td>
            <td><span class="chip">${esc(b.status)}</span></td>
            <td>${esc(b.watermark_value) || "-"}</td>
            <td>${
              b.status === "待盖印"
                ? `<button type="button" class="ghost" data-pick="${b.id}">盖印</button>`
                : ""
            }</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>
      ${
        selected
          ? `<div class="cardish">
        <h3>盖印</h3>
        <p>${esc(selected.run_code)} · ${esc(selected.table_name)}</p>
        <label>水印值<input id="stamp-input" value="${esc(stampValue)}" /></label>
        <button type="button" id="btn-stamp">写入盖印</button>
      </div>`
          : ""
      }`;
  }

  function gateChip(gate) {
    if (!gate) return `<span class="chip chip-warn">门槛未加载</span>`;
    return `<span class="chip chip-gate" title="sha256 ${esc(gate.sha256)}">门槛 ${
      esc(gate.gate_id)
    } v${gate.gate_version} · ${esc(gate.credential)}</span>`;
  }

  function renderGateDirectory() {
    const gate = (overview && overview.gate) || (gateInfo && gateInfo.gate);
    const history = (overview && overview.gate_history) ||
      (gateInfo && gateInfo.history) || [];
    return `
      <section class="panel">
        <h3>闸口目录</h3>
        <div class="row">${gateChip(gate)}</div>
        ${
          gate
            ? `<p class="muted">${esc(gate.title)} · 要求 ${esc(
                gate.requirement
              )} · 文件摘要 ${esc(gate.sha256.slice(0, 16))}…</p>`
            : ""
        }
        <h4>只读历史门槛</h4>
        ${
          history.length
            ? `<ul class="history">${history
                .map(
                  (h) =>
                    `<li><span class="chip chip-history">${esc(
                      h.gate_id
                    )} v${h.gate_version}</span> ${esc(h.title)} <span class="muted">（${
                      esc(h.retired_reason || h.description)
                    }）</span></li>`
                )
                .join("")}</ul>`
            : `<p class="muted">无历史门槛</p>`
        }
      </section>`;
  }

  function renderStampCard() {
    const stamps = (overview && overview.stamps) || [];
    return `
      <section class="panel">
        <h3>印记值卡片</h3>
        <table>
          <thead><tr><th>运行码</th><th>表</th><th>印记值</th><th>状态</th></tr></thead>
          <tbody>
            ${stamps
              .map(
                (s) => `<tr class="${s.missing ? "row-missing" : ""}">
              <td>${esc(s.run_code)}</td>
              <td>${esc(s.table_name)}</td>
              <td>${s.missing ? `<span class="miss-tag">缺印</span>` : esc(s.watermark_value)}</td>
              <td><span class="chip">${esc(s.status)}</span></td>
            </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </section>`;
  }

  function renderDownstreamAppendix() {
    const rows = (overview && overview.downstream) || [];
    return `
      <section class="panel">
        <h3>下游表附页</h3>
        ${
          rows.length
            ? `<table>
          <thead><tr><th>运行码</th><th>表</th><th>齐检</th><th>缺印</th><th>放行</th><th></th></tr></thead>
          <tbody>
            ${rows
              .map(
                (r) => `<tr class="${r.qi_complete ? "" : "row-missing"}">
              <td>${esc(r.run_code)}</td>
              <td>${esc(r.table_name)}</td>
              <td><span class="chip ${r.qi_complete ? "chip-ok" : "chip-bad"}">${
                  r.qi_complete ? "齐检齐备" : "缺印"
                }</span></td>
              <td>${
                r.missing.length
                  ? r.missing
                      .map(
                        (m) =>
                          `<span class="miss-tag">${esc(m.run_code)}</span>`
                      )
                      .join(" ")
                  : "-"
              }</td>
              <td>${
                r.released
                  ? `<span class="chip chip-gate">${esc(
                      r.release && r.release.credential
                    )}</span>`
                  : `<span class="chip">未放行</span>`
              }</td>
              <td>${
                r.released
                  ? ""
                  : `<button type="button" class="ghost" data-release="${esc(
                      r.run_code
                    )}">放行</button>`
              }</td>
            </tr>`
              )
              .join("")}
          </tbody>
        </table>`
            : `<p class="muted">暂无下游表</p>`
        }
      </section>`;
  }

  function renderReleaseProgress() {
    const rows = (overview && overview.progress) || [];
    const stop = overview && overview.stop;
    return `
      <section class="panel">
        <h3>放行进度</h3>
        ${
          stop
            ? `<p class="stop-line">齐印与可放行不同源，已自动停止放行，请核查。</p>`
            : ""
        }
        <div class="progress-list">
          ${
            rows.length
              ? rows
                  .map(
                    (r) => `<div class="progress-row ${
                      r.qi_complete === false ? "row-missing" : ""
                    }">
                <span class="dot ${r.qi_complete === false ? "dot-bad" : "dot-ok"}"></span>
                <strong>${esc(r.run_code)}</strong>
                ${gateChip({
                  gate_id: r.gate_id,
                  gate_version: r.gate_version,
                  credential: r.credential,
                  sha256: r.gate_sha256,
                })}
                <span class="muted">${esc(r.released_at)}</span>
              </div>`
                  )
                  .join("")
              : `<p class="muted">尚未放行任何批次</p>`
          }
        </div>
      </section>`;
  }

  function renderGate() {
    return `
      <h2>齐检闸口</h2>
      <p class="muted">闸口目录、印记值卡片、下游表附页、放行进度四处同看，齐印与可放行同源。</p>
      ${renderGateDirectory()}
      ${renderStampCard()}
      ${renderDownstreamAppendix()}
      ${renderReleaseProgress()}`;
  }

  function renderTrace() {
    const src = (traceResult && traceResult.sources) || [];
    const down = (traceResult && traceResult.downstream) || [];
    const withheld = (traceResult && traceResult.withheld) || [];
    return `
      <h2>下游追索</h2>
      <label>水印值<input id="trace-input" value="${esc(traceValue)}" placeholder="例如 WM-ORD-131" /></label>
      <div class="row"><button type="button" id="btn-trace">追索</button></div>
      ${
        traceResult
          ? `<div>
        <h3>源批次</h3>
        <ul>${src
          .map((s) => `<li>${esc(s.run_code)} · ${esc(s.table_name)}</li>`)
          .join("")}</ul>
        <h3>下游</h3>
        <ul>${down
          .map(
            (d) =>
              `<li>${esc(d.run_code)} · ${esc(d.status)} · ${
                d.qi_complete ? "齐检齐备" : "缺印"
              } · ${d.released ? "已放行" : "未放行"}</li>`
          )
          .join("")}</ul>
        ${
          withheld.length
            ? `<div class="stop-line">复验拦下 ${withheld.length} 条缺印放行记录：${esc(
                withheld.map((w) => w.run_code).join("、")
              )}</div>`
            : ""
        }
      </div>`
          : ""
      }`;
  }

  function renderGaps() {
    return `
      <h2>缺口对账</h2>
      <button type="button" id="btn-gap">生成对账</button>
      <table>
        <thead><tr><th>编号</th><th>截至</th><th>缺口</th><th>摘要</th></tr></thead>
        <tbody>
          ${reports
            .map(
              (r) => `<tr>
            <td>${r.id}</td>
            <td>${esc(r.as_of_date)}</td>
            <td>${r.gap_count}</td>
            <td>${esc(r.summary)}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function render() {
    if (tab === "templates") view.innerHTML = renderTemplates();
    else if (tab === "batches") view.innerHTML = renderBatches();
    else if (tab === "trace") view.innerHTML = renderTrace();
    else if (tab === "gate") view.innerHTML = renderGate();
    else view.innerHTML = renderGaps();

    view.querySelectorAll("[data-pick]").forEach((btn) => {
      btn.onclick = () => {
        const id = Number(btn.dataset.pick);
        selected = batches.find((b) => b.id === id) || null;
        stampValue = selected ? "WM-" + selected.run_code.toUpperCase() : "";
        render();
      };
    });
    const stampInput = document.getElementById("stamp-input");
    if (stampInput) {
      stampInput.oninput = () => (stampValue = stampInput.value);
      document.getElementById("btn-stamp").onclick = async () => {
        setMsg("");
        try {
          await api("/api/batches/" + selected.id + "/stamp", {
            method: "POST",
            body: JSON.stringify({ watermark_value: stampValue }),
          });
          selected = null;
          await refresh();
          setMsg("盖印完成");
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    }
    view.querySelectorAll("[data-release]").forEach((btn) => {
      btn.onclick = async () => {
        setMsg("");
        const row = ((overview && overview.downstream) || []).find(
          (r) => r.run_code === btn.dataset.release
        );
        try {
          const res = await api("/api/release", {
            method: "POST",
            body: JSON.stringify({
              run_code: btn.dataset.release,
              credential: row ? row.credential : null,
            }),
          });
          await refresh();
          setMsg("放行完成 · 凭证 " + res.credential);
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    });
    const traceInput = document.getElementById("trace-input");
    if (traceInput) {
      traceInput.oninput = () => (traceValue = traceInput.value);
      document.getElementById("btn-trace").onclick = async () => {
        setMsg("");
        try {
          traceResult = await api("/api/trace", {
            method: "POST",
            body: JSON.stringify({ watermark_value: traceValue }),
          });
          setMsg("追索完成");
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    }
    const gapBtn = document.getElementById("btn-gap");
    if (gapBtn) {
      gapBtn.onclick = async () => {
        setMsg("");
        try {
          const r = await api("/api/gap-reports", {
            method: "POST",
            body: JSON.stringify({ as_of_date: "2026-11-16" }),
          });
          await refresh();
          setMsg(r.report.summary);
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    }
  }

  document.querySelectorAll(".dock [data-tab]").forEach((btn) => {
    btn.onclick = () => {
      tab = btn.dataset.tab;
      syncDock();
      render();
    };
  });
  document.getElementById("btn-logout").onclick = () => {
    fetch("/api/logout", { method: "POST" }).then(() => (location.href = "/login"));
  };

  refresh()
    .then(() => {
      syncDock();
      render();
    })
    .catch((e) => setMsg(e.message));
})();
