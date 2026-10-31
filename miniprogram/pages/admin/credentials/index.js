const api = require('../../../services/api')
const config = require('../../../config/index')
const identity = require('../../../services/identity')
const {timeText} = require('../../../utils/format')

const KIND = {lawyer_license: '律师执业证', legal_aid: '法律援助工作证'}

Page({
  data: {loading: true, items: [], error: '', busy: false},

  async onShow() { return this.load() },

  async load() {
    this.setData({loading: true, error: ''})
    try {
      const result = await api.request('/admin/credentials?status=pending')
      const items = ((result && result.items) || []).map(item => ({
        ...item, kindText: KIND[item.kind] || item.kind, timeText: timeText(item.created_at)
      }))
      this.setData({items, loading: false})
    } catch (error) {
      this.setData({loading: false, items: [], error: error.message || '读取失败'})
    }
  },

  // 凭证是私有图片，必须带 token 下载后再预览，不能直接拼 URL。
  view(e) {
    const id = e.currentTarget.dataset.id
    wx.showLoading({title: '加载中'})
    wx.downloadFile({
      url: config.baseURL + '/admin/credentials/' + id + '/image',
      header: {Authorization: 'Bearer ' + (identity.getToken() || '')},
      success: result => {
        wx.hideLoading()
        if (result.statusCode !== 200) {
          wx.showToast({title: '读取图片失败', icon: 'none'}); return
        }
        wx.previewImage({urls: [result.tempFilePath]})
      },
      fail: () => { wx.hideLoading(); wx.showToast({title: '下载失败', icon: 'none'}) }
    })
  },

  async review(e) {
    if (this.data.busy) return
    const {id, decision} = e.currentTarget.dataset
    this.setData({busy: true})
    try {
      await api.request('/admin/credentials/' + id + '/review', 'POST', {decision, note: ''})
      wx.showToast({title: decision === 'approve' ? '已通过' : '已拒绝', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '操作失败', icon: 'none'})
    } finally {
      this.setData({busy: false})
    }
  }
})
