# AI-Ops 项目结构重组

## 新的项目结构

```
ai_ops/
├── app/                          # 主应用目录
│   ├── __init__.py
│   ├── main.py                   # FastAPI应用主文件
│   ├── core/                     # 核心配置
│   │   ├── __init__.py
│   │   └── config.py             # 配置设置
│   ├── models/                   # 数据模型
│   │   ├── __init__.py
│   │   └── db.py                 # 数据库操作
│   ├── services/                 # 业务逻辑服务
│   │   ├── __init__.py
│   │   ├── prom_client.py        # Prometheus客户端
│   │   ├── log_analyzer.py       # 日志分析器
│   │   ├── inspection.py         # 巡检引擎
│   │   ├── performance_monitor.py # 性能监控
│   │   ├── notifiers.py          # 通知服务
│   │   └── ai_client.py          # AI客户端
│   ├── routers/                  # API路由
│   │   ├── __init__.py
│   │   └── api.py                # API端点
│   ├── schemas/                  # Pydantic模型
│   │   └── __init__.py
│   └── utils/                    # 工具函数
│       ├── __init__.py
│       ├── http_client.py        # HTTP客户端
│       ├── es_diagnostic.py      # ES诊断
│       └── check_syntax.py       # 语法检查
├── static/                       # 静态资源
│   ├── css/
│   ├── js/
│   └── fonts/
├── main_new.py                   # 新的主入口文件
├── start_new.py                  # 新的启动脚本
├── requirements.txt              # 依赖文件
└── README.md                     # 项目说明
```

## 使用方法

### 启动Web服务
```bash
python start_new.py serve
```

### 执行巡检
```bash
python start_new.py inspect
```

### 定时巡检
```bash
python start_new.py schedule
```

### 数据库初始化
```bash
python start_new.py setup
```

## 主要改进

1. **模块化结构**: 按照FastAPI最佳实践组织代码
2. **清晰分层**: 分离了核心配置、数据模型、业务服务、API路由等
3. **易于维护**: 每个模块职责明确，便于扩展和维护
4. **标准化**: 符合Python项目标准结构

## 迁移说明

- 原有的 `main.py` 保持不变，作为向后兼容
- 新的入口文件为 `main_new.py`
- 所有导入路径已更新为新的模块结构
- 静态资源和配置文件位置保持不变
