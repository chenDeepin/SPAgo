/** Side panel: shows the detected publication number and deep-links into the
 * SPAgo workspace (URL state contract: ?q=<publication number>). */
const detectedEl = document.getElementById("detected");
const openSlot = document.getElementById("open-slot");
const urlInput = document.getElementById("spago-url");

function render(publicationNumber, spagoBase) {
  if (publicationNumber) {
    detectedEl.innerHTML = `Detected: <span class="mono">${publicationNumber}</span>`;
    const base = (spagoBase || "http://localhost:8000").replace(/\/$/, "");
    openSlot.innerHTML = `<a class="button" href="${base}/?q=${encodeURIComponent(
      publicationNumber,
    )}" target="_blank">Open in SPAgo</a>`;
  } else {
    detectedEl.textContent = "No patent detected on this page.";
    openSlot.innerHTML = "";
  }
}

chrome.storage.sync.get({ spagoBase: "http://localhost:8000" }, ({ spagoBase }) => {
  urlInput.value = spagoBase;
  chrome.storage.session.get({ spagoPublicationNumber: null }, ({ spagoPublicationNumber }) =>
    render(spagoPublicationNumber, spagoBase),
  );
});

urlInput.addEventListener("change", () => {
  const spagoBase = urlInput.value.trim() || "http://localhost:8000";
  chrome.storage.sync.set({ spagoBase });
  chrome.storage.session.get({ spagoPublicationNumber: null }, ({ spagoPublicationNumber }) =>
    render(spagoPublicationNumber, spagoBase),
  );
});
