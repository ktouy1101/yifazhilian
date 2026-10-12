const api = require('../../services/api')
const showError = require('../../utils/errors')
Page({
  data: {domain: 'medical', text: '', messages: [], busy: false},
  onLoad(query) { this.setData({domain: query.domain === 'legal' ? 'legal' : 'medical'}); this.conversationId = null },
  onInput(e) { this.setData({text: e.detail.value}) },
  switchDomain() { this.conversationId = null; this.setData({domain: this.data.domain === 'medical' ? 'legal' : 'medical', messages: [], text: ''}) },
  async send() {
    const text = this.data.text.trim()
    if (!text || this.data.busy) return
    this.setData({busy: true})
    try {
      if (!this.conversationId) {
        const conversation = await api.request('/conversations', 'POST', {domain: this.data.domain})
        this.conversationId = conversation.id
      }
      const result = await api.request('/conversations/' + this.conversationId + '/messages', 'POST', {text})
      this.setData({text: '', messages: this.data.messages.concat([{question: text, answer: result.answer, sources: result.sources || [], disclaimer: result.disclaimer}])})
    } catch (e) { showError(e) } finally { this.setData({busy: false}) }
  }
})
