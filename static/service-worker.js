// service-worker.js
self.addEventListener('push', event => {
  let data = { title: 'Notifikasi', body: 'Ada pesan baru', url: '/' };
  try {
    if (event.data) {
      data = event.data.json();
    }
  } catch (e) {
    // jika payload bukan JSON, fallback
    data = { title: 'Notifikasi', body: event.data ? event.data.text() : 'Ada pesan baru', url: '/' };
  }

  const options = {
    body: data.body,
    data: { url: data.url },
    // icon/badge opsional:
    // icon: '/static/icons/icon-192.png',
    // badge: '/static/icons/badge-72.png',
    // tambahkan actions jika perlu
  };

  event.waitUntil(self.registration.showNotification(data.title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url ? event.notification.data.url : '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      for (const client of clientList) {
        // jika tab sudah terbuka, fokuskan
        if (client.url === url && 'focus' in client) return client.focus();
      }
      // jika belum, buka jendela baru
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
