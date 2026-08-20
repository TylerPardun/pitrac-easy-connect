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
<title>PiTrac</title>
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
  label.field{display:block;color:var(--muted);font-size:.88rem;margin-bottom:9px}

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
  <button data-pane="shots">Shots</button>
  <button data-pane="pitrac">PiTrac</button>
  <button data-pane="setup">Setup</button>
</nav>

<div class="pane on" id="pane-play"><div class="centre">
<main>
  <div class="brand">PiTrac</div>

  <div class="status">
    <div class="dot" id="dot"></div>
    <div style="flex:1">
      <h1 id="head">Starting</h1>
      <div class="sub" id="sub"></div>
      <div class="why" id="why"></div>
    </div>
  </div>

  <div id="err"></div>

  <div class="do" id="do"></div>

  <div id="update"></div>

  <div class="pick hidden" id="pick"></div>

  <div class="pick hidden" id="codeBox">
    <label class="field" for="code">Enter the six-digit code shown on the PiTrac setup page</label>
    <input type="text" id="code" inputmode="numeric" maxlength="6" placeholder="000000"
           autocomplete="off">
    <button class="primary" id="doPair">Pair</button>
    <button class="quiet" id="cancelPair">Cancel</button>
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
      <button class="quiet" id="quit">Stop Easy Connect</button>

      <h3>Details</h3>
      <dl class="kv" id="kv"></dl>
      <div id="note"></div>
    </div>
  </details>
</main>
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
let status=null, pairing=null, busy=false;

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
  if(!error){$("err").innerHTML="";return;}
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

// --- the single line, and the single thing to do about it ----------------

function present(data){
  const linked=data.link && data.link.connected;
  const sim=data.simulatorStatus||{};
  const steps={}; (data.chain||[]).forEach(s=>steps[s.key]=s);

  if(!data.pairedEnclosures.length && !pairing) return {
    dot:"", head:"Set up PiTrac", sub:"Let's find your enclosure.",
    why:"PiTrac needs to be powered on and on this network.",
    actions:[{label:"Find my PiTrac", id:"find", primary:true}], find:true};

  if(pairing) return {dot:"busy", head:"Pairing", sub:"", why:"", actions:[]};

  if(!linked) return {
    dot:"busy", head:"Looking for PiTrac", sub:"",
    why:"Check PiTrac has power and is on this network.",
    actions:[{label:"Search again", id:"find", primary:false}], find:true};

  const name=(data.link.device&&data.link.device.displayName)||"PiTrac";

  if(steps.pitrac && !steps.pitrac.ok) return {
    dot:"bad", head:"PiTrac needs attention", sub:esc(steps.pitrac.detail),
    why:"Easy Connect is connected, but the launch monitor cannot measure a shot yet.",
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
  const view=present(data);

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
  $("adv").classList.toggle("hidden", !data.pairedEnclosures.length);
  // The other tabs only mean anything once there is an enclosure to show.
  $("tabs").classList.toggle("hidden", !(data.link && data.link.connected));
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
    ["PiTrac",device.version||"-"],["This computer",data.version],
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
      pairing=id; host.classList.add("hidden");
      $("codeBox").classList.remove("hidden"); $("code").focus();
    }));
  }catch(error){ showError(error); host.classList.add("hidden"); }
}

$("cancelPair").addEventListener("click",()=>{
  pairing=null; $("codeBox").classList.add("hidden"); refresh();
});
$("doPair").addEventListener("click",e=>run(e.target, async()=>{
  const code=$("code").value.replace(/\D/g,"");
  const target=pairing;
  pairing=null;
  await api("/api/pair",{deviceId:target, code});
  $("codeBox").classList.add("hidden"); $("code").value="";
}));
$("code").addEventListener("keydown",e=>{ if(e.key==="Enter") $("doPair").click(); });

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
  if(!confirm("Stop Easy Connect?\n\nShots will stop reaching your simulator until you start it again.")) return;
  await api("/api/quit",{});
  document.body.innerHTML='<main><div class="brand">PiTrac</div>'+
    '<div class="status"><div class="dot"></div><div><h1>Easy Connect has stopped</h1>'+
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

let pane="play";

function showPane(name){
  pane=name;
  document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("on", p.id==="pane-"+name));
  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on", b.dataset.pane===name));
  loadFrames();
}
document.querySelectorAll("#tabs button").forEach(button=>
  button.addEventListener("click",()=>showPane(button.dataset.pane)));

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
    $("head").textContent="Easy Connect has stopped";
    $("sub").textContent="You can close this window.";
    $("why").textContent="";
  }
}
refresh();
setInterval(()=>{ if(!busy && !pairing) refresh(); }, 3000);
</script>
</body>
</html>
"""
