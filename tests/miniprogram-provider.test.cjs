const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const capabilities = require('../miniprogram/utils/capabilities')

const settle = () => new Promise(resolve => setImmediate(resolve))
const event = {currentTarget: {dataset: {scope: 'ai_medical'}}}
const externalPolicy = {
  recipient: 'deepseek_official_api', policy_version: 'deepseek-demo-v1', provider: 'deepseek', external_network: true,
  notice: '当前问题与命中参考材料发送 DeepSeek；不上传病历或历史。当前为单轮问答。授权有效期30天，可撤回；已发出的请求不可收回。仅允许合成场景。'
}
const localPolicy = {recipient: 'local_demo_process', policy_version: 'demo-1', provider: 'mock', external_network: false, notice: '仅在本机处理合成资料，授权可撤回。'}
const policies = () => ({ai_medical: {...externalPolicy}, ai_legal: {...externalPolicy}, vitals: {...localPolicy}, records_read: {...localPolicy}})
const record = policy => ({scope: 'ai_medical', granted: true, revoked_at: null, expires_at: new Date(Date.now() + 60000).toISOString(), recipient: policy.recipient, policy_version: policy.policy_version})

function pageHarness(name, api, previewMode = false) {
  let definition
  const app = {globalData: {previewMode, token: previewMode ? null : 'synthetic-test-token', user: previewMode ? null : {id: 'demo-patient-001', role: 'patient'}, identityVersion: 1}}
  // Injected identity shim: tracks token/user/version in the app globalData so
  // page guards behave the same way they would against the real module.
  api = Object.assign({
    login: async () => { throw new Error('login not mocked') },
    logout: async () => { app.globalData.token = null; app.globalData.user = null; app.globalData.previewMode = true; app.globalData.identityVersion++ },
    getMe: async () => ({id: 'demo-patient-001', role: 'patient', profile: null}),
    request: async () => ({items: [], policies: {}}),
    identity: {
      getToken: () => app.globalData.token,
      getUser: () => app.globalData.user,
      getVersion: () => app.globalData.identityVersion,
      saveSession(token, user) { app.globalData.token = token; app.globalData.user = user; app.globalData.previewMode = !token; app.globalData.identityVersion++ },
      clearSession() { app.globalData.token = null; app.globalData.user = null; app.globalData.previewMode = true; app.globalData.identityVersion++ }
    }
  }, api)
  const modals = [], errors = [], redirects = []
  const sandbox = {
    Page(value) { definition = value },
    require(name) {
      if (name.includes('services/api')) return api
      if (name.includes('utils/capabilities')) return capabilities
      return error => errors.push(error.message)
    },
    getApp() { return app },
    wx: {
      showModal(options) { modals.push(options) }, showToast() {},
      redirectTo(options) { redirects.push(options.url) }, reLaunch(options) { redirects.push(options.url) }
    },
    Date,
    setTimeout(fn) { queueMicrotask(fn); return 1 }, clearTimeout() {}
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../miniprogram/pages', name, 'index.js'), 'utf8'), sandbox)
  const page = {data: structuredClone(definition.data), setData(values) { Object.assign(this.data, values) }}
  page.setData({animateAnswers: false})
  for (const [key, value] of Object.entries(definition)) if (typeof value === 'function') page[key] = value.bind(page)
  return {page, app, modals, errors, api, redirects}
}

test('旧本地授权或接收方/版本变更均不能显示有效外部授权', async () => {
  const response = {items: [record(localPolicy)], policies: policies()}
  const {page} = pageHarness('profile', {request: async () => response})
  await page.refresh()
  assert.equal(page.data.scopes[0].active, false)
  assert.equal(page.data.scopes[0].statusLabel, '需重新授权')
  response.items = [record(externalPolicy)]
  await page.refresh()
  assert.equal(page.data.scopes[0].active, true)
  response.policies.ai_medical = {...externalPolicy, recipient: 'changed-recipient'}
  await page.refresh()
  assert.equal(page.data.scopes[0].statusLabel, '需重新授权')
  response.policies.ai_medical = {...externalPolicy, policy_version: 'next-version'}
  await page.refresh()
  assert.equal(page.data.scopes[0].active, false)
})

test('逐次展示服务器告知，取消无写入，确认才提交准确接收方和版本', async () => {
  const writes = [], response = {items: [], policies: policies()}
  const {page, modals} = pageHarness('profile', {request: async (url, method, body) => {
    if (method === 'POST') { writes.push({...body}); response.items = [record(externalPolicy)] }
    return response
  }})
  await page.refresh()
  const cancelled = page.grant(event)
  await settle()
  assert.equal(writes.length, 0)
  assert.ok(modals[0].content.includes(externalPolicy.notice))
  modals[0].success({confirm: false})
  await cancelled
  assert.equal(writes.length, 0)
  const confirmed = page.grant(event)
  await settle()
  assert.equal(writes.length, 0)
  modals[1].success({confirm: true})
  await confirmed
  assert.deepEqual(writes, [{scope: 'ai_medical', granted: true, recipient: externalPolicy.recipient, policy_version: externalPolicy.policy_version}])
  assert.equal(page.data.scopes[0].active, true)
})

test('缺少完整告知时关闭授权通道，绝不沿用本地默认授权', async () => {
  const writes = []
  const {page, modals, errors} = pageHarness('profile', {request: async (_url, method) => {
    if (method === 'POST') writes.push(method)
    return {items: [record(localPolicy)]}
  }})
  await page.refresh()
  await page.grant(event)
  assert.equal(page.data.scopes[0].active, false)
  assert.equal(modals.length, 0)
  assert.equal(writes.length, 0)
  assert.equal(errors.length, 1)
})

test('阅读弹窗后政策变化由后端拒绝，前端不自动改用新版本重试', async () => {
  const response = {items: [], policies: policies()}, writes = []
  const {page, modals, errors} = pageHarness('profile', {request: async (_url, method, body) => {
    if (method === 'POST') { writes.push({...body}); throw new Error('告知版本已变化') }
    return response
  }})
  await page.refresh()
  const pending = page.grant(event)
  await settle()
  response.policies.ai_medical = {...externalPolicy, policy_version: 'next-version'}
  modals[0].success({confirm: true})
  await pending
  assert.equal(writes.length, 1)
  assert.equal(writes[0].policy_version, externalPolicy.policy_version)
  assert.deepEqual(errors, ['告知版本已变化'])
  assert.equal(modals.length, 1)
})

test('离线预览不登录或授权，晚到的授权查询不能覆盖退出状态', async () => {
  let calls = 0, resolveQuery
  const offline = pageHarness('profile', {request: async () => { calls++ }, login: async () => { calls++ }}, true)
  await offline.page.refresh()
  await offline.page.grant(event)
  assert.equal(calls, 0)
  const online = pageHarness('profile', {request: () => new Promise(resolve => { resolveQuery = resolve })})
  const pending = online.page.refresh()
  await settle()
  online.page.logout()
  resolveQuery({items: [record(externalPolicy)], policies: policies()})
  await pending
  assert.equal(online.app.globalData.previewMode, true)
  assert.ok(online.page.data.scopes.every(scope => !scope.active))
})

test('模型、本地安全规则和Mock回复分别标注，消息仅提交当前问题', async () => {
  for (const [provider, expected] of [['deepseek', /AI 生成/], ['local_safety', /安全提示/], ['local_medical_boundary', /医学提醒/], ['local_legal_boundary', /法律提醒/], ['local_legal_guide', /法律指引/], ['local_care_guide', /就诊指引/], ['local_record_checklist', /病历清单/], ['mock', /演示回复/]]) {
    const writes = []
    const {page} = pageHarness('chat', {request: async (url, _method, body) => {
      writes.push({...body})
      return url === '/conversations' ? {id: 'demo-chat'} : {provider, answer: '合成场景回答', sources: []}
    }})
    page.onLoad({domain: 'legal'})
    page.setData({text: '知情同意是什么'})
    await page.send()
    assert.match(page.data.messages.at(-1).label, expected)
    assert.deepEqual(writes.find(item => item && item.text), {text: '知情同意是什么'})
  }
})

test('法知页只播天平开场，结束后直接进入智能体对话', async () => {
  const {page, redirects} = pageHarness('legal', {})
  page.onLoad()
  assert.equal(page.data.introVisible, true)
  page.finishIntro()
  await settle()
  assert.equal(page.data.introVisible, false)
  assert.equal(page.data.introClosing, false)
  assert.deepEqual(redirects, ['/pages/chat/index?domain=legal'])
})

test('进入法律对话后打字介绍三个彩色用法卡片，不再重复播放动画', async () => {
  const {page} = pageHarness('chat', {})
  page.onLoad({domain: 'legal'})
  assert.equal(page.data.introVisible, undefined)
  await settle()
  const tours = page.data.messages.filter(message => message.label === '模块用法 · 演示')
  assert.equal(tours.length, 1)
  assert.equal(tours[0].typing, false)
  assert.equal(tours[0].cardsVisible, true)
  assert.equal(tours[0].cards.length, 3)
  assert.equal(tours[0].cards.map(card => card.title).join(','), '问权益,说直白点,备材料')
  assert.match(tours[0].text, /这个窗口可以这样用/)
  assert.match(tours[0].footnote, /不替代律师/)
  page.onShow()
  assert.equal(page.data.messages.filter(message => message.label === '模块用法 · 演示').length, 1)
})

test('在线请求失败保留错误与输入，不回退到模拟回复或自动登录', async () => {
  let calls = 0
  const {page} = pageHarness('chat', {request: async url => {
    calls++
    if (url === '/conversations') return {id: 'demo-chat'}
    throw new Error('模型暂不可用')
  }, login: async () => assert.fail('must not auto-login')})
  page.onLoad({})
  page.setData({text: '合成问题'})
  await page.send()
  const last = page.data.messages.at(-1)
  assert.equal(last.error, true)
  assert.equal(last.label, '发送未完成')
  assert.match(last.text, /模型暂不可用/)
  assert.equal(page.data.text, '合成问题')
  assert.equal(calls, 3)
})

test('聊天页直接读取服务器授权，确认后写入同一用途并继续发送', async () => {
  const grants = []
  const {page, modals} = pageHarness('chat', {request: async (url, method, body) => {
    if (url === '/consents' && (!method || method === 'GET')) return {items: [], policies: policies()}
    if (url === '/consents' && method === 'POST') { grants.push(body); return {...record(externalPolicy), ...body} }
    if (url === '/conversations') return {id: 'demo-chat'}
    return {provider: 'deepseek', answer: '授权后回答', sources: []}
  }})
  page.onLoad({})
  page.setData({text: '这个药是做什么的'})
  const pending = page.send()
  await settle()
  assert.equal(modals.length, 1)
  assert.match(modals[0].title, /健康问答授权/)
  modals[0].success({confirm: true})
  await pending
  assert.equal(JSON.stringify(grants), JSON.stringify([{scope: 'ai_medical', granted: true, recipient: externalPolicy.recipient, policy_version: externalPolicy.policy_version}]))
  assert.equal(page.data.messages.at(-1).text, '授权后回答')
})

test('已有有效授权不重复弹窗，直接沿用并继续发送', async () => {
  const {page, modals} = pageHarness('chat', {request: async (url, method) => {
    if (url === '/consents' && (!method || method === 'GET')) return {items: [record(externalPolicy)], policies: policies()}
    if (url === '/conversations') return {id: 'demo-chat'}
    return {provider: 'deepseek', answer: '沿用已有授权', sources: []}
  }})
  page.onLoad({})
  page.setData({text: '这个药是做什么的'})
  await page.send()
  assert.equal(modals.length, 0)
  assert.equal(page.data.messages.at(-1).text, '沿用已有授权')
})

test('离线聊天继续使用明确演示回复且无网络请求', async () => {
  const {page} = pageHarness('chat', {request: async () => assert.fail('offline must not request')}, true)
  page.onLoad({})
  assert.equal(page.data.subtitle, undefined)
  assert.match(page.data.messages[0].text, /健康知识助手/)
  assert.doesNotMatch(page.data.messages[0].text, /只做三件事|不看病、不诊断/)
  assert.match(page.data.messages[0].disclaimer, /以医生、护士的说明为准/)
  page.setData({text: '这个药怎么吃'})
  await page.send()
  assert.equal(page.data.messages.at(-1).label, '演示回复')
  assert.match(page.data.messages.at(-1).text, /医嘱/)
  assert.equal(page.data.messages.at(-1).topic, '用药')
  assert.equal(page.data.messages.at(-1).suggestions, undefined)
})

test('法律离线回复携带主题、追问、材料和下一步清单', async () => {
  const {page} = pageHarness('chat', {request: async () => assert.fail('offline must not request')}, true)
  page.onLoad({domain: 'legal'})
  page.setData({text: '怎样申请复制病历'})
  await page.send()
  const last = page.data.messages.at(-1)
  assert.equal(last.label, '演示回复')
  assert.match(last.text, /病案室|病历/)
  assert.equal(last.topic, '病历查阅、复制与封存')
  assert.ok(last.materials.length >= 2)
  assert.ok(last.nextSteps.length >= 2)
})

test('回答消息不再携带 suggestions 字段', async () => {
  const {page} = pageHarness('chat', {request: async () => assert.fail('offline must not request')}, true)
  page.onLoad({})
  const message = page.addMessage('ai', '示例回答', {
    followups: ['出现哪些变化要叫医护？'],
    doctorQuestions: ['需要复查吗？']
  })
  assert.equal(message.suggestions, undefined)
})

test('回答正文不显示引用编号', async () => {
  const {page} = pageHarness('chat', {request: async () => assert.fail('offline must not request')}, true)
  page.onLoad({})
  const message = page.addMessage('ai', '记下药名、剂量和时间[1]。\n- 复诊时带给医生看[2]', {})
  const shown = message.blocks.map(block => block.text).join('\n')
  assert.doesNotMatch(shown, /\[[12]\]/)
  assert.match(shown, /记下药名、剂量和时间。/)
  assert.match(shown, /复诊时带给医生看/)
})

test('智能体回答逐字显示，完成后才展示追问', async () => {
  const {page} = pageHarness('chat', {request: async () => assert.fail('offline must not request')}, true)
  page.onLoad({})
  page.setData({animateAnswers: true})
  page.showAnswer('第一句。\n- 要点[1]', {followups: ['还要问什么？']})
  assert.equal(page.data.messages.at(-1).text, '')
  assert.equal(page.data.messages.at(-1).typing, true)
  await settle()
  const last = page.data.messages.at(-1)
  assert.equal(last.typing, false)
  assert.equal(last.text, '第一句。\n- 要点')
  assert.equal(last.suggestions, undefined)
})

test('医学回复携带可继续追问和问医生的问题，历史字段不会混入法律对话', async () => {
  const {page} = pageHarness('chat', {request: async url => {
    if (url === '/conversations') return {id: 'demo-chat'}
    return {
      provider: 'local_medical_boundary', answer: '这是医学边界内的大白话解释。', sources: [],
      topic: '肝功能',
    }
  }})
  page.onLoad({})
  page.setData({text: '转氨酶偏高说明什么'})
  await page.send()
  const last = page.data.messages.at(-1)
  assert.equal(last.label, '医学提醒')
  assert.equal(last.topic, '肝功能')
  assert.equal(last.suggestions, undefined)

  const legal = pageHarness('chat', {request: async url => {
    if (url === '/conversations') return {id: 'legal-chat'}
    return {
      provider: 'local_legal_guide', answer: '法律示例回答。', sources: [],
      topic: '知情同意与签字', followups: ['签字前我可以问哪些问题？'],
      materials: ['知情同意书/手术同意书'], next_steps: ['要求医生说明风险和替代方案'],
      doctor_questions: ['这个操作的必要性是什么？']
    }
  }})
  legal.page.onLoad({domain: 'legal'})
  legal.page.setData({text: '知情同意是什么'})
  await legal.page.send()
  assert.equal(legal.page.data.messages.at(-1).label, '法律指引')
  assert.equal(legal.page.data.messages.at(-1).topic, '知情同意与签字')
  assert.deepEqual(legal.page.data.messages.at(-1).materials, ['知情同意书/手术同意书'])
  assert.deepEqual(legal.page.data.messages.at(-1).nextSteps, ['要求医生说明风险和替代方案'])
})

test('个性化推荐按资料和记录排序，只给提问入口，不给诊断或剂量', () => {
  const {page} = pageHarness('chat', {}, true)
  const result = page.buildRecommendations(
    {allergies: '青霉素', age: 70, bed_location: '3床', doctor_phone: '13800138000'},
    {
      followups: [{due_at: '2026-10-25', done: false}],
      plans: [{name: '阿莫西林', start_date: '2000-01-01'}],
      entries: [{kind: 'heart_rate'}]
    }
  )
  assert.deepEqual(Array.from(result.items, item => item.key), ['allergy', 'followup', 'medication'])
  assert.equal(result.note, '结合你的资料和近期记录')
  for (const item of result.items) {
    assert.ok(item.reason && item.question)
    assert.doesNotMatch(item.question, /诊断|确诊|开药|剂量|停药/)
  }
  const generic = page.buildRecommendations({}, null)
  assert.equal(generic.items.length, 2)
  assert.equal(generic.note, '完善资料后可更贴合你')
  const noAllergy = page.buildRecommendations({allergies: '无过敏史'}, null)
  assert.ok(!Array.from(noAllergy.items, item => item.key).includes('allergy'))
})

test('在线聊天页只有有效记录授权时才读取健康概览', async () => {
  const vitalsPolicy = {...localPolicy}, vitalsRecord = {...record(vitalsPolicy), scope: 'vitals'}
  let overviewReads = 0
  const {page} = pageHarness('chat', {
    getMe: async () => ({id: 'demo-patient-001', profile: {allergies: '青霉素'}}),
    request: async url => {
      if (url === '/consents') return {items: [vitalsRecord], policies: {...policies(), vitals: vitalsPolicy}}
      if (url.startsWith('/health-management/overview')) {
        overviewReads++
        return {followups: [{due_at: '2026-10-25', done: false}], plans: [], entries: []}
      }
      throw new Error('unexpected request ' + url)
    }
  })
  page.onLoad({})
  await page.loadRecommendations()
  assert.equal(overviewReads, 1)
  assert.deepEqual(Array.from(page.data.recommendations, item => item.key), ['allergy', 'followup'])
  assert.equal(page.data.recoNote, '结合你的资料和近期记录')
  vitalsRecord.granted = false
  await page.loadRecommendations()
  assert.equal(overviewReads, 1)
  const fallbackKeys = Array.from(page.data.recommendations, item => item.key)
  assert.ok(fallbackKeys.includes('allergy'))
  assert.ok(!fallbackKeys.includes('followup'))
  assert.equal(page.data.recoNote, '根据你的资料')
})

test('仅消息接口等待45秒，其他请求10秒，超时仍返回失败', async () => {
  const requests = [], module = {exports: {}}
  const identityShim = {getToken: () => 'synthetic', clearSession() {}}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../miniprogram/services/api.js'), 'utf8'), {
    module,
    require: (name) => name.includes('config') ? {baseURL: 'http://127.0.0.1:8000/api/v1'} : identityShim,
    getApp: () => ({globalData: {token: 'synthetic'}}),
    wx: {request(options) { requests.push(options); options.success({statusCode: 200, data: {}}) }}
  })
  await module.exports.request('/conversations/demo/messages', 'POST', {text: '合成问题'})
  await module.exports.request('/consents')
  await module.exports.request('/emergencies', 'POST', {idempotency_key: 'synthetic-event'})
  assert.deepEqual(requests.map(item => item.timeout), [45000, 10000, 10000])
  const failures = {exports: {}}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../miniprogram/services/api.js'), 'utf8'), {
    module: failures,
    require: (name) => name.includes('config') ? {baseURL: 'http://127.0.0.1:8000/api/v1'} : identityShim,
    getApp: () => ({globalData: {token: null}}),
    wx: {request(options) { options.fail({errMsg: 'request:fail timeout'}) }}
  })
  await assert.rejects(failures.exports.request('/conversations/demo/messages', 'POST', {text: '合成问题'}), /请求超时/)
})
