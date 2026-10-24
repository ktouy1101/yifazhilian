const api = require('./api')
const identity = require('./identity')
const root = '/health-management'
const enc = encodeURIComponent
const requestId = () => 'health-' + Date.now() + '-' + Math.random().toString(36).slice(2, 12)

async function access() {
  const result = await api.request('/consents')
  const policy = result.policies && result.policies.vitals
  if (!policy || policy.policy_version !== 'health-records-1' || !policy.notice || !policy.recipient || policy.external_network !== false) {
    throw new Error('健康记录服务需要更新，请检查本机服务后重试')
  }
  const consent = (result.items || []).find(item => item.scope === 'vitals')
  const active = !!(consent && consent.granted && !consent.revoked_at && Date.parse(consent.expires_at) > Date.now()
    && consent.policy_version === policy.policy_version && consent.recipient === policy.recipient)
  return {active, policy, expiresAt: active ? Date.parse(consent.expires_at) : 0}
}
async function grant(policy) {
  const version = identity.getVersion()
  const confirm = await new Promise(resolve => wx.showModal({title: '健康记录与用药授权',
    content: policy.notice, confirmText: '同意授权', confirmColor: '#0E7C86',
    success: res => resolve(!!res.confirm), fail: () => resolve(false)}))
  if (!confirm || version !== identity.getVersion()) return false
  await api.request('/consents', 'POST', {scope: 'vitals', recipient: policy.recipient, policy_version: policy.policy_version})
  return true
}
module.exports = {
  requestId, access, grant,
  overview: day => api.request(root + '/overview?day=' + enc(day)),
  summary: days => api.request(root + '/summary?days=' + enc(days)),
  createEntry: data => api.request(root + '/entries', 'POST', data),
  updateEntry: (id, data) => api.request(root + '/entries/' + enc(id), 'PUT', data),
  deleteEntry: (id, revision) => api.request(root + '/entries/' + enc(id) + '?revision=' + revision, 'DELETE'),
  createPlan: data => api.request(root + '/plans', 'POST', data),
  updatePlan: (id, data) => api.request(root + '/plans/' + enc(id), 'PUT', data),
  deletePlan: (id, revision) => api.request(root + '/plans/' + enc(id) + '?revision=' + revision, 'DELETE'),
  recordDose: data => api.request(root + '/doses', 'PUT', data),
  createFollowup: data => api.request(root + '/followups', 'POST', data),
  updateFollowup: (id, done) => api.request(root + '/followups/' + enc(id), 'PATCH', {done}),
  deleteFollowup: id => api.request(root + '/followups/' + enc(id), 'DELETE')
}
