const api = require('../../../services/api')

Page({
  data: {loading: true, items: [], error: ''},

  async onShow() { return this.load() },

  async load() {
    this.setData({loading: true, error: ''})
    try {
      const result = await api.request('/admin/users')
      const items = ((result && result.items) || []).filter(item => !item.deleted).map(item => {
        const roles = item.roles || []
        return {...item,
          hasVolunteer: roles.indexOf('volunteer') >= 0,
          hasReviewer: roles.indexOf('reviewer') >= 0,
          rolesText: roles.length ? roles.join(' / ') : '无'}
      })
      this.setData({items, loading: false})
    } catch (error) {
      this.setData({loading: false, items: [], error: error.message || '读取失败'})
    }
  },

  async toggleRole(e) {
    const {id, role, action} = e.currentTarget.dataset
    try {
      await api.request('/admin/users/' + id + '/roles', 'POST', {role, action})
      wx.showToast({title: action === 'grant' ? '已授予' : '已撤销', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '操作失败', icon: 'none'})
    }
  },

  disableUser(e) {
    const {id, name} = e.currentTarget.dataset
    wx.showModal({
      title: '停用账号',
      content: '将注销「' + (name || id) + '」：立即下线、释放手机号，历史数据保留。确定吗？',
      success: async result => {
        if (!result.confirm) return
        try {
          await api.request('/admin/users/' + id, 'DELETE')
          wx.showToast({title: '已停用', icon: 'success'})
          await this.load()
        } catch (error) {
          wx.showToast({title: error.message || '操作失败', icon: 'none'})
        }
      }
    })
  }
})
