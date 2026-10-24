const nav = require('../../services/navigation')
const api = require('../../services/api')
const guard = require('../../utils/navigation-page')
const STATUS = {draft: '草稿', submitted: '待审核', changes_requested: '需补拍', published: '已发布', disabled: '已停用'}
const EMPTY = {me: {}, perms: {}, tasks: [], routes: [], mine: [], queue: [], roleLabel: ''}
Page({
  data: {...EMPTY, statusLabel: STATUS, busy: false, loading: false, switching: false, error: '', pickerOpen: true, legacyExpanded: false,
    selectedAccountId: 'm11-test-patient', selectedAction: '以体验员进入导诊',
    testAccounts: [{id: 'm11-test-patient', role: 'patient', label: '体验员', name: '小安', icon: 'pin',
      description: '浏览已发布路线，查看照片、反馈问题', action: '以体验员进入导诊'},
      {id: 'm11-test-collector', role: 'volunteer', label: '采集员', name: '小林', icon: 'camera',
        description: '领取任务、拍照，提交后等待他人审核', action: '进入采集工作台'},
      {id: 'm11-test-reviewer', role: 'volunteer', label: '审核员', name: '小周', icon: 'shield',
        description: '审核他人提交，发布或停用路线', action: '进入审核工作台'}],
    accounts: [{id: 'demo-volunteer-001', role: 'volunteer', label: '演示采集者'},
      {id: 'demo-reviewer-001', role: 'volunteer', label: '演示审核员'},
      {id: 'demo-patient-001', role: 'patient', label: '合成患者'}]},
  onLoad() { guard.bind(this, {...EMPTY, pickerOpen: true}) },
  onShow() { return this.reload() },
  onUnload() { guard.dispose(this) },
  async reload() {
    const current = guard.begin(this)
    this.setData({...EMPTY, error: '', loading: true, busy: false})
    if (!api.identity.getToken()) { this.setData({loading: false, pickerOpen: true}); return false }
    try {
      const me = await nav.me()
      if (!current()) return false
      const p = me.permissions
      const [routes, tasks, mine, queue] = await Promise.all([
        nav.routes(), p.collect ? nav.tasks() : {items: []},
        p.collect ? nav.listSubmissions('mine') : {items: []},
        p.review ? nav.listSubmissions('review') : {items: []}
      ])
      if (!current()) return false
      this.setData({me, perms: p, pickerOpen: false, roleLabel: p.review ? '审核员' : p.collect ? '采集员' : '体验员',
        routes: routes.items, tasks: tasks.items, mine: mine.items, queue: queue.items})
      return true
    } catch (e) { if (current()) this.setData({error: e.message}); return false }
    finally { if (current()) this.setData({loading: false}) }
  },
  async switchDemo(e) {
    if (this.data.busy || this._switching) return
    const account = this.data.testAccounts.concat(this.data.accounts).find(a => a.id === e.currentTarget.dataset.id)
    if (!account) return
    this._switching = true
    this.setData({busy: true, switching: true, error: ''})
    try {
      if (!api.identity.getUser() || api.identity.getUser().id !== account.id) {
        await api.logout()
        await api.login(account.id, account.role)
      }
      return await this.reload()
    } catch (e) { this.setData({error: e.message, busy: false, pickerOpen: true}); return false }
    finally { this._switching = false; this.setData({switching: false}) }
  },
  selectAccount(e) {
    if (this.data.busy || this.data.loading || this._switching) return
    const account = this.data.testAccounts.concat(this.data.accounts).find(a => a.id === e.detail.value)
    if (account) this.setData({selectedAccountId: account.id, selectedAction: account.action || '使用' + account.label, error: ''})
  },
  toggleLegacy() { if (!this._switching) this.setData({legacyExpanded: !this.data.legacyExpanded}) },
  openAccountPicker() {
    if (this.data.busy || this.data.loading || this._switching) return
    const id = this.data.me.user && this.data.me.user.id
    this.setData({pickerOpen: true, error: '', legacyExpanded: this.data.accounts.some(a => a.id === id)})
    if (id) this.selectAccount({detail: {value: id}})
  },
  cancelSwitch() { if (!this._switching && this.data.me.user) this.setData({pickerOpen: false}) },
  async enterSelectedAccount() {
    if (this.data.busy || this.data.loading || this._switching) return
    const id = this.data.selectedAccountId
    const success = await this.switchDemo({currentTarget: {dataset: {id}}})
    if (success && this.data.perms.browse && !this.data.perms.collect && !this.data.perms.review) this.goNavigation()
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
    } catch (e) { if (current()) this.setData({error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  openCapture(e) { wx.navigateTo({url: '/pages/route-capture/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },
  openReview(e) { wx.navigateTo({url: '/pages/route-review/index?id=' + encodeURIComponent(e.currentTarget.dataset.id)}) },
  openRoute(e) { wx.navigateTo({url: '/pages/route-review/index?readonly=1&id=' + encodeURIComponent(e.currentTarget.dataset.id)}) }
})

