const api = require('../../../services/api')
const {timeText, auditAction} = require('../../../utils/format')

Page({
  data: {loading: true, items: [], error: ''},

  async onShow() { return this.load() },

  async load() {
    this.setData({loading: true, error: ''})
    try {
      const result = await api.request('/admin/audit?limit=50')
      const items = ((result && result.items) || []).map(item => ({
        ...item,
        actionText: auditAction(item.action),
        timeText: timeText(item.created_at)
      }))
      this.setData({items, loading: false})
    } catch (error) {
      this.setData({loading: false, items: [], error: error.message || '读取失败'})
    }
  }
})
