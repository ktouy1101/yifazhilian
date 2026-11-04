const identity = require('./services/identity')
const {cloudRun} = require('./config/index')

App({
  onLaunch() {
    // 云托管模式：初始化云开发环境，之后 api.js 用 callContainer 发请求。
    if (cloudRun && cloudRun.enabled && cloudRun.env && wx.cloud) {
      wx.cloud.init({env: cloudRun.env, traceUser: true})
    }
    identity.restore()
    const token = identity.getToken()
    this.globalData = {
      token,
      user: identity.getUser(),
      previewMode: !token,
      identityVersion: identity.getVersion()
    }
  },
  globalData: {token: null, user: null, previewMode: true, identityVersion: 0}
})
