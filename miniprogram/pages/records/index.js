const records = require('../../services/records')
const api = require('../../services/api')
const identity = require('../../services/identity')
const guard = require('../../utils/navigation-page')

const reset = {items: [], visible: [], notes: [], expandedNote: '', noteError: '', noteBusy: false, active: false, error: '', query: '', filter: 'all',
  checklist: null, checklistScenario: 'inpatient', checklistError: '', checklistBusy: false}
Page({
  data: {...reset, loading: false, busy: false, loggedIn: false},
  onLoad() { guard.bind(this, reset) },
  onShow() { return this.reload() },
  onHide() { clearTimeout(this._expiry) },
  onUnload() { clearTimeout(this._expiry); guard.dispose(this); records.clearTemp() },
  login() { wx.navigateTo({url: '/pages/login/index'}) },
  async reload() {
    const current = guard.begin(this)
    this.setData({loading: true, error: '', loggedIn: !!identity.getToken()})
    if (!identity.getToken()) { this.setData({...reset, loading: false}); return }
    try {
      const access = await records.access()
      if (!current()) return
      this._policy = access.policy
      this._expiresAt = access.expiresAt
      this.setData({active: access.active})
      if (!access.active) { this.setData({items: [], visible: [], notes: [], expandedNote: '', checklist: null, checklistError: ''}); return }
      this.armExpiry(current)
      const result = await records.list()
      if (!current()) return
      this.setData({items: result.items.map(item => ({...item, statusLabel: records.statusLabel(item.status)}))})
      this.filterItems()
      await this.loadNotes(current)
      await this.loadChecklist(current)
    } catch (error) {
      if (current()) this.setData({items: [], visible: [], notes: [], checklist: null, error: error.message, active: false})
    } finally { if (current()) this.setData({loading: false}) }
  },
  armExpiry(current) {
    clearTimeout(this._expiry)
    const remaining = this._expiresAt - Date.now()
    if (remaining <= 0) { this.expire(); return }
    this._expiry = setTimeout(() => {
      if (!current()) return
      if (Date.now() < this._expiresAt) { this.armExpiry(current); return }
      this.expire()
    }, Math.min(remaining, 2147483647))
  },
  expire() {
    records.clearTemp()
    this.setData({...reset, error: '授权已到期，请重新授权'})
  },
  async loadChecklist(current) {
    this.setData({checklistBusy: true, checklistError: ''})
    try {
      const result = await records.checklist(this.data.checklistScenario)
      if (!current || current()) this.setData({checklist: result})
    } catch (error) {
      if (!current || current()) this.setData({checklist: null, checklistError: error.message || '完整性检查失败'})
    } finally { if (!current || current()) this.setData({checklistBusy: false}) }
  },
  changeChecklistScenario(e) {
    if (!this.data.active || this.data.checklistBusy) return
    const scenario = e.currentTarget.dataset.scenario
    if (!scenario || scenario === this.data.checklistScenario) return
    this.setData({checklistScenario: scenario})
    this.loadChecklist(guard.begin(this))
  },
  reloadChecklist() {
    if (!this.data.active || this.data.checklistBusy) return
    this.loadChecklist(guard.begin(this))
  },
  async loadNotes(current) {
    try {
      const result = await api.listRecords()
      if (current && !current()) return
      this.setData({notes: result.items || [], noteError: ''})
    } catch (error) {
      if (!current || current()) this.setData({notes: [], noteError: error.message || '病历笔记读取失败'})
    }
  },
  async addNote() {
    if (!this.data.active || this.data.noteBusy) return
    const title = await new Promise(resolve => wx.showModal({
      title: '病历笔记标题', editable: true, placeholderText: '如：心内科复诊',
      success: result => resolve(result.confirm ? result.content : null), fail: () => resolve(null)
    }))
    if (!title) return
    const summary = await new Promise(resolve => wx.showModal({
      title: '备注（可选）', editable: true, placeholderText: '记录要点或想问医生的问题',
      success: result => resolve(result.confirm ? result.content : null), fail: () => resolve(null)
    }))
    const current = guard.begin(this)
    this.setData({noteBusy: true, noteError: ''})
    try {
      await api.createRecord({title, summary: summary || null, record_date: new Date().toISOString().slice(0, 10)})
      if (!current()) return
      await this.loadNotes(current)
      if (current()) wx.showToast({title: '已保存', icon: 'success'})
    } catch (error) {
      if (current()) this.setData({noteError: error.message || '保存失败，请重试'})
    } finally { if (current()) this.setData({noteBusy: false}) }
  },
  toggleNote(e) {
    const id = e.currentTarget.dataset.id
    this.setData({expandedNote: this.data.expandedNote === id ? '' : id})
  },
  async authorize() {
    if (this.data.busy || !this._policy) return
    this.setData({busy: true})
    try { if (await records.grant(this._policy)) await this.reload() }
    catch (error) { this.setData({error: error.message}) }
    finally { this.setData({busy: false}) }
  },
  filterItems() {
    const {items, query, filter} = this.data
    const visible = items.filter(item => (filter === 'all' || (filter === 'archived' ? item.archived_version > 0 : item.status !== 'archived'))
      && [item.title, item.institution, item.visit, item.record_date].join(' ').includes(query.trim()))
    this.setData({visible})
  },
  search(e) { this.setData({query: e.detail.value}); this.filterItems() },
  selectFilter(e) { this.setData({filter: e.currentTarget.dataset.value}); this.filterItems() },
  add(e) {
    if (!this.data.active) return
    wx.navigateTo({url: '/pages/record-review/index?source=' + e.currentTarget.dataset.source})
  },
  open(e) { wx.navigateTo({url: '/pages/record-review/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) }
})
