const api = require('../../../services/api')
const config = require('../../../config/index')
const identity = require('../../../services/identity')
const images = require('../../../services/image_upload')
const {timeText} = require('../../../utils/format')

const KIND = {lawyer_license: '律师执业证', legal_aid: '法律援助工作证'}
const STATUS = {pending: '待核验', approved: '已通过', rejected: '已拒绝'}

// 法律帮扶：上传执业证（私有存储），核验通过后才能接工单。
Page({
  data: {loading: true, caps: {}, credentials: [], uploading: false, error: ''},

  onShow() { return this.load() },

  async load() {
    if (!api.identity.getToken()) { this.setData({loading: false}); return }
    try {
      const me = await api.request('/volunteer/me')
      const credentials = ((await api.request('/volunteer/credentials')).items || []).map(item => ({
        ...item, kindText: KIND[item.kind] || item.kind,
        statusText: STATUS[item.status] || item.status,
        timeText: timeText(item.created_at)
      }))
      this.setData({loading: false, caps: me.capabilities || {}, credentials, error: ''})
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  uploadCredential() {
    if (this.data.uploading) return
    wx.chooseImage({
      count: 1, sizeType: ['compressed'], sourceType: ['album', 'camera'],
      success: result => this.pushCredential(result.tempFilePaths[0])
    })
  },

  async pushCredential(filePath) {
    if (images.enabled()) {
      // 云托管：无 multipart，压缩后转 base64
      this.setData({uploading: true})
      try {
        const data = await images.toDataUrl(filePath)
        await api.request('/volunteer/credentials-base64', 'POST', {kind: 'lawyer_license', data})
        wx.showToast({title: '已提交，等待核验', icon: 'success'})
        await this.load()
      } catch (error) {
        wx.showToast({title: error.message || '上传失败', icon: 'none'})
      } finally {
        this.setData({uploading: false})
      }
      return
    }
    this.setData({uploading: true})
    wx.uploadFile({
      url: config.baseURL + '/volunteer/credentials',
      filePath, name: 'file', formData: {kind: 'lawyer_license'},
      header: {Authorization: 'Bearer ' + (identity.getToken() || '')},
      success: async response => {
        let body = {}
        try { body = JSON.parse(response.data || '{}') } catch (e) { body = {} }
        if (response.statusCode === 201) {
          wx.showToast({title: '已提交，等待核验', icon: 'success'})
          await this.load()
        } else {
          wx.showToast({title: body.detail || '上传失败', icon: 'none'})
        }
      },
      fail: () => wx.showToast({title: '上传失败，请重试', icon: 'none'}),
      complete: () => this.setData({uploading: false})
    })
  },

  openLegalHelp() { wx.navigateTo({url: '/pages/legal-help/index'}) }
})
