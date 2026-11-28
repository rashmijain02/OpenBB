/* OpenBB financial planning extension for Hermes WebUI (#1342).
 *
 * UMD: Node's `require` gets the pure HfpCards logic for tests; in the browser the
 * module registers with `hermesExt`. Every sidecar call goes through the same-origin
 * WebUI proxy path below, never to the sidecar port. The extension never starts a
 * chat turn. Cards and their logic land in T02.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.HfpCards = api;
    if (root.hermesExt && typeof root.hermesExt.register === "function") {
      try {
        root.hermesExt.register(api.EXTENSION_ID);
      } catch (err) {
        /* registration failure leaves the page untouched */
      }
    }
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var EXTENSION_ID = "openbb-hfp";
  var PROXY_PREFIX = "/api/extensions/" + EXTENSION_ID + "/sidecar";

  function proxyPath(path) {
    if (typeof path !== "string" || path.charAt(0) !== "/" || path.indexOf("//") !== -1) {
      throw new Error("invalid_path");
    }
    return PROXY_PREFIX + path;
  }

  return { EXTENSION_ID: EXTENSION_ID, PROXY_PREFIX: PROXY_PREFIX, proxyPath: proxyPath };
});
