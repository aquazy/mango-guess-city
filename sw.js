/* 回滚用的「清理版」Service Worker
 *
 * 之前的版本给页面注册了缓存型 SW。为了让已经访问过的手机立刻回到
 * “不走缓存、直接走网络”的原始行为，这个 SW 只做三件事：
 *   1. 装好就接管（skipWaiting）
 *   2. 清空所有缓存并把自己注销
 *   3. 不拦截任何请求（fetch 监听里什么都不做 → 完全走浏览器默认行为）
 *
 * 注销之后这个文件不会再被注册，用户下次打开就是纯净的原始版本。
 */
self.addEventListener('install', function () {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map(function (k) { return caches.delete(k); }));
    } catch (e) { /* 忽略 */ }
    try {
      await self.registration.unregister();
    } catch (e) { /* 忽略 */ }
  })());
});

// 故意留空：不调用 respondWith，所有请求都按浏览器默认行为直接走网络
self.addEventListener('fetch', function () {});
