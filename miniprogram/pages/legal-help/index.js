const api = require('../../services/api')
const {timeText} = require('../../utils/format')

// 法知模块里的真人服务窗口：
// 患者把问题说出来 → 进入队列 → 已核验的法律志愿者接单 → 同一窗口里对话。
Page({
  data: {loading: true, mode: 'patient', items: [], available: false, error: '',
         text: '', submitting: false},

  onShow() { return this.load() },

  async load() {
    this.setData({loading: true, error: ''})
    if (!api.identity.getToken()) { this.setData({loading: false, mode: 'guest'}); return }
    try {
      const me = await api.request('/users/me')
      const caps = (me && me.capabilities) || {}
      const mode = caps.can_help_legal ? 'volunteer' : 'patient'
      if (mode === 'volunteer') {
        const result = await api.request('/legal-help/queue')
        this.setData({loading: false, mode, available: true, items: decorate(result && result.items)})
      } else {
        const result = await api.request('/legal-help/requests')
        this.setData({loading: false, mode, available: !!(result && result.available),
                      items: decorate(result && result.items)})
      }
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  onText(e) { this.setData({text: e.detail.value}) },

  async submit() {
    if (this.data.submitting) return
    const text = (this.data.text || '').trim()
    if (text.length < 5) {
      wx.showToast({title: '先把问题说清楚（至少 5 个字）', icon: 'none'})
      return
    }
    this.setData({submitting: true})
    try {
      // 主题取前 14 个字，患者只填一个输入框。
      const created = await api.request('/legal-help/requests', 'POST',
        {topic: text.slice(0, 14), text})
      this.setData({text: ''})
      wx.navigateTo({url: '/pages/legal-help/detail/index?id=' + encodeURIComponent(created.id)})
    } catch (error) {
      wx.showToast({title: error.message || '提交失败', icon: 'none'})
    } finally {
      this.setData({submitting: false})
    }
  },

  open(e) { wx.navigateTo({url: '/pages/legal-help/detail/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },
  openLogin() { wx.switchTab({url: '/pages/profile/index'}) }
})

function decorate(items) {
  return ((items) || []).map(item => ({
    ...item, timeText: timeText(item.updated_at), statusText: statusLabel(item.status)
  }))
}

function statusLabel(status) {
  return {open: '等待接单', claimed: '志愿者已接单', answered: '已回复', closed: '已结束'}[status] || status
}
