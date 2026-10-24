const identity = require('./identity')
const {baseURL} = require('../config/index')
const enc = encodeURIComponent

// Capture identity before dispatch. Abort in-flight work on logout/switch;
// old responses (including 401) must never affect the new account.
function transport(kind, path, options = {}) {
  const token = identity.getToken()
  const version = identity.getVersion()
  if (!token) return Promise.reject(new Error('请先登录或选择合成演示身份'))
  return new Promise((resolve, reject) => {
    let task, settled = false
    const done = (error, value) => {
      if (settled) return
      settled = true
      unsubscribe()
      if (error) reject(error)
      else resolve(value)
    }
    const unsubscribe = identity.onChange(() => {
      done(new Error('身份已切换，本次操作已取消'))
      if (task && task.abort) task.abort()
    })
    task = wx[kind](Object.assign({}, options, {
      url: baseURL + path, timeout: 20000,
      header: {Authorization: 'Bearer ' + token},
      success(res) {
        if (identity.getVersion() !== version) return done(new Error('身份已切换'))
        let body = res.data
        if (kind === 'uploadFile') {
          try { body = JSON.parse(body) } catch (_) { return done(new Error('上传响应无法解析，请刷新确认结果')) }
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          return done(null, kind === 'downloadFile' ? res.tempFilePath : body)
        }
        const error = new Error(body && typeof body.detail === 'string' ? body.detail : '操作失败，请刷新后重试')
        error.status = res.statusCode
        done(error)
        if (res.statusCode === 401 && identity.getVersion() === version) identity.clearSession()
      },
      fail() { done(new Error('网络请求未完成，请检查连接并刷新确认结果')) }
    }))
  })
}
const json = (path, method = 'GET', data) => transport('request', '/navigation' + path, {method, data})
const navigation = {
  me: () => json('/me'),
  tasks: () => json('/tasks'),
  claimTask: id => json('/tasks/' + enc(id) + '/claim', 'POST'),
  createSubmission: data => json('/submissions', 'POST', data),
  listSubmissions: (scope = 'mine') => json('/submissions?scope=' + enc(scope)),
  getSubmission: id => json('/submissions/' + enc(id)),
  version: (id, revision) => json('/submissions/' + enc(id) + '/versions/' + revision),
  updateSubmission: (id, data) => json('/submissions/' + enc(id), 'PUT', data),
  submit: (id, data) => json('/submissions/' + enc(id) + '/submit', 'POST', data),
  review: (id, data) => json('/submissions/' + enc(id) + '/review', 'POST', data),
  disable: (id, data) => json('/submissions/' + enc(id) + '/disable', 'POST', data),
  revise: (id, data) => json('/submissions/' + enc(id) + '/revise', 'POST', data),
  routes: () => json('/routes'),
  route: id => json('/routes/' + enc(id)),
  feedback: (id, data) => json('/routes/' + enc(id) + '/feedback', 'POST', data),
  uploadMedia: (id, {nodeKey, revision, filePath, uploadId}) => transport('uploadFile',
    '/navigation/submissions/' + enc(id) + '/media', {
      filePath, name: 'file',
      formData: {node_key: nodeKey, revision: String(revision), client_upload_id: uploadId || ''}
    }),
  fetchMediaTempUrl: id => transport('downloadFile', '/navigation/media/' + enc(id)),
  fetchVersionPhoto: (id, revision, key) => transport('downloadFile',
    '/navigation/submissions/' + enc(id) + '/versions/' + revision + '/media/' + enc(key))
}
module.exports = navigation

