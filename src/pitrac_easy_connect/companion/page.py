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
  main{width:min(440px,calc(100% - 40px));padding:40px 0}
  .framehint{padding:14px 18px;color:var(--faint);font-size:.85rem;text-align:center}

  /* Shots: a table you can actually read, not a dashboard. */
  .shots{width:min(560px,calc(100% - 40px));margin-inline:auto;padding:26px 0 40px}
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

  /* Pairing: only ever seen once. */
  .pick{margin-top:22px;display:flex;flex-direction:column;gap:8px}
  body.pairing .status,body.pairing #do,body.pairing #pick,
  body.pairing #update,body.pairing .adv{display:none}
  /* --- practice range --- */
  #pane-range{padding:0;display:flex;flex-direction:column;height:100%}
  .rangewrap{position:relative;flex:1;min-height:0;background:#0a0f0d}
  #rangeCanvas{display:block;width:100%;height:100%;outline:none}
  #rangeCanvas:focus-visible{box-shadow:inset 0 0 0 2px var(--green)}
  .rangefallback{position:absolute;inset:0;display:flex;align-items:center;
    justify-content:center;text-align:center;padding:28px;color:var(--muted);
    font-size:.9rem;line-height:1.6}
  .rangehud{position:absolute;top:14px;left:14px;pointer-events:none;
    background:rgba(8,12,10,.68);border:1px solid rgba(255,255,255,.08);
    border-radius:14px;padding:12px 14px;min-width:132px}
  .hudrow{display:flex;align-items:baseline;gap:7px;margin:2px 0}
  .hudlabel{font-size:.62rem;font-weight:800;letter-spacing:.12em;
    text-transform:uppercase;color:var(--faint);min-width:48px}
  .hudbig{font-size:1.5rem;font-weight:800;color:var(--text);
    font-variant-numeric:tabular-nums;line-height:1.1}
  .hudval{font-size:.9rem;color:var(--muted);font-variant-numeric:tabular-nums}
  .hudunit{font-size:.7rem;color:var(--faint)}
  .hudclub{margin-top:6px;font-size:.7rem;font-weight:700;letter-spacing:.08em;
    text-transform:uppercase;color:var(--green)}
  .rangebar{position:absolute;left:0;right:0;bottom:0;display:flex;
    align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;
    background:linear-gradient(to top,rgba(8,12,10,.92) 40%,rgba(8,12,10,.55) 75%,transparent)}
  .views,.rangeright{display:flex;gap:6px;align-items:center}
  .viewbtn{background:rgba(20,26,23,.9);color:var(--muted);border:1px solid var(--line);
    border-radius:9px;padding:7px 11px;font-size:.76rem;font-weight:600;cursor:pointer;
    font-family:inherit}
  .viewbtn:hover{color:var(--text)}
  .viewbtn.on{background:var(--green);color:#0b0f0d;border-color:var(--green)}
  .viewbtn:focus-visible{outline:2px solid var(--green);outline-offset:2px}
  .rangecount{font-size:.72rem;color:var(--muted);font-variant-numeric:tabular-nums;
    text-align:right;line-height:1.25}
  .rangeclubs{flex:none;max-height:34%;overflow-y:auto;padding:12px 16px 16px;
    border-top:1px solid var(--line)}
  .rangeclub{display:flex;align-items:baseline;gap:10px;padding:7px 0;
    border-bottom:1px solid var(--line);font-size:.84rem}
  .rangeclub:last-child{border-bottom:none}
  .rcname{flex:1;font-weight:700;color:var(--text)}
  .rcstat{color:var(--muted);font-variant-numeric:tabular-nums;font-size:.78rem}
  .rcstat b{color:var(--text);font-weight:700}
  @media (prefers-reduced-motion:reduce){.viewbtn{transition:none}}

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

  <div id="update"></div>

  <div class="pick hidden" id="pick"></div>

  <div class="pick hidden" id="askBox">
    <iframe class="askframe" id="askFrame" title="PiTrac setup page"></iframe>
    <div class="asknote" id="askNote"></div>
    <button class="quiet" id="cancelPair">Back</button>
  </div>

  <details class="adv" id="adv">
    <summary>Advanced</summary>
    <div class="advbody">
      <h3>Simulator</h3>
      <div class="row2">
        <button class="quiet" data-sim="gspro" id="simGspro">GSPro</button>
        <button class="quiet" data-sim="e6" id="simE6">E6 Connect</button>
      </div>

      <h3>PiTrac</h3>
      <a class="linkbtn quiet" id="setupLink" href="#" target="_blank" rel="noopener">Open the PiTrac setup page</a>
      <button class="quiet" id="testShot">Send a test shot</button>
      <button class="quiet" id="restart">Restart PiTrac</button>
      <button class="quiet danger" id="shutdown">Shut down PiTrac safely</button>

      <h3>Backup</h3>
      <button class="quiet" id="makeBackup">Save a backup</button>
      <label class="linkbtn quiet" for="bkFile" style="cursor:pointer">Restore from a file</label>
      <input type="file" id="bkFile" accept=".pitracbackup,.json,application/json" class="hidden">
      <div id="bkPreview"></div>

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

<div class="pane" id="pane-range">
  <div class="rangewrap">
    <canvas id="rangeCanvas" tabindex="0"
      aria-label="Practice range. Shots are drawn as they are measured."></canvas>
    <div class="rangefallback hidden" id="rangeFallback"></div>

    <div class="rangehud" id="rangeHud">
      <div class="hudrow"><span class="hudlabel">Carry</span><span class="hudbig" id="hudCarry">--</span><span class="hudunit">yd</span></div>
      <div class="hudrow"><span class="hudlabel">Total</span><span class="hudval" id="hudTotal">--</span></div>
      <div class="hudrow"><span class="hudlabel">Apex</span><span class="hudval" id="hudApex">--</span></div>
      <div class="hudrow"><span class="hudlabel">Offline</span><span class="hudval" id="hudOffline">--</span></div>
      <div class="hudclub" id="hudClub"></div>
    </div>

    <div class="rangebar">
      <div class="views" role="group" aria-label="Camera">
        <button class="viewbtn on" data-view="behind">Behind</button>
        <button class="viewbtn" data-view="down">Down the line</button>
        <button class="viewbtn" data-view="top">Top down</button>
      </div>
      <div class="rangeright">
        <span class="rangecount" id="rangeCount"></span>
        <button class="viewbtn" id="rangeDemo">Demo shot</button>
        <button class="viewbtn" id="rangeClear">Clear</button>
      </div>
    </div>
  </div>

  <div class="rangeclubs" id="rangeClubs"></div>
</div>

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
//: Which of the window's tabs is showing. Declared here because present() has
//: to be able to send the window back to Play when the tabs disappear.
let pane="play";
//: True while the "PiTrac will not take another computer" panel is up.
const asking=()=>!$("askBox").classList.contains("hidden");

async function api(path, body){
  const options={method: body?"POST":"GET", headers:{}};
  if(body){options.headers["Content-Type"]="application/json";options.body=JSON.stringify(body);}
  const response=await fetch(path, options);
  const data=await response.json().catch(()=>({}));
  if(!response.ok){const e=new Error((data.error&&data.error.failed)||"That did not work");e.info=data.error;throw e;}
  return data;
}
function esc(v){const d=document.createElement("div");d.textContent=v==null?"":String(v);return d.innerHTML;}

function showError(error){
  // Clearing it while the refusal panel is up would leave that panel with no
  // explanation of why it appeared.
  if(!error){ if(!asking()) $("err").innerHTML=""; return; }
  const info=error.info||{};
  $("err").innerHTML=`<div class="err"><h2>${esc(info.failed||error.message)}</h2>
    ${info.nextStep?`<p>${esc(info.nextStep)}</p>`:""}
    ${info.code?`<div class="code">${esc(info.code)}</div>`:""}</div>`;
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
  {key:"sim",   label:"Simulator"},
  {key:"open",  label:"Open it"},
  {key:"test",  label:"Test shot"},
  {key:"done",  label:"Ready"},
];
let wizard={started:false, simPicked:false};

const CANNOT_FIND=`<ol>
  <li>Check the Raspberry Pi has power and its light is on.</li>
  <li>Give it two minutes after switching on. It is slower than a phone.</li>
  <li>If it has never been on your Wi-Fi, it makes its own network to be set up
      through. On a phone or laptop, join the Wi-Fi network called
      <code>PiTrac-</code> followed by four characters, using the password on
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
    why:"Three short steps: connect to your PiTrac, tell it which simulator "+
        "you use, and hit one test shot to prove it works.",
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
    dot:"", head:"Which simulator do you use?", sub:name,
    why:"You can change this later.",
    actions:[{label:"GSPro", id:"wizSimGspro", primary:data.simulator==="gspro"},
             {label:"E6 Connect", id:"wizSimE6", primary:data.simulator==="e6"}]};

  if(!sim.connected) return {step:"open",
    dot:"bad", head:"Open "+esc(data.simulatorLabel), sub:name,
    why:data.simulator==="gspro"
      ? "In GSPro, open the Open Connect screen so it is waiting for a device."
      : "In E6 Connect, start a session and step onto the tee.",
    actions:[{label:"Check again", id:"check", primary:true},
             {label:"Back", id:"wizBackSim", primary:false}]};

  if(!sim.ready) return {step:"test",
    dot:"busy", head:"One test shot", sub:esc(data.simulatorLabel)+" · "+name,
    why:"This proves the whole path from the launch monitor to your simulator. "+
        "It is a real shot, so close any open round first.",
    actions:[{label:"Send a test shot", id:"test", primary:true}]};

  return {step:"done",
    dot:"good", head:"You're ready to play", sub:esc(data.simulatorLabel)+" · "+name,
    why:"That's setup done. You will not see these steps again — next time you "+
        "open this it goes straight to playing.",
    actions:[{label:"Finish", id:"wizFinish", primary:true}]};
}

function renderWizard(view){
  const showing=!!(view && view.step!==undefined);
  $("wiz").classList.toggle("hidden", !showing || !view.step);
  if(!showing || !view.step) return;
  const at=WIZARD.findIndex(s=>s.key===view.step);
  $("wizRail").innerHTML=WIZARD.map((s,i)=>
    `<i class="${i===at?"on":(i<at?"done":"")}"></i>`).join("");
  $("wizStep").textContent="Step "+(at+1)+" of "+WIZARD.length+" · "+WIZARD[at].label;
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

  if(!sim.connected) return {
    dot:"bad", head:"Open "+esc(data.simulatorLabel), sub:name,
    why:data.simulator==="gspro"
      ? "In GSPro, open the Open Connect screen so it is waiting for a device."
      : "In E6 Connect, start a session and step onto the tee.",
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
    if(view.find) findDevices(); else $("pick").classList.add("hidden");
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
  $("tabs").classList.toggle("hidden", guiding);
  // The tabs go away when the link does, so anyone left on a pane that frames
  // the enclosure would be looking at an empty window with nothing to press.
  // The range and the shot history are not that: they are this session's own
  // data, still worth looking at with PiTrac unplugged, so they stay put.
  if(!linkedNow && pane!=="play" && pane!=="range" && pane!=="shots") showPane("play");
  loadFrames();
  document.querySelectorAll("[data-sim]").forEach(b=>{
    b.classList.toggle("primary", b.dataset.sim===data.simulator);
    b.classList.toggle("quiet", b.dataset.sim!==data.simulator);
  });
  $("setupLink").href = data.link && data.link.address
    ? "http://"+data.link.address.split(":")[0] : "#";
  renderDetails(data);
}

function doAction(id, button){
  if(id==="wizStart"){ wizard.started=true; return refresh(); }
  if(id==="wizBackSim"){ wizard.simPicked=false; return refresh(); }
  if(id==="wizSimGspro"||id==="wizSimE6") return run(button, async()=>{
    await api("/api/simulator",{simulator:id==="wizSimGspro"?"gspro":"e6"});
    wizard.simPicked=true;
  });
  if(id==="wizFinish") return run(button, ()=>api("/api/finish-setup",{done:true}));
  if(id==="find") return run(button, findDevices);
  if(id==="check") return run(button, ()=>api("/api/check",{}));
  if(id==="test") return run(button, async()=>{
    if(!confirm("Send a test shot to "+status.simulatorLabel+"?\n\nThis is a real shot. If a round is open it may be scored.")) return;
    await api("/api/test-shot",{});
  });
  if(id==="dash"||id==="setup"){
    const url = id==="dash" ? status.dashboardUrl
      : (status.link&&status.link.address ? "http://"+status.link.address.split(":")[0] : "");
    if(url) window.open(url,"_blank","noopener");
  }
}

function renderUpdate(update){
  const host=$("update");
  if(!update || !update.available){ host.innerHTML=""; return; }
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
  if(get) get.addEventListener("click",()=>{
    if(update.downloadUrl) window.open(update.downloadUrl,"_blank","noopener");
  });
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
    ["Shots sent",shots.delivered!=null?shots.delivered:"-"],
    ["Not delivered",shots.lost!=null?shots.lost:"-"],
    ["PiTrac",device.version||"-"],["Easy-Connect",data.version],
    ["Versions match",update.enclosureVersion?(update.versionsMatch?"yes":"no — update both"):"-"],
    ["Updates",update.detail||"-"]];
  $("kv").innerHTML=rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

// --- pairing, which happens once ----------------------------------------

async function findDevices(){
  const host=$("pick");
  try{
    const data=await api("/api/search",{});
    const known=status?status.pairedEnclosures.map(e=>e.deviceId):[];
    if(!data.enclosures.length){ host.classList.add("hidden"); return; }
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
        catch(error){ showAsk(data.enclosures.find(e=>e.deviceId===id)); throw error; }
      });
    }));
  }catch(error){ showError(error); host.classList.add("hidden"); }
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

$("setupAgain").addEventListener("click",e=>run(e.target, async()=>{
  wizard={started:true, simPicked:false};
  await api("/api/finish-setup",{done:false});
}));

// --- advanced ------------------------------------------------------------

document.querySelectorAll("[data-sim]").forEach(button=>button.addEventListener("click",
  e=>run(e.currentTarget, ()=>api("/api/simulator",{simulator:e.currentTarget.dataset.sim}))));
$("testShot").addEventListener("click",e=>doAction("test",e.target));
$("restart").addEventListener("click",e=>run(e.target, async()=>{
  await api("/api/enclosure",{command:"restartPitrac"});
  $("note").innerHTML='<div class="note good">PiTrac was restarted.</div>';
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
  if(!confirm("Stop Easy-Connect?\n\nShots will stop reaching your simulator until you start it again.")) return;
  await api("/api/quit",{});
  document.body.innerHTML='<main><div class="brand">PiTrac Easy-Connect</div>'+
    '<div class="status"><div class="dot"></div><div><h1>Easy-Connect has stopped</h1>'+
    '<div class="sub">You can close this window.</div></div></div></main>';
}));
$("makeBackup").addEventListener("click",e=>run(e.target, async()=>{
  window.location.href="/api/backup";
  $("note").innerHTML='<div class="note good">Saved to this computer.</div>';
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
      const result=await api("/api/backup/restore",{file:text, calibration:true, preferences:true,
        identity:info.sections.includes("identity"), pairings:info.sections.includes("pairings"),
        confirmDifferentDevice:true});
      $("bkPreview").innerHTML="";
      $("note").innerHTML='<div class="note good">Restored: '+result.restored.map(esc).join(", ")+'</div>';
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

// --- the practice range --------------------------------------------------
//
// Hand-written WebGL rather than a rendering library: the scene is a ground
// plane, a sky, some markers and a few lines, which is not worth 600 KB of
// dependency in a project that otherwise ships nothing but the standard
// library. See docs/range-prd.md section 4.2.
//
// The page does no physics. Trajectories arrive from the companion already
// computed, and this only draws them.

const YARD = 0.9144;
const RANGE = (function(){
  let gl=null, canvas=null, programs=null, raf=null, lost=false;
  let meshes={}, dynamic={}, skyBuffer=null, lastViewProj=null;
  let shots=[], byClub=[], targets=[], markers=[], count=0;
  // Kept in one place: the declaration and setView must not drift apart, or
  // the range opens on a camera no button can reproduce.
  const VIEWS = {
    behind: {yaw:0.62, pitch:0.30, dist:205},
    down:   {yaw:0.0,  pitch:0.055, dist:120},
  };
  let view="behind", orbit=Object.assign({}, VIEWS.behind), drag=null;
  let animation=null, lastFrame=0;

  const reduced = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- shaders ----------------------------------------------------------
  //
  // Four programs rather than one that does everything: a sky, lit ground with
  // procedural grass, lit solid geometry, and unlit lines. Each stays short
  // enough to read, and none of them branches on what it is drawing.

  const SUN = [0.38, 0.82, -0.42];        // direction toward the sun
  const SKY_TOP = [0.204, 0.361, 0.573];
  const SKY_HORIZON = [0.663, 0.741, 0.792];

  // A full-screen triangle, coloured by the direction each pixel looks in.
  const SKY_VERT = `#version 300 es
    in vec2 aClip;
    uniform mat4 uInverseViewProj;
    out vec3 vRay;
    void main(){
      gl_Position = vec4(aClip, 1.0, 1.0);
      vec4 near = uInverseViewProj * vec4(aClip, -1.0, 1.0);
      vec4 far  = uInverseViewProj * vec4(aClip,  1.0, 1.0);
      vRay = normalize(far.xyz/far.w - near.xyz/near.w);
    }`;
  const SKY_FRAG = `#version 300 es
    precision highp float;
    in vec3 vRay;
    uniform vec3 uTop, uHorizon, uSun;
    out vec4 outColor;
    void main(){
      vec3 ray = normalize(vRay);
      float height = clamp(ray.y * 1.6 + 0.05, 0.0, 1.0);
      vec3 sky = mix(uHorizon, uTop, pow(height, 0.62));
      // A soft sun, and the glow it throws across the sky near it.
      float toSun = max(dot(ray, normalize(uSun)), 0.0);
      sky += vec3(1.0, 0.92, 0.76) * pow(toSun, 220.0) * 0.85;
      sky += vec3(0.98, 0.86, 0.66) * pow(toSun, 7.0) * 0.14;
      // Ground haze below the horizon, so the turf meets something.
      sky = mix(vec3(0.596, 0.678, 0.729), sky, smoothstep(-0.055, 0.004, ray.y));
      outColor = vec4(sky, 1.0);
    }`;

  // Ground: procedural turf. Mowing stripes, value noise for mottling, and a
  // little normal jitter so it catches the light unevenly instead of reading
  // as a sheet of plastic.
  const GROUND_VERT = `#version 300 es
    in vec3 aPos;
    uniform mat4 uViewProj;
    out vec3 vWorld;
    void main(){ vWorld = aPos; gl_Position = uViewProj * vec4(aPos, 1.0); }`;
  const GROUND_FRAG = `#version 300 es
    precision highp float;
    in vec3 vWorld;
    uniform vec3 uSun, uEye;
    out vec4 outColor;

    float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
    float noise(vec2 p){
      vec2 i = floor(p), f = fract(p);
      vec2 u = f*f*(3.0-2.0*f);
      return mix(mix(hash(i), hash(i+vec2(1,0)), u.x),
                 mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), u.x), u.y);
    }
    float turf(vec2 p){
      return noise(p*1.7)*0.55 + noise(p*7.3)*0.28 + noise(p*23.0)*0.17;
    }

    void main(){
      vec2 p = vWorld.xz;
      float grain = turf(p * 0.9);

      // Mown stripes: alternating bands cut in opposite directions, which is
      // why a real fairway shows light and dark rows.
      float band = floor(vWorld.z / 9.144);
      float stripe = mod(band, 2.0) < 1.0 ? 1.06 : 0.90;
      stripe *= 1.0 + (turf(p * 0.35) - 0.5) * 0.10;

      vec3 base = mix(vec3(0.220, 0.396, 0.216), vec3(0.310, 0.522, 0.290), grain);
      base *= stripe;

      // Bare, darker ground once past the mown range.
      float mown = 1.0 - smoothstep(58.0, 132.0, abs(vWorld.x));
      mown *= 1.0 - smoothstep(275.0, 400.0, vWorld.z);
      mown *= smoothstep(-70.0, -14.0, vWorld.z);
      base = mix(vec3(0.196, 0.271, 0.165) * (0.72 + grain*0.55), base, mown);

      // Lighting: a directional sun, and sky light from above.
      vec3 jitter = normalize(vec3((turf(p*4.1)-0.5)*0.45, 1.0, (turf(p*4.7+9.0)-0.5)*0.45));
      float sun = max(dot(jitter, normalize(uSun)), 0.0);
      float ambient = 0.62 + 0.20 * jitter.y;
      vec3 lit = base * (ambient + sun * 0.52);

      // Distance haze, so the far end of the range recedes.
      float away = clamp(length(vWorld - uEye) / 620.0, 0.0, 1.0);
      lit = mix(lit, vec3(0.612, 0.694, 0.745), pow(away, 1.9) * 0.80);
      outColor = vec4(lit, 1.0);
    }`;

  // Lit solid geometry: the ball, the flags, the target greens.
  const SOLID_VERT = `#version 300 es
    in vec3 aPos; in vec3 aNormal; in vec3 aColor;
    uniform mat4 uViewProj;
    out vec3 vNormal; out vec3 vColor; out vec3 vWorld;
    void main(){
      vNormal = aNormal; vColor = aColor; vWorld = aPos;
      gl_Position = uViewProj * vec4(aPos, 1.0);
    }`;
  const SOLID_FRAG = `#version 300 es
    precision highp float;
    in vec3 vNormal; in vec3 vColor; in vec3 vWorld;
    uniform vec3 uSun, uEye;
    uniform float uAlpha;
    out vec4 outColor;
    void main(){
      vec3 n = normalize(vNormal);
      vec3 toSun = normalize(uSun);
      float sun = max(dot(n, toSun), 0.0);
      float ambient = 0.55 + 0.26 * clamp(n.y * 0.5 + 0.5, 0.0, 1.0);
      // A tight highlight, which is what makes a golf ball read as a golf ball.
      vec3 toEye = normalize(uEye - vWorld);
      float spec = pow(max(dot(reflect(-toSun, n), toEye), 0.0), 42.0);
      vec3 lit = vColor * (ambient + sun * 0.58) + vec3(1.0, 0.97, 0.90) * spec * 0.60;
      float away = clamp(length(vWorld - uEye) / 620.0, 0.0, 1.0);
      lit = mix(lit, vec3(0.612, 0.694, 0.745), pow(away, 1.9) * 0.70);
      outColor = vec4(lit, uAlpha);
    }`;

  // Unlit lines: tracers and markings. These are annotation, not scenery, and
  // lighting them would only make them harder to follow.
  const LINE_VERT = `#version 300 es
    in vec3 aPos; in vec3 aColor;
    uniform mat4 uViewProj;
    out vec3 vColor; out vec3 vWorld;
    void main(){ vColor = aColor; vWorld = aPos; gl_Position = uViewProj * vec4(aPos,1.0); }`;
  const LINE_FRAG = `#version 300 es
    precision highp float;
    in vec3 vColor; in vec3 vWorld;
    uniform vec3 uEye; uniform float uAlpha;
    out vec4 outColor;
    void main(){
      float away = clamp(length(vWorld - uEye) / 660.0, 0.0, 1.0);
      outColor = vec4(mix(vColor, vec3(0.612,0.694,0.745), pow(away,1.9)*0.55), uAlpha);
    }`;

  function compile(src, kind){
    const s = gl.createShader(kind);
    gl.shaderSource(s, src.trim());
    gl.compileShader(s);
    if(!gl.getShaderParameter(s, gl.COMPILE_STATUS))
      throw new Error(gl.getShaderInfoLog(s) || "shader failed to compile");
    return s;
  }

  function link(vertSrc, fragSrc, attribs){
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(vertSrc, gl.VERTEX_SHADER));
    gl.attachShader(prog, compile(fragSrc, gl.FRAGMENT_SHADER));
    gl.linkProgram(prog);
    if(!gl.getProgramParameter(prog, gl.LINK_STATUS))
      throw new Error(gl.getProgramInfoLog(prog) || "program failed to link");
    const record = {prog: prog, attrib: {}, uniform: {}};
    attribs.forEach(function(name){ record.attrib[name] = gl.getAttribLocation(prog, name); });
    const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for(let i=0;i<count;i++){
      const info = gl.getActiveUniform(prog, i);
      record.uniform[info.name] = gl.getUniformLocation(prog, info.name);
    }
    return record;
  }

  // --- small matrix helpers --------------------------------------------
  function perspective(fovy, aspect, near, far){
    const f = 1/Math.tan(fovy/2), d = near-far;
    return [f/aspect,0,0,0, 0,f,0,0, 0,0,(far+near)/d,-1, 0,0,2*far*near/d,0];
  }
  function lookAt(eye, at, up){
    const z = norm(sub(eye,at)), x = norm(cross(up,z)), y = cross(z,x);
    return [x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0,
            -dot(x,eye),-dot(y,eye),-dot(z,eye),1];
  }
  function multiply(a,b){
    const o = new Array(16);
    for(let r=0;r<4;r++) for(let c=0;c<4;c++)
      o[c*4+r] = a[r]*b[c*4] + a[4+r]*b[c*4+1] + a[8+r]*b[c*4+2] + a[12+r]*b[c*4+3];
    return o;
  }
  const sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
  function norm(v){ const l=Math.hypot(v[0],v[1],v[2])||1; return [v[0]/l,v[1]/l,v[2]/l]; }

  // --- geometry ---------------------------------------------------------

  function mesh(parts){
    // parts: {pos:[], normal:[], color:[]} -> buffers ready to draw.
    return {
      pos: new Float32Array(parts.pos),
      normal: parts.normal ? new Float32Array(parts.normal) : null,
      color: new Float32Array(parts.color),
      count: parts.pos.length / 3,
    };
  }

  function groundMesh(){
    // One large quad. All the detail is in the fragment shader, so there is no
    // reason to tessellate it.
    const far = 1100*YARD, side = 800*YARD, back = 160*YARD;
    return mesh({pos:[-side,0,-back,  side,0,-back,  side,0,far,
                      -side,0,-back,  side,0,far,   -side,0,far], color:new Array(18).fill(0)});
  }

  function sphere(cx, cy, cz, radius, colour, rings, segments){
    const pos=[], normal=[], color=[];
    for(let r=0;r<rings;r++){
      const p0 = Math.PI*r/rings, p1 = Math.PI*(r+1)/rings;
      for(let s=0;s<segments;s++){
        const t0 = 2*Math.PI*s/segments, t1 = 2*Math.PI*(s+1)/segments;
        const corner = function(phi, theta){
          return [Math.sin(phi)*Math.cos(theta), Math.cos(phi), Math.sin(phi)*Math.sin(theta)];
        };
        const a=corner(p0,t0), b=corner(p1,t0), c=corner(p1,t1), d=corner(p0,t1);
        [a,b,c, a,c,d].forEach(function(n){
          pos.push(cx+n[0]*radius, cy+n[1]*radius, cz+n[2]*radius);
          normal.push(n[0], n[1], n[2]);
          color.push(colour[0], colour[1], colour[2]);
        });
      }
    }
    return {pos:pos, normal:normal, color:color};
  }

  function ringDisc(cz, radius, colour, y){
    // A filled disc for a target green, facing up.
    const pos=[], normal=[], color=[], steps=44;
    for(let i=0;i<steps;i++){
      const a0=2*Math.PI*i/steps, a1=2*Math.PI*(i+1)/steps;
      [[0,0],[Math.cos(a0),Math.sin(a0)],[Math.cos(a1),Math.sin(a1)]].forEach(function(pt){
        pos.push(pt[0]*radius, y, cz+pt[1]*radius);
        normal.push(0,1,0);
        color.push(colour[0], colour[1], colour[2]);
      });
    }
    return {pos:pos, normal:normal, color:color};
  }

  function box(x0,y0,z0, x1,y1,z1, colour){
    const pos=[], normal=[], color=[];
    const face = function(a,b,c,d,n){
      [a,b,c, a,c,d].forEach(function(v){
        pos.push(v[0],v[1],v[2]); normal.push(n[0],n[1],n[2]);
        color.push(colour[0],colour[1],colour[2]);
      });
    };
    face([x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1],[0,0,1]);
    face([x1,y0,z0],[x0,y0,z0],[x0,y1,z0],[x1,y1,z0],[0,0,-1]);
    face([x1,y0,z1],[x1,y0,z0],[x1,y1,z0],[x1,y1,z1],[1,0,0]);
    face([x0,y0,z0],[x0,y0,z1],[x0,y1,z1],[x0,y1,z0],[-1,0,0]);
    face([x0,y1,z1],[x1,y1,z1],[x1,y1,z0],[x0,y1,z0],[0,1,0]);
    return {pos:pos, normal:normal, color:color};
  }

  function join(pieces){
    const out={pos:[], normal:[], color:[]};
    pieces.forEach(function(part){
      out.pos.push.apply(out.pos, part.pos);
      out.normal.push.apply(out.normal, part.normal);
      out.color.push.apply(out.color, part.color);
    });
    return out;
  }

  function furnitureMesh(){
    // Target greens, flagsticks and the 100-yard distance posts, all lit.
    const parts=[];
    targets.forEach(function(yards){
      const z = yards*YARD;
      parts.push(ringDisc(z, 9.5*YARD, [0.310, 0.510, 0.267], 0.035));
      parts.push(ringDisc(z, 8.2*YARD, [0.396, 0.612, 0.325], 0.045));
      parts.push(box(-0.045, 0, z-0.045, 0.045, 2.35, z+0.045, [0.88,0.89,0.86]));   // pole
      parts.push(box(0.045, 1.85, z-0.02, 0.80, 2.30, z+0.02, [0.784,0.235,0.216])); // flag
    });
    markers.forEach(function(yards){
      const z = yards*YARD;
      [-1,1].forEach(function(side){
        const x = side*62*YARD;
        parts.push(box(x-0.09, 0, z-0.09, x+0.09, 1.5, z+0.09, [0.62,0.64,0.60]));
        parts.push(box(x-0.55, 1.5, z-0.03, x+0.55, 2.1, z+0.03, [0.90,0.91,0.88]));
      });
    });
    return parts.length ? mesh(join(parts)) : null;
  }

  function markingsMesh(){
    // Flat lines on the turf: the yard lines and the centre line.
    const pos=[], col=[];
    const line=(a,b,c)=>{ pos.push(a[0],a[1],a[2], b[0],b[1],b[2]);
                          col.push(c[0],c[1],c[2], c[0],c[1],c[2]); };
    const wide = 62*YARD;
    markers.forEach(function(yards){
      line([-wide,0.03,yards*YARD],[wide,0.03,yards*YARD],[0.48,0.55,0.47]);
    });
    line([0,0.03,0],[0,0.03,320*YARD],[0.32,0.40,0.33]);
    return {pos:new Float32Array(pos), color:new Float32Array(col), count:pos.length/3};
  }

  function ballMesh(){
    return mesh(sphere(0, 0, 0, 0.30, [0.965, 0.969, 0.945], 12, 18));
  }

  function shadowMesh(){
    // A soft blob under the ball. Cheap, and the thing that stops the ball
    // looking like it is pasted on top of the picture.
    const pos=[], normal=[], color=[], steps=28;
    for(let i=0;i<steps;i++){
      const a0=2*Math.PI*i/steps, a1=2*Math.PI*(i+1)/steps;
      pos.push(0,0,0, Math.cos(a0),0,Math.sin(a0), Math.cos(a1),0,Math.sin(a1));
      normal.push(0,1,0, 0,1,0, 0,1,0);
      color.push(0.02,0.03,0.02, 0.02,0.03,0.02, 0.02,0.03,0.02);
    }
    return mesh({pos:pos, normal:normal, color:color});
  }

  function build(){
    programs = {
      sky:    link(SKY_VERT, SKY_FRAG, ["aClip"]),
      ground: link(GROUND_VERT, GROUND_FRAG, ["aPos", "aColor"]),
      solid:  link(SOLID_VERT, SOLID_FRAG, ["aPos", "aNormal", "aColor"]),
      line:   link(LINE_VERT, LINE_FRAG, ["aPos", "aColor"]),
    };
    gl.bindVertexArray(gl.createVertexArray());

    // One oversized triangle covering the screen, for the sky.
    skyBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, skyBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);

    dynamic = {};
    meshes = {
      ground: groundMesh(),
      markings: markingsMesh(),
      furniture: furnitureMesh(),
      ball: ballMesh(),
      shadow: shadowMesh(),
    };

    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.clearColor(SKY_HORIZON[0], SKY_HORIZON[1], SKY_HORIZON[2], 1);
  }

  function rebuildScenery(){
    // Targets and markers arrive from the companion, so the furniture cannot
    // be built until the first status has landed.
    if(!gl || !programs) return;
    meshes.markings = markingsMesh();
    meshes.furniture = furnitureMesh();
  }


  function camera(aspect){
    let eye, focus, up=[0,1,0], fov=Math.PI/4;
    if(view==="top"){
      // Looking straight down at the middle of the range. High enough, and
      // through a narrow enough lens, that it reads as a plan rather than as a
      // trapezoid: this view exists to show dispersion, and perspective would
      // make the far shots look tighter than they were.
      const mid = 150*YARD;
      eye=[0, 560, mid]; focus=[0, 0, mid]; up=[0,0,1]; fov=Math.PI/7;
    }else{
      // Behind and down-the-line are the same orbiting camera at different
      // starting points, so dragging works identically in both.
      focus = [0, 12, 105*YARD];
      const flat = orbit.dist*Math.cos(orbit.pitch);
      eye = [focus[0] + Math.sin(orbit.yaw)*flat,
             focus[1] + orbit.dist*Math.sin(orbit.pitch),
             focus[2] - Math.cos(orbit.yaw)*flat];
    }
    const proj = perspective(fov, aspect, 0.4, 2600);
    const matrix = multiply(proj, lookAt(eye, focus, up));
    lastViewProj = matrix;
    return {matrix: matrix, eye: eye, inverse: invert(matrix)};
  }

  function invert(m){
    // Full 4x4 inverse. The sky shader turns clip-space corners back into
    // world-space directions, which needs it.
    const inv = new Array(16);
    inv[0]=m[5]*m[10]*m[15]-m[5]*m[11]*m[14]-m[9]*m[6]*m[15]+m[9]*m[7]*m[14]+m[13]*m[6]*m[11]-m[13]*m[7]*m[10];
    inv[4]=-m[4]*m[10]*m[15]+m[4]*m[11]*m[14]+m[8]*m[6]*m[15]-m[8]*m[7]*m[14]-m[12]*m[6]*m[11]+m[12]*m[7]*m[10];
    inv[8]=m[4]*m[9]*m[15]-m[4]*m[11]*m[13]-m[8]*m[5]*m[15]+m[8]*m[7]*m[13]+m[12]*m[5]*m[11]-m[12]*m[7]*m[9];
    inv[12]=-m[4]*m[9]*m[14]+m[4]*m[10]*m[13]+m[8]*m[5]*m[14]-m[8]*m[6]*m[13]-m[12]*m[5]*m[10]+m[12]*m[6]*m[9];
    inv[1]=-m[1]*m[10]*m[15]+m[1]*m[11]*m[14]+m[9]*m[2]*m[15]-m[9]*m[3]*m[14]-m[13]*m[2]*m[11]+m[13]*m[3]*m[10];
    inv[5]=m[0]*m[10]*m[15]-m[0]*m[11]*m[14]-m[8]*m[2]*m[15]+m[8]*m[3]*m[14]+m[12]*m[2]*m[11]-m[12]*m[3]*m[10];
    inv[9]=-m[0]*m[9]*m[15]+m[0]*m[11]*m[13]+m[8]*m[1]*m[15]-m[8]*m[3]*m[13]-m[12]*m[1]*m[11]+m[12]*m[3]*m[9];
    inv[13]=m[0]*m[9]*m[14]-m[0]*m[10]*m[13]-m[8]*m[1]*m[14]+m[8]*m[2]*m[13]+m[12]*m[1]*m[10]-m[12]*m[2]*m[9];
    inv[2]=m[1]*m[6]*m[15]-m[1]*m[7]*m[14]-m[5]*m[2]*m[15]+m[5]*m[3]*m[14]+m[13]*m[2]*m[7]-m[13]*m[3]*m[6];
    inv[6]=-m[0]*m[6]*m[15]+m[0]*m[7]*m[14]+m[4]*m[2]*m[15]-m[4]*m[3]*m[14]-m[12]*m[2]*m[7]+m[12]*m[3]*m[6];
    inv[10]=m[0]*m[5]*m[15]-m[0]*m[7]*m[13]-m[4]*m[1]*m[15]+m[4]*m[3]*m[13]+m[12]*m[1]*m[7]-m[12]*m[3]*m[5];
    inv[14]=-m[0]*m[5]*m[14]+m[0]*m[6]*m[13]+m[4]*m[1]*m[14]-m[4]*m[2]*m[13]-m[12]*m[1]*m[6]+m[12]*m[2]*m[5];
    inv[3]=-m[1]*m[6]*m[11]+m[1]*m[7]*m[10]+m[5]*m[2]*m[11]-m[5]*m[3]*m[10]-m[9]*m[2]*m[7]+m[9]*m[3]*m[6];
    inv[7]=m[0]*m[6]*m[11]-m[0]*m[7]*m[10]-m[4]*m[2]*m[11]+m[4]*m[3]*m[10]+m[8]*m[2]*m[7]-m[8]*m[3]*m[6];
    inv[11]=-m[0]*m[5]*m[11]+m[0]*m[7]*m[9]+m[4]*m[1]*m[11]-m[4]*m[3]*m[9]-m[8]*m[1]*m[7]+m[8]*m[3]*m[5];
    inv[15]=m[0]*m[5]*m[10]-m[0]*m[6]*m[9]-m[4]*m[1]*m[10]+m[4]*m[2]*m[9]+m[8]*m[1]*m[6]-m[8]*m[2]*m[5];
    let det = m[0]*inv[0]+m[1]*inv[4]+m[2]*inv[8]+m[3]*inv[12];
    if(!det) return inv;
    det = 1.0/det;
    return inv.map(v=>v*det);
  }

  function bindMesh(program, m, withNormal){
    if(!m.buffers){
      m.buffers = {pos: gl.createBuffer(), color: gl.createBuffer()};
      gl.bindBuffer(gl.ARRAY_BUFFER, m.buffers.pos);
      gl.bufferData(gl.ARRAY_BUFFER, m.pos, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, m.buffers.color);
      gl.bufferData(gl.ARRAY_BUFFER, m.color, gl.STATIC_DRAW);
      if(m.normal){
        m.buffers.normal = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, m.buffers.normal);
        gl.bufferData(gl.ARRAY_BUFFER, m.normal, gl.STATIC_DRAW);
      }
    }
    attach(program.attrib.aPos, m.buffers.pos, 3);
    attach(program.attrib.aColor, m.buffers.color, 3);
    if(withNormal && m.buffers.normal) attach(program.attrib.aNormal, m.buffers.normal, 3);
  }

  function attach(location, buffer, size){
    if(location === undefined || location < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
  }

  function drawSky(inverseViewProj){
    const p = programs.sky;
    gl.useProgram(p.prog);
    gl.depthMask(false);
    gl.disable(gl.DEPTH_TEST);
    attach(p.attrib.aClip, skyBuffer, 2);
    gl.uniformMatrix4fv(p.uniform.uInverseViewProj, false, new Float32Array(inverseViewProj));
    gl.uniform3fv(p.uniform.uTop, SKY_TOP);
    gl.uniform3fv(p.uniform.uHorizon, SKY_HORIZON);
    gl.uniform3fv(p.uniform.uSun, SUN);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.enable(gl.DEPTH_TEST);
    gl.depthMask(true);
  }

  function draw(){
    if(!gl || lost || !programs) return;
    const w=canvas.width, h=canvas.height;
    gl.viewport(0,0,w,h);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    const view = camera(w/Math.max(h,1));
    const vp = new Float32Array(view.matrix);
    drawSky(view.inverse);

    // Ground.
    let p = programs.ground;
    gl.useProgram(p.prog);
    bindMesh(p, meshes.ground, false);
    gl.uniformMatrix4fv(p.uniform.uViewProj, false, vp);
    gl.uniform3fv(p.uniform.uSun, SUN);
    gl.uniform3fv(p.uniform.uEye, view.eye);
    gl.drawArrays(gl.TRIANGLES, 0, meshes.ground.count);

    // Greens, flags, posts.
    p = programs.solid;
    gl.useProgram(p.prog);
    gl.uniformMatrix4fv(p.uniform.uViewProj, false, vp);
    gl.uniform3fv(p.uniform.uSun, SUN);
    gl.uniform3fv(p.uniform.uEye, view.eye);
    gl.uniform1f(p.uniform.uAlpha, 1.0);
    if(meshes.furniture){
      bindMesh(p, meshes.furniture, true);
      gl.drawArrays(gl.TRIANGLES, 0, meshes.furniture.count);
    }

    // Markings, then tracers.
    p = programs.line;
    gl.useProgram(p.prog);
    gl.uniformMatrix4fv(p.uniform.uViewProj, false, vp);
    gl.uniform3fv(p.uniform.uEye, view.eye);
    gl.uniform1f(p.uniform.uAlpha, 0.55);
    bindMesh(p, meshes.markings, false);
    gl.drawArrays(gl.LINES, 0, meshes.markings.count);

    const traced = shots.filter(s=>s.points && s.points.length>1);
    let ballAt = null;
    traced.forEach(function(shot, index){
      const fresh = index===traced.length-1;
      let pts = shot.points;
      if(fresh && animation) pts = pts.slice(0, Math.max(2, animation.upto));
      if(fresh) ballAt = pts[pts.length-1];

      const pos=[], col=[];
      const tint = fresh ? [0.855, 0.965, 0.396] : [0.451, 0.573, 0.435];
      for(let i=1;i<pts.length;i++){
        pos.push(pts[i-1][2],pts[i-1][1],pts[i-1][0], pts[i][2],pts[i][1],pts[i][0]);
        col.push(tint[0],tint[1],tint[2], tint[0],tint[1],tint[2]);
      }
      uploadDynamic(new Float32Array(pos), new Float32Array(col));
      attach(p.attrib.aPos, dynamic.pos, 3);
      attach(p.attrib.aColor, dynamic.color, 3);
      gl.uniform1f(p.uniform.uAlpha,
        fresh ? 0.98 : Math.max(0.16, 0.62 - (traced.length-1-index)*0.075));
      gl.drawArrays(gl.LINES, 0, (pts.length-1)*2);
    });

    // Where each shot finished: a small mark on the turf.
    if(traced.length){
      const pos=[], col=[];
      shots.forEach(function(shot){
        const end = shot.points && shot.points.length
          ? shot.points[shot.points.length-1]
          : [shot.carryYards*YARD, 0, shot.offlineYards*YARD];
        const x = shot.points && shot.points.length ? end[2] : end[2];
        const z = shot.points && shot.points.length ? end[0] : end[0];
        const r = 0.55;
        for(let i=0;i<10;i++){
          const a0=2*Math.PI*i/10, a1=2*Math.PI*(i+1)/10;
          pos.push(x+Math.cos(a0)*r, 0.06, z+Math.sin(a0)*r,
                   x+Math.cos(a1)*r, 0.06, z+Math.sin(a1)*r);
          col.push(0.78,0.86,0.55, 0.78,0.86,0.55);
        }
      });
      uploadDynamic(new Float32Array(pos), new Float32Array(col));
      attach(p.attrib.aPos, dynamic.pos, 3);
      attach(p.attrib.aColor, dynamic.color, 3);
      gl.uniform1f(p.uniform.uAlpha, 0.7);
      gl.drawArrays(gl.LINES, 0, pos.length/3);
    }

    // The ball itself, with a shadow beneath it, while a shot is in the air.
    if(ballAt && animation){
      drawBall(view, vp, ballAt);
    }
  }

  function drawBall(view, vp, at){
    const x = at[2], y = at[1], z = at[0];
    const p = programs.solid;
    gl.useProgram(p.prog);
    gl.uniformMatrix4fv(p.uniform.uViewProj, false, vp);
    gl.uniform3fv(p.uniform.uSun, SUN);
    gl.uniform3fv(p.uniform.uEye, view.eye);

    // Shadow first: it spreads and fades the higher the ball is, the way a
    // real one does.
    const spread = 1.0 + Math.min(y, 40) * 0.09;
    gl.uniform1f(p.uniform.uAlpha, Math.max(0.05, 0.42 - y * 0.008));
    gl.depthMask(false);
    bindMesh(p, meshes.shadow, true);
    drawTranslatedScaled(p, x, 0.05, z, spread * 0.62, 1.0, spread * 0.62,
                         meshes.shadow.count);
    gl.depthMask(true);

    gl.uniform1f(p.uniform.uAlpha, 1.0);
    bindMesh(p, meshes.ball, true);
    drawTranslatedScaled(p, x, y, z, 1, 1, 1, meshes.ball.count);
  }

  function drawTranslatedScaled(program, tx, ty, tz, sx, sy, sz, count){
    // The meshes are built at the origin, so the model transform is folded
    // into the view-projection rather than kept as a separate uniform.
    const model = [sx,0,0,0, 0,sy,0,0, 0,0,sz,0, tx,ty,tz,1];
    const current = program.__vp || null;
    gl.uniformMatrix4fv(program.uniform.uViewProj, false,
                        new Float32Array(multiply(lastViewProj, model)));
    gl.drawArrays(gl.TRIANGLES, 0, count);
    gl.uniformMatrix4fv(program.uniform.uViewProj, false, new Float32Array(lastViewProj));
  }

  function uploadDynamic(pos, col){
    if(!dynamic.pos){ dynamic.pos = gl.createBuffer(); dynamic.color = gl.createBuffer(); }
    gl.bindBuffer(gl.ARRAY_BUFFER, dynamic.pos);
    gl.bufferData(gl.ARRAY_BUFFER, pos, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, dynamic.color);
    gl.bufferData(gl.ARRAY_BUFFER, col, gl.DYNAMIC_DRAW);
  }

  function frame(now){
    raf = null;
    if(animation){
      // Fractional progress, so the ball takes as long to fly as the shot
      // actually took. Advancing by a whole point per frame made every shot
      // last the same two seconds regardless of the club.
      const dt = lastFrame ? Math.min((now-lastFrame)/1000, 0.1) : 0.016;
      animation.progress += dt / animation.seconds;
      animation.upto = Math.max(2, Math.round(animation.total * Math.min(1, animation.progress)));
      if(animation.progress >= 1) animation = null;
    }
    lastFrame = now;
    draw();
    if(animation) schedule();
  }

  function schedule(){
    if(raf === null && !document.hidden && pane === "range")
      raf = requestAnimationFrame(frame);
  }

  function resize(){
    if(!canvas) return;
    // Cap the pixel ratio: a 3x Retina panel at full res costs fill rate for
    // no visible gain on lines this thin.
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(canvas.clientWidth * ratio));
    const h = Math.max(1, Math.round(canvas.clientHeight * ratio));
    if(canvas.width !== w || canvas.height !== h){ canvas.width=w; canvas.height=h; }
    schedule();
  }

  function start(){
    canvas = $("rangeCanvas");
    if(!canvas || gl) return true;
    try{
      gl = canvas.getContext("webgl2", {antialias:true, alpha:false, depth:true});
      if(!gl) throw new Error("WebGL 2 is not available");
      build();
    }catch(err){
      gl = null;
      fallback(err && err.message);
      return false;
    }
    canvas.addEventListener("webglcontextlost", function(e){
      e.preventDefault(); lost = true;
      if(raf){ cancelAnimationFrame(raf); raf=null; }
    });
    canvas.addEventListener("webglcontextrestored", function(){
      // Windows does this on a driver update. Rebuild rather than go black.
      lost = false; gl = canvas.getContext("webgl2", {antialias:true, alpha:false});
      try{ build(); rebuildScenery(); schedule(); }catch(e){ fallback(e.message); }
    });
    bindPointer();
    return true;
  }

  function fallback(reason){
    const box = $("rangeFallback");
    if(!box) return;
    box.classList.remove("hidden");
    box.innerHTML = "<div><strong>The 3D range cannot run on this computer.</strong><br>" +
      "Your shots are still measured and their numbers are still shown, on the " +
      "Shots tab and above.<br><small>" + esc(reason||"no WebGL") + "</small></div>";
    if(canvas) canvas.style.display = "none";
  }

  function bindPointer(){
    canvas.addEventListener("pointerdown", function(e){
      drag = {x:e.clientX, y:e.clientY};
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", function(e){
      if(!drag) return;
      orbit.yaw += (e.clientX-drag.x)*0.006;
      orbit.pitch = Math.max(0.02, Math.min(1.4, orbit.pitch + (e.clientY-drag.y)*0.004));
      drag = {x:e.clientX, y:e.clientY};
      schedule();
    });
    const stop = function(){ drag=null; };
    canvas.addEventListener("pointerup", stop);
    canvas.addEventListener("pointercancel", stop);
    canvas.addEventListener("wheel", function(e){
      e.preventDefault();
      orbit.dist = Math.max(30, Math.min(420, orbit.dist * (1 + e.deltaY*0.0012)));
      schedule();
    }, {passive:false});
    canvas.addEventListener("keydown", function(e){
      const step = 0.12;
      if(e.key==="ArrowLeft") orbit.yaw -= step;
      else if(e.key==="ArrowRight") orbit.yaw += step;
      else if(e.key==="ArrowUp") orbit.pitch = Math.min(1.4, orbit.pitch+0.06);
      else if(e.key==="ArrowDown") orbit.pitch = Math.max(0.02, orbit.pitch-0.06);
      else if(e.key==="+"||e.key==="=") orbit.dist = Math.max(30, orbit.dist*0.9);
      else if(e.key==="-") orbit.dist = Math.min(420, orbit.dist*1.1);
      else return;
      e.preventDefault(); schedule();
    });
  }

  function setView(name){
    view = name;
    // Behind is deliberately off to one side. From directly behind, the apex
    // and the landing project to nearly the same height on screen and every
    // shot reads as a vertical line -- the descent is real but invisible.
    // A three-quarter view gives the arc its horizontal extent back.
    // Down the line is the golfer's own view, where near-vertical is honest.
    if(VIEWS[name]) orbit = Object.assign({}, VIEWS[name]);
    schedule();
  }

  function apply(data){
    const previous = shots.length ? shots[shots.length-1].id : 0;
    shots = data.shots || []; byClub = data.byClub || [];
    targets = data.targets || []; markers = data.markers || [];
    count = data.count || 0;
    rebuildScenery();

    const newest = shots.length ? shots[shots.length-1] : null;
    if(newest && newest.id !== previous && newest.points && newest.points.length > 1){
      animation = reduced ? null
        : {upto: 2, progress: 0, total: newest.points.length,
           seconds: Math.max(0.8, newest.flightSeconds || 3)};
      lastFrame = 0;
    }
    renderHud(newest);
    renderClubs();
    schedule();
  }

  function renderHud(shot){
    const one = function(id, value){ const el=$(id); if(el) el.textContent=value; };
    if(!shot){
      one("hudCarry","--"); one("hudTotal","--"); one("hudApex","--");
      one("hudOffline","--");
      const club=$("hudClub"); if(club) club.textContent="";
    }else{
      one("hudCarry", Math.round(shot.carryYards));
      one("hudTotal", Math.round(shot.totalYards)+" yd");
      one("hudApex", Math.round(shot.apexFeet)+" ft");
      const off = Math.round(shot.offlineYards);
      one("hudOffline", off===0 ? "straight" :
        Math.abs(off)+" yd "+(off>0?"right":"left"));
      const club=$("hudClub"); if(club) club.textContent = shot.club || "";
    }
    const c=$("rangeCount");
    if(c) c.textContent = count ? count+(count===1?" shot":" shots") : "";
  }

  function renderClubs(){
    const host=$("rangeClubs");
    if(!host) return;
    if(!byClub.length){
      host.innerHTML='<div class="empty">Hit a ball and it will appear here.</div>';
      return;
    }
    host.innerHTML = byClub.map(function(row){
      return '<div class="rangeclub"><span class="rcname">'+esc(row.club)+'</span>'+
        '<span class="rcstat"><b>'+Math.round(row.carryAvg)+'</b> yd avg</span>'+
        '<span class="rcstat">best <b>'+Math.round(row.carryBest)+'</b></span>'+
        '<span class="rcstat">&plusmn;'+Math.round(row.offlineSigma)+' yd</span>'+
        '<span class="rcstat">'+row.shots+'</span></div>';
    }).join("");
  }

  return {start:start, apply:apply, resize:resize, setView:setView, schedule:schedule};
})();

async function refreshRange(){
  if(pane !== "range") return;
  try{ RANGE.apply(await api("/api/range")); }catch(e){}
}

document.querySelectorAll(".viewbtn[data-view]").forEach(function(button){
  button.addEventListener("click", function(){
    document.querySelectorAll(".viewbtn[data-view]").forEach(b=>b.classList.remove("on"));
    button.classList.add("on");
    RANGE.setView(button.dataset.view);
  });
});
$("rangeClear").addEventListener("click", e=>run(e.target, async()=>{
  RANGE.apply(await api("/api/range-clear",{}));
}));
$("rangeDemo").addEventListener("click", e=>run(e.target, async()=>{
  await api("/api/range-demo",{});
  await refreshRange();
}));
window.addEventListener("resize", function(){
  clearTimeout(window.__rangeResize);
  window.__rangeResize = setTimeout(()=>RANGE.resize(), 120);
});
document.addEventListener("visibilitychange", ()=>{ if(!document.hidden) RANGE.schedule(); });

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
  $("clubNote").textContent = log.club
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
      <td class="num" title="${row.worstSpeed==null?"":"from "+row.worstSpeed+" to "+row.bestSpeed+" mph"}">${
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
      <th class="num">Spin</th></tr></thead>
    <tbody>${recent.map(s=>`<tr class="${s.delivered?"":"lost"}">
      <td>${esc(s.timeText)}</td><td>${esc(s.club||"-")}</td>
      <td class="num">${s.speed==null?"-":s.speed}</td>
      <td class="num">${s.launch==null?"-":s.launch}</td>
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
    return `<a href="${esc(url)}" target="_blank" rel="noopener" title="${esc(image.name)}">
      <img src="${esc(url)}" alt="${esc(image.name)}" decoding="async">
      <small>${esc(image.name)}</small></a>`;
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
  if(pane==="setup"){
    const address=status.link && status.link.address ? status.link.address.split(":")[0] : "";
    const port=(status.link && status.link.device && status.link.device.portalPort) || 80;
    frameInto("setupFrame","setupHint", address?("http://"+address+(port===80?"":":"+port)):"",
      "Connect to PiTrac to change its settings.");
  }
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
refresh();
setInterval(()=>{ if(!busy && !asking()) refresh(); }, 3000);
// The range polls faster than the rest of the app, because a shot landing
// three seconds after it was hit does not feel like it belongs to the swing.
setInterval(()=>{ if(!busy && pane==="range" && !document.hidden) refreshRange(); }, 900);
</script>
</body>
</html>
"""
