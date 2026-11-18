(() => {
  const view = document.getElementById("view");
  const msgEl = document.getElementById("msg");
  let tab = "batches";
  let meta = null;
  let batches = [];
  let selected = null;
  let detail = null;
  let reports = [];
  let acceptance = null;
  let pullResult = null;
  let closeError = null;
  let form = { object_key: "", content_hash: "", byte_size: "100" };

  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (r.status === 401) {
      location.href = "/login";
      throw new Error("未登录");
    }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(j.error || j.detail || ("HTTP " + r.status));
      err.payload = j;
      throw err;
    }
    return j;
  }

  function setMsg(t) {
    msgEl.textContent = t || "";
  }

  async function refresh() {
    meta = await api("/api/meta");
    document.getElementById("lab-brand").textContent = meta.lab_name || "湖区清单台";
    batches = (await api("/api/batches")).items || [];
    reports = (await api("/api/visibility-reports")).items || [];
  }

  async function loadAcceptance() {
    acceptance = await api("/api/close-acceptance");
  }

  async function openBatch(id) {
    selected = id;
    detail = await api("/api/batches/" + id);
    closeError = null;
    pullResult = null;
    tab = "detail";
    syncNav();
    render();
  }

  async function doRegister() {
    if (!selected) return;
    setMsg("");
    closeError = null;
    try {
      await api("/api/batches/" + selected + "/objects", {
        method: "POST",
        body: JSON.stringify({
          object_key: form.object_key,
          content_hash: form.content_hash,
          byte_size: Number(form.byte_size || 0),
        }),
      });
      form = { object_key: "", content_hash: "", byte_size: "100" };
      await openBatch(selected);
      await refresh();
      setMsg("已登记对象");
      render();
    } catch (e) {
      setMsg(e.message);
    }
  }

  async function doClose() {
    if (!selected) return;
    setMsg("");
    closeError = null;
    try {
      const r = await api("/api/batches/" + selected + "/close", {
        method: "POST",
        body: "{}",
      });
      await openBatch(selected);
      await refresh();
      setMsg(`清单已闭合：固化 ${r.object_count} 个对象（口径：${r.count_mode_label}）`);
      render();
    } catch (e) {
      // 拦截回白话：原因 + 计数值同时留在面板里
      const payload = e.payload || { error: e.message };
      setMsg(payload.error || e.message);
      try {
        await openBatch(selected);
        await refresh();
      } catch (_) {}
      closeError = payload;
      render();
    }
  }

  async function doPull() {
    if (!selected) return;
    setMsg("");
    pullResult = null;
    try {
      const r = await api("/api/batches/" + selected + "/manifest-pull", {
        method: "POST",
        body: "{}",
      });
      pullResult = { accepted: true, count: r.manifest.object_count };
      setMsg(`解析任务已接收清单：${r.manifest.object_count} 个对象`);
    } catch (e) {
      const p = e.payload || {};
      pullResult = {
        accepted: false,
        error: p.error || e.message,
        code: p.code || "",
        count: p.object_count,
      };
      setMsg(`解析任务拒收：${pullResult.error}`);
    }
    render();
  }

  async function doReport() {
    setMsg("");
    try {
      const r = await api("/api/visibility-reports", {
        method: "POST",
        body: JSON.stringify({ as_of_date: "2026-11-16" }),
      });
      await refresh();
      tab = "reports";
      syncNav();
      setMsg(r.report.summary);
      render();
    } catch (e) {
      setMsg(e.message);
    }
  }

  function syncNav() {
    document.querySelectorAll("nav [data-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
  }

  function chipClass(gate) {
    if (!gate) return "chip";
    if (gate.code === "already_closed" || gate.chip === "已闭合") return "chip chip-closed";
    if (gate.can_close) return "chip chip-ok";
    if (gate.code === "empty_manifest") return "chip chip-danger";
    if (gate.chip === "拦截") return "chip chip-danger";
    return "chip chip-warn";
  }

  function chipText(gate) {
    return (gate && gate.chip) || "未判定";
  }

  function progress(n, threshold) {
    const t = Math.max(1, Number(threshold || 1));
    const pct = Math.min(100, Math.round((Number(n || 0) / t) * 100));
    const lower = Number(n || 0) < t;
    return `
      <div class="progress ${lower ? "lower" : ""}"><span style="width:${pct}%"></span></div>
      <p class="muted gate-note">实有对象 ${n} / 门槛 ${t}${lower ? " · 低于门槛" : " · 已达门槛"}</p>`;
  }

  function renderBatches() {
    return `
      <h2>收集列表</h2>
      <p class="muted">主链：选批 → 登记对象 → 闭合清单 → 可见性对账</p>
      <p class="muted">闭合口径：${esc(meta && meta.count_mode_label)}；门槛：至少 ${esc(meta && meta.close_threshold)} 个对象，空批即停。</p>
      <table>
        <thead><tr><th>编号</th><th>湖区</th><th>业务日</th><th>状态</th><th>对象 / 门槛</th><th>闭合判定</th><th></th></tr></thead>
        <tbody>
          ${batches
            .map(
              (b) => `<tr>
            <td>${b.id}</td>
            <td>${esc(b.zone_name)}<div class="muted">${esc(b.zone_code)}</div></td>
            <td>${esc(b.biz_date)}</td>
            <td><span class="pill">${esc(b.status)}</span></td>
            <td>${b.registered_object_count} / ${b.threshold}
              <div class="muted">已固化 ${b.closed_object_count ?? "—"}</div></td>
            <td><span class="${chipClass(b.gate)}">${esc(chipText(b.gate))}</span>
              ${b.gate && b.gate.message ? `<div class="attempt">${esc(b.gate.message)}</div>` : ""}</td>
            <td><button type="button" class="secondary" data-open="${b.id}">打开</button></td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function renderEmptyPanel() {
    if (!detail) return "";
    const b = detail.batch;
    const gate = b.gate || {};
    if (!(gate.code === "empty_batch" || gate.code === "empty_manifest")) return "";
    const emptyManifest = gate.code === "empty_manifest";
    return `
      <div class="panel empty">
        <h3>${emptyManifest ? "空清单面板" : "空批面板"}</h3>
        <p class="danger-text"><strong>${esc(emptyManifest ? "空清单拦截" : "空批拦截")}</strong>
          <span class="chip chip-danger">${esc(gate.chip)}</span></p>
        <p class="gate-note">${esc(gate.message)}</p>
        <div class="stat-row">
          <div class="stat"><span>实有对象</span><strong>${gate.object_count ?? b.registered_object_count}</strong></div>
          <div class="stat"><span>闭合门槛</span><strong>${b.threshold}</strong></div>
          <div class="stat"><span>计数口径</span><strong>${esc(b.count_mode_label)}</strong></div>
        </div>
        ${emptyManifest ? progress(0, b.threshold) : progress(gate.object_count, b.threshold)}
        ${b.last_close_attempt
          ? `<p class="attempt">最近拦截：对象 ${b.last_close_attempt.object_count} 个，门槛 ${b.last_close_attempt.threshold}，代码 ${esc(b.last_close_attempt.code)}，时间 ${esc(b.last_close_attempt.created_at)}</p>`
          : ""}
        <p class="muted">解析任务拉清单：${emptyManifest ? "将被拒收（空清单）" : "不可拉取（批次未闭合）"}</p>
      </div>`;
  }

  function renderPullPanel() {
    if (!pullResult) return "";
    if (pullResult.accepted) {
      return `<div class="panel"><h3>解析验收台 · 拉清单</h3>
        <p class="ok-text">已接收：${pullResult.count} 个对象</p></div>`;
    }
    return `<div class="panel empty"><h3>解析验收台 · 拉清单</h3>
      <p class="danger-text">拒收 <span class="chip chip-danger">${esc(pullResult.code || "拒收")}</span></p>
      <p class="gate-note">${esc(pullResult.error)}</p>
      ${pullResult.count !== undefined
        ? `<p class="muted">清单对象数：${pullResult.count}</p>`
        : ""}</div>`;
  }

  function renderDetail() {
    if (!detail) {
      return `<h2>批次详情</h2><p class="muted">请先从收集列表打开一条。</p>`;
    }
    const b = detail.batch;
    const objs = detail.objects || [];
    const gate = b.gate || {};
    const isOpen = b.status === "收集中";
    // 收集中批次始终可点闭合：门槛由服务端在提交瞬间现场重数判定并回白话，
    // 面板提前显示的判定只是提示，不作为唯一门槛。
    const closeDisabled = !isOpen;
    return `
      <h2>批次详情 #${b.id}</h2>
      <p>${esc(b.zone_name)} · ${esc(b.biz_date)} · <span class="pill">${esc(b.status)}</span>
        <span class="${chipClass(gate)}">${esc(chipText(gate))}</span></p>
      <div class="stat-row">
        <div class="stat"><span>已登记对象</span><strong>${b.registered_object_count}</strong></div>
        <div class="stat"><span>已固化对象数</span><strong>${b.closed_object_count ?? "—"}</strong></div>
        <div class="stat"><span>闭合门槛</span><strong>${b.threshold}</strong></div>
        <div class="stat"><span>计数口径</span><strong>${esc(b.count_mode_label)}</strong></div>
      </div>
      <h3>对象进度</h3>
      ${progress(b.registered_object_count, b.threshold)}
      <p class="muted gate-note">${esc(gate.message || "已达闭合门槛。")}</p>
      ${closeError ? `<p class="danger-text gate-note">闭合拦截：${esc(closeError.error)}${closeError.object_count !== undefined ? `（对象 ${closeError.object_count} 个 / 门槛 ${closeError.threshold}）` : ""}</p>` : ""}
      ${renderEmptyPanel()}
      <div class="row-actions">
        <button type="button" id="btn-close" ${closeDisabled ? "disabled" : ""}>闭合清单</button>
        <button type="button" class="secondary" id="btn-pull" ${b.status === "已闭合" ? "" : "disabled"}>模拟解析拉清单</button>
        <button type="button" class="secondary" id="btn-report-from-detail">跑可见性对账</button>
      </div>
      ${renderPullPanel()}
      <div class="panel">
        <h3>登记对象</h3>
        <label>对象键<input id="f-key" value="${esc(form.object_key)}" ${isOpen ? "" : "disabled"} /></label>
        <label>内容指纹<input id="f-hash" value="${esc(form.content_hash)}" ${isOpen ? "" : "disabled"} /></label>
        <label>字节数<input id="f-size" value="${esc(form.byte_size)}" ${isOpen ? "" : "disabled"} /></label>
        <button type="button" id="btn-register" ${isOpen ? "" : "disabled"}>写入登记</button>
      </div>
      <h3>对象列表</h3>
      <table>
        <thead><tr><th>键</th><th>指纹</th><th>字节</th><th>状态</th></tr></thead>
        <tbody>
          ${objs
            .map(
              (o) => `<tr>
            <td>${esc(o.object_key)}</td><td>${esc(o.content_hash)}</td><td>${o.byte_size}</td><td>${esc(o.status)}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function renderAcceptance() {
    const a = acceptance || { batches: [], recent_pulls: [] };
    return `
      <h2>解析验收台</h2>
      <p class="muted">闭合门槛与实有对象同屏核对；空批即停，空清单拒收。</p>
      <div class="stat-row">
        <div class="stat"><span>闭合门槛</span><strong>${a.threshold}</strong></div>
        <div class="stat"><span>计数口径</span><strong>${esc(a.count_mode_label)}</strong></div>
        <div class="stat"><span>空批（收集中需拦截）</span><strong>${a.empty_open_batch_count}</strong></div>
        <div class="stat"><span>空已闭合（异常）</span><strong>${a.empty_closed_batch_count}</strong></div>
      </div>
      <h3>批次门槛核对</h3>
      <table>
        <thead><tr><th>编号</th><th>湖区</th><th>状态</th><th>实有对象</th><th>已闭合清单</th><th>固化数</th><th>判定</th><th>最近拦截</th></tr></thead>
        <tbody>
          ${(a.batches || [])
            .map(
              (b) => `<tr>
            <td>${b.batch_id}</td>
            <td>${esc(b.zone_name)}<div class="muted">${esc(b.zone_code)}</div></td>
            <td>${esc(b.status)}</td>
            <td>${b.registered_object_count}</td>
            <td>${b.closed_manifest_count}</td>
            <td>${b.closed_object_count ?? "—"}</td>
            <td>${
              b.empty_manifest
                ? '<span class="chip chip-danger">空清单拦截</span>'
                : b.would_block_empty
                ? '<span class="chip chip-danger">拦截</span>'
                : b.status === "已闭合"
                ? '<span class="chip chip-closed">已闭合</span>'
                : '<span class="chip chip-ok">可闭合</span>'
            }</td>
            <td>${b.last_close_attempt
              ? `${esc(b.last_close_attempt.code || "通过")} · ${b.last_close_attempt.object_count} 个 / 门槛 ${b.last_close_attempt.threshold}`
              : '<span class="muted">—</span>'}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>
      <h3>解析拉清单记录</h3>
      <table>
        <thead><tr><th>编号</th><th>批次</th><th>结果</th><th>对象数</th><th>原因</th><th>时间</th></tr></thead>
        <tbody>
          ${(a.recent_pulls || [])
            .map(
              (p) => `<tr>
            <td>${p.id}</td><td>#${p.batch_id}</td>
            <td>${p.accepted ? '<span class="chip chip-ok">接收</span>' : '<span class="chip chip-danger">拒收</span>'}</td>
            <td>${p.object_count}</td><td>${esc(p.message || p.code)}</td><td>${esc(p.created_at)}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function renderReports() {
    return `
      <h2>可见性对账</h2>
      <button type="button" id="btn-report">生成对账</button>
      <table>
        <thead><tr><th>编号</th><th>截至</th><th>错位</th><th>空已闭合</th><th>摘要</th></tr></thead>
        <tbody>
          ${reports
            .map(
              (r) => `<tr>
            <td>${r.id}</td><td>${esc(r.as_of_date)}</td><td>${r.mismatch_count}</td>
            <td>${r.empty_closed_batch_count ?? "—"}</td><td>${esc(r.summary)}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function render() {
    if (tab === "batches") view.innerHTML = renderBatches();
    else if (tab === "detail") view.innerHTML = renderDetail();
    else if (tab === "acceptance") view.innerHTML = renderAcceptance();
    else view.innerHTML = renderReports();

    view.querySelectorAll("[data-open]").forEach((btn) => {
      btn.onclick = () => openBatch(Number(btn.dataset.open));
    });
    const reg = document.getElementById("btn-register");
    if (reg) {
      const key = document.getElementById("f-key");
      const hash = document.getElementById("f-hash");
      const size = document.getElementById("f-size");
      key.oninput = () => (form.object_key = key.value);
      hash.oninput = () => (form.content_hash = hash.value);
      size.oninput = () => (form.byte_size = size.value);
      reg.onclick = doRegister;
    }
    const closeBtn = document.getElementById("btn-close");
    if (closeBtn) closeBtn.onclick = doClose;
    const pullBtn = document.getElementById("btn-pull");
    if (pullBtn) pullBtn.onclick = doPull;
    const r1 = document.getElementById("btn-report");
    const r2 = document.getElementById("btn-report-from-detail");
    if (r1) r1.onclick = doReport;
    if (r2) r2.onclick = doReport;
  }

  document.querySelectorAll("nav [data-tab]").forEach((btn) => {
    btn.onclick = async () => {
      tab = btn.dataset.tab;
      syncNav();
      if (tab === "acceptance") {
        try {
          await loadAcceptance();
        } catch (e) {
          setMsg(e.message);
        }
      }
      render();
    };
  });
  document.getElementById("btn-logout").onclick = () => {
    fetch("/api/logout", { method: "POST" }).then(() => (location.href = "/login"));
  };

  refresh()
    .then(() => loadAcceptance())
    .then(render)
    .catch((e) => setMsg(e.message));
})();
