# 医法智联开源调研与法源索引

调研用于架构选型，不代表这些项目满足中国医疗上线要求。本工程未复制这些仓库的代码；引入前须核对具体版本、代码及模型许可证。

|方向|仓库|技术与模式|适配点与边界|
|---|---|---|---|
|医疗AI|[HuatuoGPT](https://github.com/FreedomIntelligence/HuatuoGPT)|Python/PyTorch/Transformers，Apache-2.0代码|医学问答与评测方法；不是原生小程序，权重许可另核验|
|健康管理|[OpenHealth](https://github.com/OpenHealthForAll/open-health)|Next.js/TypeScript/Prisma，Python解析，AGPL-3.0|资料解析、结构化、问答；本地路径可参考，需审计并关闭非必要外传|
|法律AI|[ChatLaw](https://github.com/PKU-YuanGroup/ChatLaw)|InternLM/MoE、Text2Vec、图谱，AGPL-3.0|事实整理与检索引证；不能代替现行法条库|
|法律AI|[LaWGPT](https://github.com/pengxiao-song/LaWGPT)|Python/Transformers/PEFT/Gradio，GPL-3.0|语料及问答评测；首期不建议自训|
|智慧医院|[OpenMRS](https://github.com/openmrs/openmrs-core)|Java/Maven，MPL-2.0附医疗免责声明|患者、就诊、观察记录分离；借鉴数据模型，不整套搬入|
|挂号小程序|[HISReserveWeb](https://github.com/lianghuan-xatu/HISReserveWeb)|原生小程序/ColorUI，Apache-2.0|挂号/查询交互参考；代码以压缩包存放，工程入口不完整，未验证可运行|
|RAG|[Haystack](https://github.com/deepset-ai/haystack)|Python组件Pipeline，Apache-2.0|检索、路由、模型解耦；适合双知识库|
|RAG|[RAGFlow](https://github.com/infiniflow/ragflow)|当前main含Go服务、React/TypeScript，Apache-2.0|文档解析、分块与引用；依赖较重，MVP无需整套部署|

[HospitalRun](https://github.com/HospitalRun/hospitalrun-frontend)可作弱网同步模式补充参考，但仓库已于2023-01-09归档，不建议直接使用旧依赖作为新底座。[Gitee医院小程序候选](https://gitee.com/mmkj/hospital-mini-program/blob/master/README.en.md)本次未完整核实实现和许可，未计入可靠样本。

## 健康智能体与完整健康应用

以下补充基于2026-10-14的一手仓库与源码，属于架构参考，未安装运行，也没有复制源码进本工程。分支内容会变化，实际引入时需锁定提交、依赖及对应许可证。

|项目|核实的实现及可借鉴点|本项目选择与限制|
|---|---|---|
|[Smart Health Assistant](https://github.com/wananing/Smart-Health-Assistant)|MIT；FastAPI、LangGraph、React，按领域路由、专门工具及结构化卡片；[graph.py](https://github.com/wananing/Smart-Health-Assistant/blob/main/backend/agents/graph.py)含路由与专门节点|借鉴状态和工具分工，原生微信界面自行实现；真实模型和语音服务需另外配置，不视为免费医疗知识服务|
|[Health Assistant](https://github.com/health-assistant-io/health-assistant)|Apache-2.0；FastAPI、React、FHIR风格记录、检验指标与关系图谱，依赖PostgreSQL/TimescaleDB、Redis/Celery及可选兼容模型|借鉴“就诊—文档—指标—来源”和人工确认卡片，不整套搬入SQLite工程；Beta，术语和素材另有许可，不因FHIR数据结构就视为已接医院|

Health Assistant README提出AI写入需人工确认，但[examinations.py](https://github.com/health-assistant-io/health-assistant/blob/main/backend/app/ai/tools/examinations.py)仍注册`update_examination_notes`并直接提交数据库。该差异说明需要核查具体工具，而不能照搬“AI绝不写病历”或“跨租户绝不可能”的宣传。本工程明确要求病历变更经过核对和版本流程。

HuatuoGPT、ChatDoctor等研究训练路线不作为学生电脑默认运行前提；权重许可、GPU资源和临床评测是另一层问题。参考模型研究不等于获得可用的患者档案、授权或导诊应用。

## 知识图谱 RAG 与 OCR

[OpenSPG/KAG](https://github.com/OpenSPG/KAG)采用Apache-2.0，提供Schema约束知识构建、知识与文本片段互索引及多跳问答。可借鉴“每条关系绑定原文证据”的方式，不直接引入完整OpenSPG服务栈。首期SQLite节点/边与分域检索便于核查来源；未来是否增加向量检索，以真实评测中未命中和误命中问题决定，不把图谱连线当诊断依据。

[RapidOCR](https://github.com/RapidAI/RapidOCR)是本地OCR候选，官方说明代码采用Apache-2.0，模型来源、转换及许可另见[MODEL_LICENSES.md](https://github.com/RapidAI/RapidOCR/blob/main/MODEL_LICENSES.md)。[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)与RapidOCR先在隔离兼容worker中用合成报告比较：中文、数值/小数点、单位、表格结构、低清与倾斜图片、CPU耗时和失败返回。本工程当前Python 3.14不能作为所有OCR依赖兼容性的承诺；还未安装、下载模型或完成选型。OCR只产生待核对材料，不能自动认证病历或确认患者。

## 医疗与中国法 MCP 工具候选

[MCP官方说明](https://modelcontextprotocol.io/docs/getting-started/intro)定义模型应用连接外部数据与工具的协议；MCP本身不是模型、法条库或可靠性证明。先接受控本地只读工具，不允许任意工具写病历、发通知或发布地图。

|项目|实际来源与运行方式|采用前需要解决|
|---|---|---|
|[FHIR MCP Server](https://github.com/wso2/fhir-mcp-server)|Apache-2.0；Python，连接FHIR资源的读取、搜索和写入工具，可对接本地测试FHIR服务|医疗数据连接候选，不是诊疗模型，也不授予医院数据访问权。仅开放必要只读工具，在服务端限制机构、患者和字段；不能将上游全部CRUD能力直接交给智能体|
|[chinalaw-cli](https://github.com/nh59yytyd5-dev/chinalaw-cli)|Apache-2.0；Python、SQLite、MCP，保留来源、内容摘要、检查时间及效力状态；项目仍处Alpha阶段|作为带版本本地法条检索候选；部分上游资料许可和更新完整性需单独核查，必须以目标法规官方原文及有效时间复核，不能把快照当自动更新的现行法库|
|[legal-database](https://github.com/sublatesublate-design/legal-database)|MIT；Python、SQLite、FastMCP；README以国家法律法规数据库为下载源，下载链依赖浏览器自动化；[mcp_server.py](https://github.com/sublatesublate-design/legal-database/blob/master/mcp_server.py)直接查询本地库|本地检索不需要模型付费Key；初始化、更新和可选向量依赖需验证。目录/发布包的“有效”不能代替逐法源时间核对；导入版本、官方URL和状态应随结果返回|
|[chinese-law-mcp](https://github.com/lttxzmj/chinese-law-mcp)|README声明MIT、语料CC0；Node MCP，[index.js](https://github.com/lttxzmj/chinese-law-mcp/blob/master/index.js)通过CDN读取语料并缓存|属于中国法、不是美国法，但不是完全离线即用；来源网页和非官方整理需与官方原文核对。README声明季度更新不证明每条现行有效；代码与数据都需锁版本，完整许可文件实施前再核查|

这些项目是工具连接候选，不能替代知识运营。法律助手输出应同时标明条文、版本/效力时间和官方原文链接；若只有第三方整理链接，必须明确其来源层级。`legal-database`的检索回退路径还需逐项确认不会绕过效力状态过滤；CDN读取默认分支的工具需先固定数据版本。未确认存在足以免除专业审核的成熟中国医疗法律MCP成品，也未选择外部医疗MCP作为必需依赖。

## AR 导航与无新增标识

目前未核实到同时满足“原生微信、自采、医院无新增标识、完整本地免费链路”的成品。微信AR能力样例与Unity工程属于不同平台；不能把静态箭头、相机叠图或全景浏览当成室内定位。

|项目|核实的流程与适配价值|平台 依赖和许可限制|
|---|---|---|
|[ARIndoorNav](https://github.com/Oscheibe/ARIndoorNav)|利用楼内已有门牌OCR确定房间，手工登记地标坐标和朝向，比例地图与NavMesh规划；契合不新增标识的流程|Unity/ARCore Android，旧版测试环境，Google Cloud Vision外部OCR；未发现项目级LICENSE，仅见导入组件许可证，只研究流程，不直接复制|
|[Wander AR](https://github.com/hitmoose007/wander-AR)|README描述手机采图、点云地图、布置路径节点、视觉定位与导航|Unity C#、Immersal SDK和Firebase，仓库MIT不覆盖第三方服务授权；[Immersal价格与权限](https://immersal.com/pricing)需按地图规模、部署及商用条件核对，不作为默认免费本地方案|
|[BEAM AR Indoor Navigation](https://github.com/sainihaal2347/BEAM-AR-Indoor-Navigation)|ARFoundation、NavMesh与二维码校准思路|README要求在入口/路口等布置二维码，不符合本医院不能新增标识的约束，不选作主路线|

ARIndoorNav的[MarkerDetection.cs](https://github.com/Oscheibe/ARIndoorNav/blob/master/ARIndoorNav%20Project/Assets/Scripts/Model/MarkerDetection.cs)实际用OCR房号命中预登记房间，再使用拍照时手机姿态；不是从门牌图像解算完整六自由度位姿。识别无结果后仍调用后续定位，可能空引用或沿用旧房间。[PoseEstimation.cs](https://github.com/Oscheibe/ARIndoorNav/blob/master/ARIndoorNav%20Project/Assets/Scripts/Model/PoseEstimation.cs)的漂移、楼梯、电梯等重定位分支及重置函数仍有TODO；[Navigation.cs](https://github.com/Oscheibe/ARIndoorNav/blob/master/ARIndoorNav%20Project/Assets/Scripts/Model/Navigation.cs)确有NavMesh目标和路径计算。故可借鉴已有门牌与地图对齐流程，不能宣称获得可靠跨楼层定位。

本工程选定的方向是单院短路线、现有自然地标、人工校准、版本地图与失跟恢复。志愿者提交是采集证据，需独立审核和实走；上传不等于自动建图，资料发布先保持`ar_ready=false`。VPS仅为后续可行性候选；手机跟踪/渲染与电脑地图管理分别验收。

### 原生微信与本地视觉定位候选

|项目|负责什么|本项目如何评估|
|---|---|---|
|[微信官方小程序示例](https://github.com/wechat-miniprogram/miniprogram-demo)|MIT；原生VisionKit与XR-frame能力示例|作为手机相机、跟踪与AR显示的首要能力验证入口；示例不包含完整医院地图、审核或路线服务|
|[COLMAP](https://github.com/colmap/colmap)|BSD-3-Clause；从重叠多视角图像重建相机位姿与场景结构|作为电脑端离线建图候选，先测短路段数据质量；还需测量尺度并对齐医院地图坐标，不直接把点云当可走路线|
|[Hierarchical Localization](https://github.com/cvg/Hierarchical-Localization)|Apache-2.0；图像检索、局部匹配和几何视觉定位|作为自建视觉定位候选，需已有地图和未参与建图的测试画面；不是微信SDK，模型、权重与子依赖许可单独检查，部分SuperGlue相关许可限制商业使用|

微信实现以官方[AR跟踪器说明](https://developers.weixin.qq.com/miniprogram/dev/component/xr-frame/ar/tracker.html)及[VisionKit会话接口](https://developers.weixin.qq.com/miniprogram/dev/api/ai/visionkit/wx.createVKSession.html)为能力边界。现有自然参照物必须稳定、可区分并能登记尺寸、坐标和朝向；纯文字门牌OCR只能辅助识别地点。六自由度跟踪、尺度、设备支持和跨楼层恢复必须分别验证，屏幕叠加箭头不算完成定位。

采集规范参考[COLMAP重建说明](https://colmap.github.io/tutorial.html#structure-from-motion)：需要相邻视角足够重叠并实际移动相机，白墙、重复走廊、玻璃反光和动态人群可能使重建或定位失败。先做小样本实测，再确定志愿者任务的角度、间距与补拍规则；不能先大规模上传再假定素材一定可用。

## 官方法源

- [民法典](https://gdca.miit.gov.cn/zwgk/zcwj/flfg/art/2020/art_573d6ef5018b46b6a4e1f31ca085a710.html)：1218/1219/1221/1222，责任、告知同意、诊疗义务、法定情形下推定过错。
- [个人信息保护法](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm)：15条撤回；28—30条敏感信息及单独同意/特别告知；21/23条委托和提供；38/39条跨境；55/56条影响评估。
- [数据安全法](https://www.miit.gov.cn/zwgk/zcwj/flfg/art/2022/art_284b390b84484f10b0e43eeafaad0f6d.html)：分类分级和全流程安全。
- [医疗纠纷预防和处理条例](https://www.beijing.gov.cn/zhengce/zhengcefagui/201905/t20190522_61432.html)：15/16条病历保管、查阅复制。
- [电子签名法](https://www.miit.gov.cn/jgsj/zfs/fl/art/2022/art_e3f623f70c23497e88a941170093446a.html)：13/14条可靠签名条件与效力。
- [互联网诊疗监管细则（试行）](https://www.nhc.gov.cn/yzygj/c100068/202203/2072f0e8988249e59d942e1b2a933916.shtml)：适用范围内AI不得冒用/替代医师诊疗，不得自动生成处方。
- [人工智能生成合成内容标识办法](https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm)：上线时核对显式、隐式等标识义务。

## 产品落地顺序

当前实施顺序统一以[实施路线图](implementation-roadmap.md)的步骤1—7为准：身份数据基础→导航采集审核并行AR技术验证→医院地图与真实AR→病历OCR→双知识库和双智能体→健康与SOS→整体联调。AR为必做项，单院试点不能新增标识。真实医院、设备、通知和正式签署另满足各自接入条件。

L1/L2/L3只作为界面预设；医疗健康均须按敏感信息要求设计。家属联系人不等于病历代理人或代签人。手写签名图片与文书哈希不能自动构成可靠电子签名。授权撤回后的停止处理与法定留存要分开执行。免责声明不能代替医疗服务资质和数据处理合法性。
