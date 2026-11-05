// Exercise the shipped browser logic with DOM stubs; no browser or network required.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const element = () => ({
  handlers: {}, hidden: true, disabled: false,
  addEventListener(name, callback) { this.handlers[name] = callback; },
});

const slides = ["abc", "def", "ghi"].map((id) => ({ id, hidden: false }));
const previous = element(), next = element(), fullscreen = element();
const counter = { textContent: "" };
const deck = element();
deck.querySelectorAll = () => slides;
deck.querySelector = (selector) => ({ "[data-previous]": previous, "[data-next]": next, "[data-counter]": counter, "[data-fullscreen]": fullscreen })[selector];
const location = { hash: "#sdef" };
vm.runInNewContext(readFileSync(new URL("../static/js/deck.js", import.meta.url), "utf8"), {
  document: { querySelectorAll: () => [deck] },
  window: { addEventListener() {} }, location,
  history: { replaceState(_state, _title, hash) { location.hash = hash; } },
});
assert.equal(counter.textContent, "2 / 3", "legacy slide fragment should select its slide");
assert.equal(slides[1].hidden, false);
next.handlers.click();
assert.equal(counter.textContent, "3 / 3");
assert.equal(next.disabled, true);
assert.equal(location.hash, "#ghi");
let prevented = false;
deck.handlers.keydown({ key: "Home", target: { matches: () => false }, preventDefault() { prevented = true; } });
assert.equal(prevented, true);
assert.equal(counter.textContent, "1 / 3");
assert.equal(previous.disabled, true);
deck.handlers.keydown({ key: "ArrowRight", target: { matches: () => true }, preventDefault() { throw Error("Do not intercept text inputs"); } });
assert.equal(counter.textContent, "1 / 3");

function recording(source) {
  const button = element();
  const container = {
    dataset: { recording: source }, frame: null,
    querySelector() { return button; },
    replaceChildren(frame) { this.frame = frame; },
  };
  vm.runInNewContext(readFileSync(new URL("../static/js/recording.js", import.meta.url), "utf8"), {
    URL,
    document: { querySelectorAll: () => [container], createElement: (tag) => ({ tag }) },
  });
  return { container, button };
}
const youtube = recording("https://www.youtube.com/watch?v=GAstY027AXg&t=1079s");
assert.equal(youtube.container.frame, null, "video must not load before clicking");
assert.equal(youtube.button.hidden, false);
youtube.button.handlers.click();
const embed = new URL(youtube.container.frame.src);
assert.equal(embed.hostname, "www.youtube-nocookie.com");
assert.equal(embed.pathname, "/embed/GAstY027AXg");
assert.equal(embed.searchParams.get("start"), "1079");
const vimeo = recording("https://vimeo.com/123456?h=example");
vimeo.button.handlers.click();
assert.equal(new URL(vimeo.container.frame.src).hostname, "player.vimeo.com");
assert.equal(new URL(vimeo.container.frame.src).searchParams.get("h"), "example");
assert.equal(recording("https://example.com/watch?v=GAstY027AXg").button.hidden, true);
console.log("PASS: slide fragments, navigation, keyboard handling, and click-to-load recording players");
