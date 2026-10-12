"""Two isolated local corpora; deterministic keyword retrieval, not vector RAG."""
from app.ai.providers.base import AIProvider, KnowledgeChunk
from app.ai.providers.mock import MockProvider

CORPORA = {
    "medical": [
        KnowledgeChunk("med-001", "medical", "医法智联演示健康提示（非临床指南）",
                       "关于住院用药、过敏和监测，请向主管医护核对。不要根据本演示自行调整用药。",
                       None, ("用药", "药", "过敏", "监测", "血压", "心率", "血氧")),
    ],
    "legal": [
        KnowledgeChunk("law-1219", "legal", "《民法典》第1219条（简要释义）",
                       "医务人员应说明病情和医疗措施；手术、特殊检查、特殊治疗通常需要说明风险、替代方案并取得明确同意。紧急情形另有规则，具体情况请核实。",
                       "https://gdca.miit.gov.cn/zwgk/zcwj/flfg/art/2020/art_573d6ef5018b46b6a4e1f31ca085a710.html",
                       ("知情", "同意", "手术", "风险", "治疗", "法条")),
        KnowledgeChunk("law-1222", "legal", "《民法典》第1222条（简要释义）",
                       "在法律规定的情形下，如隐匿、拒绝提供与纠纷有关的病历，或者遗失、伪造、篡改、违法销毁病历，可能推定医疗机构有过错；不等同于自动认定全部赔偿责任。",
                       "https://gdca.miit.gov.cn/zwgk/zcwj/flfg/art/2020/art_573d6ef5018b46b6a4e1f31ca085a710.html",
                       ("病历", "篡改", "纠纷", "过错", "赔偿")),
    ],
}

provider: AIProvider = MockProvider()


def retrieve(domain: str, text: str) -> list[KnowledgeChunk]:
    # Domain is selected on conversation creation and never taken from prompts.
    ranked = [(sum(word in text for word in doc.keywords), doc)
              for doc in CORPORA[domain]]
    return [doc for score, doc in sorted(ranked, key=lambda pair: pair[0], reverse=True)
            if score > 0][:2]


def respond(domain: str, text: str) -> dict:
    context = retrieve(domain, text)
    return {
        "answer": provider.generate(domain=domain, text=text, context=context),
        "sources": [
            {"id": d.id, "domain": d.domain, "title": d.title, "text": d.text, "url": d.url}
            for d in context
        ],
        "provider": provider.name,
        "retrieval": "local_keyword_demo",
    }
