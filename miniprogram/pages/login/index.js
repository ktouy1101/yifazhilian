const api = require('../../services/api')

Page({
  data: {
    phone: '', code: '', password: '', mode: 'code', countdown: 0, sending: false, loading: false,
    recentAccounts: [], joinVolunteer: false
  },
  onLoad() {
    // 读最近登录过的手机号列表（本地存储）
    const list = wx.getStorageSync('recent_phones') || []
    this.setData({recentAccounts: list})
  },
  // 登录框右下角的「成为志愿者」：标记一下，登录成功后直接去志愿者中心申请。
  joinAsVolunteer() { this.setData({joinVolunteer: !this.data.joinVolunteer}) },
  // 离开或返回时清掉倒计时和已填的验证码：否则登录成功再回到本页，
  // 会看到上一轮的「27s」和被自动填入的旧验证码。
  onHide() { this.resetForm() },
  onUnload() { this.resetForm() },
  resetForm() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
    if (this.data.countdown || this.data.code) this.setData({code: '', countdown: 0})
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
    const {phone, code, mode, password} = this.data
    if (!/^1[3-9]\d{9}$/.test(phone)) { wx.showToast({title: '手机号格式不对', icon: 'none'}); return }
    if (mode === 'password') {
      if (!password || password.length < 6) { wx.showToast({title: '请输入密码（至少 6 位）', icon: 'none'}); return }
    } else if (!/^\d{6}$/.test(code)) {
      wx.showToast({title: '请输入 6 位验证码', icon: 'none'}); return
    }
    this.setData({loading: true})
    try {
      const res = mode === 'password'
        ? await api.request('/auth/password-login', 'POST', {phone, password})
        : await api.request('/auth/phone-login', 'POST', {phone, code})
      api.identity.saveSession(res.access_token, res.user)
      // 保存最近登录列表
      const list = wx.getStorageSync('recent_phones') || []
      const filtered = list.filter(x => x.phone !== phone)
      filtered.unshift({phone, label: res.user.display_name || ''})
      wx.setStorageSync('recent_phones', filtered.slice(0, 5))
      // 登录成功立刻清掉本页的验证码与倒计时，避免返回时看到旧状态。
      this.resetForm()
      await this.routeAfterLogin()
    } catch (e) {
      wx.showToast({title: e.message || '登录失败', icon: 'none'})
    } finally { this.setData({loading: false}) }
  },

  switchMode(e) {
    const mode = e.currentTarget.dataset.mode
    if (mode === this.data.mode) return
    this.resetForm()
    this.setData({mode, error: ''})
  },
  onPassword(e) { this.setData({password: e.detail.value}) },

  useRecent(e) {
    this.setData({phone: e.currentTarget.dataset.phone})
  },

  // 登录后只看服务端能力决定去哪：审核员 → 管理台，志愿者 → 志愿者中心，其余 → 首页。
  // 勾了「成为志愿者」则先去志愿者中心提交申请。
  async routeAfterLogin() {
    let caps = {}
    try {
      const me = await api.request('/users/me')
      caps = (me && me.capabilities) || {}
    } catch (e) { /* 拿不到能力就按患者分流 */ }
    if (caps.is_reviewer) {
      wx.showToast({title: '已进入管理台', icon: 'success'})
      setTimeout(() => wx.navigateTo({url: '/pages/admin/workbench/index'}), 400)
      return
    }
    if (this.data.joinVolunteer || caps.is_volunteer || caps.can_collect || caps.can_help_legal) {
      wx.showToast({title: '已进入志愿者中心', icon: 'success'})
      setTimeout(() => wx.navigateTo({url: '/pages/volunteer/workbench/index'}), 400)
      return
    }
    wx.showToast({title: '登录成功', icon: 'success'})
    setTimeout(() => wx.switchTab({url: '/pages/home/index'}), 500)
  }
})
