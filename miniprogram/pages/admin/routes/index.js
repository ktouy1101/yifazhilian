const api = require('../../../services/api')
const {timeText} = require('../../../utils/format')

const STATUS = {draft: '草稿', submitted: '待审核', changes_requested: '需补拍', published: '已发布', disabled: '已停用'}

Page({
  data: {loading: true, items: [], error: ''},

  async onShow() { return this.load() },

  async load() {
    this.setData({loading: true, error: ''})
    try {
      const result = await api.request('/navigation/submissions?scope=review')
      const items = ((result && result.items) || []).map(item => ({
        ...item,
        statusText: STATUS[item.status] || item.status,
        timeText: timeText(item.updated_at)
      }))
      this.setData({items, loading: false})
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  open(e) {
    wx.navigateTo({url: '/pages/route-review/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)})
  }
})
