const health = require('../../services/health')
const identity = require('../../services/identity')
const view = require('../../utils/health-view')
const kinds = ['heart_rate', 'spo2', 'blood_pressure', 'symptom']
const statuses = ['active', 'paused', 'ended']
const doseStatuses = ['taken', 'skipped', 'pending', 'postponed']
const empty = () => ({entries: [], plans: [], doses: [], followups: [], latest: [], entryCount: 0,
  summary: {taken: 0, skipped: 0, pending: 0}, chart: {points: [], count: 0},
  visit: null, visitDays: 7, visitSections: [], visitText: '', visitBusy: false, visitError: '',
  latestRecord: null, latestSymptom: null, nextFollowup: null, hasMeasurements: false, recordCount: 0,
  careAlert: null, accessUntil: ''})
const accessDate = value => {
  const date = new Date(value)
  return isNaN(date.getTime()) ? '' : (date.getMonth() + 1) + '月' + date.getDate() + '日'
}
const confirm = (title, content) => new Promise(resolve => wx.showModal({title, content,
  confirmColor: '#0E7C86', success: r => resolve(!!r.confirm), fail: () => resolve(false)}))

Page({
  data: {...empty(), tab: 'plans', today: '', day: '', loggedIn: false, active: false, loading: false,
    busy: false, error: '', sheet: '', form: {}, formError: '', metric: 0, days: 7,
    kindLabels: ['心率', '血氧', '血压', '身体感受'], metricLabels: ['心率', '血氧', '血压'],
    sourceLabels: ['手动记录', '报告转录'], planStatuses: ['使用中', '暂停', '结束'],
    doseStatuses: ['已服用（本人确认）', '已跳过（本人确认）', '恢复为未记录', '稍后处理待办']},
  onLoad() {
    this._epoch = 0
    this._unsubscribe = identity.onChange(() => { this.clearPrivate(); if (this._visible) this.refresh() })
  },
  onShow() {
    this._visible = true
    const today = view.parts().date
    this.setData({today, day: today})
    const app = getApp()
    const entry = app.globalData.healthEntry
    if (entry) {
      const tabs = {today: 'plans', records: 'status', status: 'status', visits: 'status', plans: 'plans'}
      this.setData({tab: tabs[entry] || 'plans'})
      delete app.globalData.healthEntry
      if (entry === 'plans' && wx.pageScrollTo) {
        setTimeout(() => wx.pageScrollTo({selector: '#medication-plan', duration: 300}), 50)
      }
    }
    this.refresh()
  },
  onHide() { this._visible = false; this.clearPrivate() },
  onUnload() { this._visible = false; this.clearPrivate(); if (this._unsubscribe) this._unsubscribe() },
  clearPrivate() {
    this._epoch++
    clearTimeout(this._expiry)
    this._policy = null; this._expiresAt = 0; this._raw = null
    this.setData({...empty(), active: false, loggedIn: !!identity.getToken(), loading: false,
      busy: false, sheet: '', form: {}, formError: '', error: ''})
  },
  current(epoch, version) { return this._visible && epoch === this._epoch && version === identity.getVersion() },
  async refresh() {
    if (this.data.busy) return
    const epoch = ++this._epoch, version = identity.getVersion()
    clearTimeout(this._expiry)
    this.setData({loggedIn: !!identity.getToken(), loading: !!identity.getToken(), error: ''})
    if (!identity.getToken()) { this.clearPrivate(); return }
    try {
      const access = await health.access()
      if (!this.current(epoch, version)) return
      this._policy = access.policy; this._expiresAt = access.expiresAt
      if (!access.active) { this._raw = null; this.setData({...empty(), active: false, loading: false, sheet: '', form: {}}); return }
      this.armExpiry(epoch, version)
      const data = await health.overview(this.data.day)
      if (!this.current(epoch, version) || Date.now() >= this._expiresAt) return
      this._raw = data
      this.render(data)
      this.setData({active: true, loading: false, accessUntil: accessDate(this._expiresAt)})
    } catch (err) {
      if (!this.current(epoch, version)) return
      this._raw = null
      this.setData({...empty(), active: false, loading: false, sheet: '', form: {}, error: err.message || '加载失败，请重试'})
    }
  },
  armExpiry(epoch, version) {
    clearTimeout(this._expiry)
    const remaining = this._expiresAt - Date.now()
    if (remaining <= 0) {
      this.clearPrivate()
      this.setData({error: '授权已到期，请重新查看告知并授权。'})
      return
    }
    this._expiry = setTimeout(() => {
      if (!this.current(epoch, version)) return
      if (Date.now() < this._expiresAt) { this.armExpiry(epoch, version); return }
      this.clearPrivate()
      this.setData({error: '授权已到期，请重新查看告知并授权。'})
    }, Math.min(remaining, 2147483647))
  },
  render(data) {
    const entries = data.entries.map(view.entry), plans = data.plans.map(p => view.plan(p))
    const doses = data.doses.map(d => view.dose(d))
    const latest = kinds.slice(0, 3).map(kind => entries.find(e => e.kind === kind) ||
      {id: kind, kind, label: view.labels[kind], valueLabel: '—', unit: view.units[kind], timeLabel: '尚无记录', sourceLabel: ''})
    const followups = data.followups.map(f => ({...f, timeLabel: view.timeLabel(f.due_at)}))
    this.setData({entries, plans, doses, latest, entryCount: data.entry_count,
      followups,
      latestRecord: view.recordSummary(data.latest_record),
      latestSymptom: entries.find(entry => entry.kind === 'symptom') || null,
      nextFollowup: view.nextFollowup(followups),
      hasMeasurements: latest.some(item => item.valueLabel && item.valueLabel !== '—'),
      recordCount: data.record_count || 0,
      careAlert: view.careAlert(data),
      summary: {taken: doses.filter(d => d.status === 'taken').length, skipped: doses.filter(d => d.status === 'skipped').length,
        pending: doses.filter(d => d.pending).length},
      chart: view.trend(data.entries, kinds[this.data.metric], this.data.days)})
  },
  async authorize() {
    if (this.data.busy) return
    const epoch = this._epoch, version = identity.getVersion()
    this.setData({busy: true, error: ''})
    try {
      const access = await health.access()
      if (!this.current(epoch, version)) return
      const granted = await health.grant(access.policy)
      if (!this.current(epoch, version)) return
      this.setData({busy: false})
      if (granted) await this.refresh()
    } catch (err) { if (this.current(epoch, version)) this.setData({error: err.message}) }
    finally { if (this.current(epoch, version)) this.setData({busy: false}) }
  },
  login() { wx.switchTab({url: '/pages/profile/index'}) },
  chat() { wx.navigateTo({url: '/pages/chat/index?domain=medical'}) },
  openCareChat(e) {
    if (!this.data.active || this.data.busy) return
    const question = e && e.currentTarget && e.currentTarget.dataset.kind === 'urgent'
      ? '我最近记录中出现胸痛或呼吸困难，应该怎么处理？'
      : '我的复诊快到了，复诊要带什么？'
    wx.navigateTo({url: '/pages/chat/index?domain=medical&question=' + encodeURIComponent(question)})
  },
  openRecordDocuments() {
    if (this.data.busy) return
    wx.navigateTo({url: '/pages/records/index'})
  },
  openVisits() {
    if (this.data.busy) return
    this.setData({tab: 'status'})
  },
  openSummary() {
    if (!this.data.active || this.data.busy) return
    this.setData({sheet: 'summary', visitDays: 7, visit: null, visitSections: [], visitText: '', visitError: ''})
    this.loadSummary()
  },
  changeSummaryDays(e) {
    if (this.data.visitBusy) return
    const days = Number(e.currentTarget.dataset.days)
    if (days !== 7 && days !== 30) return
    this.setData({visitDays: days})
    this.loadSummary()
  },
  async loadSummary() {
    if (!this.data.active || this.data.visitBusy) return
    const epoch = this._epoch, version = identity.getVersion()
    this.setData({visitBusy: true, visitError: '', visit: null, visitSections: [], visitText: ''})
    try {
      const data = await health.summary(this.data.visitDays)
      if (!this.current(epoch, version) || this.data.sheet !== 'summary') return
      const sections = view.summarySections(data)
      this.setData({visit: data, visitSections: sections, visitText: view.summaryText(sections), visitBusy: false})
    } catch (err) {
      if (!this.current(epoch, version)) return
      if (err.status === 401 || err.status === 403) {
        this.clearPrivate()
        this.setData({error: '访问授权已失效，请重新授权。'})
        return
      }
      this.setData({visitBusy: false, visitError: err.message || '摘要生成失败，请重试'})
    }
  },
  copySummary() {
    if (!this.data.visitText) return
    wx.setClipboardData({
      data: this.data.visitText,
      success: () => wx.showToast({title: '已复制摘要', icon: 'success'})
    })
  },
  switchTab(e) { if (!this.data.busy) this.setData({tab: e.currentTarget.dataset.tab}) },
  changeDay(e) { if (this.data.busy) return; this.setData({day: e.detail.value}); this.refresh() },
  changeMetric(e) { this.setData({metric: Number(e.detail.value)}); if (this._raw) this.render(this._raw) },
  changeDays(e) { this.setData({days: Number(e.currentTarget.dataset.days)}); if (this._raw) this.render(this._raw) },
  canEdit() { return this._visible && this.data.active && !this.data.busy && !this.data.loading && Date.now() < this._expiresAt },
  openEntry(e) {
    if (!this.canEdit()) return
    const id = e.currentTarget.dataset.id, row = this.data.entries.find(r => r.id === id)
    const p = view.parts(row ? row.measured_at : Date.now())
    this.setData({sheet: 'entry', formError: '', form: {id: row ? row.id : '', revision: row ? row.revision : 0,
      request_id: health.requestId(), kind: row ? kinds.indexOf(row.kind) : (e.currentTarget.dataset.symptom ? 3 : 0),
      source: row && row.source === 'report' ? 1 : 0, date: p.date, time: p.time,
      value: row && row.value != null ? String(row.value) : '', secondary: row && row.secondary_value != null ? String(row.secondary_value) : '',
      title: row ? row.title : '', note: row ? row.note : ''}})
  },
  openPlan(e) {
    if (!this.canEdit()) return
    const row = this.data.plans.find(r => r.id === e.currentTarget.dataset.id)
    this.setData({sheet: 'plan', formError: '', form: {id: row ? row.id : '', revision: row ? row.revision : 0,
      request_id: health.requestId(), name: row ? row.name : '', strength: row ? row.strength : '', dose: row ? row.dose : '',
      times: row ? row.times.slice() : [], start_date: row ? row.start_date : this.data.today,
      end_date: row ? (row.end_date || '') : '', note: row ? row.note : '', status: row ? statuses.indexOf(row.status) : 0}})
  },
  openDose(e) {
    if (!this.canEdit()) return
    const row = this.data.doses.find(d => d.key === e.currentTarget.dataset.key)
    if (!row) return
    const p = row.actual_at ? view.parts(row.actual_at) : {date: this.data.day, time: this.data.day === this.data.today ? view.parts().time : ''}
    this.setData({sheet: 'dose', formError: '', form: {...row, statusIndex: row.status === 'pending' ? 0 : doseStatuses.indexOf(row.status),
      date: p.date, time: p.time, postponeDate: view.parts(Date.now() + 30 * 60000).date, postponeTime: view.parts(Date.now() + 30 * 60000).time}})
  },
  openFollowup() {
    if (!this.canEdit()) return
    this.setData({sheet: 'followup', formError: '', form: {request_id: health.requestId(), title: '', note: '', date: this.data.today, time: ''}})
  },
  addPlanTime() {
    if (this.data.busy) return
    const times = this.data.form.times || []
    if (times.length >= 8) return
    const used = new Set(times)
    const next = ['08:00', '12:00', '18:00', '21:00', '09:00', '15:00', '20:00', '22:00'].find(t => !used.has(t)) || '08:00'
    this.setData({['form.times']: [...times, next].sort(), formError: ''})
  },
  pickPlanTime(e) {
    if (this.data.busy) return
    const index = Number(e.currentTarget.dataset.index), value = e.detail.value
    const times = (this.data.form.times || []).slice()
    if (times.includes(value)) { this.setData({formError: '这个时间已经添加过了，请选择其他时间'}); return }
    times[index] = value
    this.setData({['form.times']: times.sort(), formError: ''})
  },
  removePlanTime(e) {
    if (this.data.busy) return
    const times = (this.data.form.times || []).slice()
    times.splice(Number(e.currentTarget.dataset.index), 1)
    this.setData({['form.times']: times, formError: ''})
  },
  input(e) {
    if (this.data.busy) return
    const key = e.currentTarget.dataset.field
    const allowed = ['kind', 'source', 'date', 'time', 'value', 'secondary', 'title', 'note', 'name', 'strength', 'dose', 'times',
      'start_date', 'end_date', 'status', 'statusIndex', 'postponeDate', 'postponeTime']
    if (!allowed.includes(key)) return
    let value = e.detail.value
    if (['kind', 'source', 'status', 'statusIndex'].includes(key)) value = Number(value)
    this.setData({['form.' + key]: value, formError: ''})
  },
  clearEnd() { if (!this.data.busy) this.setData({'form.end_date': ''}) },
  closeSheet() {
    if (this.data.busy) return
    this._epoch += 1
    this.setData({sheet: '', form: {}, formError: '', visit: null, visitSections: [], visitText: '', visitError: '', visitBusy: false})
  },
  noop() {},
  async mutate(action) {
    if (!this.canEdit()) return
    const epoch = this._epoch, version = identity.getVersion()
    this.setData({busy: true, formError: '', error: ''})
    try {
      await action()
      if (!this.current(epoch, version)) return
      this.setData({busy: false, sheet: '', form: {}})
      wx.showToast({title: '已保存', icon: 'success'})
      await this.refresh()
    } catch (err) {
      if (!this.current(epoch, version)) return
      if (err.status === 403 || err.status === 401) { this.clearPrivate(); this.setData({error: '访问授权已失效，请重新授权。'}); return }
      const message = err.status === 409 ? '记录已变化或上次请求可能已保存。请关闭表单，刷新核对后重试。' : (err.message || '保存失败，请重试')
      this.setData({formError: message, error: this.data.sheet ? '' : message})
    } finally { if (this.current(epoch, version)) this.setData({busy: false}) }
  },
  async save() {
    if (!this.canEdit()) return
    const f = this.data.form
    try {
      if (this.data.sheet === 'entry') {
        const kind = kinds[f.kind], symptom = kind === 'symptom'
        if (!symptom && (!String(f.value).trim() || !Number.isFinite(Number(f.value)))) throw new Error('请填写真实测量值')
        if (kind === 'blood_pressure' && (!String(f.secondary).trim() || !Number.isFinite(Number(f.secondary)))) throw new Error('请同时填写舒张压')
        if (symptom && (!f.title.trim() || !f.note.trim())) throw new Error('请填写身体感受的主题和描述')
        const payload = {kind, source: !symptom && f.source === 1 ? 'report' : 'manual', measured_at: view.iso(f.date, f.time),
          value: symptom ? null : Number(f.value), secondary_value: kind === 'blood_pressure' ? Number(f.secondary) : null,
          title: symptom ? f.title.trim() : '', note: f.note.trim()}
        await this.mutate(() => f.id ? health.updateEntry(f.id, {...payload, revision: f.revision}) : health.createEntry({...payload, request_id: f.request_id}))
      } else if (this.data.sheet === 'plan') {
        const times = (f.times || []).slice().sort()
        if (!f.name.trim() || !f.dose.trim() || !times.length) throw new Error('请填写药品、每次用量，并添加至少一个每日时间')
        if (times.length > 8 || new Set(times).size !== times.length || times.some(t => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(t))) throw new Error('每日时间最多 8 个、不能重复，请用滚轮重新选择')
        view.iso(f.start_date, '00:00'); if (f.end_date) view.iso(f.end_date, '00:00')
        if (f.end_date && f.end_date < f.start_date) throw new Error('结束日期不能早于开始日期')
        const payload = {name: f.name.trim(), strength: f.strength.trim(), dose: f.dose.trim(), times, start_date: f.start_date,
          end_date: f.end_date || null, note: f.note.trim(), status: statuses[f.status]}
        await this.mutate(() => f.id ? health.updatePlan(f.id, {...payload, revision: f.revision}) : health.createPlan({...payload, request_id: f.request_id}))
      } else if (this.data.sheet === 'dose') {
        const status = doseStatuses[f.statusIndex]
        const payload = {plan_id: f.plan_id, plan_revision: f.plan_revision, scheduled_at: f.scheduled_at, revision: f.revision, status,
          actual_at: status === 'taken' ? view.iso(f.date, f.time) : null,
          postponed_until: status === 'postponed' ? view.iso(f.postponeDate, f.postponeTime) : null, note: f.note.trim()}
        await this.mutate(() => health.recordDose(payload))
      } else if (this.data.sheet === 'followup') {
        if (!f.title.trim()) throw new Error('请填写待办名称')
        const payload = {request_id: f.request_id, title: f.title.trim(), due_at: view.iso(f.date, f.time), note: f.note.trim()}
        await this.mutate(() => health.createFollowup(payload))
      }
    } catch (err) { this.setData({formError: err.message}) }
  },
  async remove() {
    if (!this.canEdit()) return
    const epoch = this._epoch, version = identity.getVersion(), f = this.data.form, type = this.data.sheet
    const yes = await confirm('确认删除', type === 'plan' ? '将删除此计划及其全部服药记录，无法恢复。若需保留历史，请在状态中选择暂停或结束。已添加的日历提醒需要自行删除。' : '将永久删除这条健康记录，无法恢复。')
    if (!yes || !this.current(epoch, version)) return
    await this.mutate(() => type === 'plan' ? health.deletePlan(f.id, f.revision) : health.deleteEntry(f.id, f.revision))
  },
  async toggleFollowup(e) {
    const row = this.data.followups.find(f => f.id === e.currentTarget.dataset.id)
    if (row) await this.mutate(() => health.updateFollowup(row.id, !row.done))
  },
  async removeFollowup(e) {
    if (!this.canEdit()) return
    const epoch = this._epoch, version = identity.getVersion(), id = e.currentTarget.dataset.id
    if (await confirm('删除待办', '删除此待办？已添加的手机日历提醒需要自行删除。') && this.current(epoch, version)) {
      await this.mutate(() => health.deleteFollowup(id))
    }
  },
  calendar(e) {
    if (!this.canEdit()) return
    const d = e.currentTarget.dataset
    const row = d.id ? this.data.followups.find(f => f.id === d.id) : this.data.doses.find(f => f.key === d.key)
    if (!row) return
    const at = d.id ? row.due_at : (row.status === 'postponed' ? row.postponed_until : row.scheduled_at)
    if (Date.parse(at) <= Date.now()) { wx.showToast({title: '请选择未来的待办时间', icon: 'none'}); return }
    if (!wx.addPhoneCalendar) { wx.showModal({title: '请使用手机日历', content: '当前环境不支持添加日历，请在手机日历中自行设置提醒。', showCancel: false}); return }
    wx.addPhoneCalendar({title: d.id ? '健康待办提醒' : '用药记录提醒', startTime: Math.floor(Date.parse(at) / 1000),
      endTime: Math.floor(Date.parse(at) / 1000) + 300, alarm: true, alarmOffset: 0,
      description: '请打开小程序核对当前计划并记录。',
      success: () => wx.showToast({title: '已添加到手机日历', icon: 'none'}),
      fail: () => wx.showToast({title: '未添加，请到手机日历设置', icon: 'none'})})
  }
})
