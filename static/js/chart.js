/* Seoul APT 59m² Index — Chart Module
 * TradingView Lightweight Charts v4
 */

const API = {
  hourly:         '/api/hourly?limit=720',
  daily:          '/api/daily?limit=365',
  complexes:      '/api/complexes',
  status:         '/api/status',
  runNow:         '/api/run',
  districtHourly: '/api/district/hourly?limit=168',
};

const DISTRICT_COLORS = {
  '강남구': '#f85149',
  '서초구': '#ff8c00',
  '용산구': '#d29922',
  '송파구': '#3fb950',
  '마포구': '#58a6ff',
  '성동구': '#bc8cff',
  '동작구': '#f0883e',
  '강동구': '#39d353',
};

let chart, avgSeries, medSeries;
let districtChart, districtSeries = {};
let currentMode   = 'hourly';  // 'hourly' | 'daily'
let currentMetric = 'avg';     // 'avg' | 'median'
let currentFilter = '전체';    // 단지 필터: '전체' | district name
let rawData = { hourly: [], daily: [] };

const FILTER_DISTRICTS = ['전체', ...Object.keys(DISTRICT_COLORS)];

// ── Lightweight Charts init ──────────────────────────────────────────────

function initChart() {
  const container = document.getElementById('chart-container');
  chart = LightweightCharts.createChart(container, {
    layout: {
      background: { color: '#0d1117' },
      textColor: '#e6edf3',
    },
    grid: {
      vertLines: { color: '#1c2128' },
      horzLines: { color: '#1c2128' },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#30363d' },
    timeScale: {
      borderColor: '#30363d',
      timeVisible: true,
      secondsVisible: false,
    },
    width:  container.clientWidth,
    height: container.clientHeight,
  });

  avgSeries = chart.addCandlestickSeries({
    upColor:          '#f85149',
    downColor:        '#58a6ff',
    borderUpColor:    '#f85149',
    borderDownColor:  '#58a6ff',
    wickUpColor:      '#f85149',
    wickDownColor:    '#58a6ff',
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
  });

  medSeries = chart.addCandlestickSeries({
    upColor:          '#3fb950',
    downColor:        '#d29922',
    borderUpColor:    '#3fb950',
    borderDownColor:  '#d29922',
    wickUpColor:      '#3fb950',
    wickDownColor:    '#d29922',
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    visible: false,
  });

  new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
  }).observe(container);

  chart.subscribeCrosshairMove(p => {
    if (!p.seriesData) return;
    const active = currentMetric === 'avg' ? avgSeries : medSeries;
    const d = p.seriesData.get(active);
    if (d) updatePriceDisplay(d.close, null);
  });
}

function initDistrictChart() {
  const container = document.getElementById('district-chart-container');
  districtChart = LightweightCharts.createChart(container, {
    layout: {
      background: { color: '#0d1117' },
      textColor: '#e6edf3',
    },
    grid: {
      vertLines: { color: '#1c2128' },
      horzLines: { color: '#1c2128' },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#30363d' },
    timeScale: {
      borderColor: '#30363d',
      timeVisible: true,
      secondsVisible: false,
    },
    width:  container.clientWidth,
    height: container.clientHeight,
  });

  for (const [name, color] of Object.entries(DISTRICT_COLORS)) {
    districtSeries[name] = districtChart.addLineSeries({
      color,
      lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      title: name,
    });
  }

  new ResizeObserver(() => {
    districtChart.applyOptions({ width: container.clientWidth });
  }).observe(container);

  // 범례 — 데이터 도착 후 updateDistrictLegend 가 채움
  const legend = document.getElementById('district-legend');
  for (const [name, color] of Object.entries(DISTRICT_COLORS)) {
    const item = document.createElement('div');
    item.className = 'district-legend-item';
    item.dataset.district = name;
    item.innerHTML = `
      <span class="district-legend-dot" style="background:${color}"></span>
      <span class="district-legend-name">${name}</span>
      <span class="district-legend-meta"></span>
    `;
    legend.appendChild(item);
  }
}

function initComplexFilter() {
  const container = document.getElementById('complex-filter');
  for (const d of FILTER_DISTRICTS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-filter' + (d === currentFilter ? ' active' : '');
    btn.dataset.district = d;
    btn.textContent = d;
    btn.onclick = () => setComplexFilter(d);
    container.appendChild(btn);
  }
}

function updateDistrictLegend(complexes) {
  const stats = {};
  for (const cx of complexes) {
    const d = cx.district;
    if (!stats[d]) stats[d] = { count: 0, households: 0 };
    stats[d].count += 1;
    stats[d].households += (cx.household_cnt || 0);
  }
  document.querySelectorAll('.district-legend-item').forEach(item => {
    const name = item.dataset.district;
    const s = stats[name];
    const meta = item.querySelector('.district-legend-meta');
    meta.textContent = s
      ? ` (${s.count}단지·${s.households.toLocaleString()}세대)`
      : ' (0단지)';
  });
}

function applyComplexFilter() {
  const tbody = document.getElementById('complex-tbody');
  let visible = 0;
  for (const tr of tbody.querySelectorAll('tr[data-district]')) {
    const show = currentFilter === '전체' || tr.dataset.district === currentFilter;
    tr.style.display = show ? '' : 'none';
    if (show) visible++;
  }
  const label = currentFilter === '전체' ? `${visible}개` : `${currentFilter} ${visible}개`;
  document.getElementById('complex-count').textContent = label;
}

function setComplexFilter(district) {
  currentFilter = district;
  document.querySelectorAll('.btn-filter').forEach(b =>
    b.classList.toggle('active', b.dataset.district === district));
  applyComplexFilter();
}

// ── Data conversion ─────────────────────────────────────────────────────

function toTimestamp(s) {
  if (!s) return 0;
  // DB stores naive KST strings. Append 'Z' so JS Date treats the value
  // as UTC — Lightweight Charts then displays the stored KST number as-is.
  const iso = s.length === 10 ? s + 'T00:00:00Z' : s.replace(' ', 'T') + 'Z';
  return Math.floor(new Date(iso).getTime() / 1000);
}

function toCandles(rows, prefix) {
  return rows
    .filter(r => r[`${prefix}_open`] !== null)
    .map(r => ({
      time:  toTimestamp(r.ts || r.date),
      open:  r[`${prefix}_open`],
      high:  r[`${prefix}_high`],
      low:   r[`${prefix}_low`],
      close: r[`${prefix}_close`],
    }));
}

// ── Render ───────────────────────────────────────────────────────────────

function renderChart() {
  const data = currentMode === 'hourly' ? rawData.hourly : rawData.daily;
  const avgCandles = toCandles(data, 'avg');
  const medCandles = toCandles(data, 'median');

  avgSeries.setData(avgCandles);
  medSeries.setData(medCandles);

  avgSeries.applyOptions({ visible: currentMetric === 'avg' });
  medSeries.applyOptions({ visible: currentMetric === 'median' });

  chart.timeScale().fitContent();

  const latest = avgCandles[avgCandles.length - 1];
  if (latest) {
    const prev = avgCandles[avgCandles.length - 2];
    updatePriceDisplay(latest.close, prev ? latest.close - prev.close : null);
  }
}

function updatePriceDisplay(price, change) {
  const el = document.getElementById('price-display');
  const chEl = document.getElementById('price-change');
  el.textContent = price ? `${price.toFixed(2)}억` : '-';
  el.className = 'price-display' + (change > 0 ? ' up' : change < 0 ? ' down' : '');
  if (change !== null) {
    const sign = change > 0 ? '+' : '';
    chEl.textContent = `${sign}${change.toFixed(2)}억`;
  }
}

// ── Fetch helpers ────────────────────────────────────────────────────────

async function loadData() {
  const [h, d] = await Promise.all([
    fetch(API.hourly).then(r => r.json()),
    fetch(API.daily).then(r => r.json()),
  ]);
  rawData.hourly = h;
  rawData.daily  = d;
  renderChart();
}

async function loadComplexes() {
  const data = await fetch(API.complexes).then(r => r.json());
  const tbody = document.getElementById('complex-tbody');
  tbody.innerHTML = '';
  for (const cx of data) {
    const tr = document.createElement('tr');
    tr.dataset.district = cx.district;
    const price = cx.latest_price_eok != null
      ? `${cx.latest_price_eok.toFixed(2)}억`
      : '-';
    tr.innerHTML = `
      <td class="rank">${cx.rank ?? '-'}</td>
      <td>${cx.complex_name}</td>
      <td>${cx.district}</td>
      <td class="rank">${cx.household_cnt?.toLocaleString()}</td>
      <td class="price${cx.latest_price_eok == null ? ' na' : ''}">${price}</td>
    `;
    tbody.appendChild(tr);
  }
  updateDistrictLegend(data);
  applyComplexFilter();
}

async function loadStatus() {
  const s = await fetch(API.status).then(r => r.json());
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('last-update');
  dot.className = 'status-dot' + (s.scheduler_running ? ' live' : '');
  if (s.last_run) {
    const d = new Date(s.last_run);
    txt.textContent = `마지막 수집: ${d.toLocaleString('ko-KR')}`;
  }
}

async function loadDistrictChart() {
  const data = await fetch(API.districtHourly).then(r => r.json());

  // Lightweight Charts requires data sorted by time, ascending, no duplicates
  for (const [district, series] of Object.entries(districtSeries)) {
    const points = data[district] || [];
    const seen = new Set();
    const lineData = points
      .map(p => ({ time: toTimestamp(p.ts), value: p.avg }))
      .filter(p => p.time > 0 && p.value != null)
      .filter(p => { if (seen.has(p.time)) return false; seen.add(p.time); return true; })
      .sort((a, b) => a.time - b.time);
    series.setData(lineData);
  }
  // 데이터가 있는 첫 시리즈를 기준으로 fitContent
  const anyHasData = Object.values(data).some(arr => Array.isArray(arr) && arr.length > 0);
  if (anyHasData) {
    districtChart.timeScale().fitContent();
  }
}

// ── Event handlers ───────────────────────────────────────────────────────

function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.btn-mode').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === mode));
  renderChart();
}

function setMetric(metric) {
  currentMetric = metric;
  document.querySelectorAll('.btn-metric').forEach(b =>
    b.classList.toggle('active', b.dataset.metric === metric));
  renderChart();
}

async function runNow() {
  const btn = document.getElementById('btn-run');
  btn.disabled = true;
  btn.textContent = '수집 중...';
  await fetch(API.runNow, { method: 'POST' });

  // 파이프라인이 시작될 때까지 잠깐 대기 후 폴링
  await new Promise(r => setTimeout(r, 3000));

  let elapsed = 0;
  const poll = setInterval(async () => {
    try {
      elapsed += 5;
      const s = await fetch(API.status).then(r => r.json());
      btn.textContent = `수집 중... (${elapsed}s)`;
      if (!s.is_running) {
        clearInterval(poll);
        await Promise.all([loadData(), loadComplexes(), loadStatus(), loadDistrictChart()]);
        btn.disabled = false;
        btn.textContent = '지금 수집';
      }
    } catch (_) { /* 일시적 네트워크 오류 무시 */ }
  }, 5000);
}

// ── Init ─────────────────────────────────────────────────────────────────

function showError(msg) {
  const box = document.getElementById('js-error');
  if (!box) { console.error(msg); return; }
  box.style.display = 'block';
  box.textContent = (box.textContent ? box.textContent + ' | ' : '') + msg;
}

async function safe(label, fn) {
  try { await fn(); }
  catch (e) {
    console.error(label, e);
    showError(`${label}: ${e.message}`);
  }
}

async function init() {
  if (typeof LightweightCharts === 'undefined') {
    showError('LightweightCharts 라이브러리 로드 실패 — /static/js/lightweight-charts.standalone.production.js 확인 필요');
    return;
  }
  await safe('initChart',         async () => initChart());
  await safe('initDistrictChart', async () => initDistrictChart());
  await safe('initComplexFilter', async () => initComplexFilter());
  await Promise.all([
    safe('loadData',          loadData),
    safe('loadComplexes',     loadComplexes),
    safe('loadStatus',        loadStatus),
    safe('loadDistrictChart', loadDistrictChart),
  ]);

  // 자동 갱신 (60초)
  setInterval(() => {
    safe('loadData',          loadData);
    safe('loadStatus',        loadStatus);
    safe('loadDistrictChart', loadDistrictChart);
  }, 60_000);
}

document.addEventListener('DOMContentLoaded', init);
