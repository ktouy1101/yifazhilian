const api = require('../../services/api')
const showError = require('../../utils/errors')
const {canEnterWorkbench} = require('../../utils/capabilities')

function validPolicy(policy) {
  return !!(policy && ['recipient', 'policy_version', 'notice', 'provider'].every(key =>
    typeof policy[key] === 'string' && policy[key].trim()) && typeof policy.external_network === 'boolean')
}

function expiryText(value) {
  const date = new Date(value)
  if (isNaN(date.getTime())) return ''
  const pad = number => (number < 10 ? '0' : '') + number
  return (date.getMonth() + 1) + '月' + date.getDate() + '日 ' + pad(date.getHours()) + ':' + pad(date.getMinutes())
}

Page({
  data: {
    sheet: '', previewMode: true, serviceConnected: false, connecting: false, authorizationBusy: false,
    elderMode: true, fontSize: '中', fontSizes: ['小', '中', '大'],
    status: '',
    me: null,
    // 资料编辑表单
    profileForm: {nickname: '', age: '', gender: '未填', bed_location: '', allergies: '', emergency_name: '', emergency_phone: '', doctor_phone: ''},
    accountList: [
      {id: 'demo-patient-001', label: '合成患者 001', role: 'patient'},
      {id: 'demo-patient-002', label: '合成患者 002', role: 'patient'},
      {id: 'demo-volunteer-001', label: '演示志愿者', role: 'volunteer'},
      {id: 'demo-reviewer-001', label: '演示审核员', role: 'volunteer'}
    ]
  },
  onShow() {
    const app = getApp()
    const openSettings = !!(app && app.globalData && app.globalData.openSettings)
    if (app && app.globalData) app.globalData.openSettings = false
    this.refresh()
    if (openSettings) this.openSettings()
  },
  onHide() { this.setData({sheet: ''}) },
  noop() {},
  openNavigationWorkbench() { wx.navigateTo({url: '/pages/navigation-workbench/index'}) },
  openVolunteer() { wx.navigateTo({url: '/pages/volunteer/index'}) },
  openAdmin() { wx.navigateTo({url: '/pages/admin/index'}) },

  openSettings() { this.setData({sheet: 'settings'}); this.refresh() },
  openProfile() {
    const p = (this.data.me && this.data.me.profile) || {}
    this.setData({
      sheet: 'profile',
      profileForm: {
        nickname: p.nickname || '', age: p.age || '', gender: p.gender || '未填',
        bed_location: p.bed_location || '', allergies: p.allergies || '',
        emergency_name: p.emergency_name || '', emergency_phone: p.emergency_phone || '',
        doctor_phone: p.doctor_phone || ''
      }
    })
  },
  closeSheet() { this.setData({sheet: ''}) },

  async refresh() {
    const version = this.refreshVersion = (this.refreshVersion || 0) + 1
    const token = api.identity.getToken()
    const previewMode = !token
    this.setData({previewMode})
    if (previewMode) {
      this.policies = {}
      this.setData({serviceConnected: false, status: '未登录', me: null, scopes: []})
      return false
    }
    try {
      const me = await api.getMe()
      this.setData({me, canWorkbench: canEnterWorkbench(me && me.capabilities)})
      const result = await api.request('/consents')
      if (version !== this.refreshVersion || token !== api.identity.getToken()) return false
      this.policies = result.policies || {}
      const now = Date.now()
      const scopes = [
        {key: 'ai_medical', label: '健康问答', detail: '健康知识问答；发送范围以授权告知为准', statusLabel: '未连接', active: false},
        {key: 'ai_legal', label: '法律问答', detail: '患者权益答疑；发送范围以授权告知为准', statusLabel: '未连接', active: false},
        {key: 'vitals', label: '健康记录与用药', detail: '手动测量、身体感受、用药计划与本人服药记录', statusLabel: '未连接', active: false},
        {key: 'records_read', label: '本地病历处理', detail: '照片上传、本地OCR、核对归档与回查', statusLabel: '未连接', active: false}
      ]
      this.setData({
        serviceConnected: true, status: '已读取授权记录',
        scopes: scopes.map(item => {
          const record = (result.items || []).find(entry => entry.scope === item.key)
          const policy = this.policies[item.key]
          const policyReady = validPolicy(policy)
          const matches = !!(policyReady && record && record.recipient === policy.recipient && record.policy_version === policy.policy_version)
          const active = !!(matches && record.granted && !record.revoked_at && Date.parse(record.expires_at) > now)
          let statusLabel = '未授权'
          if (!policyReady) statusLabel = '告知未就绪'
          else if (record) statusLabel = record.revoked_at || !record.granted ? '已撤回' : (!matches ? '需重新授权' : (active ? '已授权' : '已到期'))
          let expiryLabel = ''
          if (record && record.granted && !record.revoked_at && matches) {
            expiryLabel = (active ? '有效至 ' : '已于 ') + expiryText(record.expires_at) + (active ? '' : ' 到期')
          }
          return {...item, statusLabel, active, expiryLabel}
        })
      })
      return true
    } catch (error) {
      if (version !== this.refreshVersion || !api.identity.getToken()) return false
      this.setData({serviceConnected: false, scopes: [], status: '未能读取授权状态：' + error.message})
      return false
    }
  },

  // 资料编辑
  onProfileInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({[`profileForm.${field}`]: e.detail.value})
  },
  onGenderPick(e) {
    this.setData({'profileForm.gender': e.currentTarget.dataset.value})
  },
  async saveProfile() {
    try {
      const f = this.data.profileForm
      const payload = {
        nickname: f.nickname || null,
        age: f.age ? parseInt(f.age) : null,
        gender: f.gender,
        bed_location: f.bed_location || null,
        allergies: f.allergies || null,
        emergency_name: f.emergency_name || null,
        emergency_phone: f.emergency_phone || null,
        doctor_phone: f.doctor_phone || ''
      }
      const me = await api.updateProfile(payload)
      this.setData({me, sheet: '', canWorkbench: canEnterWorkbench(me && me.capabilities)})
      wx.showToast({title: '已保存', icon: 'success'})
    } catch (e) { showError(e) }
  },

  openHealth(tab = 'today') {
    getApp().globalData.healthEntry = typeof tab === 'string' ? tab : 'today'
    wx.switchTab({url: '/pages/home/index'})
  },
  addMed() { this.openHealth('plans') },
  addVital() { this.openHealth('records') },

  async connectService() {
    wx.navigateTo({url: '/pages/login/index'})
  },

  async grant(e) {
    if (this.data.previewMode || this.data.authorizationBusy) return
    const scope = e.currentTarget.dataset.scope
    const entry = this.data.scopes.find(item => item.key === scope)
    if (!entry) return
    let submitted = false
    this.setData({authorizationBusy: true})
    try {
      const refreshed = await this.refresh()
      const policy = this.policies && this.policies[scope]
      if (!refreshed || !validPolicy(policy)) throw new Error('未取得完整授权告知，请稍后重试。')
      const notice = {recipient: policy.recipient, policy_version: policy.policy_version, text: policy.notice}
      const confirmed = await new Promise(resolve => wx.showModal({
        title: '单独授权：' + entry.label,
        content: notice.text + '\n\n接收方：' + notice.recipient + '\n告知版本：' + notice.policy_version,
        confirmText: '同意授权', confirmColor: '#0E7C86',
        success: result => resolve(!!result.confirm), fail: () => resolve(false)
      }))
      if (!confirmed) return
      submitted = true
      await api.request('/consents', 'POST', {scope, granted: true, recipient: notice.recipient, policy_version: notice.policy_version})
      await this.refresh()
    } catch (error) {
      showError(error)
      if (submitted) await this.refresh()
    }
    finally { this.setData({authorizationBusy: false}) }
  },

  async revoke(e) {
    if (this.data.previewMode || this.data.authorizationBusy) return
    this.setData({authorizationBusy: true})
    try { await api.request('/consents/' + e.currentTarget.dataset.scope, 'DELETE'); await this.refresh() }
    catch (error) { showError(error) }
    finally { this.setData({authorizationBusy: false}) }
  },

  async logout() {
    if (this.data.authorizationBusy) return
    this.setData({authorizationBusy: true})
    try {
      await api.logout()
      this.setData({me: null, previewMode: true})
      await this.refresh()
    } catch (error) { showError(error) }
    finally { this.setData({authorizationBusy: false}) }
  },

  async switchAccount(e) {
    if (this.data.authorizationBusy) return
    const id = e.currentTarget.dataset.id
    const role = e.currentTarget.dataset.role
    const currentId = this.data.me && this.data.me.id
    if (id === currentId) return
    this.setData({authorizationBusy: true})
    try {
      await api.logout()
      await api.login(id, role)
      wx.showToast({title: '已切换', icon: 'success'})
      await this.refresh()
    } catch (e) { showError(e) }
    finally { this.setData({authorizationBusy: false}) }
  },

  async reloginWechat() {
    wx.navigateTo({url: '/pages/login/index'})
  }
})
