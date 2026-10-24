const identity = require('../services/identity')

function bind(page, reset) {
  page._epoch = 0
  page._identityVersion = identity.getVersion()
  page._unsubscribe = identity.onChange(() => {
    page._epoch += 1
    page.setData(Object.assign({}, reset, {busy: false, loading: false, error: '身份已变化，请重新进入或刷新。'}))
  })
}
function begin(page) {
  const epoch = page._epoch = (page._epoch || 0) + 1
  const version = identity.getVersion()
  return () => page._epoch === epoch && identity.getVersion() === version
}
function dispose(page) {
  page._epoch += 1
  if (page._unsubscribe) page._unsubscribe()
}
module.exports = {bind, begin, dispose}
