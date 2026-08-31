// In your existing checkScheduledAlert() function,
// immediately AFTER:
//     await loadFnoAlerts(true);
//
// add:
await fetch(
    "/api/whatsapp/evaluate",
    { method: "POST" }
);
