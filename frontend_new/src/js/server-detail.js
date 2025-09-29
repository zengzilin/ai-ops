/**
 * AI-Ops 服务器详情页面 - Tailwind CSS版本
 */

// 工具函数
const Utils = {
    getQueryParam: (key) => {
        return new URLSearchParams(location.search).get(key) || '';
    },

    formatPct: (v) => {
        return (Number(v || 0)).toFixed(1) + '%';
    },

    pickDiskMax: (server) => {
        try {
            const partitions = server.disk?.partitions || [];
            if (!partitions.length) return 0;
            return Math.max(...partitions.map(p => Number(p.usage_percent || 0)));
        } catch (e) {
            return 0;
        }
    },

    getProgressBarClass: (value) => {
        if (value >= 80) return 'bg-red-500';
        if (value >= 60) return 'bg-yellow-500';
        return 'bg-green-500';
    },

    getMetricCardClass: (value) => {
        if (value >= 80) return 'border-red-500';
        if (value >= 60) return 'border-yellow-500';
        return 'border-green-500';
    }
};

// 数据管理器
class ServerDetailDataManager {
    constructor() {
        this.instance = Utils.getQueryParam('instance');
    }

    async fetchServerData() {
        try {
            // 快速读取缓存
            const quickResponse = await axios.get('/api/server-resources?quick=true&t=' + Date.now());
            let serverData = (quickResponse.data?.data || quickResponse.data || [])
                .find(s => (s.instance || '') === this.instance);

            if (!serverData) {
                // 后台强制刷新并重试
                try {
                    await axios.get('/api/server-resources?refresh=true&t=' + Date.now(), { timeout: 60000 });
                } catch (e) {
                    console.warn('后台刷新失败:', e);
                }

                const freshResponse = await axios.get('/api/server-resources?t=' + Date.now());
                serverData = (freshResponse.data?.data || freshResponse.data || [])
                    .find(s => (s.instance || '') === this.instance);
            }

            return serverData;
        } catch (error) {
            console.error('获取服务器数据失败:', error);
            throw error;
        }
    }
}

// UI管理器
class ServerDetailUIManager {
    constructor() {
        this.dataManager = new ServerDetailDataManager();
    }

    async init() {
        // 设置实例名称
        document.getElementById('title-inst').textContent = this.dataManager.instance || '未知实例';

        try {
            const serverData = await this.dataManager.fetchServerData();
            this.renderServerDetail(serverData);
        } catch (error) {
            this.renderError('加载失败：' + (error.message || error));
        }
    }

    renderServerDetail(serverData) {
        if (!serverData) {
            this.renderError('未找到该实例数据');
            return;
        }

        const cpu = Number(serverData.cpu?.usage_percent || 0);
        const mem = Number(serverData.memory?.usage_percent || 0);
        const diskMax = Utils.pickDiskMax(serverData);
        const cores = serverData.cpu?.cores || 0;
        const memGb = serverData.memory?.total_gb || 0;
        const uptime = Number(serverData.system?.uptime_days || 0);
        const hostname = (serverData.system?.hostname) || (this.dataManager.instance.split(':')[0] || '');

        // 渲染顶部指标
        this.renderTopMetrics(cpu, mem, diskMax, uptime);

        // 渲染资源进度条
        this.renderResourceBars(cpu, mem, diskMax);

        // 渲染基本信息
        this.renderBasicInfo(this.dataManager.instance, hostname, cores, memGb, uptime);

        // 渲染磁盘分区表格
        this.renderDiskPartitions(serverData.disk?.partitions || []);
    }

    renderTopMetrics(cpu, mem, diskMax, uptime) {
        const topMetrics = document.getElementById('top-metrics');
        
        topMetrics.innerHTML = `
            <div class="bg-white rounded-xl p-6 shadow-lg border-l-4 ${Utils.getMetricCardClass(cpu)}">
                <div class="text-center">
                    <div class="text-xs text-gray-500 uppercase tracking-wide mb-2">CPU 使用率</div>
                    <div class="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                        ${cpu.toFixed(1)}%
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-xl p-6 shadow-lg border-l-4 ${Utils.getMetricCardClass(mem)}">
                <div class="text-center">
                    <div class="text-xs text-gray-500 uppercase tracking-wide mb-2">内存 使用率</div>
                    <div class="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                        ${mem.toFixed(1)}%
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-xl p-6 shadow-lg border-l-4 ${Utils.getMetricCardClass(diskMax)}">
                <div class="text-center">
                    <div class="text-xs text-gray-500 uppercase tracking-wide mb-2">磁盘(最大)</div>
                    <div class="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                        ${diskMax.toFixed(1)}%
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-xl p-6 shadow-lg border-l-4 border-blue-500">
                <div class="text-center">
                    <div class="text-xs text-gray-500 uppercase tracking-wide mb-2">运行天数</div>
                    <div class="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                        ${uptime.toFixed(1)}
                    </div>
                </div>
            </div>
        `;
    }

    renderResourceBars(cpu, mem, diskMax) {
        const bars = document.getElementById('bars');
        
        bars.innerHTML = `
            <div class="space-y-6">
                <div>
                    <div class="flex justify-between items-center mb-2">
                        <span class="text-sm text-gray-600">CPU 使用率</span>
                        <span class="text-sm font-medium text-gray-900">${Utils.formatPct(cpu)}</span>
                    </div>
                    <div class="w-full bg-gray-200 rounded-full h-4">
                        <div class="h-4 rounded-full transition-all duration-500 ${Utils.getProgressBarClass(cpu)}" 
                             style="width: ${cpu}%"></div>
                    </div>
                </div>
                
                <div>
                    <div class="flex justify-between items-center mb-2">
                        <span class="text-sm text-gray-600">内存 使用率</span>
                        <span class="text-sm font-medium text-gray-900">${Utils.formatPct(mem)}</span>
                    </div>
                    <div class="w-full bg-gray-200 rounded-full h-4">
                        <div class="h-4 rounded-full transition-all duration-500 ${Utils.getProgressBarClass(mem)}" 
                             style="width: ${mem}%"></div>
                    </div>
                </div>
                
                <div>
                    <div class="flex justify-between items-center mb-2">
                        <span class="text-sm text-gray-600">磁盘 使用率(最大分区)</span>
                        <span class="text-sm font-medium text-gray-900">${Utils.formatPct(diskMax)}</span>
                    </div>
                    <div class="w-full bg-gray-200 rounded-full h-4">
                        <div class="h-4 rounded-full transition-all duration-500 ${Utils.getProgressBarClass(diskMax)}" 
                             style="width: ${diskMax}%"></div>
                    </div>
                </div>
            </div>
        `;
    }

    renderBasicInfo(instance, hostname, cores, memGb, uptime) {
        const kv = document.getElementById('kv');
        
        kv.innerHTML = `
            <div class="flex justify-between items-center py-3 border-b border-dashed border-gray-200">
                <span class="text-gray-600">实例</span>
                <span class="font-semibold text-gray-900">${instance}</span>
            </div>
            <div class="flex justify-between items-center py-3 border-b border-dashed border-gray-200">
                <span class="text-gray-600">主机名</span>
                <span class="font-semibold text-gray-900">${hostname || '无'}</span>
            </div>
            <div class="flex justify-between items-center py-3 border-b border-dashed border-gray-200">
                <span class="text-gray-600">CPU 核心</span>
                <span class="font-semibold text-gray-900">${cores}</span>
            </div>
            <div class="flex justify-between items-center py-3 border-b border-dashed border-gray-200">
                <span class="text-gray-600">总内存</span>
                <span class="font-semibold text-gray-900">${memGb} GB</span>
            </div>
            <div class="flex justify-between items-center py-3">
                <span class="text-gray-600">运行时间</span>
                <span class="font-semibold text-gray-900">${uptime.toFixed(1)} 天</span>
            </div>
        `;
    }

    renderDiskPartitions(partitions) {
        const tbody = document.getElementById('disk-tbody');
        
        if (!partitions.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="px-4 py-8 text-center text-gray-500">
                        <i class="bi bi-inbox text-2xl mb-2"></i>
                        <div>暂无磁盘分区数据</div>
                    </td>
                </tr>
            `;
            return;
        }

        const rows = partitions.map(partition => {
            const usage = Number(partition.usage_percent || 0);
            return `
                <tr class="hover:bg-gray-50">
                    <td class="px-4 py-3">
                        <code class="bg-gray-100 px-2 py-1 rounded text-sm">
                            ${partition.mountpoint || partition.device || '-'}
                        </code>
                    </td>
                    <td class="px-4 py-3 text-gray-900">
                        ${partition.device || ''}
                    </td>
                    <td class="px-4 py-3" style="width: 40%">
                        <div class="flex items-center space-x-3">
                            <div class="flex-1">
                                <div class="w-full bg-gray-200 rounded-full h-3">
                                    <div class="h-3 rounded-full transition-all duration-300 ${Utils.getProgressBarClass(usage)}" 
                                         style="width: ${usage}%"></div>
                                </div>
                            </div>
                            <span class="text-sm font-medium text-gray-900 min-w-0">
                                ${Utils.formatPct(usage)}
                            </span>
                        </div>
                    </td>
                    <td class="px-4 py-3 text-gray-600">
                        ${partition.fs_type || ''}
                    </td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
    }

    renderError(message) {
        document.getElementById('content').innerHTML = `
            <div class="flex items-center justify-center py-12 text-red-500">
                <div class="text-center">
                    <i class="bi bi-exclamation-triangle text-4xl mb-3"></i>
                    <div class="text-lg">${message}</div>
                </div>
            </div>
        `;
        document.getElementById('content').classList.remove('hidden');
    }
}

// 初始化应用
function initializeServerDetailApp() {
    const uiManager = new ServerDetailUIManager();
    uiManager.init();

    // 全局变量，便于调试
    window.ServerDetailUI = uiManager;
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initializeServerDetailApp);