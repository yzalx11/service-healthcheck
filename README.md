# 企业内网服务健康巡检

当前阶段提供环境、团队和服务的 CRUD，以及主动巡检和结果入库。参见 [开发设计笔记](DESIGN.md)。

## 本地运行

在项目根目录运行 PowerShell。首次搭建时创建独立 Conda 环境并安装依赖。

```powershell
conda create --prefix .\.conda python=3.12 pip -y
conda activate .\.conda
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

若 Windows 的 `conda.exe` 无法启动，可以在上述创建命令中用 `& D:\Anaconda3\python.exe -m conda` 代替 `conda`，然后直接用 `& .\.conda\python.exe` 执行后续 Python 命令。

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
