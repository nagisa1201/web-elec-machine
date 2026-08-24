/* Thin fetch wrapper around the JSON API. */
(function () {
  "use strict";

  async function getJSON(path, params) {
    const url = new URL(path, window.location.origin);
    if (params) {
      Object.keys(params).forEach((key) => {
        if (params[key] !== undefined && params[key] !== null && params[key] !== "") {
          url.searchParams.set(key, params[key]);
        }
      });
    }
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("HTTP " + response.status + " for " + path);
    }
    return response.json();
  }

  const api = {
    health: () => getJSON("/api/health"),
    meters: () => getJSON("/api/meters"),
    days: (meter) => getJSON("/api/days", { meter }),
    realtime: (meter, minutes) => getJSON("/api/realtime", { meter, minutes }),
    series: (meter, date) => getJSON("/api/series", { meter, date }),
    stats: (meter, date) => getJSON("/api/stats", { meter, date }),
  };

  window.api = api;
})();
