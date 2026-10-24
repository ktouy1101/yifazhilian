from app.ai.providers.base import KnowledgeChunk


class MockProvider:
    name = "mock"
    external_network = False
    recipient = "local_demo_process"
    policy_version = "demo-1"
    consent_notice = "仅将当前合成问题用于本机检索与模板回复，不向外部模型发送。授权有效期30天，可随时撤回；已保存记录不会自动删除。急症关键词由本地规则提示联系医护。"

    def generate(self, *, domain: str, text: str,
                 context: list[KnowledgeChunk]) -> str:
        if domain == "medical" and any(word in text for word in ["胸痛", "胸闷", "呼吸困难", "喘不过气", "昏迷"]):
            return "【本地模板演示】请立即联系病区医护或使用实体呼叫铃；不要等待 AI 回复。本程序不会派出急救人员。"
        if not context:
            return "【本地模板演示】没有匹配到本领域的已审核资料，无法给出有依据的回答；请向医护或法律专业人员核实。"
        return "【本地模板演示，并非大模型推理】" + context[0].text
