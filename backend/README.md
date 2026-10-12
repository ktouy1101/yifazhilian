# 医法智联后端：本地合成数据演示

Python + FastAPI + 本机 SQLite；API 前缀 `/api/v1`。SQLite 来自 Python 标准库，无需安装数据库服务，也不需要数据库账号。默认没有外部 AI、短信、电话、云 OCR 或任何付费服务。数据库文件**没有加密**，只能输入虚构数据，不得导入真实患者资料。授权、会话、体征、SOS 与审计事件重启后保留。

## 启动

在本目录执行（Python 3.11+）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/docs> 查看完整的请求/响应契约。微信开发者工具中仅本地调试时勾选“不校验合法域名”；真机和发布版必须接入 HTTPS 合法域名，不能直接使用 localhost。不要将演示服务绑定公网。`YIFAZHILIAN_MODE` 只接受 `demo`，其他值启动失败。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

已在 Python 3.14.8、FastAPI 0.143.0、Pydantic 2.14.1、Uvicorn 0.54.0、pytest 9.1.1、httpx 0.28.1 上验证：14 项测试通过，覆盖原有安全边界、跨重开持久化与撤回、令牌摘要/到期、并发幂等、整轮消息事务回滚及活跃 WAL 备份恢复。所有测试注入临时文件数据库，并拦截默认库连接，绝不清空或重置日常演示数据库。当前 Starlette 会对 httpx 测试适配器发出一条弃用提醒，不影响这些测试；依赖复现可使用 `pip install -r requirements-lock.txt`（包括测试依赖）。

## 本机数据库与备份

默认路径是项目内 `backend/data/yifazhilian.db`，与启动时工作目录无关；第一次需要存储的请求自动建库、建表并插入三条合成用户。只有导入模块或访问 `/health` 不会创建数据库。覆盖路径时先设置环境变量再启动服务，建议使用绝对路径：

```powershell
$env:YIFAZHILIAN_DB_PATH = Join-Path $PWD 'data\my-demo.db'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

相对覆盖路径按进程工作目录解释。移除当前 PowerShell 的覆盖可执行 `Remove-Item Env:YIFAZHILIAN_DB_PATH`。数据目录以及 `*.db`、`*.db-wal`、`*.db-shm` 等运行时文件不得提交 Git。只用于本机普通磁盘，避免把活跃数据库放到共享网络盘或同步盘。

`app/schema.sql` 定义关系表：`users`、`sessions`、`consents`、`consent_fields`、`conversations`、`messages`、`message_sources`、`vitals`、`emergency_events`、`audit_events`。没有整库 JSON 快照；消息和体征均按独立行保存。令牌仅保存 SHA-256 摘要，随机原令牌只在登录响应中返回。授权表保存当前用途状态，授予/撤回操作另存事件；尚不是完整版本化、不可篡改的同意证据链。

每次事务新建并关闭当前线程连接，开启外键、WAL、10 秒 busy timeout 和 `synchronous=FULL`。写操作使用 `BEGIN IMMEDIATE`；授权检查与消息、来源和审计写入在同一事务中，撤回与写入按提交顺序生效。SQLite 唯一约束保证 `(user_id,source,sample_id)` 和 `(user_id,idempotency_key)` 去重。当前只在事务内运行快速本地模板；未来联网模型必须改用任务机制并再次检查授权，不能把慢外部调用直接放进写事务。

令牌和授权仍各 1 小时到期，重启不会重置到期时间；撤回状态跨重启保留。持久化也不会使模拟 SOS 获得真实通知或回执。

运行期间不要只复制 `.db` 主文件：最新已提交数据可能仍在 WAL 中。使用附带的 SQLite backup API 命令生成一致快照；源库与服务读取同一个环境变量，目标必须是不存在的新文件：

```powershell
.\.venv\Scripts\python.exe -m app.backup --output .\data\backup-20261013-01.db
```

备份会纳入已提交 WAL 页面并执行 `PRAGMA quick_check`，不会覆盖已有备份。恢复时先停止服务，再把 `YIFAZHILIAN_DB_PATH` 指向备份文件并启动；原数据库得以保留。备份同样是未加密的合成数据文件，勿上传仓库。正式备份计划、加密、恢复演练和保留期限仍需补齐。

## 实际实现

15 个核心业务端点（另有 `/health`）：

|方法|路径（均有 /api/v1 前缀）|主要输入 / 输出|
|---|---|---|
|POST|/auth/demo-login|role, demo_alias? → access_token, user|
|GET|/users/me|Bearer → id, role, display_name, synthetic|
|GET|/consents|Bearer → items|
|POST|/consents|scope, granted:true → 用途、字段、接收方、版本、期限|
|DELETE|/consents/{scope}|scope → granted:false|
|POST|/conversations|domain:medical/legal → id|
|GET|/conversations/{id}|id → 本人会话与历史|
|POST|/conversations/{id}/messages|text → answer,sources,provider,disclaimer|
|GET|/records|records_read 授权 → 虚构占位病历|
|GET|/medications|Bearer → 虚构占位药品，无真实处方|
|GET|/vitals|vitals 授权 → 本人体征样本|
|POST|/vitals|sample_id,source,kind,value,unit,measured_at,quality → id,alert|
|POST|/emergencies|idempotency_key → id,status:received,delivery:mock|
|GET|/emergencies/{id}|id → 本人演示事件|
|GET|/audit-events|Bearer → 本人不含正文的持久化事件元数据，tamper_evident:false|

登录仅允许固定合成账号 `demo-patient-001/002`、`demo-volunteer-001`；默认 patient/001。不是真实微信认证，也不证明使用者身份。演示用户之间的所有权隔离用于验证业务逻辑，不能视为生产认证安全。

除登录和健康检查，所有端点需 `Authorization: Bearer <access_token>`。禁止客户端传 user_id/openid；由令牌推导资源所有者。志愿者无病历、体征、患者会话及患者授权权限。令牌与授权各 1 小时到期；授权 scope 为 `ai_medical`、`ai_legal`、`vitals`、`records_read`，撤回后下一次请求立即拒绝。紧急演示独立于可选 AI 授权。

`AIProvider` 是可替换协议，当前只有 `MockProvider`；医学和法律各有独立本地小语料库，使用关键词检索并展示来源。**这不是向量 RAG、真实大模型或法律专业意见**。无来源时拒答；对话文本不交给外部模型，也不会触发工具或修改权限。后续模型适配器须实现同一个协议，而不是让业务路由依赖某一家厂商。

体征 `source` 仅接受 `demo_device`；`(user,source,sample_id)` 唯一，同样本重试返回原结果，冲突返回 409。校验单位、范围、带时区时间（24 小时内、未来最多 5 分钟）和质量。阈值只演示 UI 告警，**未经临床验证**，无标记不代表安全。演示设备没有生产级设备签名验证。

SOS 按用户和幂等键去重，只记录 `received/mock`；永不声称已拨号、已通知、已接通或已获响应。实际呼叫必须用病区呼叫铃、医护联系方式等可确认渠道。

## 上线前必须补齐

- 微信 `code → code2session` 服务端交换、医院身份绑定、防冒用、会话吊销与速率限制；不能保留公开 demo 登录。
- 根据并发量与部署方式评估生产数据库（如 PostgreSQL）、密钥管理、敏感字段加密、对象存储鉴权、备份制度、保留/删除制度、审计防篡改及生产监控。本机 SQLite 持久化和普通审计行不是合规存证。
- 分用途与字段的真正告知/同意，必要场景单独同意，撤回后的任务取消、外部处理者同步，以及法定留存例外；L1/L2/L3 只是产品预设，不能代表法定分类。
- 经专业审核、版本化的双知识库、向量检索、外部适配器隐私评估/去标识化/传输边界、人工接管、诊疗与法律风险评测。
- 病历 OCR、用户核验与可追溯原件；现阶段只有合成病历占位，不宣称具备 OCR 或真实病历存取。
- 知情同意文书模板、医师解释、身份核验、签署意愿、可靠电子签名与可信时间/证据链；画签名不等于可靠电子签名。现阶段没有文书签署 API。
- 真实设备绑定与验签、乱序处理、告警分级/去抖/持续性、多样本临床规则与医护确认闭环。
- 多对象实际呼叫、呼叫渠道状态机、回执、超时升级和可用性演练；不要把接口接收成功当成救援成功。
- 志愿者实名审核、培训、值班/区域、只含导诊任务的最小权限、退出与人工支持；志愿者不是执业医师。

任何真实医疗健康信息都属于敏感信息范围内的重点保护对象；脱敏展示不能替代底层加密、权限和合法处理依据。演示代码不构成上线合规证明。
