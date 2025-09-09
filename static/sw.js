// File: static/sw.js

self.addEventListener('push', function(event) {
    console.log('[Service Worker] Push Diterima.');
    
    let notificationData = {};

    // Coba baca data sebagai JSON.
    try {
        // Ini akan berhasil untuk notifikasi dari server Flask.
        notificationData = event.data.json();
    } catch (e) {
        // Jika gagal (seperti saat tes manual), baca sebagai teks biasa.
        notificationData = {
            title: 'Notifikasi Tes Browser',
            body: event.data.text(),
        };
    }

    const title = notificationData.title || 'Notifikasi Baru';
    const options = {
        body: notificationData.body || 'Anda memiliki pesan baru.',
        icon: '/static/images/notification-icon.png' // Opsional: Ganti path ikon Anda
    };

    // Tampilkan notifikasi
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
    console.log('[Service Worker] Notifikasi diklik.');
    event.notification.close();
    event.waitUntil(clients.openWindow('/dashboard_kajur'));
});
