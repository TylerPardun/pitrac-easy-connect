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

function renderDetails(data){
  const device=(data.link&&data.link.device)||{};
  const enclosure=data.enclosure||{};
  const network=enclosure.network||{};
  const shots=data.shots||{};
  const rows=[["Enclosure",device.displayName||"-"],["Device",device.deviceId||"-"],
    ["Address",(data.link&&data.link.address)||"-"],
    ["Wi-Fi",(network.connection&&network.connection.ssid)||"-"],
    ["Shots sent",shots.delivered!=null?shots.delivered:"-"],
    ["Not delivered",shots.lost!=null?shots.lost:"-"],
    ["PiTrac",device.version||"-"],["This computer",data.version]];
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

function loadFrames(){
  if(!status) return;
  // Load a frame the first time its tab is opened, so the enclosure is not
  // serving two extra pages to a window nobody has looked at.
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
