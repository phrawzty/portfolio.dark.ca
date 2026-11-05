"use strict";
document.querySelectorAll("[data-deck]").forEach((deck) => {
  const slides = [...deck.querySelectorAll("[data-slide]")];
  const previous = deck.querySelector("[data-previous]");
  const next = deck.querySelector("[data-next]");
  const counter = deck.querySelector("[data-counter]");
  let current = 0;
  function show(index, updateHash = true) {
    current = Math.max(0, Math.min(index, slides.length - 1));
    slides.forEach((slide, i) => { slide.hidden = i !== current; });
    previous.disabled = current === 0;
    next.disabled = current === slides.length - 1;
    counter.textContent = `${current + 1} / ${slides.length}`;
    if (updateHash) history.replaceState(null, "", `#${slides[current].id}`);
  }
  function fromHash() {
    const fragment = decodeURIComponent(location.hash.slice(1));
    const index = slides.findIndex((slide) => slide.id === fragment || `s${slide.id}` === fragment);
    show(index < 0 ? 0 : index, false);
  }
  previous.addEventListener("click", () => show(current - 1));
  next.addEventListener("click", () => show(current + 1));
  deck.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea, select")) return;
    const actions = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: slides.length - 1 };
    if (event.key in actions) { event.preventDefault(); show(actions[event.key]); }
  });
  deck.querySelector("[data-fullscreen]").addEventListener("click", async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (deck.requestFullscreen) await deck.requestFullscreen();
  });
  window.addEventListener("hashchange", fromHash);
  fromHash();
});
