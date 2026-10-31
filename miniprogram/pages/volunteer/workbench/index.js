const api = require('../../../services/api')
const nav = require('../../../services/navigation')
const {timeText} = require('../../../utils/format')

const ALL_TABS = {
  home: {key: 'home', label: '工作台', icon: '⌂'},
  collect: {key: 'collect', label: '采集', icon: '◉'},
  legal: {key: 'legal', label: '法律', icon: '§'},
  mine: {key: 'mine', label: '我的', icon: '☺'}
}
const STATUS = {draft: '草稿', submitted: '待审核', changes_requested: '需补拍', published: '已发布', disabled: '已停用'}
const HELP = {open: '等待接单', claimed: '已接单', answered: '已回复', closed: '已结束'}

// 志愿者外壳。tab 按能力生成：只做采集的不显示法律，只做法律的不显示采集。
// 工作台只放"今天要做什么"，具体列表在采集 / 法律两个 tab 里，避免重复入口。
Page({
  data: {
    tab: 'home', tabs: [],
    loading: true, error: '',
    me: null, caps: {},
    tasks: [], resubmit: [], drafting: [], submitted: [],
    legalOpen: [], legalMine: [],
    counts: {resubmit: 0, tasks: 0, legal: 0, submitted: 0},
    statusLabel: STATUS
  },

  onShow() { return this.load() },

  switchTab(e) { this.setData({tab: e.detail.key}) },

  async load() {
    if (!api.identity.getToken()) { this.setData({loading: false, error: '请先登录'}); return }
    try {
      const me = await api.request('/users/me')
      const caps = (me && me.capabilities) || {}
      const tabs = [ALL_TABS.home]
      if (caps.can_collect) tabs.push(ALL_TABS.collect)
      if (caps.can_help_legal) tabs.push(ALL_TABS.legal)
      tabs.push(ALL_TABS.mine)

      const jobs = []
      if (caps.can_collect) {
        jobs.push(nav.tasks().then(r => this.setData({tasks: r.items || []})).catch(() => {}))
        jobs.push(nav.listSubmissions('mine').then(r => {
          const items = r.items || []
          this.setData({
            resubmit: items.filter(i => i.status === 'changes_requested'),
            drafting: items.filter(i => i.status === 'draft'),
            submitted: items.filter(i => i.status === 'submitted' || i.status === 'published')
          })
        }).catch(() => {}))
      }
      if (caps.can_help_legal) {
        jobs.push(api.request('/legal-help/queue').then(r => {
          const mine = (me && me.id) || ''
          const items = (r.items || []).map(item => ({...item,
            statusText: HELP[item.status] || item.status, timeText: timeText(item.updated_at)}))
          this.setData({
            legalOpen: items.filter(i => i.status === 'open'),
            legalMine: items.filter(i => i.volunteer_id === mine)
          })
        }).catch(() => {}))
      }
      await Promise.all(jobs)
      this.setData({
        loading: false, me, caps, tabs, error: '',
        counts: {
          resubmit: this.data.resubmit.length,
          tasks: this.data.tasks.filter(t => t.collectable && !t.mine_claimed).length,
          legal: this.data.legalOpen.length,
          submitted: this.data.submitted.length
        }
      })
    } catch (error) {
      this.setData({loading: false, error: error.message || '读取失败'})
    }
  },

  goCollect() { this.setData({tab: 'collect'}) },
  goLegal() { this.setData({tab: 'legal'}) },

  async claim(e) {
    const id = e.currentTarget.dataset.id
    try {
      await nav.claimTask(id)
      const task = this.data.tasks.find(t => t.id === id) || {}
      const sub = await nav.createSubmission({task_id: id, title: task.title || '导航任务', request_id: 'task-' + id})
      wx.navigateTo({url: '/pages/route-capture/index?id=' + encodeURIComponent(sub.id)})
    } catch (error) {
      wx.showToast({title: error.message || '领取失败', icon: 'none'})
    }
  },

  openCapture(e) { wx.navigateTo({url: '/pages/route-capture/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },
  openHelp(e) { wx.navigateTo({url: '/pages/legal-help/detail/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },
  openApplication() { wx.navigateTo({url: '/pages/volunteer/application/index'}) },
  openCredential() { wx.navigateTo({url: '/pages/volunteer/legal/index'}) },

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
