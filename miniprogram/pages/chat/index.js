const api = require('../../services/api')

const QUESTIONS = {
  medical: ['胸闷 / 心慌要叫医护吗', '这个药是做什么的', '报告怎么看', '医生这句话什么意思', '复诊要带什么', '出现什么要叫医护', '病历还缺什么'],
  legal: ['怎样申请复制病历', '知情同意是什么', '有纠纷怎么办', '如何撤回授权'],
  volunteer: ['科室怎么走', '怎么办出院手续', '食堂在哪', '想找人说说话']
}

function replyLabel(provider) {
  if (provider === 'deepseek') return 'AI 生成 · 仅供参考'
  if (provider === 'local_safety') return '安全提示'
  if (provider === 'local_medical_boundary') return '医学提醒'
  if (provider === 'local_legal_boundary') return '法律提醒'
  if (provider === 'local_legal_guide') return '法律指引'
  if (provider === 'local_care_guide') return '就诊指引'
  if (provider === 'local_record_checklist') return '病历清单'
  if (provider === 'local_chitchat') return '助手回复'
  if (provider === 'mock') return '演示回复'
  return 'AI 回复 · 服务方未标明'
}

const GENERIC_TOPICS = ['一般医学知识', '一般法律知识']

function activeConsent(info, scope) {
  const policy = info && info.policies && info.policies[scope]
  if (!policy || !policy.notice || !policy.recipient || policy.external_network !== false) return false
  const record = (info.items || []).find(item => item.scope === scope)
  return !!(record && record.granted && !record.revoked_at
    && Date.parse(record.expires_at) > Date.now()
    && record.policy_version === policy.policy_version && record.recipient === policy.recipient)
}

function profileText(value) {
  const text = String(value || '').trim()
  if (!text || /^(无|没有|否认|不详|未知|none|n\/a)/i.test(text)) return ''
  return text
}

function todayKey() {
  const now = new Date()
  const pad = value => (value < 10 ? '0' : '') + value
  return now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate())
}

function recommendFor(profile, overview) {
  const p = profile || {}
  const h = overview || {}
  const items = []
  const seen = Object.create(null)
  const add = (key, reason, question) => {
    if (items.length >= 3 || seen[key]) return
    seen[key] = true
    items.push({key, reason, question})
  }
  if (profileText(p.allergies)) add('allergy', '根据你的过敏史', '我有过敏史，用药时要注意什么？')
  const nextFollowup = (h.followups || []).filter(item => !item.done)
    .sort((a, b) => String(a.due_at || '').localeCompare(String(b.due_at || '')))[0]
  if (nextFollowup) add('followup', '你有复诊安排', '复诊前要准备哪些资料？')
  const today = todayKey()
  const plan = (h.plans || []).find(item => item && item.name && item.start_date
    && today >= item.start_date && (!item.end_date || today <= item.end_date))
  if (plan) add('medication', '根据你的用药记录', '这个药和我正在用的药会冲突吗？')
  const latest = (h.entries || [])[0]
  if (latest) {
    const labels = {heart_rate: '心率', spo2: '血氧', blood_pressure: '血压', symptom: '症状'}
    const label = labels[latest.kind] || '身体指标'
    add('entry', '根据你最近的记录', '我最近记录的' + label + '怎么看？')
  }
  if (Number(p.age) >= 65) add('age', '年龄 ' + p.age + ' 岁', '老年人用药和复诊要注意什么？')
  if (profileText(p.bed_location)) add('bed', '根据你的床位', '在病房遇到紧急情况，怎么最快叫到医护？')
  if (profileText(p.doctor_phone)) add('doctor', '病历里留了医生电话', '什么情况下应该给医生打电话？')
  if (items.length < 2) {
    add('prepare', '通用建议', '怎样把症状和用药情况说清楚？')
    add('followup_generic', '通用建议', '这次复诊最该确认哪几件事？')
  }
  const healthKeys = ['followup', 'medication', 'entry']
  const profileKeys = ['allergy', 'age', 'bed', 'doctor']
  const note = items.some(item => healthKeys.indexOf(item.key) >= 0)
    ? '结合你的资料和近期记录'
    : items.some(item => profileKeys.indexOf(item.key) >= 0) ? '根据你的资料' : '完善资料后可更贴合你'
  return {items, note}
}

function stripCitations(text) {
  return String(text || '').replace(/\s*[\[［【][\d,\s\-–—]+[\]］】]/g, '')
}

function parseAnswer(text) {
  const clean = stripCitations(text)
  const blocks = []
  let paragraph = []
  const flush = () => {
    const value = paragraph.join('\n').trim()
    if (value) blocks.push({type: 'text', text: value})
    paragraph = []
  }
  String(clean).split('\n').forEach(raw => {
    const line = raw.trim()
    if (!line) { flush(); return }
    let match = line.match(/^(?:先说)?结论[:：]\s*(.+)$/)
    if (match) { flush(); blocks.push({type: 'lead', text: match[1]}); return }
    match = line.match(/^(?:就医提示|何时就医|需要就医|出现以下情况|注意|提醒)[:：]\s*(.+)$/)
    if (match) { flush(); blocks.push({type: 'alert', text: match[1]}); return }
    match = line.match(/^(?:复诊提示|下次复诊|复诊安排)[:：]\s*(.+)$/)
    if (match) { flush(); blocks.push({type: 'followup', text: match[1]}); return }
    match = line.match(/^(?:[-*•·]|\d+[.、])\s*(.+)$/)
    if (match) { flush(); blocks.push({type: 'point', text: match[1]}); return }
    paragraph.push(line)
  })
  flush()
  if (!blocks.length) return [{type: 'text', text: clean, key: 0}]
  if (!blocks.some(block => block.type === 'lead')) {
    const first = blocks.find(block => block.type === 'text')
    if (first) {
      const end = first.text.search(/[。！？!?]/)
      if (end > 0 && end <= 70) {
        const index = blocks.indexOf(first)
        const rest = first.text.slice(end + 1).trim()
        const split = [{type: 'lead', text: first.text.slice(0, end + 1)}]
        if (rest) split.push({type: 'text', text: rest})
        blocks.splice(index, 1, ...split)
      }
    }
  }
  return blocks.filter(block => block.text).map((block, index) => Object.assign({key: index}, block))
}

function previewAnswer(text, role, domain) {
  if (/(胸痛|胸闷|呼吸困难|喘不过气|昏迷)/.test(text)) {
    return '如果你现在正有这些不适，请立即使用床旁呼叫器或直接联系病区医护。\n- 别等聊天回复\n- 这个演示不会通知护士，也不会派出救援人员'
  }
  if (role === 'volunteer') {
    if (/(科室|怎么走|在哪|食堂|热水|卫生间|位置)/.test(text)) return '这里演示志愿者的导诊答复：您可以先在「导诊」选择想去的科室，再向护士站核实楼层和无障碍路线。当前没有接入医院真实地图，也没有真人陪同服务。'
    if (/(手续|出院|入院|医保|结算|缴费)/.test(text)) return '这里演示就医流程指引：先向主管医护确认是否已安排出院，再向医院出入院窗口核对材料与办理时间。具体要求以这家医院的说明为准；本演示没有代办或提交任何手续。'
    if (/(药|报告|诊断|检查结果)/.test(text)) return '志愿者主要提供导诊、流程指引和陪伴，不负责诊断、处方或检查结果解读。涉及病情与用药，请直接咨询主管医护。这里没有连接真人志愿者。'
    return '住院时有些孤单或担心，可以先把想说的话写下来，也可以联系家人或向护士寻求陪伴支持。这是志愿者陪伴场景的演示回复，当前没有真人在线接待。'
  }
  if (domain === 'legal') return legalPreviewAnswer(text)
  if (/(缺|完整|齐)/.test(text) && /(病历|资料)/.test(text)) return '可以到「检验单与病历」查看“病历完整性”清单。\n- 它会区分未上传、待核对和已归档\n- 缺文件只说明资料类型不齐，不代表医院诊疗不完整'
  if (/(诊断|看不懂|医嘱|医生.*(说|意思|讲)|这句话)/.test(text)) return '诊断和医嘱，要结合医生记录、检查结果和你的具体情况来看，单看一句话确定不了。\n- 先把医生原话和想问的问题记下来\n- 复诊时逐条请医生解释\n- 这个演示不能判断诊断对不对，也不建议改药'
  if (/(复诊|复查)/.test(text)) return '复诊时间以医生的安排和医院通知为准。\n- 在「健康 → 复诊待办」记录日期和要带的材料\n- 症状加重或出现新的不适，提前联系医护'
  if (/(药|怎么吃|服用|剂量)/.test(text)) return '这个药具体治什么，得看药名和医生怎么交代。\n- 住院用药以医嘱和主管医护的说明为准\n- 把药名、剂量、时间和身体反应记下来\n- 拿不准就询问专业医护或药师，不要自己加量、停药或换药'
  if (/(报告|检查|化验|结果|影像)/.test(text)) return '报告要结合病情、检查时间和参考范围一起看，单看一个箭头说明不了全部。\n- 先记下看不懂的项目\n- 请医护人员结合你的情况解释\n- 这个演示不看病，也没有读取你的真实检查资料'
  if (/(睡|焦虑|心情|烦)/.test(text)) return '住院时睡不好，可以先把影响休息的事情告诉护士。\n- 比如环境、疼痛或心里的担忧\n- 和护士一起商量适合你的办法\n- 这个演示不提供治疗或用药方案'
  return '住院期间有身体不适、用药疑问或检查问题，直接跟医护人员说最稳妥。\n- 这里可以帮你把问题整理清楚\n- 但不能替代面诊、诊断和专业医疗建议'
}

function legalPreviewMeta(text) {
  if (/(打我|被打|打人|殴打|暴力|威胁|报警|人身安全|限制自由)/.test(text)) {
    return {topic: '人身安全', followups: [], doctorQuestions: [], materials: [], nextSteps: []}
  }
  if (/(赔多少|赔偿金额|能赔|要多少钱)/.test(text)) {
    return {
      topic: '赔偿与鉴定',
      followups: [],
      doctorQuestions: ['赔偿项目通常包括哪些？', '需要哪些票据和证明材料？', '责任程度和伤残等级如何影响金额？'],
      materials: ['病历复印件/封存清单', '费用清单和票据', '损害后果资料'],
      nextSteps: ['先固定病历和费用材料', '向医务科、12348或律师核实', '需要责任判断时申请医疗损害鉴定']
    }
  }
  if (/(误诊|过错|医疗事故|医院有责任|承担责任|能不能赢)/.test(text)) {
    return {
      topic: '医疗损害责任',
      followups: [],
      doctorQuestions: ['根据现有病历，需要重点核实哪些诊疗环节？', '是否需要做医疗损害鉴定？', '诉讼时效和证据保全要注意什么？'],
      materials: ['病历复印件/封存清单', '费用清单和票据', '沟通记录'],
      nextSteps: ['先固定病历和沟通记录', '向医务科、12348或律师核实', '需要责任判断时申请医疗损害鉴定']
    }
  }
  if (/(隐私|个人信息|泄露|公开|保密|授权|撤回)/.test(text)) {
    return {
      topic: '隐私与个人信息',
      followups: ['授权后还能撤回吗？', '医院能公开我的病历吗？', '信息泄露后可以怎么处理？'],
      doctorQuestions: ['我的哪些信息会被共享，目的是什么？', '撤回授权后，医院还会保留哪些资料？', '如果信息泄露，医院内部怎么处理？'],
      materials: ['授权/同意记录', '泄露内容截图或时间线', '与医院沟通记录'],
      nextSteps: ['要求医院说明处理目的、范围和保存期限', '撤回同意并要求停止后续处理（法定留存除外）', '向医务科或投诉部门书面反映，必要时咨询12348']
    }
  }
  if (/(病历|病历本|复印|复制|查阅|封存|医嘱单|住院志)/.test(text)) {
    return {
      topic: '病历查阅、复制与封存',
      followups: ['病历可以复印哪些？', '医院不给复印怎么办？', '病历封存怎么启动？'],
      doctorQuestions: ['复制病历需要哪些材料、多久能拿到？', '能否加盖病案室证明印记？', '如果发生争议，病历封存怎么启动？'],
      materials: ['身份证/就诊凭证', '病历资料清单', '已复印或拍照的病历', '封存申请/沟通记录'],
      nextSteps: ['向病案室书面申请查阅/复制', '核对清单和页码，要求加盖证明印记', '发生争议时申请医患双方在场封存']
    }
  }
  if (/(同意|签字|手术|风险|替代方案|特殊检查)/.test(text)) {
    return {
      topic: '知情同意与签字',
      followups: ['签字前我可以问哪些问题？', '紧急情况下没签字怎么办？', '同意书签了还能投诉吗？'],
      doctorQuestions: ['这个操作的必要性、主要风险和替代方案是什么？', '如果不做，可能有什么后果？', '同意书里哪些条款需要我特别注意？'],
      materials: ['知情同意书/手术同意书', '医生对风险、替代方案的说明记录', '患者或家属的问题清单'],
      nextSteps: ['要求医生用大白话说明风险、替代方案和“不做”的后果', '确认理解后再签；有疑问先问', '紧急情况由医院按规定处理，事后可要求说明']
    }
  }
  if (/(纠纷|投诉|调解|诉讼|起诉|鉴定|协商|医务科)/.test(text)) {
    return {
      topic: '医疗纠纷处理',
      followups: ['协商、调解、诉讼怎么选？', '需要准备哪些材料？', '医疗损害鉴定看什么？'],
      doctorQuestions: ['医院内部投诉/医务科的处理流程是什么？', '病历和现场实物是否已经封存？', '是否建议先调解或做鉴定？'],
      materials: ['就诊时间线', '病历复印件/封存清单', '费用清单和票据', '沟通记录', '损害后果资料'],
      nextSteps: ['先固定病历和费用材料', '向医院医务科/投诉部门书面反映', '协商不成可申请人民调解、行政调解或诉讼', '需要责任判断时申请医疗损害鉴定']
    }
  }
  if (/(过度检查|不必要检查|乱检查|重复检查)/.test(text)) {
    return {
      topic: '检查的必要性',
      followups: ['怎么判断检查是否必要？', '怀疑过度检查先找谁？'],
      doctorQuestions: ['这项检查的诊断目的和依据是什么？', '如果不做这项检查，会影响哪些判断？'],
      materials: ['检查申请单', '费用清单', '病历和医嘱', '与医生沟通记录'],
      nextSteps: ['保留检查申请单和费用清单', '向医务科书面询问检查目的和依据', '必要时请专业律师评估']
    }
  }
  if (/(劳动|工伤|离婚|房产|继承|合同|交通事故|刑事|欠款|租房)/.test(text)) {
    return {
      topic: '超出本模块范围',
      followups: [],
      doctorQuestions: [],
      materials: [],
      nextSteps: ['拨打12348公共法律服务热线或咨询律师']
    }
  }
  return {
    topic: '医疗法律知识',
    followups: ['知情同意书里重点看什么？', '病历复印和封存有什么区别？', '发生纠纷先找哪个部门？'],
    doctorQuestions: ['我这个情况适用哪些规定？', '需要准备哪些材料？', '下一步找医务科、12348还是律师？'],
    materials: ['就诊时间线', '相关病历/同意书', '与医护沟通记录'],
    nextSteps: ['先确认事实和时间线', '把问题写成清单', '向医务科、12348或律师核实']
  }
}

function legalPreviewAnswer(text) {
  if (/(打我|被打|打人|殴打|暴力|威胁|报警|人身安全|限制自由)/.test(text)) {
    return '如果正在发生暴力、威胁、限制人身自由，或你感到人身危险：先离开现场，呼叫医院保安，拨打110；有伤情拨打120。保留伤情照片、时间线和证人信息。不要等待聊天回复；这个演示不会通知任何人。'
  }
  if (/(赔多少|赔偿金额|能赔|要多少钱)/.test(text)) {
    return '这里不能根据几句话估算赔偿金额，也不能判断能赔多少。赔偿通常涉及损害后果、医疗费、误工、护理、伤残等，以及责任程度和鉴定意见；协商、调解或诉讼中都会看证据。可以先保存病历、费用票据、沟通记录，再向医务科、12348或律师核实。'
  }
  if (/(误诊|过错|医疗事故|医院有责任|承担责任|能不能赢)/.test(text)) {
    return '这里不能判断这是不是误诊、医院有没有过错，也不能预测能不能赢。医疗损害责任通常要看诊疗行为、损害后果、过错和因果关系；病历、鉴定意见、费用票据是关键材料。可以先固定病历和沟通记录，再请专业律师或鉴定机构评估。'
  }
  if (/(隐私|个人信息|泄露|公开|保密|授权|撤回)/.test(text)) {
    return '医疗健康信息属于敏感个人信息，处理要有特定目的和充分必要性，通常需要单独同意。您可以撤回同意，撤回后应停止后续处理（法定留存等例外除外）。医院及医务人员应对隐私和个人信息保密；泄露或未经同意公开病历，可能承担侵权责任。'
  }
  if (/(病历|病历本|复印|复制|查阅|封存|医嘱单|住院志)/.test(text)) {
    return '您有权查阅、复制门诊病历、住院志、体温单、医嘱单、检验报告、影像资料、同意书、手术及麻醉记录、病理、护理记录、费用等病历资料。医院应提供复制服务并加盖证明印记，复制时应有患者或近亲属在场。发生纠纷时可要求医患双方在场封存病历，开列清单各执一份。'
  }
  if (/(同意|签字|手术|风险|替代方案|特殊检查)/.test(text)) {
    return '知情同意不是只签一个字。需要手术、特殊检查、特殊治疗时，医务人员应说明医疗风险、替代方案等，并取得书面同意；患者无法自主决定或不宜告知时，向近亲属说明并取得书面同意。可以先问：为什么做、不做会怎样、有哪些替代方案、主要风险和失败后怎么办。签字不代表放弃对过错追究。'
  }
  if (/(纠纷|投诉|调解|诉讼|起诉|鉴定|协商|医务科)/.test(text)) {
    return '发生医疗纠纷，可以先固定病历和费用材料，向医院医务科/投诉部门书面反映。解决途径包括双方协商、人民调解、行政调解、诉讼；协商不成可以申请医疗纠纷人民调解，需要明确责任时可做医疗损害鉴定。具体走哪条路、能否获赔，要看事实、证据和鉴定。'
  }
  if (/(过度检查|不必要检查|乱检查|重复检查)/.test(text)) {
    return '如果怀疑不必要的检查，先保留检查申请单、费用清单和病历，向医务科或投诉部门书面询问检查目的和依据；是否属于“违反诊疗规范的不必要检查”，需要结合病情和专业判断，不能只凭项目多少下结论。'
  }
  if (/(劳动|工伤|离婚|房产|继承|合同|交通事故|刑事|欠款|租房)/.test(text)) {
    return '这个模块只覆盖就医过程中的知情同意、病历资料、隐私保护和医疗纠纷处理。劳动、工伤、交通事故、婚姻继承、房产等不属于这里；您可以拨打12348公共法律服务热线或咨询律师。'
  }
  return '有疑问时，可以先整理经过、就诊资料和希望解决的问题，再向医院医务科、投诉接待部门或专业人员咨询。这里只做普法与风险提示，不判断具体责任，也没有替您联系专业人员。'
}


function previewMeta(text, role, domain) {
  if (domain === 'legal' && role !== 'volunteer') return legalPreviewMeta(text)
  if (role === 'volunteer' || /(胸痛|胸闷|呼吸困难|喘不过气|昏迷)/.test(text)) {
    return {topic: '', followups: [], doctorQuestions: []}
  }
  if (/(药|怎么吃|服用|剂量|副作用)/.test(text)) {
    return {
      topic: '用药',
      followups: ['漏服了一次怎么办？', '这个药和别的药能一起吃吗？', '出现皮疹或黑便怎么办？'],
      doctorQuestions: ['这个药主要是治什么的？', '漏服或不舒服时应该怎么处理？', '和其他药一起吃要注意什么？']
    }
  }
  if (/(报告|检查|化验|结果|影像|指标|偏高|偏低)/.test(text)) {
    return {
      topic: '检查报告',
      followups: ['这个指标需要空腹复查吗？', '复查前要注意什么？', '这个结果和我在吃的药有关吗？'],
      doctorQuestions: ['这个指标和参考区间相比具体偏了多少？', '这次结果和上次比是变好还是变差？', '需要复查或进一步检查吗？']
    }
  }
  return {
    topic: '一般医学知识',
    followups: ['这个情况需要马上处理吗？', '出现哪些变化要叫医护？', '复诊时要带哪些资料？'],
    doctorQuestions: ['这个症状最可能和哪些因素有关？', '需要马上处理还是可以观察？', '出现哪些变化要提前叫医护？']
  }
}

Page({
  data: {
    domain: 'medical', role: 'assistant', roleName: '健康知识助手',
    roleSwitchLabel: '切换到志愿者陪伴',
    placeholder: '说说哪里不舒服，或想问医生什么…',
    questions: QUESTIONS.medical, messages: [], text: '', busy: false,
    menuOpen: false, scrollTo: '', previewMode: true, animateAnswers: true,
    doctorPhone: '', recommendations: [], recoNote: '',
    statusBarHeight: 20, navHeight: 56, capsuleInset: 12
  },
  onLoad(query) {
    this.sequence = 0
    this.conversationId = null
    this.disposed = false
    this.legalTourAdded = false
    this.identityVersion = api.identity.getVersion()
    this.identityUserId = (api.identity.getUser() || {}).id || ''
    const domain = query && query.domain === 'legal' ? 'legal' : 'medical'
    const previewMode = getApp().globalData.previewMode !== false
    let initialQuestion = query && typeof query.question === 'string' ? query.question : ''
    try { initialQuestion = decodeURIComponent(initialQuestion) } catch (_) { /* Keep malformed input as plain text. */ }
    initialQuestion = initialQuestion.slice(0, 500)
    let statusBarHeight = 20
    let navHeight = 56
    let capsuleInset = 12
    try {
      const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
      statusBarHeight = windowInfo.statusBarHeight || 20
      if (wx.getMenuButtonBoundingClientRect) {
        const capsule = wx.getMenuButtonBoundingClientRect()
        if (capsule && capsule.left > 0) {
          capsuleInset = Math.max(12, windowInfo.windowWidth - capsule.left + 8)
          navHeight = Math.max(48, (capsule.top - statusBarHeight) * 2 + capsule.height)
        }
      }
    } catch (_) { /* Default metrics keep the page usable in static previews. */ }
    this.setData({domain, previewMode, statusBarHeight, navHeight, capsuleInset, text: initialQuestion})
    this.updateRole()
    this.startOpening()
  },
  onShow() {
    // Consent is server-owned and can be granted or revoked from profile or
    // home while this page is hidden; re-check on every return instead of
    // trusting a page-local cache.
    this._aiAuthorized = false
    // If the identity changed while this page was hidden (login/logout/switch
    // from the profile page), drop the old user's conversation and messages so
    // the new identity starts clean.
    const version = api.identity.getVersion()
    const userId = (api.identity.getUser() || {}).id || ''
    if (version !== this.identityVersion || userId !== this.identityUserId) {
      this.identityVersion = version
      this.identityUserId = userId
      this.conversationId = null
      this.legalTourAdded = false
      clearTimeout(this.tourTypingTimer)
      this.setData({messages: [], text: '', busy: false, scrollTo: ''})
      this.updateRole()
      this.startOpening()
    }
    this.loadDoctorPhone()
    this.loadRecommendations()
  },
  async loadDoctorPhone() {
    if (this.data.domain !== 'medical' || this.data.previewMode) {
      if (this.data.doctorPhone) this.setData({doctorPhone: ''})
      return
    }
    try {
      const me = await api.getMe()
      const phone = (me && me.profile && me.profile.doctor_phone) || ''
      if (!this.disposed) this.setData({doctorPhone: phone})
    } catch (_) {
      // A missing profile must not block the conversation.
    }
  },
  buildRecommendations(profile, overview) {
    return recommendFor(profile, overview)
  },
  async loadRecommendations() {
    this.recoSequence = (this.recoSequence || 0) + 1
    const sequence = this.recoSequence
    const current = () => !this.disposed && sequence === this.recoSequence
    if (this.data.domain !== 'medical' || this.data.role !== 'assistant') {
      if (this.data.recommendations.length || this.data.recoNote) {
        this.setData({recommendations: [], recoNote: ''})
      }
      return
    }
    const capturedVersion = api.identity.getVersion()
    if (this.data.previewMode) {
      const demo = this.buildRecommendations({}, null)
      this.setData({recommendations: demo.items, recoNote: '演示推荐'})
      return
    }
    try {
      const me = await api.getMe()
      let overview = null
      try {
        const info = await api.request('/consents')
        if (activeConsent(info, 'vitals')) {
          overview = await api.request('/health-management/overview?day=' + encodeURIComponent(todayKey()))
        }
      } catch (_) {
        // Profile-only recommendations are still useful when health data is unavailable.
      }
      if (!current() || capturedVersion !== api.identity.getVersion()) return
      const result = this.buildRecommendations((me && me.profile) || {}, overview)
      this.setData({recommendations: result.items, recoNote: result.note})
    } catch (_) {
      if (!current() || capturedVersion !== api.identity.getVersion()) return
      const result = this.buildRecommendations({}, null)
      this.setData({recommendations: result.items, recoNote: result.note})
    }
  },
  callDoctor() {
    const phone = String(this.data.doctorPhone || '').replace(/[^\d+]/g, '')
    if (!phone) return
    wx.makePhoneCall({
      phoneNumber: phone,
      fail: () => wx.showToast({title: '未能拨号，请手动输入号码', icon: 'none'})
    })
  },
  onUnload() {
    this.disposed = true
    clearTimeout(this.replyTimer)
    clearTimeout(this.tourTypingTimer)
    Object.keys(this.answerTimers || {}).forEach(id => clearTimeout(this.answerTimers[id]))
    if (this.finishDelay) this.finishDelay()
  },
  updateRole() {
    const volunteer = this.data.role === 'volunteer'
    const legal = this.data.domain === 'legal'
    const name = legal ? '法律知识助手' : '健康知识助手'
    this.setData({
      roleName: volunteer ? '志愿者陪伴' : name,
      roleSwitchLabel: volunteer ? '切换到' + name : '切换到志愿者陪伴',
      questions: QUESTIONS[volunteer ? 'volunteer' : this.data.domain],
      placeholder: volunteer ? '想去哪里，或想聊些什么…' : (legal ? '说说您想了解的患者权益问题…' : '说说哪里不舒服，或想问医生什么…')
    })
  },
  startOpening() {
    if (this.data.domain === 'legal') this.addLegalTour()
    else this.addGreeting()
  },
  addLegalTour() {
    if (this.legalTourAdded) return
    this.legalTourAdded = true
    const cards = [
      {key: 'rights', icon: '权', tone: 'teal', title: '问权益', text: '知情同意、病历查阅、隐私授权、纠纷处理'},
      {key: 'plain', icon: '白', tone: 'blue', title: '说直白点', text: '我解释法条，并标出还要向医护核实的事实'},
      {key: 'materials', icon: '材', tone: 'warm', title: '备材料', text: '生成知情同意草稿，带去和医护逐条确认'}
    ]
    const message = this.addMessage('ai', '', {
      label: '模块用法 · 演示', cards, cardsVisible: false, typing: true,
      footnote: '我只做普法与风险提示，不判断责任，也不替代律师。',
      disclaimer: '学习示例，不构成正式法律意见。'
    })
    this.typeTour(message.id, '您好，我是智联知识助手。\n\n这个窗口可以这样用：')
  },
  typeTour(id, fullText) {
    clearTimeout(this.tourTypingTimer)
    let index = 0
    const tick = () => {
      if (this.disposed) return
      index += 1
      const done = index >= fullText.length
      this.patchMessage(id, {text: fullText.slice(0, index), typing: !done, cardsVisible: done})
      if (!done) this.tourTypingTimer = setTimeout(tick, 28)
    }
    this.tourTypingTimer = setTimeout(tick, 260)
  },
  showAnswer(text, options) {
    const value = stripCitations(text)
    if (!this.data.animateAnswers) {
      this.addMessage('ai', value, Object.assign({}, options, {typing: false}))
      return
    }
    const message = this.addMessage('ai', '', Object.assign({}, options, {typing: true}))
    this.typeAnswer(message.id, value)
  },
  typeAnswer(id, fullText) {
    const value = stripCitations(fullText)
    this.answerTimers = this.answerTimers || {}
    clearTimeout(this.answerTimers[id])
    if (!value) {
      this.patchMessage(id, {typing: false})
      return
    }
    let index = 0
    const step = Math.max(1, Math.ceil(value.length / 70))
    const tick = () => {
      if (this.disposed) return
      index = Math.min(value.length, index + step)
      const done = index >= value.length
      this.patchMessage(id, {text: value.slice(0, index), typing: !done})
      if (done) delete this.answerTimers[id]
      else this.answerTimers[id] = setTimeout(tick, 20)
    }
    this.answerTimers[id] = setTimeout(tick, 160)
  },
  patchMessage(id, patch) {
    this.setData({messages: this.data.messages.map(item => {
      if (item.id !== id) return item
      const next = Object.assign({}, item, patch)
      if (typeof patch.text === 'string') next.blocks = parseAnswer(patch.text)
      return next
    })})
  },
  addMessage(role, text, options) {
    const extra = options || {}
    const id = 'message-' + Date.now() + '-' + (++this.sequence)
    const topic = GENERIC_TOPICS.indexOf(extra.topic) >= 0 ? '' : (extra.topic || '')
    const message = {id, role, text, blocks: role === 'user' ? [] : parseAnswer(text), label: extra.label || '', cards: extra.cards || [],
      cardsVisible: extra.cardsVisible !== false, typing: !!extra.typing, footnote: extra.footnote || '',
      disclaimer: extra.disclaimer || '', error: !!extra.error,
      action: extra.action || '', actionLabel: extra.actionLabel || '',
      topic, materials: extra.materials || [], nextSteps: extra.nextSteps || []}
    this.setData({messages: this.data.messages.concat([message]), scrollTo: id})
    return message
  },
  addGreeting() {
    const volunteer = this.data.role === 'volunteer'
    const text = volunteer
      ? '您好，这里是志愿者陪伴的演示角色。可以试着问我科室位置、就医流程，或聊聊住院时的心情；当前没有连接真人志愿者。'
      : this.data.domain === 'legal'
        ? '您好，我是法律知识助手。您可以询问病历查阅、知情同意和患者权益，我会尽量说得直白些。请不要输入真实身份或就诊资料。'
        : '您好，我是健康知识助手。可以问我医生的话、检查报告或用药安排是什么意思，我会尽量用日常话解释。'
    this.addMessage('ai', text, {disclaimer: this.data.domain === 'legal' ? '以上由 AI 助手整理，供普法参考；具体请咨询专业律师。' : '以上由 AI 助手整理，供理解参考；具体以医生、护士的说明为准。'})
  },
  back() { wx.navigateBack({delta: 1, fail: () => wx.switchTab({url: '/pages/home/index'})}) },
  toggleMenu() { this.setData({menuOpen: !this.data.menuOpen}) },
  // 法知区的真人服务窗口：问题交给已核验的法律志愿者接单回复。
  openHumanHelp() { wx.navigateTo({url: '/pages/legal-help/index'}) },
  closeMenu() { this.setData({menuOpen: false}) },
  switchRole() {
    if (this.data.busy) return
    const role = this.data.role === 'assistant' ? 'volunteer' : 'assistant'
    this.setData({role, menuOpen: false, text: ''})
    this.updateRole()
    this.loadRecommendations()
    this.addMessage('ai', role === 'volunteer'
      ? '已切换到志愿者陪伴演示。可以了解导诊与就医流程；这里没有真人接听，不提供诊断和用药建议。'
      : '已切换回' + this.data.roleName + '。我们可以继续整理您的问题，具体情况请向医护或法律专业人员核实。', {label: '角色切换 · 演示'})
  },
  clearChat() {
    if (this.data.busy) return
    this.closeMenu()
    wx.showModal({
      title: '清空当前聊天',
      content: '清空本页显示并开始新会话？这不会删除已保存在本机服务中的记录。',
      confirmText: '清空', confirmColor: '#0E7C86',
      success: result => {
        if (!result.confirm || this.disposed) return
        this.conversationId = null
        this.legalTourAdded = false
        clearTimeout(this.tourTypingTimer)
        this.setData({messages: [], text: '', scrollTo: ''})
        this.startOpening()
      }
    })
  },
  onInput(event) { this.setData({text: event.detail.value}) },
  askQuick(event) {
    if (this.data.busy) return
    this.setData({text: event.currentTarget.dataset.question})
    this.send()
  },
  handleAction(event) {
    if (event.currentTarget.dataset.action !== 'settings') return
    const app = getApp()
    if (app && app.globalData) app.globalData.openSettings = true
    wx.switchTab({url: '/pages/profile/index'})
  },
  async ensureAiAccess() {
    if (this.data.previewMode || this.data.role === 'volunteer' || this._aiAuthorized) return true
    const scope = 'ai_' + this.data.domain
    let info
    try {
      info = await api.request('/consents')
    } catch (_) {
      // The send request will surface the real connection/consent error.
      return true
    }
    const policy = info && info.policies && info.policies[scope]
    if (!policy || !policy.notice || !policy.recipient || !policy.policy_version) return true
    const record = (info.items || []).find(item => item.scope === scope)
    const active = !!(record && record.granted && !record.revoked_at
      && Date.parse(record.expires_at) > Date.now()
      && record.recipient === policy.recipient && record.policy_version === policy.policy_version)
    if (active) {
      this._aiAuthorized = true
      return true
    }
    const confirmed = await new Promise(resolve => wx.showModal({
      title: this.data.domain === 'legal' ? '法律问答授权' : '健康问答授权',
      content: policy.notice,
      confirmText: '同意并继续', confirmColor: '#0E7C86',
      success: result => resolve(!!result.confirm), fail: () => resolve(false)
    }))
    if (!confirmed) return false
    await api.request('/consents', 'POST', {
      scope, granted: true, recipient: policy.recipient, policy_version: policy.policy_version
    })
    this._aiAuthorized = true
    return true
  },
  async send() {
    const text = this.data.text.trim()
    if (!text || this.data.busy) return
    const simulated = this.data.previewMode || this.data.role === 'volunteer'
    if (!simulated && !getApp().globalData.token) {
      wx.showModal({title: '请先连接并授权', content: '请到「我的 → 设置」点击「连接本机服务」，再阅读并确认相应用途的授权告知。', showCancel: false})
      return
    }
    const capturedVersion = api.identity.getVersion()
    const identityChanged = () => this.disposed || api.identity.getVersion() !== capturedVersion
    if (!simulated) {
      try {
        const allowed = await this.ensureAiAccess()
        if (identityChanged()) return
        if (!allowed) {
          this.setData({text})
          wx.showToast({title: '未授权，消息没有发送', icon: 'none'})
          return
        }
      } catch (error) {
        if (!identityChanged()) {
          this.addMessage('ai', '暂时无法检查问答授权：' + (error.message || '请稍后重试'), {
            label: '发送未完成', error: true, action: 'settings', actionLabel: '去设置授权'
          })
        }
        return
      }
    }
    this.closeMenu()
    this.addMessage('user', text)
    this.setData({text: '', busy: true, scrollTo: 'typing-row'})
    try {
      if (simulated) {
        await new Promise(resolve => {
          this.finishDelay = resolve
          this.replyTimer = setTimeout(resolve, 450)
        })
        this.finishDelay = null
        if (identityChanged()) return
        const meta = previewMeta(text, this.data.role, this.data.domain)
        this.showAnswer(previewAnswer(text, this.data.role, this.data.domain), {
          label: '演示回复', topic: meta.topic, followups: meta.followups,
          doctorQuestions: meta.doctorQuestions, materials: meta.materials, nextSteps: meta.nextSteps
        })
      } else {
        if (!this.conversationId) {
          const conversation = await api.request('/conversations', 'POST', {domain: this.data.domain})
          if (identityChanged()) return
          this.conversationId = conversation.id
        }
        const result = await api.request('/conversations/' + this.conversationId + '/messages', 'POST', {text})
        if (identityChanged()) return
        this.showAnswer(result.answer, {
          label: replyLabel(result.provider),
          disclaimer: result.disclaimer,
          topic: result.topic || '',
          materials: result.materials || [], nextSteps: result.next_steps || []
        })
      }
    } catch (error) {
      if (!identityChanged()) {
        const unauthorized = error.status === 403 && /授权/.test(error.message || '')
        this.addMessage('ai', unauthorized
          ? '这个账号还没有当前用途的有效授权，消息没有发送。授权只影响之后的问题，可以随时撤回。'
          : '未取得回复：' + (error.message || '请稍后重试') + '。请检查本机服务是否启动、手机和电脑是否在同一网络。', {
            label: '发送未完成', error: true,
            action: unauthorized ? 'settings' : '', actionLabel: unauthorized ? '去设置授权' : ''
          })
        this._aiAuthorized = false
        this.setData({text})
      }
    } finally {
      if (!this.disposed && api.identity.getVersion() === capturedVersion) this.setData({busy: false})
    }
  }
})
