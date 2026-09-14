/** Content script: reads only the page URL (via the shared detector) and
 * forwards the detected publication number to the service worker. */
const publicationNumber = detectPublicationNumber(window.location.href);
if (publicationNumber) {
  chrome.runtime.sendMessage({ type: "spago-patent-detected", publicationNumber });
}
