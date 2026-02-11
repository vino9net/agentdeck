/* Service worker for Web Push notifications */

self.addEventListener("push", (event) => {
  if (!event.data) return;

  const data = event.data.json();

  // Suppress if app is visible in a focused window
  const showPromise = self.clients
    .matchAll({ type: "window", includeUncontrolled: false })
    .then((clients) => {
      const hasFocused = clients.some((c) => c.focused);
      if (hasFocused) return;
      return self.registration.showNotification(data.title || "AgentDeck", {
        body: data.body || "Session needs input",
        icon: "/static/icon-192.png",
        badge: "/static/icon-192.png",
        tag: data.session_id || "default",
        renotify: true,
        data: { url: data.url, session_id: data.session_id },
      });
    });

  event.waitUntil(showPromise);
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const url = event.notification.data?.url || "/";

  const focusPromise = self.clients
    .matchAll({ type: "window", includeUncontrolled: true })
    .then((clients) => {
      // Try to find an existing app window and navigate it
      for (const client of clients) {
        if (client.url.startsWith(self.location.origin)) {
          client.focus();
          client.navigate(url);
          return;
        }
      }
      // No existing window — open a new one
      return self.clients.openWindow(url);
    });

  event.waitUntil(focusPromise);
});
