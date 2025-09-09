# AI-Ops 智能运维巡检系统

一个基于Prometheus的自动化运维巡检系统，专注于硬件资源监控和健康检查。

## 功能特性

- **硬件巡检**: 基于Prometheus的CPU、内存、磁盘、网络监控
- **健康检查**: 系统和应用健康状态检查
- **数据存储**: 巡检结果存储到MySQL数据库
- **Web界面**: 现代化的Web仪表板展示巡检数据
- **多通道通知**: 支持钉钉、飞书、Slack等多种通知渠道
- **定时巡检**: 支持定时自动巡检
- **缓存机制**: Redis缓存提升性能

## 新增功能：智能日志分析

### 1. 获取详细日志Message信息

#### API: `/api/log-messages`
获取详细的日志message信息，支持分类过滤和搜索。

**请求示例：**
```bash
# 获取最近1小时的日志，按数据库连接失败分类过滤
curl "http://localhost:8000/api/log-messages?hours=1&category=数据库连接失败&page=1&page_size=20"

# 搜索包含"timeout"关键词的日志
curl "http://localhost:8000/api/log-messages?hours=24&search=timeout&severity=warning"

# 按实例过滤
curl "http://localhost:8000/api/log-messages?hours=6&instance=mysql-service&limit=50"
```

**响应示例：**
```json
{
  "logs": [
    {
      "id": "log_123",
      "timestamp": "2025-01-14T10:30:00Z",
      "message": "Connection to MySQL database failed: timeout after 30 seconds",
      "category": "数据库连接失败",
      "severity": "warning",
      "level": "error",
      "logger": "com.example.db.DatabaseService",
      "host": "web-server-01",
      "instance": "mysql-service",
      "score": 0.95
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 45,
    "total_hits": 45,
    "pages": 3
  },
  "statistics": {
    "category_distribution": {
      "数据库连接失败": 15,
      "网络超时": 12,
      "内存不足": 8
    },
    "severity_distribution": {
      "warning": 25,
      "critical": 10,
      "info": 10
    }
  }
}
```

### 2. 获取日志分类统计

#### API: `/api/log-categories`
获取日志分类统计和详细信息。

**请求示例：**
```bash
# 获取最近24小时的分类统计
curl "http://localhost:8000/api/log-categories?hours=24&include_details=true"
```

**响应示例：**
```json
{
  "total_logs": 150,
  "time_range": "最近24小时",
  "categories": {
    "数据库连接失败": {
      "count": 45,
      "percentage": 30.0,
      "severity_breakdown": {
        "warning": 30,
        "critical": 15
      },
      "instance_count": 3,
      "instances": ["mysql-service", "postgres-service", "redis-service"],
      "examples": [
        {
          "message": "Connection to MySQL database failed: timeout after 30 seconds",
          "timestamp": "2025-01-14T10:30:00Z",
          "instance": "mysql-service",
          "severity": "warning"
        }
      ]
    }
  },
  "summary": {
    "total_categories": 8,
    "most_common_category": "数据库连接失败",
    "critical_count": 25,
    "warning_count": 80,
    "info_count": 45
  }
}
```

+### 3. 全文搜索日志

#### API: `/ap+i/log-search`
全文搜索日志messa+ge内容，支持高亮显示。
+
*+*请求示例：**

# 搜索包含"memory"关键词的日志
 "http://localhost:8000/api/log-search?q=memory&hours=24&highlight=true"

# 搜索特定错误模式
curl "http://localhost:8000/api/log-search?q=connection+refused&hours=6&limit=100"
```

**响应示例：**
```json
{
  "query": "memory",
  "results": [
    {
      "id": "log_456",
      "score": 0.92,
      "timestamp": "2025-01-14T11:15:00Z",
      "message": "Out of memory error: Java heap space exhausted",
      "category": "内存不足",
      "severity": "critical",
      "highlight": {
        "message": [
          "Out of <mark>memory</mark> error: Java heap space exhausted"
        ]
      }
    }
  ],
  "total_hits": 12,
  "search_stats": {
    "query_time_ms": 45,
    "max_score": 0.95
  }
}
```

### 4. 详细日志分析

#### API: `/api/log-analysis-detail`
获取详细的日志分析结果，包含智能分类和处理建议。

**请求示例：**
```bash
# 获取最近6小时的详细分析
curl "http://localhost:8000/api/log-analysis-detail?hours=6&include_suggestions=true&limit=100"
```

**响应示例：**
```json
{
  "analysis": {
    "total_logs": 89,
    "filtered_logs": 89,
    "time_range": "最近6小时",
    "analysis_timestamp": "2025-01-14T12:00:00Z"
  },
  "detailed_results": [
    {
      "id": "log_789",
      "timestamp": "2025-01-14T11:45:00Z",
      "message": "Database connection pool exhausted",
      "classification": {
        "category": "数据库连接失败",
        "severity": "critical",
        "confidence": 0.9,
        "method": "pattern_match",
        "suggested_actions": [
          "立即处理 - 影响系统稳定性",
          "检查数据库服务状态",
          "验证连接配置",
          "检查网络连通性",
          "查看数据库日志"
        ]
      },
      "context": {
        "logger": "com.example.db.ConnectionPool",
        "host": "app-server-02",
        "instance": "user-service",
        "level": "error"
      }
    }
  ],
  "suggestions_summary": {
    "数据库连接失败_critical": {
      "category": "数据库连接失败",
      "severity": "critical",
      "suggestions": [
        "立即处理 - 影响系统稳定性",
        "检查数据库服务状态",
        "验证连接配置"
      ],
      "count": 5
    }
  }
}
```

### 5. 日志模式分析

#### API: `/api/log-patterns`
分析日志中的重复模式，帮助发现系统性问题。

**请求示例：**
```bash
# 分析最近24小时的日志模式，最小频率为3次
curl "http://localhost:8000/api/log-patterns?hours=24&min_frequency=3"
```

**响应示例：**
```json
{
  "patterns": {
    "Connection to database N failed: timeout after N seconds": {
      "count": 25,
      "examples": [
        {
          "message": "Connection to database mysql failed: timeout after 30 seconds",
          "timestamp": "2025-01-14T10:30:00Z",
          "instance": "mysql-service",
          "category": "数据库连接失败",
          "severity": "warning"
        }
      ],
      "instances": ["mysql-service", "postgres-service"],
      "hosts": ["web-server-01", "web-server-02"],
      "categories": ["数据库连接失败"],
      "severities": ["warning", "critical"]
    }
  },
  "summary": {
    "total_patterns": 8,
    "total_logs": 150,
    "min_frequency": 3,
    "time_range": "最近24小时"
  }
}
```

## 新增功能：中文日志分析

### 1. 最近1分钟日志分析

#### API: `/api/log-recent-analysis`
获取最近N分钟的日志分析结果，包含中文业务类别提取和错误分析。

**请求示例：**
```bash
# 获取最近1分钟的日志分析
curl "http://localhost:8000/api/log-recent-analysis?minutes=1"

# 获取最近1分钟的日志分析（不包含详细错误信息）
curl "http://localhost:8000/api/log-recent-analysis?minutes=1&include_details=false"

# 强制刷新（绕过缓存）获取最近1分钟的日志分析
curl "http://localhost:8000/api/log-recent-analysis?minutes=1&include_details=true&refresh=true"
```

**响应示例：**
```json
{
  "total_logs": 15,
  "time_range": "最近1分钟",
  "analysis_timestamp": "2025-01-14T12:00:00Z",
  "business_modules": {
    "APP_首页版块": {
      "count": 8,
      "errors": [
        {
          "message": "【APP_首页版块】获取用户信息失败 java.lang.NullPointerException: null",
          "timestamp": "2025-01-14T11:59:30Z",
          "error_type": "空指针异常"
        }
      ],
      "instances": ["user-service", "app-service"]
    }
  },
  "error_categories": {
    "应用异常": 10,
    "业务异常": 3,
    "数据库异常": 2
  },
  "error_types": {
    "空指针异常": 8,
    "数据获取异常": 3,
    "数据库连接失败": 2
  },
  "severity_distribution": {
    "critical": 8,
    "warning": 5,
    "info": 2
  },
  "recent_errors": [
    {
      "id": "log_123",
      "timestamp": "2025-01-14T11:59:30Z",
      "message": "【APP_首页版块】获取用户信息失败 java.lang.NullPointerException: null",
      "business_analysis": {
        "business_module": "APP_首页版块",
        "business_function": "获取用户信息失败",
        "error_detail": "java.lang.NullPointerException",
        "extracted_info": {
          "业务模块": "APP_首页版块",
          "业务功能": "获取用户信息失败",
          "Java异常": "java.lang.NullPointerException"
        }
      },
      "error_analysis": {
        "error_type": "空指针异常",
        "error_category": "应用异常",
        "severity": "critical",
        "business_context": "APP_首页版块",
        "technical_details": {
          "异常类型": "NullPointerException",
          "业务模块": "APP_首页版块",
          "业务功能": "获取用户信息失败"
        },
        "suggested_actions": [
          "检查APP_首页版块相关配置",
          "检查对象是否为空",
          "添加空值检查",
          "查看调用链中的空值传递"
        ]
      }
    }
  ]
}
```

### 2. 业务模块错误统计

#### API: `/api/log-business-modules`
获取业务模块错误统计，重点关注【】中的业务类别。

**请求示例：**
```bash
# 获取最近5分钟的业务模块统计
curl "http://localhost:8000/api/log-business-modules?minutes=1&min_count=2"
```

**响应示例：**
```json
{
  "total_errors": 25,
  "time_range": "最近5分钟",
  "business_modules": {
    "APP_首页版块": {
      "count": 12,
      "error_types": {
        "空指针异常": 8,
        "数据获取异常": 4
      },
      "severity_distribution": {
        "critical": 8,
        "warning": 4
      },
      "instances": ["user-service", "app-service"],
      "recent_errors": [
        {
          "timestamp": "2025-01-14T11:59:30Z",
          "message": "【APP_首页版块】获取用户信息失败 java.lang.NullPointerException: null",
          "error_type": "空指针异常",
          "severity": "critical",
          "business_function": "获取用户信息失败",
          "technical_details": {
            "异常类型": "NullPointerException",
            "业务模块": "APP_首页版块"
          }
        }
      ]
    },
    "用户管理模块": {
      "count": 8,
      "error_types": {
        "数据获取异常": 5,
        "数据库连接失败": 3
      },
      "severity_distribution": {
        "warning": 8
      },
      "instances": ["user-service"],
      "recent_errors": []
    }
  },
  "summary": {
    "total_modules": 2,
    "most_error_module": "APP_首页版块",
    "analysis_timestamp": "2025-01-14T12:00:00Z"
  }
}
```

### 3. 详细错误信息

#### API: `/api/log-error-details`
获取详细的错误信息，包含完整的业务分析和处理建议。

**请求示例：**
```bash
# 获取APP_首页版块的错误详情
curl "http://localhost:8000/api/log-error-details?minutes=1&business_module=APP_首页版块&limit=10"

# 获取空指针异常的详细信息
curl "http://localhost:8000/api/log-error-details?minutes=1&error_type=空指针异常&severity=critical"
```

**响应示例：**
```json
{
  "total_logs": 25,
  "filtered_logs": 8,
  "time_range": "最近5分钟",
  "filters": {
    "business_module": "APP_首页版块",
    "error_type": null,
    "severity": null
  },
  "results": [
    {
      "id": "log_123",
      "timestamp": "2025-01-14T11:59:30Z",
      "message": "【APP_首页版块】获取用户信息失败 java.lang.NullPointerException: null\n\tat com.itlong.cloud.utils.data.filter.ProjectFilterUtil.isOpenBookProject(ProjectFilterUtil.java:53)\n\tat com.itlong.cloud.controller.current.AppHomeController.getUserInfo(AppHomeController.java:1004)",
      "business_info": {
        "module": "APP_首页版块",
        "function": "获取用户信息失败",
        "extracted_info": {
          "业务模块": "APP_首页版块",
          "业务功能": "获取用户信息失败",
          "Java异常": "java.lang.NullPointerException",
          "异常位置": "com.itlong.cloud.utils.data.filter.ProjectFilterUtil.isOpenBookProject(ProjectFilterUtil.java:53)"
        }
      },
      "error_info": {
        "type": "空指针异常",
        "category": "应用异常",
        "severity": "critical",
        "technical_details": {
          "异常类型": "NullPointerException",
          "业务模块": "APP_首页版块",
          "业务功能": "获取用户信息失败",
          "异常位置": "com.itlong.cloud.utils.data.filter.ProjectFilterUtil.isOpenBookProject(ProjectFilterUtil.java:53)"
        },
        "suggested_actions": [
          "检查APP_首页版块相关配置",
          "检查对象是否为空",
          "添加空值检查",
          "查看调用链中的空值传递"
        ]
      },
      "context": {
        "logger": "com.itlong.cloud.thrown.DataAccessException",
        "host": "web-server-01",
        "instance": "user-service",
        "thread": "http-nio-8084-exec-33",
        "level": "error"
      }
    }
  ],
  "analysis_timestamp": "2025-01-14T12:00:00Z"
}
```

## 中文日志分析特性

### 1. 业务类别提取
- **【】标记识别**: 自动提取【】中的业务模块名称
- **中文功能描述**: 识别业务功能描述（如"获取用户信息失败"）
- **Java异常提取**: 识别具体的Java异常类型
- **堆栈信息解析**: 提取异常发生的具体位置

### 2. 智能错误分类
- **空指针异常**: 识别NullPointerException并提供处理建议
- **中文错误映射**: 将中文错误描述映射到标准错误类型
- **业务异常识别**: 区分业务异常和技术异常
- **严重程度评估**: 自动评估错误的严重程度

### 3. 处理建议生成
- **基于业务上下文**: 根据业务模块提供针对性建议
- **技术处理建议**: 提供具体的技术解决方案
- **优先级排序**: 按严重程度排序处理建议

### 4. 统计分析
- **业务模块统计**: 按【】中的业务模块分组统计
- **错误类型分布**: 分析各类错误的分布情况
- **实例影响分析**: 统计受影响的实例和主机
- **趋势分析**: 支持时间范围内的趋势分析

## 使用场景

### 1. 实时监控
```bash
# 监控最近1分钟的APP_首页版块错误
curl "http://localhost:8000/api/log-error-details?minutes=1&business_module=APP_首页版块"
```

### 2. 故障排查
```bash
# 查看空指针异常的详细信息
curl "http://localhost:8000/api/log-error-details?minutes=1&error_type=空指针异常"
```

### 3. 业务影响分析
```bash
# 分析各业务模块的错误情况
curl "http://localhost:8000/api/log-business-modules?minutes=10&min_count=1"
```

### 4. 自动化告警
基于业务模块和错误类型设置告警规则：
- APP_首页版块出现空指针异常时立即告警
- 用户管理模块连续出现数据库连接失败时告警
- 任何业务模块出现critical级别错误时告警

## 分类规则

系统支持以下主要错误分类：

### 基础设施类
- 网络超时、DNS解析失败、SSL证书错误
- 连接被重置、端口不可达

### 数据库类
- 数据库连接失败、SQL语法错误
- 主从同步异常、数据库死锁、唯一约束冲突

### 应用类
- NullPointerException、类型转换错误
- 数组越界、断言失败

### 微服务类
- 微服务调用失败、服务发现失败
- 负载均衡错误、熔断器触发

### 容器类
- 容器启动失败、镜像拉取失败
- Kubernetes资源不足、Pod调度失败

### 安全类
- 认证失败、授权失败
- 证书过期、安全扫描失败

### 性能类
- 响应时间过长、并发处理错误
- 缓存失效、队列积压

## 配置说明

### 环境变量配置

系统支持通过环境变量进行配置，主要配置项包括：

#### Elasticsearch 配置
- `ES_QUERY_TIMEOUT`: Elasticsearch查询超时时间（秒），默认60秒
- `ES_CONNECTION_TIMEOUT`: Elasticsearch连接超时时间（秒），默认30秒  
- `ES_MAX_RETRIES`: Elasticsearch请求重试次数，默认3次

#### Prometheus 配置
- `PROM_QUERY_TIMEOUT`: Prometheus查询超时时间（秒），默认15秒
- `PROM_MAX_WORKERS`: Prometheus最大工作线程数，默认20
- `PROM_BATCH_SIZE`: Prometheus批处理大小，默认50

#### 数据库配置
- `DB_HOST`: MySQL数据库主机地址，默认192.168.123.29
- `DB_PORT`: MySQL数据库端口，默认3306
- `DB_USER`: MySQL数据库用户名，默认root
- `DB_PASSWORD`: MySQL数据库密码，默认123456
- `DB_NAME`: MySQL数据库名称，默认bigdata

#### Redis配置
- `REDIS_HOST`: Redis主机地址，默认192.168.123.29
- `REDIS_PORT`: Redis端口，默认6379
- `REDIS_PASSWORD`: Redis密码，默认空
- `REDIS_DB`: Redis数据库编号，默认0
- `REDIS_CACHE_TTL`: Redis缓存TTL（秒），默认300秒（5分钟）

#### 通知配置
- `DINGTALK_WEBHOOK`: 钉钉机器人Webhook地址
- `FEISHU_WEBHOOK`: 飞书机器人Webhook地址
- `SLACK_WEBHOOK`: Slack机器人Webhook地址
- `WORKWECHAT_URL`: 企业微信通知地址
- `WORKWECHAT_CHANNEL`: 企业微信通知频道

#### 日志配置
- `LOG_LEVEL`: 日志级别，默认INFO
- `LOG_FORMAT`: 日志格式

### 超时配置优化

由于网络传输过程中可能存在延迟，系统提供了以下超时配置优化：

1. **日志分析API超时**: 默认120秒，适用于复杂的日志分析查询
2. **连接超时**: 默认60秒，适用于建立Elasticsearch连接
3. **重试机制**: 默认5次重试，提高请求成功率

这些配置可以通过环境变量进行调整，以适应不同的网络环境需求。

### 故障排除指南

#### Elasticsearch连接问题

如果遇到日志分析API返回空数据或超时，请按以下步骤排查：

1. **检查Elasticsearch服务状态**
   ```bash
   # 测试连接
   curl "http://192.168.123.29:9200/_cluster/health"
   
   # 检查索引
   curl "http://192.168.123.29:9200/_cat/indices?format=json"
   ```

2. **运行诊断脚本**
   ```bash
   # 运行Elasticsearch诊断
   python es_diagnostic.py
   
   # 运行API测试
   python test_api.py
   ```

3. **检查配置**
   ```bash
   # 设置环境变量
   export ES_HOST=192.168.123.29
   export ES_PORT=9200
   export ES_INDEX_PATTERN="filebeat-*"
   export ES_LOG_FIELD="message"
   export ES_QUERY_TIMEOUT=120
   export ES_CONNECTION_TIMEOUT=60
   ```

4. **常见问题及解决方案**
   - **连接超时**: 增加 `ES_CONNECTION_TIMEOUT` 值
   - **查询超时**: 增加 `ES_QUERY_TIMEOUT` 值
   - **索引不存在**: 检查 `ES_INDEX_PATTERN` 配置
   - **字段不匹配**: 检查 `ES_LOG_FIELD` 配置
   - **网络延迟**: 增加超时时间和重试次数

5. **日志分析**
   ```bash
   # 查看系统日志
   tail -f ai_ops.log
   
   # 搜索Elasticsearch相关错误
   grep -i "elasticsearch\|es" ai_ops.log
   ```

### Elasticsearch配置
```python
# log_analyzer.py
self.es_host = "192.168.123.29"
self.es_port = 9200
self.es_index_pattern = "prod_error_logs*"
self.es_field = "message"
```

### 分类规则自定义
可以在 `log_analyzer.py` 中的 `error_patterns` 字典中添加或修改分类规则。

### 缓存配置
系统使用Redis缓存分析结果，提高查询性能：
- 分钟趋势缓存：60秒
- 分类统计缓存：300秒
- 搜索结果缓存：180秒

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置环境变量
```bash
# Prometheus地址
export PROM_URL="http://your-prometheus:9090"

# MySQL数据库
export DB_HOST="your-mysql-host"
export DB_PORT="3306"
export DB_USER="your-username"
export DB_PASSWORD="your-password"
export DB_NAME="your-database"

# Redis缓存（可选）
export REDIS_HOST="your-redis-host"
export REDIS_PORT="6379"
```

### 3. 初始化数据库
```bash
python -m ai_ops setup
```

### 4. 执行巡检
```bash
# 单次巡检
python -m ai_ops inspect

# 定时巡检（每5分钟）
python -m ai_ops schedule --health-interval 300

# 启动Web界面
python -m ai_ops serve --port 8000
```

## 安装

```bash
# 安装依赖
pip install -r requirements.txt
```

## 配置

通过环境变量配置系统：

```bash
# Prometheus配置
export PROM_URL="http://localhost:9090"

# 数据库配置
export DB_HOST="192.168.123.29"
export DB_PORT="3306"
export DB_USER="root"
export DB_PASSWORD="123456"
export DB_NAME="bigdata"

# Redis配置
export REDIS_HOST="192.168.123.29"
export REDIS_PORT="6379"
export REDIS_PASSWORD=""
export REDIS_DB="0"

# 通知配置
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxx"
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
export SLACK_WEBHOOK="https://hooks.slack.com/services/xxx"

# 运行参数
export LOG_LEVEL="INFO"
```

## 使用方法

### 初始化

```bash
python -m ai_ops setup
```

### 执行巡检

```bash
# 执行巡检，写入数据库
python -m ai_ops inspect

# 执行巡检并发送通知
python -m ai_ops inspect --notify
```

### 定时巡检

```bash
# 每5分钟执行一次巡检
python -m ai_ops schedule --health-interval 300
```

### Web界面

```bash
# 启动Web服务器
python -m ai_ops serve --host 0.0.0.0 --port 8000

# 访问仪表盘
# http://localhost:8000/
```

## 新增功能：日志类型展示页面

### 页面访问

访问日志类型分析页面：
```
http://localhost:8000/log-types
```

### 页面功能

#### 1. 统计卡片
- **总日志数**: 显示最近N分钟的总日志数量
- **警告级别**: 显示警告级别的错误数量
- **严重错误**: 显示严重级别的错误数量
- **业务模块**: 显示涉及的业务模块数量

#### 2. 图表展示
- **业务模块分布**: 饼图显示各业务模块的错误分布
- **错误类型分布**: 柱状图显示各类错误的数量
- **严重程度分布**: 饼图显示不同严重程度的错误分布

#### 3. 最近错误列表
- 显示最近的错误日志
- 包含时间、业务模块、错误类型、严重程度等信息
- 支持查看错误详情

#### 4. 详细错误信息
- 显示过滤后的详细错误信息
- 包含业务分析结果和处理建议
- 支持按业务模块、错误类型、严重程度过滤

#### 5. 交互功能
- **时间范围选择**: 可选择最近1分钟、5分钟、10分钟、30分钟
- **过滤功能**: 支持按业务模块、错误类型、严重程度过滤
- **自动刷新**: 支持自动刷新数据（每30秒）
- **手动刷新**: 支持手动刷新数据

### 页面特性

#### 1. 实时数据
- 页面自动从后端API获取最新数据
- 支持实时监控日志变化

#### 2. 响应式设计
- 适配不同屏幕尺寸
- 移动端友好的界面设计

#### 3. 交互体验
- 悬停效果和动画
- 模态框显示详细信息
- 表格排序和分页

#### 4. 错误处理
- 网络错误提示
- 数据加载失败处理
- 友好的错误信息展示

### 使用场景

#### 1. 实时监控
- 监控系统错误趋势
- 快速发现异常情况
- 实时了解系统健康状态

#### 2. 故障排查
- 查看具体错误详情
- 分析错误分布情况
- 获取处理建议

#### 3. 业务分析
- 分析业务模块错误情况
- 识别问题频发的模块
- 优化系统架构

#### 4. 运维决策
- 基于数据做出运维决策
- 制定优化计划
- 评估系统稳定性

### 技术实现

#### 1. 前端技术
- **HTML5**: 页面结构
- **CSS3**: 样式和动画
- **JavaScript ES6+**: 交互逻辑
- **Bootstrap 5**: UI框架
- **Chart.js**: 图表库

#### 2. 后端API
- `/api/log-recent-analysis`: 获取最近日志分析
- `/api/log-business-modules`: 获取业务模块统计
- `/api/log-error-details`: 获取详细错误信息

#### 3. 数据流
```
用户操作 → JavaScript → API调用 → 后端处理 → 数据返回 → 页面更新
```

### 部署说明

#### 1. 静态文件
确保以下静态文件存在：
```
static/
├── log-types.html          # 日志类型页面
├── js/
│   └── log-types.js        # 页面JavaScript
└── css/
    ├── bootstrap.min.css   # Bootstrap样式
    ├── bootstrap-icons.css # 图标样式
    └── dashboard.css       # 自定义样式
```

#### 2. 依赖库
确保以下JavaScript库可用：
- `bootstrap.min.js`: Bootstrap交互组件
- `chart.min.js`: Chart.js图表库

#### 3. 访问路径
页面通过以下路径访问：
```
GET /log-types
```

### 自定义配置

#### 1. 刷新间隔
修改自动刷新间隔：
```javascript
// 在log-types.js中修改
setInterval(() => {
    this.refreshData();
}, 30000); // 30秒
```

#### 2. 时间范围
修改默认时间范围：
```javascript
// 在log-types.js中修改
const response = await fetch('/api/log-recent-analysis?minutes=5&include_details=true');
```

#### 3. 图表配置
修改图表样式和配置：
```javascript
// 在log-types.js中修改图表选项
options: {
    responsive: true,
    plugins: {
        legend: { position: 'bottom' },
        title: { display: true, text: '图表标题' }
    }
}
```

## 架构设计

```
┌─────────────────┐    ┌─────────────────┐
│   Prometheus    │    │     Redis       │
│   (Metrics)     │    │    (Cache)      │
└─────────────────┘    └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────────────┐
│                    AI-Ops Core                 │
│  ┌─────────────┐  ┌─────────────┐            │
│  │Health Checks│  │Data Storage │            │
│  │             │  │             │            │
│  │• CPU/Memory │  │• MySQL DB   │            │
│  │• Disk Usage │  │• Results    │            │
│  │• Network    │  │• Summaries  │            │
│  │• Services   │  │             │            │
│  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────────────┐
│                    Web Interface               │
│  ┌─────────────┐  ┌─────────────┐            │
│  │ Dashboard   │  │   Reports   │            │
│  │             │  │             │            │
│  │• Real-time  │  │• Statistics │            │
│  │• Charts     │  │• Trends     │            │
│  │• Alerts     │  │• History    │            │
│  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────────────┐
│                    Notifications               │
│  ┌─────────────┐  ┌─────────────┐            │
│  │   DingTalk  │  │   Feishu    │            │
│  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────┘
```

## 性能优化

- **缓存机制**: Redis缓存减少重复查询
- **批量处理**: 批量插入数据库提升性能
- **异步通知**: 使用线程池并行发送通知
- **性能监控**: 内置操作计时器，记录各阶段耗时

## 错误处理

- **优雅降级**: 当组件不可用时使用备用方案
- **详细日志**: 完整的操作日志和错误追踪
- **异常隔离**: 单个异常不影响整体流程
- **重试机制**: HTTP请求支持指数退避重试

## 开发

```bash
# 代码格式化
black ai_ops/

# 类型检查
mypy ai_ops/

# 运行测试
pytest tests/
```

## 许可证

MIT License
