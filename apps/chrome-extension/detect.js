/**
 * Pure publication-number detection shared by the content script and tests.
 * Supported page shapes (2025/2026 URL layouts):
 *  - Google Patents: https://patents.google.com/patent/US10102057B2/en
 *  - Espacenet search: https://worldwide.espacenet.com/patent/search?q=pn%3DEP1234567A1
 *  - Espacenet publication: .../patent/EP1234567A1 (path form)
 * No page scraping beyond the URL happens anywhere in this extension.
 */
function detectPublicationNumber(urlString) {
  let url;
  try {
    url = new URL(urlString);
  } catch {
    return null;
  }

  const candidate = (value) => {
    if (!value) return null;
    const v = decodeURIComponent(value).trim().toUpperCase();
    // Publication numbers: 2-letter country + digits + 1-2 letter/number kind code
    return /^[A-Z]{2}\d{5,12}[A-Z]\d?$/.test(v) ? v : null;
  };

  if (url.hostname.endsWith("patents.google.com")) {
    const m = url.pathname.match(/\/patent\/([A-Z]{2}\d{5,12}[A-Z]\d?)/i);
    if (m) return candidate(m[1]);
  }

  if (url.hostname.endsWith("espacenet.com")) {
    const q = url.searchParams.get("q");
    if (q) {
      const pn = q.match(/pn\s*=\s*([A-Za-z]{2}\d{5,12}[A-Za-z]\d?)/i);
      if (pn) return candidate(pn[1]);
      const direct = candidate(q);
      if (direct) return direct;
    }
    const m = url.pathname.match(/\/patent\/([A-Za-z]{2}\d{5,12}[A-Za-z]\d?)/);
    if (m) return candidate(m[1]);
  }

  return null;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { detectPublicationNumber };
}
