const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

function header(depth, wx) {
  let component
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../miniprogram/components/app-header/index.js'), 'utf8'), {
    Component: value => { component = value }, wx, getCurrentPages: () => Array.from({length: depth}, () => ({}))
  })
  return {...component.methods, properties: {fallback: '/pages/navigation/index'}}
}

test('header returns exactly one page and ignores repeated taps while navigating', () => {
  const calls = []
  const instance = header(3, {navigateBack: options => calls.push(options), switchTab: () => assert.fail('must keep previous page')})
  instance.goBack(); instance.goBack()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].delta, 1)
  calls[0].success()
  assert.equal(instance._returning, false)
})

test('a directly opened route returns to the navigation tab without a page stack', () => {
  let destination
  const instance = header(1, {navigateBack: () => assert.fail('no previous page'), switchTab: options => {
    destination = options.url; options.complete()
  }})
  instance.goBack()
  assert.equal(destination, '/pages/navigation/index')
  assert.equal(instance._returning, false)
})

test('failed back navigation falls back to a tab and stays locked until that finishes', () => {
  let fallback, attempts = 0
  const instance = header(2, {navigateBack: options => { attempts++; options.fail() }, switchTab: options => { fallback = options }})
  instance.goBack(); instance.goBack()
  assert.equal(attempts, 1)
  assert.equal(fallback.url, '/pages/navigation/index')
  fallback.complete()
  assert.equal(instance._returning, false)
})

test('a failed fallback shows an error and permits another attempt', () => {
  let message, calls = 0
  const instance = header(1, {switchTab: options => { calls++; options.fail(); options.complete() }, showToast: options => { message = options.title }})
  instance.goBack(); instance.goBack()
  assert.equal(calls, 2)
  assert.match(message, /返回.*重试/)
})
