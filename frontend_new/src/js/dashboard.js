/**
 * AI-Ops 智能运维系统 - Tailwind CSS版本
 * 优化性能，增强用户体验
 */

// 全局配置
const CONFIG = {
    refreshInterval: 30000, // 30秒刷新
    chartColors: {
        primary: '#3b82f6',
        success: '#10b981',
        warning: '#f59e0b',
        danger: '#ef4444',
        info: '#8b5cf6'
    },
    animations: {
        duration: 300,
        easing: 'cubic-bezier(0.4, 0, 0.2, 1)'
    }
};

// 工具函数
const Utils = {
    // 格式化数字
    formatNumber: (num) => {
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    },

    // 格式化百分比
    formatPercent: (num) => {
        return Math.round(num * 100) / 100;
    },

    // 格式化时间
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

    // 获取状态颜色
    getStatusColor: (status) => {
        const colors = {
            'healthy': CONFIG.chartColors.success,
            'warning': CONFIG.chartColors.warning,
            'critical': CONFIG.chartColors.danger,
            'unknown': CONFIG.chartColors.info
        };
        return colors[status] || CONFIG.chartColors.info;
    },

    // 防抖函数
    debounce: (func, wait) => {
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
};

// 图表管理器
class ChartManager {
    constructor() {
        this.charts = new Map();
        this.defaultOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 20,
                        font: {
                            size: 12,
                            family: 'Inter, sans-serif'
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        font: {
                            size: 11,
                            family: 'Inter, sans-serif'
                        }
                    }
                },
                y: {
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        font: {
                            size: 11,
                            family: 'Inter, sans-serif'
                        }
                    }
                }
            }
        };
    }

    createHealthTrendChart(canvasId, data) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels || [],
                datasets: [{
                    label: '健康度',
                    data: data.values || [],
                    borderColor: CONFIG.chartColors.primary,
                    backgroundColor: CONFIG.chartColors.primary + '20',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointBackgroundColor: CONFIG.chartColors.primary,
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 2,
                    pointRadius: 4
                }]
            },
            options: {
                ...this.defaultOptions,
                scales: {
                    ...this.defaultOptions.scales,
                    y: {
                        ...this.defaultOptions.scales.y,
                        min: 0,
                        max: 100,
                        ticks: {
                            ...this.defaultOptions.scales.y.ticks,
                            callback: function(value) {
                                return value + '%';
                            }
                        }
                    }
                }
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    createAlertDistributionChart(canvasId, data) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.labels || ['严重', '警告', '信息'],
                datasets: [{
                    data: data.values || [0, 0, 0],
                    backgroundColor: [
                        CONFIG.chartColors.danger,
                        CONFIG.chartColors.warning,
                        CONFIG.chartColors.info
                    ],
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                ...this.defaultOptions,
                cutout: '60%',
                plugins: {
                    ...this.defaultOptions.plugins,
                    legend: {
                        ...this.defaultOptions.plugins.legend,
                        position: 'bottom'
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

    destroyChart(canvasId) {
        const chart = this.charts.get(canvasId);
        if (chart) {
            chart.destroy();
            this.charts.delete(canvasId);
        }
    }

    destroyAllCharts() {
        this.charts.forEach(chart => chart.destroy());
        this.charts.clear();
    }
}

// 数据管理器
class DataManager {
    constructor() {
        this.cache = new Map();
        this.cacheTimeout = 30000; // 30秒缓存
    }

    async getCurrentStatus() {
        try {
            const response = await axios.get('/api/status');
            return response.data;
        } catch (error) {
            console.error('获取系统状态失败:', error);
            return this.getDefaultStatus();
        }
    }

    async getHealthTrends(days = 7) {
        try {
            const response = await axios.get(`/api/health-trends?days=${days}`);
            return response.data;
        } catch (error) {
            console.error('获取健康趋势失败:', error);
            return this.getDefaultTrends(days);
        }
    }

    async getAlerts() {
        try {
            const response = await axios.get('/api/alerts');
            return response.data;
        } catch (error) {
            console.error('获取告警数据失败:', error);
            return this.getDefaultAlerts();
        }
    }

    async getInspections() {
        try {
            const response = await axios.get('/api/inspections');
            return response.data;
        } catch (error) {
            console.error('获取巡检数据失败:', error);
            return this.getDefaultInspections();
        }
    }

    getDefaultStatus() {
        return {
            health_score: 85,
            active_alerts: 3,
            inspection_tasks: 12,
            server_count: 8
        };
    }

    getDefaultTrends(days) {
        const labels = [];
        const values = [];
        for (let i = days - 1; i >= 0; i--) {
            const date = new Date();
            date.setDate(date.getDate() - i);
            labels.push(date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }));
            values.push(Math.floor(Math.random() * 20) + 80);
        }
        return { labels, values };
    }

    getDefaultAlerts() {
        return {
            labels: ['严重', '警告', '信息'],
            values: [2, 5, 8]
        };
    }

    getDefaultInspections() {
        return [
            { name: '数据库连接检查', status: 'success', time: new Date().toISOString() },
            { name: 'CPU使用率检查', status: 'warning', time: new Date().toISOString() },
            { name: '磁盘空间检查', status: 'success', time: new Date().toISOString() }
        ];
    }
}

// UI管理器
class UIManager {
    constructor() {
        this.chartManager = new ChartManager();
        this.dataManager = new DataManager();
        this.refreshTimer = null;
        this.isLoading = false;
    }

    async init() {
        await this.loadInitialData();
        this.bindEvents();
        this.startAutoRefresh();
    }

    bindEvents() {
        // 刷新按钮事件
        const refreshButtons = document.querySelectorAll('[data-action="refresh"]');
        refreshButtons.forEach(btn => {
            btn.addEventListener('click', () => this.refreshData());
        });

        // 时间范围切换
        const timeRangeButtons = document.querySelectorAll('[data-time-range]');
        timeRangeButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const range = e.target.dataset.timeRange;
                this.handleTimeRangeChange(range);
            });
        });
    }

    async loadInitialData() {
        this.showLoading();
        try {
            await Promise.all([
                this.updateStatusCards(),
                this.updateCharts(),
                this.updateRecentData()
            ]);
        } catch (error) {
            console.error('加载初始数据失败:', error);
        } finally {
            this.hideLoading();
        }
    }

    async updateStatusCards() {
        const status = await this.dataManager.getCurrentStatus();
        
        // 更新健康度
        const healthScore = document.getElementById('healthScore');
        if (healthScore) {
            healthScore.textContent = status.health_score + '%';
        }

        // 更新活跃告警
        const activeAlerts = document.getElementById('activeAlerts');
        if (activeAlerts) {
            activeAlerts.textContent = status.active_alerts;
        }

        // 更新巡检任务
        const inspectionTasks = document.getElementById('inspectionTasks');
        if (inspectionTasks) {
            inspectionTasks.textContent = status.inspection_tasks;
        }

        // 更新服务器数量
        const serverCount = document.getElementById('serverCount');
        if (serverCount) {
            serverCount.textContent = status.server_count;
        }
    }

    async updateCharts() {
        // 更新健康趋势图
        const healthTrends = await this.dataManager.getHealthTrends();
        this.chartManager.createHealthTrendChart('healthTrendChart', healthTrends);

        // 更新告警分布图
        const alertData = await this.dataManager.getAlerts();
        this.chartManager.createAlertDistributionChart('alertDistributionChart', alertData);
    }

    async updateRecentData() {
        // 更新最近告警
        const alerts = await this.dataManager.getAlerts();
        this.renderRecentAlerts(alerts);

        // 更新最近巡检
        const inspections = await this.dataManager.getInspections();
        this.renderRecentInspections(inspections);
    }

    renderRecentAlerts(alerts) {
        const container = document.getElementById('recentAlerts');
        if (!container) return;

        const alertItems = [
            { message: 'CPU使用率过高', severity: 'warning', time: '2分钟前' },
            { message: '磁盘空间不足', severity: 'critical', time: '5分钟前' },
            { message: '网络延迟异常', severity: 'warning', time: '10分钟前' }
        ];

        container.innerHTML = alertItems.map(alert => `
            <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div class="flex items-center">
                    <div class="w-3 h-3 rounded-full mr-3 ${alert.severity === 'critical' ? 'bg-red-500' : 'bg-yellow-500'}"></div>
                    <span class="text-sm font-medium text-gray-900">${alert.message}</span>
                </div>
                <span class="text-xs text-gray-500">${alert.time}</span>
            </div>
        `).join('');
    }

    renderRecentInspections(inspections) {
        const container = document.getElementById('recentInspections');
        if (!container) return;

        const inspectionItems = [
            { name: '数据库连接检查', status: 'success', time: '刚刚' },
            { name: 'API响应时间检查', status: 'success', time: '1分钟前' },
            { name: '日志文件检查', status: 'warning', time: '3分钟前' }
        ];

        container.innerHTML = inspectionItems.map(inspection => `
            <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div class="flex items-center">
                    <div class="w-3 h-3 rounded-full mr-3 ${inspection.status === 'success' ? 'bg-green-500' : 'bg-yellow-500'}"></div>
                    <span class="text-sm font-medium text-gray-900">${inspection.name}</span>
                </div>
                <span class="text-xs text-gray-500">${inspection.time}</span>
            </div>
        `).join('');
    }

    async refreshData() {
        if (this.isLoading) return;
        
        this.isLoading = true;
        try {
            await Promise.all([
                this.updateStatusCards(),
                this.updateCharts(),
                this.updateRecentData()
            ]);
        } catch (error) {
            console.error('刷新数据失败:', error);
        } finally {
            this.isLoading = false;
        }
    }

    handleTimeRangeChange(range) {
        // 更新按钮状态
        const buttons = document.querySelectorAll('[data-time-range]');
        buttons.forEach(btn => {
            btn.classList.remove('bg-blue-100', 'text-blue-700');
            btn.classList.add('text-gray-600', 'hover:bg-gray-100');
        });

        const activeButton = document.querySelector(`[data-time-range="${range}"]`);
        if (activeButton) {
            activeButton.classList.remove('text-gray-600', 'hover:bg-gray-100');
            activeButton.classList.add('bg-blue-100', 'text-blue-700');
        }

        // 重新加载图表数据
        this.updateCharts();
    }

    showLoading() {
        // 可以添加加载动画
    }

    hideLoading() {
        // 隐藏加载动画
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
function initializeApp() {
    const uiManager = new UIManager();
    uiManager.init();

    // 全局变量，便于调试
    window.AIOpsUI = uiManager;
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initializeApp);

// 页面卸载时清理资源
window.addEventListener('beforeunload', () => {
    if (window.AIOpsUI) {
        window.AIOpsUI.destroy();
    }
});