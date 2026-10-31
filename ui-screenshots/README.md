# UI 截图索引

设备：微信开发者工具模拟器 iPhone（332×718 输出），未做任何美化，原始界面。

按角色分组，编号即截图顺序。

## 未登录 / 患者端

| 文件 | 页面 | 说明 |
|---|---|---|
| 01-home-guest.png | pages/home/index | 未登录首页，顶部有「登录」入口 |
| 02-navigation-guest.png | pages/navigation/index | 导诊列表，未登录态 |
| 03-legal-chat-guest.png | pages/chat/index?domain=legal | 法知对话页（含真人志愿者入口） |
| 04-profile-guest.png | pages/profile/index | 我的，未登录 |
| 05-login-normal.png | pages/login/index | 登录页，普通模式 |
| 06-login-volunteer-mode.png | pages/login/index | 登录页，志愿者注册模式 |
| 07-home-patient.png | pages/home/index | 患者首页 · 用药计划 |
| 08-home-status.png | pages/home/index | 患者首页 · 健康状况 |
| 09-navigation-patient.png | pages/navigation/index | 导诊列表，已登录 |
| 10-profile-patient.png | pages/profile/index | 我的，已登录 |
| 11-records.png | pages/records/index | 病历/资料列表 |
| 12-chat-medical.png | pages/chat/index?domain=medical | 医疗对话页 |
| 13-photo-walkthrough.png | pages/photo-walkthrough/index | 图文导览（逐步照片） |

## 志愿者端

| 文件 | 页面 | 说明 |
|---|---|---|
| 14-volunteer-workbench.png | pages/volunteer/workbench/index | 工作台首页（待办数字） |
| 15-volunteer-collect.png | 同上 · 采集 tab | 待领取任务 / 我的采集 |
| 16-volunteer-legal.png | 同上 · 法律 tab | 待接工单 / 我的工单 |
| 17-volunteer-mine.png | 同上 · 我的 tab | 账号与能力 |
| 18-volunteer-application.png | pages/volunteer/application/index | 志愿者申请与状态 |
| 19-volunteer-credentials.png | pages/volunteer/legal/index | 律师执业证上传与核验 |
| 20-legal-help-list.png | pages/legal-help/index | 真人法律志愿者窗口 |
| 21-legal-help-detail.png | pages/legal-help/detail/index | 工单对话详情 |
| 22-navigation-workbench.png | pages/navigation-workbench/index | 导航采集与审核工作台 |
| 23-route-capture.png | pages/route-capture/index | 路线采集（拍照、填节点） |

## 审核端

| 文件 | 页面 | 说明 |
|---|---|---|
| 24-admin-todo.png | pages/admin/workbench/index | 待办：志愿者申请 / 凭证 / 路线 |
| 25-admin-supervise.png | 同上 · 监督 tab | 工单只读、反馈、审计入口 |
| 26-admin-users.png | 同上 · 用户 tab | 按类型分组管理账号 |
| 27-admin-mine.png | 同上 · 我的 tab | 审计与退出 |
| 28-admin-hub.png | pages/admin/index | 管理台旧入口页 |
| 29-admin-routes.png | pages/admin/routes/index | 路线待审列表 |
| 30-admin-volunteers.png | pages/admin/volunteers/index | 志愿者申请审核 |
| 31-admin-feedback.png | pages/admin/feedback/index | 导航反馈 |
| 32-admin-users-page.png | pages/admin/users/index | 用户管理（表格版） |
| 33-admin-credentials.png | pages/admin/credentials/index | 法律凭证核验 |
| 34-admin-legal-help.png | pages/admin/legal-help/index | 全部工单 |
| 35-admin-audit.png | pages/admin/audit/index | 审计记录 |
| 36-route-review.png | pages/route-review/index | 路线审核（看照片、通过发布） |

## 给设计时的备注

- 患者端：浅青底 `#F3F8F9`、白色圆角卡片、主色 `#0E7C86`，底部 4 个原生 tab。
- 志愿者/审核端：自定义底栏（白底、选中青色），3–4 个 tab，按能力显示。
- 两套壳已统一配色与卡片样式；`14`–`17`、`24`–`27` 是同一页面的不同 tab，可直接对照。
- 未覆盖：紧急呼叫的弹窗、各页的弹窗/对话框状态、真机状态栏差异。
