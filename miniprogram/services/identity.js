// Identity store: token + current user persisted to wx.storage so a relaunch
// restores the session. identityVersion is an in-memory monotonic counter:
// every login/logout/switch bumps it, and pages compare it around async work
// to discard stale responses after the identity has changed.
const TOKEN_KEY = 'yfz_token'
const USER_KEY = 'yfz_user'

let _token = ''
let _user = null
let _version = 0
const listeners = new Set()

function storage() {
  // wx is the global in the mini-program runtime; tests inject a mock.
  return (typeof wx !== 'undefined') ? wx : null
}

function restore() {
  const s = storage()
  if (!s) return
  try {
    _token = s.getStorageSync(TOKEN_KEY) || ''
    const user = s.getStorageSync(USER_KEY)
    _user = user && typeof user === 'object' ? user : null
  } catch (_) {
    _token = ''
    _user = null
  }
  if (!_token) _user = null
  bump()
}

function bump() {
  _version += 1
  listeners.forEach(listener => { try { listener() } catch (_) {} })
  return _version
}

function syncGlobalApp() {
  // Mirror the session into getApp().globalData for existing pages that still
  // read it. In unit tests getApp is undefined, so this is a no-op there.
  if (typeof getApp === 'function') {
    const app = getApp()
    if (app && app.globalData) {
      app.globalData.token = _token
      app.globalData.user = _user
      app.globalData.previewMode = !_token
      app.globalData.identityVersion = _version
    }
  }
}

function saveSession(token, user) {
  _token = String(token || '')
  _user = user && typeof user === 'object' ? user : null
  const s = storage()
  if (s) {
    try {
      if (_token) {
        s.setStorageSync(TOKEN_KEY, _token)
        if (_user) s.setStorageSync(USER_KEY, _user)
      } else {
        s.removeStorageSync(TOKEN_KEY)
        s.removeStorageSync(USER_KEY)
      }
    } catch (_) { /* storage full / unavailable: keep in-memory only */ }
  }
  bump()
  syncGlobalApp()
  return _version
}

function clearSession() {
  _token = ''
  _user = null
  const s = storage()
  if (s) {
    try {
      s.removeStorageSync(TOKEN_KEY)
      s.removeStorageSync(USER_KEY)
    } catch (_) { /* ignore */ }
  }
  bump()
  syncGlobalApp()
  return _version
}

module.exports = {
  restore, bump, saveSession, clearSession,
  getToken: () => _token,
  getUser: () => _user,
  getVersion: () => _version,
  onChange(listener) { listeners.add(listener); return () => listeners.delete(listener) },
  // Exposed for tests only.
  _reset() { _token = ''; _user = null; _version = 0 }
}
