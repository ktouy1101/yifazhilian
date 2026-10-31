// 展示用格式化：把后端返回的代码/ISO 时间转成中文与本地时间。
// 只做展示，不改数据；后端仍然存原始值。

const FEEDBACK = {
  closed: '通道已关闭',
  misdirected: '指错方向',
  privacy: '隐私相关',
  other: '其他'
}

const AUDIT = {
  admin_role_grant: '授予角色',
  admin_role_revoke: '撤销角色',
  admin_delete_user: '停用账号',
  volunteer_apply: '提交志愿者申请',
  volunteer_review: '审核志愿者',
  phone_login: '手机号登录',
  wechat_login: '微信登录',
  demo_login: '演示登录',
  logout: '退出登录',
  conversation_answered: '完成一次问答',
  navigation_task_claimed: '领取采集任务'
}

const pad = value => (value < 10 ? '0' : '') + value

// 后端时间带 6 位微秒（2026-10-17T12:24:20.267931+00:00），
// iOS 的 Date 解析不接受超过 3 位小数，这里先裁剪再格式化。
function timeText(value) {
  if (!value) return ''
  const raw = String(value).trim()
  const parsed = new Date(raw.replace(/(\.\d{3})\d+/, '$1'))
  if (isNaN(parsed.getTime())) return raw
  return parsed.getFullYear() + '-' + pad(parsed.getMonth() + 1) + '-' + pad(parsed.getDate())
    + ' ' + pad(parsed.getHours()) + ':' + pad(parsed.getMinutes())
}

function feedbackCategory(code) {
  return FEEDBACK[code] || code || ''
}

function auditAction(code) {
  return AUDIT[code] || code || ''
}

module.exports = {timeText, feedbackCategory, auditAction}
