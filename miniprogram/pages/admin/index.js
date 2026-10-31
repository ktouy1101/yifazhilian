const api = require('../../services/api')

// 管理台首页：只放概览数字与入口，具体的列表和操作在各自子页面。
Page({
  data: {loading: true, denied: false, me: null, overview: {}},

  async onShow() { return this.load() },

  async load() {
    if (!api.identity.getToken()) {
      this.setData({loading: false, denied: true})
      this.deny('需要先登录。')
      return
    }
    try {
      const me = await api.request('/users/me')
      const caps = (me && me.capabilities) || {}
      if (!caps.is_reviewer) {
        this.setData({loading: false, denied: true})
        this.deny('当前账号不是审核员。管理员手机号由服务端配置指定，请联系管理员。')
        return
      }
      const overview = await api.request('/admin/overview')
      this.setData({loading: false, me, overview, denied: false})
    } catch (error) {
      this.setData({loading: false, denied: true})
      wx.showToast({title: '读取失败：' + (error.message || '请稍后重试'), icon: 'none'})
    }
  },

  deny(content) {
    wx.showModal({
      title: '没有审核员权限', content, showCancel: false,
      success: () => wx.navigateBack({fail: () => wx.switchTab({url: '/pages/home/index'})})
    })
  },

  open(e) { wx.navigateTo({url: e.currentTarget.dataset.url}) }
})
