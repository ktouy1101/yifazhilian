const test = require('node:test')
const assert = require('node:assert/strict')

// Build a fresh sandbox around the identity module for each test.
function loadIdentity() {
  const store = new Map()
  globalThis.wx = {
    getStorageSync(key) { return store.has(key) ? store.get(key) : '' },
    setStorageSync(key, value) { store.set(key, value) },
    removeStorageSync(key) { store.delete(key) }
  }
  delete require.cache[require.resolve('../miniprogram/services/identity')]
  const identity = require('../miniprogram/services/identity')
  identity._reset()
  return {identity, store}
}

test('saveSession persists token/user and bumps version', () => {
  const {identity, store} = loadIdentity()
  const v1 = identity.getVersion()
  const version = identity.saveSession('tok-abc', {id: 'demo-patient-001', role: 'patient'})
  assert.equal(version, v1 + 1)
  assert.equal(identity.getToken(), 'tok-abc')
  assert.equal(identity.getUser().id, 'demo-patient-001')
  assert.equal(store.get('yfz_token'), 'tok-abc')
  assert.deepEqual(store.get('yfz_user'), {id: 'demo-patient-001', role: 'patient'})
})

test('clearSession wipes memory and storage, version bumps', () => {
  const {identity, store} = loadIdentity()
  identity.saveSession('tok-abc', {id: 'demo-patient-001'})
  const before = identity.getVersion()
  identity.clearSession()
  assert.equal(identity.getToken(), '')
  assert.equal(identity.getUser(), null)
  assert.equal(store.has('yfz_token'), false)
  assert.equal(store.has('yfz_user'), false)
  assert.equal(identity.getVersion(), before + 1)
})

test('restore reads back a previously saved session', () => {
  const {identity, store} = loadIdentity()
  identity.saveSession('tok-restore', {id: 'demo-volunteer-001', role: 'volunteer'})
  // Simulate a relaunch: reset memory and reload from storage.
  identity._reset()
  assert.equal(identity.getToken(), '')
  identity.restore()
  assert.equal(identity.getToken(), 'tok-restore')
  assert.equal(identity.getUser().role, 'volunteer')
})

test('restore with empty storage yields preview mode', () => {
  const {identity} = loadIdentity()
  identity.restore()
  assert.equal(identity.getToken(), '')
  assert.equal(identity.getUser(), null)
})

test('switching identities bumps version so pages can detect staleness', () => {
  const {identity} = loadIdentity()
  identity.saveSession('tok-a', {id: 'demo-patient-001'})
  const afterA = identity.getVersion()
  identity.clearSession()
  identity.saveSession('tok-b', {id: 'demo-patient-002'})
  assert.ok(identity.getVersion() > afterA)
  assert.equal(identity.getToken(), 'tok-b')
  assert.equal(identity.getUser().id, 'demo-patient-002')
})
