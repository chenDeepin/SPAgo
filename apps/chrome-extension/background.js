/** Service worker: opens the side panel on toolbar click and relays the
 * detected publication number to the panel. No data, cache, or chemistry
 * logic lives here (PROMPT.md §3: the extension is a context bridge). */
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((err) => console.error("spago: side panel setup failed", err));

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === "spago-patent-detected") {
    chrome.storage.session.set({ spagoPublicationNumber: message.publicationNumber });
    sendResponse({ ok: true });
  }
});
