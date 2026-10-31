# 身份与后台路线图（志愿者 / 法律志愿者 / 审核员）

更新：2026-10-23。本文是"三种身份 + 一套后台"的落地计划，配套[产品方案](product-plan.md)、[实施路线图](implementation-roadmap.md)与[架构说明](architecture.md)阅读。患者端本期不变，相关页面与接口以现状为准。

## 1. 目标与边界

**目标**：在小程序内支持三条真实可用的身份路径，并让审核员真正能做后台工作。

- 志愿者：登录后申请，通过后可以**采集/提交路线**（复用现有 M11 流程）。
- 法律志愿者：另有**律师凭证核验**，通过后可以接患者的法律帮扶请求。
- 审核员（管理员）：审核路线、审核志愿者与凭证、管理用户、查看审计——即后台工作入口。

**边界（本期不做）**：不改患者端页面与交互；不做独立家属端（沿用[产品方案](product-plan.md)的"同设备协助"）；不做实时聊天；不做独立 Web 管理端；不承诺凭证"官方核验"，只做人工看图与留痕。

## 2. 已定决策（2026-10-23）

| # | 决策 | 理由 |
|---|---|---|
| 1 | 审核员不能自助注册，由环境变量 `YIFAZHILIAN_ADMIN_PHONE` 指定手机号，该号码登录即为管理员 | 避免"申请即可成为管理员"；也避免邀请码分发 |
| 2 | 法律帮扶先做**异步工单**，不做实时聊天 | 实时聊天需要在线状态、消息推送、值守排班，成本翻倍 |
| 3 | 律师凭证**人工核验**（看图 + 留痕），不对接律协/司法部 | 官方核验接口不可得；界面上也不得暗示已获机构背书 |
| 4 | 后台先做在**小程序内**，页面复用现有组件 | 免额外部署；管理量变大再拆 Web 端 |

## 3. 身份与权限

身份用"能力位"表达，不用单一角色字段：一个人可以同时是志愿者和法律志愿者。

| 能力 | 患者 | 志愿者（导诊） | 法律志愿者 | 审核员 |
|---|---|---|---|---|
| AI 问答 / 健康记录 / 求助 | 现状不变 | — | — | — |
| 采集、提交路线 | — | 申请通过后 | — | ✅ |
| 审核、发布、停用路线 | — | — | — | ✅（不得审本人提交） |
| 接法律帮扶工单 | — | — | 凭证通过后 | — |
| 审核志愿者申请与凭证 | — | — | — | ✅ |
| 用户管理、审计查看 | — | — | — | ✅ |

判权一律在服务端完成，客户端隐藏按钮不算鉴权。

## 4. 数据模型

`users.role` 是 SQLite `CHECK` 约束，新增取值要重建整张表，风险高于收益。因此**不动 `users`**，另开表：

```sql
-- schema v9
CREATE TABLE user_roles (
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK(role IN ('patient','volunteer','reviewer')),
  granted_by TEXT REFERENCES users(id),
  granted_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role)
);

CREATE TABLE volunteer_profiles (
  user_id     TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  hospital_id TEXT NOT NULL DEFAULT 'demo-hospital',
  kinds       TEXT NOT NULL DEFAULT '',   -- guide / guide,legal
  real_name   TEXT,
  status      TEXT NOT NULL CHECK(status IN ('none','pending','approved','rejected','suspended')),
  note        TEXT,
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  updated_at  TEXT NOT NULL
);

CREATE TABLE volunteer_credentials (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK(kind IN ('lawyer_license','legal_aid')),
  media_id    TEXT NOT NULL,              -- 私有存储，仅审核员可读
  status      TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  note        TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE legal_help_requests (
  id           TEXT PRIMARY KEY,
  patient_id   TEXT NOT NULL REFERENCES users(id),
  text         TEXT NOT NULL,
  status       TEXT NOT NULL CHECK(status IN ('open','claimed','answered','closed')),
  volunteer_id TEXT REFERENCES users(id),
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE legal_help_messages (
  id         TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES legal_help_requests(id) ON DELETE CASCADE,
  sender_id  TEXT NOT NULL REFERENCES users(id),
  text       TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

规则：

- 工单只传**问题文本**，不传病历、不传身份标识；志愿者看到的是编号或"已核验法律志愿者"，患者看不到志愿者的手机号。
- 凭证图片走私有读取接口，仅本人与审核员可读，禁止出现在公开路由。
- 所有审核动作写 `audit_events`（谁、何时、对哪条、结果）。

## 5. 分阶段计划

### P1 身份基座（已完成 2026-10-23，约 1 天）

- 新增 schema v9 与迁移；`capabilities(user)` 统一判权（角色 + 志愿者状态 + 导航能力位）。
- 登录页增加两个入口：**志愿者登录**、**工作人员登录**；患者入口保持现状。
- `YIFAZHILIAN_ADMIN_PHONE` 指定的号码登录后获得 reviewer 能力。
- 收紧 `demo-login`：演示账号不再能登录成志愿者/审核员（或仅在回环地址可用）。

**验收**：三种入口都能登录；非审核员访问管理接口返回 403；demo 账号拿不到管理能力；现有 199 项测试不回退。

**实际交付（2026-10-23）**：

- schema v9：`user_roles`、`volunteer_profiles`（本次只建这两张，凭证与工单表留到 P4）。
- `app/services/roles.py`：`capabilities()`、`grant_admin()`、`is_loopback()`；`users.role` 未改动。
- `GET /users/me` 增加 `capabilities` 字段；新增 `GET /admin/ping` 作为鉴权探针。
- 登录页三个入口（患者 / 志愿者 / 工作人员），登录后按 **服务端能力** 分流：审核员进管理台、有采集权限的志愿者进工作台、其他回首页。
- `pages/admin/index` 管理台骨架（待办占位，P3 接入真实审核）。
- 演示审核员账号改为**仅限本机登录**：局域网客户端调用 `demo-login` 登录该账号返回 403。
- `YIFAZHILIAN_ADMIN_PHONE` 中的号码登录时自动获得 reviewer 角色与导航审核位。
- 测试：`backend/tests/test_roles.py` 7 项；全量 206 项通过。迁移断言同步到 v9。

### P2 志愿者采集路线（已完成 2026-10-24，约 0.5 天）

- 志愿者登录 → 提交申请（医院、实名、培训确认）→ 审核员通过 → 自动写入 `navigation_memberships.can_collect=1`。
- 首页/我的出现「采集路线」入口，复用 `route-capture` 与现有提交/版本接口。
- 采集提交后仍需独立审核，采集者不能审自己的（沿用现有 `_access` 规则）。

**验收**：新志愿者从登录到提交一条草稿 ≤ 3 步；未通过申请的人看不到采集入口且接口 403；提交后进入审核队列。

**实际交付（2026-10-24）**：

- 新增 `app/api/volunteer.py`：`GET /volunteer/me`、`POST /volunteer/apply`（培训未确认 422、重复申请 409、被拒后可重提）、`GET /admin/volunteers?status=`、`POST /admin/volunteers/{user_id}/review`（通过则授予 volunteer 角色并把 `can_collect` 置 1，拒绝则清零）。
- 申请与审核都写 `audit_events`；审核员不能审自己的申请。
- 新增 `pages/volunteer/index`（申请表单 / 等待审核 / 已通过 → 采集工作台）；「我的」按能力在「志愿者中心」与「导航采集与路线管理」之间切换。
- 管理台新增「志愿者申请 · 待审核」列表，可直接通过/拒绝。
- 测试：`backend/tests/test_volunteer.py` 5 项；全量 214 项通过。

### P3 审核台（已完成 2026-10-24，约 1.5 天）

- 新增 `pages/admin/index` 待办中心：路线待审、志愿者申请、法律凭证、导航反馈、举报。
- 路线审核复用现有 review 接口与 `route-review` 页。
- 用户管理：改能力、停用账号、查看 `audit_events`。
- 审核员工作台入口从"我的"页进入，非审核员不显示且接口 403。

**验收**：审核员能在待办中心完成"审路线→发布""审志愿者→放行""看审计"三条闭环；任何一个动作都能在同一页面看到结果。

**实际交付（2026-10-24）**：

- 新增 `app/api/admin.py`：`GET /admin/overview`（路线待审/已发布/志愿者待审/反馈/用户）、`GET /admin/feedback`、`GET /admin/audit`、`POST /admin/users/{id}/roles`（授予/撤销 volunteer、reviewer）。
- 撤销审核员会同时清 `navigation_memberships.can_review`；不能撤销自己的审核员权限（400）。
- `GET /admin/users` 增加 `roles` 字段，供管理台显示与切换。
- 管理台页面重做：概览数字、路线待审入口（跳采集工作台）、志愿者审核、反馈列表、用户管理（授予/撤销角色、停用）、审计列表。
- 测试：`backend/tests/test_admin_console.py` 8 项；全量 228 项通过。
- 法律凭证审核随 P4 一起做，管理台已预留位置。

### P4 法律帮扶（已完成 2026-10-24）

- 法律志愿者上传执业证 → 审核员看图核验 → approved。
- 患者端在法知模块内新增「真人法律志愿者」入口：提交问题后进入队列，由已核验志愿者接单；没有在线志愿者时问题也会保留。
- 志愿者接单 → 异步回复 → 患者收到；审核员可查全部工单与超时未接单。

**实际交付（2026-10-24）**：

- schema v11：`volunteer_credentials`（私有 BLOB 凭证）、`legal_help_requests`、`legal_help_messages`。
- 凭证：`POST /volunteer/credentials`（限 4MB，PIL 统一转 JPEG 去元数据）、`GET /volunteer/credentials`、`GET /admin/credentials?status=`、`GET /admin/credentials/{id}/image`（仅审核员）、`POST /admin/credentials/{id}/review`。
- 工单：`POST /legal-help/requests`（无已核验志愿者时 409）、`GET /legal-help/requests`、`GET /legal-help/queue`（仅 `can_help_legal`）、`POST /legal-help/requests/{id}/claim`（不能接自己的）、`POST /legal-help/requests/{id}/messages`、`GET /legal-help/requests/{id}`（本人/接单志愿者/审核员可看）、`GET /admin/legal-help`。
- 能力位：`can_help_legal` = 志愿者档案 approved + kinds 含 legal + 至少一张凭证 approved。
- 页面：`pages/legal-help/index`（按角色显示提问或队列）、`pages/legal-help/detail`（往来与回复）、`pages/admin/credentials`（看图/通过/拒绝）、`pages/admin/legal-help`（全部工单）、志愿者中心增加凭证上传、我的页增加「法律帮扶」入口、管理台增加两个入口。
- 测试：`backend/tests/test_legal_help.py` 4 项（凭证门禁、工单闭环、越权拒绝、非法图片与重复审核）；全量 228 项通过。

**验收**：无凭证账号无法接单；核验通过后可接单回复；工单里不出现病历与手机号；审核员能看到完整往来与状态。

## 6. 与现有代码的衔接

| 复用 | 位置 | 说明 |
|---|---|---|
| 路线采集与审核 | [navigation.py](../backend/app/api/navigation.py) 20+ 接口、`route-capture`、`navigation-workbench`、`route-review` | 流程已完整，P2/P3 只加身份与入口 |
| 判权与鉴权 | [dependencies.py](../backend/app/api/dependencies.py) | 新增 `require_reviewer`、`require_volunteer` 依赖 |
| 审计 | `audit_events` 表与 `audit()` | 每个审核动作写一条 |
| 私有图片 | 现有 `navigation_media` 读取方式 | 凭证图沿用同一套私有读取 |
| 运行开关 | `app/config.py` | 新增 `YIFAZHILIAN_ADMIN_PHONE`；与既有 `RUNTIME_MODE`、`DEMO_AUTH` 一致读 `.env` |

## 7. 风险与待定

| 风险 | 处理 |
|---|---|
| 演示登录仍开（未接短信通道） | 本期至少把 demo 账号与"志愿者/审核员"能力解耦；真正关闭仍需短信通道 |
| 凭证只做人工核验 | 界面明确"人工核验，不代表机构背书"；不写"认证律师"字样 |
| 小程序内审图体验有限 | 第一期接受；管理量上来再迁 Web |
| 审核员单点 | 至少保留两名管理员，且禁止自审自批 |
| 法律帮扶可能涉及真实纠纷 | 工单只提供信息与材料清单，不给个案法律意见；沿用现有免责声明 |

## 8. 总体验收（端到端）

1. 患者 → 提问、看路线、找法律志愿者（入口按可用性显示）。
2. 志愿者 → 登录、申请、通过、采集并提交一条路线。
3. 审核员 → 审路线发布、审志愿者放行、审法律凭证、停用一个账号。
4. 法律志愿者 → 凭证通过、接单、回复。
5. 越权检查：非审核员调管理接口 403；采集者审自己的路线 403；无凭证接单 403。
6. 审计可回溯：上述每个动作都能在 `audit_events` 里查到操作人与时间。
