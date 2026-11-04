const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const os = require('node:os')
const net = require('node:net')
const {spawn} = require('node:child_process')
const ROOT = path.resolve(__dirname, '..')
const tick = () => new Promise(resolve => setImmediate(resolve))
function moduleFrom(file, requires, wx = {}) {
  const module = {exports: {}}
  vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'miniprogram', file), 'utf8'), {
    module, require: name => { if (!(name in requires)) throw new Error(name); return requires[name] },
    wx, Set, Map, setTimeout, clearTimeout, console
  }, {filename: file})
  return module.exports
}
function makeIdentity() { return moduleFrom('services/identity.js', {}, {setStorageSync() {}, removeStorageSync() {}}) }
function makePage(name, identity, records, wx = {}, api = {}) {
  let definition
  const guard = moduleFrom('utils/navigation-page.js', {'../services/identity': identity})
  vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'miniprogram/pages', name, 'index.js'), 'utf8'), {
    Page: value => { definition = value }, require: key => ({'../../services/records': records, '../../services/api': api, '../../services/identity': identity, '../../utils/navigation-page': guard})[key],
    wx: {showModal: options => options.success({confirm: true}), showToast() {}, pageScrollTo() {}, ...wx},
    setTimeout, clearTimeout, console
  }, {filename: name})
  const page = {...definition, data: structuredClone(definition.data)}
  page.setData = (patch, callback) => {
    for (const [key, value] of Object.entries(patch)) {
      const parts = key.replace(/\[(\d+)\]/g, '.$1').split('.')
      let target = page.data
      for (const part of parts.slice(0, -1)) target = target[part]
      target[parts.at(-1)] = value
    }
    if (callback) callback()
  }
  return page
}
const event = (data, value) => ({currentTarget: {dataset: data}, detail: {value}})
const document = () => ({id: 'doc1', status: 'review', revision: 3, archived_version: 0, versions: [], jobs: [],
  draft: {title: '合成报告', record_type: '检验单', record_date: '2026-10-17', institution: '', visit: '', metadata_confirmed: false,
    fields: [{id: 'ocr-1', name: '合成项目', result: '6.30', unit: 'mg/L', reference: '0-8', confirmed: false,
      confidence: .72, original: {name: '合成项目', result: '6.30', unit: 'mg/L', reference: '0-8'}, box: [1,2,3,4]}]}})
function setup(overrides = {}, wx = {}) {
  const identity = makeIdentity(); identity.saveSession('token', {id: 'patient'})
  let count = 0
  const records = {clearTemp() {}, removeTemp() {}, statusLabel: value => value, requestId: () => 'request-' + (++count), ...overrides}
  const page = makePage('record-review', identity, records, wx)
  page.onLoad({id: 'doc1'}); page.setData({active: true}); page.setDocument(document())
  return {page, identity, records}
}

test('OCR fields require individual review; editing resets confirmation and original stays visible', () => {
  const {page} = setup()
  assert.equal(page.data.form.fields[0].lowConfidence, true)
  page.confirmField(event({index: 0}, ['yes']))
  assert.equal(page.data.confirmedCount, 1)
  page.inputField(event({index: 0, key: 'result'}, '6.80'))
  assert.equal(page.data.confirmedCount, 0)
  assert.equal(page.data.form.fields[0].original.result, '6.30')
  page.metadataChange(event({}, ['yes'])); page.inputMeta(event({key: 'institution'}, '测试机构'))
  assert.equal(page.data.form.metadata_confirmed, false)
  page.onUnload()
})

test('cancel archive never posts, failed archive remains editable, repeated attempt reuses request ID', async () => {
  const calls = []; let confirm = false
  const {page} = setup({confirm: async (id, payload) => { calls.push(payload); throw new Error('超时') }}, {
    showModal: options => options.success({confirm})
  })
  page.confirmField(event({index: 0}, ['yes'])); page.metadataChange(event({}, ['yes']))
  await page.confirm(); assert.equal(calls.length, 0)
  confirm = true
  await page.confirm(); await page.confirm()
  assert.equal(calls.length, 2); assert.equal(calls[0].request_id, calls[1].request_id)
  assert.equal(page.data.doc.archived_version, 0); assert.equal(page.data.readOnly, false)
  assert.match(page.data.error, /超时/)
  page.onUnload()
})

test('text-only OCR explains missing projects and navigates to retry without archiving', async () => {
  const scrolls = []; let posts = 0
  const {page} = setup({confirm: async () => { posts++ }}, {pageScrollTo: options => scrolls.push(options)})
  page.selectComponent = () => ({data: {statusHeight: 54, barHeight: 44}})
  const doc = document(); doc.draft.fields = []
  page.setDocument(doc); page.setData({rawVisible: true})
  assert.equal(page.data.archiveReady, false)
  assert.match(page.data.archiveIssues[0].text, /尚无.*项目/)
  await page.confirm()
  assert.equal(posts, 0)
  assert.equal(scrolls.at(-1).selector, '#review-items')
  assert.equal(scrolls.at(-1).offsetTop, -110)
  assert.equal(page.data.rawVisible, false)
  assert.equal(page.data.form.metadata_confirmed, false)
  page.addField()
  assert.match(page.data.archiveIssues[0].text, /第 1 项缺少/)
  page.onUnload()
})

test('archive guidance locates missing fields, metadata and correction reason and resets after editing', async () => {
  const scrolls = []; let posts = 0
  const {page} = setup({confirm: async () => { posts++ }}, {pageScrollTo: options => scrolls.push(options.selector)})
  await page.confirm()
  assert.equal(scrolls.at(-1), '#review-field-0')
  page.confirmField(event({index: 0}, ['yes']))
  await page.confirm()
  assert.equal(scrolls.at(-1), '#metadata-confirmation')
  page.metadataChange(event({}, ['yes']))
  assert.equal(page.data.archiveReady, true)
  page.inputField(event({index: 0, key: 'result'}, ' '))
  page.confirmField(event({index: 0}, ['yes']))
  assert.equal(page.data.archiveReady, false)
  assert.match(page.data.archiveIssues[0].text, /缺少/)
  await page.confirm(); assert.equal(posts, 0)
  const doc = document(); doc.status = 'archived'; doc.archived_version = 1
  page.setDocument(doc); page.edit()
  page.confirmField(event({index: 0}, ['yes'])); page.metadataChange(event({}, ['yes']))
  await page.confirm()
  assert.equal(scrolls.at(-1), '#correction-reason')
  page.inputReason(event({}, '对照原图更正'))
  assert.equal(page.data.archiveReady, true)
  page.removeField(event({index: 0})); assert.equal(page.data.archiveReady, false)
  page.onUnload()
})

test('archive guidance rejects empty title and invalid calendar dates before posting', async () => {
  let posts = 0
  const {page} = setup({confirm: async () => { posts++ }})
  page.confirmField(event({index: 0}, ['yes']))
  for (const value of ['2026-02-30', '2026-13-01', '2026-2-01', '0000-01-01']) {
    page.inputMeta(event({key: 'record_date'}, value)); page.metadataChange(event({}, ['yes']))
    assert.match(page.data.archiveIssues[0].text, /有效的报告日期/)
    await page.confirm()
  }
  page.inputMeta(event({key: 'record_date'}, '2024-02-29')); page.metadataChange(event({}, ['yes']))
  assert.equal(page.data.archiveReady, true)
  page.inputMeta(event({key: 'title'}, ' ')); page.metadataChange(event({}, ['yes']))
  assert.match(page.data.archiveIssues[0].text, /标题/)
  await page.confirm(); assert.equal(posts, 0)
  page.onUnload()
})

test('camera cancel and permission rejection never claim upload success', async () => {
  let fail = {errMsg: 'chooseMedia:fail cancel'}
  const {page} = setup({}, {chooseMedia: options => options.fail(fail)})
  await page.choosePhoto(); assert.equal(page.data.localPath, ''); assert.equal(page.data.error, '')
  fail = {errMsg: 'permission denied'}
  await page.choosePhoto(); assert.match(page.data.error, /权限/)
  page.onUnload()
})

test('entering from camera never opens a picker automatically; album and camera buttons select their own source', async () => {
  const identity = makeIdentity(); identity.saveSession('token', {id: 'patient'})
  const calls = []
  const records = {access: async () => ({active: true, expiresAt: Date.now() + 60000}), clearTemp() {}}
  const page = makePage('record-review', identity, records, {chooseMedia: options => {
    calls.push(options)
    options.success({tempFiles: [{tempFilePath: options.sourceType[0] + '.jpg', size: 100}]})
  }})
  page.onLoad({source: 'camera'}); await page.onShow()
  assert.equal(calls.length, 0)
  await page.choosePhoto(event({source: 'album'}))
  assert.deepEqual(Array.from(calls[0].sourceType), ['album'])
  assert.equal(page.data.localPath, 'album.jpg')
  page.privacyChange(event({}, ['yes']))
  await page.choosePhoto(event({source: 'camera'}))
  assert.deepEqual(Array.from(calls[1].sourceType), ['camera'])
  assert.equal(page.data.localPath, 'camera.jpg')
  assert.equal(page.data.privacyConfirmed, false)
  assert.equal(page.data.choosing, false)
  page.onUnload()
})

test('old WeChat image picker is normalized and preserves explicit album source', async () => {
  const calls = []
  const {page} = setup({}, {chooseImage: options => {
    calls.push(options)
    options.success({tempFilePaths: ['legacy.jpg'], tempFiles: [{path: 'legacy.jpg', size: 100}]})
  }})
  await page.choosePhoto(event({source: 'album'}))
  assert.deepEqual(Array.from(calls[0].sourceType), ['album'])
  assert.equal(page.data.localPath, 'legacy.jpg')
  page.onUnload()
})

test('unsupported media API falls back once; refusal and privacy errors never trigger an alternate picker', async () => {
  let error = 'chooseMedia:fail not supported', legacyCalls = 0
  const {page} = setup({}, {
    chooseMedia: options => options.fail({errMsg: error}),
    chooseImage: options => { legacyCalls++; options.success({tempFilePaths: ['legacy.jpg']}) }
  })
  await page.choosePhoto(event({source: 'album'})); assert.equal(legacyCalls, 1)
  error = 'chooseMedia:fail auth deny'
  await page.choosePhoto(event({source: 'album'}))
  assert.equal(legacyCalls, 1); assert.match(page.data.error, /相册权限未开启/)
  error = 'chooseMedia:fail privacy permission is not authorized'
  await page.choosePhoto(event({source: 'album'}))
  assert.equal(legacyCalls, 1); assert.match(page.data.error, /微信隐私授权/)
  page.onUnload()
})

test('cancelled replacement retains the selected image and never reports a successful upload', async () => {
  const {page} = setup({}, {chooseMedia: options => options.fail({errMsg: 'chooseMedia:fail cancel'})})
  page.setData({localPath: 'previous.jpg', privacyConfirmed: true, notice: '照片尚未上传'})
  await page.choosePhoto(event({source: 'album'}))
  assert.equal(page.data.localPath, 'previous.jpg'); assert.equal(page.data.privacyConfirmed, true)
  assert.equal(page.data.error, ''); assert.match(page.data.notice, /尚未上传/)
  page.onUnload()
})

test('only one picker can open, upload waits for selection, and identity change discards late photos', async () => {
  let finish, calls = 0, uploads = 0
  const {page, identity} = setup({upload: () => { uploads++; throw new Error('must not upload') }}, {
    chooseMedia: options => { calls++; finish = options.success }
  })
  page.setData({localPath: 'previous.jpg', privacyConfirmed: true})
  const pending = page.choosePhoto(event({source: 'album'}))
  await page.choosePhoto(event({source: 'camera'})); await page.upload()
  assert.equal(calls, 1); assert.equal(uploads, 0); assert.equal(page.data.choosing, true)
  identity.saveSession('new', {id: 'new'})
  finish({tempFiles: [{tempFilePath: 'private.jpg', size: 100}]}); await pending
  assert.equal(page.data.localPath, ''); assert.equal(page.data.choosing, false)
  page.onUnload()
})

test('closed page ignores late photo selection and missing file paths cannot be uploaded', async () => {
  let finish
  const {page} = setup({}, {chooseMedia: options => { finish = options.success }})
  const pending = page.choosePhoto(event({source: 'album'}))
  page.onUnload(); finish({tempFiles: [{tempFilePath: 'late.jpg', size: 100}]}); await pending
  assert.equal(page.data.localPath, '')
  const missing = setup({}, {chooseMedia: options => options.success({tempFiles: []})}).page
  await missing.choosePhoto(event({source: 'album'}))
  assert.equal(missing.data.localPath, ''); assert.match(missing.data.error, /未取得照片/)
  missing.onUnload()
})

test('busy OCR prevents editing, late recognition is ignored after identity switch', async () => {
  let finish
  const {page, identity} = setup({recognize: () => new Promise(resolve => { finish = resolve })})
  const pending = page.recognize(); await tick()
  page.inputField(event({index: 0, key: 'result'}, '999'))
  assert.equal(page.data.form.fields[0].result, '6.30')
  identity.saveSession('another', {id: 'other'})
  finish(document()); await pending
  assert.equal(page.data.doc, null); assert.equal(page.data.image, '')
  page.onUnload()
})

test('transport aborts every private channel and deletes late downloaded photos after switch', async () => {
  const identity = makeIdentity(); identity.saveSession('old', {id: 'old'})
  const calls = [], removed = []
  const wx = {getFileSystemManager: () => ({unlink: options => removed.push(options.filePath)})}
  for (const kind of ['request', 'uploadFile', 'downloadFile']) wx[kind] = options => {
    const call = {options, kind}; calls.push(call)
    return {abort() { call.aborted = true }}
  }
  const records = moduleFrom('services/records.js', {'./identity': identity, '../config/index': {baseURL: 'http://local'}, './image_upload': {enabled: () => false, toDataUrl: async () => ''}}, wx)
  const promises = [records.list(), records.upload('file'), records.image('id')].map(p => assert.rejects(p, /身份已切换/))
  identity.saveSession('new', {id: 'new'})
  await Promise.all(promises)
  assert.ok(calls.every(c => c.aborted))
  calls[2].options.success({statusCode: 200, tempFilePath: 'private-photo'})
  calls[0].options.success({statusCode: 401, data: {}})
  assert.ok(removed.includes('private-photo')); assert.equal(identity.getToken(), 'new')
})

test('revocation clears rendered data and download cache rather than keeping old result', async () => {
  let cleared = 0
  const {page} = setup({get: async () => { const e = new Error('授权已撤回'); e.status = 403; throw e }, clearTemp() { cleared++ }})
  page.setData({image: 'sensitive-photo'})
  await page.reload()
  assert.equal(page.data.image, ''); assert.equal(page.data.doc, null); assert.equal(page.data.active, false)
  assert.ok(cleared > 0); page.onUnload()
})

test('historical snapshot is read-only and returning reloads latest version', async () => {
  const doc = document(); doc.status = 'archived'; doc.archived_version = 2
  const {page} = setup({version: async () => ({snapshot: {version: 1, draft: document().draft}, changes: [], reason: '首次归档'}),
    get: async () => doc, image: async () => 'original'})
  page.setDocument(doc)
  await page.openVersion(event({version: 1}))
  page.inputField(event({index: 0, key: 'result'}, '999')); page.edit()
  assert.equal(page.data.form.fields[0].result, '6.30'); assert.equal(page.data.readOnly, true)
  await page.reload(); assert.equal(page.data.version, null); assert.equal(page.data.doc.archived_version, 2)
  page.onUnload()
})

test('merged records page keeps medical notes beside documents', async () => {
  const identity = makeIdentity(); identity.saveSession('token', {id: 'patient'})
  let notes = [], created = null
  const api = {
    listRecords: async () => ({items: notes}),
    createRecord: async data => { created = data; notes = [{id: 'note-2', ...data}]; return notes[0] }
  }
  const records = {
    clearTemp() {}, statusLabel: value => value,
    access: async () => ({active: true, policy: {}, expiresAt: Date.now() + 60000}),
    list: async () => ({items: []}),
    checklist: async scenario => ({scenario, scenario_label: scenario === 'outpatient' ? '门诊病历' : '住院病历',
      complete_count: 2, total_required: 5, missing_count: 3, items: [], disclaimer: '资料类型完整度'})
  }
  const modals = [{confirm: true, content: '复诊记录'}, {confirm: true, content: '问医生血压'}]
  const page = makePage('records', identity, records, {showModal: options => options.success(modals.shift() || {confirm: false})}, api)
  page.onLoad()
  await page.reload()
  assert.equal(page.data.active, true)
  assert.equal(page.data.notes.length, 0)
  assert.equal(page.data.checklist.complete_count, 2)
  assert.equal(page.data.checklistScenario, 'inpatient')
  page.changeChecklistScenario({currentTarget: {dataset: {scenario: 'outpatient'}}})
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(page.data.checklist.scenario, 'outpatient')
  assert.equal(page.data.checklist.scenario_label, '门诊病历')
  await page.addNote()
  assert.equal(created.title, '复诊记录')
  assert.equal(created.summary, '问医生血压')
  assert.equal(page.data.notes.length, 1)
  page.toggleNote({currentTarget: {dataset: {id: 'note-2'}}})
  assert.equal(page.data.expandedNote, 'note-2')
  page.onUnload()
})

test('native page handlers run actual HTTP upload → CPU OCR → correction → archive → history → regrant', {timeout: 120000}, async t => {
  const python = path.join(ROOT, 'backend/.venv/Scripts/python.exe')
  if (!fs.existsSync(python) || !fs.existsSync(path.join(ROOT, 'backend/.ocr-venv/Scripts/python.exe'))) { t.skip('local backend and OCR environments required'); return }
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'm03-http-'))
  const port = await new Promise(resolve => { const server = net.createServer(); server.listen(0, '127.0.0.1', () => { const p = server.address().port; server.close(() => resolve(p)) }) })
  const api = `http://127.0.0.1:${port}/api/v1`
  const child = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', String(port), '--no-access-log'], {
    cwd: ROOT, windowsHide: true, env: {...process.env, YIFAZHILIAN_DB_PATH: path.join(directory, 'test.sqlite3'), YIFAZHILIAN_AI_PROVIDER: 'mock', YIFAZHILIAN_WECHAT_APPID: '', YIFAZHILIAN_WECHAT_SECRET: ''}, stdio: 'ignore'
  })
  const identity = makeIdentity()
  let page
  try {
    for (let i = 0; i < 100; i++) {
      try { if ((await fetch(api + '/health')).ok) break } catch (_) {}
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    const login = await (await fetch(api + '/auth/demo-login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({demo_alias: 'demo-patient-001', role: 'patient'})})).json()
    identity.saveSession(login.access_token, login.user)
    const auth = {Authorization: 'Bearer ' + login.access_token, 'Content-Type': 'application/json'}
    await fetch(api + '/consents', {method: 'POST', headers: auth, body: JSON.stringify({scope: 'records_read'})})
    const fixture = path.join(ROOT, 'backend/fixtures/records-m03/synthetic-lab.png')
    const wx = {getFileSystemManager: () => ({unlink: ({filePath}) => { if (filePath.startsWith(directory)) fs.rmSync(filePath, {force: true}) }}),
      showModal: options => options.success({confirm: true}), chooseMedia: options => options.success({tempFiles: [{tempFilePath: fixture, size: fs.statSync(fixture).size}]}), pageScrollTo() {}}
    let downloads = 0
    for (const kind of ['request', 'uploadFile', 'downloadFile']) wx[kind] = options => {
      const controller = new AbortController()
      ;(async () => {
        const init = {headers: options.header, signal: controller.signal, method: options.method || 'GET'}
        if (kind === 'uploadFile') { const form = new FormData(); form.append('file', new Blob([fs.readFileSync(options.filePath)], {type: 'image/png'}), 'synthetic.png'); init.method = 'POST'; init.body = form }
        else if (options.data) { init.body = JSON.stringify(options.data); init.headers = {...init.headers, 'Content-Type': 'application/json'} }
        const response = await fetch(options.url, init)
        if (kind === 'downloadFile') { const tempFilePath = path.join(directory, 'photo-' + (++downloads) + '.png'); fs.writeFileSync(tempFilePath, Buffer.from(await response.arrayBuffer())); options.success({statusCode: response.status, tempFilePath}) }
        else { const text = await response.text(); options.success({statusCode: response.status, data: kind === 'uploadFile' ? text : JSON.parse(text)}) }
      })().catch(e => options.fail({errMsg: e.message}))
      return {abort: () => controller.abort()}
    }
    const records = moduleFrom('services/records.js', {'./identity': identity, '../config/index': {baseURL: api}, './image_upload': {enabled: () => false, toDataUrl: async () => ''}}, wx)
    page = makePage('record-review', identity, records, wx)
    page.onLoad({source: 'album'}); await page.onShow()
    assert.equal(page.data.localPath, '')
    await page.choosePhoto(event({source: 'album'}))
    page.privacyChange(event({}, ['yes'])); await page.upload()
    assert.equal(page.data.doc.status, 'uploaded', page.data.error)
    const id = page.data.doc.id
    await page.recognize()
    assert.equal(page.data.doc.status, 'review', page.data.error)
    assert.equal(page.data.form.fields.length, 5)
    // Real fixture exposes a high-confidence unit OCR error: manual correction must persist.
    page.inputField(event({index: 0, key: 'unit'}, '10^9/L'))
    page.inputField(event({index: 0, key: 'result'}, '6.80'))
    for (let i = 0; i < 5; i++) page.confirmField(event({index: i}, ['yes']))
    page.metadataChange(event({}, ['yes']))
    await page.confirm()
    assert.equal(page.data.doc.archived_version, 1, page.data.error)
    assert.equal(page.data.form.fields[0].original.result, '6.30')
    await page.locate(event({index: 0})); assert.ok(page.data.crop)
    page.edit(); page.inputField(event({index: 0, key: 'result'}, '6.90'))
    page.confirmField(event({index: 0}, ['yes'])); page.metadataChange(event({}, ['yes'])); page.inputReason(event({}, '合成纠错测试'))
    await page.confirm(); assert.equal(page.data.doc.archived_version, 2, page.data.error)
    await page.openVersion(event({version: 1})); assert.equal(page.data.form.fields[0].result, '6.80')
    await page.reload(); assert.equal(page.data.form.fields[0].result, '6.90')
    await fetch(api + '/consents/records_read', {method: 'DELETE', headers: auth})
    await page.reload(); assert.equal(page.data.doc, null); assert.equal(page.data.image, '')
    await fetch(api + '/consents', {method: 'POST', headers: auth, body: JSON.stringify({scope: 'records_read'})})
    await page.onShow(); assert.equal(page.data.doc.id, id); assert.equal(page.data.doc.archived_version, 2)
  } finally {
    if (page) page.onUnload()
    const stopped = new Promise(resolve => child.once('exit', resolve)); child.kill(); await stopped
    fs.rmSync(directory, {recursive: true, force: true})
  }
})
