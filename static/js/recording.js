"use strict";
document.querySelectorAll("[data-recording]").forEach((container) => {
  let source;
  try { source = new URL(container.dataset.recording); } catch (_) { return; }
  let embed;
  if (["www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com"].includes(source.hostname)) {
    const id = source.hostname === "youtu.be" ? source.pathname.slice(1) : source.searchParams.get("v");
    if (!/^[A-Za-z0-9_-]{11}$/.test(id || "")) return;
    embed = new URL(`https://www.youtube-nocookie.com/embed/${id}`);
    const start = source.searchParams.get("t") || source.searchParams.get("start") || "";
    if (/^\d+s?$/.test(start)) embed.searchParams.set("start", parseInt(start, 10));
  } else if (["vimeo.com", "www.vimeo.com"].includes(source.hostname) && /^\/\d+$/.test(source.pathname)) {
    embed = new URL(`https://player.vimeo.com/video${source.pathname}`);
    if (source.searchParams.has("h")) embed.searchParams.set("h", source.searchParams.get("h"));
  } else return;
  const button = container.querySelector("[data-play-recording]");
  button.hidden = false;
  button.addEventListener("click", () => {
    embed.searchParams.set("autoplay", "1");
    const frame = document.createElement("iframe");
    frame.src = embed.href;
    frame.title = "Presentation recording";
    frame.allow = "autoplay; fullscreen; picture-in-picture";
    frame.allowFullscreen = true;
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    container.replaceChildren(frame);
  });
});
