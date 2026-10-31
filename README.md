# 医法智联

面向患者、志愿者与审核员三类角色的微信小程序演示工程：**导诊路线采集与审核**、**健康与病历记录**、**法律知识问答**、**真人法律志愿者帮扶**。

原生小程序（WXML/WXSS）+ Python FastAPI + 本地 SQLite，无前端 npm 依赖。所有内容为合成演示数据，**不构成诊疗意见或法律意见**。

界面截图见 [`ui-screenshots/`](ui-screenshots/README.md)（36 张，按角色分组）。

## 三类角色

| 角色 | 能做什么 | 进入方式 |
|---|---|---|
| **患者** | 健康记录与用药、检验单拍照 OCR 与核对、健康/法律智能问答、已发布路线导览与反馈、向法律志愿者提问 | 登录后进患者端（首页 / 导诊 / 法知 / 我的） |
| **志愿者** | 导诊采集（领任务、拍照、提交、按退回意见补拍）、法律接单与回复、上传执业证 | 登录后进「志愿者工作台」，tab 按能力生成 |
| **审核员** | 审核志愿者申请、核验律师凭证、审核并发布路线、查看反馈与工单（只读）、管理用户与审计 | 登录后进「审核工作台」 |

角色由**服务端能力**决定，登录页不再选身份：审核员 → 审核工作台，志愿者 → 志愿者工作台，其余 → 患者端。

## 主要功能

- **导诊路线**：领取任务 → 逐节点拍照上传 → 提交 → 他人审核/退回 → 发布 → 停用；含版本快照、反馈与禁止自审。
- **健康与病历**：用药计划、健康记录、就诊摘要、检验单/病历拍照 → 本地 OCR（可选）→ 原图核对 → 纠错归档 → 历史回查。
- **智能问答**：医学与法律分域；急症/诊断/赔偿等边界问题明确拒答或引导线下；法条优先本地库，可选接北大法宝 MCP。
- **法律帮扶**：律师执业证上传（私有存储）→ 审核员看图核验 → 通过后可接单；患者提问进队列，志愿者接单后在对话里回复。
- **权限与审计**：`user_roles` + `volunteer_profiles` + `navigation_memberships` 计算能力位；审核、授权、停用等动作写 `audit_events`。

## 技术栈

```
miniprogram/   原生小程序（自定义 tabBar / 组件 / 页面）
backend/       FastAPI + SQLite(WAL)，schema 版本化迁移（当前 v12）
deploy/        Dockerfile + Caddy 自动 HTTPS + 备份脚本
ui-screenshots/ 全页面截图（供 UI 参考）
docs/          方案、验收、部署文档
```

## 本地运行

环境：Python 3.11+，微信开发者工具。

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
.\backend\.venv\Scripts\python.exe -m pytest -q          # 后端测试
.\start-backend.ps1                                      # 启动后端（按小程序 baseURL 监听）
```

小程序：用开发者工具导入**仓库根目录**（`project.config.json` 已指向 `miniprogram/`）。本地联调需在「详情 → 本地设置」勾选「不校验合法域名」。

- 后端默认 `http://192.168.199.126:8000`，接口文档 `/docs`
- 数据库默认 `backend/data/yifazhilian.db`（被 Git 忽略），可用 `YIFAZHILIAN_DB_PATH` 覆盖
- 本地 OCR 可选：运行 `./setup-ocr.ps1` 安装独立环境；不装时拍照后会提示手填

## 演示账号

验证码登录（演示模式验证码自动回填）或密码登录（密码 = 手机号后 6 位）：

| 手机号 | 密码 | 角色 |
|---|---|---|
| `19077411124` | `411124` | 审核员 |
| `13900000088` | `000088` | 采集 + 法律志愿者 |
| `13900000021` | `000021` | 采集志愿者 |
| `13800138000` | `138000` | 普通患者 |

管理员号码由 `YIFAZHILIAN_ADMIN_PHONE` 环境变量或 `backend/admins.txt` 指定，两者取并集。

## 测试

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -q      # 后端 234 passed
node --test tests/*.test.cjs                          # 前端 83/85（2 项依赖本地临时目录，见 docs/ci-status.md）
```

数字只对当次运行有效，提交前请重跑。测试使用临时数据库与合成图片，不调用真实模型。

## 部署

完整步骤见 [部署手册](docs/deploy.md)：买服务器 → 域名备案 → `docker compose up` → 微信后台配置合法域名 → 发体验版。

关键约束：小程序体验版/正式版要求 **HTTPS + 已备案域名**；跨域调试只能在开发者工具关闭域名校验。

## 文档

| 文档 | 内容 |
|---|---|
| [部署手册](docs/deploy.md) | 服务器、域名、HTTPS、微信后台、备份与排错 |
| [角色路线图](docs/roles-roadmap.md) | 志愿者/审核员的 P1–P4 实施记录 |
| [产品方案](docs/product-plan.md) · [架构](docs/architecture.md) | 模块边界与接口 |
| [验收记录](docs/m11-acceptance.md) 等 | M03/M04/M05/M06/M07/M11 |
| [CI 状态](docs/ci-status.md) | 本地与 CI 的真实测试结果 |

## 边界与未实现

- 全部内容为合成演示数据；不接入医院系统、真实短信、律师或签名服务。
- 演示登录（`YIFAZHILIAN_DEMO_AUTH=1`）会回显验证码，**任何公开环境必须关闭并接入短信**。
- 密码登录没有失败次数限制，密码为手机号后六位，仅适合内部演示。
- 未实现：真实 AR 定位、向量检索、举报处理流程、工单超时提醒、多实例部署。
- 数据未加密、无生产级备份验证；上线前需完成身份核验、加密、授权与合规评估。

## 仓库

<https://github.com/ktouy1101/penguin>（公开）

数据库、`.env`、虚拟环境与外部附件均不入库。提交前请确认 diff 中没有密钥、真实手机号或个人资料。
