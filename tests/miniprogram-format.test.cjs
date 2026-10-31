const test = require('node:test')
const assert = require('node:assert/strict')
const {timeText, feedbackCategory, auditAction} = require('../miniprogram/utils/format')

const pad = value => (value < 10 ? '0' : '') + value

test('六位微秒的 ISO 时间也能格式化成本地时间', () => {
  const iso = '2026-10-17T12:24:20.267931+00:00'
  const parsed = new Date('2026-10-17T12:24:20.267+00:00')
  const expected = parsed.getFullYear() + '-' + pad(parsed.getMonth() + 1) + '-' + pad(parsed.getDate())
    + ' ' + pad(parsed.getHours()) + ':' + pad(parsed.getMinutes())
  assert.equal(timeText(iso), expected)
  assert.match(timeText(iso), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
})

test('空值或非法时间原样返回，不抛错', () => {
  assert.equal(timeText(''), '')
  assert.equal(timeText(null), '')
  assert.equal(timeText('not-a-date'), 'not-a-date')
})

test('反馈分类翻译成中文，未知代码原样保留', () => {
  assert.equal(feedbackCategory('misdirected'), '指错方向')
  assert.equal(feedbackCategory('closed'), '通道已关闭')
  assert.equal(feedbackCategory('privacy'), '隐私相关')
  assert.equal(feedbackCategory('other'), '其他')
  assert.equal(feedbackCategory('weird'), 'weird')
  assert.equal(feedbackCategory(undefined), '')
})

test('审计动作翻译成中文，未知动作原样保留', () => {
  assert.equal(auditAction('admin_role_grant'), '授予角色')
  assert.equal(auditAction('volunteer_review'), '审核志愿者')
  assert.equal(auditAction('admin_delete_user'), '停用账号')
  assert.equal(auditAction('something_new'), 'something_new')
})
