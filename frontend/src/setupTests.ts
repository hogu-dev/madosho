import "@testing-library/jest-dom";

// Under jsdom + Node's native undici, react-router v7 navigation builds
// `new Request(url, { signal })` with jsdom's AbortController.signal, which
// undici's Request rejects ("Expected signal to be an instance of AbortSignal").
// This is a test-harness-only mismatch; real browsers are fine. Wrap Request so
// an incompatible signal is dropped, letting navigation-triggered tests run.
//
// The catch is deliberately narrow: it only retries (sans signal) when the
// failure is the AbortSignal-instance mismatch. Any other Request construction
// error (bad URL, invalid method, body/method conflict) is rethrown unchanged,
// so a genuinely malformed Request in a future test still surfaces its real error.
const RealRequest = globalThis.Request;
class PatchedRequest extends RealRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    try {
      super(input, init);
    } catch (err) {
      const isSignalMismatch =
        init?.signal != null &&
        err instanceof TypeError &&
        /AbortSignal/.test(err.message);
      if (!isSignalMismatch) throw err;
      const { signal: _signal, ...rest } = init;
      super(input, rest);
    }
  }
}
globalThis.Request = PatchedRequest as typeof Request;
