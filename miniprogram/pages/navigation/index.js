const nav = require('../../services/navigation')
const api = require('../../services/api')
const identity = require('../../services/identity')
const guard = require('../../utils/navigation-page')
const {canEnterWorkbench} = require('../../utils/capabilities')
const EMPTY = {routes: [], filtered: [], state: 'idle'}

Page({
  data: {...EMPTY, query: '', busy: false, error: ''},
  onLoad() { guard.bind(this, EMPTY) },
  onShow() { return this.reload() },
  onHide() { this._epoch += 1; this.setData({...EMPTY, busy: false}) },
  onUnload() { guard.dispose(this) },
  async onPullDownRefresh() {
    try { await this.reload() } finally { wx.stopPullDownRefresh() }
  },
  async reload() {
    const current = guard.begin(this)
    this.setData({...EMPTY, state: 'loading', busy: true, error: ''})
    if (!identity.getToken()) { this.setData({state: 'guest', busy: false, canWorkbench: false}); return }
    try {
      const result = await nav.routes()
      if (!current()) return
      if (!Array.isArray(result.items)) throw new Error('路线数据读取失败，请重试')
      const routes = result.items.filter(r => r.status === 'published').map(r => ({
        ...r, start: r.start || {}, end: r.end || {},
        floorsText: (r.floors || []).join(' / '),
        verifiedDate: r.verified_at ? r.verified_at.slice(0, 10) : ''
      }))
      // 采集/审核入口只给有权限的人看；判定仍以服务端 capabilities 为准。
      let canWorkbench = false
      try {
        const me = await api.getMe()
        canWorkbench = canEnterWorkbench(me && me.capabilities)
      } catch (e) { canWorkbench = false }
      if (!current()) return
      this.setData({routes, state: 'ready', canWorkbench})
      this.filterRoutes()
    } catch (e) {
      if (current()) this.setData({...EMPTY, state: 'error', error: e.message})
    } finally { if (current()) this.setData({busy: false}) }
  },
  onSearch(e) { this.setData({query: e.detail.value}); this.filterRoutes() },
  clearSearch() { this.setData({query: ''}); this.filterRoutes() },
  filterRoutes() {
    const words = this.data.query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    this.setData({filtered: this.data.routes.filter(r => {
      const text = [r.title, r.start.description, r.start.floor, r.end.description, r.end.floor, r.floorsText].join(' ').toLowerCase()
      return words.every(word => text.includes(word))
    })})
  },
  openRoute(e) {
    if (this.data.state !== 'ready') return
    const route = this.data.filtered.find(r => r.id === e.currentTarget.dataset.id)
    if (route) wx.navigateTo({url: '/pages/route-review/index?readonly=1&id=' + encodeURIComponent(route.id)})
  },
  openLogin() { wx.switchTab({url: '/pages/profile/index'}) },
  openWorkbench() { wx.navigateTo({url: '/pages/navigation-workbench/index'}) }
})
