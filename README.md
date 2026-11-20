# 企业内网服务健康巡检

本项目实现笔试方案 C。运行方式与设计取舍见下文及 [开发设计笔记](DESIGN.md)。

## 题目要求与验收

在项目根目录、依赖安装完成后执行。以下命令中的 `python` 指项目 Conda 环境的解释器。也可以在 VS Code「运行和调试」中选择「验收：Django 全量测试」或「验收：Celery 完整链路」，按 `Ctrl+F5`。

| 题目要求 | 实现位置 | 验收命令 |
| --- | --- | --- |
| 服务、环境、团队模型及外键 | [模型](inspection/models.py) | `python manage.py migrate`，再运行 `python manage.py test inspection.test_service_api` |
| CRUD 和按需 HTTP 巡检 | [接口](inspection/views.py)、[探测](inspection/probes.py) | `python manage.py test inspection.test_service_api inspection.test_probe_auth` |
| 每 8 小时轮换 Token 并加密记录 | [任务](inspection/tasks.py)、[凭据](inspection/probe_tokens.py) | `python manage.py test inspection.test_tasks inspection.test_probe_auth` |
| 每日 00:00 按环境和团队统计健康率并入库 | [调度](healthcheck/celery.py)、[任务](inspection/tasks.py) | `python manage.py test inspection.test_tasks`，再运行 [Celery 完整链路验收](#验收-redisworker-与-beat) |
| Django 请求耗时中间件 | [中间件](healthcheck/middleware.py) | `python manage.py test inspection.test_request_timing` |

北京时间 00:00 的近 24 小时对应前一个自然日。日报固定该日期的边界，方便停机后补跑。已生成的日报可通过 [只读日报列表](#只读日报列表) 查询。

## 本地运行

在项目根目录运行PowerShell。首次搭建时创建独立 Conda 环境并安装依赖。

```powershell
conda create --prefix .\.conda python=3.12 pip -y
conda activate .\.conda
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

若 Windows的 `conda.exe` 无法启动，可以在上述创建命令中用 `& D:\Anaconda3\python.exe -m conda` 代替 `conda`，然后直接用 `& .\.conda\python.exe` 执行后续 Python 命令。

## 接口

环境、团队、服务分别在 `/api/environments/`、`/api/teams/`、`/api/services/`。集合支持 GET 和 POST，详情地址加上 ID 后支持 GET、PUT、PATCH 和 DELETE。环境名称取 `dev`、`test` 或 `prod`。当前 API 面向本地验收。

### 巡检历史

使用 `GET /api/services/{id}/inspections/` 查看指定服务的巡检记录。每条记录含巡检时间、结果类型、目标 HTTP 状态码和探测耗时。超时或连接失败时，目标状态码为 `null`。列表按时间倒序排列，时间相同时较新的记录 ID 排在前面。默认每页 20 条，可用 `?page=2` 查看第二页。服务存在但没有历史时返回空列表，服务不存在时返回 404。

支持组合筛选。三个参数均可省略，也可只提供一个时间边界。

| 参数 | 用途 |
| --- | --- |
| `outcome` | `healthy`、`http_error`、`timeout` 或 `connection_error` |
| `since` | 起始时间，包含该时刻 |
| `until` | 结束时间，排除该时刻 |

时间参数使用 ISO 8601。建议带时区偏移或 `Z`，省略时区时按项目时区 `Asia/Shanghai` 解释。两个边界同时提供时，`until` 必须晚于 `since`，否则返回 400。以下示例查询北京时间 09:00 至 10:00 之间的超时记录。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/services/1/inspections/?outcome=timeout&since=2026-11-21T01:00:00Z&until=2026-11-21T02:00:00Z'
```

在 VS Code「运行和调试」中选择「验收：巡检历史」，按 `Ctrl+F5`，预期显示 `Ran 7 tests` 和 `OK`。也可执行 `python manage.py test inspection.test_inspection_history`。测试无需启动 Redis。

### 按需触发巡检

在另一个终端启动用于验收的本地 HTTP 服务。`/` 返回 200，一个不存在的路径返回 404。

```powershell
& .\.conda\python.exe -m http.server 9001 --bind 127.0.0.1
```

在第三个终端创建记录，然后触发一次巡检。

```powershell
$api = 'http://127.0.0.1:8000/api'
$environment = Invoke-RestMethod "$api/environments/" -Method Post -ContentType 'application/json' -Body '{"name":"dev"}'
$team = Invoke-RestMethod "$api/teams/" -Method Post -ContentType 'application/json' -Body '{"name":"Platform"}'
$service = Invoke-RestMethod "$api/services/" -Method Post -ContentType 'application/json' -Body (@{
    name = 'demo'
    environment = $environment.id
    team = $team.id
    origin = 'http://127.0.0.1:9001'
    health_path = '/'
} | ConvertTo-Json)
Invoke-RestMethod "$api/services/$($service.id)/check/" -Method Post
```

预期返回 `outcome: healthy` 和 `status_code: 200`。将 `health_path` 改为不存在的路径可验证 `http_error`。默认允许探测 `http://127.0.0.1:9001`。如需测试其他受信任的源，启动 Django 前用空格分隔配置 `PROBE_ALLOWED_ORIGINS`。每个源由协议、主机和可选端口组成。比较时忽略协议和主机名的大小写以及单个尾斜杠。省略端口和显式写出默认端口仍分别匹配。

支持 `http://paysvc:8080` 这类内网短主机名。运行 Django 的环境需要能解析该名称。主机名末尾的点会保留，`paysvc` 和 `paysvc.` 分别匹配白名单。Origin 内的空白和控制字符会被拒绝。

国际化域名按 Python 内置的 IDNA2003 规则匹配。Unicode 域名与按该规则生成的 ASCII 写法等价。部分域名在 IDNA2008 下的结果不同，例如 `straße.de` 在这里匹配 `strasse.de`，而 IDNA2008 的 ASCII 写法是 `xn--strae-oqa.de`。

修改 `PROBE_ALLOWED_ORIGINS` 或 `MANAGED_PROBE_ORIGIN` 后，可以运行 `python manage.py check` 检查配置。无效的白名单条目会报 `inspection.W001` 并被忽略，无效的受控目标会报 `inspection.W002` 并禁用受控探测。告警以配置名开头，省略原始值。更新到此版本后运行 `python manage.py migrate` 应用服务模型字段迁移。

## 只读日报列表

使用 `GET /api/reports/` 查看已入库的日报。三个查询参数都可省略，组合时取交集。

| 参数 | 格式 |
| --- | --- |
| `date` | 报表日期，`YYYY-MM-DD` |
| `environment` | `dev`、`test` 或 `prod` |
| `team` | 报表中的团队全名，精确匹配 |

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/reports/?date=2026-11-20&environment=dev&team=Site%20Operations'
```

每条记录返回日期、服务 ID、生成日报时的环境和团队、成功次数、总次数及 `health_rate`。健康率是 0 到 1 的比例，例如 `0.75` 表示 75%。没有巡检时为 `null`。结果按日期倒序、同一天按服务 ID 升序，每页 20 条。可继续使用 `page` 分页和 `format=json` 选择响应格式。未知查询参数会以 `unknown_parameters` 返回 400。合法筛选没有匹配记录时返回空列表，写请求返回 405。

在 VS Code「运行和调试」选择「验收：只读日报列表」，按 `Ctrl+F5`。预期显示 `Ran 6 tests` 和 `OK`。专项测试用临时数据库准备日报，无需启动 Django 开发服务或 Redis。

## 第二阶段验收

先安装更新后的依赖并执行 `python manage.py migrate`。在 Windows 的 Conda 终端可单独执行任务，验证算法和数据库写入。先在 API 创建至少一个服务。以下命令生成仅供本次验收使用的加密密钥，避免直接输出密钥或 Token。

```powershell
$env:PROBE_TOKEN_ENCRYPTION_KEY = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python manage.py shell -c "from inspection.tasks import rotate_probe_tokens as task; print(task.run()); print(task.run())"
python manage.py shell -c "from inspection.tasks import write_daily_health_rates as task; from inspection.models import DailyHealthRate; print(task.run()); print([(r.date, r.environment_name, r.team_name, r.successful_checks, r.total_checks, r.health_rate) for r in DailyHealthRate.objects.all()])"
```

在首次运行的窗口，轮换任务返回更新的服务数，重复调用返回 `0`。当天刚产生的巡检数据要到次日才进入日报。补跑指定日期时，用 ISO 日期字符串调用 `task.run("YYYY-MM-DD")`。同一数据库长期运行时，请通过环境管理工具配置固定的加密密钥。

### 验收 Redis、worker 与 beat

Worker 和 beat 都随 `celery[redis]` 安装，分别作为两个进程运行。`[redis]` 会安装 Python Redis 客户端。Broker 是消息中转的角色，本项目由独立运行的 Redis 服务端承担。

在本机 PowerShell 通过以下命令运行测试。

```powershell
& .\.conda\python.exe -m pip install -r requirements.txt
& .\.conda\python.exe manage.py test inspection
& .\.conda\python.exe test_celery_chain.py --redis-server 'D:\redis\Redis-x64-3.2.100\redis-server.exe'
```

也可以打开 VS Code 的「运行和调试」，选择「验收：Django 全量测试」或「验收：Celery 完整链路」，按 `Ctrl+F5` 运行。Django 全量测试预期显示 `OK`，无需提前启动 Django。链路测试会提示 Redis 程序路径，本机可直接使用默认值。

`test_celery_chain.py` 会临时启动 Redis、单进程 worker 和独立 beat。它只在测试子进程中把调度间隔缩短为两秒，读回临时数据库中的加密 Token 和健康率后自动关闭服务。正式调度时刻由 `inspection/test_tasks.py` 单独验证。项目限制 Celery 和 Kombu 在 5.6 系列，以兼容这台 Windows 机器的 Redis 3.2。该组合用于本地验收。

Celery 的受支持部署环境可使用 Linux 和当前受维护的 Redis。在 Linux 或 WSL2 的 Linux 文件系统中准备一份项目和 Python 环境，安装依赖并迁移数据库。将 Django、worker 和 beat 指向同一份数据库。启动 Redis 后，在 worker 和 beat 的环境中设置 `CELERY_BROKER_URL`，本机 Redis 可沿用默认 `redis://127.0.0.1:6379/0`。在 worker 环境中配置 `PROBE_TOKEN_ENCRYPTION_KEY`。

分别启动以下两个进程。

```bash
python -m celery -A healthcheck worker --loglevel=INFO
python -m celery -A healthcheck beat --loglevel=INFO
```

无需等到整点即可验证 Redis 转发。在相同环境执行 `python manage.py shell -c "from inspection.tasks import rotate_probe_tokens, catch_up_daily_health_rates; rotate_probe_tokens.delay(); catch_up_daily_health_rates.delay()"`，检查 worker 日志收到两项任务。Beat 按北京时间在 00:00、08:00、16:00 调度 Token 轮换，每小时整点检查并补跑缺失的日报，每次最多补七天。

受控 Token 认证默认关闭。可设置 `MANAGED_PROBE_ORIGIN=http://127.0.0.1:8000`，将该地址同时加入 `PROBE_ALLOWED_ORIGINS`，并给 Django 和 worker 配置同一个 `PROBE_TOKEN_ENCRYPTION_KEY`。创建服务后，把它的源设为该地址、路径设为 `/probe-health/<服务 ID>/`。首次轮换后触发巡检，预期目标返回 204。Django 验收配置已包含真实 HTTP 测试，验证新 Token 可用、旧 Token 被拒绝。

## 第三阶段验收

在 VS Code「运行和调试」中选择「验收：请求耗时中间件」，按 `Ctrl+F5`。预期显示 `Ran 3 tests` 和 `OK`。测试验证 200、404 和 500 的耗时响应头及日志。

也可在项目根目录执行：

```powershell
& .\.conda\python.exe manage.py test inspection.test_request_timing
```

手动验收时，启动此分支的 Django 后，分别请求 API 首页和不存在的路径。

```powershell
curl.exe -i http://127.0.0.1:8000/api/
curl.exe -i http://127.0.0.1:8000/missing-route/
```

两次响应都应包含形如 `Server-Timing: app;dur=1.235` 的响应头，单位为毫秒。Django 终端会打印对应的 `method`、`route`、`status` 和 `duration_ms`。404 的路由显示为 `<unmatched>`。验收无需启动 Redis、worker 或 beat。
