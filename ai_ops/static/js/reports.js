/**
 * 巡检报告页面JavaScript功能
 * 包含数据加载、图表渲染、筛选、导出等功能
 */

class InspectionReports {
    constructor() {
        this.charts = {};
        this.currentFilters = {
            timeRange: '7d',
            status: 'all',
            category: 'all',
            severity: 'all'
        };
        this.currentPage = 1;
        this.pageSize = 10;
        this.totalItems = 0;
        this.allData = [];
        this.filteredData = [];
        
        this.init();
    }

    init() {
        this.attachEventListeners();
        this.loadInitialData();
        this.initCharts();
    }

    attachEventListeners() {
        // 时间范围选择器
        document.querySelectorAll('.time-picker .btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.setTimeRange(e.target.dataset.range);
            });
        });

        // 筛选器变化
        document.getElementById('status-filter')?.addEventListener('change', (e) => {
            this.currentFilters.status = e.target.value;
            this.applyFilters();
        });

        document.getElementById('category-filter')?.addEventListener('change', (e) => {
            this.currentFilters.category = e.target.value;
            this.applyFilters();
        });

        document.getElementById('severity-filter')?.addEventListener('change', (e) => {
            this.currentFilters.severity = e.target.value;
            this.applyFilters();
        });

        // 搜索框
        document.getElementById('search-input')?.addEventListener('input', (e) => {
            this.currentFilters.search = e.target.value;
            this.debounce(() => this.applyFilters(), 300);
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

        // 分页控件
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('page-btn')) {
                const page = parseInt(e.target.dataset.page);
                this.goToPage(page);
            }
        });
    }

    setTimeRange(range) {
        this.currentFilters.timeRange = range;
        
        // 更新按钮状态
        document.querySelectorAll('.time-picker .btn').forEach(btn => {
            btn.classList.remove('active');
            if (btn.dataset.range === range) {
                btn.classList.add('active');
            }
        });

        this.loadInitialData();
    }

    async loadInitialData() {
        try {
            this.showLoading();
            
            // 并行加载多个数据源
            const [inspections, stats, trends] = await Promise.all([
                this.loadInspections(),
                this.loadStats(),
                this.loadTrends()
            ]);

            this.allData = inspections;
            this.applyFilters();
            this.updateStats(stats);
            this.updateTrends(trends);
            this.renderTable();
            
        } catch (error) {
            console.error('加载数据失败:', error);
            this.showError('加载数据失败: ' + error.message);
        } finally {
            this.hideLoading();
        }
    }

    async loadInspections() {
        const hours = this.getHoursFromRange(this.currentFilters.timeRange);
        const response = await axios.get(`/api/inspections?hours=${hours}&page=1&page_size=1000`);
        this.totalItems = response.data.total || response.data.items?.length || 0;
        return response.data.items || [];
    }

    async loadStats() {
        const days = this.getDaysFromRange(this.currentFilters.timeRange);
        const response = await axios.get(`/api/inspection-stats?days=${days}`);
        return response.data;
    }

    async loadTrends() {
        const days = this.getDaysFromRange(this.currentFilters.timeRange);
        const response = await axios.get(`/api/health-trends?days=${days}`);
        return response.data;
    }

    getHoursFromRange(range) {
        const ranges = {
            '1d': 24,
            '3d': 72,
            '7d': 168,
            '30d': 720
        };
        return ranges[range] || 168;
    }

    getDaysFromRange(range) {
        const ranges = {
            '1d': 1,
            '3d': 3,
            '7d': 7,
            '30d': 30
        };
        return ranges[range] || 7;
    }

    applyFilters() {
        let filtered = [...this.allData];

        // 状态筛选
        if (this.currentFilters.status !== 'all') {
            filtered = filtered.filter(item => item.status === this.currentFilters.status);
        }

        // 类别筛选
        if (this.currentFilters.category !== 'all') {
            filtered = filtered.filter(item => item.category === this.currentFilters.category);
        }

        // 严重程度筛选
        if (this.currentFilters.severity !== 'all') {
            filtered = filtered.filter(item => item.severity === this.currentFilters.severity);
        }

        // 搜索筛选
        if (this.currentFilters.search) {
            const searchTerm = this.currentFilters.search.toLowerCase();
            filtered = filtered.filter(item => 
                item.check_name.toLowerCase().includes(searchTerm) ||
                item.detail.toLowerCase().includes(searchTerm) ||
                (item.instance && item.instance.toLowerCase().includes(searchTerm))
            );
        }

        this.filteredData = filtered;
        this.totalItems = filtered.length;
        this.currentPage = 1;
        
        this.renderTable();
        this.updatePagination();
        this.updateSummary();
    }

    renderTable() {
        const tbody = document.getElementById('inspection-tbody');
        if (!tbody) return;

        const start = (this.currentPage - 1) * this.pageSize;
        const end = start + this.pageSize;
        const pageItems = this.filteredData.slice(start, end);

        if (pageItems.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-4">
                        <div class="empty-state">
                            <i class="bi bi-inbox"></i>
                            <p>暂无数据</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = pageItems.map(item => this.renderTableRow(item)).join('');
    }

    renderTableRow(item) {
        const statusClass = this.getStatusClass(item.status);
        const severityClass = this.getSeverityClass(item.severity);
        const statusIcon = this.getStatusIcon(item.status);
        const severityIcon = this.getSeverityIcon(item.severity);

        return `
            <tr class="fade-in">
                <td>
                    <small>${this.formatTime(item.ts)}</small>
                </td>
                <td>
                    <strong>${this.escapeHtml(item.check_name)}</strong>
                </td>
                <td>
                    <span class="status-badge ${statusClass}">
                        <i class="bi ${statusIcon}"></i>
                        ${this.getStatusText(item.status)}
                    </span>
                </td>
                <td>
                    <span class="badge bg-secondary">${item.category || '无'}</span>
                </td>
                <td>
                    <span class="status-badge ${severityClass}">
                        <i class="bi ${severityIcon}"></i>
                        ${this.getSeverityText(item.severity)}
                    </span>
                </td>
                <td>
                    <div class="progress" style="height: 20px;">
                        <div class="progress-bar ${this.getScoreClass(item.score)}" 
                             style="width: ${item.score}%" 
                             title="健康评分: ${item.score}%">
                            ${item.score}%
                        </div>
                    </div>
                </td>
                <td>
                    <small class="text-muted">${this.escapeHtml(item.detail || '无')}</small>
                </td>
            </tr>
        `;
    }

    getStatusClass(status) {
        const classes = {
            'ok': 'ok',
            'alert': 'alert',
            'error': 'error'
        };
        return classes[status] || 'info';
    }

    getSeverityClass(severity) {
        const classes = {
            'info': 'info',
            'warning': 'warning',
            'critical': 'danger'
        };
        return classes[severity] || 'info';
    }

    getStatusIcon(status) {
        const icons = {
            'ok': 'bi-check-circle',
            'alert': 'bi-exclamation-triangle',
            'error': 'bi-x-circle'
        };
        return icons[status] || 'bi-question-circle';
    }

    getSeverityIcon(severity) {
        const icons = {
            'info': 'bi-info-circle',
            'warning': 'bi-exclamation-triangle',
            'critical': 'bi-exclamation-octagon'
        };
        return icons[severity] || 'bi-info-circle';
    }

    getStatusText(status) {
        const texts = {
            'ok': '正常',
            'alert': '告警',
            'error': '错误'
        };
        return texts[status] || status;
    }

    getSeverityText(severity) {
        const texts = {
            'info': '提示',
            'warning': '警告',
            'critical': '严重'
        };
        return texts[severity] || severity;
    }

    getScoreClass(score) {
        if (score >= 80) return 'bg-success';
        if (score >= 60) return 'bg-warning';
        return 'bg-danger';
    }

    updateStats(stats) {
        if (!stats) return;

        // 更新统计卡片
        this.updateStatCard('total-inspections', stats.overall?.total_inspections || 0);
        this.updateStatCard('avg-health-score', (stats.overall?.avg_health_score || 0).toFixed(1));
        this.updateStatCard('min-health-score', (stats.overall?.min_health_score || 0).toFixed(1));
        this.updateStatCard('max-health-score', (stats.overall?.max_health_score || 0).toFixed(1));

        // 更新状态分布图表
        if (this.charts.statusChart) {
            const okCount = stats.overall?.ok_count || 0;
            const alertCount = stats.overall?.alert_count || 0;
            const errorCount = stats.overall?.error_count || 0;

            this.charts.statusChart.data.datasets[0].data = [okCount, alertCount, errorCount];
            this.charts.statusChart.update('active');
        }
    }

    updateTrends(trends) {
        if (!trends || !trends.trends) return;

        // 更新健康趋势图表
        if (this.charts.healthChart) {
            const sortedData = trends.trends.sort((a, b) => new Date(a.date) - new Date(b.date));
            const labels = sortedData.map(item => this.formatDate(item.date));
            const scores = sortedData.map(item => item.health_score);

            this.charts.healthChart.data.labels = labels;
            this.charts.healthChart.data.datasets[0].data = scores;
            this.charts.healthChart.update('active');
        }
    }

    updateStatCard(id, value) {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
        }
    }

    updateSummary() {
        const summaryElement = document.getElementById('summary-info');
        if (!summaryElement) return;

        const total = this.filteredData.length;
        const okCount = this.filteredData.filter(item => item.status === 'ok').length;
        const alertCount = this.filteredData.filter(item => item.status === 'alert').length;
        const errorCount = this.filteredData.filter(item => item.status === 'error').length;

        summaryElement.innerHTML = `
            <div class="row text-center">
                <div class="col-md-3">
                    <div class="text-primary fw-bold">${total}</div>
                    <small class="text-muted">总检查数</small>
                </div>
                <div class="col-md-3">
                    <div class="text-success fw-bold">${okCount}</div>
                    <small class="text-muted">正常</small>
                </div>
                <div class="col-md-3">
                    <div class="text-warning fw-bold">${alertCount}</div>
                    <small class="text-muted">告警</small>
                </div>
                <div class="col-md-3">
                    <div class="text-danger fw-bold">${errorCount}</div>
                    <small class="text-muted">错误</small>
                </div>
            </div>
        `;
    }

    updatePagination() {
        const paginationElement = document.getElementById('pagination');
        if (!paginationElement) return;

        const totalPages = Math.ceil(this.totalItems / this.pageSize);
        
        if (totalPages <= 1) {
            paginationElement.innerHTML = '';
            return;
        }

        let paginationHTML = `
            <div class="pagination-container">
                <div class="pagination-info">
                    共 ${this.totalItems} 条记录，每页 ${this.pageSize} 条
                </div>
                <div class="pagination-controls">
        `;

        // 上一页
        const prevDisabled = this.currentPage <= 1 ? 'disabled' : '';
        paginationHTML += `
            <button class="btn btn-outline-primary btn-sm page-btn ${prevDisabled}" 
                    data-page="${this.currentPage - 1}" ${prevDisabled}>
                <i class="bi bi-chevron-left"></i> 上一页
            </button>
        `;

        // 页码
        const startPage = Math.max(1, this.currentPage - 2);
        const endPage = Math.min(totalPages, this.currentPage + 2);

        for (let i = startPage; i <= endPage; i++) {
            const active = i === this.currentPage ? 'active' : '';
            paginationHTML += `
                <button class="btn btn-sm page-btn ${active ? 'btn-primary' : 'btn-outline-primary'}" 
                        data-page="${i}">${i}</button>
            `;
        }

        // 下一页
        const nextDisabled = this.currentPage >= totalPages ? 'disabled' : '';
        paginationHTML += `
            <button class="btn btn-outline-primary btn-sm page-btn ${nextDisabled}" 
                    data-page="${this.currentPage + 1}" ${nextDisabled}>
                下一页 <i class="bi bi-chevron-right"></i>
            </button>
        `;

        paginationHTML += '</div></div>';
        paginationElement.innerHTML = paginationHTML;
    }

    goToPage(page) {
        if (page < 1 || page > Math.ceil(this.totalItems / this.pageSize)) return;
        
        this.currentPage = page;
        this.renderTable();
        this.updatePagination();
        
        // 滚动到表格顶部
        document.getElementById('inspection-table')?.scrollIntoView({ 
            behavior: 'smooth', 
            block: 'start' 
        });
    }

    initCharts() {
        // 健康趋势图表
        const healthCtx = document.getElementById('health-trend-chart');
        if (healthCtx) {
            this.charts.healthChart = new Chart(healthCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: '健康评分',
                        data: [],
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        tension: 0.4,
                        borderWidth: 3,
                        pointBackgroundColor: '#667eea',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        pointRadius: 6,
                        pointHoverRadius: 8,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            titleColor: '#fff',
                            bodyColor: '#fff',
                            borderColor: '#667eea',
                            borderWidth: 1
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            grid: {
                                color: 'rgba(0,0,0,0.1)'
                            },
                            ticks: {
                                callback: function(value) {
                                    return value + '%';
                                }
                            }
                        },
                        x: {
                            grid: {
                                color: 'rgba(0,0,0,0.1)'
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    }
                }
            });
        }

        // 状态分布图表
        const statusCtx = document.getElementById('status-chart');
        if (statusCtx) {
            this.charts.statusChart = new Chart(statusCtx, {
                type: 'doughnut',
                data: {
                    labels: ['正常', '告警', '错误'],
                    datasets: [{
                        data: [0, 0, 0],
                        backgroundColor: ['#28a745', '#ffc107', '#dc3545'],
                        borderWidth: 0,
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                padding: 20,
                                usePointStyle: true,
                                font: {
                                    size: 12
                                }
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            titleColor: '#fff',
                            bodyColor: '#fff',
                            borderColor: '#667eea',
                            borderWidth: 1
                        }
                    }
                }
            });
        }

        // 类别分布图表
        const categoryCtx = document.getElementById('category-chart');
        if (categoryCtx) {
            this.charts.categoryChart = new Chart(categoryCtx, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: '检查数量',
                        data: [],
                        backgroundColor: 'rgba(102, 126, 234, 0.8)',
                        borderColor: '#667eea',
                        borderWidth: 1,
                        borderRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            titleColor: '#fff',
                            bodyColor: '#fff',
                            borderColor: '#667eea',
                            borderWidth: 1
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: {
                                color: 'rgba(0,0,0,0.1)'
                            }
                        },
                        x: {
                            grid: {
                                display: false
                            }
                        }
                    }
                }
            });
        }
    }

    async refreshData() {
        const refreshBtn = document.getElementById('refresh-btn');
        if (refreshBtn) {
            refreshBtn.innerHTML = '<div class="loading-spinner"></div> 刷新中...';
            refreshBtn.disabled = true;
        }

        try {
            await this.loadInitialData();
            this.showSuccess('数据刷新成功');
        } catch (error) {
            console.error('刷新数据失败:', error);
            this.showError('刷新数据失败: ' + error.message);
        } finally {
            if (refreshBtn) {
                refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> 刷新';
                refreshBtn.disabled = false;
            }
        }
    }

    async exportToPDF() {
        try {
            this.showLoading('正在生成PDF报告...');
            
            // 这里可以集成jsPDF或其他PDF生成库
            // 暂时使用浏览器打印功能
            window.print();
            
            this.showSuccess('PDF报告生成成功');
        } catch (error) {
            console.error('生成PDF失败:', error);
            this.showError('生成PDF失败: ' + error.message);
        } finally {
            this.hideLoading();
        }
    }

    async exportToExcel() {
        try {
            this.showLoading('正在生成Excel报告...');
            
            // 准备导出数据
            const exportData = this.filteredData.map(item => ({
                '时间': this.formatTime(item.ts),
                '检查项': item.check_name,
                '状态': this.getStatusText(item.status),
                '类别': item.category || '无',
                '严重程度': this.getSeverityText(item.severity),
                '健康评分': item.score + '%',
                '详情': item.detail || '无',
                '实例': item.instance || '无'
            }));

            // 创建CSV内容
            const headers = Object.keys(exportData[0]);
            const csvContent = [
                headers.join(','),
                ...exportData.map(row => 
                    headers.map(header => 
                        JSON.stringify(row[header] || '')
                    ).join(',')
                )
            ].join('\n');

            // 下载CSV文件
            const blob = new Blob(['\ufeff' + csvContent], { 
                type: 'text/csv;charset=utf-8;' 
            });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            link.setAttribute('download', `巡检报告_${this.formatDate(new Date())}.csv`);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showSuccess('Excel报告导出成功');
        } catch (error) {
            console.error('导出Excel失败:', error);
            this.showError('导出Excel失败: ' + error.message);
        } finally {
            this.hideLoading();
        }
    }

    // 工具方法
    formatTime(timestamp) {
        if (!timestamp) return '无';
        
        const date = new Date(timestamp);
        if (isNaN(date.getTime())) return '无效时间';
        
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    formatDate(dateString) {
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return '未知日期';
        
        return date.toLocaleDateString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

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

    showLoading(message = '加载中...') {
        const loadingElement = document.getElementById('loading-overlay');
        if (loadingElement) {
            loadingElement.style.display = 'flex';
            const messageElement = loadingElement.querySelector('.loading-message');
            if (messageElement) {
                messageElement.textContent = message;
            }
        }
    }

    hideLoading() {
        const loadingElement = document.getElementById('loading-overlay');
        if (loadingElement) {
            loadingElement.style.display = 'none';
        }
    }

    showSuccess(message) {
        this.showNotification(message, 'success');
    }

    showError(message) {
        this.showNotification(message, 'error');
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(notification);
        
        // 自动消失
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 5000);
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    // 检查必要的依赖
    if (typeof Chart === 'undefined') {
        console.error('Chart.js 未加载');
        return;
    }
    
    if (typeof axios === 'undefined') {
        console.error('Axios 未加载');
        return;
    }
    
    // 初始化巡检报告
    window.inspectionReports = new InspectionReports();
});

// 全局工具函数
window.formatTime = function(timestamp) {
    if (!timestamp) return '无';
    
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) return '无效时间';
    
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
};

window.formatDate = function(dateString) {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return '未知日期';
    
    return date.toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    });
};
