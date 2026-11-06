const identity = require('./services/identity')
const {cloudRun} = require('./config/index')

App({
  onLaunch() {
    // 云托管模式：初始化云开发环境，之后 api.js 用 callContainer 发请求。
    // 若基础库不支持云能力（或环境 ID 不对），这里不能抛错，否则整个小程序白屏。
    if (cloudRun && cloudRun.enabled && cloudRun.env && wx.cloud) {
      try {
        wx.cloud.init({env: cloudRun.env, traceUser: true})
        this.globalData.cloudReady = true
      } catch (error) {
        console.error('[cloud] init failed, fallback to HTTP', error)
        this.globalData.cloudReady = false
      }
    }
    identity.restore()
    const token = identity.getToken()
    this.globalData = {
      ...(this.globalData || {}),
      token,
      user: identity.getUser(),
      previewMode: !token,
      identityVersion: identity.getVersion()
    }
  },
  globalData: {token: null, user: null, previewMode: true, identityVersion: 0, cloudReady: false}
})
