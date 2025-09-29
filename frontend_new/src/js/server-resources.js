/**
 * AI-Ops 服务器资源监控页面 - Tailwind CSS版本
 */

// 全局状态
const SR_STATE = {
    items: [],
    filtered: [],
    page: 1,
    pageSize: 12,
    sortBy: 'max',
    sortDir: 'desc',
    query: '',
    auto: true,
    instanceFilter: null
};

// 工具函数
const Utils = {
    formatPct: (v) => {
        return (Number(v || 0)).toFixed(1) + '%';
    },

    pickDiskMax: (server) => {
        try {
            const partitions = server.disk?.partitions || [];
            if (!partitions.length) return { usage: 0, name: '-' };
            
            const maxPartition = partitions.reduce((max, p) => {
                const usage = Number(p.usage_percent || 0);
                return usage > max.usage ? { 
                    usage, 
                    name: p.mountpoint || p.device || '-' 
                } : max;
            }, { usage: 0, name: '-' });
            
            return maxPartition;
        } catch (e) {
            return { usage: 0, name: '-' };
        }
    },

    computeMetrics: (list) => {
        const n = list.length || 0;
        if (!n) return { count: 0, avgCpu: 0, avgMem: 0, high: 0 };
        
        let cpu = 0, mem = 0, high = 0;
        list.forEach(s => {
            const c = Number(s.cpu?.usage_percent || 0);
            const m = Number(s.memory?.usage_percent || 0);
            cpu += c;
            mem += m;
            if (Math.max(c, m) >= 80) high++;
        });
        
        return {
            count: n,
            avgCpu: cpu / n,
            avgMem: mem / n,
            high
        };
    },

    getProgressBarClass: (value) => {
        if (value >= 80) return 'bg-red-500';
        if (value >= 60) return 'bg-yellow-500';
        return 'bg-green-500';
    },

    getStatusDotClass: (cpu, mem) => {
        if (cpu >= 80 || mem >= 80) return 'bg-red-500';
        if (cpu >= 60 || mem >= 60) return 'bg-yellow-500';
        return 'bg-green-500';
    }
};

// 数据管理器
class ServerResourcesDataManager {
    constructor(uiManager) {
        this.refreshTimer = null;
        this.uiManager = uiManager;
    }

    readQuery() {
        const sp = new URLSearchParams(location.search);
        const inst = sp.get('instance');
        if (inst) SR_STATE.instanceFilter = inst;
    }

    applyFilters() {
        let arr = SR_STATE.items.slice();
        
        // 实例筛选
        if (SR_STATE.instanceFilter) {
            arr = arr.filter(s => (s.instance || '').includes(SR_STATE.instanceFilter));
            const pill = document.getElementById('sr-active-filter');
            pill.textContent = '实例筛选: ' + SR_STATE.instanceFilter;
            pill.style.display = 'inline-flex';
            pill.onclick = () => {
                SR_STATE.instanceFilter = null;
                pill.style.display = 'none';
                this.applyFilters();
                this.uiManager.renderAll();
            };
        }

        // 搜索筛选
        const q = SR_STATE.query.trim().toLowerCase();
        if (q) {
            arr = arr.filter(s => 
                (s.instance || '').toLowerCase().includes(q) || 
                (s.system?.hostname || '').toLowerCase().includes(q)
            );
        }

        // 排序
        const sortKey = SR_STATE.sortBy;
        arr.sort((a, b) => {
            const cpuA = Number(a.cpu?.usage_percent || 0);
            const cpuB = Number(b.cpu?.usage_percent || 0);
            const memA = Number(a.memory?.usage_percent || 0);
            const memB = Number(b.memory?.usage_percent || 0);
            const diskA = Utils.pickDiskMax(a);
            const diskB = Utils.pickDiskMax(b);
            
            let keyA, keyB;
            switch (sortKey) {
                case 'cpu':
                    keyA = cpuA;
                    keyB = cpuB;
                    break;
                case 'mem':
                    keyA = memA;
                    keyB = memB;
                    break;
                case 'disk':
                    keyA = diskA.usage;
                    keyB = diskB.usage;
                    break;
                default: // 'max'
                    keyA = Math.max(cpuA, memA);
                    keyB = Math.max(cpuB, memB);
            }
            
            return SR_STATE.sortDir === 'desc' ? (keyB - keyA) : (keyA - keyB);
        });

        SR_STATE.filtered = arr;
        
        // 调整页码
        const totalPages = Math.max(1, Math.ceil(arr.length / SR_STATE.pageSize));
        if (SR_STATE.page > totalPages) SR_STATE.page = totalPages;
    }

    async fetchData(initial = false) {
        try {
            if (initial) {
                // 快速读取缓存
                const quickUrl = `/api/server-resources?quick=true&t=${Date.now()}`;
                const quick = await axios.get(quickUrl, { timeout: 20000 });
                SR_STATE.items = Array.isArray(quick.data?.data) ? 
                    quick.data.data : 
                    (Array.isArray(quick.data) ? quick.data : []);
                
                this.applyFilters();
                this.uiManager.renderAll();

                // 后台强制刷新
                axios.get(`/api/server-resources?refresh=true&t=${Date.now()}`, { timeout: 60000 })
                    .then(r => {
                        const fresh = Array.isArray(r.data?.data) ? 
                            r.data.data : 
                            (Array.isArray(r.data) ? r.data : []);
                        
                        if (fresh && fresh.length > 0) {
                            SR_STATE.items = fresh;
                            this.applyFilters();
                            this.uiManager.renderAll();
                        }
                    })
                    .catch(() => {});
                return;
            }

            const url = `/api/server-resources?t=${Date.now()}`;
            const resp = await axios.get(url, { timeout: 30000 });
            SR_STATE.items = Array.isArray(resp.data?.data) ? 
                resp.data.data : 
                (Array.isArray(resp.data) ? resp.data : []);
            
            this.applyFilters();
            this.uiManager.renderAll();
        } catch (e) {
            document.getElementById('sr-grid').innerHTML = `
                <div class="col-span-full flex items-center justify-center py-12 text-red-500">
                    <div class="text-center">
                        <i class="bi bi-exclamation-triangle text-2xl mb-2"></i>
                        <div>加载失败：${e.message}</div>
                    </div>
                </div>
            `;
        }
    }

    startAutoRefresh() {
        this.refreshTimer = setInterval(() => {
            if (SR_STATE.auto) {
                this.fetchData(false);
            }
        }, 30000);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }
}

// UI管理器
class ServerResourcesUIManager {
    constructor() {
        this.dataManager = new ServerResourcesDataManager(this);
    }

    init() {
        this.dataManager.readQuery();
        this.bindEvents();
        this.dataManager.fetchData(true);
        this.dataManager.startAutoRefresh();
    }

    bindEvents() {
        // 刷新按钮
        document.getElementById('sr-refresh').onclick = () => {
            this.dataManager.fetchData(true);
        };

        // 自动刷新开关
        document.getElementById('sr-auto').onchange = (e) => {
            SR_STATE.auto = !!e.target.checked;
        };

        // 排序选择
        document.getElementById('sr-sort').onchange = (e) => {
            SR_STATE.sortBy = e.target.value;
            SR_STATE.page = 1;
            this.dataManager.applyFilters();
            this.dataManager.renderAll();
        };

        // 每页条数
        document.getElementById('sr-page-size').onchange = (e) => {
            SR_STATE.pageSize = parseInt(e.target.value || '12', 10);
            SR_STATE.page = 1;
            this.dataManager.applyFilters();
            this.dataManager.renderAll();
        };

        // 搜索框
        const search = document.getElementById('sr-search');
        let searchTimeout = null;
        search.oninput = (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                SR_STATE.query = e.target.value || '';
                SR_STATE.page = 1;
                this.dataManager.applyFilters();
                this.renderAll();
            }, 200);
        };
    }

    renderMetrics() {
        const m = Utils.computeMetrics(SR_STATE.filtered);
        const el = document.getElementById('sr-metrics');
        
        el.innerHTML = `
            <div class="bg-white rounded-xl p-4 shadow-sm border-l-4 border-blue-500">
                <div class="text-xs text-gray-500 uppercase tracking-wide mb-1">服务器数量</div>
                <div class="text-2xl font-bold text-gray-900">${m.count}</div>
            </div>
            <div class="bg-white rounded-xl p-4 shadow-sm border-l-4 border-green-500">
                <div class="text-xs text-gray-500 uppercase tracking-wide mb-1">平均CPU</div>
                <div class="text-2xl font-bold text-gray-900">${m.avgCpu.toFixed(1)}%</div>
            </div>
            <div class="bg-white rounded-xl p-4 shadow-sm border-l-4 border-purple-500">
                <div class="text-xs text-gray-500 uppercase tracking-wide mb-1">平均内存</div>
                <div class="text-2xl font-bold text-gray-900">${m.avgMem.toFixed(1)}%</div>
            </div>
            <div class="bg-white rounded-xl p-4 shadow-sm border-l-4 border-red-500">
                <div class="text-xs text-gray-500 uppercase tracking-wide mb-1">高负载(>=80%)</div>
                <div class="text-2xl font-bold text-gray-900">${m.high}</div>
            </div>
        `;
    }

    renderGrid() {
        const grid = document.getElementById('sr-grid');
        
        if (!SR_STATE.filtered.length) {
            grid.innerHTML = `
                <div class="col-span-full flex items-center justify-center py-12 text-gray-500">
                    <div class="text-center">
                        <i class="bi bi-server text-4xl mb-3"></i>
                        <div>暂无服务器资源信息</div>
                    </div>
                </div>
            `;
            return;
        }

        const start = (SR_STATE.page - 1) * SR_STATE.pageSize;
        const pageItems = SR_STATE.filtered.slice(start, start + SR_STATE.pageSize);
        
        let html = '';
        pageItems.forEach(sv => {
            const instance = sv.instance || 'unknown';
            const hostname = (sv.system?.hostname) || (instance.split(':')[0] || '');
            const cpu = Number(sv.cpu?.usage_percent || 0);
            const mem = Number(sv.memory?.usage_percent || 0);
            const disk = Utils.pickDiskMax(sv);
            const cores = sv.cpu?.cores || 0;
            const memGb = sv.memory?.total_gb || 0;
            const up = Number(sv.system?.uptime_days || 0);

            html += `
                <div class="bg-white rounded-2xl shadow-lg hover:shadow-xl transition-all duration-300 hover:-translate-y-1 overflow-hidden">
                    <!-- 服务器头部 -->
                    <div class="bg-gradient-to-r from-gray-50 to-gray-100 px-4 py-3 border-b border-gray-200">
                        <div class="flex items-center justify-between">
                            <h6 class="flex items-center space-x-2 font-semibold text-gray-900">
                                <i class="bi bi-hdd-network text-blue-600"></i>
                                <span>${instance}</span>
                            </h6>
                            <span class="inline-flex items-center space-x-2 px-3 py-1 rounded-full text-xs bg-white border border-gray-200">
                                <span class="w-2 h-2 rounded-full ${Utils.getStatusDotClass(cpu, mem)}"></span>
                                <span class="text-gray-600">${hostname}</span>
                            </span>
                        </div>
                    </div>

                    <!-- 服务器内容 -->
                    <div class="p-4">
                        <!-- CPU 使用率 -->
                        <div class="mb-3">
                            <div class="flex justify-between items-center mb-1">
                                <span class="text-xs text-gray-500">CPU 使用率</span>
                                <span class="text-xs font-medium text-gray-700">${Utils.formatPct(cpu)}</span>
                            </div>
                            <div class="w-full bg-gray-200 rounded-full h-3">
                                <div class="h-3 rounded-full transition-all duration-300 ${Utils.getProgressBarClass(cpu)}" style="width: ${cpu}%"></div>
                            </div>
                        </div>

                        <!-- 内存使用率 -->
                        <div class="mb-3">
                            <div class="flex justify-between items-center mb-1">
                                <span class="text-xs text-gray-500">内存使用率</span>
                                <span class="text-xs font-medium text-gray-700">${Utils.formatPct(mem)}</span>
                            </div>
                            <div class="w-full bg-gray-200 rounded-full h-3">
                                <div class="h-3 rounded-full transition-all duration-300 ${Utils.getProgressBarClass(mem)}" style="width: ${mem}%"></div>
                            </div>
                        </div>

                        <!-- 磁盘使用率 -->
                        <div class="mb-4">
                            <div class="flex justify-between items-center mb-1">
                                <span class="text-xs text-gray-500">磁盘使用率(最大): <code class="text-xs bg-gray-100 px-1 rounded">${disk.name}</code></span>
                                <span class="text-xs font-medium text-gray-700">${Utils.formatPct(disk.usage)}</span>
                            </div>
                            <div class="w-full bg-gray-200 rounded-full h-3">
                                <div class="h-3 rounded-full transition-all duration-300 ${Utils.getProgressBarClass(disk.usage)}" style="width: ${disk.usage}%"></div>
                            </div>
                        </div>

                        <!-- 服务器信息 -->
                        <div class="flex justify-between text-xs text-gray-500 mb-4">
                            <span>核心: <strong class="text-gray-700">${cores}</strong></span>
                            <span>内存: <strong class="text-gray-700">${memGb} GB</strong></span>
                            <span>运行: <strong class="text-gray-700">${up.toFixed(1)} 天</strong></span>
                        </div>

                        <!-- 操作按钮 -->
                        <div class="flex justify-end">
                            <a href="/server-resources?instance=${encodeURIComponent(instance)}" 
                               class="inline-flex items-center space-x-1 px-3 py-2 text-xs bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors">
                                <i class="bi bi-aspect-ratio"></i>
                                <span>仅看此实例</span>
                            </a>
                        </div>
                    </div>
                </div>
            `;
        });

        grid.innerHTML = html;
    }

    renderPager() {
        const pager = document.getElementById('sr-pager');
        const total = SR_STATE.filtered.length;
        const totalPages = Math.max(1, Math.ceil(total / SR_STATE.pageSize));
        const prevDisabled = SR_STATE.page <= 1;
        const nextDisabled = SR_STATE.page >= totalPages;

        pager.innerHTML = `
            <div class="text-sm text-gray-600">
                共 ${total} 台 · 每页 ${SR_STATE.pageSize} 台
            </div>
            <div class="flex items-center space-x-2">
                <button 
                    class="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors ${prevDisabled ? 'opacity-50 cursor-not-allowed' : ''}"
                    onclick="window.ServerResourcesUI.gotoPage(${SR_STATE.page - 1})"
                    ${prevDisabled ? 'disabled' : ''}
                >
                    上一页
                </button>
                <span class="text-sm text-gray-600">
                    第 ${SR_STATE.page}/${totalPages} 页
                </span>
                <button 
                    class="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors ${nextDisabled ? 'opacity-50 cursor-not-allowed' : ''}"
                    onclick="window.ServerResourcesUI.gotoPage(${SR_STATE.page + 1})"
                    ${nextDisabled ? 'disabled' : ''}
                >
                    下一页
                </button>
            </div>
        `;
    }

    renderAll() {
        this.renderMetrics();
        this.renderGrid();
        this.renderPager();
    }

    gotoPage(p) {
        if (p < 1) return;
        SR_STATE.page = p;
        this.renderAll();
    }

    destroy() {
        this.dataManager.stopAutoRefresh();
    }
}

// 初始化应用
function initializeServerResourcesApp() {
    const uiManager = new ServerResourcesUIManager();
    uiManager.init();

    // 全局变量，便于调试和分页
    window.ServerResourcesUI = uiManager;
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initializeServerResourcesApp);

// 页面卸载时清理资源
window.addEventListener('beforeunload', () => {
    if (window.ServerResourcesUI) {
        window.ServerResourcesUI.destroy();
    }
});