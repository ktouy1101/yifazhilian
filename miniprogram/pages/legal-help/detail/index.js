const api = require('../../../services/api')
const {timeText} = require('../../../utils/format')

// 工单详情：患者看进度并补充；已核验志愿者可接单并回复。
Page({
  data: {loading: true, error: '', request: null, messages: [], canHelp: false, reply: '', sending: false},

  onLoad(query) { this.id = query && query.id },

  async onShow() { return this.load() },

  async load() {
    if (!this.id) { this.setData({loading: false, error: '缺少工单编号'}); return }
    try {
      const me = await api.request('/users/me')
      const caps = (me && me.capabilities) || {}
      const request = await api.request('/legal-help/requests/' + this.id)
      this.setData({
        loading: false, error: '', request,
        statusText: {open: '等待接单', claimed: '志愿者已接单', answered: '已回复', closed: '已结束'}[request.status] || request.status,
        timeText: timeText(request.updated_at),
        canHelp: !!caps.can_help_legal,
        viewerRole: request.viewer_role || 'owner',
        messages: (request.messages || []).map(item => ({...item, timeText: timeText(item.created_at)}))
      })
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  async claim() {
    try {
      await api.request('/legal-help/requests/' + this.id + '/claim', 'POST', {})
      wx.showToast({title: '已接单', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '接单失败', icon: 'none'})
    }
  },

  onReply(e) { this.setData({reply: e.detail.value}) },

  async send() {
    if (this.data.sending) return
    const text = (this.data.reply || '').trim()
    if (!text) return
    this.setData({sending: true})
    try {
      await api.request('/legal-help/requests/' + this.id + '/messages', 'POST', {text})
      this.setData({reply: ''})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '发送失败', icon: 'none'})
    } finally {
      this.setData({sending: false})
    }
  }
})
