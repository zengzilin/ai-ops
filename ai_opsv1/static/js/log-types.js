// 日志类型展示页面JavaScript
class LogTypesDashboard {
    constructor() {
        // 先初始化属性，再调用init方法
        this.cache = new Map(); // 客户端缓存
        this.cacheTimeout = 30000; // 30秒缓存过期
        this.lastRequestTime = 0; // 上次请求时间
        this.minRequestInterval = 5000; // 最小请求间隔5秒
        this.data = null; // 初始化数据为null
        this.localCacheTTL = 60000; // 本地缓存TTL 60秒，避免刷新空白
        
        // 最后调用init方法
        this.init();
    }

    async init() {
        await this.loadData();
        this.setupEventListeners();
        this.renderDashboard();
    }

    async loadData() {
        try {
            // 优先尝试从本地持久缓存读取（避免刷新时页面空白）
            const localKey = this.getCacheKey();
            const localCached = this.getLocalCachedData(localKey);
            if (localCached) {
                this.data = localCached;
                // 使用本地缓存立即返回以触发渲染，同时在后台刷新最新数据
                setTimeout(() => {
                    this.refreshData();
                }, 0);
                return;
            }
            
            // 检查缓存对象是否存在
            if (!this.cache) {
                console.error('缓存对象未初始化');
                this.cache = new Map();
            }
            
            // 检查缓存
            const cacheKey = this.getCacheKey();
            console.log('缓存键:', cacheKey);
            console.log('缓存对象状态:', this.cache);
            
            const cachedData = this.getCachedData(cacheKey);
            console.log('缓存数据:', cachedData);
            
            if (cachedData) {
                this.data = cachedData;
                console.log('使用缓存数据');
                return;
            }

            // 检查请求频率限制
            const now = Date.now();
            if (now - this.lastRequestTime < this.minRequestInterval) {
                console.log('请求过于频繁，使用缓存数据');
                return;
            }

            console.log('开始加载数据...');
            
            // 根据页面时间范围选择获取最近N分钟的日志分析结果（包含清洗后的数据）
            const timeRangeElement = document.getElementById('timeRange');
            const minutes = timeRangeElement && timeRangeElement.value ? parseInt(timeRangeElement.value) : 1;
            const response = await fetch(`/api/log-recent-analysis?minutes=${minutes}&include_details=true`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            this.data = await response.json();
            console.log('API响应数据:', this.data);
            
            // 验证数据结构
            if (!this.data || typeof this.data !== 'object') {
                throw new Error('API返回的数据格式无效');
            }
            
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
            
            // 打印清洗统计信息
            this.printCleaningSummary();
            
            // 更新缓存和请求时间
            this.setCachedData(cacheKey, this.data);
            this.lastRequestTime = now;

            // 写入本地持久缓存（用于刷新时快速展示）
            this.setLocalCachedData(cacheKey, this.data);
            
        } catch (error) {
            console.error('加载数据失败:', error);
            // 出错时优先回退到本地持久缓存，避免页面空白
            const fallback = this.getLocalCachedData(this.getCacheKey(), true);
            if (fallback) {
                this.data = fallback;
            } else {
                this.showError(`数据加载失败: ${error.message}`);
                // 设置默认数据，避免页面崩溃
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

    async loadAndCleanLogs() {
        try {
            console.log('🧹 开始加载并清洗最近1分钟的日志...');
            
            // 使用新的日志归类测试端点获取清洗后的日志
            const response = await fetch('/api/log-classification-test?minutes=1');
            
            if (!response.ok) {
                throw new Error(`日志清洗API请求失败: HTTP ${response.status}`);
            }
            
            const result = await response.json();
            console.log('日志清洗API响应:', result);
            
            if (result.status === 'success') {
                const rawStats = result.data.raw_stats;
                const formattedReport = result.data.formatted_report;
                
                // 打印清洗后的日志内容
                this.printCleanedLogs(rawStats, formattedReport);
                
                // 显示清洗统计信息
                this.displayCleaningStats(result.data.summary);
                
            } else {
                console.warn('日志清洗API返回警告:', result.message);
            }
            
        } catch (error) {
            console.error('日志清洗失败:', error);
            this.showError(`日志清洗失败: ${error.message}`);
        }
    }

    printCleanedLogs(rawStats, formattedReport) {
        console.log('\n' + '='.repeat(80));
        console.log('✨ 清洗后的日志内容');
        console.log('='.repeat(80));
        
        if (rawStats) {
            // 打印级别分布
            const levelDist = rawStats.level_distribution;
            if (levelDist && Object.keys(levelDist).length > 0) {
                console.log('\n🔴 级别分布:');
                const totalLevels = Object.values(levelDist).reduce((a, b) => a + b, 0);
                Object.entries(levelDist).forEach(([level, count]) => {
                    const percentage = totalLevels > 0 ? ((count / totalLevels) * 100).toFixed(1) : 0;
                    console.log(`  ${level}: ${count} (${percentage}%)`);
                });
            }
            
            // 打印实例分布
            const instanceDist = rawStats.instance_distribution;
            if (instanceDist && Object.keys(instanceDist).length > 0) {
                console.log('\n🖥️  实例分布:');
                const totalInstances = Object.values(instanceDist).reduce((a, b) => a + b, 0);
                Object.entries(instanceDist).forEach(([instance, count]) => {
                    const percentage = totalInstances > 0 ? ((count / totalInstances) * 100).toFixed(1) : 0;
                    console.log(`  ${instance}: ${count} (${percentage}%)`);
                });
            }
            
            // 打印业务模块
            const businessModules = rawStats.business_modules;
            if (businessModules && Object.keys(businessModules).length > 0) {
                console.log('\n🏢 业务模块:');
                const totalBusiness = Object.values(businessModules).reduce((a, b) => a + b, 0);
                Object.entries(businessModules).forEach(([module, count]) => {
                    const percentage = totalBusiness > 0 ? ((count / totalBusiness) * 100).toFixed(1) : 0;
                    console.log(`  ${module}: ${count} (${percentage}%)`);
                });
            }
            
            // 打印错误类别
            const errorCategories = rawStats.error_categories;
            if (errorCategories && Object.keys(errorCategories).length > 0) {
                console.log('\n❌ 错误类别:');
                const totalErrors = Object.values(errorCategories).reduce((a, b) => a + b, 0);
                Object.entries(errorCategories).forEach(([category, count]) => {
                    const percentage = totalErrors > 0 ? ((count / totalErrors) * 100).toFixed(1) : 0;
                    console.log(`  ${category}: ${count} (${percentage}%)`);
                });
            }
            
            // 打印严重程度分布
            const severityDist = rawStats.severity_distribution;
            if (severityDist && Object.keys(severityDist).length > 0) {
                console.log('\n⚠️  严重程度分布:');
                const totalSeverity = Object.values(severityDist).reduce((a, b) => a + b, 0);
                Object.entries(severityDist).forEach(([severity, count]) => {
                    const percentage = totalSeverity > 0 ? ((count / totalSeverity) * 100).toFixed(1) : 0;
                    console.log(`  ${severity}: ${count} (${percentage}%)`);
                });
            }
            
            // 打印严重错误详情
            const criticalErrors = rawStats.critical_errors;
            if (criticalErrors && criticalErrors.length > 0) {
                console.log('\n🚨 严重错误详情:');
                criticalErrors.slice(0, 5).forEach((error, index) => {
                    console.log(`  ${index + 1}. ${error.message}`);
                    console.log(`     时间: ${error.timestamp}`);
                    console.log(`     实例: ${error.instance}`);
                    console.log(`     类别: ${error.category}`);
                    console.log(`     业务模块: ${error.business_module}`);
                });
            }
            
            // 打印最近错误
            const recentErrors = rawStats.recent_errors;
            if (recentErrors && recentErrors.length > 0) {
                console.log('\n📝 最近错误:');
                recentErrors.slice(0, 5).forEach((error, index) => {
                    console.log(`  ${index + 1}. ${error.message}`);
                    console.log(`     时间: ${error.timestamp}`);
                    console.log(`     实例: ${error.instance}`);
                    console.log(`     类别: ${error.category}`);
                    console.log(`     严重程度: ${error.severity}`);
                    console.log(`     业务模块: ${error.business_module}`);
                });
            }
        }
        
        if (formattedReport) {
            console.log('\n' + '='.repeat(80));
            console.log('📋 格式化报告');
            console.log('='.repeat(80));
            
            // 打印趋势分析
            const trends = formattedReport.trends;
            if (trends) {
                console.log('\n📈 趋势分析:');
                console.log(`  错误增长: ${trends.error_growth || 'unknown'}`);
                console.log(`  业务影响: ${trends.business_impact || 'unknown'}`);
                console.log(`  系统健康: ${trends.system_health || 'unknown'}`);
                console.log(`  严重错误趋势: ${trends.critical_trend || 'unknown'}`);
            }
            
            // 打印建议措施
            const recommendations = formattedReport.recommendations;
            if (recommendations && recommendations.length > 0) {
                console.log('\n💡 建议措施:');
                recommendations.forEach((rec, index) => {
                    console.log(`  ${index + 1}. ${rec}`);
                });
            }
        }
        
        console.log('\n' + '='.repeat(80));
        console.log('✅ 日志清洗内容打印完成');
        console.log('='.repeat(80));
    }

    displayCleaningStats(summary) {
        // 在页面上显示清洗统计信息
        const container = document.getElementById('cleaningStats');
        if (container && summary) {
            container.innerHTML = `
                <div class="alert alert-info">
                    <h5>🧹 日志清洗统计</h5>
                    <div class="row">
                        <div class="col-md-3">
                            <strong>总日志数:</strong> ${summary.total_logs || 0}
                        </div>
                        <div class="col-md-3">
                            <strong>总错误数:</strong> ${summary.total_errors || 0}
                        </div>
                        <div class="col-md-3">
                            <strong>业务模块数:</strong> ${summary.business_modules_count || 0}
                        </div>
                        <div class="col-md-3">
                            <strong>实例数:</strong> ${summary.instances_count || 0}
                        </div>
                    </div>
                    <div class="mt-2">
                        <small class="text-muted">
                            生成时间: ${summary.generated_at || 'N/A'} | 
                            时间范围: ${summary.time_range || 'N/A'}
                        </small>
                    </div>
                </div>
            `;
        }
    }

    printCleaningSummary() {
        if (this.data && this.data.cleaning_summary) {
            const summary = this.data.cleaning_summary;
            console.log('\n' + '='.repeat(80));
            console.log('🧹 日志清洗统计摘要');
            console.log('='.repeat(80));
            console.log(`原始日志数量: ${summary.raw_logs_count || 0}`);
            console.log(`清洗后日志数量: ${summary.cleaned_logs_count || 0}`);
            console.log(`重复日志移除: ${summary.duplicates_removed || 0}`);
            console.log(`发现业务模块: ${summary.business_modules_found || 0}`);
            console.log(`发现错误类别: ${summary.error_categories_found || 0}`);
            console.log(`清洗时间: ${summary.cleaning_timestamp || 'N/A'}`);
            console.log(`处理状态: ${this.data.processing_status || 'unknown'}`);
            
            // 显示清洗后的数据分布
            if (this.data.business_modules && Object.keys(this.data.business_modules).length > 0) {
                console.log('\n🏢 业务模块分布:');
                Object.entries(this.data.business_modules).forEach(([module, info]) => {
                    console.log(`  ${module}: ${info.count} 条日志`);
                });
            }
            
            if (this.data.error_categories && Object.keys(this.data.error_categories).length > 0) {
                console.log('\n❌ 错误类别分布:');
                Object.entries(this.data.error_categories).forEach(([category, count]) => {
                    console.log(`  ${category}: ${count} 条`);
                });
            }
            
            if (this.data.severity_distribution && Object.keys(this.data.severity_distribution).length > 0) {
                console.log('\n⚠️  严重程度分布:');
                Object.entries(this.data.severity_distribution).forEach(([severity, count]) => {
                    console.log(`  ${severity}: ${count} 条`);
                });
            }
            
            console.log('='.repeat(80));
            console.log('✅ 日志清洗完成，数据已存储并可用于页面渲染');
            console.log('='.repeat(80));
        }
    }

    getCacheKey() {
        const timeRangeElement = document.getElementById('timeRange');
        const timeRange = timeRangeElement && timeRangeElement.value ? timeRangeElement.value : '1';
        return `log_analysis_${timeRange}`;
    }

    getCachedData(key) {
        if (!this.cache || !(this.cache instanceof Map)) {
            console.error('缓存对象无效，重新初始化');
            this.cache = new Map();
            return null;
        }
        
        try {
            const cached = this.cache.get(key);
            if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
                return cached.data;
            }
            return null;
        } catch (error) {
            console.error('获取缓存数据时出错:', error);
            return null;
        }
    }

    setCachedData(key, data) {
        if (!this.cache || !(this.cache instanceof Map)) {
            console.error('缓存对象无效，重新初始化');
            this.cache = new Map();
        }
        
        try {
            this.cache.set(key, {
                data: data,
                timestamp: Date.now()
            });
        } catch (error) {
            console.error('设置缓存数据时出错:', error);
        }
    }

    // 本地持久缓存：使用localStorage
    getLocalCachedData(key, allowStale = false) {
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return null;
            const obj = JSON.parse(raw);
            if (!obj || !obj.timestamp || !obj.data) return null;
            const isFresh = (Date.now() - obj.timestamp) < this.localCacheTTL;
            if (isFresh || allowStale) return obj.data;
            return null;
        } catch (e) {
            return null;
        }
    }

    setLocalCachedData(key, data) {
        try {
            localStorage.setItem(key, JSON.stringify({ data, timestamp: Date.now() }));
        } catch (e) {
            // 忽略本地存储错误
        }
    }

    setupEventListeners() {
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.refreshData();
            });
        }

        // 已移除类型分布点击检索

        const timeRange = document.getElementById('timeRange');
        if (timeRange) {
            timeRange.addEventListener('change', (e) => {
                this.currentFilters = { minutes: parseInt(e.target.value) };
                this.refreshData();
            });
        }

        // 自动刷新 - 减少频率，避免过度请求
        setInterval(() => {
            const autoRefresh = document.getElementById('autoRefresh');
            if (autoRefresh && autoRefresh.checked) {
                this.refreshData();
            }
        }, 50000); // 改为50秒自动刷新
    }

    async refreshData() {
        // 清除相关缓存，强制重新加载
        const cacheKey = this.getCacheKey();
        this.cache.delete(cacheKey);
        
        await this.loadData();
        this.renderDashboard();
    }

    renderDashboard() {
        console.log('开始渲染仪表板，当前数据:', this.data);
        
        // 添加调试信息
        if (this.data) {
            console.log('数据详情:', {
                total_logs: this.data.total_logs,
                time_range: this.data.time_range,
                error_types: this.data.error_types,
                recent_errors: this.data.recent_errors ? this.data.recent_errors.length : 0
            });
        } else {
            console.warn('数据为空，无法渲染');
        }
        
        this.renderSummaryCards();
        this.renderTypeDistribution();
        this.renderRecentErrors();
        this.renderErrorDetails();
        
        // 页面渲染完成
    }
    

    renderSummaryCards() {
        const container = document.getElementById('summaryCards');
        if (!container || !this.data) return;

        // 安全地解构数据
        const {
            total_logs = 0,
            cleaned_logs_count = 0,
            business_modules = {},
            error_categories = {},
            severity_distribution = {},
            processing_status = 'unknown'
        } = this.data;

        // 计算业务模块数量
        const business_modules_count = Object.keys(business_modules).length;
        
        // 计算错误类别数量
        const error_categories_count = Object.keys(error_categories).length;
        
        // 计算严重错误数量
        const critical_errors_count = Object.values(severity_distribution).reduce((sum, count) => {
            return sum + (count || 0);
        }, 0);

        // 构建卡片HTML
        const cardsHTML = `
            <div class="col-md-3 mb-3">
                <div class="card summary-card h-100">
                    <div class="card-body text-center">
                        <div class="d-flex align-items-center justify-content-center mb-2">
                            <i class="bi bi-file-text text-primary fs-1"></i>
                        </div>
                        <h5 class="card-title">总日志数</h5>
                        <h3 class="text-primary mb-0">${total_logs}</h3>
                        <small class="text-muted">原始日志数量</small>
                    </div>
                </div>
            </div>
            
            <div class="col-md-3 mb-3">
                <div class="card summary-card h-100">
                    <div class="card-body text-center">
                        <div class="d-flex align-items-center justify-content-center mb-2">
                            <i class="bi bi-check-circle text-success fs-1"></i>
                        </div>
                        <h5 class="card-title">清洗后日志</h5>
                        <h3 class="text-success mb-0">${cleaned_logs_count}</h3>
                        <small class="text-muted">去重后数量</small>
                    </div>
                </div>
            </div>
            
            <div class="col-md-3 mb-3">
                <div class="card summary-card h-100">
                    <div class="card-body text-center">
                        <div class="d-flex align-items-center justify-content-center mb-2">
                            <i class="bi bi-building text-info fs-1"></i>
                        </div>
                        <h5 class="card-title">业务模块</h5>
                        <h3 class="text-info mb-0">${business_modules_count}</h3>
                        <small class="text-muted">识别到的模块</small>
                    </div>
                </div>
            </div>
            
            <div class="col-md-3 mb-3">
                <div class="card summary-card h-100">
                    <div class="card-body text-center">
                        <div class="d-flex align-items-center justify-content-center mb-2">
                            <i class="bi bi-exclamation-triangle text-warning fs-1"></i>
                        </div>
                        <h5 class="card-title">错误类别</h5>
                        <h3 class="text-warning mb-0">${error_categories_count}</h3>
                        <small class="text-muted">分类统计</small>
                    </div>
                </div>
            </div>
        `;

        // 添加处理状态指示器
        const statusHTML = `
            <div class="col-12 mb-3">
                <div class="alert ${this.getStatusAlertClass(processing_status)}">
                    <div class="d-flex align-items-center">
                        <i class="bi ${this.getStatusIcon(processing_status)} me-2"></i>
                        <div>
                            <strong>处理状态:</strong> ${this.getStatusText(processing_status)}
                            ${this.data.cleaning_summary ? `
                                <br><small class="text-muted">
                                    清洗时间: ${this.formatTime(this.data.cleaning_summary.cleaning_timestamp)} | 
                                    重复移除: ${this.data.cleaning_summary.duplicates_removed || 0} 条
                                </small>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;

        container.innerHTML = statusHTML + cardsHTML;
    }

    getStatusAlertClass(status) {
        switch (status) {
            case 'cleaned_and_stored':
                return 'alert-success';
            case 'processing':
                return 'alert-info';
            case 'error':
                return 'alert-danger';
            case 'no_logs_found':
                return 'alert-warning';
            default:
                return 'alert-secondary';
        }
    }

    getStatusIcon(status) {
        switch (status) {
            case 'cleaned_and_stored':
                return 'bi-check-circle-fill';
            case 'processing':
                return 'bi-arrow-clockwise';
            case 'error':
                return 'bi-exclamation-triangle-fill';
            case 'no_logs_found':
                return 'bi-search';
            default:
                return 'bi-question-circle';
        }
    }

    getStatusText(status) {
        switch (status) {
            case 'cleaned_and_stored':
                return '日志已清洗并存储完成';
            case 'processing':
                return '正在处理中...';
            case 'error':
                return '处理过程中出现错误';
            case 'no_logs_found':
                return '未找到日志数据';
            default:
                return '未知状态';
        }
    }

    renderRecentErrors() {
        const container = document.getElementById('recentErrors');
        if (!container || !this.data) return;

        const recentErrors = this.data.recent_errors || [];
        
        if (recentErrors.length === 0) {
            container.innerHTML = `
                <div class="alert alert-info">
                    <i class="bi bi-info-circle"></i> 暂无最近错误数据
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>时间</th>
                            <th>业务模块</th>
                            <th>错误类型</th>
                            <th>严重程度</th>
                            <th>错误信息</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${recentErrors.map(error => {
                            try {
                                const businessModule = error.business_analysis && error.business_analysis.business_module ? error.business_analysis.business_module : '未知';
                                const errorType = error.error_analysis && error.error_analysis.error_type ? error.error_analysis.error_type : '未知';
                                const severity = error.error_analysis && error.error_analysis.severity ? error.error_analysis.severity : '未知';
                                const severityLabel = this.getSeverityLabel(severity);
                                const severityClass = this.getSeverityBadgeClass(severity);
                                // 最近错误列表仍展示原始错误信息
                                const message = error.message || '无错误信息';
                                
                                return `
                                    <tr>
                                        <td>${this.formatTime(error.timestamp)}</td>
                                        <td>
                                            <span class="badge bg-primary">${businessModule}</span>
                                        </td>
                                        <td>
                                            <span class="badge bg-warning">${errorType}</span>
                                        </td>
                                        <td>
                                            <span class="badge ${severityClass}">${severityLabel}</span>
                                        </td>
                                        <td>
                                            <small title="${this.escapeHtml(error.message || message)}">${this.truncateMessage(message)}</small>
                                        </td>
                                    </tr>
                                `;
                            } catch (e) {
                                console.warn('渲染错误行时出现问题:', e, error);
                                return `
                                    <tr>
                                        <td>${this.formatTime(error.timestamp || '')}</td>
                                        <td><span class="badge bg-secondary">数据异常</span></td>
                                        <td><span class="badge bg-secondary">数据异常</span></td>
                                        <td><span class="badge bg-secondary">数据异常</span></td>
                                        <td><small>数据格式异常</small></td>
                                    </tr>
                                `;
                            }
                        }).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    renderTypeDistribution() {
        const container = document.getElementById('typeDistribution');
        if (!container || !this.data) return;

        // 使用累计统计（后端每分钟累加维护）
        const errorTypes = this.data.error_types || {};
        const entries = Object.entries(errorTypes).sort((a, b) => b[1] - a[1]);

        if (entries.length === 0) {
            container.innerHTML = `
                <div class="alert alert-info">
                    <i class="bi bi-info-circle"></i> 暂无类型分布数据
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>错误类型（基于中文归类）</th>
                            <th>数量</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${entries.map(([type, count]) => `
                            <tr>
                                <td>${type}</td>
                                <td><span class="badge bg-secondary">${count}</span></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    // 已移除按类型检索相关代码

    renderErrorDetails() {
        const container = document.getElementById('errorDetails');
        if (!container || !this.data) return;

        const recentErrors = this.data.recent_errors || [];
        
        if (recentErrors.length === 0) {
            container.innerHTML = `
                <div class="alert alert-info">
                    <i class="bi bi-info-circle"></i> 暂无详细错误信息
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>时间</th>
                            <th>业务模块</th>
                            <th>功能描述</th>
                            <th>错误类型</th>
                            <th>处理建议</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${recentErrors.map(error => {
                            try {
                                const businessModule = error.business_analysis && error.business_analysis.business_module ? error.business_analysis.business_module : '未知';
                                const businessFunction = error.business_analysis && error.business_analysis.business_function ? error.business_analysis.business_function : '未知';
                                // 使用后端清洗的核心消息作为功能描述优先展示
                                const description = (error.core_message || (error.error_analysis && error.error_analysis.core_message)) || businessFunction;
                                const errorType = error.error_analysis && error.error_analysis.error_type ? error.error_analysis.error_type : '未知';
                                const suggestedActions = error.error_analysis && error.error_analysis.suggested_actions && Array.isArray(error.error_analysis.suggested_actions) ? error.error_analysis.suggested_actions.slice(0, 2).join(', ') : '暂无建议';
                                
                                return `
                                    <tr>
                                        <td>${this.formatTime(error.timestamp)}</td>
                                        <td>
                                            <span class="badge bg-primary">${businessModule}</span>
                                        </td>
                                        <td><span title="${this.escapeHtml(error.message || description)}">${this.truncateMessage(description)}</span></td>
                                        <td>
                                            <span class="badge bg-warning">${errorType}</span>
                                        </td>
                                        <td>
                                            <small>${suggestedActions}</small>
                                        </td>
                                    </tr>
                                `;
                            } catch (e) {
                                console.warn('渲染详细错误行时出现问题:', e, error);
                                return `
                                    <tr>
                                        <td>${this.formatTime(error.timestamp || '')}</td>
                                        <td><span class="badge bg-secondary">数据异常</span></td>
                                        <td>数据异常</td>
                                        <td><span class="badge bg-secondary">数据异常</span></td>
                                        <td><small>数据格式异常</small></td>
                                    </tr>
                                `;
                            }
                        }).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    showError(message) {
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-danger alert-dismissible fade show';
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        const container = document.querySelector('.container-fluid');
        if (container) {
            container.insertBefore(alertDiv, container.firstChild);
        }
    }

    // 严重程度中文映射
    getSeverityLabel(severity) {
        const s = (severity || '').toString().toLowerCase();
        switch (s) {
            case 'critical':
                return '严重';
            case 'warning':
                return '警告';
            case 'info':
                return '信息';
            default:
                return '未知';
        }
    }

    // 严重程度样式映射
    getSeverityBadgeClass(severity) {
        const s = (severity || '').toString().toLowerCase();
        switch (s) {
            case 'critical':
                return 'bg-danger';
            case 'warning':
                return 'bg-warning text-dark';
            case 'info':
                return 'bg-info text-dark';
            default:
                return 'bg-secondary';
        }
    }

    // 简单转义，避免title属性中出现非法字符
    escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    formatTime(timestamp) {
        if (!timestamp) return '未知';
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
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    try {
        console.log('开始初始化LogTypesDashboard...');
        window.logTypesDashboard = new LogTypesDashboard();
        console.log('LogTypesDashboard初始化完成');
    } catch (error) {
        console.error('初始化LogTypesDashboard失败:', error);
        // 显示错误信息
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-danger alert-dismissible fade show';
        alertDiv.innerHTML = `
            初始化失败: ${error.message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        const container = document.querySelector('.container-fluid');
        if (container) {
            container.insertBefore(alertDiv, container.firstChild);
        }
    }
});


