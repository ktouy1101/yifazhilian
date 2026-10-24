const OFFSET = 8 * 3600000
const labels = {heart_rate: '心率', spo2: '血氧', blood_pressure: '血压', symptom: '身体感受'}
const units = {heart_rate: 'bpm', spo2: '%', blood_pressure: 'mmHg', symptom: ''}
const pad = n => String(n).padStart(2, '0')
function parts(value = Date.now()) {
  const d = new Date(new Date(value).getTime() + OFFSET)
  return {date: d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()),
    time: pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes())}
}
function iso(date, time) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) throw new Error('请填写完整的日期和时间')
  const stamp = Date.parse(date + 'T' + time + ':00+08:00')
  if (!Number.isFinite(stamp) || parts(stamp).date !== date) throw new Error('日期或时间无效')
  return new Date(stamp).toISOString()
}
function timeLabel(value) { if (!value) return ''; const p = parts(value); return p.date + ' ' + p.time }
function entry(row) {
  return {...row, label: row.kind === 'symptom' ? row.title : labels[row.kind],
    valueLabel: row.kind === 'symptom' ? '' : (row.kind === 'blood_pressure' ? row.value + ' / ' + row.secondary_value : String(row.value)),
    unit: units[row.kind], timeLabel: timeLabel(row.measured_at), sourceLabel: row.source === 'report' ? '报告转录' : (row.kind === 'symptom' ? '本人自述' : '手动记录')}
}
function dose(row, now = Date.now()) {
  const pending = row.status === 'pending' || row.status === 'postponed'
  let statusLabel = {taken: '已服用 · 自报', skipped: '已跳过 · 自报', postponed: '稍后处理', pending: '待记录'}[row.status]
  if (pending && parts(row.scheduled_at).date < parts(now).date) statusLabel = '未记录'
  else if (row.status === 'pending' && Date.parse(row.scheduled_at) <= now) statusLabel = '待确认'
  else if (row.status === 'postponed' && Date.parse(row.postponed_until) <= now) statusLabel = '待确认'
  return {...row, clock: parts(row.scheduled_at).time, pending, statusLabel,
    actualLabel: timeLabel(row.actual_at), postponedLabel: timeLabel(row.postponed_until)}
}
function plan(row, now = Date.now()) {
  let statusLabel = {active: '使用中', paused: '已暂停', ended: '已结束'}[row.status]
  if (row.status === 'active' && row.start_date > parts(now).date) statusLabel = '尚未开始'
  if (row.status === 'active' && row.end_date && row.end_date < parts(now).date) statusLabel = '疗程已结束'
  return {...row, statusLabel, timesLabel: row.times.join('、') || '待核对时间',
    periodLabel: row.start_date + ' 至 ' + (row.end_date || '未设结束日期')}
}
function trend(rows, kind, days, now = Date.now()) {
  const end = Date.parse(parts(now).date + 'T23:59:59+08:00')
  const start = end + 1000 - days * 86400000
  const selected = rows.filter(row => row.kind === kind && Date.parse(row.measured_at) >= start && Date.parse(row.measured_at) <= now)
    .sort((a, b) => Date.parse(a.measured_at) - Date.parse(b.measured_at))
  const values = selected.flatMap(row => kind === 'blood_pressure' ? [row.value, row.secondary_value] : [row.value])
  if (!values.length) return {points: [], count: 0, min: '', max: '', start: parts(start).date.slice(5), end: parts(end).date.slice(5)}
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1
  const points = []
  selected.forEach(row => {
    const x = 4 + (Date.parse(row.measured_at) - start) / (end - start) * 92
    const point = (value, secondary) => ({id: row.id + (secondary ? '-dia' : '-value'), entryId: row.id,
      x: x.toFixed(2), y: (max === min ? 50 : 88 - (value - min) / span * 76).toFixed(2), secondary, value})
    points.push(point(row.value, false))
    if (kind === 'blood_pressure') points.push(point(row.secondary_value, true))
  })
  return {points, count: selected.length, min, max, start: parts(start).date.slice(5), end: parts(end).date.slice(5)}
}
function summarySections(data) {
  const section = (title, items) => ({title, items})
  const sections = [section('统计范围', [
    data.start + ' 至 ' + data.end + '（' + data.days + ' 天，北京时间）'
  ])]
  const lines = []
  const counts = data.entries.by_kind || {}
  const parts = ['heart_rate', 'spo2', 'blood_pressure']
    .filter(kind => counts[kind])
    .map(kind => labels[kind] + ' ' + counts[kind] + ' 次')
  if (data.entries.total) {
    lines.push('共 ' + data.entries.total + ' 条记录' + (parts.length ? '：' + parts.join('、') : '') + '。')
  } else {
    lines.push('本区间没有手动记录。')
  }
  ;(data.entries.latest || []).forEach(row => {
    const item = entry(row)
    lines.push(item.label + '：' + (item.valueLabel || '—') + ' ' + (item.unit || '') +
      '（' + item.timeLabel + '，' + item.sourceLabel + '）')
  })
  const symptoms = data.symptoms || {}
  if (symptoms.count) {
    lines.push('身体感受 ' + symptoms.count + ' 条。')
    ;(symptoms.items || []).slice(0, 3).forEach(row => {
      lines.push('· ' + (row.title || '未命名感受') + '（' + timeLabel(row.measured_at) + '）')
    })
  }
  sections.push(section('测量与身体感受', lines))

  const med = data.medication || {}
  const medLines = []
  if (med.total) {
    medLines.push('本区间涉及 ' + (med.plans_in_period || 0) + ' 个用药计划，共安排 ' + med.total +
      ' 次；已到时间 ' + med.due + ' 次。')
    medLines.push('已服用 ' + med.taken + ' 次，已跳过 ' + med.skipped + ' 次，未记录 ' + med.unrecorded +
      ' 次' + (med.postponed ? '，稍后处理 ' + med.postponed + ' 次' : '') +
      (med.upcoming ? '；还有 ' + med.upcoming + ' 次待记录' : '') + '。')
    ;(med.by_plan || []).forEach(planItem => {
      medLines.push(planItem.name + '（' + (planItem.dose || '用量未填') + '）：已服用 ' + planItem.taken +
        '，已跳过 ' + planItem.skipped + '，未记录 ' + planItem.unrecorded +
        (planItem.upcoming ? '，待记录 ' + planItem.upcoming : '') + '。')
    })
  } else if (med.plan_count) {
    medLines.push('本区间没有需要记录的用药安排。')
  } else {
    medLines.push('本区间没有用药计划。')
  }
  sections.push(section('用药记录', medLines))

  const followups = data.followups || {}
  const followupLines = []
  if (followups.pending_count) {
    followupLines.push('未完成待办 ' + followups.pending_count + ' 项。')
    ;(followups.items || []).slice(0, 5).forEach(item => {
      followupLines.push('· ' + item.title + '（' + timeLabel(item.due_at) + '）')
    })
  } else {
    followupLines.push('没有未完成的复诊或其他待办。')
  }
  sections.push(section('复诊与其他待办', followupLines))

  const notes = [
    '以上为本人填写/自报的记录，未接入医院或设备，不构成诊断、医嘱或医院证明。',
    '“未记录”不等于漏服；请结合实际情况核对。'
  ]
  if (data.entries.truncated) notes.push('记录较多，本摘要只统计最近 1000 条。')
  sections.push(section('说明', notes))
  return sections
}

function summaryText(sections) {
  return sections.map(section => section.title + '\n' +
    section.items.map(item => '· ' + item).join('\n')).join('\n\n')
}

const RED_FLAGS = ['胸痛', '胸闷', '呼吸困难', '喘不过气', '意识不清', '昏迷', '抽搐', '大出血', '剧烈头痛']

function careAlert(data, now = Date.now()) {
  const entries = data.entries || []
  const flagged = entries.find(row => row.kind === 'symptom' &&
    RED_FLAGS.some(word => ((row.title || '') + (row.note || '')).includes(word)))
  if (flagged) {
    return {level: 'urgent', kind: 'urgent', title: '需要尽快联系医护',
      text: '你最近的感受记录里出现了需要现场评估的描述。请立即使用床旁呼叫器或联系病区医护，不要等待聊天回复；本页不判断病情。',
      action: '查看建议'}
  }
  const next = nextFollowup(data.followups)
  if (!next) return null
  const due = Date.parse(next.due_at)
  if (!Number.isFinite(due)) return null
  if (due <= now) {
    return {level: 'due', kind: 'followup', title: '复诊时间已到',
      text: '你记录的复诊待办已经到期，建议联系医院确认新的时间；如症状加重，请提前联系医护。',
      action: '去咨询'}
  }
  if (due <= now + 3 * 86400000) {
    return {level: 'soon', kind: 'followup', title: '复诊时间临近',
      text: '复诊快到了，请提前确认挂号、要带的资料和交通安排；如症状加重，请提前联系医护。',
      action: '去咨询'}
  }
  return null
}

function nextFollowup(followups) {
  return (followups || []).filter(item => !item.done)
    .sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at))[0] || null
}

function recordSummary(record) {
  if (!record) return null
  return {...record, dateLabel: record.record_date || '日期未填',
    fields: (record.fields || []).filter(field => field.name || field.result).slice(0, 4)}
}

module.exports = {parts, iso, timeLabel, entry, dose, plan, trend, summarySections, summaryText, careAlert, nextFollowup, recordSummary, labels, units}
