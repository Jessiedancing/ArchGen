(() => {
  const state = {
    style: null,
    generating: false,
    stem: null,
    activeProfile: null,
  };

  // T03 / A-06：舒适下限 25%，但「适应窗口」可更小；1:1 按导出倍率还原逻辑尺寸
  const ZOOM_COMFORT_MIN = 0.25;
  const ZOOM_MAX = 4;
  const ZOOM_FACTOR = 1.12;
  const EXPORT_SCALE = 3;
  let waitTimer = null;
  const preview = {
    scale: 1,
    tx: 0,
    ty: 0,
    dragging: false,
    lastX: 0,
    lastY: 0,
  };

  const $ = (id) => document.getElementById(id);
  const statusLine = $("statusLine");
  const styleList = $("styleList");
  const historyList = $("historyList");
  const previewFrame = $("previewFrame");
  const previewStem = $("previewStem");
  const fileLinks = $("fileLinks");
  const dialog = $("settingsDialog");
  const form = $("settingsForm");
  const probeOut = $("probeOut");

  function setStatus(text, kind = "") {
    statusLine.textContent = text || "";
    statusLine.className = "status" + (kind ? " " + kind : "");
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `请求失败 ${res.status}`);
    }
    return data;
  }

  function renderStyles(payload) {
    const styles = payload.styles || [];
    const def = payload.default || (styles[0] && styles[0].key);
    styleList.innerHTML = "";
    styles.forEach((s) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "style-btn" + (s.key === def ? " active" : "");
      btn.dataset.key = s.key;
      btn.innerHTML = `<strong>${escapeHtml(s.name || s.key)}</strong><span>${escapeHtml(s.use_when || s.description || "")}</span>`;
      btn.addEventListener("click", () => selectStyle(s.key));
      styleList.appendChild(btn);
    });
    selectStyle(def);
  }

  function selectStyle(key) {
    state.style = key;
    styleList.querySelectorAll(".style-btn").forEach((el) => {
      el.classList.toggle("active", el.dataset.key === key);
    });
  }

  function renderHistory(payload) {
    const items = payload.items || [];
    historyList.innerHTML = "";
    if (!items.length) {
      historyList.innerHTML = '<p class="muted">还没有图</p>';
      return;
    }
    items.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hist-btn";
      btn.textContent = item.stem;
      btn.title = item.stem;
      btn.addEventListener("click", () => {
        showPreview(item.preview_url, item.stem, item);
      });
      historyList.appendChild(btn);
    });
  }

  function previewImg() {
    return previewFrame.querySelector("img");
  }

  function computeFitScale() {
    const img = previewImg();
    if (!img || !img.naturalWidth) return null;
    const rect = previewFrame.getBoundingClientRect();
    const pad = 16;
    const sx = (rect.width - pad) / img.naturalWidth;
    const sy = (rect.height - pad) / img.naturalHeight;
    return Math.min(sx, sy);
  }

  function currentMinZoom() {
    const fit = computeFitScale();
    if (!fit || !Number.isFinite(fit)) return ZOOM_COMFORT_MIN;
    return Math.min(ZOOM_COMFORT_MIN, fit);
  }

  function clampZoom(value) {
    return Math.min(ZOOM_MAX, Math.max(currentMinZoom(), value));
  }

  function applyPreviewTransform() {
    const img = previewImg();
    if (!img) {
      $("zoomLabel").textContent = "—";
      return;
    }
    img.style.transform = `translate(${preview.tx}px, ${preview.ty}px) scale(${preview.scale})`;
    $("zoomLabel").textContent = `${Math.round(preview.scale * 100)}%`;
  }

  function zoomAt(nextScale, cx, cy) {
    if (!previewImg()) return;
    const scale = clampZoom(nextScale);
    const contentX = (cx - preview.tx) / preview.scale;
    const contentY = (cy - preview.ty) / preview.scale;
    preview.scale = scale;
    preview.tx = cx - contentX * scale;
    preview.ty = cy - contentY * scale;
    applyPreviewTransform();
  }

  function framePoint(clientX, clientY) {
    const rect = previewFrame.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }

  function frameCenter() {
    const rect = previewFrame.getBoundingClientRect();
    return { x: rect.width / 2, y: rect.height / 2 };
  }

  function fitPreview() {
    const img = previewImg();
    if (!img || !img.naturalWidth) return;
    const rect = previewFrame.getBoundingClientRect();
    const scale = computeFitScale();
    if (!scale) return;
    preview.scale = scale;
    preview.tx = (rect.width - img.naturalWidth * preview.scale) / 2;
    preview.ty = (rect.height - img.naturalHeight * preview.scale) / 2;
    applyPreviewTransform();
  }

  function resetPreview1x() {
    const img = previewImg();
    if (!img || !img.naturalWidth) return;
    const rect = previewFrame.getBoundingClientRect();
    preview.scale = 1 / EXPORT_SCALE;
    preview.tx = (rect.width - img.naturalWidth * preview.scale) / 2;
    preview.ty = (rect.height - img.naturalHeight * preview.scale) / 2;
    applyPreviewTransform();
  }

  function stopPreviewWait() {
    if (waitTimer) {
      clearInterval(waitTimer);
      waitTimer = null;
    }
    previewFrame.classList.remove("is-waiting");
  }

  function formatElapsed(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m} 分 ${String(s).padStart(2, "0")} 秒` : `${s} 秒`;
  }

  function showPreviewWaiting() {
    stopPreviewWait();
    state.stem = null;
    previewStem.textContent = "";
    fileLinks.innerHTML = "";
    if ($("exportBar")) $("exportBar").hidden = true;
    setPreviewEnabled(false);
    previewFrame.classList.remove("has-image");
    previewFrame.classList.add("is-waiting");
    previewFrame.innerHTML =
      `<div class="preview-wait"><div class="preview-skel"></div>` +
      `<p class="preview-wait-time">已等待 0 秒</p>` +
      `<p class="preview-wait-text">模型正在写图（本机大模型常要 3～10 分钟）。` +
      `请看启动窗口是否在逐字出内容；LM Studio 里 token 在涨就说明没卡死。</p></div>`;
    const started = Date.now();
    waitTimer = setInterval(() => {
      const sec = Math.floor((Date.now() - started) / 1000);
      const timeEl = previewFrame.querySelector(".preview-wait-time");
      if (timeEl) timeEl.textContent = `已等待 ${formatElapsed(sec)}`;
      setStatus(`正在生成，已等待 ${formatElapsed(sec)}…`);
    }, 1000);
  }

  function showPreviewError(message) {
    stopPreviewWait();
    state.stem = null;
    previewStem.textContent = "";
    fileLinks.innerHTML = "";
    if ($("exportBar")) $("exportBar").hidden = true;
    setPreviewEnabled(false);
    previewFrame.classList.remove("has-image");
    previewFrame.innerHTML =
      `<div class="preview-error"><strong>生成失败</strong><pre>${escapeHtml(message || "未知错误")}</pre></div>`;
  }

  function setPreviewEnabled(on) {
    previewFrame.classList.toggle("has-image", on);
    ["btnZoomOut", "btnZoomIn", "btnZoomReset", "btnZoomFit"].forEach((id) => {
      $(id).disabled = !on;
    });
    if (!on) $("zoomLabel").textContent = "—";
  }

  function showPreview(previewUrl, stem, item) {
    stopPreviewWait();
    previewStem.textContent = stem || "";
    preview.scale = 1;
    preview.tx = 0;
    preview.ty = 0;
    if (previewUrl) {
      previewFrame.innerHTML = `<img src="${previewUrl}?t=${Date.now()}" alt="${escapeHtml(stem || "preview")}" draggable="false" />`;
      const img = previewImg();
      setPreviewEnabled(false);
      img.addEventListener("load", () => {
        setPreviewEnabled(true);
        fitPreview();
      });
      img.addEventListener("error", () => {
        previewFrame.innerHTML = '<p class="muted placeholder">PNG 加载失败</p>';
        setPreviewEnabled(false);
      });
    } else {
      previewFrame.innerHTML = '<p class="muted placeholder">没有 PNG 预览</p>';
      setPreviewEnabled(false);
    }
    fileLinks.innerHTML = "";
    state.stem = stem || null;
    const exportBar = $("exportBar");
    if (exportBar) exportBar.hidden = !stem;
    const always = ["png", "html", "md", "mmd", "json"];
    const onDemand = ["drawio", "pptx"];
    always.forEach((ext) => {
      const exists = !!(item && (item[ext] || (item.files && item.files[ext])));
      if (!exists && ext !== "png") return;
      let href;
      if (item && item.files && item.files[ext]) {
        const base = item.files[ext].split(/[/\\]/).pop();
        href = `/api/files/${encodeURIComponent(base)}`;
      } else {
        const name = item && item[ext] ? item[ext] : stem ? `${stem}.${ext}` : null;
        if (!name) return;
        href = `/api/files/${encodeURIComponent(name)}`;
      }
      const a = document.createElement("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = ext.toUpperCase();
      fileLinks.appendChild(a);
    });
    onDemand.forEach((ext) => {
      const exists = !!(item && (item[ext] || (item.files && item.files[ext])));
      if (exists) {
        const raw = (item.files && item.files[ext]) || item[ext];
        const base = String(raw).split(/[/\\]/).pop();
        const a = document.createElement("a");
        a.href = `/api/files/${encodeURIComponent(base)}`;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = ext.toUpperCase();
        fileLinks.appendChild(a);
        return;
      }
      if (!stem) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "file-link-btn";
      btn.textContent = ext.toUpperCase();
      btn.title = "尚未生成，点击导出";
      btn.addEventListener("click", () => exportKind(ext));
      fileLinks.appendChild(btn);
    });
  }

  function showGenerateResult(data) {
    const files = data.files || {};
    const item = { files, stem: data.stem };
    Object.keys(files).forEach((k) => {
      item[k] = files[k].split(/[/\\]/).pop();
    });
    showPreview(data.preview_url, data.stem, item);
  }

  function fillSettings(settings) {
    const s = settings || {};
    [...form.elements].forEach((el) => {
      if (!el.name) return;
      if (s[el.name] != null) el.value = s[el.name];
    });
  }

  function fillProfiles(payload) {
    const select = $("profileSelect");
    if (!select) return;
    const profiles = payload.profiles || {};
    const active = payload.active;
    state.activeProfile = active;
    select.innerHTML = "";
    Object.keys(profiles).forEach((key) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = profiles[key].label || key;
      if (key === active) opt.selected = true;
      select.appendChild(opt);
    });
    fillSettings(payload.settings || {});
  }

  async function loadModels() {
    try {
      const data = await api("/api/models");
      const list = $("modelList");
      if (!list) return;
      list.innerHTML = "";
      (data.models || []).forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        list.appendChild(opt);
      });
    } catch (_err) {
      /* 网关 /v1/models 不可用时保持手填 */
    }
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function boot() {
    try {
      const meta = await api("/api/meta");
      $("versionTag").textContent = `本地绿色版 · v${meta.version || "?"}`;
      const styles = await api("/api/styles");
      renderStyles(styles);
      const hist = await api("/api/history");
      renderHistory(hist);
      const settings = await api("/api/settings");
      fillProfiles(settings);
      await loadModels();
      if (!(settings.settings || {}).BASE_URL) {
        setStatus("请先点右上角「设置」填写私有网关", "error");
        dialog.showModal();
      }
    } catch (err) {
      setStatus(err.message || String(err), "error");
    }
  }

  $("btnSettings").addEventListener("click", async () => {
    try {
      const settings = await api("/api/settings");
      fillProfiles(settings);
      probeOut.textContent = "";
      dialog.showModal();
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  $("btnCloseSettings").addEventListener("click", () => dialog.close());

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const payload = {};
    [...form.elements].forEach((el) => {
      if (el.name) payload[el.name] = el.value;
    });
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: payload }),
      });
      const refreshed = await api("/api/settings");
      fillProfiles(refreshed);
      await loadModels();
      setStatus("设置已保存", "ok");
      dialog.close();
    } catch (err) {
      probeOut.textContent = err.message;
    }
  });

  $("btnProbe").addEventListener("click", async () => {
    probeOut.textContent = "正在探测…";
    // 先保存再探测
    const payload = {};
    [...form.elements].forEach((el) => {
      if (el.name) payload[el.name] = el.value;
    });
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: payload }),
      });
      const data = await api("/api/probe", { method: "POST", body: "{}" });
      const lines = [
        `网关：${data.base_url}`,
        `默认：${data.default_model || "(未配置)"}`,
        "",
        ...((data.results || []).map(
          (r) => `[${r.ok ? "可用" : "不可用"}] ${r.model}  ${r.detail}`
        )),
      ];
      probeOut.textContent = lines.join("\n");
      await loadModels();
    } catch (err) {
      probeOut.textContent = err.message;
    }
  });

  $("btnOpenFolder").addEventListener("click", async () => {
    try {
      await api("/api/open-folder", { method: "POST", body: "{}" });
      setStatus("已打开产出文件夹", "ok");
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  $("btnGenerate").addEventListener("click", async () => {
    if (state.generating) return;
    const text = $("inputText").value.trim();
    if (!text) {
      setStatus("请先填写要画的内容", "error");
      return;
    }
    if (!state.style) {
      setStatus("请选择图种", "error");
      return;
    }
    state.generating = true;
    $("btnGenerate").disabled = true;
    showPreviewWaiting();
    setStatus("正在生成，请稍候…");
    try {
      const data = await api("/api/generate", {
        method: "POST",
        body: JSON.stringify({
          text,
          style: state.style,
          name: $("inputName").value.trim() || null,
          model: $("inputModel").value.trim() || null,
        }),
      });
      showGenerateResult(data);
      setStatus(`已生成 ${data.stem}`, "ok");
      const hist = await api("/api/history");
      renderHistory(hist);
    } catch (err) {
      showPreviewError(err.message);
      setStatus(err.message, "error");
    } finally {
      state.generating = false;
      $("btnGenerate").disabled = false;
    }
  });

  $("profileSelect").addEventListener("change", async (ev) => {
    try {
      const data = await api("/api/profiles/switch", {
        method: "POST",
        body: JSON.stringify({ name: ev.target.value }),
      });
      fillProfiles(data);
      await loadModels();
      setStatus(`已切换到「${(data.profiles[data.active] || {}).label || data.active}」`, "ok");
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  async function mutateProfile(action, extra) {
    const name = window.prompt(
      action === "delete" ? "确认删除当前档位？输入档位 key 确认" : "档位 key（英文/数字/连字符）",
      action === "copy" ? `${state.activeProfile || "default"}-copy` : state.activeProfile || ""
    );
    if (!name) return;
    const data = await api("/api/profiles", {
      method: "POST",
      body: JSON.stringify({ action, name, from: state.activeProfile, ...extra }),
    });
    fillProfiles(data);
    await loadModels();
    return data;
  }

  $("btnProfileNew").addEventListener("click", async () => {
    try {
      await mutateProfile("create");
      setStatus("已新增档位", "ok");
    } catch (err) {
      probeOut.textContent = err.message;
    }
  });
  $("btnProfileCopy").addEventListener("click", async () => {
    try {
      await mutateProfile("copy");
      setStatus("已复制档位", "ok");
    } catch (err) {
      probeOut.textContent = err.message;
    }
  });
  $("btnProfileRename").addEventListener("click", async () => {
    try {
      await mutateProfile("rename");
      setStatus("已改名", "ok");
    } catch (err) {
      probeOut.textContent = err.message;
    }
  });
  $("btnProfileDelete").addEventListener("click", async () => {
    try {
      await mutateProfile("delete");
      setStatus("已删除档位", "ok");
    } catch (err) {
      probeOut.textContent = err.message;
    }
  });

  $("btnProbeAll").addEventListener("click", async () => {
    probeOut.textContent = "正在逐档探测…";
    try {
      const data = await api("/api/probe", {
        method: "POST",
        body: JSON.stringify({ all: true }),
      });
      const lines = (data.probes || []).map((row) => {
        if (row.error) return `[不可达] ${row.label}  ${row.error}`;
        const ok = (row.results || []).some((r) => r.ok);
        return `[${ok ? "可用" : "不可达"}] ${row.label}  ${row.base_url || ""}`;
      });
      probeOut.textContent = ["不自动切换档位，请手动选择可用环境。", "", ...lines].join("\n");
    } catch (err) {
      probeOut.textContent = err.message;
    }
  });

  async function exportKind(kind) {
    if (!state.stem) {
      setStatus("请先生成或点选一张图", "error");
      return;
    }
    const data = await api("/api/export", {
      method: "POST",
      body: JSON.stringify({ stem: state.stem, kind }),
    });
    const hist = await api("/api/history");
    renderHistory(hist);
    const item = (hist.items || []).find((x) => x.stem === state.stem) || { stem: state.stem };
    showPreview(`/api/files/${encodeURIComponent(state.stem + ".png")}`, state.stem, item);
    setStatus(data.path ? `已导出 ${kind}：${data.path}` : `已导出 ${kind}`, "ok");
  }

  $("btnExportDrawio").addEventListener("click", async () => {
    try {
      await exportKind("drawio");
    } catch (err) {
      setStatus(err.message, "error");
    }
  });
  $("btnExportPptx").addEventListener("click", async () => {
    try {
      await exportKind("pptx");
    } catch (err) {
      setStatus(err.message, "error");
    }
  });
  $("btnCopyPng").addEventListener("click", async () => {
    if (!state.stem) {
      setStatus("请先生成或点选一张图", "error");
      return;
    }
    try {
      await api("/api/copy-png", {
        method: "POST",
        body: JSON.stringify({ stem: state.stem }),
      });
      setStatus("已复制为图片。要改文字请导出 PPTX。", "ok");
    } catch (err) {
      try {
        const res = await fetch(`/api/files/${encodeURIComponent(state.stem + ".png")}`);
        const blob = await res.blob();
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        setStatus("已用浏览器剪贴板复制图片。要改文字请导出 PPTX。", "ok");
      } catch (fallbackErr) {
        setStatus(err.message || fallbackErr.message, "error");
      }
    }
  });

  $("btnZoomIn").addEventListener("click", () => {
    const c = frameCenter();
    zoomAt(preview.scale * ZOOM_FACTOR, c.x, c.y);
  });
  $("btnZoomOut").addEventListener("click", () => {
    const c = frameCenter();
    zoomAt(preview.scale / ZOOM_FACTOR, c.x, c.y);
  });
  $("btnZoomReset").addEventListener("click", () => resetPreview1x());
  $("btnZoomFit").addEventListener("click", () => fitPreview());

  previewFrame.addEventListener(
    "wheel",
    (ev) => {
      if (!ev.ctrlKey) return;
      if (!previewImg()) return;
      ev.preventDefault();
      const pt = framePoint(ev.clientX, ev.clientY);
      const factor = ev.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
      zoomAt(preview.scale * factor, pt.x, pt.y);
    },
    { passive: false }
  );

  previewFrame.addEventListener("mousedown", (ev) => {
    if (ev.button !== 0) return;
    if (!previewImg()) return;
    ev.preventDefault();
    preview.dragging = true;
    preview.lastX = ev.clientX;
    preview.lastY = ev.clientY;
    previewFrame.classList.add("is-panning");
  });
  window.addEventListener("mousemove", (ev) => {
    if (!preview.dragging) return;
    preview.tx += ev.clientX - preview.lastX;
    preview.ty += ev.clientY - preview.lastY;
    preview.lastX = ev.clientX;
    preview.lastY = ev.clientY;
    applyPreviewTransform();
  });
  window.addEventListener("mouseup", () => {
    preview.dragging = false;
    previewFrame.classList.remove("is-panning");
  });

  setPreviewEnabled(false);
  boot();
})();
