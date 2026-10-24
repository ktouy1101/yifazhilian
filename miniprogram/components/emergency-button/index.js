const api = require('../../services/api')
Component({
  data: {holding: false, busy: false, status: '尚未发起事件', retryAvailable: false},
  lifetimes: {detached() { clearTimeout(this.timer) }},
  pageLifetimes: {hide() { this.cancel() }},
  methods: {
    start() {
      if (this.data.busy || this.data.holding) return
      this.setData({holding: true})
      this.timer = setTimeout(() => {
        this.timer = null
        this.setData({holding: false})
        if (!this.pendingKey) this.pendingKey = 'sos-' + Date.now() + '-' + Math.random().toString(36).slice(2)
        this.submit()
      }, 1200)
    },
    cancel() { clearTimeout(this.timer); this.timer = null; this.setData({holding: false}) },
    retry() { if (this.pendingKey && !this.data.busy) this.submit() },
    async submit() {
      this.setData({busy: true, status: '正在提交演示事件'})
      try {
        const result = await api.request('/emergencies', 'POST', {idempotency_key: this.pendingKey})
        this.pendingKey = null
        this.setData({status: '本地服务已接收演示事件；未通知、未接通任何对象。事件 ' + result.id, retryAvailable: false})
      } catch (e) {
        this.setData({status: '提交状态未确认。请使用床旁呼叫器；可重试同一演示事件。', retryAvailable: true})
      } finally { this.setData({busy: false}) }
    }
  }
})
