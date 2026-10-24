# M07 知识库与引用（第一版）使用与验收

更新：2026-10-21。当前交付是可核查的 SQLite 演示知识库，检索结果只在服务端为生成提供参考，不再作为引用卡片返回聊天页。医学/法律内容仍为演示摘录，不能替代专业核实。

## 已实现

- Schema 8 新增 `knowledge_sources`、`knowledge_chunks`；来源保存标题、发布方、URL、文档版本、生效/失效日期、审核人和状态。
- 启动时幂等写入 3 个演示来源、10 个片段；状态为 `published`，只允许在生效区间内参与检索。
- 医学、法律按域隔离；检索使用 SQLite 关键词匹配，取最多 2 条，不调用向量库或外部检索服务。
- 聊天回复不再返回 `sources`，也不再写 `message_sources`；旧表在启动迁移时删除，检索来源只在服务端生成时使用。
- 新增 `GET /api/v1/knowledge/search?domain=medical|legal&q=...`，需要登录，返回引用条目；不要求患者健康记录授权。
- 前端聊天不再展示引用卡片；来源标题、版本、发布状态等只在知识库/后台接口中查看。

## 检索规则

1. 查询必须指定 `domain`，服务端不会根据提问内容切换领域。
2. 只选择来源 `status='published'` 且当天处于 `effective_from`—`effective_until` 之间的片段。
3. 对片段关键词做本地命中计数，按命中数、片段顺序排序，最多返回 2 条。
4. 没有命中时不调用模型，返回本地“没有匹配依据”提示；急症关键词仍在检索前由本地规则拦截。
5. 知识片段和来源都是待处理数据，不能改变授权、系统提示或工具权限。

## 可选法律 MCP（默认关闭）

本地 SQLite 是默认知识源。配置以下环境变量后，**仅法律领域**改用只读 MCP，医学仍走本地 SQLite：

```text
YIFAZHILIAN_LEGAL_MCP_COMMAND=uvx
YIFAZHILIAN_LEGAL_MCP_ARGS=china-law-mcp
YIFAZHILIAN_LEGAL_MCP_TIMEOUT=30
```

- 适配器为 `StdioMCPClient` + `MCPLegalKnowledgeProvider`，只允许 `search_statutes`、`get_article`、`verify_citation` 三个工具；其他工具在客户端直接拒绝。
- MCP 调用不在 SQLite 事务内；只发送当前法律问题和数量，不发送病历、体征、用户标识、聊天历史或令牌。
- MCP 失败返回 503，**不静默回退本地旧资料**；回答不会保存。
- 外部 MCP 结果标记 `status=external`，只在服务端参与生成；不返回聊天页，也不会伪装成本库已审核来源。
- 已用假 stdio MCP 服务器验证 initialize、tools/list、tools/call 和白名单；本机 `uvx` 缓存目录受当前环境权限限制，尚未完成真实 `china-law-mcp` 进程联调。安装并在普通终端运行后再做一次真实联调。

## 当前限制

- 种子语料只有 3 个来源、10 个片段，未做医学/法律专业审核，也没有逐条引用核验；法律条文仅为简要释义，必须回到官方原文核对。
- 没有知识录入、审核、发布、停用和版本回滚的后台；`draft/reviewed/published/retired` 状态目前只由种子和数据库维护。
- 没有向量检索、知识图谱、知识审核后台或多轮上下文；MCP 只有可选的法律只读适配器，不是完整工具编排；这些是 M07/M05/M06 的后续工作。
- 检索命中只证明“生成时参考了这条已发布片段”，不证明模型逐字遵守了它，也不证明内容适用于具体个案。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/knowledge/search` | `domain`、`q`、可选 `limit`；返回片段与来源元数据 |
| POST | `/api/v1/conversations/{id}/messages` | 在授权内检索并生成回复；不返回来源，也不再返回 `suggestions`（2026-10-24 删除） |

## 验证

- 后端全量：**166 passed**，其中 M07 相关 12 项：种子已发布/分域、停用与失效过滤、消息不再返回来源、旧元数据不回流已删字段、未知问题拒答、搜索需要登录、MCP 域隔离/结构化结果/失败不回退/路由 503、stdio 协议与工具白名单。
- 前端全量：**83 项，受限沙箱 82 passed / 1 skipped**；M11 全链路在当前沙箱启动子进程被 `EPERM`，完整权限下 83 passed；健康页本地 HTTP 用例在受限沙箱也可能因临时库权限失败。
- 微信开发者工具预览编译通过。
- 真实 HTTP 冒烟覆盖登录、授权、知识搜索、聊天引用和历史回看（7 项通过）；撤回阻断由 M04 冒烟覆盖。未调用外部 AI。

复核：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_knowledge.py -q
node --test tests/miniprogram-provider.test.cjs
```
