const nav = require('../../services/navigation')
const guard = require('../../utils/navigation-page')
const EMPTY = {route: {}, nodes: [], current: 0, node: null, percent: 0}
Page({
  data: {...EMPTY, id: '', busy: false, error: '',
    kindLabel: {start: '起点', turn: '转弯', landmark: '地标', elevator: '电梯', stairs: '楼梯', end: '终点'}},
  onLoad(query) {
    guard.bind(this, EMPTY)
    this._revision = Number(query.revision) || 0
    this.setData({id: query.id})
  },
  onShow() {
    clearInterval(this._timer)
    // Only validity is polled. Time never advances the user's position.
    this._timer = setInterval(() => this.checkStatus(), 15000)
    return this.showNode(this.data.current)
  },
  onHide() { clearInterval(this._timer); this._epoch += 1; this.setData({node: null, nodes: [], busy: false}) },
  onUnload() { clearInterval(this._timer); guard.dispose(this) },
  validate(route) {
    if (this._revision && route.revision !== this._revision) throw new Error('路线已更新，请返回路线详情重新确认起点')
    if (!route.nodes || !route.nodes.length) throw new Error('路线没有可用节点')
  },
  pause(message) {
    this.setData({route: {}, nodes: [], node: null, percent: 0,
      error: message + '。照片导览已暂停，请依据现场标识或联系工作人员。'})
  },
  async checkStatus() {
    if (this.data.busy || this._checking || !this.data.node) return
    this._checking = true
    const current = guard.begin(this)
    try {
      const route = await nav.route(this.data.id)
      if (current()) this.validate(route)
    } catch (e) { if (current()) this.pause(e.message) }
    finally { this._checking = false }
  },
  async showNode(index) {
    if (this.data.busy) return
    const current = guard.begin(this)
    this.setData({busy: true, error: '', node: null})
    try {
      const route = await nav.route(this.data.id)
      if (!current()) return
      this.validate(route)
      const i = Math.max(0, Math.min(index, route.nodes.length - 1))
      const node = {...route.nodes[i]}
      if (!node.media_id) throw new Error('这个节点缺少现场照片')
      node.tempPath = await nav.fetchMediaTempUrl(node.media_id)
      if (!current()) return
      this._revision = route.revision
      this.setData({route, nodes: route.nodes, current: i, node, percent: Math.round((i + 1) / route.nodes.length * 100)})
    } catch (e) { if (current()) this.pause(e.message) }
    finally { if (current()) this.setData({busy: false}) }
  },
  prev() { if (this.data.node) return this.showNode(this.data.current - 1) },
  next() { if (this.data.node) return this.showNode(this.data.current + 1) },
  retry() { return this.showNode(this.data.current) },
  preview() {
    if (this.data.node && this.data.node.tempPath) wx.previewImage({urls: [this.data.node.tempPath], current: this.data.node.tempPath})
  },
  photoFailed() { this._epoch += 1; this.pause('照片无法显示，请重新读取'); this.setData({busy: false}) },
  backToRoute() { wx.navigateBack() },
  async finish() {
    if (this.data.busy || !this.data.node || this.data.current !== this.data.nodes.length - 1) return
    await this.showNode(this.data.current)
    if (this.data.node && !this.data.error) {
      wx.showToast({title: '已结束照片导览', icon: 'success'})
      wx.navigateBack()
    }
  }
})

