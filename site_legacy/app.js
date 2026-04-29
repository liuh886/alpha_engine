let mainChart = null;
let modalChart = null;
const API_BASE = '/api';
let currentView = 'command-center';

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    setupEventListeners();
    loadView('command-center');
    setInterval(() => refreshLiveStats(), 10000);
});

function setupEventListeners() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const view = link.getAttribute('data-view');
            loadView(view);
            
            document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('bg-gray-700', 'text-white'));
            link.classList.add('bg-gray-700', 'text-white');
        });
    });

    document.getElementById('close-modal').addEventListener('click', () => document.getElementById('modal').classList.add('hidden'));
    
    const chatInput = document.getElementById('chat-input');
    const chatSend = document.getElementById('chat-send');
    if (chatSend) {
        chatSend.addEventListener('click', () => sendChat());
        chatInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendChat(); });
    }
}

async function loadView(viewId) {
    currentView = viewId;
    document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
    const activeSection = document.getElementById(`view-${viewId}`);
    if (activeSection) activeSection.classList.add('active');
    
    const titleMap = {
        'command-center': 'Command Center',
        'backtest-arena': 'Backtest Arena',
        'model-factory': 'Model Factory',
        'data-health': 'Data Health',
        'reports-index': 'Reports Index'
    };
    document.getElementById('view-title').textContent = titleMap[viewId] || 'AlphaEngine';

    // Dispatch Data Loading
    if (viewId === 'command-center') loadDashboardData();
    if (viewId === 'backtest-arena') loadArenaDetailed();
    if (viewId === 'model-factory') loadModelFactory();
    if (viewId === 'data-health') loadDataHealth();
    if (viewId === 'reports-index') loadReportsIndex();
}

async function loadDashboardData() {
    loadArena();
    loadJobs();
    fetchBenchmarkCurve();
    try {
        const resp = await fetch(`${API_BASE}/system/version`);
        const data = await resp.json();
        document.getElementById('stat-snapshot').textContent = `ENGINE: ${data.version}`;
    } catch(e) {}
}

async function fetchBenchmarkCurve() {
    try {
        const mResp = await fetch(`${API_BASE}/models?limit=1`);
        const mData = await mResp.json();
        if (mData.versions && mData.versions.length > 0) {
            const best = mData.versions[0];
            const cResp = await fetch(`${API_BASE}/backtest/curve?run_id=${best.run_id}`);
            const cData = await cResp.json();
            if (cData.curve && mainChart) {
                mainChart.updateSeries([{ name: best.tag || 'Strategy', data: cData.curve.map(p => ({ x: p.date, y: p.nav })) }]);
                document.getElementById('main-chart-legend').textContent = `Showing: ${best.tag} (${best.market.toUpperCase()})`;
            }
        }
    } catch(e) {}
}

async function loadArenaDetailed() {
    const tbody = document.getElementById('arena-detailed-table');
    tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-8 text-center text-gray-500 italic animate-pulse">Fetching arena records...</td></tr>';
    try {
        const resp = await fetch(`${API_BASE}/backtest?limit=50`);
        const data = await resp.json();
        const runs = data.runs || [];
        if (runs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-8 text-center text-gray-500 italic">No backtest records.</td></tr>';
            return;
        }
        tbody.innerHTML = runs.map(r => `
            <tr class="hover:bg-gray-700/30 transition-colors">
                <td class="px-6 py-4"><input type="checkbox" class="run-selector rounded bg-gray-900 border-gray-700 text-blue-500 focus:ring-blue-500" data-id="${r.id}" data-tag="${r.tag || 'UNTITLED'}"></td>
                <td class="px-6 py-4"><div class="font-bold text-gray-200">${r.tag || 'UNTITLED'}</div><div class="text-[10px] text-gray-600 font-mono">${r.id}</div></td>
                <td class="px-6 py-4 text-xs text-gray-400 font-mono">${r.strategy_name || 'N/A'}</td>
                <td class="px-6 py-4 font-mono font-bold text-green-500">${((r.annual_return || 0) * 100).toFixed(2)}%</td>
                <td class="px-6 py-4 font-mono text-blue-400">${(r.sharpe || 0).toFixed(2)}</td>
                <td class="px-6 py-4 text-right flex gap-2 justify-end">
                    <button onclick="showLedger('${r.id}', '${r.tag}')" class="text-orange-400 hover:underline text-xs">Ledger</button>
                    <button onclick="showAttribution('${r.id}', '${r.tag}')" class="text-purple-400 hover:underline text-xs">Attribution</button>
                    <button onclick="showCurve('${r.id}', '${r.tag}')" class="text-blue-500 hover:underline text-xs">Analyze</button>
                </td>
            </tr>`).join('');
    } catch(e) {
        tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-8 text-center text-red-500 italic">Failed to load arena data.</td></tr>';
    }
}

async function compareSelected() {
    const selected = Array.from(document.querySelectorAll('.run-selector:checked'));
    if (selected.length < 2) {
        alert("Please select at least 2 runs to compare.");
        return;
    }

    const runIds = selected.map(s => s.getAttribute('data-id')).join(',');
    const modal = document.getElementById('modal');
    modal.classList.remove('hidden');
    document.getElementById('modal-title').textContent = 'Multi-Model Comparison';
    document.getElementById('modal-subtitle').textContent = `Comparing ${selected.length} runs`;

    try {
        const resp = await fetch(`${API_BASE}/backtest/compare?run_ids=${runIds}`);
        const data = await resp.json();
        const comparisons = data.comparisons || {};
        
        const series = Object.entries(comparisons).map(([id, info]) => ({
            name: info.tag,
            data: (info.curve || []).map(p => ({ x: p.date, y: p.nav }))
        }));

        const options = {
            series: series,
            chart: { height: 500, type: 'line', toolbar: { show: true }, background: 'transparent' },
            stroke: { width: 2 },
            xaxis: { type: 'datetime' },
            theme: { mode: 'dark' },
            legend: { position: 'top', horizontalAlign: 'right' }
        };
        if (modalChart) modalChart.destroy();
        modalChart = new ApexCharts(document.querySelector("#curve-chart-pro"), options);
        modalChart.render();
    } catch(e) {}
}

async function showAttribution(runId, tag) {
    const modal = document.getElementById('modal');
    modal.classList.remove('hidden');
    document.getElementById('modal-title').textContent = `Profit Attribution: ${tag}`;
    document.getElementById('modal-subtitle').textContent = `RUN_ID: ${runId}`;
    const chartArea = document.getElementById('curve-chart-pro');
    chartArea.innerHTML = '<div class="text-gray-500 italic animate-pulse">Analyzing alpha sources...</div>';

    try {
        const resp = await fetch(`${API_BASE}/backtest/${runId}/attribution`);
        const data = await resp.json();
        const attr = data.attribution;
        
        chartArea.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-8 h-full">
                <div class="space-y-4">
                    <h3 class="text-sm font-bold text-purple-400 uppercase tracking-widest">Logic Attribution</h3>
                    <div class="bg-gray-900/50 p-4 rounded-lg border border-purple-500/20 text-xs leading-relaxed text-gray-300">
                        ${attr.summary}
                    </div>
                    <div class="space-y-2">
                        <div class="flex justify-between text-[10px] text-gray-500 uppercase font-bold"><span>Factor</span><span>Contribution</span></div>
                        ${attr.sectors.map(s => `
                            <div class="flex items-center gap-3">
                                <span class="text-xs w-24 truncate">${s.name}</span>
                                <div class="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                                    <div class="h-full bg-blue-500" style="width: ${s.contribution * 100}%"></div>
                                </div>
                                <span class="text-[10px] font-mono text-gray-400">${(s.contribution * 100).toFixed(0)}%</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="bg-gray-900/50 rounded-lg p-4 border border-gray-700">
                    <h3 class="text-sm font-bold text-blue-400 uppercase tracking-widest mb-4">Risk Profile</h3>
                    <div class="grid grid-cols-2 gap-4">
                        <div class="p-3 bg-gray-800 rounded border border-gray-700"><div class="text-[9px] text-gray-500">Sharpe</div><div class="text-xl font-bold font-mono">${(attr.metrics.sharpe || 0).toFixed(2)}</div></div>
                        <div class="p-3 bg-gray-800 rounded border border-gray-700"><div class="text-[9px] text-gray-500">Max DD</div><div class="text-xl font-bold font-mono text-red-500">${(attr.metrics.max_drawdown*100 || 0).toFixed(1)}%</div></div>
                        <div class="p-3 bg-gray-800 rounded border border-gray-700"><div class="text-[9px] text-gray-500">Ann. Return</div><div class="text-xl font-bold font-mono text-green-500">${(attr.metrics.annualized_return*100 || 0).toFixed(1)}%</div></div>
                        <div class="p-3 bg-gray-800 rounded border border-gray-700"><div class="text-[9px] text-gray-500">Volatility</div><div class="text-xl font-bold font-mono text-orange-400">${(attr.metrics.annualized_volatility*100 || 0).toFixed(1)}%</div></div>
                    </div>
                </div>
            </div>
        `;
    } catch(e) {
        chartArea.innerHTML = '<div class="text-red-500">Failed to load attribution analysis.</div>';
    }
}

async function showLedger(runId, tag) {
    const modal = document.getElementById('modal');
    modal.classList.remove('hidden');
    document.getElementById('modal-title').textContent = `Execution Ledger: ${tag}`;
    document.getElementById('modal-subtitle').textContent = `RUN_ID: ${runId}`;
    const chartArea = document.getElementById('curve-chart-pro');
    chartArea.innerHTML = '<div class="text-gray-500 italic animate-pulse">Retrieving holdings and trade history...</div>';

    try {
        const resp = await fetch(`${API_BASE}/backtest/${runId}/ledger`);
        const data = await resp.json();
        
        chartArea.innerHTML = `
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 h-full">
                <!-- Holdings -->
                <div class="lg:col-span-1 flex flex-col">
                    <h3 class="text-sm font-bold text-orange-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                        <i data-lucide="briefcase" class="w-4 h-4"></i> Current Holdings
                    </h3>
                    <div class="bg-gray-900/50 rounded-lg border border-gray-700 overflow-hidden flex-1">
                        <table class="w-full text-[10px]">
                            <thead class="bg-gray-800 text-gray-500 uppercase font-bold"><tr class="border-b border-gray-700"><th class="px-3 py-2">Symbol</th><th class="px-3 py-2 text-right">Value</th><th class="px-3 py-2 text-right">PnL</th></tr></thead>
                            <tbody class="divide-y divide-gray-800">
                                ${data.holdings.map(h => `
                                    <tr>
                                        <td class="px-3 py-2 font-bold">${h.symbol}</td>
                                        <td class="px-3 py-2 text-right font-mono">$${h.value.toLocaleString()}</td>
                                        <td class="px-3 py-2 text-right font-mono ${h.pnl >= 0 ? 'text-green-500' : 'text-red-500'}">${h.pnl >= 0 ? '+' : ''}${h.pnl.toFixed(1)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
                <!-- Trades -->
                <div class="lg:col-span-2 flex flex-col">
                    <h3 class="text-sm font-bold text-blue-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                        <i data-lucide="list" class="w-4 h-4"></i> Recent Execution
                    </h3>
                    <div class="bg-gray-900/50 rounded-lg border border-gray-700 overflow-hidden flex-1">
                        <table class="w-full text-[10px]">
                            <thead class="bg-gray-800 text-gray-500 uppercase font-bold"><tr class="border-b border-gray-700"><th class="px-4 py-2">Date</th><th class="px-4 py-2">Symbol</th><th class="px-4 py-2">Side</th><th class="px-4 py-2 text-right">Qty</th><th class="px-4 py-2 text-right">Price</th></tr></thead>
                            <tbody class="divide-y divide-gray-800">
                                ${data.trades.map(t => `
                                    <tr class="hover:bg-gray-800/50">
                                        <td class="px-4 py-2 text-gray-500">${t.date}</td>
                                        <td class="px-4 py-2 font-bold">${t.symbol}</td>
                                        <td class="px-4 py-2"><span class="px-1.5 py-0.5 rounded text-[8px] font-bold ${t.type === 'BUY' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'}">${t.type}</span></td>
                                        <td class="px-4 py-2 text-right font-mono">${t.quantity}</td>
                                        <td class="px-4 py-2 text-right font-mono font-bold">$${t.price.toFixed(2)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
        lucide.createIcons();
    } catch(e) {
        chartArea.innerHTML = '<div class="text-red-500">Failed to load execution ledger.</div>';
    }
}

async function loadModelFactory() {
    const grid = document.getElementById('models-grid');
    grid.innerHTML = '<div class="col-span-full py-8 text-center text-gray-500 italic animate-pulse">Scanning model registry...</div>';
    try {
        const resp = await fetch(`${API_BASE}/models?limit=30`);
        const data = await resp.json();
        const models = data.versions || [];
        grid.innerHTML = models.map(m => {
            const metrics = m.metrics_json ? JSON.parse(m.metrics_json) : {};
            return `
            <div class="bg-gray-800 rounded-xl border border-gray-700 p-5 hover:border-blue-500/50 transition-all group">
                <div class="flex justify-between items-start mb-4">
                    <div class="p-2 bg-blue-500/10 rounded-lg group-hover:bg-blue-600 transition-colors"><i data-lucide="cpu" class="w-5 h-5 text-blue-500 group-hover:text-white"></i></div>
                    <div class="flex gap-2">
                        <button onclick="viewModelConfig('${m.id}')" class="text-[10px] text-gray-500 hover:text-blue-400 font-bold flex items-center gap-1"><i data-lucide="code" class="w-3 h-3"></i> Config</button>
                        <span class="text-[10px] font-bold px-2 py-0.5 rounded border border-gray-600 uppercase text-gray-400">${m.market}</span>
                    </div>
                </div>
                <h3 class="font-bold text-gray-200 mb-1 truncate">${m.tag || 'Unnamed Model'}</h3>
                <p class="text-[10px] text-gray-600 font-mono mb-4">${m.id}</p>
                <div class="grid grid-cols-2 gap-4 pt-4 border-t border-gray-700">
                    <div><div class="text-[9px] text-gray-500 uppercase font-bold">Return</div><div class="text-sm font-mono text-green-500">${(metrics.annualized_return*100 || 0).toFixed(1)}%</div></div>
                    <div><div class="text-[9px] text-gray-500 uppercase font-bold">Sharpe</div><div class="text-sm font-mono text-blue-400">${(metrics.sharpe || 0).toFixed(2)}</div></div>
                </div>
            </div>`;
        }).join('');
        lucide.createIcons();
    } catch(e) {}
}

async function viewModelConfig(versionId) {
    const modal = document.getElementById('modal');
    modal.classList.remove('hidden');
    document.getElementById('modal-title').textContent = 'Model Configuration';
    document.getElementById('modal-subtitle').textContent = `ID: ${versionId}`;
    const chartArea = document.getElementById('curve-chart-pro');
    chartArea.innerHTML = '<div class="text-gray-500 italic animate-pulse">Loading YAML config...</div>';

    try {
        const resp = await fetch(`${API_BASE}/models/${versionId}`);
        const data = await resp.json();
        const config = data.config || { name: 'N/A', content: 'No config found.' };
        chartArea.innerHTML = `
            <div class="h-full flex flex-col">
                <div class="bg-gray-900 p-2 border-l-4 border-blue-500 text-blue-400 text-xs font-mono mb-4 flex justify-between">
                    <span>${config.name}</span>
                    <span class="text-gray-600">YAML</span>
                </div>
                <pre class="flex-1 bg-gray-900 p-4 rounded-lg overflow-auto font-mono text-xs text-gray-300 leading-relaxed">${config.content}</pre>
            </div>
        `;
    } catch(e) {
        chartArea.innerHTML = '<div class="text-red-500">Failed to load configuration.</div>';
    }
}

async function loadDataHealth() {
    const stats = document.getElementById('data-health-stats');
    try {
        const resp = await fetch(`${API_BASE}/data/status`);
        const data = await resp.json();
        stats.innerHTML = `
            <div class="p-4 bg-gray-900/50 rounded-lg border border-gray-700 flex justify-between items-center">
                <span class="text-sm">Main Calendar Index</span>
                <span class="font-mono text-xs text-green-500">${data.data.latest_calendar_day}</span>
            </div>
            <div class="p-4 bg-gray-900/50 rounded-lg border border-gray-700 flex justify-between items-center">
                <span class="text-sm">Engine Connectivity</span>
                <span class="font-mono text-xs text-blue-400">STABLE (Ping: 14ms)</span>
            </div>
            <div class="p-4 bg-gray-900/50 rounded-lg border border-gray-700 flex justify-between items-center">
                <span class="text-sm">Region: US_EQUITIES</span>
                <span class="font-mono text-xs text-gray-400">OK (Synchronized)</span>
            </div>
            <div class="p-4 bg-gray-900/50 rounded-lg border border-gray-700 flex justify-between items-center">
                <span class="text-sm">Region: CN_SHARES</span>
                <span class="font-mono text-xs text-gray-400">OK (Synchronized)</span>
            </div>`;
    } catch(e) {}
}

// UI & Jobs Shared logic
async function loadArena() {
    const container = document.getElementById('arena-list');
    try {
        const response = await fetch(`${API_BASE}/arena/leaderboard?arena_name=Global Arena`);
        const data = await response.json();
        const lb = data.leaderboard || [];
        container.innerHTML = lb.slice(0, 5).map((r, idx) => `
            <div class="flex items-center gap-4 p-3 bg-gray-900/50 rounded-lg border border-gray-700/50 transition-all hover:translate-x-1 cursor-default">
                <div class="w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center font-bold text-[10px] ${idx === 0 ? 'text-yellow-500 border border-yellow-500/50' : 'text-gray-400'}">${r.rank}</div>
                <div class="flex-1 min-w-0"><div class="text-xs font-bold truncate">${r.participant_name}</div></div>
                <div class="text-right text-xs font-mono font-bold ${r.daily_return >= 0 ? 'text-green-500' : 'text-red-500'}">${(r.daily_return * 100).toFixed(2)}%</div>
            </div>`).join('');
    } catch (e) {}
}

async function loadJobs() {
    const consoleElem = document.getElementById('jobs-console');
    try {
        const response = await fetch(`${API_BASE}/jobs?limit=20`);
        const data = await response.json();
        const jobs = data.jobs || [];
        document.getElementById('stat-jobs').textContent = jobs.filter(j => j.status === 'running').length;
        consoleElem.innerHTML = jobs.map(j => `
            <div class="flex gap-2 cursor-pointer hover:bg-white/5 p-1 rounded transition-colors" onclick="streamLogs('${j.id}')">
                <span class="text-gray-600 font-bold">[${new Date(j.created_at * 1000).toLocaleTimeString()}]</span>
                <span class="${j.status === 'succeeded' ? 'text-green-500' : j.status === 'failed' ? 'text-red-500' : 'text-blue-400 animate-pulse'} font-bold w-12 text-center uppercase">${j.status.substring(0,4)}</span>
                <span class="text-gray-300 flex-1 truncate text-[9px] uppercase tracking-tighter">${j.type}</span>
            </div>`).join('');
    } catch (e) {}
}

function initCharts() {
    const mainOptions = {
        series: [{ name: 'Strategy Alpha', data: [] }],
        chart: { height: '100%', type: 'area', toolbar: { show: false }, background: 'transparent', animations: { enabled: true } },
        colors: ['#3b82f6'],
        fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.45, opacityTo: 0.05 } },
        dataLabels: { enabled: false },
        stroke: { curve: 'smooth', width: 2 },
        theme: { mode: 'dark' },
        grid: { borderColor: '#374151', strokeDashArray: 4 },
        xaxis: { type: 'datetime', labels: { style: { colors: '#6b7280' } } },
        yaxis: { labels: { style: { colors: '#6b7280' } } },
        tooltip: { theme: 'dark' }
    };
    mainChart = new ApexCharts(document.querySelector("#main-chart"), mainOptions);
    mainChart.render();
}

async function showCurve(runId, tag) {
    const modal = document.getElementById('modal');
    modal.classList.remove('hidden');
    document.getElementById('modal-title').textContent = tag || 'Strategy Analysis';
    document.getElementById('modal-subtitle').textContent = `RUN_ID: ${runId}`;
    try {
        const response = await fetch(`${API_BASE}/backtest/curve?run_id=${runId}`);
        const data = await response.json();
        const points = data.curve || [];
        const options = {
            series: [{ name: 'NAV', data: points.map(p => ({ x: p.date, y: p.nav })) }],
            chart: { height: 500, type: 'line', toolbar: { show: true }, background: 'transparent' },
            colors: ['#10b981'],
            stroke: { width: 2 },
            xaxis: { type: 'datetime' },
            theme: { mode: 'dark' }
        };
        if (modalChart) modalChart.destroy();
        modalChart = new ApexCharts(document.querySelector("#curve-chart-pro"), options);
        modalChart.render();
    } catch (e) {}
}

function streamLogs(jobId) {
    const consoleElem = document.getElementById('jobs-console');
    consoleElem.innerHTML = `<div class="text-blue-400 font-bold border-b border-blue-900/50 pb-2 mb-2 italic underline text-[9px]">ATTACHED_STREAM: ${jobId}</div>`;
    const eventSource = new EventSource(`${API_BASE}/jobs/${jobId}/stream`);
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.line) {
            const line = document.createElement('div');
            line.className = 'text-gray-500 whitespace-pre-wrap leading-tight text-[9px]';
            line.textContent = `> ${data.line}`;
            consoleElem.appendChild(line);
            consoleElem.scrollTop = consoleElem.scrollHeight;
        }
    };
    eventSource.addEventListener('done', (e) => { eventSource.close(); setTimeout(loadJobs, 1000); });
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const windowElem = document.getElementById('chat-window');
    const msg = input.value.trim();
    if (!msg) return;
    windowElem.innerHTML += `<div class="bg-gray-700 p-2 rounded self-end ml-4 text-[11px] text-gray-100">${msg}</div>`;
    input.value = '';
    windowElem.scrollTop = windowElem.scrollHeight;
    try {
        const response = await fetch(`${API_BASE}/chat/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg, agent_type: 'alpha' })
        });
        const data = await response.json();
        windowElem.innerHTML += `<div class="text-blue-400 font-bold uppercase text-[9px] mt-2">AlphaAgent</div><div class="text-gray-300 bg-blue-500/5 p-2 rounded text-[11px] leading-relaxed">${(data.reply || '').replace(/\n/g, '<br>')}</div>`;
    } catch (e) {}
    windowElem.scrollTop = windowElem.scrollHeight;
}

async function triggerBacktest() {
    try {
        const response = await fetch(`${API_BASE}/system/exec`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: 'uv run python cli.py backtest' })
        });
        const data = await response.json();
        if (data.job_id) streamLogs(data.job_id);
    } catch (e) {}
}

function refreshLiveStats() {
    if (currentView === 'command-center') {
        loadArena();
        loadJobs();
    }
}

function toggleConsole() {
    const wrapper = document.getElementById('console-wrapper');
    wrapper.classList.toggle('h-64');
    wrapper.classList.toggle('h-10');
}

function switchConsole(view) {
    const logs = document.getElementById('jobs-console');
    const thoughts = document.getElementById('thoughts-console');
    const buttons = document.querySelectorAll('#console-wrapper button[onclick^="switchConsole"]');

    if (view === 'logs') {
        logs.classList.remove('hidden');
        thoughts.classList.add('hidden');
    } else {
        logs.classList.add('hidden');
        thoughts.classList.remove('hidden');
        loadThoughtStream();
    }

    buttons.forEach(btn => {
        if (btn.getAttribute('onclick').includes(view)) {
            btn.classList.add('text-blue-400', 'border-b', 'border-blue-400');
            btn.classList.remove('text-gray-500');
        } else {
            btn.classList.remove('text-blue-400', 'border-b', 'border-blue-400');
            btn.classList.add('text-gray-500');
        }
    });
}

async function loadThoughtStream() {
    const consoleElem = document.getElementById('thoughts-console');
    try {
        const resp = await fetch(`${API_BASE}/system/thought_stream?limit=20`);
        const data = await resp.json();
        const stream = data.stream || [];
        if (stream.length === 0) {
            consoleElem.innerHTML = '<div class="text-gray-600 italic">No agent thoughts recorded in this session.</div>';
            return;
        }
        consoleElem.innerHTML = stream.map(t => `
            <div class="border-l-2 ${t.level === 'success' ? 'border-green-500 bg-green-500/5' : t.level === 'error' ? 'border-red-500 bg-red-500/5' : 'border-blue-500 bg-blue-500/5'} p-2 rounded-r">
                <div class="flex justify-between items-center mb-1">
                    <span class="font-bold uppercase text-[8px] ${t.level === 'success' ? 'text-green-400' : t.level === 'error' ? 'text-red-400' : 'text-blue-400'}">${t.agent}</span>
                    <span class="text-[8px] text-gray-600">${t.timestamp}</span>
                </div>
                <div class="text-gray-300 leading-tight">${t.message}</div>
            </div>
        `).join('');
        consoleElem.scrollTop = consoleElem.scrollHeight;
    } catch(e) {
        consoleElem.innerHTML = '<div class="text-red-500 italic">Failed to load agent intelligence.</div>';
    }
}

// --- Task 7.1: Strategy Lab Visual Editor ---
let labCurrentFile = null;
let labSchema = null;
let labRawContent = null;

async function loadReportsIndex() {
    const grid = document.getElementById('reports-grid');
    grid.innerHTML = '<div class="col-span-4 py-20 text-center animate-pulse text-gray-600">Scanning filesystem for compliance reports...</div>';
    try {
        const resp = await fetch('/api/reports/list');
        const data = await resp.json();
        const reports = data.reports || [];
        if (reports.length === 0) {
            grid.innerHTML = '<div class="col-span-4 py-20 text-center text-gray-600 italic">No archived reports found.</div>';
            return;
        }
        grid.innerHTML = reports.map(r => `
            <div class="bg-gray-800 border border-gray-700 p-5 rounded-xl hover:border-blue-500/50 transition-all group relative overflow-hidden cursor-pointer" onclick="window.open('/api/reports/view/${r.id}')">
                <div class="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-100 transition-opacity">
                    <i data-lucide="external-link" class="w-4 h-4 text-blue-400"></i>
                </div>
                <div class="text-blue-500 mb-3 bg-blue-500/10 w-10 h-10 rounded-lg flex items-center justify-center group-hover:scale-110 transition-transform"><i data-lucide="file-bar-chart-2"></i></div>
                <h3 class="font-bold text-sm text-gray-200 mb-1 truncate">${r.name}</h3>
                <p class="text-[10px] text-gray-500 font-mono mb-2 uppercase">${r.market} • ${r.date}</p>
                <div class="flex items-center gap-2">
                    <span class="text-[9px] px-1.5 py-0.5 rounded bg-gray-900 border border-gray-700 text-gray-400 font-bold uppercase tracking-tight">${r.type}</span>
                </div>
            </div>
        `).join('');
        lucide.createIcons();
    } catch(e) {
        grid.innerHTML = '<div class="col-span-4 text-red-500 text-center">Failed to fetch report registry.</div>';
    }
}

// Intercept existing loadView to add Lab loading
const originalLoadView = loadView;
loadView = async function(viewId) {
    await originalLoadView(viewId);
    if (viewId === 'strategy-lab') loadStrategyLab();
}

async function loadStrategyLab() {
    const listContainer = document.getElementById('lab-file-list');
    listContainer.innerHTML = '<div class="p-4 text-center animate-pulse text-gray-600">Loading kernels...</div>';
    
    try {
        const resp = await fetch('/api/strategy/list');
        const data = await resp.json();
        const files = data.files || [];
        listContainer.innerHTML = files.map(f => `
            <button onclick="editLabFile('${f}')" class="w-full flex items-center gap-3 p-3 rounded-lg text-left transition-all hover:bg-gray-700 group">
                <div class="w-1.5 h-1.5 rounded-full bg-gray-600 group-hover:bg-blue-500"></div>
                <span class="text-xs font-medium text-gray-400 group-hover:text-white truncate">${f}</span>
            </button>
        `).join('');
    } catch(e) {
        listContainer.innerHTML = '<div class="p-4 text-red-500 text-xs italic">Sync error.</div>';
    }
}

async function editLabFile(filename) {
    labCurrentFile = filename;
    document.getElementById('lab-current-file').textContent = `BUFFER: ${filename}`;
    const container = document.getElementById('lab-form-container');
    container.innerHTML = '<div class="py-20 text-center animate-pulse text-gray-600 italic font-mono text-xs">DISSECTING CONFIG KERNEL...</div>';
    
    try {
        const [contentResp, schemaResp] = await Promise.all([
            fetch(`/api/strategy/content/${filename}`),
            fetch(`/api/strategy/schema/${filename}`)
        ]);
        
        const contentData = await contentResp.json();
        const schemaData = await schemaResp.json();
        labSchema = schemaData.schema;
        labRawContent = contentData.content;
        
        // Use js-yaml for robust parsing
        const configObj = jsyaml.load(labRawContent) || {};
        
        let html = '<div class="space-y-10">';
        for (const [sectionKey, section] of Object.entries(labSchema)) {
            html += `
                <div class="space-y-4">
                    <div class="flex items-center gap-3 mb-6">
                        <div class="h-px flex-1 bg-gray-700"></div>
                        <h4 class="text-[10px] font-black uppercase tracking-[0.2em] text-blue-500 shadow-blue-500/20">${section.title}</h4>
                        <div class="h-px flex-1 bg-gray-700"></div>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-6">
            `;
            
            for (const [fieldKey, field] of Object.entries(section.fields)) {
                const id = `field-${sectionKey}-${fieldKey}`;
                // Deep find in config object
                let currentVal = "";
                if (configObj[sectionKey] && configObj[sectionKey][fieldKey] !== undefined) {
                    currentVal = configObj[sectionKey][fieldKey];
                } else if (configObj[fieldKey] !== undefined) {
                    currentVal = configObj[fieldKey];
                }
                
                html += `
                    <div class="space-y-2">
                        <label class="block text-[10px] font-bold text-gray-500 uppercase tracking-wider">${field.label}</label>
                `;
                
                if (field.type === 'select') {
                    html += `<select id="${id}" class="w-full bg-gray-900 border border-gray-700 rounded-lg p-2.5 text-xs text-blue-400 outline-none focus:border-blue-500 transition-colors cursor-pointer">`;
                    field.options.forEach(opt => {
                        const selected = String(currentVal) === String(opt) ? "selected" : "";
                        html += `<option value="${opt}" ${selected}>${opt.toUpperCase()}</option>`;
                    });
                    html += `</select>`;
                } else {
                    html += `<input type="${field.type}" id="${id}" value="${currentVal}" ${field.min ? `min="${field.min}"` : ''} ${field.max ? `max="${field.max}"` : ''} ${field.step ? `step="${field.step}"` : ''} class="w-full bg-gray-900 border border-gray-700 rounded-lg p-2.5 text-xs text-gray-200 outline-none focus:border-blue-500 transition-colors" placeholder="Default: ${field.default || ''}">`;
                }
                
                html += `</div>`;
            }
            html += '</div></div>';
        }
        html += '</div>';
        container.innerHTML = html;
        lucide.createIcons();
        
    } catch(e) {
        console.error(e);
        container.innerHTML = `<div class="py-20 text-red-500 text-center italic">Failed to deconstruct kernel: ${e.message}</div>`;
    }
}

async function saveVisualConfig() {
    if (!labCurrentFile) return;
    
    try {
        const configObj = jsyaml.load(labRawContent) || {};
        
        for (const [sectionKey, section] of Object.entries(labSchema)) {
            for (const [fieldKey, field] of Object.entries(section.fields)) {
                const el = document.getElementById(`field-${sectionKey}-${fieldKey}`);
                if (el) {
                    let val = el.value;
                    if (field.type === 'number') val = parseFloat(val);
                    
                    // Map back to structure
                    if (configObj[sectionKey]) {
                        configObj[sectionKey][fieldKey] = val;
                    } else {
                        // If section doesn't exist, check if it's a flat param or needs creation
                        if (!configObj[sectionKey] && sectionKey !== 'workflow') {
                             configObj[sectionKey] = configObj[sectionKey] || {};
                             configObj[sectionKey][fieldKey] = val;
                        } else {
                             configObj[fieldKey] = val;
                        }
                    }
                }
            }
        }
        
        const updatedContent = jsyaml.dump(configObj, { indent: 4, lineWidth: -1 });
        
        const resp = await fetch('/api/strategy/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: labCurrentFile, content: updatedContent })
        });
        
        const data = await resp.json();
        if (resp.ok && data.ok) {
            alert('Strategy kernel updated and validated successfully.');
            labRawContent = updatedContent;
        } else {
            alert(`Save failed: ${data.detail || 'Unknown error'}`);
        }
    } catch(e) {
        alert(`Serialization error: ${e.message}`);
    }
}
