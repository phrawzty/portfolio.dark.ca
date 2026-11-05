"use strict";
let previous;
setInterval(async () => {
  try {
    const response = await fetch("/__portfolio_version", { cache: "no-store" });
    if (!response.ok) return;
    const current = await response.text();
    if (previous && previous !== current) location.reload();
    previous = current;
  } catch (_) { /* Keep the last successful preview while rebuilding. */ }
}, 1000);
