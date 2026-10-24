const CONSENT_TEMPLATES = [
  { title: '冠脉造影 / 支架手术', diagnosis: '冠心病 · 不稳定心绞痛', measure: '经皮冠状动脉造影，必要时植入支架', risk: '造影剂过敏、穿刺部位出血、血管损伤等。具体风险及替代方案待医护人员结合实际病情补充。' },
  { title: '全身麻醉手术', diagnosis: '拟行外科手术治疗', measure: '气管插管全身麻醉', risk: '麻醉药物过敏、呼吸循环抑制、误吸等。具体风险及替代方案待医护人员结合实际病情补充。' },
  { title: '特殊检查（增强 CT）', diagnosis: '需进一步明确病灶', measure: '静脉注射造影剂增强 CT', risk: '造影剂过敏、造影剂相关肾损伤、辐射暴露等。具体风险及替代方案待医护人员结合实际病情补充。' }
]
const KNOWLEDGE = [
  { key: 'consent', label: '知情同意权', left: 18.24, top: 20, citation: '《民法典》第 1219 条', summary: '就手术、特殊检查、特殊治疗等，关注病情、医疗措施、医疗风险与替代方案的说明，以及明确同意。仅展示原型中的法条概述，具体适用需结合事实。' },
  { key: 'privacy', label: '隐私与数据', left: 81.76, top: 20, citation: '《个人信息保护法》第 28 条', summary: '医疗健康等属于敏感个人信息，处理应具有特定目的与充分必要性，并采取严格保护措施。本项目以最小必要、分项授权及可撤回作为设计原则。' },
  { key: 'algorithm', label: '算法归责', left: 88.24, top: 56.19, citation: '研究议题 · 不是现行法律条款', summary: '原型将 AI 误诊责任列为立法研究议题，不能据此认定自动成立连带责任。讨论医疗损害时，应结合《民法典》第 1218、1221 条所涉及的过错、诊疗义务与损害事实。' },
  { key: 'evidence', label: '电子证据', left: 72.35, top: 84.76, citation: '《电子签名法》· 原型关联主题', summary: '保留资料来源、时间及原始记录，关注电子签名和数据的可靠性。截图、监测记录或本示例的阅读确认，不能自动等同于可靠电子签名或有效证据结论。' },
  { key: 'dispute', label: '医疗纠纷', left: 27.65, top: 84.76, citation: '《医疗纠纷预防和处理条例》；《民法典》第 1222 条', summary: '可了解协商、人民调解、诉讼等处理途径，并妥善保存病历资料。第 1222 条涉及隐匿、篡改、违法销毁病历等法定情形下的过错推定；个案需核实事实。' },
  { key: 'levels', label: '数据分级', left: 11.76, top: 56.19, citation: '分类分级保护模型 · 原型设计主题', summary: '按数据敏感程度确定访问、脱敏及保存规则。L1 / L2 / L3 是本项目的产品分级，不是法定分类，也不能代替针对具体处理目的的授权。' }
]
const PROCESS_STEPS = [
  { number: 1, title: '知识答疑', subtitle: '厘清问题', detail: '先梳理事情经过和希望解决的问题。助手仅提供普法信息与问题整理，不给出责任或赔偿结论。' },
  { number: 2, title: '电子证据', subtitle: '固定保全', detail: '整理病历、检查资料和相关记录，保留来源与时间信息。示例仅提供清单思路，未进行证据保全或自动上传。' },
  { number: 3, title: '人民调解', subtitle: '医患协商', detail: '可了解医院投诉、医患协商和人民调解渠道；具体机构和流程应以当地及院方公布的信息为准。' },
  { number: 4, title: '专业咨询指引', subtitle: '诉讼鉴定', detail: '复杂纠纷可咨询执业律师，结合实际证据判断是否需要鉴定或诉讼。当前为学习示例，未对接真实服务。' }
]
function readingChecks() {
  return ['已阅读病情与拟实施措施示例', '已阅读风险与替代方案提示', '已阅读数据使用与撤回说明', '理解此示例尚未由医护人员审核、尚未签署'].map((label, index) => ({ index, label, checked: false }))
}

Page({
  data: {
    previewMode: true,
    introVisible: true, introClosing: false,
    patientName: '您',
    graphNodes: KNOWLEDGE, processSteps: PROCESS_STEPS,
    sheetType: '', activeNode: {}, activeProcess: {},
    consentTemplates: CONSENT_TEMPLATES, consentIndex: 0, consent: CONSENT_TEMPLATES[0],
    readingChecks: readingChecks(), readingSaved: false,
    selectedLawyer: '公益咨询示例', lawyerRequested: false,
    lawyerSheetTitle: '法律知识学习'
  },
  onLoad() {
    this._introClosing = false
    this.introTimer = setTimeout(() => this.finishIntro(), 4500)
  },
  onShow() {
    const u = getApp().globalData.user
    if (u && u.display_name) this.setData({patientName: u.display_name})
    if (this.data.introVisible && !this._introClosing) {
      clearTimeout(this.introTimer)
      this.introTimer = setTimeout(() => this.finishIntro(), 4500)
    }
  },
  onHide() {
    clearTimeout(this.introTimer)
    if (this._introClosing) {
      clearTimeout(this.introHideTimer)
      this._introClosing = false
      this.setData({introClosing: false})
    }
  },
  onUnload() {
    clearTimeout(this.introTimer)
    clearTimeout(this.introHideTimer)
  },
  finishIntro() {
    if (!this.data.introVisible || this._introClosing) return
    this._introClosing = true
    clearTimeout(this.introTimer)
    this.setData({introClosing: true})
    this.introHideTimer = setTimeout(() => {
      this.setData({introVisible: false, introClosing: false})
      this._introClosing = false
      this.enterChat()
    }, 220)
  },
  enterChat() {
    const url = '/pages/chat/index?domain=legal'
    wx.redirectTo({ url, fail: () => wx.reLaunch({ url }) })
  },
  chat(e) {
    const question = e && e.currentTarget.dataset.question
    wx.navigateTo({ url: '/pages/chat/index?domain=legal' + (question ? '&question=' + encodeURIComponent(question) : '') })
  },
  openConsent() { this.setData({ sheetType: 'consent', readingSaved: false }) },
  chooseConsent(e) {
    const index = Number(e.currentTarget.dataset.index)
    if (!CONSENT_TEMPLATES[index]) return
    this.setData({ consentIndex: index, consent: CONSENT_TEMPLATES[index], readingChecks: readingChecks(), readingSaved: false })
  },
  toggleReading(e) {
    const index = Number(e.currentTarget.dataset.index)
    this.setData({ readingChecks: this.data.readingChecks.map(item => item.index === index ? Object.assign({}, item, { checked: !item.checked }) : item), readingSaved: false })
  },
  confirmReading() {
    if (!this.data.readingChecks.every(item => item.checked)) {
      wx.showToast({ title: '请先逐项阅读并勾选', icon: 'none' })
      return
    }
    // 仅本页内存状态，不生成法律签名，不向医院提交。
    this.setData({ readingSaved: true })
  },
  openLawyer() { this.setData({ sheetType: 'lawyer', lawyerRequested: false }) },
  chooseLawyer(e) { this.setData({ selectedLawyer: e.currentTarget.dataset.name, lawyerRequested: false }) },
  requestLawyer() { this.setData({ lawyerRequested: true }) },
  openKnowledge(e) {
    const node = KNOWLEDGE.find(item => item.key === e.currentTarget.dataset.key)
    if (node) this.setData({ sheetType: 'knowledge', activeNode: node })
  },
  openProcess(e) {
    const step = PROCESS_STEPS[Number(e.currentTarget.dataset.index)]
    if (step) this.setData({ sheetType: 'process', activeProcess: step })
  },
  closeSheet() { this.setData({ sheetType: '' }) },
  noop() {}
})
