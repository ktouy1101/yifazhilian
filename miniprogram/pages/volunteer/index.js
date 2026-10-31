const api = require('../../services/api')

// 志愿者中心首页：只放状态与入口，具体操作在子页面。
Page({
  data: {loading: true, status: 'none', profile: null, caps: {}, credentials: [], error: ''},

  onShow() { return this.load() },

  async load() {
    if (!api.identity.getToken()) { this.setData({loading: false, status: 'guest'}); return }
    try {
      const result = await api.request('/volunteer/me')
      const profile = result.profile || null
      const caps = result.capabilities || {}
      let credentials = []
      try { credentials = (await api.request('/volunteer/credentials')).items || [] } catch (e) { /* 无凭证时留空 */ }
      this.setData({
        loading: false,
        profile,
        caps,
        credentials,
        status: (profile && profile.status) || 'none',
        error: ''
      })
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  open(e) { wx.navigateTo({url: e.currentTarget.dataset.url}) },
  openWorkbench() { wx.navigateTo({url: '/pages/navigation-workbench/index'}) },
  openLegalHelp() { wx.navigateTo({url: '/pages/legal-help/index'}) },
  openLogin() { wx.switchTab({url: '/pages/profile/index'}) }
})
