const nav = require('../../services/navigation')
const api = require('../../services/api')
const guard = require('../../utils/navigation-page')
const STATUS = {draft: '草稿', submitted: '待审核', changes_requested: '需补拍', published: '已发布', disabled: '已停用'}
const EMPTY = {me: {}, perms: {}, tasks: [], routes: [], mine: [], queue: [], roleLabel: ''}

Page({
  data: {...EMPTY, statusLabel: STATUS, busy: false, loading: false, error: ''},

  onLoad() { guard.bind(this, {...EMPTY}) },
  onShow() { return this.reload() },
  onUnload() { guard.dispose(this) },

  async reload() {
    const current = guard.begin(this)
    this.setData({...EMPTY, error: '', loading: true, busy: false})
    if (!api.identity.getToken()) { this.setData({loading: false}); return false }
    try {
      const me = await nav.me()
      if (!current()) return false
      const perms = me.permissions
      const [routes, tasks, mine, queue] = await Promise.all([
        nav.routes(), perms.collect ? nav.tasks() : {items: []},
        perms.collect ? nav.listSubmissions('mine') : {items: []},
        perms.review ? nav.listSubmissions('review') : {items: []}
      ])
      if (!current()) return false
      this.setData({
        me, perms, routes: routes.items, tasks: tasks.items, mine: mine.items, queue: queue.items,
        roleLabel: perms.review ? '审核员' : perms.collect ? '采集员' : '体验员'
      })
      return true
    } catch (error) {
      if (current()) this.setData({error: error.message})
      return false
    } finally {
      if (current()) this.setData({loading: false})
    }
  },

  goNavigation() { wx.switchTab({url: '/pages/navigation/index'}) },
  openLogin() { wx.navigateTo({url: '/pages/login/index'}) },

  async claim(e) {
    if (this.data.busy) return
    const task = this.data.tasks.find(t => t.id === e.currentTarget.dataset.id)
    if (!task) return
    const current = guard.begin(this)
    this.setData({busy: true, error: ''})
    try {
      await nav.claimTask(task.id)
      if (!current()) return
      const sub = await nav.createSubmission({task_id: task.id, title: task.title, request_id: 'task-' + task.id})
      if (!current()) return
      wx.navigateTo({url: '/pages/route-capture/index?id=' + encodeURIComponent(sub.id)})
    } catch (error) {
      if (current()) this.setData({error: error.message})
    } finally {
      if (current()) this.setData({busy: false})
    }
  },

  openCapture(e) { wx.navigateTo({url: '/pages/route-capture/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },
  openReview(e) { wx.navigateTo({url: '/pages/route-review/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },
  openRoute(e) { wx.navigateTo({url: '/pages/route-review/index?readonly=1&id=' + encodeURIComponent(e.currentTarget.dataset.id)}) }
})
