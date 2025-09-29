/**
 * AI-Ops 巡检报告页面 - Tailwind CSS版本
 */

// 全局配置
const CONFIG = {
    refreshInterval: 30000,
    pageSize: 20,
    chartColors: {
        primary: '#3b82f6',
        success: '#10b981',
        warning: '#f59e0b',
        danger: '#ef4444',
        info: '#8b5cf6'
    }
};

// 工具函数
const Utils = {
    formatTime: (timestamp) => {
        const date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    },

    formatStatus: (status) => {
        const statusMap = {
            'ok': { text: '正常', class: 'badge-success' },
            'alert': { text: '告警', class: 'badge-warning' },
            'error': { text: '错误', class: 'badge-danger' },
            'unknown': { text: '未知', class: 'badge-info' }
        };
        return statusMap[status] || statusMap['unknown'];
    },

    formatCategory: (category) => {
        const categoryMap = {
            'system': '系统检查',
            'database': '数据库检查',
            'network': '网络检查',
            'application': '应用检查'
        };
        return categoryMap[category] || category;
    },

    formatScore: (score) => {
        if (score === null || score === undefined) return '--';
        return Math.round(score * 100) / 100;
    }
};

// 图表管理器
class ReportsChartManager {
    constructor() {
        this.charts = new Map();
    }

    createInspectionTrendChart(canvasId, data) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels || [],
                datasets: [{
                    label: '巡检次数',
                    data: data.values || [],
                    borderColor: CONFIG.chartColors.primary,
                    backgroundColor: CONFIG.chartColors.primary + '20',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    x: {
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        }
                    },
                    y: {
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        },
                        beginAtZero: true
                    }
                }
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    createStatusDistributionChart(canvasId, data) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['正常', '告警', '错误'],
                datasets: [{
                    data: data.values || [0, 0, 0],
                    backgroundColor: [
                        CONFIG.chartColors.success,
                        CONFIG.chartColors.warning,
                        CONFIG.chartColors.danger
                    ],
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true
                        }
                    }
                }
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    updateChart(canvasId, newData) {
        const chart = this.charts.get(canvasId);
        if (chart && newData) {
            chart.data = newData;
            chart.update('active');
        }
    }

    destroyAllCharts() {
        this.charts.forEach(chart => chart.destroy());
        this.charts.clear();
    }
}

// 数据管理器
class ReportsDataManager {
    constructor() {
        this.currentPage = 1;
        this.currentFilters = {
            timeRange: '7d',
            status: 'all',
            type: 'all',
            search: ''
        };
    }

    async getInspectionStats() {
        try {
            const response = await axios.get('/api/inspection-stats');
            return response.data;
        } catch (error) {
            console.error('获取巡检统计失败:', error);
            return this.getDefaultStats();
        }
    }

    async getInspectionTrends() {
        try {
            const response = await axios.get(`/api/inspection-trends?days=${this.currentFilters.timeRange.replace('d', '')}`);
            return response.data;
        } catch (error) {
            console.error('获取巡检趋势失败:', error);
            return this.getDefaultTrends();
        }
    }

    async getInspectionList(page = 1) {
        try {
            const params = new URLSearchParams({
                page: page,
                page_size: CONFIG.pageSize,
                time_range: this.currentFilters.timeRange,
                status: this.currentFilters.status,
                type: this.currentFilters.type,
                search: this.currentFilters.search
            });

            const response = await axios.get(`/api/inspections?${params}`);
            return response.data;
        } catch (error) {
            console.error('获取巡检列表失败:', error);
            return this.getDefaultList();
        }
    }

    getDefaultStats() {
        return {
            total: 1250,
            normal: 1100,
            warning: 120,
            error: 30
        };
    }

    getDefaultTrends() {
        const labels = [];
        const values = [];
        for (let i = 6; i >= 0; i--) {
            const date = new Date();
            date.setDate(date.getDate() - i);
            labels.push(date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }));
            values.push(Math.floor(Math.random() * 50) + 150);
        }
        return { labels, values };
    }

    getDefaultList() {
        return {
            items: [
                {
                    timestamp: new Date().toISOString(),
                    check_name: 'CPU使用率检查',
                    status: 'ok',
                    category: 'system',
                    score: 95.5,
                    detail: 'CPU使用率正常，当前使用率15%'
                },
                {
                    timestamp: new Date().toISOString(),
                    check_name: '数据库连接检查',
                    status: 'alert',
                    category: 'database',
                    score: 75.2,
                    detail: '数据库连接数较高，建议优化'
                }
            ],
            total: 2,
            page: 1,
            total_pages: 1
        };
    }

    updateFilters(filters) {
        this.currentFilters = { ...this.currentFilters, ...filters };
        this.currentPage = 1;
    }
}

// UI管理器
class ReportsUIManager {
    constructor() {
        this.chartManager = new ReportsChartManager();
        this.dataManager = new ReportsDataManager();
        this.refreshTimer = null;
        this.sortColumn = null;
        this.sortDirection = 'asc';
    }

    async init() {
        await this.loadInitialData();
        this.bindEvents();
        this.startAutoRefresh();
    }

    bindEvents() {
        // 时间范围切换
        const timeRangeButtons = document.querySelectorAll('[data-range]');
        timeRangeButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.handleTimeRangeChange(e.target.dataset.range);
            });
        });

        // 筛选器
        document.getElementById('status-filter')?.addEventListener('change', (e) => {
            this.dataManager.updateFilters({ status: e.target.value });
            this.refreshData();
        });

        document.getElementById('type-filter')?.addEventListener('change', (e) => {
            this.dataManager.updateFilters({ type: e.target.value });
            this.refreshData();
        });

        document.getElementById('search-input')?.addEventListener('input', (e) => {
            this.dataManager.updateFilters({ search: e.target.value });
            this.debounceRefresh();
        });

        // 刷新按钮
        document.getElementById('refresh-btn')?.addEventListener('click', () => {
            this.refreshData();
        });

        // 导出按钮
        document.getElementById('export-pdf-btn')?.addEventListener('click', () => {
            this.exportToPDF();
        });

        document.getElementById('export-excel-btn')?.addEventListener('click', () => {
            this.exportToExcel();
        });

        // 表格排序
        const sortHeaders = document.querySelectorAll('[data-sort]');
        sortHeaders.forEach(header => {
            header.addEventListener('click', (e) => {
                this.handleSort(e.target.dataset.sort);
            });
        });
    }

    async loadInitialData() {
        try {
            await Promise.all([
                this.updateStats(),
                this.updateCharts(),
                this.updateTable()
            ]);
        } catch (error) {
            console.error('加载初始数据失败:', error);
        }
    }

    async updateStats() {
        const stats = await this.dataManager.getInspectionStats();
        
        document.getElementById('totalInspections').textContent = stats.total;
        document.getElementById('normalChecks').textContent = stats.normal;
        document.getElementById('warningChecks').textContent = stats.warning;
        document.getElementById('errorChecks').textContent = stats.error;
    }

    async updateCharts() {
        // 更新趋势图
        const trends = await this.dataManager.getInspectionTrends();
        this.chartManager.createInspectionTrendChart('inspectionTrendChart', trends);

        // 更新状态分布图
        const stats = await this.dataManager.getInspectionStats();
        const distributionData = {
            values: [stats.normal, stats.warning, stats.error]
        };
        this.chartManager.createStatusDistributionChart('statusDistributionChart', distributionData);
    }

    async updateTable(page = 1) {
        const data = await this.dataManager.getInspectionList(page);
        this.renderTable(data);
        this.renderPagination(data);
    }

    renderTable(data) {
        const tbody = document.getElementById('inspectionTableBody');
        if (!tbody) return;

        tbody.innerHTML = data.items.map(item => `
            <tr class="hover:bg-gray-50">
                <td>${Utils.formatTime(item.timestamp)}</td>
                <td class="font-medium">${item.check_name}</td>
                <td>
                    <span class="badge ${Utils.formatStatus(item.status).class}">
                        ${Utils.formatStatus(item.status).text}
                    </span>
                </td>
                <td>${Utils.formatCategory(item.category)}</td>
                <td class="font-mono">${Utils.formatScore(item.score)}</td>
                <td class="max-w-xs truncate" title="${item.detail}">${item.detail}</td>
                <td>
                    <button class="text-blue-600 hover:text-blue-800 text-sm font-medium">
                        查看详情
                    </button>
                </td>
            </tr>
        `).join('');

        // 更新记录数
        document.getElementById('totalRecords').textContent = data.total;
        document.getElementById('totalCount').textContent = data.total;
    }

    renderPagination(data) {
        const pagination = document.getElementById('pagination');
        if (!pagination) return;

        const totalPages = data.total_pages;
        const currentPage = data.page;
        
        let paginationHTML = '';
        
        // 上一页
        if (currentPage > 1) {
            paginationHTML += `
                <button class="px-3 py-2 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50" data-page="${currentPage - 1}">
                    <i class="bi bi-chevron-left"></i>
                </button>
            `;
        }

        // 页码
        for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {
            paginationHTML += `
                <button class="px-3 py-2 text-sm ${i === currentPage ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'} border border-gray-300 rounded-lg" data-page="${i}">
                    ${i}
                </button>
            `;
        }

        // 下一页
        if (currentPage < totalPages) {
            paginationHTML += `
                <button class="px-3 py-2 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50" data-page="${currentPage + 1}">
                    <i class="bi bi-chevron-right"></i>
                </button>
            `;
        }

        pagination.innerHTML = paginationHTML;

        // 绑定分页事件
        pagination.querySelectorAll('[data-page]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const page = parseInt(e.target.dataset.page);
                this.updateTable(page);
            });
        });

        // 更新页面信息
        const start = (currentPage - 1) * CONFIG.pageSize + 1;
        const end = Math.min(currentPage * CONFIG.pageSize, data.total);
        document.getElementById('pageStart').textContent = start;
        document.getElementById('pageEnd').textContent = end;
    }

    handleTimeRangeChange(range) {
        // 更新按钮状态
        const buttons = document.querySelectorAll('[data-range]');
        buttons.forEach(btn => {
            btn.classList.remove('bg-blue-100', 'text-blue-700');
            btn.classList.add('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');
        });

        const activeButton = document.querySelector(`[data-range="${range}"]`);
        if (activeButton) {
            activeButton.classList.remove('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');
            activeButton.classList.add('bg-blue-100', 'text-blue-700');
        }

        // 更新数据
        this.dataManager.updateFilters({ timeRange: range });
        this.refreshData();
    }

    handleSort(column) {
        if (this.sortColumn === column) {
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortColumn = column;
            this.sortDirection = 'asc';
        }

        // 更新排序图标
        const headers = document.querySelectorAll('[data-sort]');
        headers.forEach(header => {
            const icon = header.querySelector('i');
            if (header.dataset.sort === column) {
                icon.className = this.sortDirection === 'asc' ? 'bi bi-arrow-up ml-1 text-xs' : 'bi bi-arrow-down ml-1 text-xs';
            } else {
                icon.className = 'bi bi-arrow-up-down ml-1 text-xs';
            }
        });

        this.updateTable();
    }

    async refreshData() {
        try {
            await Promise.all([
                this.updateStats(),
                this.updateCharts(),
                this.updateTable()
            ]);
        } catch (error) {
            console.error('刷新数据失败:', error);
        }
    }

    debounceRefresh = this.debounce(() => {
        this.refreshData();
    }, 500);

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    exportToPDF() {
        // 实现PDF导出功能
        console.log('导出PDF');
    }

    exportToExcel() {
        // 实现Excel导出功能
        console.log('导出Excel');
    }

    startAutoRefresh() {
        this.refreshTimer = setInterval(() => {
            this.refreshData();
        }, CONFIG.refreshInterval);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }

    destroy() {
        this.stopAutoRefresh();
        this.chartManager.destroyAllCharts();
    }
}

// 初始化应用
function initializeReportsApp() {
    const uiManager = new ReportsUIManager();
    uiManager.init();

    // 全局变量，便于调试
    window.ReportsUI = uiManager;
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initializeReportsApp);

// 页面卸载时清理资源
window.addEventListener('beforeunload', () => {
    if (window.ReportsUI) {
        window.ReportsUI.destroy();
    }
});