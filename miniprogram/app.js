const identity = require('./services/identity')

App({
  onLaunch() {
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
