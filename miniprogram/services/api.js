const {baseURL} = require('../config/index')
function request(path, method = 'GET', data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: baseURL + path, method, data, timeout: 10000,
      header: {Authorization: 'Bearer ' + (getApp().globalData.token || '')},
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data)
        if (res.statusCode === 401) getApp().globalData.token = null
        const detail = res.data && res.data.detail
        reject(new Error(typeof detail === 'string' ? detail : '请求未完成，请检查授权与输入'))
      },
      fail() { reject(new Error('本地服务未连接；紧急情况请使用床旁呼叫器联系医护')) }
    })
  })
}
async function login() {
  const result = await request('/auth/demo-login', 'POST', {role: 'patient', demo_alias: 'demo-patient-001'})
  getApp().globalData.token = result.access_token
  return result
}
module.exports = {request, login}
