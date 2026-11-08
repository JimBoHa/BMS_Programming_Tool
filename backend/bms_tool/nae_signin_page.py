"""Site-neutral native NAE credential qualification page; no vendor UI embedding."""

import re
from html import escape


def native_signin_page(*, name, origin, device, model, firmware, certificate_sha256):
    values = {
        "ENGINE_NAME": name,
        "ENGINE_ORIGIN": origin,
        "ENGINE_DEVICE": device,
        "ENGINE_MODEL": model,
        "ENGINE_FIRMWARE": firmware,
        "CERTIFICATE_SHA256": certificate_sha256,
    }
    for value in values.values():
        if type(value) is not str or len(value) > 512:
            raise ValueError("Invalid native sign-in context.")
    return re.sub(r"__([A-Z_]+)__", lambda match: escape(values[match[1]], quote=True), PAGE)


PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>BMS Studio — native NAE sign-in</title>
  <style>
    body {font:16px system-ui; background:#f4f8f9; color:#183440;
          max-width:760px; margin:4rem auto; padding:0 24px}
    label {display:block; margin:24px 0}
    input {display:block; box-sizing:border-box; width:100%; padding:12px;
           border:1px solid #a7c0c3; border-radius:5px; font:inherit}
    button {font:inherit; padding:12px 24px; border:1px solid #007e7a;
            border-radius:5px; background:#007e7a; color:white; cursor:pointer}
    button:disabled {opacity:.6; cursor:default}
    :focus-visible {outline:3px solid #345d8a; outline-offset:3px}
    .muted {color:#526c77}
    #result {white-space:pre-wrap; margin-top:24px}
    details {margin-top:24px}
    code {word-break:break-all}
  </style>
</head>
<body>
  <p class="muted">BMS STUDIO · NATIVE NAE QUALIFICATION</p>
  <h1>Sign in directly to __ENGINE_NAME__</h1>
  <p>Engine: <strong>__ENGINE_ORIGIN__</strong> · __ENGINE_DEVICE__ ·
     __ENGINE_MODEL__ · Firmware __ENGINE_FIRMWARE__</p>
  <p>BMS Tool sends this login to the NAE’s own HTTPS service.
     No JCT/SCT service or application participates.</p>
  <form id="signin">
    <label>NAE account username<input id="username" autocomplete="off" required></label>
    <label>NAE account password<input id="password" type="password" autocomplete="off" required></label>
    <button id="connect" type="submit" disabled>Sign in directly to NAE</button>
  </form>
  <noscript>Enable JavaScript to sign in. No credentials have been sent.</noscript>
  <p class="muted">The password clears on submission and is not saved. The native
     session stays in backend memory. This qualification screen does not apply
     configuration or transfer a program.</p>
  <button id="disconnect" type="button" hidden>Close native engine session</button>
  <div id="result" role="status" aria-live="polite"></div>
  <details><summary>Trusted selected-engine certificate</summary>
    <code>__CERTIFICATE_SHA256__</code>
  </details>
  <script>
    let studioToken;
    async function call(path, body) {
      if (!studioToken) {
        const response = await fetch('/api/session');
        const session = await response.json();
        if (!response.ok || typeof session.token !== 'string' || !session.token) {
          throw new Error('Local BMS session unavailable. Reload and try again.');
        }
        studioToken = session.token;
      }
      const response = await fetch('/api/nae-qualification/' + path, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Studio-Token': studioToken},
        body: JSON.stringify(body)
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || 'Native request failed');
      return value;
    }
    const form = document.getElementById('signin');
    const result = document.getElementById('result');
    const close = document.getElementById('disconnect');
    const button = document.getElementById('connect');
    form.onsubmit = async event => {
      event.preventDefault();
      if (button.disabled) return;
      button.disabled = true;
      const password = document.getElementById('password');
      const secret = password.value;
      password.value = '';
      result.textContent = 'Verifying the selected NAE and signing in directly…';
      try {
        const response = await call('login', {
          username: document.getElementById('username').value,
          password: secret
        });
        form.hidden = true;
        close.hidden = false;
        result.textContent = 'Native NAE login accepted for ' + response.account +
          '.\nNo JCT/SCT dependency. No configuration writes performed.';
      } catch (error) {
        result.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    };
    close.onclick = async () => {
      close.disabled = true;
      try {
        await call('close', {});
        form.hidden = false;
        close.hidden = true;
        result.textContent = 'Native engine session closed.';
      } catch (error) {
        result.textContent = error.message;
      } finally {
        close.disabled = false;
      }
    };
    // Disabled in HTML until all submit handlers have installed successfully.
    button.disabled = false;
  </script>
</body>
</html>
"""
