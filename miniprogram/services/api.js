const {baseURL} = require('../config/index')
const identity = require('./identity')

function request(path, method = 'GET', data) {
  const messageRequest = /^\/conversations\/[^/]+\/messages$/.test(path)
  const token = identity.getToken() || ''
  const sessionVersion = identity.getVersion ? identity.getVersion() : token
  const current = () => sessionVersion === (identity.getVersion ? identity.getVersion() : (identity.getToken() || ''))
  return new Promise((resolve, reject) => {
    let task, settled = false, unsubscribe = () => {}
    const finish = (error, value) => {
      if (settled) return
      settled = true
      unsubscribe()
      if (error) reject(error)
      else resolve(value)
    }
    if (identity.onChange) unsubscribe = identity.onChange(() => {
      finish(new Error('身份已切换，本次请求已取消'))
      if (task && task.abort) task.abort()
    })
    task = wx.request({
      url: baseURL + path, method, data, timeout: messageRequest ? 45000 : 10000,
      header: {Authorization: 'Bearer ' + token},
      success(res) {
        if (!current()) return finish(new Error('身份已切换，本次请求已取消'))
        if (res.statusCode >= 200 && res.statusCode < 300) return finish(null, res.data)
        const detail = res.data && res.data.detail
        const validation = path.startsWith('/health-management') && Array.isArray(detail)
          ? detail.map(item => String(item.msg || '').replace(/^Value error, /, '')).filter(Boolean).join('；') : ''
        const error = new Error(typeof detail === 'string' ? detail : (validation || '请求未完成，请检查授权与输入'))
        error.status = res.statusCode
        finish(error)
        if (res.statusCode === 401) {
          // Token revoked (logout/expiry): drop local session so the UI returns
          // to preview mode instead of retrying with a dead token.
          identity.clearSession()
        }
      },
      fail(error) {
        const timedOut = error && typeof error.errMsg === 'string' && /timeout/i.test(error.errMsg)
        finish(new Error(timedOut ? '请求超时，未确认服务端是否已完成；请检查连接后再操作' : '本地服务未连接；紧急情况请使用床旁呼叫器联系医护'))
      }
    })
  })
}

async function login(alias = 'demo-patient-001', role = 'patient') {
  const result = await request('/auth/demo-login', 'POST', {role, demo_alias: alias})
  identity.saveSession(result.access_token, result.user)
  return result
}

async function wechatLogin() {
  // wx.login gets a temporary code; backend exchanges it for an openid.
  const code = await new Promise((resolve, reject) => {
    wx.login({
      success(res) { res.code ? resolve(res.code) : reject(new Error('未拿到微信 code')) },
      fail() { reject(new Error('微信登录失败')) }
    })
  })
  const result = await request('/auth/wechat-login', 'POST', {code})
  identity.saveSession(result.access_token, result.user)
  return result
}

async function logout() {
  try { await request('/auth/logout', 'POST') } catch (_) { /* ignore */ }
  identity.clearSession()
}

// 用户资料
const getMe = () => request('/users/me')
const updateProfile = (data) => request('/users/me', 'PATCH', data)

// 体征
const listVitals = () => request('/vitals')
const uploadVital = (data) => request('/vitals', 'POST', data)

// 用药
const listMedications = () => request('/medications')
const createMedication = (data) => request('/medications', 'POST', data)
const deleteMedication = (id) => request('/medications/' + id, 'DELETE')

// 就诊笔记
const listRecords = () => request('/records')
const createRecord = (data) => request('/records', 'POST', data)
const deleteRecord = (id) => request('/records/' + id, 'DELETE')

module.exports = {
  request, login, wechatLogin, logout, identity,
  getMe, updateProfile,
  listVitals, uploadVital,
  listMedications, createMedication, deleteMedication,
  listRecords, createRecord, deleteRecord
}
