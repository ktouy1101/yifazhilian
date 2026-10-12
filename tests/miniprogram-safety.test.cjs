const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')

function component(request) {
  let definition, scheduled
  const sandbox = {
    Component(value) { definition = value },
    require() { return {request} },
    setTimeout(fn, delay) { assert.equal(delay, 1200); scheduled = fn; return 1 },
    clearTimeout() { scheduled = null },
    Date, Math
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../miniprogram/components/emergency-button/index.js'), 'utf8'), sandbox)
  const instance = {data: {...definition.data}, setData(value) { Object.assign(this.data, value) }}
  for (const [key, fn] of Object.entries(definition.methods)) instance[key] = fn.bind(instance)
  return {instance, definition, trigger() { const fn = scheduled; scheduled = null; if (fn) fn() }, hasTimer() { return !!scheduled }}
}
const settle = () => new Promise(resolve => setImmediate(resolve))

test('松手或切后台在阈值前取消，不向服务端发事件', async () => {
  let calls = 0
  const c = component(async () => { calls++; return {id: 'demo-1'} })
  c.instance.start()
  assert.equal(calls, 0)
  c.instance.cancel()
  c.trigger()
  assert.equal(calls, 0)
  c.instance.start()
  c.definition.pageLifetimes.hide.call(c.instance)
  assert.equal(c.hasTimer(), false)
  c.trigger()
  await settle()
  assert.equal(calls, 0)
})

test('超时重试复用幂等键，成功只显示本地接收而非接通', async () => {
  const keys = []
  const c = component(async (_path, _method, body) => {
    keys.push(body.idempotency_key)
    if (keys.length === 1) throw new Error('timeout after server acceptance')
    return {id: 'demo-event-1', status: 'received', delivery: 'mock'}
  })
  c.instance.start(); c.trigger(); await settle()
  assert.equal(c.instance.data.retryAvailable, true)
  c.instance.retry(); await settle()
  assert.equal(keys.length, 2)
  assert.equal(keys[0], keys[1])
  assert.match(c.instance.data.status, /未通知、未接通/)
  assert.equal(c.instance.data.retryAvailable, false)
})
