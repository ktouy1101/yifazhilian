const api = require('../../../services/api')
const {timeText} = require('../../../utils/format')

// 志愿者申请：状态、审核意见与申请表单。
Page({
  data: {
    loading: true, status: 'none', profile: null, error: '',
    realName: '', hospitalId: 'demo-hospital', training: false, submitting: false
  },

  onShow() { return this.load() },

  async load() {
    if (!api.identity.getToken()) { this.setData({loading: false, status: 'guest'}); return }
    try {
      const result = await api.request('/volunteer/me')
      const profile = result.profile || null
      this.setData({
        loading: false, profile, status: (profile && profile.status) || 'none',
        realName: (profile && profile.real_name) || this.data.realName,
        hospitalId: (profile && profile.hospital_id) || this.data.hospitalId,
        error: '',
        reviewedText: profile && profile.reviewed_at ? timeText(profile.reviewed_at) : ''
      })
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  onName(e) { this.setData({realName: e.detail.value}) },
  onHospital(e) { this.setData({hospitalId: e.detail.value}) },
  onTraining(e) { this.setData({training: e.detail.value}) },

  async submit() {
    if (this.data.submitting) return
    const realName = (this.data.realName || '').trim()
    if (realName.length < 2) { wx.showToast({title: '请填写真实姓名', icon: 'none'}); return }
    if (!this.data.training) { wx.showToast({title: '请先勾选培训确认', icon: 'none'}); return }
    this.setData({submitting: true})
    try {
      await api.request('/volunteer/apply', 'POST', {
        hospital_id: (this.data.hospitalId || '').trim() || 'demo-hospital',
        real_name: realName, training_confirmed: true
      })
      wx.showToast({title: '已提交，等待审核', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '提交失败', icon: 'none'})
    } finally {
      this.setData({submitting: false})
    }
  },

  openLogin() { wx.switchTab({url: '/pages/profile/index'}) }
})
