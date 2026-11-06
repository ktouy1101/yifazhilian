const api = require('../../../services/api')
const config = require('../../../config/index')
const {cloudRun} = require('../../../config/index')
const identity = require('../../../services/identity')
const {timeText} = require('../../../utils/format')

const TABS = [
  {key: 'todo', label: '待办', icon: '/assets/icons/check-muted.png', activeIcon: '/assets/icons/check-teal.png'},
  {key: 'queues', label: '监督', icon: '/assets/icons/shield-muted.png', activeIcon: '/assets/icons/shield-teal.png'},
  {key: 'people', label: '用户', icon: '/assets/icons/user-muted.png', activeIcon: '/assets/icons/user-teal.png'},
  {key: 'mine', label: '我的', icon: '/assets/icons/settings-muted.png', activeIcon: '/assets/icons/settings-teal.png'}
]
const USER_FILTERS = [
  {key: 'all', label: '全部'},
  {key: 'patient', label: '患者'},
  {key: 'volunteer', label: '志愿者'},
  {key: 'reviewer', label: '审核员'},
  {key: 'demo', label: '演示'}
]

// 审核员专用外壳：待办优先的管理界面，与患者端、志愿者端都不同。
Page({
  data: {tab: 'todo', tabs: TABS, filters: USER_FILTERS, userFilter: 'all', userList: [],
         loading: true, error: '',
         overview: {}, volunteers: [], credentials: [], helpItems: [], users: []},

  onShow() { return this.load() },

  switchTab(e) { this.setData({tab: e.detail.key}) },

  async load() {
    if (!api.identity.getToken()) { this.setData({loading: false, error: '请先登录'}); return }
    try {
      const [overview, volunteers, credentials, helpItems, users] = await Promise.all([
        api.request('/admin/overview'),
        api.request('/admin/volunteers?status=pending').catch(() => ({items: []})),
        api.request('/admin/credentials?status=pending').catch(() => ({items: []})),
        api.request('/admin/legal-help').catch(() => ({items: []})),
        api.request('/admin/users').catch(() => ({items: []}))
      ])
      this.setData({
        loading: false, error: '', overview,
        volunteers: volunteers.items || [],
        credentials: (credentials.items || []).map(item => ({...item, kindText: item.kind === 'lawyer_license' ? '律师执业证' : '法律援助证', timeText: timeText(item.created_at)})),
        helpItems: (helpItems.items || []).map(item => ({...item, timeText: timeText(item.updated_at)})),
        users: (users.items || []).filter(item => !item.deleted)
      })
      this.applyUserFilter(this.data.userFilter)
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  // 用户按类型分开管理：真实患者 / 志愿者 / 审核员 / 演示账号各看各的。
  applyUserFilter(key) {
    const all = this.data.users || []
    const roles = item => item.roles || []
    const decorate = item => {
      const isReviewer = roles(item).includes('reviewer')
      const isVolunteer = roles(item).includes('volunteer')
      return {...item,
        isReviewer, isVolunteer, isDemo: !!item.synthetic,
        roleTag: isReviewer ? '审核员' : isVolunteer ? '志愿者' : '患者',
        initial: isReviewer ? '审' : isVolunteer ? '志' : '患',
        phoneText: item.phone || '无手机号'}
    }
    const real = all.filter(item => !item.synthetic).map(decorate)
    const demo = all.filter(item => item.synthetic).map(decorate)
    let list
    if (key === 'demo') list = demo
    else if (key === 'patient') list = real.filter(item => !item.isVolunteer && !item.isReviewer)
    else if (key === 'volunteer') list = real.filter(item => item.isVolunteer)
    else if (key === 'reviewer') list = real.filter(item => item.isReviewer)
    else list = real
    this.setData({
      userFilter: key,
      userList: list,
      userCounts: {
        all: real.length,
        patient: real.filter(item => !item.isVolunteer && !item.isReviewer).length,
        volunteer: real.filter(item => item.isVolunteer).length,
        reviewer: real.filter(item => item.isReviewer).length,
        demo: demo.length
      }
    })
  },

  setUserFilter(e) { this.applyUserFilter(e.currentTarget.dataset.key) },

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
  },

  async reviewVolunteer(e) {
    const {id, decision} = e.currentTarget.dataset
    try {
      await api.request('/admin/volunteers/' + id + '/review', 'POST', {decision, note: ''})
      wx.showToast({title: decision === 'approve' ? '已通过' : '已拒绝', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '操作失败', icon: 'none'})
    }
  },

  async viewCredential(e) {
    const id = e.currentTarget.dataset.id
    if (cloudRun.enabled && cloudRun.env) {
      try {
        const res = await api.request('/admin/credentials/' + id + '/image-base64')
        wx.previewImage({urls: [res.data]})
      } catch (error) {
        wx.showToast({title: error.message || '读取图片失败', icon: 'none'})
      }
      return
    }
    wx.downloadFile({
      url: config.baseURL + '/admin/credentials/' + id + '/image',
      header: {Authorization: 'Bearer ' + (identity.getToken() || '')},
      success: result => {
        if (result.statusCode !== 200) { wx.showToast({title: '读取图片失败', icon: 'none'}); return }
        wx.previewImage({urls: [result.tempFilePath]})
      },
      fail: () => wx.showToast({title: '下载失败', icon: 'none'})
    })
  },

  async reviewCredential(e) {
    const {id, decision} = e.currentTarget.dataset
    try {
      await api.request('/admin/credentials/' + id + '/review', 'POST', {decision, note: ''})
      wx.showToast({title: decision === 'approve' ? '已通过' : '已拒绝', icon: 'success'})
      await this.load()
    } catch (error) {
      wx.showToast({title: error.message || '操作失败', icon: 'none'})
    }
  },

  openRoutes() { wx.navigateTo({url: '/pages/admin/routes/index'}) },
  openFeedback() { wx.navigateTo({url: '/pages/admin/feedback/index'}) },
  openAudit() { wx.navigateTo({url: '/pages/admin/audit/index'}) },
  openHelp(e) { wx.navigateTo({url: '/pages/legal-help/detail/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },

  logout() {
    wx.showModal({
      title: '退出登录', content: '退出后回到未登录状态。',
      success: async result => {
        if (!result.confirm) return
        try { await api.logout() } catch (e) { /* 忽略 */ }
        wx.reLaunch({url: '/pages/home/index'})
      }
    })
  }
})
