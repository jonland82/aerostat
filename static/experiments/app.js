"use strict";

const views = {
  traversals: "/experiment-results/three-flight-globe/index.html",
  altitudes: "/experiment-results/altitude-histogram/index.html",
  deviation: "/experiment-results/geodesic-deviation/index.html"
};

function selectView(name, updateHistory = true) {
  const selectedName = views[name] ? name : "traversals";

  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.view === selectedName;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });

  document.querySelectorAll(".view").forEach((frame) => {
    const active = frame.dataset.view === selectedName;
    frame.classList.toggle("active", active);
    if (active && !frame.src) frame.src = views[selectedName];
  });

  if (updateHistory) history.pushState({ view: selectedName }, "", `?view=${selectedName}`);
}

window.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => selectView(tab.dataset.view));
  });
  selectView(new URLSearchParams(location.search).get("view"), false);
});

window.addEventListener("popstate", () => {
  selectView(new URLSearchParams(location.search).get("view"), false);
});
