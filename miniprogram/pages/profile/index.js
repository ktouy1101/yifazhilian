const api = require('../../services/api')
const showError = require('../../utils/errors')
Page({
  data: {scopes: [
    {key: 'ai_medical', label: '健康问答', detail: '将当前演示提问用于本机检索和回复'},
    {key: 'ai_legal', label: '法律问答', detail: '将当前演示提问用于本机法条检索和回复'},
    {key: 'vitals', label: '体征演示', detail: '存储与展示合成设备读数'}
  ], status: '正在读取授权记录'},
  onShow() { this.refresh() },
  async refresh() {
    if (!getApp().globalData.token) {
      this.setData({status: '请先在首页进入演示', scopes: this.data.scopes.map(item => ({...item, statusLabel: '尚未登录'}))})
      return
    }
    try {
      const result = await api.request('/consents')
      const now = Date.now()
      this.setData({
        status: '已读取本机保存的授权记录',
        scopes: this.data.scopes.map(item => {
          const record = result.items.find(entry => entry.scope === item.key)
          let statusLabel = '未授权'
          if (record) statusLabel = record.revoked_at || !record.granted ? '已撤回' : (Date.parse(record.expires_at) > now ? '已授权' : '已到期')
          return {...item, statusLabel}
        })
      })
    } catch (error) {
      this.setData({status: '未能读取授权状态：' + error.message, scopes: this.data.scopes.map(item => ({...item, statusLabel: '状态未确认'}))})
    }
  },
  async grant(e) {
    const scope = e.currentTarget.dataset.scope
    const entry = this.data.scopes.find(item => item.key === scope)
    wx.showModal({title: '单独授权：' + entry.label, content: entry.detail + '。仅在这台电脑保存演示数据，重启后保留。授权有效期1小时，可随时撤回；撤回后停止后续使用，已有记录不会自动删除。禁止上传真实数据。',
      success: async result => { if (!result.confirm) return; try { await api.request('/consents', 'POST', {scope, granted: true}); await this.refresh() } catch (error) { showError(error) } }
    })
  },
  async revoke(e) { try { await api.request('/consents/' + e.currentTarget.dataset.scope, 'DELETE'); await this.refresh() } catch (error) { showError(error) } },
  logout() { getApp().globalData.token = null; wx.switchTab({url: '/pages/home/index'}) }
})
