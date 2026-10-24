const api = require('../../services/api')

Page({
  data: {
    phone: '', code: '', countdown: 0, sending: false, loading: false,
    recentAccounts: [], intent: 'patient',
    intentHint: '登录后进入健康与法律问答首页'
  },
  pickIntent(e) {
    const intent = e.currentTarget.dataset.intent
    const hints = {
      patient: '登录后进入健康与法律问答首页',
      volunteer: '登录后进入志愿者工作台；采集权限需审核通过',
      staff: '仅限已配置的管理员手机号，登录后进入管理台'
    }
    this.setData({intent, intentHint: hints[intent] || hints.patient})
  },
  onLoad() {
    // 读最近登录过的手机号列表（本地存储）
    const list = wx.getStorageSync('recent_phones') || []
    this.setData({recentAccounts: list})
  },
  onPhone(e) { this.setData({phone: e.detail.value}) },
  onCode(e) { this.setData({code: e.detail.value}) },

  async sendCode() {
    const phone = this.data.phone
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      wx.showToast({title: '手机号格式不对', icon: 'none'}); return
    }
    if (this.data.countdown > 0 || this.data.sending) return
    this.setData({sending: true})
    try {
      const res = await api.request('/auth/send-code', 'POST', {phone})
      // 演示模式后端会回显 dev_code，直接填入；真实短信模式不回显，留空由用户输入
      if (res.dev_code) {
        this.setData({code: res.dev_code})
        wx.showModal({
          title: '验证码', content: '本次验证码：' + res.dev_code,
          showCancel: false, confirmText: '我知道了', confirmColor: '#0E7C86'
        })
      } else {
        this.setData({code: ''})
        wx.showToast({title: '验证码已发送，请查收短信', icon: 'none'})
      }
      let n = 60
      this.setData({countdown: n})
      this.timer = setInterval(() => {
        n -= 1
        if (n <= 0) { clearInterval(this.timer); this.setData({countdown: 0}) }
        else this.setData({countdown: n})
      }, 1000)
    } catch (e) {
      wx.showToast({title: e.message || '发送失败', icon: 'none'})
    } finally { this.setData({sending: false}) }
  },

  async login() {
    const {phone, code} = this.data
    if (!/^1[3-9]\d{9}$/.test(phone)) { wx.showToast({title: '手机号格式不对', icon: 'none'}); return }
    if (!/^\d{6}$/.test(code)) { wx.showToast({title: '请输入 6 位验证码', icon: 'none'}); return }
    this.setData({loading: true})
    try {
      const res = await api.request('/auth/phone-login', 'POST', {phone, code})
      api.identity.saveSession(res.access_token, res.user)
      // 保存最近登录列表
      const list = wx.getStorageSync('recent_phones') || []
      const filtered = list.filter(x => x.phone !== phone)
      filtered.unshift({phone, label: res.user.display_name || ''})
      wx.setStorageSync('recent_phones', filtered.slice(0, 5))
      await this.routeAfterLogin()
    } catch (e) {
      wx.showToast({title: e.message || '登录失败', icon: 'none'})
    } finally { this.setData({loading: false}) }
  },

  useRecent(e) {
    this.setData({phone: e.currentTarget.dataset.phone})
  },

  // 登录后按“进来的入口 + 服务端能力”决定去哪；能力只看服务端返回，不信本地判断。
  async routeAfterLogin() {
    let caps = {}
    try {
      const me = await api.request('/users/me')
      caps = (me && me.capabilities) || {}
    } catch (e) { /* 拿不到能力就按患者分流 */ }
    const intent = this.data.intent
    if (intent === 'staff') {
      if (caps.is_reviewer) {
        wx.showToast({title: '已进入管理台', icon: 'success'})
        setTimeout(() => wx.navigateTo({url: '/pages/admin/index'}), 400)
      } else {
        wx.showModal({title: '没有审核员权限', content: '这个手机号不在管理员名单里。请联系管理员在配置中添加，或换用患者入口。', showCancel: false})
        setTimeout(() => wx.switchTab({url: '/pages/home/index'}), 600)
      }
      return
    }
    if (intent === 'volunteer') {
      if (caps.can_collect) {
        wx.showToast({title: '已进入志愿者工作台', icon: 'success'})
        setTimeout(() => wx.navigateTo({url: '/pages/navigation-workbench/index'}), 400)
      } else {
        // 还没有采集权限：进志愿者中心提交申请，而不是只弹一句话。
        wx.showToast({title: '请先提交志愿者申请', icon: 'none'})
        setTimeout(() => wx.navigateTo({url: '/pages/volunteer/index'}), 400)
      }
      return
    }
    wx.showToast({title: '登录成功', icon: 'success'})
    setTimeout(() => wx.switchTab({url: '/pages/home/index'}), 500)
  }
})
