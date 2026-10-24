const nav = require('../../services/navigation')
const guard = require('../../utils/navigation-page')
const EMPTY = {sub: {}, nodes: [], isReviewer: false, selfReview: false, walkthrough: false, note: '', disableReason: ''}
Page({
  data: {...EMPTY, id: '', readonly: false, version: 0, busy: false, error: '', fbNote: '', fbCategory: 'misdirected',
    statusLabel: {draft: '草稿', submitted: '待审核', changes_requested: '需补拍', published: '已发布', disabled: '已停用'},
    actionLabel: {edit: '修改草稿', photo: '上传照片', submit: '提交审核', approve: '独立审核并发布', request_changes: '退回补拍', disable: '停用', revise: '恢复历史版本并下线待复核'},
    kindLabel: {start: '起点', turn: '转弯', landmark: '地标', elevator: '电梯', stairs: '楼梯', end: '终点'},
    fbCategories: [{value: 'closed', label: '通道封闭'}, {value: 'misdirected', label: '方向不清'},
      {value: 'privacy', label: '隐私问题'}, {value: 'other', label: '其他'}]},
  onLoad(query) {
    guard.bind(this, EMPTY)
    this.setData({id: query.id, readonly: query.readonly === '1', version: Number(query.version) || 0})
  },
  onShow() { return this.load() },
  onUnload() { guard.dispose(this) },
  async load() {
    const current = guard.begin(this)
    this.setData({...EMPTY, busy: true, error: ''})
    try {
      const [me, sub] = await Promise.all([nav.me(), this.data.readonly ? nav.route(this.data.id) :
        this.data.version ? nav.version(this.data.id, this.data.version) : nav.getSubmission(this.data.id)])
      if (!current()) return
      const nodes = sub.nodes.map(n => ({...n, tempPath: '', photoError: ''}))
      this.setData({sub, nodes, selfReview: sub.collector_id === me.user.id,
        isReviewer: !this.data.version && !this.data.readonly && me.permissions.review && sub.collector_id !== me.user.id})
      await Promise.all(nodes.map(async n => {
        const media = (sub.media || []).find(m => m.node_key === n.node_key)
        try {
          const path = this.data.version ? await nav.fetchVersionPhoto(this.data.id, this.data.version, n.node_key) :
            (n.media_id || media) ? await nav.fetchMediaTempUrl(n.media_id || media.id) : ''
          if (!current()) return
          const i = this.data.nodes.findIndex(x => x.node_key === n.node_key)
          if (i >= 0) this.setData({['nodes[' + i + '].tempPath']: path, ['nodes[' + i + '].photoError']: path ? '' : '未上传照片'})
        } catch (e) {
          if (!current()) return
          const i = this.data.nodes.findIndex(x => x.node_key === n.node_key)
          if (i >= 0) this.setData({['nodes[' + i + '].photoError']: '读取失败，请刷新重试'})
        }
      }))
    } catch (e) { if (current()) this.setData({...EMPTY, error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  onNote(e) { this.setData({note: e.detail.value}) },
  onDisableReason(e) { this.setData({disableReason: e.detail.value}) },
  toggleWalkthrough() { this.setData({walkthrough: !this.data.walkthrough}) },
  async act(action) {
    if (this.data.busy || !this.data.isReviewer || this.data.version) return
    const note = this.data.note.trim()
    if (action !== 'disable' && !note) { this.setData({error: '请填写具体审核意见或实走记录。'}); return }
    if (action === 'approve' && (!this.data.walkthrough || this.data.nodes.some(n => !n.tempPath))) {
      this.setData({error: '请查看全部照片，并确认已独立实走。照片失败时请刷新重试。'}); return
    }
    if (action === 'disable' && !this.data.disableReason.trim()) { this.setData({error: '请填写停用原因。'}); return }
    const current = guard.begin(this)
    this.setData({busy: true, error: ''})
    try {
      const payload = action === 'disable' ? {revision: this.data.sub.revision, reason: this.data.disableReason.trim()} :
        {revision: this.data.sub.revision, decision: action, note, walkthrough_confirmed: action === 'approve'}
      const sub = action === 'disable' ? await nav.disable(this.data.id, payload) : await nav.review(this.data.id, payload)
      if (!current()) return
      this.setData({sub, walkthrough: false, note: '', disableReason: ''})
      wx.showToast({title: action === 'approve' ? '已发布' : action === 'disable' ? '已停用' : '已退回', icon: 'success'})
    } catch (e) { if (current()) this.setData({error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  approve() { return this.act('approve') },
  requestChanges() { return this.act('request_changes') },
  disable() { return this.act('disable') },
  openVersion(e) { wx.navigateTo({url: '/pages/route-review/index?id=' + encodeURIComponent(this.data.id) + '&version=' + e.currentTarget.dataset.revision}) },
  preview(e) {
    const path = this.data.nodes[Number(e.currentTarget.dataset.index)].tempPath
    if (path) wx.previewImage({urls: [path], current: path})
  },
  async startWalkthrough() {
    if (this.data.busy || !this.data.readonly || this.data.sub.status !== 'published') return
    const start = this.data.nodes[0]
    if (!start || !start.tempPath || !start.floor || !start.description) {
      this.setData({error: '起点照片或位置说明不完整，请刷新；仍不完整时请反馈给审核员。'}); return
    }
    const current = guard.begin(this)
    const revision = this.data.sub.revision
    this.setData({busy: true, error: ''})
    try {
      const answer = await new Promise(resolve => wx.showModal({title: '先确认你所在的位置',
        content: start.floor + ' · ' + start.description + '。请对照起点照片，确认已在此处；导览不会自动定位。',
        confirmText: '我在起点', cancelText: '还没到达', success: resolve, fail: () => resolve({confirm: false})}))
      if (!current() || !answer.confirm) return
      const route = await nav.route(this.data.id)
      if (!current()) return
      if (route.revision !== revision) {
        this.setData({sub: {}, nodes: [], error: '路线已更新，请刷新后重新确认起点。'}); return
      }
      wx.navigateTo({url: '/pages/photo-walkthrough/index?id=' + encodeURIComponent(this.data.id) + '&revision=' + route.revision})
    } catch (e) { if (current()) this.setData({sub: {}, nodes: [], error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  pickCategory(e) { this.setData({fbCategory: e.currentTarget.dataset.value}) },
  onFbNote(e) { this.setData({fbNote: e.detail.value}) },
  async submitFeedback() {
    if (this.data.busy || !this.data.readonly || this.data.sub.status !== 'published') return
    const current = guard.begin(this)
    const signature = JSON.stringify([this.data.fbCategory, this.data.fbNote.trim()])
    if (!this._feedback || this._feedback.signature !== signature) this._feedback = {signature, id: 'fb-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8)}
    this.setData({busy: true, error: ''})
    try {
      await nav.feedback(this.data.id, {request_id: this._feedback.id, category: this.data.fbCategory, note: this.data.fbNote.trim() || null})
      if (!current()) return
      this._feedback = null
      this.setData({fbNote: ''})
      wx.showToast({title: '反馈已送至审核工作台', icon: 'none'})
    } catch (e) { if (current()) this.setData({error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  }
})

