const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const os = require('node:os'), net = require('node:net'), {spawn} = require('node:child_process')
const ROOT = path.resolve(__dirname, '..')
const view = require('../miniprogram/utils/health-view')
const event = (data = {}, value) => ({currentTarget: {dataset: data}, detail: {value}})
const overview = () => ({entries: [], entry_count: 0, plans: [], doses: [], followups: []})
const visit = () => ({
  start: '2026-10-14', end: '2026-10-20', days: 7, timezone: 'Asia/Shanghai', generated_at: '2026-10-20T04:00:00+00:00',
  entries: {total: 3, truncated: false, by_kind: {heart_rate: 1, spo2: 0, blood_pressure: 1, symptom: 1},
    latest: [
      {kind: 'heart_rate', value: 72, unit: 'bpm', source: 'manual', measured_at: '2026-10-20T08:00:00+08:00'},
      {kind: 'blood_pressure', value: 120, secondary_value: 80, unit: 'mmHg', source: 'report', measured_at: '2026-10-19T08:00:00+08:00'}
    ]},
  symptoms: {count: 1, items: [{title: '睡眠一般', measured_at: '2026-10-18T21:00:00+08:00'}]},
  medication: {plan_count: 1, plans_in_period: 1, total: 4, due: 3, taken: 1, skipped: 1, postponed: 0,
    unrecorded: 1, upcoming: 1, by_plan: [{name: '测试药', dose: '1 片', taken: 1, skipped: 1, unrecorded: 1, upcoming: 1}]},
  followups: {pending_count: 1, items: [{title: '心内科复查', due_at: '2026-10-22T09:00:00+08:00'}]}
})
function moduleFrom(file, requires, wx = {}) {
  const module = {exports: {}}
  vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'miniprogram', file), 'utf8'), {
    module, require: name => requires[name], wx, Set, Map, setTimeout, clearTimeout, console
  }, {filename: file})
  return module.exports
}
function setup(overrides = {}, wxOverrides = {}, givenIdentity) {
  const identity = givenIdentity || moduleFrom('services/identity.js', {}, {})
  if (!givenIdentity) identity.saveSession('test', {id: 'one'})
  let seq = 0, definition
  const health = {requestId: () => 'request-' + (++seq), access: async () => ({active: true, policy: {}, expiresAt: Date.now() + 60000}),
    overview: async () => overview(), ...overrides}
  const toasts = [], wx = {showToast: r => toasts.push(r), showModal: o => o.success({confirm: true}), ...wxOverrides}
  vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'miniprogram/pages/home/index.js'), 'utf8'), {
    Page: value => { definition = value }, require: name => ({'../../services/health': health, '../../services/identity': identity, '../../utils/health-view': view})[name],
    wx, getApp: () => ({globalData: {}}), setTimeout, clearTimeout, console
  })
  const page = {...definition, data: structuredClone(definition.data)}
  page.setData = patch => {
    for (const [key, value] of Object.entries(patch)) {
      const keys = key.split('.'); let target = page.data
      for (const k of keys.slice(0, -1)) target = target[k]
      target[keys.at(-1)] = value
    }
  }
  page.onLoad(); page._visible = true
  page.setData({today: view.parts().date, day: view.parts().date, active: true})
  page._expiresAt = Date.now() + 60000
  return {page, identity, health, toasts, wx}
}

test('trends preserve actual spacing, paired BP, gaps and measurement source', () => {
  const now = Date.parse('2026-10-18T12:00:00+08:00')
  const rows = [{id: 'a', kind: 'blood_pressure', source: 'manual', value: 120, secondary_value: 80, measured_at: '2026-10-13T08:00:00+08:00'},
    {id: 'b', kind: 'blood_pressure', source: 'report', value: 125, secondary_value: 82, measured_at: '2026-10-17T08:00:00+08:00'}]
  const chart = view.trend(rows, 'blood_pressure', 7, now)
  assert.equal(chart.count, 2); assert.equal(chart.points.length, 4)
  assert.ok(Number(chart.points[2].x) - Number(chart.points[0].x) > 50)
  assert.equal(view.entry(rows[0]).sourceLabel, '手动记录')
  assert.equal(view.entry(rows[1]).sourceLabel, '报告转录')
  assert.equal(view.trend(rows, 'spo2', 7, now).points.length, 0)
  assert.throws(() => view.iso('2026-02-30', '08:00'))
  assert.equal(view.parts('2026-10-17T17:00:00Z').date, '2026-10-18')
  assert.equal(view.dose({status: 'pending', scheduled_at: '2026-10-17T08:00:00+08:00'}, now).statusLabel, '未记录')
})

test('cancelled entry or deletion performs no writes; failure retains form and retry ID', async () => {
  const calls = []
  const {page, toasts} = setup({createEntry: async body => { calls.push(body); throw new Error('超时') }}, {showModal: o => o.success({confirm: false})})
  page.openEntry(event()); page.closeSheet(); assert.equal(calls.length, 0)
  page.openEntry(event()); page.input(event({field: 'value'}, '72'))
  await page.save(); await page.save()
  assert.equal(calls.length, 2); assert.equal(calls[0].request_id, calls[1].request_id)
  assert.equal(calls[0].source, 'manual'); assert.equal(page.data.sheet, 'entry')
  assert.match(page.data.formError, /超时/); assert.equal(toasts.length, 0)
  await page.remove(); assert.equal(calls.length, 2)
  page.onUnload()
})

test('BP requires both values and symptom requires narrative, never invented readings', async () => {
  const calls = [], {page} = setup({createEntry: async data => calls.push(data)})
  page.openEntry(event()); page.input(event({field: 'kind'}, '2')); page.input(event({field: 'value'}, '120'))
  await page.save(); assert.equal(calls.length, 0)
  page.input(event({field: 'secondary'}, '80')); await page.save()
  assert.equal(calls[0].secondary_value, 80)
  page.openEntry(event({symptom: 'yes'})); page.input(event({field: 'title'}, '感受')); await page.save()
  assert.equal(calls.length, 1)
  page.input(event({field: 'note'}, '合成自述')); await page.save()
  assert.equal(calls[1].value, null); assert.equal(calls[1].kind, 'symptom')
  page.onUnload()
})

test('plan times use wheel slots, cap at eight and reject duplicates', () => {
  const {page} = setup()
  page.openPlan(event())
  assert.equal(page.data.form.times.length, 0)
  for (let i = 0; i < 9; i++) page.addPlanTime()
  assert.equal(page.data.form.times.length, 8)
  assert.equal(new Set(page.data.form.times).size, 8)
  const before = page.data.form.times.slice()
  page.pickPlanTime(event({index: 0}, page.data.form.times[1]))
  assert.match(page.data.formError, /已经添加/)
  assert.deepEqual(page.data.form.times, before)
  page.removePlanTime(event({index: 0}))
  assert.equal(page.data.form.times.length, 7)
  page.setData({plans: [{id: 'p', revision: 2, times: ['20:00', '08:00'], name: '合成药品', dose: '1 片', start_date: '2026-10-20'}]})
  page.openPlan(event({id: 'p'}))
  assert.equal(page.data.form.times.join(','), '20:00,08:00')
  page.onUnload()
})

test('identity switch and hidden pages discard late private results', async () => {
  let resolve
  const {page, identity, health} = setup({overview: () => new Promise(r => { resolve = r })})
  const pending = page.refresh(); await new Promise(r => setImmediate(r))
  health.access = async () => ({active: false, policy: {}})
  identity.saveSession('two', {id: 'two'})
  resolve({...overview(), entries: [{id: 'secret', kind: 'heart_rate', value: 70, measured_at: new Date().toISOString()}]})
  await pending; assert.equal(page.data.entries.length, 0)
  page.setData({entries: [{id: 'private'}], sheet: 'entry', form: {value: 70}})
  page.onHide(); assert.equal(page.data.entries.length, 0); assert.equal(page.data.sheet, '')
  page.onUnload()
})

test('revocation on write clears data and never claims save success', async () => {
  const {page, toasts} = setup({createEntry: async () => { const e = new Error('revoked'); e.status = 403; throw e }})
  page.openEntry(event()); page.input(event({field: 'value'}, '70')); await page.save()
  assert.equal(page.data.active, false); assert.equal(page.data.sheet, '')
  assert.equal(page.data.entries.length, 0); assert.equal(toasts.length, 0)
  page.onUnload()
})

test('revoked access clears trend input so changing filters cannot resurrect private records', async () => {
  const {page, health} = setup()
  await page.refresh()
  page._raw.entries = [{id: 'private', kind: 'heart_rate', value: 72, measured_at: new Date().toISOString()}]
  health.access = async () => ({active: false, policy: {}})
  await page.refresh(); page.changeMetric(event({}, '0'))
  assert.equal(page._raw, null); assert.equal(page.data.entries.length, 0)
  assert.equal(page.data.chart.points.length, 0); page.onUnload()
})

test('historical doses require explicit actual time; calendar failure does not confirm medication', async () => {
  const calls = [], {page, toasts} = setup({recordDose: async p => calls.push(p)}, {addPhoneCalendar: o => o.fail()})
  const day = view.parts(Date.now() - 86400000).date
  page.setData({day, doses: [{key: 'slot', plan_id: 'p', plan_revision: 1, revision: 0, status: 'pending', name: '测试药', dose: '测试',
    clock: '08:00', scheduled_at: view.iso(day, '08:00'), note: ''}]})
  page.openDose(event({key: 'slot'})); await page.save(); assert.equal(calls.length, 0)
  page.input(event({field: 'time'}, '08:13')); await page.save()
  assert.equal(calls[0].actual_at, view.iso(day, '08:13'))
  const future = new Date(Date.now() + 3600000).toISOString()
  page.setData({doses: [{key: 'future', scheduled_at: future, status: 'pending'}]})
  page.calendar(event({key: 'future'}))
  assert.match(toasts.at(-1).title, /未添加/); assert.equal(calls.length, 1)
  assert.equal(page.data.doses[0].status, 'pending'); page.onUnload()
})

test('consent cancelled or identity changed while reviewing never posts', async () => {
  const identity = moduleFrom('services/identity.js', {}, {}); identity.saveSession('a', {})
  let requests = 0, choice
  const service = moduleFrom('services/health.js', {'./identity': identity, './api': {request: async () => { requests++ }}}, {showModal: o => { choice = o }})
  let pending = service.grant({notice: 'notice'}); choice.success({confirm: false}); assert.equal(await pending, false)
  pending = service.grant({notice: 'notice'}); identity.saveSession('b', {}); choice.success({confirm: true}); assert.equal(await pending, false)
  assert.equal(requests, 0)
})

test('record summary keeps only reviewed report fields and hides empty device widgets', () => {
  const summary = view.recordSummary({title: '合成检验单', record_date: '', fields: [
    {name: '项目一', result: '1.2', unit: 'mg/L'}, {name: '项目二', result: '阴性', unit: ''},
    {name: '项目三', result: '3', unit: 'g'}, {name: '项目四', result: '4', unit: 'g'},
    {name: '项目五', result: '5', unit: 'g'}]})
  assert.equal(summary.dateLabel, '日期未填')
  assert.equal(summary.fields.length, 4)
  assert.equal(view.recordSummary(null), null)
  const {page} = setup()
  page.render({entries: [], plans: [], doses: [], followups: [], entry_count: 0,
    latest_record: {title: '合成检验单', record_date: '2026-10-17', fields: [{name: '项目一', result: '1.2'}]}})
  assert.equal(page.data.latestRecord.title, '合成检验单')
  assert.equal(page.data.hasMeasurements, false)
})

test('proactive care alert prioritizes red symptoms then due follow-ups', () => {
  const now = Date.parse('2026-10-20T12:00:00+08:00')
  const urgent = view.careAlert({entries: [{kind: 'symptom', title: '胸痛', note: '比昨天重'}], followups: []}, now)
  assert.equal(urgent.level, 'urgent')
  assert.match(urgent.text, /立即.*医护/)
  const due = view.careAlert({entries: [], followups: [{title: '复诊', due_at: '2026-10-19T09:00:00+08:00', done: 0}]}, now)
  assert.equal(due.level, 'due')
  const soon = view.careAlert({entries: [], followups: [{title: '复诊', due_at: '2026-10-22T09:00:00+08:00', done: 0}]}, now)
  assert.equal(soon.level, 'soon')
  const later = view.careAlert({entries: [], followups: [{title: '复诊', due_at: '2026-11-20T09:00:00+08:00', done: 0}]}, now)
  assert.equal(later, null)
  const done = view.careAlert({entries: [], followups: [{title: '复诊', due_at: '2026-10-19T09:00:00+08:00', done: 1}]}, now)
  assert.equal(done, null)
})

test('health page renders the care alert and opens the medical agent with a prefilled question', () => {
  const opened = []
  const {page} = setup({}, {navigateTo: options => opened.push(options.url)})
  page.render({
    entries: [{id: 's1', kind: 'symptom', title: '胸闷', note: '休息后没有缓解', measured_at: '2026-10-20T08:00:00+08:00'}],
    plans: [], doses: [], followups: [], entry_count: 1
  })
  assert.equal(page.data.careAlert.level, 'urgent')
  page.openCareChat({currentTarget: {dataset: {kind: 'urgent'}}})
  assert.match(opened[0], /pages\/chat\/index.*domain=medical/)
  page.onHide()
  assert.equal(page.data.careAlert, null)
})

test('visit summary keeps unrecorded distinct from missed and never grades adherence', () => {
  const sections = view.summarySections(visit())
  const text = view.summaryText(sections)
  assert.match(text, /统计范围/)
  assert.match(text, /心率：72 bpm/)
  assert.match(text, /已服用 1 次/)
  assert.match(text, /未记录 1 次/)
  assert.match(text, /未记录.*不等于漏服/)
  assert.doesNotMatch(text, /依从|adherence/)
  assert.doesNotMatch(text, /NaN|undefined/)
  assert.ok(sections.find(section => section.title === '用药记录').items.some(line => line.includes('测试药')))
})

test('visit summary loads on demand, retries, copies and clears on identity change', async () => {
  const calls = [], copied = []
  const {page, identity} = setup({
    summary: async days => {
      calls.push(days)
      if (calls.length === 1) { const error = new Error('超时'); error.status = 504; throw error }
      return visit()
    }
  }, {setClipboardData: options => { copied.push(options.data); if (options.success) options.success() }})
  page.openSummary()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(page.data.sheet, 'summary')
  assert.match(page.data.visitError, /超时/)
  await page.loadSummary()
  assert.equal(page.data.visit.days, 7)
  assert.match(page.data.visitText, /测试药/)
  page.copySummary()
  assert.equal(copied[0], page.data.visitText)
  page.changeSummaryDays(event({days: 30}))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.at(-1), 30)
  assert.equal(page.data.visitDays, 30)
  identity.saveSession('other', {id: 'other'})
  assert.equal(page.data.visit, null)
  assert.equal(page.data.visitText, '')
  assert.equal(page.data.sheet, '')
  page.onUnload()
})

test('visit summary revocation clears old private text instead of showing stale data', async () => {
  const {page} = setup({summary: async () => {
    const error = new Error('revoked'); error.status = 403; throw error
  }})
  page.setData({visitText: '旧摘要', visit: visit(), visitSections: [], sheet: 'summary'})
  await page.loadSummary()
  assert.equal(page.data.active, false)
  assert.equal(page.data.visit, null)
  assert.equal(page.data.visitText, '')
  assert.equal(page.data.sheet, '')
  page.onUnload()
})

test('native home handlers execute health and medicine workflow against actual HTTP', {timeout: 30000}, async t => {
  const python = path.join(ROOT, 'backend/.venv/Scripts/python.exe')
  if (!fs.existsSync(python)) { t.skip('backend venv needed'); return }
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'm04-http-'))
  const port = await new Promise(resolve => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)) }) })
  const baseURL = `http://127.0.0.1:${port}/api/v1`
  const child = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', String(port), '--no-access-log'], {
    cwd: ROOT, windowsHide: true, env: {...process.env, YIFAZHILIAN_DB_PATH: path.join(directory, 'test.sqlite3'), YIFAZHILIAN_AI_PROVIDER: 'mock'}, stdio: 'ignore'})
  let page
  try {
    for (let i = 0; i < 100; i++) { try { if ((await fetch(baseURL + '/health')).ok) break } catch (_) {} await new Promise(r => setTimeout(r, 100)) }
    const identity = moduleFrom('services/identity.js', {}, {})
    const wx = {showModal: o => o.success({confirm: true}), request: options => {
      const abort = new AbortController()
      fetch(options.url, {method: options.method, headers: {...options.header, 'Content-Type': 'application/json'},
        body: options.data ? JSON.stringify(options.data) : undefined, signal: abort.signal})
        .then(async res => options.success({statusCode: res.status, data: await res.json()})).catch(e => options.fail({errMsg: e.message}))
      return {abort: () => abort.abort()}
    }}
    const api = moduleFrom('services/api.js', {'./identity': identity, '../config/index': {baseURL}}, wx)
    await api.login()
    const health = moduleFrom('services/health.js', {'./identity': identity, './api': api}, wx)
    page = setup(health, wx, identity).page
    await page.refresh(); assert.equal(page.data.active, false)
    await page.authorize(); assert.equal(page.data.active, true, page.data.error)
    page.openEntry(event()); page.input(event({field: 'value'}, '72')); await page.save()
    assert.equal(page.data.entries.length, 1, page.data.formError); assert.equal(page.data.latest[0].valueLabel, '72')
    page.openPlan(event())
    for (const [field, value] of Object.entries({name: '合成药品', dose: '测试单位'})) page.input(event({field}, value))
    page.addPlanTime(); page.addPlanTime()
    page.pickPlanTime(event({index: 0}, '08:00')); page.pickPlanTime(event({index: 1}, '20:00'))
    await page.save(); assert.equal(page.data.plans.length, 1, page.data.formError)
    assert.equal(page.data.doses.length, 2)
    page.openDose(event({key: page.data.doses[0].key})); await page.save()
    assert.equal(page.data.summary.taken, 1, page.data.formError)
    page.openPlan(event({id: page.data.plans[0].id})); page.input(event({field: 'status'}, '1')); await page.save()
    assert.equal(page.data.plans[0].status, 'paused'); assert.equal(page.data.summary.taken, 1)
    page.openFollowup(); page.input(event({field: 'title'}, '合成复查')); page.input(event({field: 'time'}, '09:00')); await page.save()
    assert.equal(page.data.followups.length, 1, page.data.formError)
    await page.toggleFollowup(event({id: page.data.followups[0].id})); assert.equal(page.data.followups[0].done, 1)
    page.setData({sheet: 'summary'})
    await page.loadSummary()
    assert.equal(page.data.visit.medication.taken, 1, page.data.visitError)
    assert.match(page.data.visitText, /合成药品/)
    await api.request('/consents/vitals', 'DELETE'); await page.refresh()
    assert.equal(page.data.active, false); assert.equal(page.data.entries.length, 0)
    await page.authorize(); assert.equal(page.data.entries.length, 1)
    await api.login('demo-patient-002'); await page.refresh()
    assert.equal(page.data.entries.length, 0); assert.equal(page.data.active, false)
  } finally {
    if (page) page.onUnload()
    const stopped = new Promise(r => child.once('exit', r)); child.kill(); await stopped
    // This directory is the exact unique path returned by mkdtemp above.
    if (!path.resolve(directory).startsWith(path.resolve(os.tmpdir()) + path.sep)) throw new Error('Unexpected cleanup directory')
    fs.rmSync(directory, {recursive: true, force: true})
  }
})
