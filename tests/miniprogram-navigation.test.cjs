const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const {spawn} = require('node:child_process')
const os = require('node:os')
const net = require('node:net')
const ROOT = path.resolve(__dirname, '..')
const capabilities = require('../miniprogram/utils/capabilities')
// 环境限制，不是功能缺陷：受限沙箱不允许 Node 创建子进程（EPERM）。
// 只有这一条依赖真实子进程的用例会因此跳过；完整权限下必须实际跑通，
// 跳过时要在交付说明里写明“该环境未验证此路径”，不能当成通过。
const SANDBOX_EPERM_SKIP = '环境限制（非功能缺陷）：当前沙箱禁止 Node 创建子进程（EPERM），'
  + 'M11 真实 HTTP 用例需完整权限；跳过不等于通过，交付时须注明该路径未在本环境验证'
const tick = () => new Promise(resolve => setImmediate(resolve))

function moduleFrom(file, requires, wx = {}) {
  const exports = {exports: {}}
  vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'miniprogram', file), 'utf8'), {
    module: exports, require: name => {
      if (!(name in requires)) throw new Error('Unexpected require: ' + name)
      return requires[name]
    }, wx, Set, Map, console, setTimeout, clearTimeout
  }, {filename: file})
  return exports.exports
}
function makeIdentity() {
  return moduleFrom('services/identity.js', {}, {setStorageSync() {}, removeStorageSync() {}})
}
function makePage(file, {nav, identity, api = {}, wx = {}, timers = {}}) {
  let definition
  const guard = moduleFrom('utils/navigation-page.js', {'../services/identity': identity})
  vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'miniprogram/pages', file, 'index.js'), 'utf8'), {
    Page: value => { definition = value }, require: name => {
      if (name === '../../services/navigation') return nav
      if (name === '../../services/identity') return identity
      if (name === '../../services/api') return {...api, identity}
      if (name === '../../utils/navigation-page') return guard
      // 新增的纯函数模块：用真实实现，避免为它单独造桩。
      if (name === '../../utils/capabilities') return capabilities
      throw new Error(name)
    }, wx: {showToast() {}, ...wx}, setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {}, ...timers
  }, {filename: file + '/index.js'})
  const page = {...definition, data: structuredClone(definition.data)}
  page.setData = patch => {
    for (const [key, value] of Object.entries(patch)) {
      const parts = key.replace(/\[(\d+)\]/g, '.$1').split('.')
      let target = page.data
      for (const part of parts.slice(0, -1)) target = target[part]
      target[parts.at(-1)] = value
    }
  }
  return page
}
const evt = data => ({currentTarget: {dataset: data}})
const sub = () => ({id: 'sub-1', collector_id: 'collector', revision: 2, title: '大厅到检验科',
  status: 'draft', nodes: [{node_key: 'start', kind: 'start', position: 0}, {node_key: 'end', kind: 'end', position: 1}], media: []})

test('JSON, upload and photo download are aborted on identity switch; stale 401 cannot log out new user', async () => {
  const identity = makeIdentity()
  identity.saveSession('old-token', {id: 'old'})
  const calls = []
  const wx = {}
  for (const kind of ['request', 'uploadFile', 'downloadFile']) wx[kind] = options => {
    const call = {kind, options, aborted: false}
    calls.push(call)
    return {abort() { call.aborted = true }}
  }
  const nav = moduleFrom('services/navigation.js', {'./identity': identity, '../config/index': {baseURL: 'http://local/api/v1'}}, wx)
  const pending = [nav.tasks(), nav.uploadMedia('s', {nodeKey: 'start', revision: 1, filePath: 'p'}),
    nav.fetchMediaTempUrl('m')].map(p => assert.rejects(p, /身份已切换/))
  identity.saveSession('new-token', {id: 'new'})
  await Promise.all(pending)
  assert.ok(calls.every(c => c.aborted && c.options.header.Authorization === 'Bearer old-token'))
  calls.forEach(c => c.options.success({statusCode: 401, data: c.kind === 'uploadFile' ? '{}' : {}}))
  assert.equal(identity.getToken(), 'new-token')
})

test('workbench claim creates/resumes a draft and navigates; failed creation remains retryable', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'collector'})
  const calls = [], urls = []
  let fail = true
  const nav = {claimTask: async id => { calls.push(['claim', id]) }, createSubmission: async body => {
    calls.push(['create', body]); if (fail) throw new Error('断网'); return sub()
  }}
  const page = makePage('navigation-workbench', {nav, identity, wx: {navigateTo: o => urls.push(o.url)}})
  page.onLoad()
  page.setData({tasks: [{id: 'task-1', title: '路线'}]})
  await page.claim(evt({id: 'task-1'}))
  assert.match(page.data.error, /断网/)
  assert.equal(page.data.busy, false)
  fail = false
  await page.claim(evt({id: 'task-1'}))
  assert.equal(calls[1][1].request_id, calls[3][1].request_id)
  assert.equal(urls[0], '/pages/route-capture/index?id=sub-1')
  page.onUnload()
})

test('shared API cancels old requests so old 401 cannot clear the new navigation identity', async () => {
  const identity = makeIdentity(); identity.saveSession('old', {id: 'old'})
  let options, aborted = false
  const api = moduleFrom('services/api.js', {'./identity': identity, '../config/index': {baseURL: 'http://local'}}, {
    request(o) { options = o; return {abort() { aborted = true }} }
  })
  const pending = assert.rejects(api.request('/consents'), /身份已切换/)
  identity.saveSession('new', {id: 'reviewer'})
  await pending
  options.success({statusCode: 401, data: {detail: '旧令牌失效'}})
  assert.equal(identity.getToken(), 'new'); assert.ok(aborted)
})

test('rapid identity taps cannot race two demo logins while logout clears the page', async () => {
  const identity = makeIdentity(); identity.saveSession('old', {id: 'old'})
  let resolveLogin, count = 0
  const page = makePage('navigation-workbench', {identity, nav: {}, api: {
    logout: async () => identity.clearSession(),
    login: async () => { count++; await new Promise(resolve => { resolveLogin = resolve }) }
  }})
  page.onLoad(); page.reload = async () => {}
  const first = page.switchDemo(evt({id: 'demo-volunteer-001'}))
  await tick()
  await page.switchDemo(evt({id: 'demo-reviewer-001'}))
  assert.equal(count, 1)
  resolveLogin(); await first
  page.onUnload()
})

test('account choice does not log in until confirmed; patient enters navigation directly', async () => {
  const identity = makeIdentity(), logins = [], urls = []
  const nav = {me: async () => ({user: identity.getUser(), permissions: {browse: true, collect: false, review: false}}),
    routes: async () => ({items: [{id: 'published'}]})}
  const api = {logout: async () => identity.clearSession(), login: async (id, role) => {
    logins.push([id, role]); identity.saveSession('t', {id})
  }}
  const page = makePage('navigation-workbench', {identity, nav, api, wx: {switchTab: o => urls.push(o.url)}})
  page.onLoad(); await page.onShow()
  assert.equal(page.data.selectedAccountId, 'm11-test-patient')
  page.selectAccount({detail: {value: 'm11-test-reviewer'}})
  assert.equal(logins.length, 0); assert.equal(page.data.selectedAction, '进入审核工作台')
  page.selectAccount({detail: {value: 'm11-test-patient'}})
  await page.enterSelectedAccount()
  assert.deepEqual(logins, [['m11-test-patient', 'patient']])
  assert.equal(urls[0], '/pages/navigation/index'); assert.equal(page.data.pickerOpen, false)
  page.openAccountPicker(); assert.equal(page.data.pickerOpen, true)
  page.cancelSwitch(); assert.equal(page.data.pickerOpen, false); assert.equal(logins.length, 1)
  page.onUnload()
})

test('failed test login stays in the selector and can be retried without navigating', async () => {
  const identity = makeIdentity(), urls = []
  const page = makePage('navigation-workbench', {identity, nav: {}, api: {
    logout: async () => identity.clearSession(), login: async () => { throw new Error('连接失败') }
  }, wx: {switchTab: o => urls.push(o.url)}})
  page.onLoad(); await page.enterSelectedAccount()
  assert.equal(page.data.pickerOpen, true); assert.equal(page.data.switching, false)
  assert.equal(page.data.busy, false); assert.match(page.data.error, /连接失败/); assert.equal(urls.length, 0)
  page.onUnload()
})

test('reviewer selection enters own workbench and legacy account selection remains visible when switching', async () => {
  const identity = makeIdentity(), urls = []
  const nav = {me: async () => ({user: identity.getUser(), permissions: {browse: true, review: true, collect: false}}),
    routes: async () => ({items: []}), listSubmissions: async () => ({items: [{id: 'pending'}]})}
  const page = makePage('navigation-workbench', {identity, nav, api: {
    logout: async () => identity.clearSession(), login: async id => identity.saveSession('t', {id})
  }, wx: {switchTab: o => urls.push(o.url)}})
  page.onLoad(); page.selectAccount({detail: {value: 'm11-test-reviewer'}}); await page.enterSelectedAccount()
  assert.equal(page.data.roleLabel, '审核员'); assert.equal(page.data.pickerOpen, false)
  assert.equal(page.data.queue[0].id, 'pending'); assert.equal(urls.length, 0)
  identity.saveSession('legacy', {id: 'demo-reviewer-001'}); await page.reload(); page.openAccountPicker()
  assert.equal(page.data.selectedAccountId, 'demo-reviewer-001'); assert.equal(page.data.legacyExpanded, true)
  page.onUnload()
})

test('dual role workbench keeps own drafts and independent review queue separate', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'collector'})
  const scopes = []
  const nav = {me: async () => ({user: {id: 'collector'}, permissions: {collect: true, review: true}}),
    routes: async () => ({items: []}), tasks: async () => ({items: []}),
    listSubmissions: async scope => { scopes.push(scope); return {items: [{id: scope}]} }}
  const page = makePage('navigation-workbench', {nav, identity})
  page.onLoad(); await page.onShow()
  assert.deepEqual(scopes.sort(), ['mine', 'review'])
  assert.equal(page.data.mine[0].id, 'mine'); assert.equal(page.data.queue[0].id, 'review')
  page.onUnload()
})

test('capture saves new nodes before upload, retains failed preview and freezes submitted content', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'collector'})
  const calls = []; let fail = true
  const nav = {me: async () => ({user: {id: 'collector'}, permissions: {collect: true}}),
    getSubmission: async () => sub(),
    updateSubmission: async (id, body) => { calls.push('save'); return {...sub(), nodes: body.nodes, revision: body.revision + 1} },
    uploadMedia: async (id, body) => { calls.push('upload'); assert.ok(body.revision > 2); if (fail) throw new Error('上传失败'); return {id: 'photo-1', submission_revision: body.revision + 1} }}
  const page = makePage('route-capture', {nav, identity, wx: {
    chooseMedia: async () => ({tempFiles: [{tempFilePath: '/pending.jpg', size: 12}]}),
    showModal: o => o.success({confirm: true})
  }})
  await page.onLoad({id: 'sub-1'})
  await page.capturePhoto(evt({index: 0}))
  assert.equal(page.data.nodes[0].pendingPath, '/pending.jpg')
  assert.equal(calls.length, 0)
  await page.uploadPhoto(evt({index: 0}))
  assert.deepEqual(calls, ['save', 'upload'])
  assert.equal(page.data.nodes[0].pendingPath, '/pending.jpg')
  assert.equal(page.data.nodes[0].mediaId, '')
  fail = false
  await page.uploadPhoto(evt({index: 0}))
  assert.equal(page.data.nodes[0].pendingPath, '')
  assert.equal(page.data.nodes[0].mediaId, 'photo-1')
  page.onUnload()
})

test('camera denial reports failure and never uploads', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'collector'})
  const page = makePage('route-capture', {identity, nav: {
    me: async () => ({user: {id: 'collector'}, permissions: {collect: true}}), getSubmission: async () => sub(),
    uploadMedia: () => { throw new Error('Must not upload') }
  }, wx: {chooseMedia: async () => { throw {errMsg: 'chooseMedia:fail auth deny'} }}})
  await page.onLoad({id: 'sub-1'}); await page.capturePhoto(evt({index: 0}))
  assert.match(page.data.error, /相机权限/)
  assert.equal(page.data.busy, false)
  page.onUnload()
})

test('identity switch clears private nodes and late photos never render', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'collector'})
  let resolvePhoto
  const nav = {getSubmission: async () => ({...sub(), media: [{id: 'private', node_key: 'start'}]}),
    me: async () => ({user: {id: 'collector'}, permissions: {collect: true}}),
    fetchMediaTempUrl: () => new Promise(resolve => { resolvePhoto = resolve })}
  const page = makePage('route-capture', {nav, identity})
  await page.onLoad({id: 'sub-1'})
  identity.saveSession('new', {id: 'patient'})
  resolvePhoto('/private.jpg'); await tick()
  assert.equal(page.data.nodes.length, 0)
  assert.equal(page.data.editable, false)
  page.onUnload()
})

test('dual-role owner cannot activate review actions, including historical views', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'collector'})
  let reviews = 0
  const nav = {me: async () => ({user: {id: 'collector'}, permissions: {review: true}}),
    getSubmission: async () => ({...sub(), status: 'submitted', nodes: []}),
    review: async () => { reviews++ }}
  const page = makePage('route-review', {nav, identity})
  page.onLoad({id: 'sub-1'}); await page.onShow()
  assert.equal(page.data.isReviewer, false); assert.equal(page.data.selfReview, true)
  await page.approve(); await page.requestChanges()
  assert.equal(reviews, 0)
  page.onUnload()
})

test('photo walkthrough uses media_id and pauses immediately when validity check fails', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'patient'})
  let disabled = false
  const nav = {route: async () => {
    if (disabled) throw new Error('路线已停用')
    return {id: 'r', nodes: [{node_key: 'start', kind: 'start', media_id: 'm'}]}
  }, fetchMediaTempUrl: async id => { assert.equal(id, 'm'); return '/photo.jpg' }}
  const page = makePage('photo-walkthrough', {nav, identity})
  page.onLoad({id: 'r'}); await page.onShow()
  assert.equal(page.data.node.tempPath, '/photo.jpg')
  disabled = true; await page.next()
  assert.equal(page.data.node, null); assert.equal(page.data.nodes.length, 0)
  assert.match(page.data.error, /停用/)
  page.onUnload()
})

test('navigation tab distinguishes login, empty routes and network failure without demo fallback', async () => {
  const identity = makeIdentity(), urls = []
  let calls = 0, fail = false
  const page = makePage('navigation', {identity, nav: {routes: async () => {
    calls++; if (fail) throw new Error('连接失败'); return {items: []}
  }}, wx: {switchTab: o => urls.push(o.url), navigateTo: o => urls.push(o.url)}})
  page.onLoad(); await page.onShow()
  assert.equal(page.data.state, 'guest'); assert.equal(calls, 0)
  page.openLogin(); assert.equal(urls.at(-1), '/pages/profile/index')
  page.openWorkbench(); assert.equal(urls.at(-1), '/pages/navigation-workbench/index')
  identity.saveSession('t', {id: 'patient'})
  await page.onShow(); assert.equal(page.data.state, 'ready'); assert.equal(page.data.routes.length, 0)
  fail = true; await page.reload()
  assert.equal(page.data.state, 'error'); assert.match(page.data.error, /连接失败/)
  assert.equal(page.data.filtered.length, 0)
  page.onUnload()
})

test('navigation tab searches published endpoints and only opens the selected route', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'patient'})
  const urls = [], items = [
    {id: 'lab', status: 'published', title: '大厅至检验科', start: {description: '南门服务台', floor: '1F'}, end: {description: '抽血室', floor: '2F'}, floors: ['1F', '2F']},
    {id: 'pharmacy', status: 'published', title: '门诊药房', start: {description: '北门'}, end: {description: '药房'}},
    {id: 'draft', status: 'draft', title: '未公开草稿'}
  ]
  const page = makePage('navigation', {identity, nav: {routes: async () => ({items})}, wx: {navigateTo: o => urls.push(o.url)}})
  page.onLoad(); await page.onShow()
  assert.equal(page.data.filtered.length, 2)
  page.onSearch({detail: {value: '南门 2f'}})
  assert.equal(page.data.filtered.length, 1); assert.equal(page.data.filtered[0].id, 'lab')
  page.openRoute(evt({id: 'pharmacy'})); assert.equal(urls.length, 0)
  page.openRoute(evt({id: 'lab'})); assert.equal(urls[0], '/pages/route-review/index?readonly=1&id=lab')
  page.onSearch({detail: {value: '不存在的科室'}}); assert.equal(page.data.filtered.length, 0)
  page.clearSearch(); assert.equal(page.data.filtered.length, 2)
  page.onUnload()
})

test('navigation tab clears old hospital results on identity change and ignores late or hidden requests', async () => {
  const identity = makeIdentity(); identity.saveSession('old', {id: 'old'})
  let resolve
  const page = makePage('navigation', {identity, nav: {routes: () => new Promise(r => { resolve = r })}})
  page.onLoad()
  const first = page.reload()
  identity.saveSession('new', {id: 'new'})
  resolve({items: [{id: 'old-route', status: 'published'}]}); await first
  assert.equal(page.data.routes.length, 0); assert.equal(page.data.busy, false)
  const second = page.reload()
  page.onHide(); resolve({items: [{id: 'hidden-route', status: 'published'}]}); await second
  assert.equal(page.data.routes.length, 0)
  page.onUnload()
})

test('starting a photo guide requires user confirmation and a fresh unchanged publication', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'patient'})
  let confirm = false, revision = 4, requests = 0
  const urls = []
  const nav = {route: async () => { requests++; return {revision} }}
  const page = makePage('route-review', {identity, nav, wx: {showModal: o => o.success({confirm}), navigateTo: o => urls.push(o.url)}})
  page.onLoad({id: 'r', readonly: '1'})
  const content = {sub: {status: 'published', revision: 4}, nodes: [{tempPath: '/start.jpg', floor: '1F', description: '大厅服务台'}]}
  page.setData(content)
  await page.startWalkthrough(); assert.equal(requests, 0); assert.equal(urls.length, 0)
  confirm = true
  await page.startWalkthrough(); assert.equal(urls.length, 1); assert.match(urls[0], /revision=4/)
  revision = 7
  await page.startWalkthrough(); assert.equal(urls.length, 1); assert.match(page.data.error, /路线已更新/)
  page.setData(content)
  nav.route = async () => { throw new Error('路线已停用') }
  await page.startWalkthrough(); assert.equal(urls.length, 1); assert.equal(page.data.nodes.length, 0)
  assert.match(page.data.error, /停用/)
  page.onUnload()
})

test('periodic route checks never advance the user or reload a photo; new versions pause the guide', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'patient'})
  let poll, revision = 4, photos = 0
  const nodes = [{node_key: 'start', media_id: 'a'}, {node_key: 'end', media_id: 'b'}]
  const page = makePage('photo-walkthrough', {identity,
    timers: {setInterval: fn => { poll = fn; return 1 }},
    nav: {route: async () => ({revision, nodes}), fetchMediaTempUrl: async id => { photos++; return '/' + id + '.jpg' }}})
  page.onLoad({id: 'r', revision: '4'}); await page.onShow()
  for (let i = 0; i < 10; i++) await poll()
  assert.equal(page.data.current, 0); assert.equal(photos, 1); assert.equal(page.data.node.tempPath, '/a.jpg')
  await page.next(); assert.equal(page.data.current, 1); assert.equal(photos, 2)
  revision = 7; await poll()
  assert.equal(page.data.node, null); assert.match(page.data.error, /路线已更新/)
  await page.retry(); assert.equal(page.data.node, null)
  page.onUnload()
})

test('capture cannot submit a photo-only route with no usable start or floor description', async () => {
  const identity = makeIdentity(); identity.saveSession('t', {id: 'collector'})
  const page = makePage('route-capture', {identity, nav: {submit() { throw new Error('must not submit') }}})
  page.setData({editable: true, privacyOk: true, nodes: [{mediaId: 'photo', floor: ' ', description: ''}]})
  await page.submit()
  assert.match(page.data.error, /第 1 个节点.*楼层和位置说明/)
})

test('native page handlers run claim → photo upload → submit → independent publish → navigation tab → feedback → disable against real HTTP', {timeout: 30000}, async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'yfz-m11-'))
  // Keep the SQLite file in the workspace: Node's temp directory can be created
  // under a sandbox ACL that the Python child cannot open on Windows.
  const dbPath = path.join(ROOT, '.work', 'm11-http-' + process.pid + '-' + Date.now() + '.sqlite3')
  fs.mkdirSync(path.dirname(dbPath), {recursive: true})
  const server = net.createServer()
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise(resolve => server.close(resolve))
  const cleanup = () => {
    fs.rmSync(dir, {recursive: true, force: true})
    for (const suffix of ['', '-wal', '-shm']) fs.rmSync(dbPath + suffix, {force: true})
  }
  let child
  try {
    child = spawn(path.join(ROOT, 'backend/.venv/Scripts/python.exe'),
      ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', String(port)], {
        cwd: ROOT, windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'],
        env: {...process.env, YIFAZHILIAN_DB_PATH: dbPath, YIFAZHILIAN_AI_PROVIDER: 'mock',
          YIFAZHILIAN_WECHAT_APPID: '', YIFAZHILIAN_WECHAT_SECRET: ''}
      })
  } catch (error) {
    cleanup()
    if (error.code === 'EPERM') return t.skip(SANDBOX_EPERM_SKIP)
    throw error
  }
  const spawnFailure = await new Promise(resolve => {
    child.once('spawn', () => resolve(null))
    child.once('error', resolve)
  })
  if (spawnFailure) {
    cleanup()
    if (spawnFailure.code === 'EPERM') return t.skip(SANDBOX_EPERM_SKIP)
    throw spawnFailure
  }
  let errors = ''
  child.stderr.on('data', data => { errors = (errors + data).slice(-4000) })
  const origin = 'http://127.0.0.1:' + port
  const pages = []
  try {
    let started = false
    for (let i = 0; i < 60; i++) {
      try { if ((await fetch(origin + '/api/v1/health')).ok) { started = true; break } } catch (_) {}
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    assert.ok(started, errors)
    const imagePath = path.join(dir, 'synthetic.png')
    fs.writeFileSync(imagePath, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=', 'base64'))
    const urls = [], toasts = []
    const wx = {
      request(options) { return send(options, false, false) },
      uploadFile(options) { return send(options, true, false) },
      downloadFile(options) { return send(options, false, true) },
      chooseMedia: async () => ({tempFiles: [{tempFilePath: imagePath, size: fs.statSync(imagePath).size}]}),
      showModal: o => o.success({confirm: true}),
      showToast: o => toasts.push(o.title),
      navigateTo: o => urls.push(o.url), navigateBack() {}
    }
    function send(options, upload, download) {
      const controller = new AbortController()
      ;(async () => {
        let body, headers = {...options.header}
        if (upload) {
          body = new FormData()
          Object.entries(options.formData).forEach(([k, v]) => body.append(k, v))
          body.append('file', new Blob([fs.readFileSync(options.filePath)], {type: 'image/png'}), 'synthetic.png')
        } else if (options.data !== undefined) {
          headers['Content-Type'] = 'application/json'; body = JSON.stringify(options.data)
        }
        const response = await fetch(options.url, {method: upload ? 'POST' : options.method || 'GET', headers, body, signal: controller.signal})
        if (download && response.ok) {
          const tempFilePath = path.join(dir, 'download-' + Math.random() + '.png')
          fs.writeFileSync(tempFilePath, Buffer.from(await response.arrayBuffer()))
          options.success({statusCode: response.status, tempFilePath})
        } else {
          const text = await response.text()
          options.success({statusCode: response.status, data: upload || !text ? text : JSON.parse(text)})
        }
      })().catch(error => options.fail({errMsg: error.message}))
      return {abort: () => controller.abort()}
    }
    const identity = makeIdentity()
    const requires = {'./identity': identity, '../config/index': {baseURL: origin + '/api/v1'}}
    const nav = moduleFrom('services/navigation.js', requires, wx)
    const api = moduleFrom('services/api.js', requires, wx)
    const env = {nav, api, identity, wx}
    const landing = makePage('navigation', env); pages.push(landing); landing.onLoad()
    const workbench = makePage('navigation-workbench', env); pages.push(workbench)
    workbench.onLoad()
    await workbench.switchDemo(evt({id: 'demo-volunteer-001'}))
    assert.equal(workbench.data.perms.collect, true, workbench.data.error)
    await landing.onShow()
    assert.equal(landing.data.state, 'ready'); assert.equal(landing.data.routes.length, 0)
    await workbench.claim(evt({id: 'task-lab-a'}))
    assert.match(urls.at(-1), /route-capture/)
    const sid = new URL('http://test' + urls.at(-1)).searchParams.get('id')
    const capture = makePage('route-capture', env); pages.push(capture)
    await capture.onLoad({id: sid})
    for (let i = 0; i < 2; i++) {
      capture.onField({...evt({index: i, key: 'floor'}), detail: {value: '门诊楼 1F'}})
      capture.onField({...evt({index: i, key: 'description'}), detail: {value: i ? '检验科入口' : '大厅服务台'}})
    }
    for (let i = 0; i < 2; i++) {
      await capture.capturePhoto(evt({index: i}))
      await capture.uploadPhoto(evt({index: i}))
      assert.ok(capture.data.nodes[i].mediaId, capture.data.error)
    }
    capture.togglePrivacy(); await capture.submit()
    assert.equal(capture.data.sub.status, 'submitted', capture.data.error)
    assert.equal(capture.data.editable, false)
    await landing.reload(); assert.equal(landing.data.routes.length, 0)
    const own = await fetch(origin + '/api/v1/navigation/submissions/' + sid + '/review', {
      method: 'POST', headers: {Authorization: 'Bearer ' + identity.getToken(), 'Content-Type': 'application/json'},
      body: JSON.stringify({revision: capture.data.sub.revision, decision: 'approve', note: '试图自审', walkthrough_confirmed: true})})
    assert.equal(own.status, 403)
    await workbench.switchDemo(evt({id: 'demo-reviewer-001'}))
    assert.equal(workbench.data.queue[0].id, sid)
    const review = makePage('route-review', env); pages.push(review)
    review.onLoad({id: sid}); await review.onShow()
    assert.ok(review.data.nodes.every(n => n.tempPath))
    review.onNote({detail: {value: '合成场景独立实走；全程同层，无台阶。'}})
    review.toggleWalkthrough(); await review.approve()
    assert.equal(review.data.sub.status, 'published', review.data.error)
    await workbench.switchDemo(evt({id: 'demo-patient-001'}))
    await landing.onShow()
    assert.equal(landing.data.filtered[0].id, sid, landing.data.error)
    assert.equal(landing.data.filtered[0].start.description, '大厅服务台')
    landing.onSearch({detail: {value: '检验科'}})
    landing.openRoute(evt({id: sid}))
    assert.match(urls.at(-1), /route-review\/index\?readonly=1/)
    const publicPage = makePage('route-review', env); pages.push(publicPage)
    publicPage.onLoad({id: sid, readonly: '1'}); await publicPage.onShow()
    assert.equal(publicPage.data.sub.status, 'published')
    await publicPage.startWalkthrough()
    assert.match(urls.at(-1), /photo-walkthrough\/index\?id=/)
    const walkQuery = Object.fromEntries(new URL('http://test' + urls.at(-1)).searchParams)
    await publicPage.submitFeedback()
    assert.ok(toasts.includes('反馈已送至审核工作台'))
    const walk = makePage('photo-walkthrough', env); pages.push(walk)
    walk.onLoad(walkQuery); await walk.onShow()
    assert.ok(walk.data.node.tempPath)
    await walk.checkStatus(); assert.equal(walk.data.current, 0)
    await walk.next(); assert.equal(walk.data.current, 1)
    await workbench.switchDemo(evt({id: 'demo-reviewer-001'}))
    await review.load()
    assert.equal(review.data.sub.feedback.length, 1)
    review.onDisableReason({detail: {value: '合成封路反馈，停用'}}); await review.disable()
    assert.equal(review.data.sub.status, 'disabled', review.data.error)
    await workbench.switchDemo(evt({id: 'demo-patient-001'}))
    assert.equal(workbench.data.routes.length, 0)
    await landing.onShow()
    assert.equal(landing.data.state, 'ready'); assert.equal(landing.data.routes.length, 0)
    await walk.retry()
    assert.equal(walk.data.node, null); assert.match(walk.data.error, /停用/)
    await workbench.switchDemo(evt({id: 'demo-volunteer-001'}))
    await capture.load()
    assert.equal(capture.data.canRevise, true)
    await capture.revise()
    assert.equal(capture.data.editable, true, capture.data.error)
    assert.equal(capture.data.sub.status, 'draft')
    assert.equal((await nav.routes()).items.length, 0)
    capture.togglePrivacy(); await capture.submit()
    assert.equal(capture.data.sub.status, 'submitted', capture.data.error)
    await workbench.switchDemo(evt({id: 'demo-reviewer-001'}))
    await review.load()
    review.onNote({detail: {value: '合成路线重新核验，确认恢复通行。'}})
    review.toggleWalkthrough(); await review.approve()
    assert.equal(review.data.sub.status, 'published', review.data.error)
  } finally {
    pages.forEach(p => p.onUnload && p.onUnload())
    child.kill()
    await new Promise(resolve => { if (child.exitCode !== null) resolve(); else child.once('exit', resolve) })
    assert.equal(path.dirname(path.resolve(dir)), path.resolve(os.tmpdir()))
    assert.match(path.basename(dir), /^yfz-m11-/)
    fs.rmSync(dir, {recursive: true, force: true})
    for (const suffix of ['', '-wal', '-shm']) fs.rmSync(dbPath + suffix, {force: true})
  }
})

