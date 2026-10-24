const api = require('../../services/api')

// 志愿者中心：申请 → 等待审核 → 通过后出现采集入口。
// 页面只负责展示与提交；能不能采集由服务端 capabilities.can_collect 决定。
Page({
  data: {
    loading: true,
    status: 'none',       // guest / none / pending / approved / rejected / suspended
    profile: null,
    caps: {},
    realName: '',
    hospitalId: 'demo-hospital',
    training: false,
    submitting: false,
    error: ''
  },

  onShow() { return this.load() },

  async load() {
    if (!api.identity.getToken()) {
      this.setData({loading: false, status: 'guest'})
      return
    }
    try {
      const result = await api.request('/volunteer/me')
      const profile = result.profile || null
      this.setData({
        loading: false,
        profile,
        caps: result.capabilities || {},
        status: (profile && profile.status) || 'none',
        realName: (profile && profile.real_name) || this.data.realName,
        hospitalId: (profile && profile.hospital_id) || this.data.hospitalId,
        error: ''
      })
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取申请状态失败'})
    }
  },

  onName(event) { this.setData({realName: event.detail.value}) },
  onHospital(event) { this.setData({hospitalId: event.detail.value}) },
  onTraining(event) { this.setData({training: event.detail.value}) },

  async submit() {
    if (this.data.submitting) return
    const realName = (this.data.realName || '').trim()
    const hospitalId = (this.data.hospitalId || '').trim() || 'demo-hospital'
    if (realName.length < 2) {
      wx.showToast({title: '请填写真实姓名', icon: 'none'})
      return
    }
    if (!this.data.training) {
      wx.showToast({title: '请先勾选培训确认', icon: 'none'})
      return
    }
    this.setData({submitting: true})
    try {
      await api.request('/volunteer/apply', 'POST', {
        hospital_id: hospitalId, real_name: realName, training_confirmed: true
      })
      wx.showToast({title: '已提交，等待审核', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '提交失败', icon: 'none'})
    } finally {
      this.setData({submitting: false})
    }
  },

  openWorkbench() { wx.navigateTo({url: '/pages/navigation-workbench/index'}) },
  openLogin() { wx.switchTab({url: '/pages/profile/index'}) }
})
