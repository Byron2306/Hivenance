/* Minimal shims for WalletConnect UMD builds that expect Node globals. */
(function () {
  if (typeof window === "undefined") return;

  if (typeof window.process === "undefined") {
    window.process = { env: {} };
  } else if (typeof window.process.env === "undefined") {
    window.process.env = {};
  }

  if (typeof window.global === "undefined") {
    window.global = window;
  }

  if (typeof window.Buffer === "undefined") {
    function BufferShim() {}
    BufferShim.from = function (val) { return val; };
    BufferShim.isBuffer = function () { return false; };
    window.Buffer = BufferShim;
  }
})();
