const identity = require('./identity')
const images = require('./image_upload')
const {baseURL, cloudRun} = require('../config/index')
const enc = encodeURIComponent
const temporary = new Set()

function removeTemp(filePath) {
  if (!filePath) return
  temporary.delete(filePath)
  if (wx.getFileSystemManager) wx.getFileSystemManager().unlink({filePath, fail() {}})
}
function clearTemp() { Array.from(temporary).forEach(removeTemp) }
identity.onChange(clearTemp)

function cloudJson(path, method = 'GET', data) {
  const token = identity.getToken()
  const version = identity.getVersion()
  return new Promise((resolve, reject) => {
    wx.cloud.callContainer({
      config: {env: cloudRun.env},
      path: '/api/v1' + path,
      method,
      header: {'X-WX-SERVICE': cloudRun.service, 'content-type': 'application/json',
               Authorization: 'Bearer ' + token},
      data,
      timeout: path.endsWith('/ocr') ? 95000 : 20000,
      success(res) {
        if (identity.getVersion() !== version) return reject(new Error('身份已切换'))
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data)
        const error = new Error((res.data && res.data.detail) || '操作未完成，请检查授权与输入后重试')
        error.status = res.statusCode
        if (res.statusCode === 401) identity.clearSession()
        reject(error)
      },
      fail() { reject(new Error('云托管服务未连通，请检查网络后重试')) }
    })
  })
}

function transport(kind, path, options = {}) {
  if (images.enabled() && kind === 'request') {
    return cloudJson(path, options.method || 'GET', options.data)
  }
  const token = identity.getToken(), version = identity.getVersion()
  if (!token) return Promise.reject(new Error('请先登录，再上传或查看检验单'))
  return new Promise((resolve, reject) => {
    let task, settled = false
    const finish = (error, value) => {
      if (settled) return
      settled = true; unsubscribe()
      error ? reject(error) : resolve(value)
    }
    const unsubscribe = identity.onChange(() => {
      finish(new Error('身份已切换，本次操作已取消'))
      if (task && task.abort) task.abort()
    })
    task = wx[kind]({...options, url: baseURL + path, timeout: path.endsWith('/ocr') ? 95000 : 20000,
      header: {Authorization: 'Bearer ' + token},
      success(res) {
        if (identity.getVersion() !== version || settled) {
          if (res.tempFilePath) removeTemp(res.tempFilePath)
          return finish(new Error('身份已切换'))
        }
        let body = res.data
        if (kind === 'uploadFile') {
          try { body = JSON.parse(body) } catch (_) { return finish(new Error('响应无法解析，请重新载入核对上传结果')) }
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          if (kind === 'downloadFile') { temporary.add(res.tempFilePath); return finish(null, res.tempFilePath) }
          return finish(null, body)
        }
        if (res.tempFilePath) removeTemp(res.tempFilePath)
        const error = new Error(body && typeof body.detail === 'string' ? body.detail : '操作未完成，请检查授权与输入后重试')
        error.status = res.statusCode
        if (res.statusCode === 403) clearTemp()
        finish(error)
        if (res.statusCode === 401 && identity.getVersion() === version) identity.clearSession()
      },
      fail(error) {
        finish(new Error(error && /timeout/.test(error.errMsg || '')
          ? '请求超时，结果尚未确认。请重新载入查看状态，再决定是否重试。'
          : '本机服务未连接，请检查服务与网络后重试'))
      }
    })
  })
}
const json = (path, method = 'GET', data) => transport('request', path, {method, data})
const root = '/record-documents'
const path = id => root + '/' + enc(id)
const requestId = () => 'm03-' + Date.now() + '-' + Math.random().toString(36).slice(2, 12)

async function access() {
  const result = await json('/consents')
  const policy = result.policies && result.policies.records_read
  if (!policy || !policy.notice || !policy.recipient || !policy.policy_version || policy.external_network !== false) {
    throw new Error('尚未取得本地病历处理告知，请稍后重试')
  }
  const consent = (result.items || []).find(item => item.scope === 'records_read')
  const active = !!(consent && consent.granted && !consent.revoked_at && Date.parse(consent.expires_at) > Date.now()
    && consent.policy_version === policy.policy_version && consent.recipient === policy.recipient)
  return {active, policy, expiresAt: active ? Date.parse(consent.expires_at) : 0}
}
async function grant(policy) {
  const version = identity.getVersion()
  const confirm = await new Promise(resolve => wx.showModal({title: '本地病历处理授权',
    content: policy.notice + '\n接收方：' + policy.recipient + '\n版本：' + policy.policy_version,
    confirmText: '同意授权', success: res => resolve(!!res.confirm), fail: () => resolve(false)}))
  if (!confirm || identity.getVersion() !== version) return false
  await json('/consents', 'POST', {scope: 'records_read', granted: true, recipient: policy.recipient, policy_version: policy.policy_version})
  return true
}
const statusLabel = value => ({uploaded: '待识别', recognizing: '识别中', review: '待核对', failed: '识别未完成', archived: '已归档'})[value] || value
const formatTime = value => value ? new Date(Date.parse(value) + 8 * 3600000).toISOString().slice(0, 16).replace('T', ' ') : ''
module.exports = {
  requestId, access, grant, clearTemp, removeTemp, statusLabel, formatTime,
  list: () => json(root), get: id => json(path(id)),
  checklist: scenario => json(root + '/checklist?scenario=' + enc(scenario)),
  upload: async filePath => {
    if (images.enabled()) {
      const data = await images.toDataUrl(filePath, 80)
      return cloudJson(root + '/base64', 'POST', {data})
    }
    return transport('uploadFile', root, {filePath, name: 'file'})
  },
  recognize: (id, data) => json(path(id) + '/ocr', 'POST', data),
  save: (id, data) => json(path(id) + '/draft', 'PUT', data),
  confirm: (id, data) => json(path(id) + '/confirm', 'POST', data),
  version: (id, version) => json(path(id) + '/versions/' + version),
  job: (id, job) => json(path(id) + '/jobs/' + enc(job)),
  image: async id => {
    if (images.enabled()) {
      const res = await cloudJson(path(id) + '/image-base64')
      return res.data
    }
    return transport('downloadFile', path(id) + '/image')
  },
  crop: async (id, job, field) => {
    if (images.enabled()) {
      const res = await cloudJson(path(id) + '/jobs/' + enc(job) + '/fields/' + enc(field) + '/image-base64')
      return res.data
    }
    return transport('downloadFile', path(id) + '/jobs/' + enc(job) + '/fields/' + enc(field) + '/image')
  },
  discard: (id, revision) => json(path(id) + '?revision=' + revision, 'DELETE')
}
