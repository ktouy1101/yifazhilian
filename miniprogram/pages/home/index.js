const api = require('../../services/api')
const showError = require('../../utils/errors')
Page({
  data: {loggedIn: false},
  onShow() { this.setData({loggedIn: !!getApp().globalData.token}) },
  async login() { try { await api.login(); this.setData({loggedIn: true}) } catch (e) { showError(e) } },
  chat() { wx.navigateTo({url: '/pages/chat/index?domain=medical'}) },
  settings() { wx.switchTab({url: '/pages/profile/index'}) }
})
