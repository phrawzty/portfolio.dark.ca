"use strict";
(async () => {
  const container = document.getElementById("appearance-map");
  if (!container || !window.L) return;
  try {
    const response = await fetch("/appearances-map.json");
    const data = await response.json();
    if (!data.points.length) { container.hidden = true; return; }
    const map = L.map(container, { worldCopyJump: true });
    if (data.tiles) L.tileLayer(data.tiles, { maxZoom: 19, attribution: data.attribution }).addTo(map);
    const bounds = [];
    const groups = new Map();
    data.points.forEach((point) => {
      const key = point.place;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(point);
    });
    groups.forEach((points) => {
      const point = points[0];
      const node = document.createElement("div");
      const heading = document.createElement("strong"); heading.textContent = point.location;
      node.append(heading);
      const list = document.createElement("ul");
      points.forEach((appearance) => {
        const row = document.createElement("li");
        const link = document.createElement("a");
        link.href = appearance.url; link.textContent = appearance.title;
        const event = document.createElement("span");
        event.textContent = ` · ${appearance.event}${appearance.location_label !== appearance.location ? ` · ${appearance.location_label}` : ""}`;
        row.append(link, event); list.append(row);
      });
      node.append(list);
      L.circleMarker([point.lat, point.lng], { radius: 5, color: "#ffa86a", fillOpacity: 0.8 }).bindPopup(node).addTo(map);
      bounds.push([point.lat, point.lng]);
    });
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 7 });
  } catch (_) { container.hidden = true; }
})();
