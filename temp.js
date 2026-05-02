    /* ── State ────────────────────────────────────────── */
    const API = '';
    let allNodes = [], summaryData = null;
    let forecastChart = null, barChart = null, map = null;
    let markers = {}, markerColors = {}, activeNodeId = null;

    /* ── Color maps ───────────────────────────────────── */
    // User spec: Ev=mavi, Okul=mor, Cami=turuncu, Üniversite=yeşil
    const TYPE_COLOR = {
      house: '#58a6ff',   // mavi
      mosque: '#e8873a',   // turuncu
      school: '#a371f7',   // mor
      university: '#3fb950',   // yeşil
    };
    const TYPE_ICON = { house: '🏠', mosque: '🕌', school: '🏫', university: '🎓' };
    const TYPE_TR = { house: 'Ev', mosque: 'Cami', school: 'Okul', university: 'Üniversite' };

    /* ── Chart.js custom plugin: forecast zone ────────── */
    const forecastZonePlugin = {
      id: 'forecastZone',
      beforeDatasetsDraw(chart) {
        const splitIdx = chart.options.plugins?.forecastZone?.splitIdx;
        if (splitIdx == null) return;
        const { ctx, chartArea: { top, bottom, right }, scales: { x } } = chart;
        // Get pixel position via label value
        const label = chart.data.labels[splitIdx];
        const xStart = x.getPixelForValue(label);
        ctx.save();
        ctx.fillStyle = 'rgba(210,153,34,0.07)';
        ctx.fillRect(xStart, top, right - xStart, bottom - top);
        ctx.restore();
      },
      afterDatasetsDraw(chart) {
        const splitIdx = chart.options.plugins?.forecastZone?.splitIdx;
        if (splitIdx == null) return;
        const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
        const label = chart.data.labels[splitIdx];
        const xPos = x.getPixelForValue(label);
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(xPos, top);
        ctx.lineTo(xPos, bottom);
        ctx.strokeStyle = '#d29922cc';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#d29922dd';
        ctx.font = 'bold 9px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('▶ TAHMİN BAŞLANGICI', xPos + 5, top + 13);
        ctx.restore();
      },
    };
    Chart.register(forecastZonePlugin);

    /* ── Utility: consumption → color ────────────────── */
    function consumptionColor(kwh, nodes) {
      const sorted = nodes.map(n => n.current_kwh).sort((a, b) => a - b);
      const p33 = sorted[Math.floor(sorted.length * 0.33)] ?? sorted[0];
      const p66 = sorted[Math.floor(sorted.length * 0.66)] ?? sorted[sorted.length - 1];
      if (kwh <= p33) return '#3fb950';  // yeşil – düşük
      if (kwh <= p66) return '#d29922';  // sarı  – orta
      return '#f78166';                   // kırmızı – yüksek
    }

    /* ── Utility: trend analysis ──────────────────────── */
    function calcTrend(current, predictedMonthly) {
      if (!current || !predictedMonthly) return { emoji: '—', text: 'Veri yok', detail: '', color: 'var(--muted)' };
      const dailyPred = predictedMonthly / 30;
      const ratio = dailyPred / current;
      const pct = ((ratio - 1) * 100).toFixed(1);
      if (ratio > 1.08) return { emoji: '⚠️', text: 'Tüketim artıyor', detail: `+${pct}% artış bekleniyor`, color: 'var(--red)' };
      if (ratio < 0.92) return { emoji: '📉', text: 'Düşüş var', detail: `${pct}% düşüş bekleniyor`, color: 'var(--green)' };
      return { emoji: '✅', text: 'Normal seyir', detail: `${pct > 0 ? '+' : ''}${pct}% fark`, color: 'var(--green)' };
    }

    /* ── Utility: bill amount color ───────────────────── */
    function billColor(amount, maxAmount) {
      const r = amount / maxAmount;
      if (r > 0.66) return 'var(--red)';
      if (r > 0.33) return 'var(--orange)';
      return 'var(--green)';
    }

    /* ── Utility: number formatter ────────────────────── */
    function fmt(v, dec = 2) {
      return v.toLocaleString('tr-TR', { minimumFractionDigits: dec, maximumFractionDigits: dec });
    }

    /* ── Tab switching ────────────────────────────────── */
    function switchTab(name) {
      document.getElementById('tab-dashboard').style.display = name === 'dashboard' ? '' : 'none';
      document.getElementById('tab-billing').style.display = name === 'billing' ? '' : 'none';
      document.querySelectorAll('.tab-btn').forEach((b, i) =>
        b.classList.toggle('active', (i === 0) === (name === 'dashboard')));
      if (name === 'dashboard') setTimeout(() => map?.invalidateSize(), 50);
    }

    /* ── Invoice Modal Functionality ──────────────────── */
    function openInvoice(id) {
      const n = allNodes.find(x => x.id === id);
      if (!n) return;
      
      const content = `
        <div class="inv-title">${TYPE_ICON[n.type] || '📍'} ${n.name}</div>
        <div class="inv-loc">📍 Konum: ${n.lat.toFixed(4)}, ${n.lon.toFixed(4)}</div>
        
        <div class="inv-row">
          <span class="inv-label">Birim Fiyat:</span>
          <span class="inv-val">2.85 ₺ / kWh</span>
        </div>
        <div class="inv-row">
          <span class="inv-label">Toplam Tüketim:</span>
          <span class="inv-val">${n.current_kwh} kWh</span>
        </div>
        <div class="inv-row">
          <span class="inv-label">Güneş Enerjisi Üretimi:</span>
          <span class="inv-val" style="color:var(--green)">${n.current_solar_kwh} kWh</span>
        </div>
        <div class="inv-row">
          <span class="inv-label">Net Şebeke Çekimi:</span>
          <span class="inv-val">${n.net_current_kwh} kWh</span>
        </div>
        <div class="inv-row">
          <span class="inv-label">Aylık Tahmini Tüketim:</span>
          <span class="inv-val">${n.predicted_monthly_kwh} kWh</span>
        </div>
        
        <div class="inv-row inv-total">
          <span>Tahmini Fatura Tutarı:</span>
          <span>${fmt(n.bill_tl)} ₺</span>
        </div>
      `;
      document.getElementById('invoice-content').innerHTML = content;
      document.getElementById('invoice-modal').style.display = 'flex';
    }

    function closeInvoice() {
      document.getElementById('invoice-modal').style.display = 'none';
    }

    /* ── Marker icon (consumption-based color) ────────── */
    function makeIcon(color, active = false) {
      const s = active ? 38 : 30;
      return L.divIcon({
        html: `<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}" viewBox="0 0 30 30">
      <circle cx="15" cy="15" r="12" fill="${color}" fill-opacity=".18" stroke="${color}" stroke-width="2"/>
      <circle cx="15" cy="15" r="5.5" fill="${color}"/>
      ${active ? `<circle cx="15" cy="15" r="14" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="4 2" opacity=".75"/>` : ''}
    </svg>`,
        className: '', iconSize: [s, s], iconAnchor: [s / 2, s / 2],
      });
    }

    /* ── Popup builder ────────────────────────────────── */
    function buildPopup(n) {
      const trend = calcTrend(n.current_kwh, n.predicted_monthly_kwh);
      const surplus = n.current_solar_kwh > n.current_kwh;
      const netLabel = surplus
        ? `<span style="color:var(--green)">+${(n.current_solar_kwh - n.current_kwh).toFixed(2)} kWh fazla</span>`
        : `${n.net_current_kwh} kWh`;
      const mcolor = consumptionColor(n.current_kwh, allNodes);
      const levelText = mcolor === '#3fb950' ? '🟢 Düşük' : mcolor === '#d29922' ? '🟡 Orta' : '🔴 Yüksek';

      return `
    <div class="popup-body">
      <h4>
        ${TYPE_ICON[n.type] || '📍'} ${n.name}
        <span style="margin-left:auto;font-size:.72rem;color:${trend.color}">${trend.emoji} ${trend.text}</span>
      </h4>
      <table>
        <tr><td style="color:var(--muted)">Tip</td><td>${TYPE_TR[n.type] || n.type}</td></tr>
        <tr><td style="color:var(--muted)">Tüketim Seviyesi</td><td>${levelText}</td></tr>
        <tr class="popup-divider"><td colspan="2"><hr/></td></tr>
        <tr><td>⚡ Tüketim</td><td>${n.current_kwh} kWh</td></tr>
        <tr><td>☀️ Üretim</td><td style="color:var(--green)">${n.current_solar_kwh} kWh</td></tr>
        <tr><td>🔌 Net Şebeke</td><td>${netLabel}</td></tr>
        <tr class="popup-divider"><td colspan="2"><hr/></td></tr>
        <tr><td>🤖 ML Tahmin (yarın)</td><td style="color:var(--gold)">${n.predicted_next_day_kwh} kWh</td></tr>
        <tr><td>📅 Aylık Tahmin</td><td>${n.predicted_monthly_kwh} kWh</td></tr>
        <tr><td>💳 Günlük Ödeme</td><td style="color:var(--gold)">${fmt(n.daily_bill_tl)} ₺</td></tr>
        <tr><td>💰 Tahmini Fatura</td><td style="color:var(--gold);font-weight:700">${fmt(n.bill_tl)} ₺</td></tr>
      </table>
      <div class="popup-btn" onclick="selectNodeAndClose('${n.id}')">📈 Tahmin Grafiğini Gör</div>
    </div>`;
    }

    /* ── Map init ─────────────────────────────────────── */
    function initMap(nodes) {
      map = L.map('map', { zoomControl: true });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '© OpenStreetMap © CARTO', maxZoom: 20,
      }).addTo(map);

      // Consumption color legend
      const legend = L.control({ position: 'bottomright' });
      legend.onAdd = () => {
        const d = L.DomUtil.create('div');
        d.innerHTML = `
      <div style="background:#1f2937;border:1px solid #30363d;border-radius:8px;padding:9px 13px;font-size:.72rem;color:#e6edf3;line-height:1.9">
        <div style="color:#8b949e;font-weight:700;margin-bottom:3px;font-size:.65rem;letter-spacing:.5px">TÜKETİM SEVİYESİ</div>
        <div><span style="color:#3fb950;font-size:1rem">●</span> Düşük</div>
        <div><span style="color:#d29922;font-size:1rem">●</span> Orta</div>
        <div><span style="color:#f78166;font-size:1rem">●</span> Yüksek</div>
      </div>`;
        return d;
      };
      legend.addTo(map);

      const bounds = [];
      nodes.forEach(n => {
        const color = consumptionColor(n.current_kwh, nodes);
        markerColors[n.id] = color;
        const m = L.marker([n.lat, n.lon], { icon: makeIcon(color, false) })
          .addTo(map)
          .bindPopup(buildPopup(n), { maxWidth: 290 });
        m.on('click', () => selectNode(n.id));
        markers[n.id] = m;
        bounds.push([n.lat, n.lon]);
      });
      map.fitBounds(bounds, { padding: [40, 40] });
    }

    /* ── Select node ──────────────────────────────────── */
    window.selectNodeAndClose = id => { selectNode(id); markers[id]?.closePopup(); };
    window.selectNodeAndGoMap = id => {
      switchTab('dashboard');
      setTimeout(() => { selectNode(id); markers[id]?.openPopup(); }, 80);
    };

    async function selectNode(id) {
      if (activeNodeId && markers[activeNodeId]) {
        markers[activeNodeId].setIcon(makeIcon(markerColors[activeNodeId] || '#8b949e', false));
      }
      activeNodeId = id;
      const node = allNodes.find(n => n.id === id);
      if (!node) return;

      markers[id].setIcon(makeIcon(markerColors[id] || '#8b949e', true));
      map.panTo([node.lat, node.lon]);

      document.querySelectorAll('.btable tbody tr').forEach(r => r.classList.remove('selected'));
      document.getElementById(`brow-${id}`)?.classList.add('selected');

      document.getElementById('chart-node-label').textContent = node.name;
      const data = await fetch(`${API}/predict/${id}?days=30`).then(r => r.json());
      renderForecastChart(data, node);
    }

    /* ── Load all data ────────────────────────────────── */
    async function loadAll() {
      [allNodes, summaryData] = await Promise.all([
        fetch(`${API}/nodes`).then(r => r.json()),
        fetch(`${API}/summary`).then(r => r.json()),
      ]);

      const s = summaryData;
      const trend = calcTrend(s.total_current_kwh, s.total_predicted_monthly_kwh);
      const highest = allNodes.reduce((mx, n) => n.current_kwh > mx.current_kwh ? n : mx, allNodes[0]);
      const dailyAvgPred = (s.total_predicted_monthly_kwh / 30).toFixed(1);

      // Dashboard cards
      document.getElementById('m-total').textContent = s.total_current_kwh.toFixed(1);
      document.getElementById('m-solar').textContent = s.total_solar_kwh.toFixed(1);
      document.getElementById('m-net').textContent = s.total_net_kwh.toFixed(1);
      document.getElementById('m-pred').textContent = s.total_predicted_monthly_kwh.toFixed(0);
      document.getElementById('m-bill').textContent = s.total_bill_tl.toLocaleString('tr-TR', { maximumFractionDigits: 0 }) + ' ₺';
      document.getElementById('m-highest-val').textContent = highest.current_kwh.toFixed(1) + ' kWh';
      document.getElementById('m-highest-name').textContent = highest.name + ' (' + TYPE_TR[highest.type] + ')';
      document.getElementById('m-trend-emoji').textContent = trend.emoji;
      document.getElementById('m-trend-text').textContent = trend.text;
      document.getElementById('m-trend-text').style.color = trend.color;
      document.getElementById('m-trend-detail').textContent = `Günlük ort. tahmin: ${dailyAvgPred} kWh`;
      document.getElementById('last-update').textContent = new Date().toLocaleTimeString('tr-TR');

      // Billing tab cards
      document.getElementById('bs-total').textContent = s.total_current_kwh.toFixed(1);
      document.getElementById('bs-solar').textContent = s.total_solar_kwh.toFixed(1);
      document.getElementById('bs-net').textContent = s.total_net_kwh.toFixed(1);
      document.getElementById('bs-bill').textContent = s.total_bill_tl.toLocaleString('tr-TR', { maximumFractionDigits: 0 }) + ' ₺';

      initMap(allNodes);
      renderBillingTable(allNodes);
      renderBarChart(allNodes);
      if (allNodes.length) selectNode(allNodes[0].id);
      document.getElementById('loading').style.display = 'none';
    }

    /* ── Billing Table (sorted high→low, color-coded) ── */
    function renderBillingTable(nodes) {
      const sorted = [...nodes].sort((a, b) => b.bill_tl - a.bill_tl);
      const maxBill = sorted[0].bill_tl;
      const maxCons = Math.max(...nodes.map(n => n.current_kwh));

      const rows = sorted.map((n, i) => {
        const bc = billColor(n.bill_tl, maxBill);
        const trend = calcTrend(n.current_kwh, n.predicted_monthly_kwh);
        const tc = TYPE_COLOR[n.type] || '#8b949e';
        const cColor = consumptionColor(n.current_kwh, nodes);
        const cRatio = n.current_kwh / maxCons;
        const sRatio = n.current_solar_kwh / n.current_kwh;

        let sClass, sText;
        if (sRatio >= 1.0) { sClass = 's-ok'; sText = '✅ Fazla Üretim'; }
        else if (sRatio >= 0.5) { sClass = 's-warn'; sText = '🔆 Kısmi Solar'; }
        else { sClass = 's-over'; sText = '🔌 Şebekeden'; }

        return `
      <tr id="brow-${n.id}" onclick="openInvoice('${n.id}')">
        <td style="color:var(--muted);font-size:.72rem">${i + 1}</td>
        <td><span style="font-weight:600">${n.name}</span></td>
        <td>
          <span class="type-pill" style="background:${tc}18;color:${tc};border:1px solid ${tc}44">
            <span class="type-dot" style="background:${tc}"></span>${TYPE_TR[n.type] || n.type}
          </span>
        </td>
        <td class="num">
          ${n.current_kwh}
          <div class="bar-mini"><div class="bar-mini-fill" style="width:${cRatio * 100}%;background:${cColor}"></div></div>
        </td>
        <td class="num" style="color:var(--green)">${n.current_solar_kwh}</td>
        <td class="num">${n.net_current_kwh}</td>
        <td class="num">${n.predicted_monthly_kwh}</td>
        <td class="num" style="font-weight:700;color:${bc}">${fmt(n.bill_tl)} ₺</td>
        <td style="text-align:center"><span class="status-badge ${sClass}">${sText}</span></td>
        <td style="text-align:center;font-size:.75rem;color:${trend.color};white-space:nowrap">${trend.emoji} ${trend.text}</td>
      </tr>`;
      });
      document.getElementById('bill-tbody').innerHTML = rows.join('');
    }

    /* ── Forecast Chart (annotation + shaded zone) ────── */
    function renderForecastChart(data, node) {
      const hist30 = data.history.slice(-30);
      const histLabels = hist30.map(d => d.date.slice(5));
      const histVals = hist30.map(d => d.consumption_kwh);
      const predLabels = data.predictions.map(d => d.date.slice(5));
      const predVals = data.predictions.map(d => d.predicted_kwh);

      const labels = [...histLabels, ...predLabels];
      const histFull = [...histVals, ...Array(predLabels.length).fill(null)];
      const predFull = [...Array(histLabels.length - 1).fill(null), histVals.at(-1), ...predVals];

      const c = TYPE_COLOR[node.type] || '#58a6ff';
      if (forecastChart) forecastChart.destroy();
      forecastChart = new Chart(document.getElementById('forecast-chart'), {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Geçmiş Tüketim',
              data: histFull,
              borderColor: c,
              backgroundColor: c + '1a',
              fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2,
            },
            {
              label: 'ML Tahmini',
              data: predFull,
              borderColor: '#d29922',
              borderDash: [6, 4],
              backgroundColor: 'transparent',
              fill: false, tension: 0.4, pointRadius: 0, borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { color: '#8b949e', font: { size: 11 }, boxWidth: 12 } },
            tooltip: {
              backgroundColor: '#1f2937', titleColor: '#e6edf3', bodyColor: '#8b949e',
              callbacks: {
                label: item => ` ${item.dataset.label}: ${item.raw != null ? item.raw.toFixed(2) : '—'} kWh`,
              },
            },
            // Vertical annotation line + shaded prediction zone
            forecastZone: { splitIdx: histLabels.length - 1 },
          },
          scales: {
            x: {
              ticks: { 
                color: '#8b949e', 
                font: { size: 9 }, 
                maxRotation: 0,
                autoSkip: false,
                callback: function(val, index) {
                  // Her 3 saatte bir etiket göster
                  return index % 3 === 0 ? this.getLabelForValue(val) : '';
                }
              },
              grid: { color: '#30363d' },
            },
            y: {
              ticks: { color: '#8b949e', font: { size: 10 } },
              grid: { color: '#30363d' },
              title: { display: true, text: 'kWh', color: '#8b949e', font: { size: 10 } },
            },
          },
        },
      });
    }

    /* ── Bar Chart (type colors + hover tooltip) ──────── */
    function renderBarChart(nodes) {
      const sorted = [...nodes].sort((a, b) => b.current_kwh - a.current_kwh);
      if (barChart) barChart.destroy();
      barChart = new Chart(document.getElementById('bar-chart'), {
        type: 'bar',
        data: {
          labels: sorted.map(n => n.name),
          datasets: [
            {
              label: 'Tüketim (kWh)',
              data: sorted.map(n => n.current_kwh),
              backgroundColor: sorted.map(n => (TYPE_COLOR[n.type] || '#8b949e') + 'cc'),
              borderColor: sorted.map(n => TYPE_COLOR[n.type] || '#8b949e'),
              borderWidth: 1, borderRadius: 5, borderSkipped: false,
            },
            {
              label: 'Üretim (kWh)',
              data: sorted.map(n => n.current_solar_kwh),
              backgroundColor: '#3fb95055',
              borderColor: '#3fb950',
              borderWidth: 1, borderRadius: 5, borderSkipped: false,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { color: '#8b949e', font: { size: 11 }, boxWidth: 12 } },
            tooltip: {
              backgroundColor: '#1f2937', titleColor: '#e6edf3', bodyColor: '#8b949e',
              callbacks: {
                title: items => items[0]?.label ?? '',
                label: item => ` ${item.dataset.label}: ${item.raw?.toFixed(2)} kWh`,
              },
            },
          },
          scales: {
            x: {
              ticks: { color: '#8b949e', font: { size: 9 }, maxRotation: 45 },
              grid: { display: false },
            },
            y: {
              ticks: { color: '#8b949e', font: { size: 10 } },
              grid: { color: '#30363d' },
              title: { display: true, text: 'kWh', color: '#8b949e', font: { size: 10 } },
            },
          },
        },
      });
    }

    /* ── Boot ─────────────────────────────────────────── */
    loadAll().catch(err => {
      document.getElementById('loading').innerHTML = `
    <div style="color:#f78166;text-align:center">
      <div style="font-size:2.2rem">⚠️</div>
      <p style="margin-top:12px;color:#e6edf3">Backend bağlantısı kurulamadı.</p>
      <code style="font-size:.72rem;color:#8b949e">${err.message}</code>
    </div>`;
    });
