/**
 * AI-Ops 智能运维系统 - 优化版JavaScript
 * 本地化依赖，优化性能，增强用户体验
 */

// 全局配置
const CONFIG = {
    refreshInterval: 30000, // 30秒刷新
    chartColors: {
        primary: '#667eea',
        success: '#28a745',
        warning: '#ffc107',
        danger: '#dc3545',
        info: '#17a2b8'
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
    },

    // 节流函数
    throttle: (func, limit) => {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
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
                            weight: '600'
                        }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    borderColor: CONFIG.chartColors.primary,
                    borderWidth: 1,
                    cornerRadius: 8,
                    displayColors: true
                }
            },
            animation: {
                duration: CONFIG.animations.duration,
                easing: CONFIG.animations.easing
            }
        };
    }

    // 创建健康趋势图表
    createHealthTrendChart(canvasId, data) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [{
                    label: '健康评分',
                    data: data.values,
                    borderColor: CONFIG.chartColors.primary,
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointBackgroundColor: CONFIG.chartColors.primary,
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 6,
                    pointHoverRadius: 8
                }]
            },
            options: {
                ...this.defaultOptions,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
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

    // 创建资源使用图表
    createResourceChart(canvasId, data, type = 'doughnut') {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: type,
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: [
                        CONFIG.chartColors.success,
                        CONFIG.chartColors.warning,
                        CONFIG.chartColors.danger,
                        CONFIG.chartColors.info
                    ],
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                ...this.defaultOptions,
                cutout: type === 'doughnut' ? '60%' : '0%'
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    // 更新图表数据
    updateChart(canvasId, newData) {
        const chart = this.charts.get(canvasId);
        if (chart) {
            chart.data = newData;
            chart.update('active');
        }
    }

    // 销毁图表
    destroyChart(canvasId) {
        const chart = this.charts.get(canvasId);
        if (chart) {
            chart.destroy();
            this.charts.delete(canvasId);
        }
    }

    // 销毁所有图表
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

    // 获取当前状态
    async getCurrentStatus() {
        try {
            const response = await this.fetchWithCache('/api/current-status');
            return response;
        } catch (error) {
            console.error('获取当前状态失败:', error);
            return this.getDefaultStatus();
        }
    }

    // 获取健康趋势
    async getHealthTrends(days = 7) {
        try {
            const response = await this.fetchWithCache(`/api/health-trends?days=${days}`);
            return response;
        } catch (error) {
            console.error('获取健康趋势失败:', error);
            return this.getDefaultTrends(days);
        }
    }

    // 获取巡检记录
    async getInspections(hours = 24, page = 1, pageSize = 50) {
        try {
            const response = await this.fetchWithCache(`/api/inspections?hours=${hours}&page=${page}&page_size=${pageSize}`);
            return response;
        } catch (error) {
            console.error('获取巡检记录失败:', error);
            return this.getDefaultInspections();
        }
    }

    // 获取服务器资源
    async getServerResources() {
        try {
            const response = await this.fetchWithCache('/api/server-resources');
            // 适配后端API返回的数据结构
            if (response && response.data) {
                return {
                    servers: response.data,
                    count: response.count || 0,
                    timestamp: response.timestamp,
                    cache: response.cache
                };
            }
            return this.getDefaultServerResources();
        } catch (error) {
            console.error('获取服务器资源失败:', error);
            return this.getDefaultServerResources();
        }
    }

    // 获取告警信息
    async getAlerts() {
        try {
            const response = await this.fetchWithCache('/api/alerts');
            return response;
        } catch (error) {
            console.error('获取告警信息失败:', error);
            return this.getDefaultAlerts();
        }
    }

    // 带缓存的请求
    async fetchWithCache(url) {
        const cacheKey = url;
        const cached = this.cache.get(cacheKey);
        
        if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
            return cached.data;
        }

        const response = await fetch(url);
        const data = await response.json();
        
        this.cache.set(cacheKey, {
            data: data,
            timestamp: Date.now()
        });

        return data;
    }

    // 清除缓存
    clearCache() {
        this.cache.clear();
    }

    // 默认数据
    getDefaultStatus() {
        return {
            total_checks: 0,
            alert_count: 0,
            error_count: 0,
            ok_count: 0,
            health_score: 0,
            timestamp: new Date().toISOString(),
            system_status: 'unknown'
        };
    }

    getDefaultTrends(days) {
        const labels = [];
        const values = [];
        for (let i = days - 1; i >= 0; i--) {
            const date = new Date();
            date.setDate(date.getDate() - i);
            labels.push(date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }));
            values.push(Math.floor(Math.random() * 20) + 80); // 80-100之间的随机值
        }
        return { labels, values };
    }

    getDefaultInspections() {
        return {
            inspections: [],
            total: 0,
            page: 1,
            page_size: 50
        };
    }

    getDefaultServerResources() {
        return {
            servers: []
        };
    }

    getDefaultAlerts() {
        return {
            alerts: []
        };
    }
}

// UI管理器
class UIManager {
    constructor() {
        this.chartManager = new ChartManager();
        this.dataManager = new DataManager();
        this.refreshTimer = null;
        this.isLoading = false;
        this.init();
    }

    // 初始化
    init() {
        this.bindEvents();
        // 延迟加载数据，确保DOM完全加载
        setTimeout(() => {
            this.loadInitialData();
        }, 100);
        this.startAutoRefresh();
        this.addLoadingStates();
    }

    // 绑定事件
    bindEvents() {
        // 导航切换
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleNavigation(e.target.getAttribute('href'));
            });
        });

        // 刷新按钮 - 使用ID选择器
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.refreshData();
            });
        }

        // 时间范围选择
        const timeRangeSelect = document.getElementById('timeRange');
        if (timeRangeSelect) {
            timeRangeSelect.addEventListener('change', (e) => {
                this.handleTimeRangeChange(e.target.value);
            });
        }

        // 搜索功能
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', Utils.debounce((e) => {
                this.handleSearch(e.target.value);
            }, 300));
        }

        // 表格排序
        document.querySelectorAll('.sortable').forEach(header => {
            header.addEventListener('click', (e) => {
                this.handleSort(e.target);
            });
        });
    }

    // 加载初始数据
    async loadInitialData() {
        this.showLoading();
        
        try {
            await Promise.all([
                this.updateDashboard(),
                this.updateCharts()
            ]);
        } catch (error) {
            console.error('加载初始数据失败:', error);
            this.showError('加载数据失败，请刷新页面重试');
        } finally {
            this.hideLoading();
        }
    }

    // 更新仪表板
    async updateDashboard() {
        try {
            const status = await this.dataManager.getCurrentStatus();
            
            // 确保DOM元素存在后再更新
            if (document.readyState === 'complete') {
                this.updateStatusCards(status);
                this.updateHealthScore(status.health_score);
            } else {
                // 如果DOM还没完全加载，等待一下再试
                setTimeout(() => {
                    this.updateStatusCards(status);
                    this.updateHealthScore(status.health_score);
                }, 100);
            }
        } catch (error) {
            console.error('更新仪表板失败:', error);
        }
    }

    // 更新状态卡片
    updateStatusCards(status) {
        const cards = {
            'total-checks': status.total_checks,
            'alert-count': status.alert_count,
            'error-count': status.error_count
        };

        Object.entries(cards).forEach(([key, value]) => {
            const element = document.getElementById(key);
            if (element) {
                try {
                    // 确保value是数字类型
                    const numericValue = parseInt(value) || 0;
                    element.textContent = Utils.formatNumber(numericValue);
                    element.classList.add('fade-in');
                } catch (error) {
                    console.error(`更新元素 ${key} 失败:`, error);
                }
            } else {
                console.warn(`DOM元素未找到: ${key}`);
            }
        });
    }

    // 更新健康评分
    updateHealthScore(score) {
        const scoreElement = document.getElementById('healthScore');
        if (scoreElement) {
            try {
                // 确保score是数字类型
                const numericScore = parseFloat(score) || 0;
                scoreElement.textContent = Utils.formatPercent(numericScore / 100);
                
                // 根据分数设置颜色
                scoreElement.className = 'card-title';
                if (numericScore >= 90) {
                    scoreElement.classList.add('success');
                } else if (numericScore >= 70) {
                    scoreElement.classList.add('warning');
                } else {
                    scoreElement.classList.add('danger');
                }
            } catch (error) {
                console.error('更新健康评分失败:', error);
            }
        } else {
            console.warn('DOM元素未找到: healthScore');
        }
    }

    // 更新图表
    async updateCharts() {
        const healthTrends = await this.dataManager.getHealthTrends(7);
        const serverResources = await this.dataManager.getServerResources();
        
        // 健康趋势图表
        if (healthTrends.labels && healthTrends.values) {
            this.chartManager.createHealthTrendChart('healthTrendChart', healthTrends);
        }

        // 服务器资源图表
        if (serverResources.servers && serverResources.servers.length > 0) {
            const resourceData = this.processResourceData(serverResources.servers);
            this.chartManager.createResourceChart('resourceChart', resourceData, 'doughnut');
        }
    }

    // 处理资源数据
    processResourceData(servers) {
        const statusCount = {
            'healthy': 0,
            'warning': 0,
            'critical': 0,
            'unknown': 0
        };

        servers.forEach(server => {
            const status = server.status || 'unknown';
            statusCount[status]++;
        });

        return {
            labels: ['健康', '警告', '严重', '未知'],
            values: Object.values(statusCount)
        };
    }

    // 刷新数据
    async refreshData() {
        if (this.isLoading) return;
        
        this.isLoading = true;
        this.showRefreshIndicator();
        
        try {
            this.dataManager.clearCache();
            await this.loadInitialData();
            this.showSuccessMessage('数据已刷新');
        } catch (error) {
            console.error('刷新数据失败:', error);
            this.showErrorMessage('刷新失败，请重试');
        } finally {
            this.isLoading = false;
            this.hideRefreshIndicator();
        }
    }

    // ===== 手动指标查询 =====
    async queryClusterLoad() {
        const resultEl = document.querySelector('#manual-cluster-load');
        if (resultEl) resultEl.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> 查询中...</div>';
        
        try {
            const res = await fetch('/api/manual/cluster-load');
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            const data = await res.json();
            this.renderManualResult('#manual-cluster-load', data);
        } catch(e) { 
            console.error('查询集群负载失败:', e);
            if (resultEl) resultEl.innerHTML = `<div class="alert alert-danger">查询失败: ${e.message}</div>`;
        }
    }

    async queryNodeLoad(node) {
        if (!node) {
            const resultEl = document.querySelector('#manual-node-load');
            if (resultEl) resultEl.innerHTML = '<div class="alert alert-warning">请输入节点地址</div>';
            return;
        }
        
        const resultEl = document.querySelector('#manual-node-load');
        if (resultEl) resultEl.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> 查询中...</div>';
        
        try {
            const res = await fetch(`/api/manual/node-load?node=${encodeURIComponent(node)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            const data = await res.json();
            this.renderManualResult('#manual-node-load', data);
        } catch(e) { 
            console.error('查询节点负载失败:', e);
            if (resultEl) resultEl.innerHTML = `<div class="alert alert-danger">查询失败: ${e.message}</div>`;
        }
    }

    async queryPodLoad(ns, pod) {
        if (!ns || !pod) {
            const resultEl = document.querySelector('#manual-pod-load');
            if (resultEl) resultEl.innerHTML = '<div class="alert alert-warning">请输入命名空间和Pod名称</div>';
            return;
        }
        
        const resultEl = document.querySelector('#manual-pod-load');
        if (resultEl) resultEl.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> 查询中...</div>';
        
        try {
            const res = await fetch(`/api/manual/pod-load?namespace=${encodeURIComponent(ns)}&pod=${encodeURIComponent(pod)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            const data = await res.json();
            this.renderManualResult('#manual-pod-load', data);
        } catch(e) { 
            console.error('查询Pod负载失败:', e);
            if (resultEl) resultEl.innerHTML = `<div class="alert alert-danger">查询失败: ${e.message}</div>`;
        }
    }

    async queryDiskRemaining(node, mountpoint) {
        if (!node) {
            const resultEl = document.querySelector('#manual-disk-remaining');
            if (resultEl) resultEl.innerHTML = '<div class="alert alert-warning">请输入节点地址</div>';
            return;
        }
        
        const resultEl = document.querySelector('#manual-disk-remaining');
        if (resultEl) resultEl.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> 查询中...</div>';
        
        const mp = mountpoint || '/';
        try {
            const res = await fetch(`/api/manual/disk-remaining?node=${encodeURIComponent(node)}&mountpoint=${encodeURIComponent(mp)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            const data = await res.json();
            this.renderManualResult('#manual-disk-remaining', data);
        } catch(e) { 
            console.error('查询磁盘剩余失败:', e);
            if (resultEl) resultEl.innerHTML = `<div class="alert alert-danger">查询失败: ${e.message}</div>`;
        }
    }

    renderManualResult(selector, data) {
        const el = document.querySelector(selector);
        if (!el) return;
        el.innerHTML = `<pre class="small bg-light p-2 rounded border">${JSON.stringify(data, null, 2)}</pre>`;
    }

    // 处理导航
    handleNavigation(href) {
        // 移除所有活动状态
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.remove('active');
        });

        // 添加活动状态
        event.target.classList.add('active');

        // 这里可以添加页面切换逻辑
        console.log('导航到:', href);
    }

    // 处理时间范围变化
    handleTimeRangeChange(value) {
        console.log('时间范围变化:', value);
        // 根据时间范围重新加载数据
        this.updateCharts();
    }

    // 处理搜索
    handleSearch(query) {
        console.log('搜索查询:', query);
        // 实现搜索逻辑
        this.filterTableData(query);
    }

    // 处理排序
    handleSort(header) {
        const table = header.closest('table');
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const columnIndex = Array.from(header.parentElement.children).indexOf(header);
        const isAscending = header.classList.contains('asc');

        // 排序行
        rows.sort((a, b) => {
            const aValue = a.children[columnIndex].textContent;
            const bValue = b.children[columnIndex].textContent;
            
            if (isAscending) {
                return aValue.localeCompare(bValue);
            } else {
                return bValue.localeCompare(aValue);
            }
        });

        // 重新插入行
        rows.forEach(row => tbody.appendChild(row));

        // 切换排序方向
        header.classList.toggle('asc');
        header.classList.toggle('desc');
    }

    // 过滤表格数据
    filterTableData(query) {
        const tables = document.querySelectorAll('table');
        tables.forEach(table => {
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                const isVisible = text.includes(query.toLowerCase());
                row.style.display = isVisible ? '' : 'none';
            });
        });
    }

    // 显示加载状态
    showLoading() {
        document.body.classList.add('loading');
        this.showLoadingSpinner();
    }

    // 隐藏加载状态
    hideLoading() {
        document.body.classList.remove('loading');
        this.hideLoadingSpinner();
    }

    // 显示加载指示器
    showLoadingSpinner() {
        const spinner = document.createElement('div');
        spinner.className = 'loading-overlay';
        spinner.innerHTML = `
            <div class="loading-content">
                <div class="loading-spinner"></div>
                <p>加载中...</p>
            </div>
        `;
        document.body.appendChild(spinner);
    }

    // 隐藏加载指示器
    hideLoadingSpinner() {
        const spinner = document.querySelector('.loading-overlay');
        if (spinner) {
            spinner.remove();
        }
    }

    // 显示刷新指示器
    showRefreshIndicator() {
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise spin"></i> 刷新中...';
            refreshBtn.disabled = true;
        }
    }

    // 隐藏刷新指示器
    hideRefreshIndicator() {
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise me-2"></i>刷新数据';
            refreshBtn.disabled = false;
        }
    }

    // 显示成功消息
    showSuccessMessage(message) {
        this.showToast(message, 'success');
    }

    // 显示错误消息
    showErrorMessage(message) {
        this.showToast(message, 'error');
    }

    // 显示错误（别名）
    showError(message) {
        this.showErrorMessage(message);
    }

    // 显示提示消息
    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type} fade-in`;
        toast.innerHTML = `
            <div class="toast-content">
                <i class="bi bi-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
                <span>${message}</span>
            </div>
        `;

        document.body.appendChild(toast);

        // 自动移除
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // 添加加载状态
    addLoadingStates() {
        // 为所有可点击元素添加加载状态
        document.querySelectorAll('button, .btn, .nav-link').forEach(element => {
            element.addEventListener('click', function() {
                if (!this.classList.contains('no-loading')) {
                    this.classList.add('loading');
                    setTimeout(() => this.classList.remove('loading'), 1000);
                }
            });
        });
    }

    // 开始自动刷新
    startAutoRefresh() {
        this.refreshTimer = setInterval(() => {
            this.refreshData();
        }, CONFIG.refreshInterval);
    }

    // 停止自动刷新
    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }

    // 销毁
    destroy() {
        this.stopAutoRefresh();
        this.chartManager.destroyAllCharts();
        this.dataManager.clearCache();
    }
}

// 页面加载完成后初始化
function initializeApp() {
    // 检查Chart.js是否可用
    if (typeof Chart === 'undefined') {
        console.error('Chart.js 未加载，请检查网络连接或本地文件');
        return;
    }

    // 确保DOM元素存在
    const requiredElements = ['healthScore', 'total-checks', 'alert-count', 'error-count', 'refreshBtn'];
    const missingElements = requiredElements.filter(id => !document.getElementById(id));
    
    if (missingElements.length > 0) {
        console.error('缺少必需的DOM元素:', missingElements);
        // 如果缺少元素，等待一下再试
        setTimeout(initializeApp, 100);
        return;
    }

    // 初始化UI管理器
    window.uiManager = new UIManager();
    
    // 添加页面可见性变化监听
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            window.uiManager.stopAutoRefresh();
        } else {
            window.uiManager.startAutoRefresh();
        }
    });
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 延迟初始化，确保DOM完全加载
    setTimeout(initializeApp, 50);
});

// 如果DOMContentLoaded已经触发，直接初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(initializeApp, 50);
    });
} else {
    // DOM已经加载完成
    setTimeout(initializeApp, 50);
}

// 页面卸载时清理
window.addEventListener('beforeunload', () => {
    if (window.uiManager) {
        window.uiManager.destroy();
    }
});

// 导出工具函数供其他脚本使用
window.AIOpsUtils = Utils;
window.AIOpsChartManager = ChartManager;
window.AIOpsDataManager = DataManager;


