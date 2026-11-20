# 企业内网服务健康巡检

当前阶段提供环境、团队和服务的 CRUD，以及主动巡检和结果入库。参见[开发设计笔记](DESIGN.md)。

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

预期返回 `outcome: healthy` 和 `status_code: 200`。将 `health_path` 改为不存在的路径可验证 `http_error`。默认允许探测 `http://127.0.0.1:9001`。如需测试其他受信任的源，启动 Django 前用空格分隔配置 `PROBE_ALLOWED_ORIGINS`，每个源由协议、主机和可选端口组成，省略末尾斜杠。

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
& .\.conda\python.exe manage.py test inspection.test_tasks
& .\.conda\python.exe test_celery_chain.py --redis-server 'D:\redis\Redis-x64-3.2.100\redis-server.exe'
```

也可以打开 VS Code 的「运行和调试」，选择「验收：Django 任务测试」或「验收：Celery 完整链路」，按 `Ctrl+F5` 运行。链路测试会提示 Redis 程序路径，本机可直接使用默认值。Django 测试通过 `manage.py test` 加载配置和临时数据库。

`test_celery_chain.py` 会临时启动 Redis、单进程 worker 和独立 beat。它只在测试子进程中把调度间隔缩短为两秒，读回临时数据库中的加密 Token 和健康率后自动关闭服务。正式调度时刻由 `inspection/test_tasks.py` 单独验证。项目限制 Celery 和 Kombu 在 5.6 系列，以兼容这台 Windows 机器的 Redis 3.2。该组合用于本地验收。

Celery 的受支持部署环境可使用 Linux 和当前受维护的 Redis。在 Linux 或 WSL2 的 Linux 文件系统中准备一份项目和 Python 环境，安装依赖并迁移数据库。将 Django、worker 和 beat 指向同一份数据库。启动 Redis 后，在 worker 和 beat 的环境中设置 `CELERY_BROKER_URL`，本机 Redis 可沿用默认 `redis://127.0.0.1:6379/0`。在 worker 环境中配置 `PROBE_TOKEN_ENCRYPTION_KEY`。

分别启动以下两个进程。

```bash
python -m celery -A healthcheck worker --loglevel=INFO
python -m celery -A healthcheck beat --loglevel=INFO
```

无需等到整点即可验证 Redis 转发。在相同环境执行 `python manage.py shell -c "from inspection.tasks import rotate_probe_tokens, write_daily_health_rates; rotate_probe_tokens.delay(); write_daily_health_rates.delay()"`，检查 worker 日志收到两项任务。Beat 按北京时间在每天 00:00 调度日报，并在 00:00、08:00、16:00 调度 Token 轮换。
