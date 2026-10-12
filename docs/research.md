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

## 官方法源

- [民法典](https://gdca.miit.gov.cn/zwgk/zcwj/flfg/art/2020/art_573d6ef5018b46b6a4e1f31ca085a710.html)：1218/1219/1221/1222，责任、告知同意、诊疗义务、法定情形下推定过错。
- [个人信息保护法](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm)：15条撤回；28—30条敏感信息及单独同意/特别告知；21/23条委托和提供；38/39条跨境；55/56条影响评估。
- [数据安全法](https://www.miit.gov.cn/zwgk/zcwj/flfg/art/2022/art_284b390b84484f10b0e43eeafaad0f6d.html)：分类分级和全流程安全。
- [医疗纠纷预防和处理条例](https://www.beijing.gov.cn/zhengce/zhengcefagui/201905/t20190522_61432.html)：15/16条病历保管、查阅复制。
- [电子签名法](https://www.miit.gov.cn/jgsj/zfs/fl/art/2022/art_e3f623f70c23497e88a941170093446a.html)：13/14条可靠签名条件与效力。
- [互联网诊疗监管细则（试行）](https://www.nhc.gov.cn/yzygj/c100068/202203/2072f0e8988249e59d942e1b2a933916.shtml)：适用范围内AI不得冒用/替代医师诊疗，不得自动生成处方。
- [人工智能生成合成内容标识办法](https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm)：上线时核对显式、隐式等标识义务。

## 产品落地顺序

1. P0：修复原型弹窗正文；公共法条、来源引用、授权撤回、紧急事件状态、合成数据答辩。
2. P1：病历本地OCR及人工核对，医护审核知识库和文书草稿，志愿者导诊工单。
3. P2：真实设备、医院系统、正式签署、院内导航定位。AR不是首期依赖。

L1/L2/L3只作为界面预设；医疗健康均须按敏感信息要求设计。家属联系人不等于病历代理人或代签人。手写签名图片与文书哈希不能自动构成可靠电子签名。授权撤回后的停止处理与法定留存要分开执行。免责声明不能代替医疗服务资质和数据处理合法性。
