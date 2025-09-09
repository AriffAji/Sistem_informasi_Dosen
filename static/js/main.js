// main.js
async function registerServiceWorker() {
  if ('serviceWorker' in navigator && 'PushManager' in window) {
    try {
      const reg = await navigator.serviceWorker.register('/service-worker.js');
      console.log('SW registered:', reg);
      return reg;
    } catch (e) {
      console.error('SW registration failed:', e);
      throw e;
    }
  } else {
    throw new Error('ServiceWorker atau PushManager tidak didukung di browser ini.');
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function askNotificationPermission() {
  const perm = await Notification.requestPermission();
  return perm === 'granted';
}

async function subscribeUser() {
  try {
    const reg = await navigator.serviceWorker.ready;

    // ambil public key dari server
    const r = await fetch('/vapid_public_key');
    if (!r.ok) throw new Error('Gagal ambil VAPID key dari server');
    const { publicKey } = await r.json();
    const applicationServerKey = urlBase64ToUint8Array(publicKey);

    // subscribe
    const subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey
    });

    // kirim subscription ke server
    const res = await fetch('/api/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subscription)
    });
    if (!res.ok) throw new Error('Gagal menyimpan subscription ke server');

    console.log('User is subscribed and subscription saved on server.');
    return subscription;
  } catch (err) {
    console.error('subscribeUser error', err);
    throw err;
  }
}

// helper: cek apakah sudah subscribe
async function isSubscribed() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  return !!sub;
}

// contoh binding ke tombol
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('btn-enable-push');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    try {
      const ok = await askNotificationPermission();
      if (!ok) { alert('Izin notifikasi ditolak'); return; }

      await registerServiceWorker();
      await subscribeUser();
      alert('Notifikasi diaktifkan');
    } catch (e) {
      alert('Gagal mengaktifkan notifikasi: ' + e.message);
    }
  });
});
