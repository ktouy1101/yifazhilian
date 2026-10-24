# 医法智联后端：本地服务与病历管理

Python + FastAPI + 本机 SQLite；API 前缀 `/api/v1`。SQLite 来自 Python 标准库，无需安装数据库服务，也不需要数据库账号。无配置时使用本地模板，也支持显式配置外部 AI；没有短信、电话或云 OCR。M03按用户需求接收本人检验单和病历照片，本地识别、核对并归档，不送入外部AI。数据库文件**没有加密**，生产身份与部署保护仍待完善。授权、会话、体征、SOS、病历及审计事件重启后保留；自动化验证仅用合成样本。

## 启动

在本目录执行（Python 3.11+）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\start-backend.ps1
```

启动脚本按小程序 `baseURL` 选择本机监听地址，并检查服务就绪；重复运行会复用已连接的服务。当前契约地址为 <http://192.168.199.126:8000/docs>。每次重启电脑后重新运行脚本，打开微信开发者工具不会自动启动 Python 后端。微信开发者工具的本地调试可使用已有开发配置；真机和发布版必须接入 HTTPS 合法域名，不能直接使用 localhost。不要将演示服务绑定公网。

## 模型配置

### M03本地OCR（独立于问答模型）

在工程根运行 `./setup-ocr.ps1`，使用uv创建Python 3.12的`backend/.ocr-venv`并安装`requirements-ocr-lock.txt`，包含RapidOCR与本地模型；主后端仍使用原`.venv`。OCR运行在无云调用的子进程，75秒超时，最多2个并行识别；缺环境、超时与识别失败均可恢复手填。更新后端代码后需要重启服务。当前接口版本0.9.0、SQLite schema 8，新增表不替换M02/M11旧数据。入口、私有图像与版本接口、验证结果见[M03使用与验收](../docs/m03-acceptance.md)。

### 问答模型

复制 `.env.example` 为本机 `.env`，设置 `YIFAZHILIAN_AI_PROVIDER=openai_compatible`、服务地址、模型、显示名称和密钥，再重启服务。环境变量优先于文件；文件只支持简单 `KEY=VALUE`，不执行命令或变量插值。`mock` 为免费离线模式，外部接口使用对应平台的账户额度，不会自动重试计费请求。

DeepSeek 当前示例配置：`YIFAZHILIAN_AI_BASE_URL=https://api.deepseek.com`、`YIFAZHILIAN_AI_MODEL=deepseek-flash`、`YIFAZHILIAN_AI_DISPLAY_NAME=DeepSeek`；密钥仅放 `YIFAZHILIAN_AI_API_KEY`。接口及模型名依据 [DeepSeek 官方文档](https://api-docs.deepseek.com/) 核对。适配器使用通用 `/chat/completions` 协议；换服务时设置相应的 HTTPS Base URL、模型、名称和密钥即可，特殊协议另实现 `AIProvider`。密钥不得放在前端、URL、Git、错误响应或日志中；`.env` 已被忽略。

小程序进入“我的 → 设置 → 连接本机服务”，读取服务器的接收方及版本告知后，再分别授权健康/法律问答。授权只对当前服务配置有效；变更接收方或版本必须重新授权，不自动迁移旧授权。请求超时和额度/鉴权错误明确返回失败；不会回退成本地模板冒充在线成功。数据仍限合成演示，真实业务还需完成供应商评估及敏感数据保护。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

已在 Python 3.14.8、FastAPI 0.143.0、Pydantic 2.14.1、Uvicorn 0.54.0、pytest 9.1.1、httpx 0.28.1 上验证；当前后端全量 **159 项通过**，覆盖原有安全边界、跨重开持久化与撤回、令牌摘要/到期、并发幂等、整轮消息事务回滚、活跃 WAL 备份恢复，以及 M05/M06 双智能体。所有测试注入临时文件数据库，并拦截默认库连接，绝不清空或重置日常演示数据库。当前 Starlette 会对 httpx 测试适配器发出一条弃用提醒，不影响这些测试；依赖复现可使用 `pip install -r requirements-lock.txt`（包括测试依赖）。

2026-10-14 接入外部模型后，增加24项配置/适配器测试、13项授权与并发撤回测试，原14项测试仍通过；前端11项测试通过。测试使用假凭据、MockTransport及临时数据库，不调用真实模型或日常数据库。另用一次仅含合成法律问题的真实 DeepSeek 请求验证了 HTTP 200、回复及本机历史保存，并确认撤回后的下一次请求为403；该验收未启动常驻后端，也未完成微信真机联调。

## 本机数据库与备份

默认路径是项目内 `backend/data/yifazhilian.db`，与启动时工作目录无关；第一次需要存储的请求自动建库、建表并插入三条合成用户。只有导入模块或访问 `/health` 不会创建数据库。覆盖路径时先设置环境变量再启动服务，建议使用绝对路径：

```powershell
$env:YIFAZHILIAN_DB_PATH = Join-Path $PWD 'data\my-demo.db'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

相对覆盖路径按进程工作目录解释。移除当前 PowerShell 的覆盖可执行 `Remove-Item Env:YIFAZHILIAN_DB_PATH`。数据目录以及 `*.db`、`*.db-wal`、`*.db-shm` 等运行时文件不得提交 Git。只用于本机普通磁盘，避免把活跃数据库放到共享网络盘或同步盘。

`app/schema.sql` 定义关系表：`users`、`sessions`、`consents`、`consent_fields`、`conversations`、`messages`、`message_metadata`、`vitals`、`emergency_events`、`audit_events`。没有整库 JSON 快照；消息和体征均按独立行保存。令牌仅保存 SHA-256 摘要，随机原令牌只在登录响应中返回。授权表保存当前用途状态，授予/撤回操作另存事件；尚不是完整版本化、不可篡改的同意证据链。

每次事务新建并关闭当前线程连接，开启外键、WAL、10 秒 busy timeout 和 `synchronous=FULL`。写操作使用 `BEGIN IMMEDIATE`。模型请求前读取并校验用途、接收方、告知版本及授权快照；网络调用在事务外完成，保存和返回回复前在写事务中再次校验同一授权。撤回及重新授权会丢弃进行中的回复；已发送给外部服务的请求无法收回。SQLite 唯一约束保证 `(user_id,source,sample_id)` 和 `(user_id,idempotency_key)` 去重。

登录令牌按 30 天到期；健康、病历、外部 AI 授权也按用途记住 30 天，有效期内不重复弹告知，重启不会重置到期时间；撤回状态跨重启保留。退出或切换演示身份时调用 `POST /auth/logout` 删除当前 session 行，旧令牌立即 401，不必等到期。持久化也不会使模拟 SOS 获得真实通知或回执。

运行期间不要只复制 `.db` 主文件：最新已提交数据可能仍在 WAL 中。使用附带的 SQLite backup API 命令生成一致快照；源库与服务读取同一个环境变量，目标必须是不存在的新文件：

```powershell
.\.venv\Scripts\python.exe -m app.backup --output .\data\backup-20261013-01.db
```

备份会纳入已提交 WAL 页面并执行 `PRAGMA quick_check`，不会覆盖已有备份。恢复时先停止服务，再把 `YIFAZHILIAN_DB_PATH` 指向备份文件并启动；原数据库得以保留。备份同样是未加密的合成数据文件，勿上传仓库。正式备份计划、加密、恢复演练和保留期限仍需补齐。

## 实际实现

2026-10-17 新增 M11：任务领取、草稿/私有照片、提交快照、禁止自审、独立发布、停用、用户反馈和历史查看。API 均位于 `/api/v1/navigation`，具体字段、状态与使用步骤见 [M11接口及验收](../docs/m11-acceptance.md)。数据库版本5采用增量建表，照片使用 Pillow 校验与去元数据；安装锁定依赖后需重启旧后端进程。最新后端78项测试通过，全部使用临时数据库；不代表真实医院身份、现场实走或AR已验收。

16 个核心业务端点（另有 `/health`）：

|方法|路径（均有 /api/v1 前缀）|主要输入 / 输出|
|---|---|---|
|POST|/auth/demo-login|role, demo_alias? → access_token, user|
|POST|/auth/logout|Bearer → 204；删除当前令牌对应的 session 行，旧令牌立即 401；无令牌/已注销也幂等返回 204|
|GET|/users/me|Bearer → id, role, display_name, synthetic|
|GET|/consents|Bearer → items, policies（当前接收方与告知）|
|POST|/consents|scope, granted:true, recipient, policy_version → 用途、字段、接收方、版本、期限；外部AI要求精确匹配当前告知|
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

除登录和健康检查，所有端点需 `Authorization: Bearer <access_token>`。禁止客户端传 user_id/openid；由令牌推导资源所有者。志愿者无病历、体征、患者会话及患者授权权限。令牌与授权均按 30 天到期，有效期内重启不重复弹告知；授权 scope 为 `ai_medical`、`ai_legal`、`vitals`、`records_read`，撤回后下一次请求立即拒绝。紧急演示独立于可选 AI 授权。

`AIProvider` 是可替换协议，支持 `MockProvider` 与通用 OpenAI-compatible 适配器。医学和法律各有独立本地小语料库，使用关键词检索，检索结果只在服务端参与生成，不向聊天页展示“检索参考”。**这不是向量 RAG 或经专业核验的意见**。无来源时拒答；医学急症关键词直接显示联系病区医护的本地提示，两者均不调用外部模型。正常外部问答仅发送当前合成提问、系统边界及命中参考材料，不发送用户标识、病历、体征或历史；不提供工具调用。历史只保存在本机，本版本模型为单轮问答。

体征 `source` 仅接受 `demo_device`；`(user,source,sample_id)` 唯一，同样本重试返回原结果，冲突返回 409。校验单位、范围、带时区时间（24 小时内、未来最多 5 分钟）和质量。阈值只演示 UI 告警，**未经临床验证**，无标记不代表安全。演示设备没有生产级设备签名验证。

SOS 按用户和幂等键去重，只记录 `received/mock`；永不声称已拨号、已通知、已接通或已获响应。实际呼叫必须用病区呼叫铃、医护联系方式等可确认渠道。

## 上线前必须补齐

- 微信 `code → code2session` 服务端交换、医院身份绑定、防冒用、会话吊销与速率限制；不能保留公开 demo 登录。
- 根据并发量与部署方式评估生产数据库（如 PostgreSQL）、密钥管理、敏感字段加密、对象存储鉴权、备份制度、保留/删除制度、审计防篡改及生产监控。本机 SQLite 持久化和普通审计行不是合规存证。
- 分用途与字段的真正告知/同意，必要场景单独同意，撤回后的任务取消、外部处理者同步，以及法定留存例外；L1/L2/L3 只是产品预设，不能代表法定分类。
- 经专业审核、版本化的双知识库、向量检索、外部适配器隐私评估/去标识化/传输边界、人工接管、诊疗与法律风险评测。
- M03已实现用户上传原图、本地OCR、逐项核对、更正与版本回查，见[M03验收](../docs/m03-acceptance.md)；医院来源核验、复杂报告识别基准和生产保护仍待完成。
- 知情同意文书模板、医师解释、身份核验、签署意愿、可靠电子签名与可信时间/证据链；画签名不等于可靠电子签名。现阶段没有文书签署 API。
- 真实设备绑定与验签、乱序处理、告警分级/去抖/持续性、多样本临床规则与医护确认闭环。
- 多对象实际呼叫、呼叫渠道状态机、回执、超时升级和可用性演练；不要把接口接收成功当成救援成功。
- 志愿者实名审核、培训、值班/区域、只含导诊任务的最小权限、退出与人工支持；志愿者不是执业医师。

任何真实医疗健康信息都属于敏感信息范围内的重点保护对象；脱敏展示不能替代底层加密、权限和合法处理依据。演示代码不构成上线合规证明。

## 运行状态与安全开关（2026-10-23）

`GET /api/v1/health` 不再硬编码`"mode":"production"`，改为报告两个真实字段：

- `mode`：来自`YIFAZHILIAN_RUNTIME_MODE`，只接受`demo`（默认）或`production`；填其它值一律按`demo`处理，避免误报。
- `demo_auth`：来自`YIFAZHILIAN_DEMO_AUTH`（默认开）。开启时`/auth/send-code`固定`123456`并在响应里回显，任何能访问该端口的人都能以任意手机号登录；启动日志会打印一条 WARNING 提醒。

登录页目前走**手机号 + 验证码**（`/auth/send-code` → `/auth/phone-login`）。因此`YIFAZHILIAN_DEMO_AUTH=0`时必须先接入真实短信通道，否则验证码随机生成却无人能收到，等于无法登录；这是外部依赖，代码内无法自足。

法宝不可用时的降级默认仍是 **503 fail-closed**。若希望改为“回落本地演示库并明确标注”，设`YIFAZHILIAN_LEGAL_MCP_FALLBACK=1`：此时`retrieval`返回`sqlite_keyword_v1_fallback`，回答正文只来自本地演示语料，响应里附`fallback_notice`。

日志使用标准`logging`（`app.startup`/`app.api`），启动时输出一行`startup mode=… demo_auth=… ai=… legal_retrieval=…`，不记录 token、密钥或患者文本。`start-backend.ps1`以`-X utf8`启动，保证日志文件里的中文可读。CI 见[.github/workflows/ci.yml](../.github/workflows/ci.yml)：后端跑`pytest`，前端跑`node --test tests/`。

### 公开面收缩（2026-10-24）

- `GET /api/v1/health` 只返回 `{status, storage}`。模型、运行模式、演示登录开关等部署细节移到 `GET /api/v1/admin/runtime`（需审核员，非审核员 403），避免在公开接口上告诉别人“这里还能用固定验证码登录”。
- 消息接口不再返回 `suggestions`：追问建议字段已从响应和 `message_metadata` 中删除（`PUBLIC_METADATA_KEYS` 同步收窄）。
- 账号删除：`DELETE /api/v1/admin/users/{id}` 为**软删除**——写 `deleted_at`、撤销全部会话、清空手机号与 openid，用户行保留，审计记录因此不会出现悬空外键；不能删除当前登录账号。
- 登录仍只有手机号验证码与微信两条路：密码登录试做过一版，因为只能登录已有账号、不能建号，已按需求删除。

### 身份与能力（schema v10）

`GET /api/v1/users/me`多返回一个`capabilities`：`is_reviewer`、`is_volunteer`、`volunteer_status`、`volunteer_kinds`、`can_collect`、`can_help_legal`。全部由服务端按`user_roles`、`volunteer_profiles`、`navigation_memberships`当场计算，客户端只用来决定显示哪些入口，隐藏按钮不构成鉴权。

- 管理员只能由配置指定：`backend/admins.txt`（一行一个手机号，可提交进仓库、改动需评审）或环境变量`YIFAZHILIAN_ADMIN_PHONE`（逗号分隔），两者取并集；都没有则没有任何管理员，也没有自助注册路径。
- `GET /api/v1/admin/ping`是鉴权探针，非审核员返回 403；P3 的后台接口都挂在`/admin`下。
- 演示审核员账号（`demo-reviewer-001`）**只允许本机/测试客户端**登录：局域网调用`demo-login`会返回 403。`YIFAZHILIAN_DEMO_AUTH=0`时整个演示登录关闭。
- 角色与阶段计划见[身份与后台路线图](../docs/roles-roadmap.md)。


## M04 健康记录与用药（无设备版）

新增`/api/v1/health-management`：`GET /overview?day=YYYY-MM-DD`，`GET /summary?days=7|30`，`POST/PUT/DELETE /entries`，`POST/PUT/DELETE /plans`，`PUT /doses`，`POST/PATCH/DELETE /followups`（修改/删除路径带对象ID，doses按计划和时段唯一）。需本人患者令牌及`vitals`用途下的`health-records-1`授权，数据不送外部模型。时间带时区；服药日期按Asia/Shanghai计算。创建使用request_id，条目/计划修改及删除使用revision，服药提交还须携带plan_revision。

`GET /summary`只汇总本人在指定区间内的测量、身体感受、用药执行和未完成待办；区分已服用、已跳过、稍后处理、未记录和待记录，不计算依从率、不判断疗效；摘要由前端复制，不生成医院证明。

Schema v7新增健康记录、计划版本、服药记录与待办表；第一次升级把旧medications迁成暂停计划，需用户核对用量及时间后启用；旧vitals演示数据不导入。旧`POST/DELETE /medications`已返回410，避免产生新旧不同步记录；旧GET需新健康授权，只为兼容回查。手填测量不使用旧vitals接口的演示阈值。

详见[范围与验收](../docs/m04-acceptance.md)。本机SQLite与开发登录的限制依旧适用，真机日历、HTTPS部署与正式身份认证需另验。

## M07 知识库与引用（第一版）

Schema 8新增`knowledge_sources`与`knowledge_chunks`，服务启动时幂等写入演示知识源和片段；只有`published`且处于生效区间内的来源参与检索，医学/法律按域隔离。检索仍为SQLite关键词匹配，不引入向量库或外部检索服务。

`GET /api/v1/knowledge/search?domain=medical|legal&q=...&limit=1..5`需要登录，返回片段正文、来源标题、来源URL、版本、审核人、状态和生效日期；`POST /conversations/{id}/messages`会在同一授权下检索知识，但检索结果只在服务端参与生成，不再返回或保存来源，前端聊天页也不显示引用卡片。

第一版仍是演示：种子内容不是临床指南或官方法律数据库，未提供知识录入/审核后台、向量检索或知识图谱；真实使用前必须逐条核对官方原文、版本和有效期。可选法律只读MCP见下。测试见[知识库说明](../docs/m07-acceptance.md)。

可选法律 MCP（默认关闭）：设置`YIFAZHILIAN_LEGAL_MCP_COMMAND`、`YIFAZHILIAN_LEGAL_MCP_ARGS`和`YIFAZHILIAN_LEGAL_MCP_TIMEOUT`后，仅法律检索改为只读 stdio MCP；医学仍用本地SQLite。只允许`search_statutes`、`get_article`、`verify_citation`，不发送患者数据，失败返回503而不回退旧资料。当前适配器已用假MCP服务验证协议。

接入北大法宝（2026-10-23 已实测）：法宝的 MCP 是 streamable HTTP + Bearer Token，而本机客户端只支持 stdio，因此用`app/services/pkulaw_bridge.py`做桥接——桥作为子进程被拉起，对外只暴露`search_statutes`/`get_article`，内部转发到法宝网关。配置四行：

```
YIFAZHILIAN_LEGAL_MCP_COMMAND=<backend/.venv/Scripts/python.exe 的绝对路径>
YIFAZHILIAN_LEGAL_MCP_ARGS=-m app.services.pkulaw_bridge
YIFAZHILIAN_LEGAL_MCP_CWD=<backend 目录的绝对路径>
YIFAZHILIAN_LEGAL_MCP_TOKEN=<法宝控制台创建的 Bearer Token>
```

可选`YIFAZHILIAN_LEGAL_MCP_UPSTREAM`覆盖网关地址（默认`https://apim-gateway.pkulaw.com/mcp-law-search-service`）。`search_article`对部分问题只返回**法规条目**（标题、文号、时效、链接）而不含条文正文；桥会保留这类结果，并在正文里写明“未返回条文原文，本条不要引用具体条号”，避免把“检索到了”误判成“没检索到”，也避免模型编造条号。真正的条文原文需要再调`get_law_item_content`（法宝的精准取条服务，需法名+条号）。`.env`里的值不会进入进程环境，因此`TOKEN`/`UPSTREAM`由`MCPSettings.env`显式转发给桥（[config.py](app/config.py)、[knowledge_provider.py](app/services/knowledge_provider.py)）；Token不写日志、不进仓库；每次法律提问按法宝计费口径消耗额度，未配置Token时桥直接报错，后端返回503而不是回退成“没有资料”。

## M05 本地就诊疑问分支

医学聊天在调用模型前先识别就诊疑问：`诊断/误诊/复诊/复查/医嘱/看不懂/检查结果/停药换药/剂量`等。命中后走本地规则，不调用外部 AI，也不读取 M03 照片或 OCR 文本；只把用户当前消息当作“患者转录”，结合公开科普和（若已授权 `vitals`）复诊待办/近期感受生成回答。

医学语料在 `services/medical_knowledge.py`：9 个来源、105 条新增片段，与原有 4 个来源、23 条合计 13 个来源、128 条。覆盖检验进阶、常见症状、常见疾病（含房颤、心衰、胆囊炎、胰腺炎、阑尾炎）、常用药物、检查/围手术期、住院安全、出院随访、特殊人群和预防；检索按同域关键词长度加权并给标题精确命中加分，完整清单见[覆盖地图](../docs/m05-knowledge-map.md)。

回答明确不判断诊断对错、不建议停药换药，误诊/赔偿类问题建议转医生或医务科；有复诊待办时提示复诊，出现胸痛、呼吸困难等危险信号时立即劝导联系现场医护。健康页根据近期感受记录和未完成复诊待办显示主动提示条，点击后带着问题进入同一聊天页。医学聊天还支持本地 `local_record_checklist`：按 `records_read` 授权读取已归档资料类型，回答门诊/住院/复诊还缺哪些资料；缺少文件只表示资料类型不齐，不判断医院诊疗完整性。该分支复用现有 `/conversations/{id}/messages`，没有新页面或新接口。验证见[路线图](../docs/implementation-roadmap.md)和后端测试 `test_medical_agent.py`、`test_record_checklist.py`。

## M06 法律知识智能体

法律域在调用模型前先走 `services/legal_agent.py` 的固定流程：分类为 `crisis / consent / records / privacy / dispute / liability / compensation / overcheck / out_of_scope / general`，并生成主题、追问、材料清单、下一步和问医务科/律师清单。人身安全/暴力威胁先劝离开现场、找保安、拨打110或120；责任认定和赔偿金额明确拒答；知情同意、病历查阅复制封存、隐私撤回、纠纷途径和超范围问题使用本地审校文字并附同域引用；只有一般法律知识才检索后交给 Provider。

知识库增加 `src-law-dispute`《医疗纠纷预防和处理条例》演示摘录，并补充《民法典》第1220—1228条相关片段；法律域独立检索，不混用医学片段。返回字段 `category/topic/topic_key/followups/doctor_questions/materials/next_steps/external_ai` 保存在 `message_metadata`，历史回看可还原。聊天页显示“本次主题”“你还可以问”（追问与问医生建议合并去重）、“可以先准备”和“下一步可以这样做”。

仍是单轮：不做跨轮事实梳理、不读病历正文、不生成正式法律意见、不接真实律师工单。法条为演示摘录，正式使用前必须核对现行有效版本。详见[M06使用与验收](../docs/m06-acceptance.md)。
