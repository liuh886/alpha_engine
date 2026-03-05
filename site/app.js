let chartInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    loadManifest();
    loadModels();
    loadArena();
    loadReports();

    document.getElementById('market-filter').addEventListener('change', (e) => {
        loadModels(e.target.value);
    });

    document.getElementById('close-modal').addEventListener('click', () => {
        document.getElementById('modal').classList.add('hidden');
    });
});

async function showCurve(runId, tag) {
    const modal = document.getElementById('modal');
    const title = document.getElementById('modal-title');
    modal.classList.remove('hidden');
    title.textContent = `Equity Curve: ${tag || runId}`;

    try {
        const response = await fetch(`data/curves/${runId}.json`);
        const data = await response.json();
        
        const ctx = document.getElementById('curve-chart').getContext('2d');
        if (chartInstance) chartInstance.destroy();

        chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.points.map(p => p.date),
                datasets: [{
                    label: 'NAV',
                    data: data.points.map(p => p.nav),
                    borderColor: 'rgb(59, 130, 246)',
                    tension: 0.1,
                    fill: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                scales: {
                    y: { beginAtZero: false }
                }
            }
        });
    } catch (e) {
        console.error("Failed to load curve", e);
        alert("Curve data not available for this run.");
        modal.classList.add('hidden');
    }
}

async function loadModels(marketFilter = 'all') {
    const tbody = document.getElementById('models-table');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4">Loading...</td></tr>';
    
    try {
        const response = await fetch('data/models.json');
        let models = await response.json();
        
        if (marketFilter !== 'all') {
            models = models.filter(m => m.market.toLowerCase() === marketFilter);
        }

        if (models.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4">No models found</td></tr>';
            return;
        }

        tbody.innerHTML = models.map(m => `
            <tr class="border-b border-gray-200 hover:bg-gray-100">
                <td class="py-3 px-4 text-left whitespace-nowrap">
                    <div class="font-bold">${m.tag || m.id}</div>
                    <div class="text-xs text-gray-400">${m.id}</div>
                </td>
                <td class="py-3 px-4 text-center">
                    <span class="bg-${m.market === 'us' ? 'blue' : 'red'}-100 text-${m.market === 'us' ? 'blue' : 'red'}-800 text-xs font-semibold px-2.5 py-0.5 rounded uppercase">
                        ${m.market}
                    </span>
                </td>
                <td class="py-3 px-4 text-center font-mono">
                    ${m.metrics ? (m.metrics.annualized_return * 100).toFixed(2) + '%' : 'N/A'}
                </td>
                <td class="py-3 px-4 text-center text-red-500 font-mono">
                    ${m.metrics ? (m.metrics.max_drawdown * 100).toFixed(2) + '%' : 'N/A'}
                </td>
                <td class="py-3 px-4 text-center">
                    ${m.run_id ? `<button onclick="showCurve('${m.run_id}', '${m.tag}')" class="bg-blue-500 hover:bg-blue-700 text-white text-xs font-bold py-1 px-2 rounded">View</button>` : '-'}
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-red-500">Error loading data</td></tr>';
    }
}

async function loadArena() {
    const tbody = document.getElementById('arena-table');
    try {
        const response = await fetch('data/arena.json');
        const data = await response.json();
        
        if (!data.leaderboard || data.leaderboard.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4">No arena data</td></tr>';
            return;
        }

        tbody.innerHTML = data.leaderboard.slice(0, 10).map(r => `
            <tr class="border-b border-gray-200">
                <td class="py-3 px-4 text-left font-bold">#${r.rank}</td>
                <td class="py-3 px-4 text-left">${r.participant_name}</td>
                <td class="py-3 px-4 text-center font-mono">${r.nav.toFixed(4)}</td>
                <td class="py-3 px-4 text-center font-mono ${r.daily_return >= 0 ? 'text-green-500' : 'text-red-500'}">
                    ${(r.daily_return * 100).toFixed(2)}%
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-red-500">Error loading data</td></tr>';
    }
}

async function loadReports() {
    const grid = document.getElementById('reports-grid');
    try {
        const response = await fetch('data/reports.json');
        const reports = await response.json();
        
        if (reports.length === 0) {
            grid.innerHTML = '<p class="col-span-full text-center py-4">No reports found</p>';
            return;
        }

        grid.innerHTML = reports.slice(0, 9).map(r => `
            <div class="border p-4 rounded hover:shadow-md transition-shadow bg-gray-50 border-gray-200">
                <div class="text-xs font-bold text-gray-400 uppercase mb-1">${r.type}</div>
                <div class="text-sm font-semibold truncate mb-2">${r.ref_id}</div>
                <div class="text-xs text-gray-500 mb-3">${r.date}</div>
                <a href="${r.static_html_path || '#'}" target="_blank" class="text-blue-600 text-xs font-bold hover:underline">
                    ${r.static_html_path ? 'View Report &rarr;' : 'Report Missing'}
                </a>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = '<p class="col-span-full text-center py-4 text-red-500">Error loading reports</p>';
    }
}
