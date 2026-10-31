const api = require('../../../services/api')
const {timeText} = require('../../../utils/format')

const STATUS = {open: '待接单', claimed: '已接单', answered: '已回复', closed: '已结束'}

Page({
  data: {loading: true, items: [], error: ''},

  async onShow() { return this.load() },

  async load() {
    this.setData({loading: true, error: ''})
    try {
      const result = await api.request('/admin/legal-help')
      const items = ((result && result.items) || []).map(item => ({
        ...item, statusText: STATUS[item.status] || item.status, timeText: timeText(item.updated_at)
      }))
      this.setData({items, loading: false})
    } catch (error) {
      this.setData({loading: false, items: [], error: error.message || '读取失败'})
    }
  },

  open(e) { wx.navigateTo({url: '/pages/legal-help/detail/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) }
})
