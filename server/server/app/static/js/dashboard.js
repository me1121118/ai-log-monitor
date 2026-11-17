const websiteInput = document.querySelector('#file-import input[name="website_id"]');
    document.querySelectorAll('a[data-website]').forEach((link) => {
      link.addEventListener('click', () => {
        if (websiteInput) {
          websiteInput.value = link.dataset.website;
        }
      });
    });

    const fileImportForm = document.getElementById('file-import');
    if (fileImportForm) {
      fileImportForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const status = document.getElementById('import-status');
        const file = form.log_file.files[0];
        if (!file) {
          status.textContent = 'Please choose a log file.';
          return;
        }
        status.textContent = 'Uploading and processing log data...';
        const content = await file.text();
        const data = Object.fromEntries(new FormData(form).entries());
        delete data.log_file;
        data.filename = file.name;
        data.content = content;
        const response = await fetch('/api/files/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        const result = await response.json();
        if (!response.ok) {
          status.textContent = result.error || 'Import failed.';
          return;
        }
        status.textContent = `Import complete: processed ${result.imported_lines} log lines (${result.problem_lines} issues found).`;
        setTimeout(() => location.reload(), 800);
      });
    }

    async function postJson(url, form) {
      const data = Object.fromEntries(new FormData(form).entries());
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      await response.text();
      setTimeout(() => location.reload(), 50);
    }
    const createWebsiteForm = document.getElementById('create-website');
    if (createWebsiteForm) {
      createWebsiteForm.addEventListener('submit', (event) => {
        event.preventDefault();
        postJson('/api/websites', event.currentTarget);
      });
    }
    const assignAgentForm = document.getElementById('assign-agent');
    if (assignAgentForm) {
      assignAgentForm.addEventListener('submit', (event) => {
        event.preventDefault();
        postJson('/api/agents/assign', event.currentTarget);
      });
    }
    const createClusterForm = document.getElementById('create-cluster');
    if (createClusterForm) {
      createClusterForm.addEventListener('submit', (event) => {
        event.preventDefault();
        postJson('/api/clusters', event.currentTarget);
      });
    }
    const createRelationForm = document.getElementById('create-relation');
    if (createRelationForm) {
      createRelationForm.addEventListener('submit', (event) => {
        event.preventDefault();
        postJson('/api/relations', event.currentTarget);
      });
    }
    const agentMaintenanceForm = document.getElementById('agent-maintenance-form');
    if (agentMaintenanceForm) {
      agentMaintenanceForm.addEventListener('submit', (event) => {
        event.preventDefault();
        postJson('/api/agents/maintenance', event.currentTarget);
      });
    }

    async function toggleAgentMaintenance(agentId, minutes) {
      const payload = minutes > 0
        ? { agent_id: agentId, minutes: Number(minutes) }
        : { agent_id: agentId, maintenance_until: null };
      const response = await fetch('/api/agents/maintenance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      await response.text();
      setTimeout(() => location.reload(), 50);
    }

    document.querySelectorAll('button[data-maintenance-agent]').forEach((button) => {
      button.addEventListener('click', () => {
        const agentId = button.dataset.maintenanceAgent;
        const minutes = Number(button.dataset.maintenanceMinutes || '60');
        toggleAgentMaintenance(agentId, minutes);
      });
    });

    document.querySelectorAll('button[data-delete-relation]').forEach((button) => {
      button.addEventListener('click', async () => {
        const relId = button.dataset.deleteRelation;
        const response = await fetch(`/api/relations/${encodeURIComponent(relId)}`, { method: 'DELETE' });
        await response.text();
        setTimeout(() => location.reload(), 50);
      });
    });

    document.querySelectorAll('button[data-delete-cluster]').forEach((button) => {
      button.addEventListener('click', async () => {
        const clusterId = button.dataset.deleteCluster;
        const response = await fetch(`/api/clusters/${encodeURIComponent(clusterId)}`, { method: 'DELETE' });
        await response.text();
        setTimeout(() => location.reload(), 50);
      });
    });

    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
      settingsForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const status = document.getElementById('settings-status');
        const data = formToSettings(form);
        if (status) {
          status.textContent = 'Saving settings...';
        }
        const response = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        const result = await response.json();
        if (!response.ok) {
          if (status) {
            status.textContent = result.error || 'Settings save failed.';
          }
          return;
        }
        if (status) {
          status.textContent = 'Settings saved.';
        }
      });
    }

    function formToSettings(form) {
      const data = {};
      const formData = new FormData(form);
      formData.forEach((value, key) => {
        setNestedValue(data, key, normalizeSettingValue(form, key, value));
      });
      form.querySelectorAll('input[type="checkbox"][name]').forEach((input) => {
        setNestedValue(data, input.name, input.checked);
      });
      return data;
    }

    function setNestedValue(target, path, value) {
      const parts = path.split('.');
      let current = target;
      parts.slice(0, -1).forEach((part) => {
        if (!current[part]) {
          current[part] = {};
        }
        current = current[part];
      });
      current[parts[parts.length - 1]] = value;
    }

    function normalizeSettingValue(form, key, value) {
      const field = form.querySelector(`[name="${CSS.escape(key)}"]`);
      if (field && field.type === 'number') {
        return Number(value);
      }
      if (value === 'true') return true;
      if (value === 'false') return false;
      return value;
    }

    document.querySelectorAll('button[data-close]').forEach((button) => {
      button.addEventListener('click', async () => {
        const response = await fetch(`/api/incidents/${button.dataset.close}/close`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        await response.text();
        setTimeout(() => location.reload(), 50);
      });
    });

    const globalSearch = document.getElementById('global-search');
    if (globalSearch) {
      const searchableItems = Array.from(document.querySelectorAll(
        '.overview-card, .fleet-mini-card, .attention-item, table tbody tr'
      ));
      globalSearch.addEventListener('input', () => {
        const query = globalSearch.value.trim().toLowerCase();
        searchableItems.forEach((item) => {
          item.hidden = Boolean(query) && !item.textContent.toLowerCase().includes(query);
        });
      });
    }

    const copyCommandButton = document.querySelector('.install-card .secondary');
    const commandBox = document.querySelector('.install-card .command-box');
    if (copyCommandButton && commandBox) {
      const defaultCopyLabel = copyCommandButton.textContent;
      copyCommandButton.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(commandBox.textContent.trim());
          copyCommandButton.textContent = 'Copied';
        } catch (err) {
          copyCommandButton.textContent = 'Select Command';
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(commandBox);
          selection.removeAllRanges();
          selection.addRange(range);
        }
        setTimeout(() => {
          copyCommandButton.textContent = defaultCopyLabel;
        }, 1600);
      });
    }
    
    function switchWebsiteTab(targetId, btnEl) {
      document.querySelectorAll('.wtab-pane').forEach((pane) => {
        if (pane.id === targetId) {
          pane.hidden = false;
          pane.classList.add('active');
        } else {
          pane.hidden = true;
          pane.classList.remove('active');
        }
      });
      document.querySelectorAll('.clean-tab-btn').forEach((btn) => {
        btn.classList.toggle('active', btn === btnEl || btn.getAttribute('data-wtab-target') === targetId);
      });
      if (targetId === 'wtab-diagram') {
        setTimeout(renderErDiagramCanvas, 30);
      }
    }

    function openAiTabAndAnalyze(websiteId) {
      const aiTabBtn = document.getElementById('tab-btn-ai');
      switchWebsiteTab('wtab-ai', aiTabBtn);
      runAiAnalysis(websiteId);
    }

    function toggleErPaletteDrawer() {
      const drawer = document.getElementById('er-palette-drawer');
      const arrow = document.getElementById('er-palette-arrow');
      if (!drawer) return;
      drawer.classList.toggle('open');
      if (arrow) {
        arrow.textContent = drawer.classList.contains('open') ? '▶' : '◀';
      }
      setTimeout(renderErDiagramCanvas, 220);
    }

    let erZoomLevel = 1;
    let selectedErRelationId = '';
    window._erDraftLine = null;

    function applyErZoom() {
      const stage = document.getElementById('er-zoom-stage');
      const label = document.getElementById('er-zoom-label');
      if (stage) {
        stage.style.transform = `scale(${erZoomLevel})`;
      }
      if (label) {
        label.textContent = `${Math.round(erZoomLevel * 100)}%`;
      }
      const canvas = document.getElementById('er-interactive-canvas');
      if (canvas) {
        const wid = canvas.getAttribute('data-website-id') || 'default';
        try {
          localStorage.setItem('alm_er_zoom_' + wid, String(erZoomLevel));
        } catch (e) {}
      }
    }

    function adjustErZoom(delta) {
      erZoomLevel = Math.max(0.4, Math.min(1.5, Math.round((erZoomLevel + delta) * 100) / 100));
      applyErZoom();
      renderErDiagramCanvas();
    }

    function fitErCanvasToScreen() {
      const canvas = document.getElementById('er-interactive-canvas');
      const stage = document.getElementById('er-zoom-stage');
      if (!canvas || !stage) return;
      let maxX = 420;
      stage.querySelectorAll('.er-zone-box, .er-entity-table').forEach((el) => {
        maxX = Math.max(maxX, el.offsetLeft + el.offsetWidth + 40);
      });
      const ratio = canvas.clientWidth / maxX;
      erZoomLevel = Math.max(0.45, Math.min(1.0, Math.round(ratio * 100) / 100));
      applyErZoom();
      renderErDiagramCanvas();
    }

    function saveErLayout() {
      const canvas = document.getElementById('er-interactive-canvas');
      if (!canvas) return;
      const wid = canvas.getAttribute('data-website-id') || 'default';
      const layout = { nodes: {}, zones: {} };
      canvas.querySelectorAll('.er-entity-table').forEach((el) => {
        const aid = el.getAttribute('data-agent-id');
        if (aid) layout.nodes[aid] = { left: el.offsetLeft, top: el.offsetTop };
      });
      canvas.querySelectorAll('.er-zone-box').forEach((el) => {
        const cid = el.getAttribute('data-cluster-id');
        if (cid) {
          layout.zones[cid] = {
            left: el.offsetLeft,
            top: el.offsetTop,
            width: el.getAttribute('data-custom-size') === '1' ? el.offsetWidth : null,
            height: el.getAttribute('data-custom-size') === '1' ? el.offsetHeight : null
          };
        }
      });
      try {
        localStorage.setItem('alm_er_layout_' + wid, JSON.stringify(layout));
      } catch (e) {}
    }

    function loadErLayout() {
      const canvas = document.getElementById('er-interactive-canvas');
      if (!canvas) return;
      const wid = canvas.getAttribute('data-website-id') || 'default';
      try {
        const savedZoom = parseFloat(localStorage.getItem('alm_er_zoom_' + wid) || '1');
        if (!isNaN(savedZoom) && savedZoom >= 0.4 && savedZoom <= 1.5) {
          erZoomLevel = savedZoom;
        }
        const raw = localStorage.getItem('alm_er_layout_' + wid);
        if (!raw) {
          applyErZoom();
          return;
        }
        const layout = JSON.parse(raw);
        if (layout && layout.nodes) {
          Object.entries(layout.nodes).forEach(([aid, pos]) => {
            const el = document.getElementById('er-node-' + aid);
            if (el && pos && typeof pos.left === 'number' && typeof pos.top === 'number') {
              el.style.left = pos.left + 'px';
              el.style.top = pos.top + 'px';
            }
          });
        }
        if (layout && layout.zones) {
          Object.entries(layout.zones).forEach(([cid, pos]) => {
            const el = canvas.querySelector(`.er-zone-box[data-cluster-id="${cid}"]`);
            if (el && pos && typeof pos.left === 'number' && typeof pos.top === 'number') {
              el.style.left = pos.left + 'px';
              el.style.top = pos.top + 'px';
              if (typeof pos.width === 'number' && pos.width >= 240) {
                el.style.width = pos.width + 'px';
                el.setAttribute('data-custom-size', '1');
              }
              if (typeof pos.height === 'number' && pos.height >= 140) {
                el.style.height = pos.height + 'px';
                el.setAttribute('data-custom-size', '1');
              }
            }
          });
        }
      } catch (e) {}
      applyErZoom();
    }

    function selectErRelation(relId) {
      selectedErRelationId = (selectedErRelationId === relId) ? '' : (relId || '');
      const delBtn = document.getElementById('er-delete-selected-link-btn');
      if (delBtn) {
        delBtn.style.display = selectedErRelationId ? 'inline-flex' : 'none';
      }
      renderErDiagramCanvas();
    }

    async function deleteSelectedErRelation() {
      if (!selectedErRelationId) return;
      const canvas = document.getElementById('er-interactive-canvas');
      const relId = selectedErRelationId;
      await fetch(`/api/relations/${encodeURIComponent(relId)}`, { method: 'DELETE' });
      if (canvas) {
        try {
          const rels = JSON.parse(canvas.getAttribute('data-er-relations') || '[]').filter(
            (r) => String(r.relation_id || '') !== String(relId)
          );
          canvas.setAttribute('data-er-relations', JSON.stringify(rels));
        } catch (e) {}
      }
      selectedErRelationId = '';
      const delBtn = document.getElementById('er-delete-selected-link-btn');
      if (delBtn) delBtn.style.display = 'none';
      renderErDiagramCanvas();
    }

    function resetErCanvasLayout() {
      if (window.erFlowActions && typeof window.erFlowActions.resetLayout === 'function') {
        window.erFlowActions.resetLayout();
        return;
      }
      const canvas = document.getElementById('er-interactive-canvas');
      if (canvas) {
        const wid = canvas.getAttribute('data-website-id') || 'default';
        try {
          localStorage.removeItem('alm_er_layout_' + wid);
          localStorage.removeItem('alm_er_zoom_' + wid);
        } catch (e) {}
      }
      erZoomLevel = 1;
      applyErZoom();
      document.querySelectorAll('.er-entity-table').forEach((el) => {
        const l = el.getAttribute('data-init-left');
        const t = el.getAttribute('data-init-top');
        if (l !== null) el.style.left = l + 'px';
        if (t !== null) el.style.top = t + 'px';
      });
      renderErDiagramCanvas();
    }

    function renderErDiagramCanvas() {
      const canvas = document.getElementById('er-interactive-canvas');
      const stage = document.getElementById('er-zoom-stage') || canvas;
      const svg = document.getElementById('er-svg-connectors');
      if (!canvas || !svg || !stage) return;
      const sRect = stage.getBoundingClientRect();
      if (sRect.width === 0) return;
      const scale = erZoomLevel || 1;
      const toStageX = (clientX) => (clientX - sRect.left) / scale;
      const toStageY = (clientY) => (clientY - sRect.top) / scale;

      // 1. Update shaded cluster zones around member VM tables (unless empty, currently being dragged, or custom resized)
      stage.querySelectorAll('.er-zone-box').forEach((zone) => {
        if (zone.getAttribute('data-dragging-cluster') === '1') return;
        if (zone.getAttribute('data-custom-size') === '1') return;
        const membersAttr = zone.getAttribute('data-zone-members') || '';
        const memberIds = membersAttr.split(',').map((s) => s.trim()).filter(Boolean);
        let minX = 99999, minY = 99999, maxX = 0, maxY = 0, found = 0;
        memberIds.forEach((id) => {
          const nodeEl = document.getElementById('er-node-' + id);
          if (!nodeEl) return;
          found++;
          const x = nodeEl.offsetLeft;
          const y = nodeEl.offsetTop;
          const w = nodeEl.offsetWidth || 240;
          const h = nodeEl.offsetHeight || 160;
          minX = Math.min(minX, x);
          minY = Math.min(minY, y);
          maxX = Math.max(maxX, x + w);
          maxY = Math.max(maxY, y + h);
        });
        if (found > 0) {
          zone.style.left = Math.max(12, minX - 20) + 'px';
          zone.style.top = Math.max(10, minY - 52) + 'px';
          zone.style.width = Math.max(380, maxX - minX + 40) + 'px';
          zone.style.height = (maxY - minY + 72) + 'px';
        } else {
          if (!zone.style.width) zone.style.width = '380px';
          if (!zone.style.height) zone.style.height = '200px';
        }
      });

      // Auto-expand stage & SVG to fit all VMs and clusters (supports 10-50+ machines cleanly)
      let stageMaxX = Math.max(820, canvas.clientWidth / scale);
      let stageMaxY = Math.max(540, canvas.clientHeight / scale);
      stage.querySelectorAll('.er-zone-box, .er-entity-table').forEach((el) => {
        stageMaxX = Math.max(stageMaxX, el.offsetLeft + el.offsetWidth + 100);
        stageMaxY = Math.max(stageMaxY, el.offsetTop + el.offsetHeight + 100);
      });
      stage.style.width = stageMaxX + 'px';
      stage.style.height = stageMaxY + 'px';
      svg.setAttribute('width', String(stageMaxX));
      svg.setAttribute('height', String(stageMaxY));

      // Helper: find cluster zone box containing an agent or matching cluster:ID
      function findZoneBox(idStr) {
        if (!idStr) return null;
        const clean = String(idStr).trim();
        const direct = stage.querySelector(`.er-zone-box[data-cluster-id="${clean}"], .er-zone-box[data-cluster-id="cluster:${clean}"]`);
        if (direct) return direct;
        let matched = null;
        stage.querySelectorAll('.er-zone-box').forEach((z) => {
          const members = (z.getAttribute('data-zone-members') || '').split(',').map((s) => s.trim());
          if (members.includes(clean)) matched = z;
        });
        return matched;
      }

      // 2. Render SVG connectors
      let rels = [];
      try {
        rels = JSON.parse(canvas.getAttribute('data-er-relations') || '[]');
      } catch (e) {
        rels = [];
      }

      let svgHtml = '';
      const drawnClusterLinks = new Set();

      rels.forEach((rel) => {
        const relId = String(rel.relation_id || '');
        const isSelected = Boolean(relId && relId === selectedErRelationId);
        const isPeer = rel.relation_type === 'PEER_SYNC';
        const srcZone = findZoneBox(rel.source_id);
        const dstZone = findZoneBox(rel.target_id);

        if (!isPeer && srcZone && dstZone && srcZone !== dstZone) {
          const zoneKey = `${srcZone.id || srcZone.getAttribute('data-cluster-id')}->${dstZone.id || dstZone.getAttribute('data-cluster-id')}:${rel.relation_type}`;
          if (drawnClusterLinks.has(zoneKey)) return;
          drawnClusterLinks.add(zoneKey);

          const szRect = srcZone.getBoundingClientRect();
          const dzRect = dstZone.getBoundingClientRect();

          const verticalStack = dzRect.top >= szRect.bottom - 30 * scale;
          let p1x, p1y, p2x, p2y, pathD, mx, my;
          const stroke = isSelected ? '#dc2626' : '#1e293b';

          if (verticalStack) {
            p1x = toStageX((szRect.left + szRect.right) / 2);
            p1y = toStageY(szRect.bottom);
            p2x = toStageX((dzRect.left + dzRect.right) / 2);
            p2y = toStageY(dzRect.top);
            const midY = (p1y + p2y) / 2;
            pathD = `M ${p1x} ${p1y} L ${p1x} ${midY} L ${p2x} ${midY} L ${p2x} ${p2y}`;
            mx = (p1x + p2x) / 2;
            my = midY;
          } else {
            p1x = toStageX(szRect.right);
            p1y = toStageY((szRect.top + szRect.bottom) / 2);
            p2x = toStageX(dzRect.left);
            p2y = toStageY((dzRect.top + dzRect.bottom) / 2);
            const midX = (p1x + p2x) / 2;
            pathD = `M ${p1x} ${p1y} L ${midX} ${p1y} L ${midX} ${p2y} L ${p2x} ${p2y}`;
            mx = midX;
            my = (p1y + p2y) / 2;
          }

          const clickAttr = relId ? `style="pointer-events:all;cursor:pointer;" onclick="selectErRelation('${escapeHtml(relId)}')"` : '';
          svgHtml += `<path d="${pathD}" fill="none" stroke="transparent" stroke-width="16" ${clickAttr} />`;
          svgHtml += `<path d="${pathD}" fill="none" stroke="${stroke}" stroke-width="${isSelected ? '3.5' : '2.5'}" ${clickAttr} />`;
          svgHtml += `<circle cx="${p1x}" cy="${p1y}" r="5" fill="${stroke}" />`;
          svgHtml += `<g ${clickAttr}>`;
          svgHtml += `<rect x="${mx - 62}" y="${my - 12}" width="124" height="24" rx="12" fill="${isSelected ? '#fee2e2' : '#ffffff'}" stroke="${stroke}" stroke-width="1.6" />`;
          svgHtml += `<text x="${mx}" y="${my + 4}" text-anchor="middle" font-size="10.5" font-weight="bold" fill="${stroke}">${isSelected ? '🗑️ คลิกเพื่อลบ' : '⊕ เชื่อมคลัสเตอร์'}</text>`;
          svgHtml += `</g>`;
          return;
        }

        const srcNode = document.getElementById('er-node-' + rel.source_id) || srcZone;
        const dstNode = document.getElementById('er-node-' + rel.target_id) || dstZone;
        if (!srcNode || !dstNode) return;

        const srcRow = document.getElementById('er-port-out-' + rel.source_id) || srcNode;
        const dstRow = (isPeer
          ? document.getElementById('er-port-out-' + rel.target_id)
          : document.getElementById('er-port-in-' + rel.target_id)) || dstNode;

        const srcRect = srcRow.getBoundingClientRect();
        const dstRect = dstRow.getBoundingClientRect();

        const srcCenterX = (srcRect.left + srcRect.right) / 2;
        const dstCenterX = (dstRect.left + dstRect.right) / 2;
        const horizGap = Math.abs(dstCenterX - srcCenterX) / scale;
        const fromRight = horizGap < 60 ? true : dstCenterX >= srcCenterX;
        const toLeft = horizGap < 60 ? false : dstCenterX >= srcCenterX;

        const p1x = toStageX(fromRight ? srcRect.right : srcRect.left);
        const p1y = toStageY((srcRect.top + srcRect.bottom) / 2);
        const p2x = toStageX(toLeft ? dstRect.left : dstRect.right);
        const p2y = toStageY((dstRect.top + dstRect.bottom) / 2);

        const dx = Math.max(55, Math.abs(p2x - p1x) * 0.42);
        const c1x = fromRight ? p1x + dx : p1x - dx;
        const c2x = toLeft ? p2x - dx : p2x + dx;

        const stroke = isSelected ? '#dc2626' : (isPeer ? '#6d28d9' : '#334155');
        const dashAttr = isPeer ? 'stroke-dasharray="5,4"' : '';
        const pathD = `M ${p1x} ${p1y} C ${c1x} ${p1y}, ${c2x} ${p2y}, ${p2x} ${p2y}`;
        const clickAttr = relId ? `style="pointer-events:all;cursor:pointer;" onclick="selectErRelation('${escapeHtml(relId)}')"` : '';

        svgHtml += `<path d="${pathD}" fill="none" stroke="transparent" stroke-width="16" ${clickAttr} />`;
        svgHtml += `<path d="${pathD}" fill="none" stroke="${stroke}" stroke-width="${isSelected ? '3.4' : '2.2'}" ${dashAttr} ${clickAttr} />`;
        svgHtml += `<circle cx="${p1x}" cy="${p1y}" r="4.2" fill="${stroke}" />`;

        const dir = toLeft ? -1 : 1;
        svgHtml += `<line x1="${p2x + dir * 10}" y1="${p2y - 6}" x2="${p2x + dir * 10}" y2="${p2y + 6}" stroke="${stroke}" stroke-width="1.8" />`;
        svgHtml += `<line x1="${p2x + dir * 10}" y1="${p2y}" x2="${p2x}" y2="${p2y - 5}" stroke="${stroke}" stroke-width="1.6" />`;
        svgHtml += `<line x1="${p2x + dir * 10}" y1="${p2y}" x2="${p2x}" y2="${p2y + 5}" stroke="${stroke}" stroke-width="1.6" />`;

        const mx = 0.125 * p1x + 0.375 * c1x + 0.375 * c2x + 0.125 * p2x;
        const my = 0.125 * p1y + 0.375 * p1y + 0.375 * p2y + 0.125 * p2y;
        svgHtml += `<g ${clickAttr}>`;
        svgHtml += `<circle cx="${mx}" cy="${my}" r="10.5" fill="${isSelected ? '#fee2e2' : '#ffffff'}" stroke="${stroke}" stroke-width="1.6" />`;
        svgHtml += `<text x="${mx}" y="${my + 3.5}" text-anchor="middle" font-size="10.5" font-weight="bold" fill="${stroke}">${isSelected ? '✕' : (isPeer ? '⇄' : '⊕')}</text>`;
        svgHtml += `</g>`;
      });

      if (window._erDraftLine) {
        const dl = window._erDraftLine;
        svgHtml += `<line x1="${dl.x1}" y1="${dl.y1}" x2="${dl.x2}" y2="${dl.y2}" stroke="#2563eb" stroke-width="2.8" stroke-dasharray="6,4" />`;
        svgHtml += `<circle cx="${dl.x1}" cy="${dl.y1}" r="5" fill="#2563eb" />`;
        svgHtml += `<circle cx="${dl.x2}" cy="${dl.y2}" r="5" fill="#2563eb" />`;
      }

      svg.innerHTML = svgHtml;
    }

    (function initErCanvasDrag() {
      if (document.getElementById('er-xyflow-root')) {
        document.querySelectorAll('.er-palette-item').forEach((item) => {
          item.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('palette_type', item.getAttribute('data-palette-type') || 'vm');
            e.dataTransfer.setData('palette_role', item.getAttribute('data-palette-role') || 'vm');
          });
        });
        return;
      }
      let activeNode = null;
      let activeCluster = null;
      let resizingCluster = null;
      let clusterMemberOffsets = [];
      let startX = 0, startY = 0, origLeft = 0, origTop = 0, origW = 0, origH = 0;
      let linkSourceId = null;

      function resolveConnectRepresentative(el) {
        if (!el) return null;
        const tableEl = el.closest('.er-entity-table');
        if (tableEl) return tableEl.getAttribute('data-agent-id');
        const zoneEl = el.closest('.er-zone-box');
        if (zoneEl) {
          const members = (zoneEl.getAttribute('data-zone-members') || '').split(',').map((s) => s.trim()).filter(Boolean);
          if (members.length > 0) return members[0];
          return zoneEl.getAttribute('data-cluster-id');
        }
        return null;
      }

      document.addEventListener('mousedown', (e) => {
        if (e.target.closest('button, a, input, select')) return;

        const stage = document.getElementById('er-zoom-stage') || document.getElementById('er-interactive-canvas');
        const scale = erZoomLevel || 1;
        const getStagePt = (cx, cy) => {
          const sr = stage ? stage.getBoundingClientRect() : { left: 0, top: 0 };
          return { x: (cx - sr.left) / scale, y: (cy - sr.top) / scale };
        };

        const zoneAnchor = e.target.closest('.er-zone-anchor');
        if (zoneAnchor) {
          linkSourceId = resolveConnectRepresentative(zoneAnchor);
          const pt = getStagePt(e.clientX, e.clientY);
          window._erDraftLine = { x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y };
          renderErDiagramCanvas();
          e.preventDefault();
          return;
        }
        const dot = e.target.closest('.er-anchor-dot');
        if (dot) {
          linkSourceId = resolveConnectRepresentative(dot);
          const pt = getStagePt(e.clientX, e.clientY);
          window._erDraftLine = { x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y };
          renderErDiagramCanvas();
          e.preventDefault();
          return;
        }

        // Check if dragging a VM Entity Table
        const vmTable = e.target.closest('.er-entity-table');
        if (vmTable) {
          activeNode = vmTable;
          startX = e.clientX;
          startY = e.clientY;
          origLeft = activeNode.offsetLeft;
          origTop = activeNode.offsetTop;
          e.preventDefault();
          return;
        }

        const resizeHandle = e.target.closest('.er-zone-resize-handle');
        if (resizeHandle) {
          const z = resizeHandle.closest('.er-zone-box');
          if (z) {
            resizingCluster = z;
            resizingCluster.setAttribute('data-custom-size', '1');
            startX = e.clientX;
            startY = e.clientY;
            origW = z.offsetWidth;
            origH = z.offsetHeight;
            e.preventDefault();
            return;
          }
        }

        // Check if dragging a Cluster Zone Box
        const zoneBox = e.target.closest('.er-zone-box');
        if (zoneBox) {
          activeCluster = zoneBox;
          activeCluster.setAttribute('data-dragging-cluster', '1');
          startX = e.clientX;
          startY = e.clientY;
          origLeft = activeCluster.offsetLeft;
          origTop = activeCluster.offsetTop;
          const members = (activeCluster.getAttribute('data-zone-members') || '').split(',').map((s) => s.trim()).filter(Boolean);
          clusterMemberOffsets = [];
          members.forEach((id) => {
            const mEl = document.getElementById('er-node-' + id);
            if (mEl) {
              clusterMemberOffsets.push({ el: mEl, left: mEl.offsetLeft, top: mEl.offsetTop });
            }
          });
          e.preventDefault();
          return;
        }
      });

      document.addEventListener('mousemove', (e) => {
        const scale = erZoomLevel || 1;
        if (linkSourceId && window._erDraftLine) {
          const stage = document.getElementById('er-zoom-stage') || document.getElementById('er-interactive-canvas');
          if (stage) {
            const sr = stage.getBoundingClientRect();
            window._erDraftLine.x2 = (e.clientX - sr.left) / scale;
            window._erDraftLine.y2 = (e.clientY - sr.top) / scale;
            renderErDiagramCanvas();
          }
          return;
        }
        if (resizingCluster) {
          const nw = Math.max(240, origW + (e.clientX - startX) / scale);
          const nh = Math.max(140, origH + (e.clientY - startY) / scale);
          resizingCluster.style.width = nw + 'px';
          resizingCluster.style.height = nh + 'px';
          renderErDiagramCanvas();
          return;
        }
        if (activeNode) {
          const nx = Math.max(16, origLeft + (e.clientX - startX) / scale);
          const ny = Math.max(58, origTop + (e.clientY - startY) / scale);
          activeNode.style.left = nx + 'px';
          activeNode.style.top = ny + 'px';
          renderErDiagramCanvas();
          return;
        }
        if (activeCluster) {
          const dx = (e.clientX - startX) / scale;
          const dy = (e.clientY - startY) / scale;
          const nx = Math.max(10, origLeft + dx);
          const ny = Math.max(10, origTop + dy);
          const realDx = nx - origLeft;
          const realDy = ny - origTop;
          activeCluster.style.left = nx + 'px';
          activeCluster.style.top = ny + 'px';
          clusterMemberOffsets.forEach((item) => {
            item.el.style.left = Math.max(16, item.left + realDx) + 'px';
            item.el.style.top = Math.max(56, item.top + realDy) + 'px';
          });
          renderErDiagramCanvas();
        }
      });

      document.addEventListener('mouseup', async (e) => {
        if (linkSourceId) {
          const targetId = resolveConnectRepresentative(e.target);
          const srcId = linkSourceId;
          linkSourceId = null;
          window._erDraftLine = null;
          if (targetId && targetId !== srcId) {
            const canvas = document.getElementById('er-interactive-canvas');
            const websiteId = canvas ? canvas.getAttribute('data-website-id') : '';
            const relType = (srcId.startsWith('db') && targetId.startsWith('db')) ? 'PEER_SYNC' : 'ROUTE_TO';
            const res = await fetch('/api/relations', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ website_id: websiteId, source_id: srcId, target_id: targetId, relation_type: relType })
            });
            const createdRel = await res.json().catch(() => null);
            if (canvas && createdRel && createdRel.relation_id) {
              try {
                const rels = JSON.parse(canvas.getAttribute('data-er-relations') || '[]');
                rels.push({
                  relation_id: createdRel.relation_id,
                  source_id: createdRel.source_id || srcId,
                  target_id: createdRel.target_id || targetId,
                  relation_type: (createdRel.relation_type || relType).toUpperCase(),
                  port: createdRel.port || null
                });
                canvas.setAttribute('data-er-relations', JSON.stringify(rels));
              } catch (err) {}
            }
          }
          renderErDiagramCanvas();
        }
        if (resizingCluster) {
          resizingCluster = null;
          saveErLayout();
          renderErDiagramCanvas();
        }
        if (activeCluster) {
          activeCluster.removeAttribute('data-dragging-cluster');
          activeCluster = null;
          clusterMemberOffsets = [];
          saveErLayout();
          renderErDiagramCanvas();
        }
        if (activeNode) {
          activeNode = null;
          saveErLayout();
        }
      });

      // Equipment Palette Drag & Drop onto ER Canvas (NO prompt() popups!)
      document.querySelectorAll('.er-palette-item').forEach((item) => {
        item.addEventListener('dragstart', (e) => {
          e.dataTransfer.setData('palette_type', item.getAttribute('data-palette-type') || 'vm');
          e.dataTransfer.setData('palette_role', item.getAttribute('data-palette-role') || 'vm');
        });
      });

      const canvas = document.getElementById('er-interactive-canvas');
      if (canvas) {
        canvas.addEventListener('dragover', (e) => e.preventDefault());
        canvas.addEventListener('drop', async (e) => {
          e.preventDefault();
          const pType = e.dataTransfer.getData('palette_type');
          const websiteId = canvas.getAttribute('data-website-id') || 'website_1';
          const stage = document.getElementById('er-zoom-stage') || canvas;
          const sRect = stage.getBoundingClientRect();
          const scale = erZoomLevel || 1;
          const dropX = Math.max(24, Math.round((e.clientX - sRect.left) / scale - 110));
          const dropY = Math.max(24, Math.round((e.clientY - sRect.top) / scale - 40));

          if (pType === 'cluster') {
            const count = canvas.querySelectorAll('.er-zone-box').length + 1;
            const defaultName = `Cluster ใหม่ #${count}`;
            const res = await fetch('/api/clusters', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ website_id: websiteId, name: defaultName, cluster_type: 'ha_cluster', quorum_min: 2 })
            });
            const created = await res.json();
            const cid = created.cluster_id || ('cluster_new_' + Date.now());
            const zoneDiv = document.createElement('div');
            zoneDiv.className = 'er-zone-box er-zone-green er-cluster-card';
            zoneDiv.id = 'er-zone-' + cid;
            zoneDiv.setAttribute('data-cluster-id', cid);
            zoneDiv.setAttribute('data-cluster-name', defaultName);
            zoneDiv.setAttribute('data-cluster-type', 'ha_cluster');
            zoneDiv.setAttribute('data-zone-members', '');
            zoneDiv.style.left = dropX + 'px';
            zoneDiv.style.top = dropY + 'px';
            zoneDiv.style.width = '420px';
            zoneDiv.style.height = '220px';
            zoneDiv.innerHTML = `
              <span class="er-zone-anchor er-zone-anchor-top" data-zone-connect="cluster:${escapeHtml(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>
              <span class="er-zone-anchor er-zone-anchor-bottom" data-zone-connect="cluster:${escapeHtml(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>
              <span class="er-zone-anchor er-zone-anchor-left" data-zone-connect="cluster:${escapeHtml(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>
              <span class="er-zone-anchor er-zone-anchor-right" data-zone-connect="cluster:${escapeHtml(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>
              <div class="er-zone-header" data-er-drag-handle="er-zone-${escapeHtml(cid)}">
                <strong class="er-zone-title-text">cluster: ${escapeHtml(defaultName)}</strong>
                <div style="display:flex;align-items:center;gap:6px;">
                  <span class="status-badge status-nodata">⚪ รอข้อมูล (0/0)</span>
                  <button type="button" class="er-dots-btn" onclick="openErEditModal('cluster', '${escapeHtml(cid)}')">⋯</button>
                </div>
              </div>
              <div class="er-empty-cluster-hint">ลากเครื่อง VM มาวางในกรอบนี้ หรือกดปุ่ม <b>⋯</b> มุมขวาบนเพื่อเปลี่ยนชื่อ/เลือกเครื่อง/ลบ</div>
              <div class="er-zone-resize-handle" title="ลากมุมนี้เพื่อปรับขนาดคลัสเตอร์"></div>
            `;
            stage.insertBefore(zoneDiv, stage.firstChild);
            saveErLayout();
            renderErDiagramCanvas();
          } else {
            const count = canvas.querySelectorAll('.er-entity-table').length + 1;
            const vmName = `vm_${count}`;
            // Check if dropped inside an existing cluster box
            let droppedClusterId = '';
            canvas.querySelectorAll('.er-zone-box').forEach((z) => {
              const zr = z.getBoundingClientRect();
              if (e.clientX >= zr.left && e.clientX <= zr.right && e.clientY >= zr.top && e.clientY <= zr.bottom) {
                const rawCid = z.getAttribute('data-cluster-id') || '';
                if (!rawCid.startsWith('cluster:upstream')) {
                  droppedClusterId = rawCid.replace(/^cluster:/, '');
                  const cur = (z.getAttribute('data-zone-members') || '').split(',').map((s) => s.trim()).filter(Boolean);
                  if (!cur.includes(vmName)) {
                    cur.push(vmName);
                    z.setAttribute('data-zone-members', cur.join(','));
                  }
                }
              }
            });
            await fetch('/api/agents/assign', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                agent_id: vmName,
                website_id: websiteId,
                agent_role: 'app',
                hostname: `${vmName}.local`,
                cluster_id: droppedClusterId,
                upsert_if_missing: true
              })
            });
            const div = document.createElement('div');
            div.className = 'er-entity-table er-member-node';
            div.id = 'er-node-' + vmName;
            div.setAttribute('data-agent-id', vmName);
            div.setAttribute('data-agent-host', `${vmName}.local`);
            div.setAttribute('data-agent-role', 'app');
            div.setAttribute('data-cluster-id', droppedClusterId);
            div.style.left = dropX + 'px';
            div.style.top = Math.max(64, dropY) + 'px';
            div.innerHTML = `
              <div class="er-entity-header er-hdr-blue" data-er-drag-handle="er-node-${escapeHtml(vmName)}">
                <span class="er-vm-title-text">${escapeHtml(vmName)}</span>
                <button type="button" class="er-hdr-dots" onclick="openErEditModal('vm', '${escapeHtml(vmName)}')">⋯</button>
              </div>
              <div class="er-entity-rows">
                <div class="er-entity-row" id="er-port-in-${escapeHtml(vmName)}">
                  <span class="er-anchor-dot er-anchor-left"></span>
                  <span class="er-col-name">🔑 _host</span><span class="er-col-type er-vm-host-text">${escapeHtml(vmName)}.local NN</span>
                </div>
                <div class="er-entity-row">
                  <span class="er-col-name">⚡ status</span><span class="er-col-type" style="color:#16a34a;font-weight:700;">ONLINE</span>
                </div>
                <div class="er-entity-row">
                  <span class="er-col-name">📊 metrics</span><span class="er-col-type">ดึงจาก Log อัตโนมัติ</span>
                </div>
                <div class="er-entity-row" id="er-port-out-${escapeHtml(vmName)}">
                  <span class="er-anchor-dot er-anchor-left"></span>
                  <span class="er-col-name">🔌 <span class="er-vm-role-text">app</span> <b style="color:#d97706;">{}</b></span>
                  <span class="er-col-type">link 👁</span>
                  <span class="er-anchor-dot er-anchor-right"></span>
                </div>
                <div class="er-entity-footer">
                  <a class="node-link-sm" href="/website?website_id=${encodeURIComponent(websiteId)}&agent_id=${encodeURIComponent(vmName)}">ดู Log →</a>
                </div>
              </div>
            `;
            stage.appendChild(div);
            saveErLayout();
            renderErDiagramCanvas();
          }
        });
      }

      window.addEventListener('load', () => {
        loadErLayout();
        setTimeout(renderErDiagramCanvas, 60);
      });
      window.addEventListener('resize', renderErDiagramCanvas);
      loadErLayout();
      setTimeout(renderErDiagramCanvas, 80);
    })();

    function closeErEditModal() {
      const m = document.getElementById('er-edit-modal') || document.getElementById('er-item-edit-modal');
      if (m) m.style.display = 'none';
    }

    function openAgentListEditModal(agentId, curHost, curRole, curWebId, curClusterId) {
      const modal = document.getElementById('er-item-edit-modal') || document.getElementById('er-edit-modal');
      const titleEl = document.getElementById('er-edit-modal-title');
      const bodyEl = document.getElementById('er-edit-modal-body');
      if (!modal || !bodyEl) return;
      titleEl.textContent = `✏️ แก้ไขข้อมูลเครื่อง: ${agentId}`;
      bodyEl.innerHTML = `
        <div style="display:grid;gap:10px;">
          <label style="font-size:12.5px;font-weight:700;">ชื่อเครื่อง / Agent ID
            <input id="edit-vm-id" value="${escapeHtml(agentId)}" readonly style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;background:#f8fafc;">
          </label>
          <label style="font-size:12.5px;font-weight:700;">วงเว็บไซต์ (Website ID เช่น website_1, web_sit, web_uat)
            <input id="edit-vm-web" value="${escapeHtml(curWebId || 'website_1')}" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
          </label>
          <label style="font-size:12.5px;font-weight:700;">ชื่อโฮสต์ / IP (Hostname)
            <input id="edit-vm-host" value="${escapeHtml(curHost || agentId)}" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
          </label>
          <label style="font-size:12.5px;font-weight:700;">บทบาทหน้าที่ (Service Role)
            <select id="edit-vm-role" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
              <option value="web" ${curRole === 'web' ? 'selected' : ''}>web (Web / Reverse Proxy)</option>
              <option value="app" ${curRole === 'app' ? 'selected' : ''}>app (Application / Worker)</option>
              <option value="db" ${curRole === 'db' ? 'selected' : ''}>db (Database Node)</option>
              <option value="lb" ${curRole === 'lb' ? 'selected' : ''}>lb (Load Balancer)</option>
            </select>
          </label>
          <label style="font-size:12.5px;font-weight:700;">สังกัดคลัสเตอร์ (Cluster ID - เว้นว่างถ้าแยกเดี่ยว)
            <input id="edit-vm-cluster" value="${escapeHtml(curClusterId || '')}" placeholder="เช่น kdt-db-galera-cluster" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
          </label>
          <div style="display:flex;justify-content:space-between;gap:8px;margin-top:8px;">
            <button type="button" class="secondary" style="color:var(--critical);border-color:var(--critical);" onclick="deleteErItem('vm', '${escapeHtml(agentId)}')">🗑️ ลบเครื่องนี้</button>
            <button type="button" class="primary-action" onclick="saveAgentListEdit('${escapeHtml(agentId)}')">💾 บันทึกการแก้ไข</button>
          </div>
        </div>
      `;
      modal.style.display = 'flex';
    }

    async function saveAgentListEdit(agentId) {
      const wid = (document.getElementById('edit-vm-web')?.value || 'website_1').trim();
      const host = (document.getElementById('edit-vm-host')?.value || agentId).trim();
      const role = document.getElementById('edit-vm-role')?.value || 'app';
      const cid = (document.getElementById('edit-vm-cluster')?.value || '').trim();
      await fetch('/api/agents/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: agentId,
          website_id: wid,
          agent_role: role,
          hostname: host,
          cluster_id: cid,
          upsert_if_missing: true
        })
      });
      location.reload();
    }

    function closeIncidentDetailModal() {
      const m = document.getElementById('incident-detail-modal');
      if (m) m.style.display = 'none';
    }

    function filterSourceRawLogs() {
      const limit = parseInt(document.getElementById('raw-log-limit')?.value || '100', 10);
      const fromVal = document.getElementById('raw-log-from')?.value || '';
      const toVal = document.getElementById('raw-log-to')?.value || '';
      const fromMs = fromVal ? new Date(fromVal).getTime() : null;
      const toMs = toVal ? new Date(toVal).getTime() : null;
      let shown = 0;
      document.querySelectorAll('#raw-log-table tbody tr.raw-log-row').forEach((row) => {
        const tsStr = row.getAttribute('data-log-ts') || '';
        const tsMs = tsStr ? new Date(tsStr).getTime() : null;
        let match = true;
        if (fromMs && tsMs && tsMs < fromMs) match = false;
        if (toMs && tsMs && tsMs > toMs) match = false;
        if (match && shown < limit) {
          row.style.display = '';
          shown += 1;
        } else {
          row.style.display = 'none';
        }
      });
    }

    function filterIncidentsByDate() {
      const dateInput = document.getElementById('incident-date-filter');
      const selectedDate = dateInput ? dateInput.value.trim() : '';
      const rows = document.querySelectorAll('#incidents-tbody tr.incident-row');
      rows.forEach(row => {
        const rowDate = row.getAttribute('data-incident-date') || '';
        if (!selectedDate || rowDate === selectedDate) {
          row.style.display = '';
        } else {
          row.style.display = 'none';
        }
      });
    }

    function clearIncidentDateFilter() {
      const dateInput = document.getElementById('incident-date-filter');
      if (dateInput) dateInput.value = '';
      filterIncidentsByDate();
    }

    async function suppressIncidentRow(btn) {
      if (!btn) return;
      const incId = btn.getAttribute('data-inc-id') || '';
      const webId = btn.getAttribute('data-inc-web') || '';
      const title = btn.getAttribute('data-inc-title') || '';
      await fetch('/api/incidents/suppress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incident_id: incId, website_id: webId, title: title })
      });
      const tr = btn.closest('tr');
      if (tr) tr.remove();
    }

    function openIncidentDetailModal(btn) {
      const modal = document.getElementById('incident-detail-modal');
      const titleEl = document.getElementById('incident-detail-modal-title');
      const bodyEl = document.getElementById('incident-detail-modal-body');
      if (!modal || !bodyEl || !btn) return;
      const webId = btn.getAttribute('data-inc-web') || '-';
      const machineId = btn.getAttribute('data-inc-machine') || '-';
      const title = btn.getAttribute('data-inc-title') || '-';
      const sev = btn.getAttribute('data-inc-sev') || 'warning';
      const aiImpact = btn.getAttribute('data-inc-ai') || '';
      const firstSeen = btn.getAttribute('data-inc-first') || '-';
      const lastSeen = btn.getAttribute('data-inc-last') || '-';
      let evidence = [];
      try {
        evidence = JSON.parse(btn.getAttribute('data-inc-evidence') || '[]');
      } catch (e) {
        evidence = [title];
      }
      titleEl.textContent = `🔍 รายละเอียดเหตุการณ์: ${title}`;
      const evHtml = evidence.map(line => `<li style="font-family:monospace;font-size:12px;padding:6px 8px;background:#0f172a;color:#e2e8f0;border-radius:6px;margin-bottom:6px;word-break:break-word;">${escapeHtml(line)}</li>`).join('');
      bodyEl.innerHTML = `
        <div style="display:grid;gap:12px;">
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;background:#f8fafc;padding:12px;border-radius:8px;border:1px solid #e2e8f0;font-size:13px;">
            <div><span class="muted">เว็บไซต์ (Website):</span><br><strong>${escapeHtml(webId)}</strong></div>
            <div><span class="muted">เครื่องต้นตอ (Machine):</span><br><strong style="color:var(--critical);">${escapeHtml(machineId)}</strong></div>
            <div><span class="muted">พบครั้งแรก (First Seen):</span><br><strong>${escapeHtml(firstSeen)}</strong></div>
            <div><span class="muted">พบล่าสุด (Last Seen):</span><br><strong>${escapeHtml(lastSeen)}</strong></div>
            <div style="grid-column:span 2;"><span class="muted">ความรุนแรง & ผลวิเคราะห์ AI:</span><br><strong>${escapeHtml(sev.toUpperCase())}</strong> — ${escapeHtml(aiImpact)}</div>
          </div>
          <div>
            <strong style="display:block;margin-bottom:6px;font-size:13px;">📜 หลักฐานบรรทัด Log ตอนเกิดเหตุ (Log Evidence):</strong>
            <ul style="list-style:none;padding:0;margin:0;max-height:240px;overflow-y:auto;">${evHtml}</ul>
          </div>
          <div style="display:flex;justify-content:flex-end;gap:8px;">
            <a class="secondary" href="/website?website_id=${encodeURIComponent(webId)}${machineId && machineId !== '-' ? '&agent_id=' + encodeURIComponent(machineId) : ''}" style="text-decoration:none;padding:7px 12px;border-radius:6px;border:1px solid var(--border);font-size:12.5px;">ไปที่หน้าเครื่อง ${escapeHtml(machineId)} →</a>
            <button type="button" class="primary-action" onclick="closeIncidentDetailModal()">ปิดหน้าต่าง</button>
          </div>
        </div>
      `;
      modal.style.display = 'flex';
    }

    function openErEditModal(kind, targetId, nodeData) {
      const modal = document.getElementById('er-edit-modal');
      const titleEl = document.getElementById('er-edit-modal-title');
      const bodyEl = document.getElementById('er-edit-modal-body');
      const canvas = document.getElementById('er-interactive-canvas');
      if (!modal || !bodyEl || !canvas) return;
      const websiteId = canvas.getAttribute('data-website-id') || 'website_1';

      if (kind === 'cluster') {
        const cleanCid = String(targetId).replace(/^cluster:/, '');
        const zoneEl = document.getElementById('er-zone-' + cleanCid) || canvas.querySelector(`.er-zone-box[data-cluster-id="${targetId}"]`);
        const curName = (nodeData && nodeData.name) ? nodeData.name : (zoneEl ? (zoneEl.getAttribute('data-cluster-name') || cleanCid) : cleanCid);
        const curMembers = (nodeData && Array.isArray(nodeData.memberIds)) ? nodeData.memberIds.join(', ') : (zoneEl ? (zoneEl.getAttribute('data-zone-members') || '') : '');
        titleEl.textContent = `✏️ แก้ไขคลัสเตอร์: ${curName}`;
        bodyEl.innerHTML = `
          <div style="display:grid;gap:10px;">
            <label style="font-size:12.5px;font-weight:700;">ชื่อกลุ่มคลัสเตอร์ (Cluster Name)
              <input id="edit-cluster-name" value="${escapeHtml(curName)}" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
            </label>
            <label style="font-size:12.5px;font-weight:700;">รายชื่อเครื่องในคลัสเตอร์ (คั่นด้วยลูกน้ำ เช่น db1, db2)
              <input id="edit-cluster-members" value="${escapeHtml(curMembers)}" placeholder="เช่น db1, db2" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
            </label>
            <div style="display:flex;justify-content:space-between;gap:8px;margin-top:8px;">
              <button type="button" class="secondary" style="color:var(--critical);border-color:var(--critical);" onclick="deleteErItem('cluster', '${escapeHtml(cleanCid)}')">🗑️ ลบคลัสเตอร์นี้</button>
              <button type="button" class="primary-action" onclick="saveErClusterEdit('${escapeHtml(websiteId)}', '${escapeHtml(cleanCid)}')">💾 บันทึกการแก้ไข</button>
            </div>
          </div>
        `;
        modal.style.display = 'flex';
      } else {
        const nodeEl = document.getElementById('er-node-' + targetId);
        const curHost = nodeEl ? (nodeEl.getAttribute('data-agent-host') || targetId) : targetId;
        const curRole = nodeEl ? (nodeEl.getAttribute('data-agent-role') || 'app') : 'app';
        const curCid = nodeEl ? (nodeEl.getAttribute('data-cluster-id') || '') : '';
        titleEl.textContent = `✏️ แก้ไขเครื่อง VM: ${targetId}`;
        bodyEl.innerHTML = `
          <div style="display:grid;gap:10px;">
            <label style="font-size:12.5px;font-weight:700;">ชื่อเครื่อง / Agent ID
              <input id="edit-vm-id" value="${escapeHtml(targetId)}" readonly style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;background:#f8fafc;">
            </label>
            <label style="font-size:12.5px;font-weight:700;">ชื่อโฮสต์ / IP (_host)
              <input id="edit-vm-host" value="${escapeHtml(curHost)}" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
            </label>
            <label style="font-size:12.5px;font-weight:700;">บทบาทหน้าที่ (Service Role)
              <select id="edit-vm-role" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
                <option value="web" ${curRole === 'web' ? 'selected' : ''}>web (Web / Reverse Proxy)</option>
                <option value="app" ${curRole === 'app' ? 'selected' : ''}>app (Application / K8s Worker)</option>
                <option value="db" ${curRole === 'db' ? 'selected' : ''}>db (Database Node)</option>
              </select>
            </label>
            <label style="font-size:12.5px;font-weight:700;">สังกัดกลุ่มคลัสเตอร์ (Cluster ID - เว้นว่างถ้าแยกเดี่ยว)
              <input id="edit-vm-cluster" value="${escapeHtml(curCid)}" placeholder="เช่น kdt-db-galera-cluster" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
            </label>
            <div class="muted" style="font-size:11.5px;">💡 ค่า <b>⚡ status</b> และ <b>📊 metrics</b> ดึงจาก Log ของเครื่องอัตโนมัติ</div>
            <div style="display:flex;justify-content:space-between;gap:8px;margin-top:8px;">
              <button type="button" class="secondary" style="color:var(--critical);border-color:var(--critical);" onclick="deleteErItem('vm', '${escapeHtml(targetId)}')">🗑️ ลบ VM นี้ออกจากผัง</button>
              <button type="button" class="primary-action" onclick="saveErVmEdit('${escapeHtml(websiteId)}', '${escapeHtml(targetId)}')">💾 บันทึกการแก้ไข</button>
            </div>
          </div>
        `;
        modal.style.display = 'flex';
      }
    }

    async function saveErClusterEdit(websiteId, clusterId) {
      const name = document.getElementById('edit-cluster-name').value.trim() || clusterId;
      const members = document.getElementById('edit-cluster-members').value.trim();
      await fetch('/api/clusters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cluster_id: clusterId === 'upstream_gateway' ? undefined : clusterId,
          website_id: websiteId,
          name: name,
          cluster_type: 'ha_cluster',
          quorum_min: 2,
          member_ids: members
        })
      });
      location.reload();
    }

    async function saveErVmEdit(websiteId, agentId) {
      const host = document.getElementById('edit-vm-host').value.trim() || agentId;
      const role = document.getElementById('edit-vm-role').value;
      const cid = document.getElementById('edit-vm-cluster').value.trim();
      await fetch('/api/agents/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: agentId,
          website_id: websiteId,
          agent_role: role,
          hostname: host,
          cluster_id: cid,
          upsert_if_missing: true
        })
      });
      location.reload();
    }

    async function deleteErItem(kind, targetId) {
      const canvas = document.getElementById('er-interactive-canvas');
      if (kind === 'cluster') {
        const cleanId = String(targetId).replace(/^cluster:/, '');
        await fetch('/api/clusters/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cluster_id: cleanId })
        });
        if (window.erFlowActions && typeof window.erFlowActions.removeNode === 'function') {
          window.erFlowActions.removeNode('cluster:' + cleanId);
        }
        const z = document.getElementById('er-zone-' + cleanId);
        if (z) z.remove();
        closeErEditModal();
        if (canvas && !window.erFlowActions) {
          saveErLayout();
          renderErDiagramCanvas();
        } else if (!canvas) {
          location.reload();
        }
      } else {
        await fetch('/api/agents/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent_id: targetId })
        });
        if (window.erFlowActions && typeof window.erFlowActions.removeNode === 'function') {
          window.erFlowActions.removeNode('vm:' + targetId);
        }
        const n = document.getElementById('er-node-' + targetId);
        if (n) n.remove();
        if (canvas && !window.erFlowActions) {
          try {
            const rels = JSON.parse(canvas.getAttribute('data-er-relations') || '[]').filter(
              (r) => String(r.source_id) !== String(targetId) && String(r.target_id) !== String(targetId)
            );
            canvas.setAttribute('data-er-relations', JSON.stringify(rels));
          } catch (e) {}
          closeErEditModal();
          saveErLayout();
          renderErDiagramCanvas();
        } else {
          closeErEditModal();
          location.reload();
        }
      }
    }

    function closeWebsiteEditModal() {
      const m = document.getElementById('website-edit-modal');
      if (m) m.style.display = 'none';
    }

    function openWebsiteEditModal(websiteId, currentName) {
      const modal = document.getElementById('website-edit-modal');
      const titleEl = document.getElementById('website-edit-modal-title');
      const bodyEl = document.getElementById('website-edit-modal-body');
      if (!modal || !bodyEl) return;
      const isNew = !websiteId;
      titleEl.textContent = isNew ? '➕ เพิ่มวงเว็บไซต์ใหม่ (SIT / UAT / Production)' : `✏️ แก้ไขชื่อเว็บไซต์: ${websiteId}`;
      bodyEl.innerHTML = `
        <div style="display:grid;gap:10px;">
          <label style="font-size:12.5px;font-weight:700;">รหัสวงระบบ (Website ID เช่น website_1, web_sit, web_uat, web_prod)
            <input id="edit-website-id" value="${escapeHtml(websiteId)}" ${isNew ? '' : 'readonly'} placeholder="เช่น web_uat" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;${isNew ? '' : 'background:#f8fafc;'}">
          </label>
          <label style="font-size:12.5px;font-weight:700;">ชื่อที่แสดงบนการ์ด (Display Name)
            <input id="edit-website-name" value="${escapeHtml(currentName)}" placeholder="เช่น ระบบ UAT - MariaDB Cluster" style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;">
          </label>
          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px;">
            <button type="button" class="secondary" onclick="closeWebsiteEditModal()">ยกเลิก</button>
            <button type="button" class="primary-action" onclick="saveWebsiteEdit()">💾 บันทึก</button>
          </div>
        </div>
      `;
      modal.style.display = 'flex';
    }

    async function saveWebsiteEdit() {
      const wid = document.getElementById('edit-website-id').value.trim();
      const wname = document.getElementById('edit-website-name').value.trim() || wid;
      if (!wid) return;
      await fetch('/api/websites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ website_id: wid, name: wname })
      });
      location.reload();
    }

    function applyThemeMode(theme) {
      const mode = theme === 'dark' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', mode);
      document.body.setAttribute('data-theme', mode);
      const btn = document.getElementById('theme-toggle-btn');
      if (btn) {
        btn.innerHTML = mode === 'dark' ? '☀️ โหมดสว่าง' : '🌙 โหมดมืด';
      }
    }

    function toggleThemeMode() {
      const cur = document.body.getAttribute('data-theme') || 'light';
      const next = cur === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem('alm_theme_mode', next);
      } catch (e) {}
      applyThemeMode(next);
    }

    (function initSavedTheme() {
      try {
        const saved = localStorage.getItem('alm_theme_mode');
        if (saved === 'dark' || saved === 'light') {
          applyThemeMode(saved);
        }
      } catch (e) {}
    })();

    function translateStepToThai(step) {
      const sNum = step.step;
      if (sNum === 1 || step.stage === 'primary_node') {
        const aid = step.agent_id || '-';
        const role = step.role || '-';
        return {
          title: `ขั้นที่ 1 (จุดเกิดเหตุหลัก): เครื่อง ${aid} (บทบาท: ${role})`,
          detail: `ตรวจพบสัญญาณผิดปกติเริ่มต้นจากเครื่อง ${aid} เป็นลำดับแรก`
        };
      }
      if (sNum === 2 || step.stage === 'cluster_quorum') {
        if (step.cluster_id) {
          const h = step.healthy_nodes ?? 0;
          const t = step.total_nodes ?? 1;
          const qOk = Boolean(step.quorum_maintained);
          return {
            title: `ขั้นที่ 2 (สถานะคลัสเตอร์): คลัสเตอร์ ${step.cluster_id} ออนไลน์ ${h}/${t} เครื่อง`,
            detail: qOk
              ? `โหนดในคลัสเตอร์ยังทำงานทดแทนกันได้ตามปกติ (ระบบสลับการทำงานอัตโนมัติพร้อมใช้งาน)`
              : `⚠️ จำนวนเครื่องที่ออนไลน์ต่ำกว่าเกณฑ์ขั้นต่ำ เสี่ยงต่อการทำให้ระบบฐานข้อมูล/บริการหยุดทำงาน`
          };
        }
        return {
          title: `ขั้นที่ 2 (สถานะคลัสเตอร์): เครื่องเดี่ยว (ไม่ได้จัดกลุ่ม HA Cluster)`,
          detail: `หากเครื่องนี้หยุดทำงาน บริการที่พึ่งพาเครื่องนี้จะได้รับผลกระทบทันที`
        };
      }
      const conn = Array.isArray(step.connected_agents) && step.connected_agents.length > 0
        ? step.connected_agents.join(', ')
        : 'ไม่มีเครื่องอื่นได้รับผลกระทบต่อเนื่อง';
      return {
        title: `ขั้นที่ 3 (ผลกระทบตามสายโยงแผนผัง ER): ${conn}`,
        detail: Array.isArray(step.connected_agents) && step.connected_agents.length > 0
          ? `เครื่องที่เชื่อมโยงในแผนผังและอาจได้รับผลกระทบต่อเนื่อง ได้แก่ ${conn}`
          : `ปัญหาจำกัดอยู่เฉพาะเครื่องต้นตอ ยังไม่ลามไปยังเครื่องอื่นในแผนผัง`
      };
    }

    async function runAiAnalysis(websiteId) {
      const panelContent = document.getElementById('ai-panel-content');
      const modal = document.getElementById('ai-modal');
      const content = panelContent || document.getElementById('ai-modal-content');
      if (!panelContent) {
        modal.style.display = 'flex';
      }
      content.innerHTML = `
        <div class="ai-loading">
          <div class="spinner"></div>
          <p style="color: var(--text-muted); font-size: 15px;">กำลังวิเคราะห์ต้นตอและผลกระทบตามแผนผังระบบ...</p>
        </div>
      `;
      try {
        const response = await fetch(`/api/analyze?website_id=${encodeURIComponent(websiteId)}`);
        const result = await response.json();
        if (!response.ok) {
          content.innerHTML = `<div class="status-badge status-critical" style="padding: 12px; border-radius: 8px; width: 100%; display: block; text-align: center;">ไม่สามารถวิเคราะห์ได้: ${result.error || 'Unknown error'}</div>`;
          return;
        }

        const suspectedEl = document.getElementById('ai-card-suspected');
        if (suspectedEl && result.primary_agent) {
          suspectedEl.textContent = result.primary_agent;
        }

        let cascadingSection = '';
        if (Array.isArray(result.cascading_timeline) && result.cascading_timeline.length > 0) {
          const stepItems = result.cascading_timeline.map((step) => {
            const th = translateStepToThai(step);
            return `
              <div class="cascading-step" style="padding: 12px 14px;">
                <strong style="font-size: 16px; display: block; margin-bottom: 4px;">${escapeHtml(th.title)}</strong>
                <div class="muted" style="font-size: 14.5px;">${escapeHtml(th.detail)}</div>
              </div>
            `;
          }).join('');
          cascadingSection = `
            <div class="report-section">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:10px;">
                <h3 style="margin:0;">🔗 ลำดับผลกระทบตามแผนผัง ER</h3>
                <div class="confidence-container">
                  <span class="muted" style="font-size:14px;">ความมั่นใจในการวิเคราะห์:</span>
                  <div class="progress-bar">
                    <div class="progress-fill" style="width: ${Math.round((result.confidence || 0) * 100)}%;"></div>
                  </div>
                  <strong class="confidence-val">${Math.round((result.confidence || 0) * 100)}%</strong>
                </div>
              </div>
              <div class="cascading-timeline">${stepItems}</div>
            </div>
          `;
        }

        content.innerHTML = `
          <div class="ai-report" style="padding: 0;">
            ${cascadingSection}
            <details class="evidence-details">
              <summary>📜 ดูบรรทัด Log ที่ใช้เป็นหลักฐานวิเคราะห์ (${result.evidence ? result.evidence.length : 0} รายการ)</summary>
              <div class="evidence-list" style="margin-top: 12px;">
                <pre class="evidence-pre">${result.evidence && result.evidence.length ? result.evidence.map(e => escapeHtml(e)).join('\\n') : 'ไม่พบบรรทัดข้อผิดพลาดในรอบเวลานี้'}</pre>
              </div>
            </details>
          </div>
        `;
      } catch (err) {
        content.innerHTML = `<div class="status-badge status-critical" style="padding: 12px; border-radius: 8px; width: 100%; display: block; text-align: center;">เกิดข้อผิดพลาด: ${err.message || err}</div>`;
      }
    }

    function closeAiModal() {
      document.getElementById('ai-modal').style.display = 'none';
    }

    function escapeHtml(str) {
      if (!str) return '';
      return str.toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }
