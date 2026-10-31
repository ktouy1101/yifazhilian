const api = require('../../../services/api')
const {timeText} = require('../../../utils/format')

Page({
  data: {loading: true, items: [], error: '', busy: false},

  async onShow() { return this.load() },

  async load() {
    this.setData({loading: true, error: ''})
    try {
      const result = await api.request('/admin/volunteers?status=pending')
      const items = ((result && result.items) || []).map(item => ({
        ...item, timeText: timeText(item.updated_at)
      }))
      this.setData({items, loading: false})
    } catch (error) {
      this.setData({loading: false, items: [], error: error.message || '读取失败'})
    }
  },

  async review(e) {
    if (this.data.busy) return
    const {id, decision} = e.currentTarget.dataset
    this.setData({busy: true})
    try {
      await api.request('/admin/volunteers/' + id + '/review', 'POST', {decision, note: ''})
      wx.showToast({title: decision === 'approve' ? '已通过' : '已拒绝', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '操作失败', icon: 'none'})
    } finally {
      this.setData({busy: false})
    }
  }
})
