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
    background:linear-gradient(to top,rgba(8,12,10,.85),transparent)}
  .views,.rangeright{display:flex;gap:6px;align-items:center}
  .viewbtn{background:rgba(20,26,23,.9);color:var(--muted);border:1px solid var(--line);
    border-radius:9px;padding:7px 11px;font-size:.76rem;font-weight:600;cursor:pointer;
    font-family:inherit}
  .viewbtn:hover{color:var(--text)}
  .viewbtn.on{background:var(--green);color:#0b0f0d;border-color:var(--green)}
  .viewbtn:focus-visible{outline:2px solid var(--green);outline-offset:2px}
  .rangecount{font-size:.72rem;color:var(--faint);font-variant-numeric:tabular-nums}
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
  let gl=null, canvas=null, program=null, buffers=null, raf=null, lost=false;
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

  // --- shader sources ---------------------------------------------------
  const VERT = `#version 300 es
    in vec3 aPos; in vec3 aColor;
    uniform mat4 uViewProj;
    uniform float uPointSize;
    out vec3 vColor; out float vDepth;
    void main(){
      vec4 clip = uViewProj * vec4(aPos, 1.0);
      gl_Position = clip;
      gl_PointSize = uPointSize;
      vColor = aColor;
      vDepth = clamp(clip.w / 400.0, 0.0, 1.0);
    }`;
  const FRAG = `#version 300 es
    precision highp float;
    in vec3 vColor; in float vDepth;
    uniform float uAlpha;
    out vec4 outColor;
    void main(){
      // Fade with distance so the far end of the range reads as far away.
      vec3 haze = vec3(0.055, 0.075, 0.065);
      outColor = vec4(mix(vColor, haze, vDepth * 0.55), uAlpha);
    }`;

  function compile(src, kind){
    const s = gl.createShader(kind);
    gl.shaderSource(s, src.trim());
    gl.compileShader(s);
    if(!gl.getShaderParameter(s, gl.COMPILE_STATUS))
      throw new Error(gl.getShaderInfoLog(s) || "shader failed to compile");
    return s;
  }

  function build(){
    program = gl.createProgram();
    gl.attachShader(program, compile(VERT, gl.VERTEX_SHADER));
    gl.attachShader(program, compile(FRAG, gl.FRAGMENT_SHADER));
    gl.linkProgram(program);
    if(!gl.getProgramParameter(program, gl.LINK_STATUS))
      throw new Error(gl.getProgramInfoLog(program) || "program failed to link");
    gl.useProgram(program);
    buffers = {pos: gl.createBuffer(), color: gl.createBuffer(), vao: gl.createVertexArray()};
    gl.bindVertexArray(buffers.vao);
    const aPos = gl.getAttribLocation(program, "aPos");
    const aColor = gl.getAttribLocation(program, "aColor");
    gl.bindBuffer(gl.ARRAY_BUFFER, buffers.pos);
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffers.color);
    gl.enableVertexAttribArray(aColor);
    gl.vertexAttribPointer(aColor, 3, gl.FLOAT, false, 0, 0);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
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
  function scene(){
    const pos=[], col=[];
    const line=(a,b,c)=>{ pos.push(a[0],a[1],a[2], b[0],b[1],b[2]); col.push(c[0],c[1],c[2], c[0],c[1],c[2]); };

    const far = 320*YARD, wide = 70*YARD;

    // Ground beyond the mown range, so the turf does not end at a hard edge
    // into nothing. The distance haze in the shader takes care of the rest.
    const out = 900*YARD, back = 120*YARD;
    pos.push(-out,-0.05,-back,  out,-0.05,-back,  out,-0.05,out,
             -out,-0.05,-back,  out,-0.05,out,   -out,-0.05,out);
    for(let i=0;i<6;i++) col.push(0.052,0.086,0.062);

    // Mown stripes, alternating, which is what makes it read as turf.
    for(let y=0; y<320; y+=10){
      const shade = (y/10)%2 ? [0.135,0.235,0.155] : [0.108,0.196,0.130];
      const z0=y*YARD, z1=Math.min(y+10,320)*YARD;
      pos.push(-wide,0,z0,  wide,0,z0,  wide,0,z1,
               -wide,0,z0,  wide,0,z1, -wide,0,z1);
      for(let i=0;i<6;i++) col.push(shade[0],shade[1],shade[2]);
    }
    const groundVerts = pos.length/3;

    // Distance markers, and a line across the range at each.
    markers.forEach(function(yards){
      const z = yards*YARD, grey=[0.30,0.36,0.32];
      line([-wide,0.02,z],[wide,0.02,z],grey);
      [-1,1].forEach(function(side){
        const x = side*wide*0.86;
        for(let h=0; h<3; h++)
          line([x,h*0.6,z],[x,(h+1)*0.6-0.15,z],[0.55,0.62,0.55]);
      });
    });

    // Target greens: a ring on the ground, plus a flag.
    targets.forEach(function(yards){
      const z=yards*YARD, r=9*YARD, ring=[0.35,0.72,0.45];
      let prev=null;
      for(let a=0;a<=48;a++){
        const th=a/48*Math.PI*2, pt=[Math.cos(th)*r, 0.03, z+Math.sin(th)*r];
        if(prev) line(prev, pt, ring);
        prev = pt;
      }
      line([0,0,z],[0,2.2,z],[0.85,0.88,0.85]);
      line([0,2.2,z],[0.9,1.95,z],[0.90,0.30,0.30]);
      line([0.9,1.95,z],[0,1.75,z],[0.90,0.30,0.30]);
    });

    // Centre line down the range.
    line([0,0.02,0],[0,0.02,far],[0.22,0.30,0.24]);
    return {pos:new Float32Array(pos), col:new Float32Array(col), ground:groundVerts};
  }

  let staticScene=null;

  function camera(aspect){
    if(view==="top"){
      // Looking straight down at the middle of the range. High enough, and
      // through a narrow enough lens, that it reads as a plan rather than as a
      // trapezoid: this view exists to show dispersion, and perspective would
      // make the far shots look tighter than they were.
      const mid = 150*YARD;
      return multiply(perspective(Math.PI/7, aspect, 1.0, 1600),
                      lookAt([0, 560, mid], [0, 0, mid], [0,0,1]));
    }
    // Behind and down-the-line are the same orbiting camera at different
    // starting points, so dragging works identically in both.
    const focus = [0, 12, 105*YARD];
    const flat = orbit.dist*Math.cos(orbit.pitch);
    const eye = [focus[0] + Math.sin(orbit.yaw)*flat,
                 focus[1] + orbit.dist*Math.sin(orbit.pitch),
                 focus[2] - Math.cos(orbit.yaw)*flat];
    return multiply(perspective(Math.PI/4, aspect, 0.5, 1200),
                    lookAt(eye, focus, [0,1,0]));
  }

  function draw(){
    if(!gl || lost) return;
    const w=canvas.width, h=canvas.height;
    gl.viewport(0,0,w,h);
    // A dusk sky rather than black, so the horizon is a horizon.
    gl.clearColor(0.055,0.075,0.088,1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if(!staticScene) return;

    const vp = camera(w/Math.max(h,1));
    gl.uniformMatrix4fv(gl.getUniformLocation(program,"uViewProj"), false, new Float32Array(vp));
    gl.uniform1f(gl.getUniformLocation(program,"uPointSize"), Math.max(3, w/260));
    const alpha = gl.getUniformLocation(program,"uAlpha");

    // Ground and furniture.
    upload(staticScene.pos, staticScene.col);
    gl.uniform1f(alpha, 1.0);
    gl.drawArrays(gl.TRIANGLES, 0, staticScene.ground);
    gl.drawArrays(gl.LINES, staticScene.ground,
                  staticScene.pos.length/3 - staticScene.ground);

    // Tracers, oldest faintest.
    const traced = shots.filter(s=>s.points && s.points.length>1);
    traced.forEach(function(shot, index){
      const age = traced.length-1-index;
      const fresh = index===traced.length-1;
      let pts = shot.points;
      if(fresh && animation) pts = pts.slice(0, Math.max(2, animation.upto));
      const pos=[], col=[];
      const tint = fresh ? [0.80,0.95,0.35] : [0.42,0.55,0.40];
      // The physics reports x downrange and z offline; the scene is built with
      // z downrange and x across. Swap here rather than in the model, so the
      // model stays in the axes a ball flight is naturally written in.
      for(let i=1;i<pts.length;i++){
        pos.push(pts[i-1][2],pts[i-1][1],pts[i-1][0], pts[i][2],pts[i][1],pts[i][0]);
        col.push(tint[0],tint[1],tint[2], tint[0],tint[1],tint[2]);
      }
      // Where it finished.
      const end = pts[pts.length-1];
      pos.push(end[2], 0.05, end[0]); col.push(tint[0],tint[1],tint[2]);
      upload(new Float32Array(pos), new Float32Array(col));
      gl.uniform1f(alpha, fresh ? 1.0 : Math.max(0.18, 0.75 - age*0.09));
      gl.drawArrays(gl.LINES, 0, (pts.length-1)*2);
      gl.drawArrays(gl.POINTS, (pts.length-1)*2, 1);
    });
  }

  function upload(pos, col){
    gl.bindBuffer(gl.ARRAY_BUFFER, buffers.pos);
    gl.bufferData(gl.ARRAY_BUFFER, pos, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffers.color);
    gl.bufferData(gl.ARRAY_BUFFER, col, gl.DYNAMIC_DRAW);
  }

  function frame(now){
    raf = null;
    if(animation){
      const dt = lastFrame ? (now-lastFrame)/1000 : 0.016;
      animation.upto += Math.max(1, Math.round(animation.total * dt / animation.seconds));
      if(animation.upto >= animation.total) animation = null;
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
      staticScene = scene();
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
      try{ build(); staticScene = scene(); schedule(); }catch(e){ fallback(e.message); }
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
    if(staticScene === null && gl) staticScene = scene();
    else if(gl) staticScene = scene();

    const newest = shots.length ? shots[shots.length-1] : null;
    if(newest && newest.id !== previous && newest.points && newest.points.length > 1){
      animation = reduced ? null
        : {upto: 2, total: newest.points.length, seconds: Math.max(0.8, newest.flightSeconds||3)};
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
