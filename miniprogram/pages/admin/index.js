const api = require('../../services/api')

// 审核员/管理员入口。页面只负责展示待办；能不能进来由服务端 capabilities 决定，
// 隐藏入口不算鉴权，真正的拒绝发生在每个 /admin 接口上。
Page({
  data: {
    loading: true,
    denied: false,
    me: null,
    caps: {},
    volunteers: [],
    volunteersError: '',
    pending: [
      {key: 'routes', title: '路线审核', detail: '采集提交的路线在此审核、发布或退回', stage: 'P3'},
      {key: 'credentials', title: '律师凭证核验', detail: '人工核对执业证，通过后开放法律帮扶', stage: 'P4'},
      {key: 'feedback', title: '导航反馈', detail: '处理志愿者采集与患者反馈', stage: 'P3'}
    ]
  },

  async onLoad() {
    try {
      const me = await api.request('/users/me')
      const caps = (me && me.capabilities) || {}
      if (!caps.is_reviewer) {
        this.setData({loading: false, denied: true})
        wx.showModal({
          title: '没有审核员权限',
          content: '当前账号不是审核员。管理员手机号由服务端配置指定，请联系管理员。',
          showCancel: false,
          success: () => wx.navigateBack({fail: () => wx.switchTab({url: '/pages/home/index'})})
        })
        return
      }
      this.setData({loading: false, me, caps})
      await this.loadVolunteers()
    } catch (error) {
      this.setData({loading: false, denied: true})
      wx.showToast({title: '读取身份失败：' + (error.message || '请稍后重试'), icon: 'none'})
    }
  },

  async loadVolunteers() {
    try {
      const result = await api.request('/admin/volunteers?status=pending')
      this.setData({volunteers: (result && result.items) || []})
    } catch (error) {
      this.setData({volunteers: [], volunteersError: error.message || '读取申请失败'})
    }
  },

  async reviewVolunteer(event) {
    const {id, decision} = event.currentTarget.dataset
    if (this.reviewing) return
    this.reviewing = true
    try {
      await api.request('/admin/volunteers/' + id + '/review', 'POST', {decision, note: ''})
      wx.showToast({title: decision === 'approve' ? '已通过' : '已拒绝', icon: 'success'})
      await this.loadVolunteers()
    } catch (error) {
      wx.showToast({title: error.message || '操作失败', icon: 'none'})
    } finally {
      this.reviewing = false
    }
  },

  back() {
    wx.navigateBack({fail: () => wx.switchTab({url: '/pages/home/index'})})
  }
})
