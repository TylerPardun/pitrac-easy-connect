"""The Companion window.

One line saying where things stand, and at most one thing to do about it.

Everything that is not "can I play right now" lives behind Advanced. Shot data
is not here at all — PiTrac's own dashboard already does that well, so this
links to it rather than growing a second version.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PiTrac Easy-Connect</title>
<style>
  :root{color-scheme:dark;
    --bg:#0b0f0d;--panel:#141b17;--line:#26312b;--line-soft:#1c2420;
    --text:#f2f6f3;--muted:#93a49b;--faint:#68786f;
    --green:#5ddc93;--amber:#f5c65c;--red:#ff7d73;
    --accent:#dff86d;--accent-text:#151d06}
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
    line-height:1.5;display:flex;flex-direction:column;overflow:hidden}

  /* The window's own tab strip. Hidden until there is more than one place to be. */
  .tabs{display:flex;gap:2px;padding:10px 14px 0;border-bottom:1px solid var(--line-soft);
    flex:none;background:var(--bg)}
  .tabs button{width:auto;padding:9px 16px;border:0;background:transparent;color:var(--faint);
    font-size:.88rem;font-weight:650;border-radius:9px 9px 0 0;border-bottom:2px solid transparent}
  .tabs button:hover{color:var(--muted)}
  .tabs button.on{color:var(--text);border-bottom-color:var(--accent)}
  .tabs.hidden{display:none}

  .pane{flex:1;min-height:0;overflow:auto;display:none}
  .pane.on{display:block}
  .pane.frame{overflow:hidden}
  .pane iframe{width:100%;height:100%;border:0;display:block;background:var(--bg)}
  .centre{min-height:100%;display:flex;align-items:center;justify-content:center}
  /* The window is at least 900px wide (see window.py), so this is the
     settled width, not a phone column that happens to be centred. The
     cap keeps a line of text short enough to read; the guide below
     stays narrow because one question at a time reads better that way. */
  main{width:min(820px,calc(100% - 64px));padding:40px 0}
  body.guiding main{width:min(440px,calc(100% - 40px))}
  .framehint{padding:14px 18px;color:var(--faint);font-size:.85rem;text-align:center}

  /* Shots: a table you can actually read, not a dashboard. */
  .shots{width:min(1040px,calc(100% - 64px));margin-inline:auto;padding:26px 0 40px}
  .clubrow{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  .clublabel{color:var(--muted);font-size:.88rem;font-weight:650}
  .shots select{flex:1;min-width:150px;padding:11px 13px;border-radius:10px;
    border:1px solid var(--line);background:var(--panel);color:var(--text);font:inherit}
  .clubnote{color:var(--faint);font-size:.8rem;flex-basis:100%}
  .sech{margin:26px 0 10px;font-size:.72rem;font-weight:800;letter-spacing:.13em;
    text-transform:uppercase;color:var(--faint)}
  .empty{color:var(--faint);font-size:.87rem}
  table.shot{width:100%;border-collapse:collapse;font-size:.87rem;
    font-variant-numeric:tabular-nums}
  table.shot th{text-align:left;font-size:.68rem;font-weight:800;letter-spacing:.09em;
    text-transform:uppercase;color:var(--faint);padding:0 8px 7px 0;
    border-bottom:1px solid var(--line)}
  table.shot td{padding:8px 8px 8px 0;border-bottom:1px solid var(--line-soft);color:var(--muted)}
  table.shot td:first-child{color:var(--text);font-weight:600}
  table.shot td.num{text-align:right;padding-right:14px}
  table.shot th.num{text-align:right}
  table.shot tr.lost td{color:var(--red);opacity:.75}
  .scroller{overflow-x:auto}
  .camrow{display:flex;justify-content:space-between;gap:12px;padding:9px 0;
    border-bottom:1px solid var(--line-soft);font-size:.87rem}
  .camrow span:first-child{color:var(--muted)}
  .shotgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:9px}
  .shotgrid a{display:block;border:1px solid var(--line);border-radius:9px;overflow:hidden;
    background:var(--panel);text-decoration:none}
  .shotgrid a:hover{border-color:#3b4a42}
  .shotgrid img{display:block;width:100%;height:88px;object-fit:cover;background:#0d1310}
  .shotgrid small{display:block;padding:6px 8px;color:var(--faint);font-size:.7rem;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .shotactions{margin-top:26px}
  .shotactions button{width:auto;padding:9px 15px;font-size:.85rem}

  .brand{font-size:.68rem;font-weight:800;letter-spacing:.22em;color:var(--faint);
    text-transform:uppercase;text-align:center;margin-bottom:28px}

  /* The one thing this window is for. */
  .status{display:flex;gap:16px;align-items:flex-start}
  .dot{width:11px;height:11px;border-radius:50%;flex:none;margin-top:9px;background:var(--faint);
    box-shadow:0 0 0 4px rgba(255,255,255,.03)}
  .dot.good{background:var(--green);box-shadow:0 0 0 4px rgba(93,220,147,.12)}
  .dot.busy{background:var(--amber);box-shadow:0 0 0 4px rgba(245,198,92,.12);
    animation:pulse 1.8s ease-in-out infinite}
  .dot.bad{background:var(--red);box-shadow:0 0 0 4px rgba(255,125,115,.12)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
  @media (prefers-reduced-motion:reduce){.dot.busy{animation:none}}

  h1{margin:0;font-size:1.6rem;font-weight:650;letter-spacing:-.02em;line-height:1.2}
  .sub{color:var(--muted);font-size:.95rem;margin-top:5px}
  .why{color:var(--faint);font-size:.88rem;margin-top:10px;line-height:1.45}

  .do{margin-top:26px;display:flex;flex-direction:column;gap:10px}
  /* Buttons fill their container, which is right in a narrow column and
     wrong in a wide one: a primary action stretched across 820px reads
     as a banner rather than something to press. The list beside it is
     cards, which do want the width, so this caps the actions only. */
  body:not(.guiding) .do{max-width:380px}

  .simsteps{margin:18px 0 4px;padding:0;list-style:none;counter-reset:step}
  .simsteps li{position:relative;padding:0 0 14px 30px;color:var(--muted);
    font-size:.92rem;line-height:1.55;counter-increment:step}
  .simsteps li::before{content:counter(step);position:absolute;left:0;top:0;
    width:20px;height:20px;border-radius:50%;background:var(--raise);
    color:var(--text);font-size:.72rem;font-weight:700;
    display:flex;align-items:center;justify-content:center}
  .simsteps li.done{color:var(--faint)}
  .simsteps li.done::before{content:"\2713";background:var(--accent);color:#0b0b0b}
  .board{margin-top:30px;display:grid;gap:12px;
    /* 280 rather than 236: in an 820px column the smaller minimum fits
       three across, which left the fourth card alone on a row of its
       own. Two by two is balanced at every width the window allows. */
    grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
  .board.hidden{display:none}
  .board button{text-align:left;padding:16px 18px;background:var(--card);
    border-color:var(--line);border-radius:14px;font-weight:400}
  .board button:hover:not(:disabled){border-color:var(--accent)}
  .board button:disabled{cursor:default;opacity:.55}
  /* An odd number of cards would leave the last one alone on half a row. */
  .board button:last-child:nth-child(odd){grid-column:1/-1}
  .board .t{font-weight:700;font-size:1rem;color:var(--text);display:block}
  .board .d{font-size:.85rem;color:var(--muted);margin-top:4px;display:block;
    line-height:1.4}
  button,.linkbtn{font:inherit;width:100%;text-align:center;border-radius:11px;
    padding:14px 18px;font-weight:700;cursor:pointer;border:1px solid transparent;
    text-decoration:none;display:block}
  .primary{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}
  .primary:hover{filter:brightness(1.06)}
  .quiet{background:transparent;color:var(--text);border-color:var(--line)}
  .quiet:hover{border-color:#3b4a42}
  button:disabled{opacity:.45;cursor:progress}
  button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);
    outline-offset:2px}

  .err{margin-top:20px;padding:14px 16px;border-radius:11px;
    border:1px solid rgba(255,125,115,.35);background:rgba(255,125,115,.06)}
  .err h2{margin:0 0 6px;font-size:.95rem;font-weight:650;color:var(--red)}
  .err p{margin:0;color:var(--muted);font-size:.88rem}
  .err .code{margin-top:8px;color:var(--faint);font-size:.74rem;letter-spacing:.07em;
    font-family:ui-monospace,Menlo,Consolas,monospace}

  /* An update is worth mentioning, never worth interrupting for. */
  .update{margin-top:22px;padding:13px 15px;border-radius:11px;border:1px solid var(--line);
    background:var(--panel);display:flex;gap:12px;align-items:center;justify-content:space-between}
  .update span{color:var(--muted);font-size:.87rem}
  .update button{width:auto;padding:8px 14px;font-size:.84rem;flex:none}
  .update-actions{display:flex;gap:8px;flex:none}

  /* The one thing that stays visible after the update card above is
     dismissed -- small on purpose, so "I'll deal with it later" never
     means "I can no longer find it." */
  .update-pill{margin-top:10px;padding:7px 12px;border-radius:20px;border:1px solid var(--line);
    background:var(--panel);display:flex;gap:8px;align-items:center;font-size:.8rem;
    color:var(--muted);cursor:pointer;width:fit-content}
  .update-pill.bad{border-color:var(--red);color:var(--red)}

  /* Pairing: only ever seen once. */
  .pick{margin-top:22px;display:flex;flex-direction:column;gap:8px}
  body.pairing .status,body.pairing #do,body.pairing #pick,
  body.pairing #update,body.pairing #updateIndicator,body.pairing .adv{display:none}
  /* --- practice range --- */
/*__RANGE_CSS__*/
  .raw{max-height:260px;overflow:auto;background:var(--bg);border:1px solid var(--line);
    border-radius:10px;padding:10px 12px;font-size:.72rem;line-height:1.5;
    color:var(--muted);white-space:pre;margin-top:8px}
  .wiz{margin-bottom:26px}
  .wizrail{display:flex;gap:6px;margin-bottom:10px}
  .wizrail i{height:3px;flex:1;border-radius:2px;background:var(--line)}
  .wizrail i.on{background:var(--green)}
  .wizrail i.done{background:var(--muted)}
  .wizstep{font-size:.7rem;font-weight:800;letter-spacing:.13em;
    text-transform:uppercase;color:var(--faint)}
  .help{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}
  .help summary{cursor:pointer;color:var(--muted);font-size:.86rem;list-style:none}
  .help summary::-webkit-details-marker{display:none}
  .help summary:before{content:"› ";color:var(--faint)}
  .help[open] summary:before{content:"⌄ "}
  .helpbody{color:var(--muted);font-size:.86rem;line-height:1.65;margin-top:10px}
  .helpbody ol{margin:0;padding-left:20px}
  .helpbody li{margin:6px 0}
  .helpbody code{background:var(--line);padding:1px 5px;border-radius:4px;
    font-size:.82rem}
  .askframe{width:100%;height:420px;border:1px solid var(--line);border-radius:14px;
    background:var(--bg);display:block}
  .asknote{color:var(--faint);font-size:.82rem;line-height:1.45;margin:2px 0 8px}
  .device{display:flex;justify-content:space-between;align-items:center;gap:12px;
    padding:14px 16px;border:1px solid var(--line);border-radius:11px;background:var(--panel);
    color:var(--text);cursor:pointer;text-align:left;width:100%}
  .device:hover{border-color:#3b4a42}
  .device small{display:block;color:var(--faint);margin-top:3px;font-size:.8rem}
  .tag{font-size:.68rem;font-weight:800;letter-spacing:.06em;color:var(--faint)}
  .tag.on{color:var(--green)}
  input[type=text]{width:100%;padding:16px;border-radius:11px;border:1px solid var(--line);
    background:var(--panel);color:var(--text);font:inherit;font-size:1.7rem;font-weight:700;
    letter-spacing:.34em;text-align:center;font-variant-numeric:tabular-nums}
  input[type=text]::placeholder{color:#3a4941;letter-spacing:.34em}

  /* Advanced: present, quiet, never in the way. */
  details.adv{margin-top:34px;border-top:1px solid var(--line-soft);padding-top:16px}
  details.adv > summary{list-style:none;cursor:pointer;color:var(--faint);font-size:.82rem;
    font-weight:600;letter-spacing:.02em;display:flex;align-items:center;gap:7px}
  details.adv > summary::-webkit-details-marker{display:none}
  details.adv > summary::before{content:"";width:5px;height:5px;border-right:1.5px solid currentColor;
    border-bottom:1.5px solid currentColor;transform:rotate(-45deg);transition:transform .15s}
  details.adv[open] > summary::before{transform:rotate(45deg)}
  details.adv > summary:hover{color:var(--muted)}
  .advbody{margin-top:18px;display:flex;flex-direction:column;gap:9px}
  .advbody h3{margin:10px 0 2px;font-size:.72rem;font-weight:800;letter-spacing:.13em;
    text-transform:uppercase;color:var(--faint)}
  .advbody button,.advbody .linkbtn{padding:11px 14px;font-size:.9rem;font-weight:600}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:9px}
  .danger{border-color:rgba(255,125,115,.3);color:var(--red)}
  .danger:hover{border-color:rgba(255,125,115,.55)}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;font-size:.8rem;color:var(--faint);
    margin-top:6px}
  .kv dd{margin:0;color:var(--muted);word-break:break-all}
  .note{padding:12px 14px;border-radius:10px;background:var(--panel);border:1px solid var(--line);
    color:var(--muted);font-size:.85rem}
  .note.good{border-color:rgba(93,220,147,.35);color:var(--green)}
  .note pre{margin:0;white-space:pre-wrap;font:inherit}
  .hidden{display:none}
</style>
</head>
<body>
<nav class="tabs hidden" id="tabs">
  <button data-pane="play" class="on">Play</button>
  <button data-pane="simulator">Play mode</button>
  <button data-pane="range">Range</button>
  <button data-pane="shots">Shots</button>
  <button data-pane="pitrac">PiTrac</button>
  <button data-pane="setup">Setup</button>
</nav>

<div class="pane on" id="pane-play"><div class="centre">
<main>
  <div class="brand">PiTrac Easy-Connect</div>

  <div class="wiz hidden" id="wiz">
    <div class="wizrail" id="wizRail"></div>
    <div class="wizstep" id="wizStep"></div>
  </div>

  <div class="status">
    <div class="dot" id="dot"></div>
    <div style="flex:1">
      <h1 id="head">Starting</h1>
      <div class="sub" id="sub"></div>
      <div class="why" id="why"></div>
    </div>
  </div>

  <div id="err"></div>

  <details class="help hidden" id="help">
    <summary id="helpTitle"></summary>
    <div class="helpbody" id="helpBody"></div>
  </details>

  <div class="do" id="do"></div>

  <!-- Where to go next, shown once setup is done. The tab bar says the
       same thing in five words; this says it with the state of each
       place attached, which is what tells you which one you wanted. -->
  <div class="board hidden" id="board"></div>

  <!-- Stays put once an update matters, whether or not the card below has
       been dismissed -- see renderUpdateIndicator(). -->
  <div class="update-pill hidden" id="updateIndicator"></div>
  <div id="update"></div>

  <div class="pick hidden" id="pick"></div>

  <!-- This computer's own saved pairings. Reachable regardless of setup or
       link state, so a pairing for a PiTrac that can never answer again
       (reset, replaced) can always be found and removed locally, even
       during first run and even when it is not the device just found. -->
  <div class="pick hidden" id="knownPis"></div>

  <div class="pick hidden" id="askBox">
    <iframe class="askframe" id="askFrame" title="PiTrac setup page"></iframe>
    <div class="asknote" id="askNote"></div>
    <button class="quiet" id="cancelPair">Back</button>
  </div>

  <details class="adv" id="adv">
    <summary>Advanced</summary>
    <div class="advbody">
      <h3>Play mode</h3>
      <div class="row2">
        <button class="quiet" data-sim="local">Local Range</button>
        <button class="quiet" data-sim="gspro">GSPro</button>
      </div>

      <h3>PiTrac</h3>
      <button class="quiet" id="setupLink">Open the PiTrac setup page</button>
      <button class="quiet" id="testShot">Send a test shot</button>
      <button class="quiet" id="pairAnotherComputer">Add another computer</button>
      <button class="quiet" id="restart">Restart PiTrac</button>
      <button class="quiet danger" id="shutdown">Shut down PiTrac safely</button>

      <h3>Backup</h3>
      <button class="quiet" id="makeBackup">Save a backup</button>
      <button class="quiet" id="fullBackup">Save a complete recovery backup</button>
      <label class="linkbtn quiet" for="bkFile" style="cursor:pointer">Restore from a file</label>
      <input type="file" id="bkFile" accept=".pitracbackup,.json,application/json" class="hidden">
      <div id="bkPreview"></div>

      <h3>PiTrac's software</h3>
      <button class="quiet" id="checkPiUpdate">Check desktop and PiTrac for updates</button>
      <div id="piUpdate"></div>

      <h3>What PiTrac sent</h3>
      <button class="quiet" id="showRaw">Show the last shots as received</button>
      <div id="rawShots"></div>

      <h3>This computer</h3>
      <button class="quiet danger" id="forget">Unpair this computer</button>
      <button class="quiet" id="setupAgain">Run setup again</button>
      <button class="quiet" id="quit">Stop Easy-Connect</button>

      <h3>Details</h3>
      <dl class="kv" id="kv"></dl>
      <div id="note"></div>
    </div>
  </details>
</main>
</div></div>

<!--__RANGE_MARKUP__-->

<div class="pane" id="pane-simulator"><div class="shots">
  <h3 class="sech">How do you want to play?</h3>
  <div class="row2">
    <button class="quiet" data-sim="local">Local Range</button>
    <button class="quiet" data-sim="gspro">GSPro</button>
  </div>
  <div class="why" id="simNote"></div>

  <h3 class="sech" id="simSection">Connection</h3>
  <div class="status">
    <div class="dot" id="simDot"></div>
    <div style="flex:1">
      <h1 id="simHead" style="font-size:1.15rem">Not connected</h1>
      <div class="why" id="simWhy"></div>
    </div>
  </div>

  <div class="simsteps" id="simSteps"></div>

  <div class="row2" id="simButtons">
    <button class="quiet" id="simCheck">Check again</button>
    <button class="quiet" id="simTest">Send a test shot</button>
  </div>

  <div class="why" id="simWhere"></div>
</div></div>

<div class="pane" id="pane-shots"><div class="shots">
  <div class="clubrow">
    <label class="clublabel" for="club">Club</label>
    <select id="club"></select>
    <span class="clubnote" id="clubNote"></span>
  </div>

  <h3 class="sech">By club</h3>
  <div id="byClub" class="empty">No shots recorded yet.</div>

  <h3 class="sech">Recent shots</h3>
  <div id="recent" class="empty"></div>

  <h3 class="sech">Shot images</h3>
  <div id="images" class="empty">PiTrac saves an image of each shot it measures.</div>

  <h3 class="sech">Cameras</h3>
  <div id="cameras" class="empty">Checking…</div>

  <div class="shotactions">
    <button class="quiet" id="clearShots">Clear shot history</button>
  </div>
</div></div>

<div class="pane frame" id="pane-pitrac">
  <div class="framehint" id="pitracHint">Connect to PiTrac to see shot data.</div>
  <iframe id="pitracFrame" title="PiTrac dashboard"></iframe>
</div>

<div class="pane frame" id="pane-setup">
  <div class="framehint" id="setupHint">Connect to PiTrac to change its settings.</div>
  <iframe id="setupFrame" title="PiTrac setup"></iframe>
</div>

<script>
"use strict";
const $=id=>document.getElementById(id);
let status=null, busy=false;
//: Discovery is a real network broadcast, not a cheap lookup. These stop the
//: 3-second status-poll render loop from launching a fresh search on every
//: single render while unlinked, which is what made a few minutes of sitting
//: on the "find your PiTrac" screen turn into dozens of broadcasts.
let searchInFlight=false, lastSearchAt=0;
const SEARCH_CACHE_MS=15000;
//: Codes whose next step is "remove the old pairing" rather than any of the
//: existing recovery flows (rate limiting, the normal pairing panel, a
//: generic dropped connection).
const STALE_PI_CODES=new Set(__STALE_PI_CODES_JSON__);
//: Which of the window's tabs is showing. Declared here because present() has
//: to be able to send the window back to Play when the tabs disappear.
let pane="play";
//: True while the "PiTrac will not take another computer" panel is up.
const asking=()=>!$("askBox").classList.contains("hidden");

function apiOptions(body){
  // This header is the browser boundary for the loopback API. A website open
  // on the computer cannot attach it cross-origin without a preflight, which
  // the server refuses. Every request made by the shipped page goes through
  // this helper, including reads and downloads.
  const options={method: body===undefined?"GET":"POST", headers:{"X-PiTrac-App":"1"}};
  if(body!==undefined){options.headers["Content-Type"]="application/json";options.body=JSON.stringify(body);}
  return options;
}

async function api(path, body){
  const options=apiOptions(body);
  const response=await fetch(path, options);
  const data=await response.json().catch(()=>({}));
  if(!response.ok){const e=new Error((data.error&&data.error.failed)||"That did not work");e.info=data.error;throw e;}
  return data;
}

async function apiDownload(path){
  const response=await fetch(path, apiOptions());
  if(!response.ok){
    const data=await response.json().catch(()=>({}));
    const e=new Error((data.error&&data.error.failed)||"That download did not work");
    e.info=data.error; throw e;
  }
  const disposition=response.headers.get("Content-Disposition")||"";
  const match=disposition.match(/filename="([^"]+)"/);
  const anchor=document.createElement("a");
  const objectUrl=URL.createObjectURL(await response.blob());
  anchor.href=objectUrl; anchor.download=match?match[1]:"PiTrac-backup.json";
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(objectUrl), 1000);
}
function esc(v){
  // Quotes as well as angle brackets. The old version set textContent and
  // read innerHTML back, which escapes & < > and leaves quotes alone -- so
  // every value dropped into a quoted attribute below could close that
  // attribute and add its own. A Wi-Fi name and a discovery reply are both
  // written by whoever is in range, and a device id of
  // x" autofocus onfocus="..." produced a button carrying a live handler.
  return String(v==null?"":v)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

function showError(error, deviceId, source){
  // Which part of the app owns the message that is up. Without this, a
  // background search cleared a connect error it had no business clearing:
  // "another computer is already connected" vanished every fifteen seconds
  // and came back on the next poll, which is the flicker this fixes.
  // Clearing it while the refusal panel is up would leave that panel with no
  // explanation of why it appeared.
  if(!error){ if(!asking()){ $("err").innerHTML=""; $("err").dataset.from=""; } return; }
  const info=error.info||{};
  // A saved pairing that can never succeed again (the enclosure was reset or
  // replaced) needs its own way out, distinct from every other recovery
  // flow: removing it is a local, no-confirmation-from-the-Pi action, so it
  // has to work even though the Pi that issued it may be unreachable.
  const stale=deviceId && info.code && STALE_PI_CODES.has(info.code);
  $("err").innerHTML=`<div class="err"><h2>${esc(info.failed||error.message)}</h2>
    ${info.nextStep?`<p>${esc(info.nextStep)}</p>`:""}
    ${info.code?`<div class="code">${esc(info.code)}</div>`:""}
    ${stale?'<button class="quiet danger" id="removeStalePairing">Remove old pairing from this computer</button>':""}</div>`;
  $("err").dataset.from = source || "action";
  if(stale){
    $("removeStalePairing").addEventListener("click",()=>run(null, async()=>{
      if(!confirm("Remove the old pairing for this PiTrac from this computer?\n\n"+
        "This only removes it here. If the enclosure still has a record of this "+
        "computer, its owner can remove that separately from the PiTrac setup page.")) return;
      await api("/api/forget-local",{deviceId});
    }));
  }
}

async function run(button, work){
  if(busy) return; busy=true;
  const label=button?button.textContent:null;
  if(button){button.disabled=true;button.textContent="Working…";}
  showError(null);
  try{ await work(); }
  catch(error){ showError(error); }
  finally{ busy=false; if(button){button.disabled=false;button.textContent=label;} await refresh(); }
}

// --- first run, led one step at a time -----------------------------------

// Someone setting this up for the first time should never have to look for the
// next thing. Until setup is finished the window shows exactly one step, in
// order, with a way forward and nothing else to press. Afterwards it gets out
// of the way and the whole app is theirs.
const WIZARD=[
  {key:"find",  label:"Connect"},
  {key:"sim",   label:"Play mode"},
  {key:"open",  label:"Open it",   gspro:true},
  {key:"test",  label:"Test shot", gspro:true},
  {key:"done",  label:"Ready"},
];
//: The Local Range has nothing to open and nothing to prove.
function wizardSteps(data){
  return WIZARD.filter(step=>!step.gspro || data.simulator==="gspro");
}
function isLocal(data){ return data.simulator==="local"; }

//: Why a play mode cannot be used on this computer, if it cannot.
function modeNote(data, value){
  const mode=(data.playModes||[]).find(m=>m.value===value);
  return (mode && mode.note) || "";
}
let wizard={started:false, simPicked:false, reachedEnclosure:false};

const CANNOT_FIND=`<ol>
  <li>Check the Raspberry Pi has power and its light is on.</li>
  <li>Give it two minutes after switching on. It is slower than a phone.</li>
  <li>If it has never been on your Wi-Fi, it makes its own network to be set up
      through. On a phone or laptop, join the Wi-Fi network called
      <code>PiTrac-</code> followed by eight characters, using the password on
      the card that came with it, then open <code>http://10.42.0.1</code> and
      follow the three steps there.</li>
  <li>Come back here and press Search again.</li>
</ol>`;

function wizardView(data){
  const linked=data.link && data.link.connected;
  const sim=data.simulatorStatus||{};
  const steps={}; (data.chain||[]).forEach(s=>steps[s.key]=s);

  if(!wizard.started) return {step:null,
    dot:"", head:"Let's get you playing", sub:"",
    why:"Connect to your PiTrac, choose how you want to play, and you're there.",
    actions:[{label:"Get started", id:"wizStart", primary:true}]};

  if(!linked) return {step:"find",
    dot:"busy", head:"Find your PiTrac", sub:"",
    why:"It needs to be powered on and on this same Wi-Fi.",
    actions:[{label:"Search again", id:"find", primary:true}], find:true,
    help:{title:"I cannot find it", body:CANNOT_FIND}};

  const name=(data.link.device&&data.link.device.displayName)||"PiTrac";

  if(steps.pitrac && !steps.pitrac.ok) return {step:"find",
    dot:"bad", head:"PiTrac needs attention", sub:esc(steps.pitrac.detail),
    why:"Connected, but the launch monitor cannot measure a shot yet. This is "+
        "usually the cameras. Fix it on PiTrac's own page, then come back.",
    actions:[{label:"Open the PiTrac setup page", id:"setup", primary:true}]};

  if(!wizard.simPicked) return {step:"sim",
    dot:"", head:"How do you want to play?", sub:name,
    why:"Local Range works on its own, with nothing else to buy or open. "+
        (modeNote(data,"gspro") || "GSPro needs its own license. ")+
        " You can change this later.",
    actions:[{label:"Local Range", id:"wizLocal", primary:true},
             {label:"GSPro", id:"wizGspro", primary:false}]};

  if(isLocal(data)) return sim.ready ? {step:"done",
    dot:"good", head:"You're ready to play", sub:"Local Range · "+name,
    why:"Hit a ball and it appears on the range. You will not see these steps "+
        "again — next time you open this it goes straight to playing.",
    actions:[{label:"Go to the range", id:"wizRange", primary:true}]}
  : {step:"sim", dot:"bad", head:"Shots cannot be saved", sub:name, why:sim.message,
    actions:[{label:"Check again", id:"check", primary:true},
             {label:"Finish later", id:"wizFinish", primary:false}]};

  if(!sim.connected) return {step:"open",
    dot:"bad", head:"Open "+esc(data.simulatorLabel), sub:name,
    why:"In GSPro, open the Open Connect screen so it is waiting for a device. "+
        modeNote(data,"gspro"),
    // Finish later, because these last steps need a simulator running and
    // the rest of the app does not. Without it, anyone who opened this
    // before starting GSPro was held here.
    actions:[{label:"Check again", id:"check", primary:true},
             {label:"Back", id:"wizBackSim", primary:false},
             {label:"Finish later", id:"wizFinish", primary:false}]};

  if(!sim.ready) return {step:"test",
    dot:"busy", head:"One test shot", sub:esc(data.simulatorLabel)+" · "+name,
    why:"This proves the whole path from the launch monitor to your simulator. "+
        "It is a real shot, so close any open round first.",
    actions:[{label:"Send a test shot", id:"test", primary:true},
             {label:"Finish later", id:"wizFinish", primary:false}]};

  return {step:"done",
    dot:"good", head:"You're ready to play", sub:esc(data.simulatorLabel)+" · "+name,
    why:"That's setup done. You will not see these steps again — next time you "+
        "open this it goes straight to playing.",
    actions:[{label:"Finish", id:"wizFinish", primary:true}]};
}

//: The places the app can take you, and what each is doing right now. The
//: enclosure's own pages need a live link -- the same rule that sends a pane
//: back to Play when the link drops -- so those two say so rather than
//: leading somewhere empty.
function boardCards(data){
  const linked=!!(data.link && data.link.connected);
  const shots=(data.shotLog&&data.shotLog.total)||0;
  const sim=data.simulatorStatus||{};
  return [
    {pane:"simulator", title:"Play mode",
     detail:isLocal(data) ? "Local Range. GSPro can be used instead."
            : sim.ready ? "Ready to play through " + esc(data.simulatorLabel || "your simulator")
            : sim.connected ? "Connected. One test shot proves the rest."
            : "Connect " + esc(data.simulatorLabel || "your simulator") + " on this computer."},
    {pane:"range", title:"Practice range",
     detail:"Ball flight, distances and shot patterns. No simulator needed."},
    {pane:"shots", title:"Shot history",
     detail:shots ? shots+(shots===1?" shot recorded":" shots recorded")
                  : "Every shot, with the club it was hit with."},
    {pane:"pitrac", title:"PiTrac dashboard", needsLink:true,
     detail:linked ? "Cameras, calibration and shot images."
                   : "Connect to PiTrac to open this."},
    {pane:"setup", title:"Enclosure setup", needsLink:true,
     detail:linked ? "Wi-Fi, backups, updates and ownership."
                   : "Connect to PiTrac to open this."},
  ].map(card=>Object.assign(card, {disabled: !!card.needsLink && !linked}));
}

//: Where the desktop dials each simulator. Shown because when this fails,
//: "nothing is listening on 127.0.0.1:921" is the fact that identifies which
//: side is wrong, and it is otherwise invisible.
const SIM_WHERE = {
  gspro: {port: 921, screen: "Open Connect",
          how: "In GSPro, open the <strong>Open Connect</strong> screen so it is waiting for a device."},
};

//: Deliberately not a wizard. Nothing here is ordered or gated: the steps are
//: shown all at once, ticked off as they come true, and the page is safe to
//: open at any time -- including with no enclosure, since this connection is
//: between this computer and the simulator on it and needs no PiTrac at all.
function renderSimulator(data){
  const sim = data.simulatorStatus || {};
  const label = data.simulatorLabel || "your simulator";
  const linked = !!(data.link && data.link.connected);
  const local = isLocal(data);

  $("simNote").textContent = modeNote(data, "gspro");
  $("simSection").textContent = local ? "Local Range" : "Connection";
  $("simButtons").classList.toggle("hidden", local);
  if(local){
    $("simDot").className = "dot " + (sim.ready ? "good" : "bad");
    $("simHead").textContent = sim.ready ? "Recording on this computer" : "Shots cannot be saved";
    $("simWhy").textContent = sim.ready
      ? "Every measured shot is saved here and drawn on the Range tab. Nothing else has to be open."
      : sim.message;
    $("simSteps").innerHTML = "";
    $("simWhere").textContent = linked ? ""
      : "PiTrac is not connected, so there are no shots to record yet.";
    return;
  }
  const where = SIM_WHERE.gspro;

  $("simDot").className = "dot " + (sim.ready ? "good" : sim.connected ? "busy" : "bad");
  $("simHead").textContent = sim.ready ? "Ready to play"
    : sim.connected ? "Connected, not proved yet" : "Not connected";
  $("simWhy").textContent = sim.message
    || (sim.ready ? label + " has accepted a shot from PiTrac."
        : sim.connected ? "Connected to " + label + ". A test shot proves the rest of the path."
        : label + " is not answering on this computer yet.");

  const steps = [
    {done: true, text: "Choose " + esc(label) + " above."},
    {done: !!sim.connected, text: "Open " + esc(label) + " on this computer. " + where.how},
    {done: !!sim.ready, text: "Send a test shot. This proves the whole path, "
                             + "from the launch monitor to " + esc(label) + "."},
  ];
  $("simSteps").innerHTML = "<ol class='simsteps'>" + steps.map(s=>
    `<li class="${s.done?"done":""}">${s.text}</li>`).join("") + "</ol>";

  $("simWhere").innerHTML =
    "Easy-Connect looks for " + esc(label) + " on <strong>this computer</strong> at "
    + "<strong>127.0.0.1:" + where.port + "</strong>. "
    + (linked ? "" : "PiTrac is not connected, so a test shot is not available yet — "
                     + "but the connection above can still be checked.");
  $("simTest").disabled = !linked || !sim.connected;
}

function renderBoard(data, guiding){
  const board=$("board");
  board.classList.toggle("hidden", guiding);
  if(guiding){ board.innerHTML=""; return; }
  board.innerHTML=boardCards(data).map(card=>
    `<button data-pane="${esc(card.pane)}"${card.disabled?" disabled":""}>
       <span class="t">${esc(card.title)}</span>
       <span class="d">${esc(card.detail)}</span>
     </button>`).join("");
}

function renderWizard(view){
  const showing=!!(view && view.step!==undefined);
  $("wiz").classList.toggle("hidden", !showing || !view.step);
  if(!showing || !view.step) return;
  const steps=wizardSteps(status);
  const at=steps.findIndex(s=>s.key===view.step);
  $("wizRail").innerHTML=steps.map((s,i)=>
    `<i class="${i===at?"on":(i<at?"done":"")}"></i>`).join("");
  $("wizStep").textContent="Step "+(at+1)+" of "+steps.length+" · "+steps[at].label;
}

// --- the single line, and the single thing to do about it ----------------

function present(data){
  const linked=data.link && data.link.connected;
  const sim=data.simulatorStatus||{};
  const steps={}; (data.chain||[]).forEach(s=>steps[s.key]=s);

  if(!data.pairedEnclosures.length) return {
    dot:"", head:"Set up PiTrac", sub:"Let's find your enclosure.",
    why:"PiTrac needs to be powered on and on this network.",
    actions:[{label:"Find my PiTrac", id:"find", primary:true}], find:true};

  if(!linked) return {
    dot:"busy", head:"Looking for PiTrac", sub:"",
    why:"Check PiTrac has power and is on this network.",
    actions:[{label:"Search again", id:"find", primary:false}], find:true};

  const name=(data.link.device&&data.link.device.displayName)||"PiTrac";

  if(steps.pitrac && !steps.pitrac.ok) return {
    dot:"bad", head:"PiTrac needs attention", sub:esc(steps.pitrac.detail),
    why:"Easy-Connect is connected, but the launch monitor cannot measure a shot yet.",
    actions:[{label:"Open the PiTrac setup page", id:"setup", primary:true}]};

  if(isLocal(data)) return sim.ready ? {
    dot:"good", head:"Ready to play", sub:"Local Range · "+name,
    why:"", actions:[{label:"Go to the range", id:"range", primary:true}]}
  : {
    dot:"bad", head:"Shots cannot be saved", sub:name, why:sim.message,
    actions:[{label:"Check again", id:"check", primary:true}]};

  if(!sim.connected) return {
    dot:"bad", head:"Open "+esc(data.simulatorLabel), sub:name,
    why:"In GSPro, open the Open Connect screen so it is waiting for a device. "+
        modeNote(data,"gspro"),
    actions:[{label:"Check again", id:"check", primary:true}]};

  if(!sim.ready) return {
    dot:"busy", head:"Almost ready", sub:esc(data.simulatorLabel)+" · "+name,
    why:"One test shot proves the whole path. It is a real shot, so close any open round first.",
    actions:[{label:"Send a test shot", id:"test", primary:true}]};

  return {
    dot:"good", head:"Ready to play", sub:esc(data.simulatorLabel)+" · "+name,
    why:"", actions:[{label:"View shot data", id:"dash", primary:false}]};
}

function render(data){
  status=data;
  const guiding=!data.setupComplete;
  const view=guiding ? wizardView(data) : present(data);
  renderWizard(guiding?view:null);

  // The link client can stop retrying on its own (a device-id mismatch, a
  // revoked pairing) with nothing else ever telling the user why — no
  // synchronous API call failed, so nothing else would have shown this.
  // Surface it here, from status, rather than only from a caught exception.
  const linkError=data.link&&data.link.lastError;
  if(linkError&&!busy&&!asking()){
    showError({info:linkError}, data.link.lastErrorDeviceId||data.activeDeviceId, "link");
  }else if(!linkError&&!busy&&!asking()&&$("err").dataset.from==="link"){
    // The connection this message described has since succeeded, or the
    // attempt that failed is no longer the last word. Taking it down here is
    // what lets a search stop doing it: render puts link errors up, so render
    // is what removes them.
    showError(null);
  }
  renderKnownPis(data);

  const help=view.help;
  $("help").classList.toggle("hidden", !help);
  if(help){ $("helpTitle").textContent=help.title; $("helpBody").innerHTML=help.body; }

  $("dot").className="dot "+view.dot;
  $("head").textContent=view.head;
  $("sub").innerHTML=view.sub||"";
  $("why").textContent=view.why||"";

  if(!busy){
    $("do").innerHTML="";
    view.actions.forEach(action=>{
      const button=document.createElement("button");
      button.className=action.primary?"primary":"quiet";
      button.textContent=action.label;
      button.addEventListener("click",()=>doAction(action.id,button));
      $("do").appendChild(button);
    });
    if(view.find){
      // Rendering must stay free of state-changing side effects: only start
      // a fresh broadcast when nothing recent is cached and none is already
      // running. Every render while waiting must not mean another search.
      const stale=!lastSearchAt||(Date.now()-lastSearchAt)>SEARCH_CACHE_MS;
      if(!searchInFlight&&stale) findDevices();
    } else $("pick").classList.add("hidden");
  }

  renderUpdate(data.update);
  renderShots(data.shotLog);
  renderImages(data.enclosure);
  // Nothing else is offered while the wizard is running. Somewhere to wander
  // off to is the thing that makes a first run confusing.
  $("adv").classList.toggle("hidden", guiding || !data.pairedEnclosures.length);
  // The other tabs only mean anything once there is an enclosure to show.
  const linkedNow=!!(data.link && data.link.connected);
  // Once setup is done the tabs stay, whether or not PiTrac is connected now.
  // Hiding them on a dropped link strands whoever was reading their numbers.
  // The guide used to hide the tabs for the whole of setup, so that a first
  // run had nowhere confusing to wander off to. That was right for the first
  // two steps and wrong after them: the remaining steps are about the
  // simulator, and the range, the shot history and PiTrac's own pages all
  // work with no simulator at all. Anyone without GSPro open was held on the
  // guide with no way past it and no way to reach the range -- which is the
  // one part of this that needs no simulator, no account and no internet.
  //
  // So the tabs come back once the enclosure has connected, which is the
  // moment there is something worth reaching. Latched, because a link that
  // drops for a moment should not take the navigation with it.
  if(linkedNow) wizard.reachedEnclosure = true;
  // pairedEnclosures survives a restart, so someone who linked once, quit
  // before finishing, and reopened with the enclosure switched off still has
  // their navigation. The session latch alone would have taken it away again.
  const beenHere = wizard.reachedEnclosure || !!(data.pairedEnclosures || []).length;
  const gated = guiding && !beenHere;
  $("tabs").classList.toggle("hidden", gated);
  // The guide is one question at a time and reads better in a narrow
  // column; everything after it is a desktop window with work in it.
  document.body.classList.toggle("guiding", guiding);
  renderBoard(data, guiding);
  renderSimulator(data);
  $("testShot").classList.toggle("hidden", isLocal(data));
  // A demo shot exists so the range can be seen before there is a
  // launch monitor to fill it. Once the enclosure reports it can
  // measure -- cameras attached, calibration present, its program
  // running -- real shots are coming and a fake one is just a way to
  // put a shot in the history that nobody hit.
  const measuring=(data.chain||[]).find(s=>s.key==="pitrac");
  $("rangeDemo").classList.toggle("hidden", !!(measuring && measuring.ok));
  if(rangeData) renderState(rangeData);
  // The tabs go away when the link does, so anyone left on a pane that frames
  // the enclosure would be looking at an empty window with nothing to press.
  // The range and the shot history are not that: they are this session's own
  // data, still worth looking at with PiTrac unplugged, so they stay put.
  // simulator is in this list because that connection is between this
  // computer and the software on it; it needs no enclosure at all.
  if(!linkedNow && pane!=="play" && pane!=="range" && pane!=="shots"
     && pane!=="simulator") showPane("play");
  loadFrames();
  document.querySelectorAll("[data-sim]").forEach(b=>{
    b.classList.toggle("primary", b.dataset.sim===data.simulator);
    b.classList.toggle("quiet", b.dataset.sim!==data.simulator);
  });
  renderDetails(data);
}

function doAction(id, button){
  if(id==="wizStart"){ wizard.started=true; return refresh(); }
  if(id==="wizBackSim"){ wizard.simPicked=false; return refresh(); }
  if(id==="wizLocal"||id==="wizGspro") return run(button, async()=>{
    await api("/api/simulator",{simulator:id==="wizLocal"?"local":"gspro"});
    wizard.simPicked=true;
  });
  if(id==="wizRange") return run(button, async()=>{
    await api("/api/finish-setup",{done:true});
    showPane("range");
  });
  if(id==="range") return showPane("range");
  if(id==="wizFinish") return run(button, ()=>api("/api/finish-setup",{done:true}));
  if(id==="find") return run(button, findDevices);
  if(id==="check") return run(button, ()=>api("/api/check",{}));
  if(id==="test") return run(button, async()=>{
    if(!confirm("Send a test shot to "+status.simulatorLabel+"?\n\nThis is a real shot. If a round is open it may be scored.")) return;
    await api("/api/test-shot",{});
  });
  // These used to open a browser. The app has tabs showing exactly these two
  // pages, so shelling out to Chrome left the user in a second window looking
  // at something the app was already able to show them.
  if(id==="dash") return showPane("pitrac");
  if(id==="setup") return showPane("setup");
}

//: Which desktop.state values mean "there is something the persistent
//: indicator should keep saying," as opposed to a routine idle/checking/
//: up-to-date answer that is correctly shown by staying silent.
const DESKTOP_UPDATE_VISIBLE_STATES=new Set([
  "checking","available","downloading","cancelled","verifying","staging",
  "ready-to-restart","preflight-failed","installing","awaiting-restart-verification",
  "rollback","rolled-back","restart-required","check-failed","download-failed",
  "verify-failed","install-failed",
]);
const DESKTOP_UPDATE_BAD_STATES=new Set([
  "preflight-failed","rolled-back","check-failed","download-failed","verify-failed","install-failed",
]);
//: Which available version the prominent card has already been shown for
//: once. Comparing against this, not against "have we ever shown a card,"
//: is what lets a second, newer release re-open the notice even if an
//: earlier one had been dismissed.
let updateNoticeShownFor="", updateNoticeDismissed=false;

function updateIndicatorText(state, desktop){
  const version=desktop.availableVersion||desktop.stagedTargetVersion||"";
  const withVersion=text=>version?text+" ("+version+")":text;
  switch(state){
    case "checking": return "Checking for desktop updates…";
    case "available": return withVersion("Desktop update available");
    case "downloading": return "Downloading the desktop update…";
    case "cancelled": return "Desktop update cancelled";
    case "verifying": return "Verifying the desktop update…";
    case "staging": return "Validating and preparing the desktop update…";
    case "ready-to-restart": return withVersion("Desktop update ready to install");
    case "installing": return "Installing the desktop update…";
    case "awaiting-restart-verification": return "Verifying the restarted desktop app…";
    case "rollback": return "Restoring the previous desktop version…";
    case "rolled-back": return "The previous desktop version was restored";
    case "preflight-failed": return "Automatic installation was safely refused";
    case "restart-required": return "Update installed — start PiTrac Easy-Connect again";
    case "check-failed": return "Could not check for a desktop update";
    case "download-failed": return "The desktop update download failed";
    case "verify-failed": return "The desktop update failed verification";
    case "install-failed": return "The desktop update could not be installed";
    default: return "";
  }
}

function renderUpdateIndicator(desktop){
  const indicator=$("updateIndicator");
  const state=(desktop&&desktop.state)||"idle";
  if(!DESKTOP_UPDATE_VISIBLE_STATES.has(state)){
    indicator.classList.add("hidden");
    indicator.onclick=null;
    return;
  }
  indicator.classList.remove("hidden");
  indicator.classList.toggle("bad", DESKTOP_UPDATE_BAD_STATES.has(state));
  indicator.textContent=updateIndicatorText(state, desktop);
  // Bringing the card back is the only thing dismissing it ever does --
  // never hides the update itself, only the interruption.
  indicator.onclick=()=>{ updateNoticeDismissed=false; if(status) render(status); };
}

function renderDesktopUpdateCard(host, desktop, plan){
  const state=desktop.state||"idle";

  if(state==="available"){
    const version=desktop.availableVersion||plan.targetVersion||"";
    if(updateNoticeShownFor!==version){
      // A newer (or first-seen) version is due its own notice even if an
      // older one had already been waved off.
      updateNoticeShownFor=version;
      updateNoticeDismissed=false;
    }
    if(updateNoticeDismissed){ host.innerHTML=""; return; }
    host.innerHTML='<div class="update"><span>Desktop update available: PiTrac Easy-Connect '+
      esc(version)+' (this computer has '+esc(desktop.installedVersion||"")+').</span>'+
      '<span class="update-actions">'+
      '<button class="quiet" id="remindLater">Remind me later</button>'+
      '<button class="primary" id="updateNow">Update now</button></span></div>';
    $("updateNow").addEventListener("click",e=>run(e.target, async()=>{
      await api("/api/update/download",{});
    }));
    $("remindLater").addEventListener("click",()=>{
      updateNoticeDismissed=true;
      host.innerHTML="";
    });
    return;
  }

  if(state==="downloading" || state==="verifying" || state==="staging"){
    const progress=(desktop.downloadTotalBytes&&state==="downloading")
      ? " ("+Math.floor((desktop.downloadProgress||0)*100)+"%)" : "";
    host.innerHTML='<div class="update"><span>'+esc(desktop.detail||
      (state==="downloading"?"Downloading the update…":"Verifying the update…"))+esc(progress)+'</span>'+
      (desktop.canCancel?'<button class="quiet" id="cancelUpdate">Cancel</button>':'')+'</div>';
    const cancel=$("cancelUpdate");
    if(cancel) cancel.addEventListener("click",e=>run(e.target,()=>api("/api/update/cancel",{})));
    return;
  }

  if(state==="ready-to-restart"){
    host.innerHTML='<div class="update"><span>'+esc(desktop.detail||"The update is ready.")+
      '</span><button class="primary" id="restartNow">Restart and install</button></div>';
    $("restartNow").addEventListener("click",e=>run(e.target, async()=>{
      const result=await api("/api/update/apply",{});
      host.innerHTML='<div class="update"><span>'+esc(result.detail||"")+'</span></div>';
    }));
    return;
  }

  if(state==="installing"){
    host.innerHTML='<div class="update"><span>Installing and restarting…</span></div>';
    return;
  }

  if(state==="restart-required"){
    host.innerHTML='<div class="update"><span>'+esc(desktop.detail||
      "The update finished. Start PiTrac Easy-Connect again to use it.")+'</span></div>';
    return;
  }

  if(state==="cancelled" || state==="preflight-failed" || state==="rolled-back" ||
     state==="download-failed" || state==="verify-failed" || state==="install-failed"){
    const manual=!!desktop.savedPackagePath;
    host.innerHTML='<div class="update"><span>'+esc(desktop.detail||
      "That update could not be completed.")+'</span>'+
      '<span class="update-actions">'+
      '<button class="quiet" id="retryUpdate">Try again</button>'+
      (manual?'<button class="quiet" id="getUpdate">'+esc(desktop.revealAction||
        "Show downloaded file")+'</button>':'')+'</span></div>';
    $("retryUpdate").addEventListener("click",e=>run(e.target, async()=>{
      await api("/api/update/download",{});
    }));
    if(manual) wireDesktopDownload(host, desktop.savedPackagePath, plan.targetVersion, true);
    return;
  }

  // idle/checking/up-to-date/check-failed but the coordination plan still
  // says a desktop update is required (a source-style service too old to
  // send desktop.state, or a check that has not landed yet) -- always leave
  // something actionable rather than a blank banner.
  host.innerHTML='<div class="update"><span>'+esc(plan.detail||desktop.detail||"")+'</span>'+
    '<button class="quiet" id="getUpdate">Get desktop update</button></div>';
  wireDesktopDownload(host, plan.downloadUrl, plan.targetVersion);
}

function renderUpdate(update){
  const host=$("update");
  if(!update){
    host.innerHTML="";
    renderUpdateIndicator(null);
    return;
  }
  const plan=update.coordination||{};
  const desktop=update.desktop||{};
  renderUpdateIndicator(desktop);

  if(plan.phase==="desktop-update-required"){
    renderDesktopUpdateCard(host, desktop, plan);
    return;
  }
  if(plan.phase==="pi-update-required"){
    host.innerHTML='<div class="update"><span>'+esc(plan.detail||"")+'</span>'+
      '<button class="quiet" id="syncPi">Update PiTrac to '+
      esc(plan.targetVersion||"")+'</button></div>';
    $("syncPi").addEventListener("click",e=>run(e.target,()=>beginPiUpdate(
      plan.targetVersion,host,"update")));
    return;
  }
  if(plan.phase==="verifying-pi" || plan.phase==="blocked"){
    host.innerHTML='<div class="update"><span>'+esc(plan.detail||"")+'</span></div>';
    return;
  }
  if(plan.phase){ host.innerHTML=""; return; }

  // Compatibility for a source service old enough not to send a coordinated
  // plan. It may update only itself; the Pi is never touched from this path.
  if(!update.available){ host.innerHTML=""; return; }
  // Offer to install only when this copy can actually install it; otherwise
  // send them to the download rather than promising something that will fail.
  const action = update.canApply
    ? '<button class="quiet" id="doUpdate">Update</button>'
    : '<button class="quiet" id="getUpdate">Get it</button>';
  host.innerHTML=`<div class="update"><span>${esc(update.detail)}</span>${action}</div>`;
  const install=$("doUpdate");
  if(install) install.addEventListener("click",e=>run(e.target, async()=>{
    const result=await api("/api/update/apply",{});
    host.innerHTML=`<div class="update"><span>${esc(result.detail)}</span></div>`;
  }));
  const get=$("getUpdate");
  if(get) wireDesktopDownload(host,update.downloadUrl);
}

function wireDesktopDownload(host,savedPath,target,isLocalPackage){
  const get=$("getUpdate");
  if(!get) return;
  get.addEventListener("click",e=>run(e.target,async()=>{
    if(isLocalPackage){
      const result=await api("/api/update/reveal",{});
      const exact=result.path||savedPath||"";
      host.innerHTML='<div class="update"><span>'+esc(result.detail||
        "Use the verified update package saved by Easy-Connect.")+
        (exact?'<br><code>'+esc(exact)+'</code>':'')+'</span>'+
        (exact?'<button class="quiet" id="copyUpdate">Copy path</button>':'')+'</div>';
      const copy=$("copyUpdate");
      if(copy) copy.addEventListener("click",async event=>{
        const copied=await copyText(exact);
        event.target.textContent=copied?"Path copied":"Copy failed — use the path shown";
      });
      return;
    }
    if(target){
      const prepared=await api("/api/update/prepare",{targetTag:target});
      if(!prepared.prepared){
        host.innerHTML='<div class="update"><span>'+esc(prepared.detail||
          "That update could not be prepared.")+'</span></div>';
        return;
      }
    }
    const started=await api("/api/update/download",{});
    host.innerHTML='<div class="update"><span>'+esc(started.detail||
      (started.started?"Downloading the update inside Easy-Connect…":
        "Easy-Connect could not start the update download."))+'</span></div>';
  }));
}

async function beginPiUpdate(target,host,style){
  host.innerHTML='<div class="'+style+'"><span>Requesting the exact '+esc(target)+
    ' Pi-service release. The connection will drop while PiTrac restarts.</span></div>';
  const done=await api("/api/update/pi",{targetTag:target});
  host.innerHTML='<div class="'+style+'"><span>'+esc(done.detail||"")+'</span></div>';
  return done;
}

async function copyText(value){
  try{
    if(navigator.clipboard && navigator.clipboard.writeText){
      await navigator.clipboard.writeText(value); return true;
    }
    const box=document.createElement("textarea");
    box.value=value; box.style.position="fixed"; box.style.opacity="0";
    document.body.appendChild(box); box.select();
    const copied=document.execCommand("copy"); box.remove(); return copied;
  }catch(_error){ return false; }
}

function renderDetails(data){
  const device=(data.link&&data.link.device)||{};
  const enclosure=data.enclosure||{};
  const network=enclosure.network||{};
  const shots=data.shots||{};
  const update=data.update||{};
  const rows=[["Enclosure",device.displayName||"-"],["Device",device.deviceId||"-"],
    ["Address",(data.link&&data.link.address)||"-"],
    ["Wi-Fi",(network.connection&&network.connection.ssid)||"-"],
    [isLocal(data)?"Shots recorded":"Shots sent",shots.delivered!=null?shots.delivered:"-"],
    [isLocal(data)?"Not recorded":"Not delivered",shots.lost!=null?shots.lost:"-"],
    ["PiTrac",device.version||"-"],["Easy-Connect",data.version],
    ["Versions match",update.enclosureVersion?(update.versionsMatch?"yes":"no — update both"):"-"],
    ["Updates",update.detail||"-"]];
  $("kv").innerHTML=rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

// --- pairing, which happens once ----------------------------------------

async function findDevices(){
  if(searchInFlight) return;
  searchInFlight=true;
  const host=$("pick");
  try{
    const data=await api("/api/search",{});
    lastSearchAt=Date.now();
    const known=status?status.pairedEnclosures.map(e=>e.deviceId):[];
    if(data.problem){
      const problem=data.problem;
      const failure=new Error(problem.message||"Discovery could not run.");
      failure.info={failed:problem.message, nextStep:problem.nextStep};
      showError(failure, "", "search");
    }
    if(!data.enclosures.length){
      host.classList.add("hidden");
      if(!data.problem){
        const missing=new Error("No PiTrac was found.");
        missing.info={failed:"No PiTrac was found.",
          nextStep:"Check that PiTrac has power and is on this same network, then search again."};
        showError(missing, "", "search");
      }
      return;
    }
    // A Pi was found by this, the latest completed search. Whatever an
    // earlier search left showing — "No PiTrac was found," a stale
    // discovery-permission message — no longer describes reality, so it
    // must not sit next to a device list that contradicts it.
    if(!data.problem && $("err").dataset.from!=="link") showError(null);
    if(data.enclosures.length===1 && known.includes(data.enclosures[0].deviceId)){
      host.classList.add("hidden");
      await api("/api/connect",{deviceId:data.enclosures[0].deviceId});
      return;
    }
    host.classList.remove("hidden");
    host.innerHTML=data.enclosures.map(e=>`
      <button class="device" data-id="${esc(e.deviceId)}" data-paired="${e.paired?"1":""}">
        <span><strong>${esc(e.displayName)}</strong><small>${esc(e.address)}</small></span>
        <span class="tag ${e.paired?"on":""}">${e.paired?"PAIRED":"NEW"}</span>
      </button>`).join("");
    host.querySelectorAll(".device").forEach(button=>button.addEventListener("click",()=>{
      const id=button.dataset.id;
      if(button.dataset.paired) return run(button, ()=>api("/api/connect",{deviceId:id}));
      // There is nothing to type. Ask, and let the enclosure decide.
      run(button, async()=>{
        try{ await api("/api/pair",{deviceId:id}); }
        catch(error){
          // The pairing exchange only fails this way — refusing a brand new
          // computer because one is already trusted — for PT-PAIR-001. Every
          // other failure (rate limiting, an expired exchange, a network
          // problem) has its own next step and does not mean "go press Pair
          // another computer on the Pi."
          if(error.info&&error.info.code===__PAIR_NOT_ACCEPTING_CODE_JSON__) showAsk(data.enclosures.find(e=>e.deviceId===id));
          throw error;
        }
      });
    }));
  }catch(error){ showError(error); host.classList.add("hidden"); }
  finally{ searchInFlight=false; }
}

// The desktop's own list of PiTracs it has pairing records for. Distinct
// from "connected right now": a Pi that is off, on another network, or was
// reset still belongs here until someone removes it, which is exactly what
// makes a stale record findable and removable outside the search flow.
function renderKnownPis(data){
  const host=$("knownPis");
  const list=data.pairedEnclosures||[];
  if(!list.length){ host.classList.add("hidden"); host.innerHTML=""; return; }
  host.classList.remove("hidden");
  host.innerHTML='<h3>Known PiTracs</h3>'+list.map(e=>`
    <div class="row2">
      <span>${esc(e.displayName)}${e.deviceId===data.activeDeviceId&&data.link&&data.link.connected?" · connected now":""}</span>
      <button class="quiet danger" data-known-remove="${esc(e.deviceId)}">Remove</button>
    </div>`).join("");
  host.querySelectorAll("[data-known-remove]").forEach(button=>button.addEventListener("click",()=>run(button, async()=>{
    const id=button.dataset.knownRemove;
    if(!confirm("Remove this PiTrac from this computer?\n\nIf it is reachable, its owner should still remove this computer from its trusted list on the PiTrac setup page.")) return;
    await api("/api/forget-local",{deviceId:id});
  })));
}

// An enclosure that already belongs to a computer will not take another one
// until its owner says so. Show its own page, so whoever is here can do that
// without being told to go and find a browser.
function showAsk(enclosure){
  const address=enclosure && enclosure.address ? enclosure.address.split(":")[0] : "";
  const port=(enclosure && enclosure.portalPort) || 80;
  const base=address ? "http://"+address+(port===80?"":":"+port) : "";
  const frame=$("askFrame"), fallback=$("askNote");
  if(base){
    frame.style.display=""; frame.src=base;
    fallback.textContent="You can also do this at "+base+" from any device on this Wi-Fi.";
  }else{
    frame.style.display="none"; frame.removeAttribute("src");
    fallback.textContent="";
  }
  document.body.classList.add("pairing");
  $("askBox").classList.remove("hidden");
}

function closeAsk(){
  $("askFrame").removeAttribute("src");  // stop it polling once it is hidden
  document.body.classList.remove("pairing");
  $("askBox").classList.add("hidden");
  $("err").innerHTML="";  // the panel is gone, so the reason for it is stale
}

$("cancelPair").addEventListener("click",()=>{ closeAsk(); refresh(); });

// The enclosure updates itself, driven from here, because nobody is going to
// SSH into it. The app only asks; the Pi does the work and restarts itself.
$("checkPiUpdate").addEventListener("click",e=>run(e.target, async()=>{
  const host=$("piUpdate");
  const status=await api("/api/update/check",{});
  const plan=status.coordination||{};
  if(plan.phase==="synchronized"){
    host.innerHTML='<div class="note good">'+esc(plan.detail||"Versions match.")+'</div>';
    return;
  }
  if(plan.phase!=="pi-update-required"){
    host.innerHTML='<div class="note">'+esc(plan.detail||status.detail||"")+'</div>';
    renderUpdate(status);
    return;
  }
  host.innerHTML='<div class="note">'+esc(plan.detail||"")+'</div>'+
    '<button class="quiet" id="doPiUpdate">Update PiTrac to '+
    esc(plan.targetVersion||"")+'</button>';
  $("doPiUpdate").addEventListener("click",ev=>run(ev.target, async()=>{
    const done=await beginPiUpdate(plan.targetVersion,host,"note");
    if(!done.started) host.firstElementChild.classList.add("bad");
  }));
}));

$("showRaw").addEventListener("click",e=>run(e.target, async()=>{
  const data = await api("/api/raw-shots");
  const host = $("rawShots");
  if(!data.shots.length){
    host.innerHTML='<div class="note">Nothing yet. Hit a ball.</div>';
    return;
  }
  const warn = data.unitsUnexpected
    ? '<div class="note bad">PiTrac is reporting units this app has not seen before ('+
      esc(data.declaredUnits.join(", "))+'). Distances may be wrong. Expected '+
      esc(data.expectedUnits)+'.</div>'
    : "";
  host.innerHTML = warn +
    '<pre class="raw">'+esc(JSON.stringify(data.shots.map(s=>s.message), null, 1))+'</pre>';
}));

$("setupAgain").addEventListener("click",e=>run(e.target, async()=>{
  wizard={started:true, simPicked:false, reachedEnclosure:false};
  await api("/api/finish-setup",{done:false});
}));

// --- advanced ------------------------------------------------------------

document.querySelectorAll("[data-sim]").forEach(button=>button.addEventListener("click",
  e=>run(e.currentTarget, ()=>api("/api/simulator",{simulator:e.currentTarget.dataset.sim}))));
$("testShot").addEventListener("click",e=>doAction("test",e.target));
$("setupLink").addEventListener("click",()=>showPane("setup"));
$("restart").addEventListener("click",e=>run(e.target, async()=>{
  await api("/api/enclosure",{command:"restartPitrac"});
  $("note").innerHTML='<div class="note good">PiTrac was restarted.</div>';
}));
$("pairAnotherComputer").addEventListener("click",e=>run(e.target, async()=>{
  // Goes over this computer's own authenticated link, not PiTrac's
  // unauthenticated setup-portal endpoint -- getting an answer at all
  // already proves this copy of Easy-Connect holds a trusted pairing.
  await api("/api/enclosure",{command:"openPairing"});
  $("note").innerHTML='<div class="note good">PiTrac will accept one more computer for the next five minutes.</div>';
}));
$("shutdown").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Shut PiTrac down safely?\n\nWait for the green light on the Raspberry Pi to stop blinking before unplugging it.")) return;
  await api("/api/enclosure",{command:"shutdown"});
  $("note").innerHTML='<div class="note">Shutting down. Wait for the green light to stop blinking, then it is safe to unplug.</div>';
}));
$("forget").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Unpair this computer?\n\nPiTrac keeps its Wi-Fi, calibration, and other paired computers. You can pair again with a new code.")) return;
  await api("/api/forget",{deviceId:status.activeDeviceId});
}));
$("quit").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Stop Easy-Connect?\n\nShots will not be recorded or sent anywhere until you start it again.")) return;
  await api("/api/quit",{});
  document.body.innerHTML='<main><div class="brand">PiTrac Easy-Connect</div>'+
    '<div class="status"><div class="dot"></div><div><h1>Easy-Connect has stopped</h1>'+
    '<div class="sub">You can close this window.</div></div></div></main>';
}));
$("makeBackup").addEventListener("click",e=>run(e.target, async()=>{
  await apiDownload("/api/backup");
  $("note").innerHTML='<div class="note good">Saved to this computer. This one '+
    'has your calibration and settings, and no secrets.</div>';
}));

// A backup that can replace a dead memory card has to carry the enclosure's
// identity and its paired computers. Without those, restoring onto a new card
// gives a machine that has lost its owner card password and forgotten every
// computer. It is separate and it is labelled, because the file is worth
// protecting.
$("fullBackup").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Save a complete recovery backup?\n\n"+
      "This one also contains your setup Wi-Fi password and the secrets your "+
      "paired computers use. Keep it somewhere private \u2014 anyone with this "+
      "file can take over the enclosure.\n\n"+
      "It is the only kind of backup that can restore a failed memory card.")) return;
  await apiDownload("/api/backup?identity=1&pairings=1");
  $("note").innerHTML='<div class="note">Saved. Keep it somewhere private: it '+
    'contains your setup password and pairing secrets.</div>';
}));
$("bkFile").addEventListener("change",async event=>{
  const file=event.target.files && event.target.files[0];
  if(!file) return;
  $("bkPreview").innerHTML="";
  try{
    const text=await file.text();
    const info=await api("/api/backup/inspect",{file:text});
    $("bkPreview").innerHTML=`<div class="note"><strong>${esc(info.displayName)}</strong>,
      ${esc(info.createdText)}<br>${info.sectionLabels.map(esc).join(", ")}
      ${info.sameDevice?"":"<br><span style='color:var(--amber)'>From a different enclosure.</span>"}
      </div><button class="quiet" id="doRestore" style="margin-top:9px">Restore this</button>`;
    $("doRestore").addEventListener("click",b=>run(b.target, async()=>{
      // Calibration describes one particular pair of cameras in one
      // particular enclosure. Sending the override without asking meant an
      // amber note was the only thing between somebody and a machine
      // calibrated for a different unit.
      if(!info.sameDevice){
        if(!confirm("This backup is from a different PiTrac.\n\n"+
            "Its camera calibration describes that enclosure's cameras, not "+
            "this one's. Restoring it will make this PiTrac measure shots "+
            "incorrectly until it is calibrated again.\n\n"+
            "Restore it anyway?")) return;
      }
      const result=await api("/api/backup/restore",{file:text, calibration:true, preferences:true,
        identity:info.sections.includes("identity"), pairings:info.sections.includes("pairings"),
        confirmDifferentDevice:!info.sameDevice});
      $("bkPreview").innerHTML="";
      // PiTrac reads its calibration at startup, so it keeps using the old
      // one until it is restarted. Saying "Restored" and stopping there left
      // people believing a restore had taken effect when it had not.
      if(result.needsRestart){
        $("note").innerHTML='<div class="note">Restored: '+
          result.restored.map(esc).join(", ")+'. Restarting PiTrac so it '+
          'picks this up\u2026</div>';
        try{
          await api("/api/enclosure",{command:"restartPitrac"});
          $("note").innerHTML='<div class="note good">Restored and PiTrac restarted.</div>';
        }catch(err){
          $("note").innerHTML='<div class="note bad">Restored, but PiTrac could '+
            'not be restarted. Restart it from Advanced before playing.</div>';
        }
      }else{
        $("note").innerHTML='<div class="note good">Restored: '+
          result.restored.map(esc).join(", ")+'</div>';
      }
    }));
  }catch(error){ showError(error); }
  event.target.value="";
});

// --- the window's tabs ---------------------------------------------------

function showPane(name){
  pane=name;
  document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("on", p.id==="pane-"+name));
  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on", b.dataset.pane===name));
  if(name==="range"){
    // The canvas has no size until its pane is shown, so the context is
    // created on first open rather than at load.
    if(RANGE.start()){ RANGE.resize(); refreshRange(); }
  }
  loadFrames();
}
document.querySelectorAll("#tabs button").forEach(button=>
  button.addEventListener("click",()=>showPane(button.dataset.pane)));
// The board is rebuilt on every refresh, so this is delegated rather than
// bound to buttons that will not be the same objects a second later.
document.addEventListener("click",function(event){
  const card=event.target.closest && event.target.closest("#board button[data-pane]");
  if(card && !card.disabled) showPane(card.dataset.pane);
});

/*__RANGE_SCRIPT__*/
// --- shots ---------------------------------------------------------------

const CLUBS=["Driver","3 wood","5 wood","3 hybrid","4 hybrid","3 iron","4 iron","5 iron",
  "6 iron","7 iron","8 iron","9 iron","Pitching wedge","Gap wedge","Sand wedge","Lob wedge",
  "Putter"];
let clubReady=false, camerasAsked=false;

function fillClubs(current){
  const select=$("club");
  if(!clubReady){
    select.innerHTML='<option value="">Not recorded</option>'+
      CLUBS.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join("");
    select.addEventListener("change",e=>run(null,()=>api("/api/club",{club:e.target.value})));
    clubReady=true;
  }
  if(document.activeElement!==select) select.value=current||"";
}

function renderShots(log){
  if(!log) return;
  fillClubs(log.club);
  $("clubNote").textContent = isLocal(status)
    ? "Choose the club you are about to hit. Putter also switches PiTrac to measuring putts, from the next ball you place."
    : log.club
    ? "Your simulator sets this automatically when you change club."
    : "Your simulator will set this when you change club, or choose it here.";

  const summary=log.byClub||[];
  if(!changed($("byClub"), JSON.stringify(summary))) return renderRecent(log);
  $("byClub").className = summary.length ? "scroller" : "empty";
  $("byClub").innerHTML = summary.length ? `<table class="shot">
    <thead><tr><th>Club</th><th class="num">Shots</th><th class="num">Ball speed</th>
      <th class="num">Spread</th><th class="num">Launch</th><th class="num">Back spin</th></tr></thead>
    <tbody>${summary.map(row=>`<tr><td>${esc(row.club)}</td>
      <td class="num">${row.shots}</td>
      <td class="num">${row.speed==null?"-":row.speed+" mph"}</td>
      <td class="num" title="${esc(row.worstSpeed==null?"":"from "+row.worstSpeed+" to "+row.bestSpeed+" mph")}">${
        row.spread==null?"-":"&plusmn;"+(row.spread/2).toFixed(1)}</td>
      <td class="num">${row.launch==null?"-":row.launch+"&deg;"}</td>
      <td class="num">${row.backSpin==null?"-":row.backSpin}</td></tr>`).join("")}
    </tbody></table>
    <div class="clubnote" style="margin-top:9px">Spread is how far your strikes vary in ball
    speed. A tight spread means you are finding the middle of the face consistently.</div>`
    : "No shots recorded yet.";

  renderRecent(log);
}

function renderRecent(log){
  const recent=log.recent||[];
  if(!changed($("recent"), JSON.stringify(recent))) return;
  $("recent").className = recent.length ? "scroller" : "empty";
  $("recent").innerHTML = recent.length ? `<table class="shot">
    <thead><tr><th>Time</th><th>Club</th><th class="num">Speed</th><th class="num">Launch</th>
      <th class="num">Direction</th><th class="num">Spin</th></tr></thead>
    <tbody>${recent.map(s=>`<tr class="${esc(s.delivered===false?"lost":"")}">
      <td>${esc(s.timeText)}</td><td>${esc(s.club||"-")}</td>
      <td class="num">${s.speed==null?"-":s.speed}</td>
      <td class="num">${s.launch==null?"-":s.launch}</td>
      <td class="num">${s.direction==null?"-":s.direction===0?"0":Math.abs(s.direction)+(s.direction>0?" R":" L")}</td>
      <td class="num">${s.backSpin==null?"-":s.backSpin}</td></tr>`).join("")}
    </tbody></table>` : "Shots appear here as you hit them.";
}

// The page polls every few seconds. Rewriting a list that has not changed
// destroys and recreates every element in it, which restarts image loading,
// re-fetches pictures that were already fetched, and loses scroll position.
function changed(host, signature){
  if(host.dataset.sig === signature) return false;
  host.dataset.sig = signature;
  return true;
}

function renderImages(enclosure){
  const host=$("images");
  const images=(enclosure && enclosure.images) || [];
  const base=(enclosure && enclosure.dashboardUrl) || (status && status.dashboardUrl) || "";
  if(!changed(host, base + "|" + images.map(i=>i.name).join(","))) return;
  if(!images.length || !base){
    host.className="empty";
    host.textContent = base
      ? "No shot images yet. PiTrac saves one for each shot it measures."
      : "Connect to PiTrac to see shot images.";
    return;
  }
  // The pictures are served by PiTrac itself; nothing is copied to this computer.
  // Deliberately not lazy: these tiles are built while the tab is still hidden,
  // and a lazy image in a display:none subtree is deferred and never retried
  // once the tab is shown. There are at most a dozen, and they are small.
  host.className="shotgrid";
  host.innerHTML=images.map(image=>{
    const url=base+image.url;
    return `<div title="${esc(image.name)}">
      <img src="${esc(url)}" alt="${esc(image.name)}" decoding="async">
      <small>${esc(image.name)}</small></div>`;
  }).join("");
}

async function loadCameras(){
  if(camerasAsked) return;
  camerasAsked=true;
  try{
    const data=await api("/api/cameras",{});
    if(!data.available){ $("cameras").className="empty";
      $("cameras").textContent=data.message||"Not available."; return; }
    const found=(data.cameras||[]).length;
    const rows=[["Detected", found ? found+" camera"+(found===1?"":"s") : "none"],
      ["Raspberry Pi", data.pi_model||"-"]];
    (data.warnings||[]).slice(0,3).forEach((w,i)=>rows.push(["Note "+(i+1), w]));
    if(data.message) rows.push(["PiTrac says", data.message]);
    $("cameras").className="";
    $("cameras").innerHTML=rows.map(([k,v])=>
      `<div class="camrow"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join("")+
      `<div class="clubnote" style="margin-top:12px">Shot images and calibration are on the
       PiTrac tab. PiTrac measures the ball with still images and does not record swing video.</div>`;
  }catch(error){ $("cameras").className="empty"; $("cameras").textContent="Could not ask PiTrac."; }
}

$("clearShots").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Clear the shot history kept on this computer?\n\nPiTrac's own history is not affected.")) return;
  await api("/api/shots/clear",{});
}));

//: A token proving to the enclosure's own setup page that this computer is
//: already trusted, obtained over this computer's authenticated link (see
//: PairingManager.issue_owner_token). Without it, the page's own sensitive
//: buttons (remove a computer, reset Wi-Fi, shut down) would need someone to
//: type the owner-card password by hand every time, once anything is paired.
let ownerToken="", ownerTokenAt=0, ownerTokenDeviceId="";
const OWNER_TOKEN_CACHE_MS=25*60*1000;

async function ensureOwnerToken(){
  if(ownerTokenDeviceId!==status.activeDeviceId){ ownerToken=""; ownerTokenDeviceId=status.activeDeviceId; }
  if(ownerToken && Date.now()-ownerTokenAt<OWNER_TOKEN_CACHE_MS) return ownerToken;
  try{
    const result=await api("/api/enclosure",{command:"issueOwnerToken"});
    ownerToken=result.token||"";
    ownerTokenAt=Date.now();
  }catch(error){
    // Not linked, or the enclosure refused. The embedded page still loads;
    // its own sensitive actions will ask for the owner-card password if the
    // enclosure needs more than the setup network or first-setup allows.
  }
  return ownerToken;
}

async function openSetupFrame(){
  const address=status.link && status.link.address ? status.link.address.split(":")[0] : "";
  const port=(status.link && status.link.device && status.link.device.portalPort) || 80;
  if(!address){
    frameInto("setupFrame","setupHint","","Connect to PiTrac to change its settings.");
    return;
  }
  const token=await ensureOwnerToken();
  const base="http://"+address+(port===80?"":":"+port);
  frameInto("setupFrame","setupHint", token?base+"?ownerToken="+encodeURIComponent(token):base,
    "Connect to PiTrac to change its settings.");
}

function loadFrames(){
  if(!status) return;
  // Load a frame the first time its tab is opened, so the enclosure is not
  // serving two extra pages to a window nobody has looked at.
  if(pane==="shots") loadCameras();
  if(pane==="pitrac"){
    const url=status.dashboardUrl;
    frameInto("pitracFrame","pitracHint",url,
      "Connect to PiTrac to see shot data.");
  }
  if(pane==="setup") openSetupFrame();
}

function frameInto(frameId, hintId, url, emptyText){
  const frame=$(frameId), hint=$(hintId);
  if(!url){ frame.style.display="none"; hint.style.display=""; hint.textContent=emptyText; return; }
  hint.style.display="none"; frame.style.display="";
  if(frame.dataset.src!==url){ frame.dataset.src=url; frame.src=url; }
}

async function refresh(){
  try{ render(await api("/api/status")); }
  catch(error){
    $("dot").className="dot bad";
    $("head").textContent="Easy-Connect has stopped";
    $("sub").textContent="You can close this window.";
    $("why").textContent="";
  }
}
// Release smoke tests add this query parameter to the exact packaged app.
// These are ordinary product routes called through the same helper and
// WKWebView/WebView2/WebKitGTK page that owners use. The server records them,
// allowing packaging checks to prove the page itself reached guarded GET,
// search, and state-changing POST routes instead of spoofing the header with
// curl and declaring the UI healthy.
async function runPageSmoke(){
  if(new URLSearchParams(window.location.search).get("pitracSmoke")!=="1") return;
  try{
    await api("/api/status");
    await api("/api/search",{});
    await api("/api/finish-setup",{done:false});
  }catch(error){ showError(error); }
}
runPageSmoke();
refresh();
setInterval(()=>{ if(!busy && !asking()) refresh(); }, 3000);
// The range polls faster than the rest of the app, because a shot landing
// three seconds after it was hit does not feel like it belongs to the swing.
setInterval(()=>{ if(!busy && pane==="range" && !document.hidden) refreshRange(); }, 400);
</script>
</body>
</html>
"""

# Filled in from the error catalogue rather than typed as literals in the
# template above, so a code renumbered or removed in common.errors cannot
# silently drift out of sync with what the page actually checks for.
def _fill_error_codes(page: str) -> str:
    import json

    from ..common.errors import LINK_DEVICE_MISMATCH, LINK_DEVICE_REPLACED, PAIR_NOT_ACCEPTING

    return page.replace(
        "__STALE_PI_CODES_JSON__",
        json.dumps([LINK_DEVICE_MISMATCH.code, LINK_DEVICE_REPLACED.code]),
    ).replace(
        "__PAIR_NOT_ACCEPTING_CODE_JSON__", json.dumps(PAIR_NOT_ACCEPTING.code)
    )


def _fill_range(page: str) -> str:
    """Put the practice range into place; see ``range_view``."""

    from . import range_view

    return (
        page.replace("/*__RANGE_CSS__*/", range_view.CSS.strip("\n"))
        .replace("<!--__RANGE_MARKUP__-->", range_view.MARKUP.strip("\n"))
        .replace("/*__RANGE_SCRIPT__*/", range_view.SCRIPT.strip("\n"))
    )


PAGE = _fill_error_codes(_fill_range(PAGE))
