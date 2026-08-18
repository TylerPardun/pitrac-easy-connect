import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from .service import CompanionService


PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PiTrac Easy Connect</title>
  <style>
    :root { color-scheme: dark; --bg:#0c1210; --panel:#151d19; --line:#2b3931;
      --text:#f4f7f5; --muted:#9eada5; --green:#58d68d; --red:#ff786f;
      --yellow:#f7c85d; --button:#dff86d; --button-text:#172008; }
    * { box-sizing:border-box; }
    body { margin:0; background:radial-gradient(circle at 15% -10%,#22372b 0,#0c1210 38%);
      color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { width:min(760px,calc(100% - 32px)); margin:48px auto; }
    .eyebrow { color:var(--green); font-weight:700; letter-spacing:.12em;
      text-transform:uppercase; font-size:.75rem; }
    h1 { margin:.4rem 0 .5rem; font-size:clamp(2rem,6vw,3.6rem); line-height:1; }
    .intro { color:var(--muted); font-size:1.08rem; line-height:1.55; max-width:620px; }
    .panel { margin-top:28px; padding:24px; border:1px solid var(--line); border-radius:20px;
      background:rgba(21,29,25,.94); box-shadow:0 18px 60px rgba(0,0,0,.25); }
    h2 { margin:0 0 8px; font-size:1.1rem; }
    .choice-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:16px; }
    .choice { text-align:left; color:var(--text); background:#101713; border:1px solid var(--line);
      border-radius:14px; padding:18px; cursor:pointer; transition:.15s ease; }
    .choice:hover { border-color:#52685b; transform:translateY(-1px); }
    .choice.selected { border-color:var(--green); box-shadow:0 0 0 2px rgba(88,214,141,.13); }
    .choice strong { display:block; font-size:1.05rem; }
    .choice span { display:block; color:var(--muted); margin-top:5px; line-height:1.35; }
    .status-list { margin-top:18px; border-top:1px solid var(--line); }
    .status-row { min-height:62px; display:grid; grid-template-columns:1fr auto; gap:16px;
      align-items:center; border-bottom:1px solid var(--line); }
    .status-row span { color:var(--muted); display:block; font-size:.9rem; margin-top:3px; }
    .pill { border-radius:99px; padding:6px 10px; font-weight:750; font-size:.78rem;
      background:#29342e; color:var(--muted); }
    .pill.good { background:rgba(88,214,141,.14); color:var(--green); }
    .pill.bad { background:rgba(255,120,111,.13); color:var(--red); }
    .actions { display:flex; flex-wrap:wrap; gap:12px; margin-top:22px; }
    button.action { border:0; border-radius:12px; padding:13px 18px; font-weight:800;
      font-size:.95rem; cursor:pointer; background:var(--button); color:var(--button-text); }
    button.secondary { background:#2a352f; color:var(--text); }
    button:disabled { opacity:.5; cursor:wait; }
    .message { margin-top:16px; min-height:52px; padding:14px 16px; border-radius:12px;
      background:#0f1612; border:1px solid var(--line); color:var(--muted); line-height:1.4; }
    .message.good { border-color:rgba(88,214,141,.4); color:var(--green); }
    .message.bad { border-color:rgba(255,120,111,.4); color:var(--red); }
    .prototype { margin-top:16px; color:var(--muted); font-size:.84rem; line-height:1.45; }
    @media (max-width:580px) { main{margin:28px auto}.choice-grid{grid-template-columns:1fr}.panel{padding:18px} }
  </style>
</head>
<body>
<main>
  <div class="eyebrow">Desktop prototype</div>
  <h1>PiTrac Easy Connect</h1>
  <p class="intro">Choose the golf simulator on this computer. Easy Connect checks the local connection and sends a test shot before play.</p>

  <section class="panel">
    <h2>1. Select the simulator</h2>
    <div class="choice-grid">
      <button class="choice" data-sim="gspro"><strong>GSPro</strong><span>Uses GSPro Open Connect</span></button>
      <button class="choice" data-sim="e6"><strong>E6 Connect</strong><span>Uses E6 TruSimAPI</span></button>
    </div>

    <div class="status-list">
      <div class="status-row">
        <div><strong>PiTrac device</strong><span id="piMessage">Not paired in this milestone</span></div>
        <div class="pill">NEXT MILESTONE</div>
      </div>
      <div class="status-row">
        <div><strong id="simLabel">Simulator</strong><span id="endpoint">Not checked</span></div>
        <div id="simPill" class="pill">NOT CHECKED</div>
      </div>
    </div>

    <div class="actions">
      <button id="check" class="action secondary">Check connection</button>
      <button id="test" class="action">Send test shot</button>
    </div>
    <div id="message" class="message">Select GSPro or E6, then check the connection.</div>
    <div class="prototype">For this prototype, run the matching mock simulator on the Mac. A later milestone will pair this screen with the Raspberry Pi and actual Windows simulator software.</div>
  </section>
</main>
<script>
  const choiceButtons = [...document.querySelectorAll('.choice')];
  const checkButton = document.getElementById('check');
  const testButton = document.getElementById('test');
  const message = document.getElementById('message');
  const simPill = document.getElementById('simPill');

  async function request(path, method='GET', body=null) {
    const options = {method, headers:{'Content-Type':'application/json'}};
    if (body) options.body = JSON.stringify(body);
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Request failed');
    return data;
  }

  function render(data) {
    choiceButtons.forEach(button => button.classList.toggle('selected', button.dataset.sim === data.simulator));
    document.getElementById('simLabel').textContent = data.simulatorLabel;
    document.getElementById('endpoint').textContent = `Local connection ${data.endpoint}`;
    document.getElementById('piMessage').textContent = data.pi.message;
    message.textContent = data.message;
    message.className = `message ${data.connected ? 'good' : (data.message === 'Not checked yet' ? '' : 'bad')}`;
    simPill.textContent = data.ready ? 'READY' : (data.connected ? 'CONNECTED' : (data.message === 'Not checked yet' ? 'NOT CHECKED' : 'NOT READY'));
    simPill.className = `pill ${data.connected ? 'good' : (data.message === 'Not checked yet' ? '' : 'bad')}`;
  }

  async function busy(button, operation) {
    checkButton.disabled = true; testButton.disabled = true;
    const original = button.textContent; button.textContent = 'Working…';
    try { render(await operation()); }
    catch (error) { message.textContent = error.message; message.className = 'message bad'; }
    finally { checkButton.disabled = false; testButton.disabled = false; button.textContent = original; }
  }

  choiceButtons.forEach(button => button.addEventListener('click', () => busy(button,
    () => request('/api/select', 'POST', {simulator:button.dataset.sim}))));
  checkButton.addEventListener('click', () => busy(checkButton, () => request('/api/check', 'POST')));
  testButton.addEventListener('click', () => busy(testButton, () => request('/api/test-shot', 'POST')));
  request('/api/status').then(render).catch(error => { message.textContent = error.message; });
</script>
</body>
</html>
"""


class CompanionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: Any, service: CompanionService):
        self.service = service
        super().__init__(address, CompanionHandler)


class CompanionHandler(BaseHTTPRequestHandler):
    server: CompanionHTTPServer

    def do_GET(self) -> None:
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/status":
            self._send_json(HTTPStatus.OK, self.server.service.status())
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        try:
            if self.path == "/api/select":
                payload = self._read_json()
                self._send_json(
                    HTTPStatus.OK,
                    self.server.service.select(str(payload.get("simulator", ""))),
                )
                return
            if self.path == "/api/check":
                self._send_json(HTTPStatus.OK, self.server.service.check())
                return
            if self.path == "/api/test-shot":
                self._send_json(HTTPStatus.OK, self.server.service.test_shot())
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length") from exc
        if length > 65536:
            raise ValueError("Request is too large")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def _send_json(self, status: HTTPStatus, value: Dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return
