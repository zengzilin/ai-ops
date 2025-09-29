/**
 * AI-Ops 日志类型分析页面 - Tailwind CSS版本
 */

class LogTypesDashboard {
    constructor() {
        this.cache = new Map();
        this.cacheTimeout = 30000; // 30秒缓存过期
        this.lastRequestTime = 0;
        this.minRequestInterval = 5000; // 最小请求间隔5秒
        this.data = null;
        this.localCacheTTL = 60000; // 本地缓存TTL 60秒
        this.autoRefreshInterval = null;
        
        this.init();
    }

    async init() {
        await this.loadData();
        this.setupEventListeners();
        this.renderDashboard();
        this.startAutoRefresh();
    }

    async loadData() {
        try {
            // 优先尝试从本地持久缓存读取
            const localKey = this.getCacheKey();
            const localCached = this.getLocalCachedData(localKey);
            if (localCached) {
                this.data = localCached;
                setTimeout(() => {
                    this.refreshData();
                }, 0);
                return;
            }
            
            // 检查缓存
            const cacheKey = this.getCacheKey();
            const cachedData = this.getCachedData(cacheKey);
            
            if (cachedData) {
                this.data = cachedData;
                return;
            }

            // 检查请求频率限制
            const now = Date.now();
            if (now - this.lastRequestTime < this.minRequestInterval) {
                return;
            }

            // 根据页面时间范围获取数据
            const timeRangeElement = document.getElementById('timeRange');
            const minutes = timeRangeElement && timeRangeElement.value ? parseInt(timeRangeElement.value) : 1;
            const response = await axios.get(`/api/log-recent-analysis?minutes=${minutes}&include_details=true`);
            
            this.data = response.data || {};
            
            // 确保必要字段存在
            this.data = {
                total_logs: this.data.total_logs || 0,
                cleaned_logs_count: this.data.cleaned_logs_count || 0,
                time_range: this.data.time_range || '最近1分钟',
                processing_status: this.data.processing_status || 'unknown',
                business_modules: this.data.business_modules || {},
                error_categories: this.data.error_categories || {},
                error_types: this.data.error_types || {},
                severity_distribution: this.data.severity_distribution || {},
                recent_errors: this.data.recent_errors || [],
                cleaning_summary: this.data.cleaning_summary || {}
            };
            
            // 更新缓存和请求时间
            this.setCachedData(cacheKey, this.data);
            this.lastRequestTime = now;
            this.setLocalCachedData(cacheKey, this.data);
            
        } catch (error) {
            console.error('加载数据失败:', error);
            const fallback = this.getLocalCachedData(this.getCacheKey(), true);
            if (fallback) {
                this.data = fallback;
            } else {
                this.showError(`数据加载失败: ${error.message}`);
                this.data = {
                    total_logs: 0,
                    cleaned_logs_count: 0,
                    time_range: '最近1分钟',
                    processing_status: 'error',
                    business_modules: {},
                    error_categories: {},
                    error_types: {},
                    severity_distribution: {},
                    recent_errors: [],
                    cleaning_summary: {}
                };
            }
        }
    }

    getCacheKey() {
        const timeRange = document.getElementById('timeRange')?.value || '1';
        return `log-types-${timeRange}`;
    }

    getCachedData(key) {
        const cached = this.cache.get(key);
        if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
            return cached.data;
        }
        return null;
    }

    setCachedData(key, data) {
        this.cache.set(key, {
            data: data,
            timestamp: Date.now()
        });
    }

    getLocalCachedData(key, allowStale = false) {
        try {
            const cached = localStorage.getItem(key);
            if (cached) {
                const parsed = JSON.parse(cached);
                if (allowStale || Date.now() - parsed.timestamp < this.localCacheTTL) {
                    return parsed.data;
                }
            }
        } catch (e) {
            console.warn('读取本地缓存失败:', e);
        }
        return null;
    }

    setLocalCachedData(key, data) {
        try {
            localStorage.setItem(key, JSON.stringify({
                data: data,
                timestamp: Date.now()
            }));
        } catch (e) {
            console.warn('写入本地缓存失败:', e);
        }
    }

    setupEventListeners() {
        // 刷新按钮
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.refreshData();
            });
        }

        // 时间范围选择
        const timeRange = document.getElementById('timeRange');
        if (timeRange) {
            timeRange.addEventListener('change', () => {
                this.refreshData();
            });
        }

        // 自动刷新开关
        const autoRefresh = document.getElementById('autoRefresh');
        if (autoRefresh) {
            autoRefresh.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.startAutoRefresh();
                } else {
                    this.stopAutoRefresh();
                }
                this.updateToggleStyle(e.target);
            });
            this.updateToggleStyle(autoRefresh);
        }
    }

    updateToggleStyle(checkbox) {
        const toggle = checkbox.parentElement.querySelector('div');
        if (checkbox.checked) {
            toggle.classList.add('bg-blue-600');
            toggle.classList.remove('bg-gray-600');
        } else {
            toggle.classList.add('bg-gray-600');
            toggle.classList.remove('bg-blue-600');
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        this.autoRefreshInterval = setInterval(() => {
            this.refreshData();
        }, 30000); // 30秒自动刷新
    }

    stopAutoRefresh() {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
        }
    }

    async refreshData() {
        // 清除缓存强制刷新
        this.cache.clear();
        await this.loadData();
        this.renderDashboard();
        this.updateLastUpdateTime();
    }

    updateLastUpdateTime() {
        const lastUpdate = document.getElementById('lastUpdate');
        if (lastUpdate) {
            lastUpdate.textContent = `最后更新: ${new Date().toLocaleTimeString()}`;
        }
    }

    renderDashboard() {
        if (!this.data) return;
        
        this.renderSummaryCards();
        this.renderCleaningStats();
        this.renderRecentErrors();
        this.renderTypeDistribution();
        this.renderErrorDetails();
        this.updateLastUpdateTime();
    }

    renderSummaryCards() {
        const container = document.getElementById('summaryCards');
        if (!container) return;

        const totalLogs = this.data.total_logs || 0;
        const cleanedLogs = this.data.cleaned_logs_count || 0;
        const errorCount = this.data.recent_errors?.length || 0;
        const processingStatus = this.data.processing_status || 'unknown';

        const cards = [
            {
                title: '总日志数',
                value: totalLogs.toLocaleString(),
                icon: 'bi-file-text',
                color: 'blue'
            },
            {
                title: '清洗后日志',
                value: cleanedLogs.toLocaleString(),
                icon: 'bi-funnel',
                color: 'green'
            },
            {
                title: '错误数量',
                value: errorCount.toLocaleString(),
                icon: 'bi-exclamation-triangle',
                color: errorCount > 0 ? 'red' : 'gray'
            },
            {
                title: '处理状态',
                value: this.getStatusText(processingStatus),
                icon: this.getStatusIcon(processingStatus),
                color: this.getStatusColor(processingStatus)
            }
        ];

        container.innerHTML = cards.map(card => `
            <div class="bg-white rounded-xl p-6 shadow-lg border-l-4 border-${card.color}-500 hover:shadow-xl transition-shadow">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-sm text-gray-600 mb-1">${card.title}</p>
                        <p class="text-2xl font-bold text-gray-900">${card.value}</p>
                    </div>
                    <div class="text-3xl text-${card.color}-500">
                        <i class="${card.icon}"></i>
                    </div>
                </div>
            </div>
        `).join('');
    }

    renderCleaningStats() {
        const container = document.getElementById('cleaningStats');
        if (!container || !this.data.cleaning_summary) return;

        const summary = this.data.cleaning_summary;
        const cards = [];

        if (summary.filtered_count !== undefined) {
            cards.push({
                title: '过滤日志数',
                value: summary.filtered_count.toLocaleString(),
                subtitle: '已过滤的重复或无效日志',
                icon: 'bi-filter',
                color: 'yellow'
            });
        }

        if (summary.categorized_count !== undefined) {
            cards.push({
                title: '分类日志数',
                value: summary.categorized_count.toLocaleString(),
                subtitle: '已成功分类的日志',
                icon: 'bi-tags',
                color: 'purple'
            });
        }

        container.innerHTML = cards.map(card => `
            <div class="bg-white rounded-xl p-6 shadow-lg">
                <div class="flex items-center justify-between mb-4">
                    <h4 class="text-lg font-semibold text-gray-900">${card.title}</h4>
                    <i class="${card.icon} text-2xl text-${card.color}-500"></i>
                </div>
                <div class="text-3xl font-bold text-${card.color}-600 mb-2">${card.value}</div>
                <p class="text-sm text-gray-600">${card.subtitle}</p>
            </div>
        `).join('');
    }

    renderRecentErrors() {
        const container = document.getElementById('recentErrors');
        if (!container) return;

        const errors = this.data.recent_errors || [];
        
        if (errors.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8 text-gray-500">
                    <i class="bi bi-check-circle text-4xl mb-3 text-green-500"></i>
                    <p class="text-lg">暂无错误日志</p>
                </div>
            `;
            return;
        }

        const tableHTML = `
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">时间</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">级别</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">实例</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">消息</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        ${errors.slice(0, 10).map(error => `
                            <tr class="hover:bg-gray-50">
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    ${this.formatTime(error.timestamp)}
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="px-2 py-1 text-xs font-medium rounded-full ${this.getSeverityBadgeClass(error.level)}">
                                        ${this.getSeverityLabel(error.level)}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    <code class="bg-gray-100 px-2 py-1 rounded text-xs">${error.instance || '-'}</code>
                                </td>
                                <td class="px-6 py-4 text-sm text-gray-900">
                                    <div class="max-w-md truncate" title="${this.escapeHtml(error.message)}">
                                        ${this.truncateMessage(error.message, 80)}
                                    </div>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        container.innerHTML = tableHTML;
    }

    renderTypeDistribution() {
        const container = document.getElementById('typeDistribution');
        if (!container) return;

        const types = this.data.error_types || {};
        const categories = this.data.error_categories || {};
        
        if (Object.keys(types).length === 0 && Object.keys(categories).length === 0) {
            container.innerHTML = `
                <div class="text-center py-8 text-gray-500">
                    <i class="bi bi-pie-chart text-4xl mb-3"></i>
                    <p class="text-lg">暂无类型分布数据</p>
                </div>
            `;
            return;
        }

        const typeRows = Object.entries(types).map(([type, count]) => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${type}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${count}</td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="w-full bg-gray-200 rounded-full h-2">
                        <div class="bg-blue-600 h-2 rounded-full" style="width: ${this.getPercentage(count, types)}%"></div>
                    </div>
                </td>
            </tr>
        `).join('');

        container.innerHTML = `
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">类型</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">数量</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">占比</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        ${typeRows}
                    </tbody>
                </table>
            </div>
        `;
    }

    renderErrorDetails() {
        const container = document.getElementById('errorDetails');
        if (!container) return;

        const errors = this.data.recent_errors || [];
        
        if (errors.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8 text-gray-500">
                    <i class="bi bi-inbox text-4xl mb-3"></i>
                    <p class="text-lg">暂无详细错误信息</p>
                </div>
            `;
            return;
        }

        const tableHTML = `
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">时间</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">级别</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">实例</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">类别</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">详细信息</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        ${errors.map(error => `
                            <tr class="hover:bg-gray-50">
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    ${this.formatTime(error.timestamp)}
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="px-2 py-1 text-xs font-medium rounded-full ${this.getSeverityBadgeClass(error.level)}">
                                        ${this.getSeverityLabel(error.level)}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    <code class="bg-gray-100 px-2 py-1 rounded text-xs">${error.instance || '-'}</code>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    ${error.category || '-'}
                                </td>
                                <td class="px-6 py-4 text-sm text-gray-900">
                                    <div class="max-w-lg" title="${this.escapeHtml(error.message)}">
                                        ${this.escapeHtml(error.message)}
                                    </div>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        container.innerHTML = tableHTML;
    }

    getPercentage(value, obj) {
        const total = Object.values(obj).reduce((sum, val) => sum + val, 0);
        return total > 0 ? ((value / total) * 100).toFixed(1) : 0;
    }

    getStatusText(status) {
        const statusMap = {
            'success': '正常',
            'processing': '处理中',
            'error': '错误',
            'warning': '警告',
            'unknown': '未知'
        };
        return statusMap[status] || status;
    }

    getStatusIcon(status) {
        const iconMap = {
            'success': 'bi-check-circle',
            'processing': 'bi-arrow-clockwise',
            'error': 'bi-x-circle',
            'warning': 'bi-exclamation-triangle',
            'unknown': 'bi-question-circle'
        };
        return iconMap[status] || 'bi-question-circle';
    }

    getStatusColor(status) {
        const colorMap = {
            'success': 'green',
            'processing': 'blue',
            'error': 'red',
            'warning': 'yellow',
            'unknown': 'gray'
        };
        return colorMap[status] || 'gray';
    }

    getSeverityLabel(severity) {
        const labelMap = {
            'error': '错误',
            'warning': '警告',
            'info': '信息',
            'debug': '调试'
        };
        return labelMap[severity] || severity;
    }

    getSeverityBadgeClass(severity) {
        const classMap = {
            'error': 'bg-red-100 text-red-800',
            'warning': 'bg-yellow-100 text-yellow-800',
            'info': 'bg-blue-100 text-blue-800',
            'debug': 'bg-gray-100 text-gray-800'
        };
        return classMap[severity] || 'bg-gray-100 text-gray-800';
    }

    formatTime(timestamp) {
        if (!timestamp) return '-';
        try {
            return new Date(timestamp).toLocaleString('zh-CN');
        } catch (e) {
            return timestamp;
        }
    }

    truncateMessage(message, maxLength = 100) {
        if (!message) return '';
        return message.length > maxLength ? message.substring(0, maxLength) + '...' : message;
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    showError(message) {
        const container = document.getElementById('summaryCards');
        if (container) {
            container.innerHTML = `
                <div class="col-span-full bg-red-50 border border-red-200 rounded-xl p-6 text-center">
                    <i class="bi bi-exclamation-triangle text-4xl text-red-500 mb-3"></i>
                    <p class="text-red-700 text-lg">${message}</p>
                </div>
            `;
        }
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    const dashboard = new LogTypesDashboard();
    
    // 全局变量，便于调试
    window.LogTypesDashboard = dashboard;
    
    // 页面卸载时清理定时器
    window.addEventListener('beforeunload', () => {
        dashboard.stopAutoRefresh();
    });
});