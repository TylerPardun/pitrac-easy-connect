"""The Companion window, which is a local web page.

The chain is the centrepiece. Four hops, always in the same order, each one
either done or the single next thing to fix. That is what replaces
"Disconnected" as an answer to "why can't I play?".
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PiTrac Easy Connect</title>
<style>
  :root{color-scheme:dark;--bg:#0c1210;--panel:#151d19;--line:#2b3931;--text:#f4f7f5;
    --muted:#9eada5;--green:#58d68d;--red:#ff786f;--amber:#f7c85d;--accent:#dff86d;--accent-text:#172008}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(circle at 15% -10%,#22372b 0,#0c1210 38%);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;line-height:1.5}
  main{width:min(760px,calc(100% - 28px));margin:34px auto 64px}
  .eyebrow{color:var(--green);font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:.72rem}
  h1{margin:.3rem 0 .3rem;font-size:clamp(1.9rem,5.5vw,3rem);line-height:1.03}
  .lede{color:var(--muted);margin:0}
  .panel{margin-top:22px;padding:22px;border:1px solid var(--line);border-radius:18px;
    background:rgba(21,29,25,.94);box-shadow:0 18px 60px rgba(0,0,0,.25)}
  h2{margin:0 0 6px;font-size:1.12rem}
  .hint{color:var(--muted);font-size:.92rem;margin:0 0 14px}
  .state{display:flex;gap:14px;align-items:flex-start}
  .dot{width:12px;height:12px;border-radius:50%;background:var(--muted);margin-top:7px;flex:none}
  .dot.good{background:var(--green)}.dot.bad{background:var(--red)}.dot.busy{background:var(--amber)}
  button{font:inherit}
  .primary{border:0;border-radius:12px;padding:13px 20px;font-weight:800;cursor:pointer;
    background:var(--accent);color:var(--accent-text)}
  .secondary{border:1px solid var(--line);border-radius:12px;padding:12px 18px;font-weight:700;
    cursor:pointer;background:#2a352f;color:var(--text)}
  .danger{border:1px solid rgba(255,120,111,.4);border-radius:12px;padding:12px 18px;font-weight:700;
    cursor:pointer;background:rgba(255,120,111,.12);color:var(--red)}
  button:disabled{opacity:.5;cursor:progress}
  .actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}
  .choices{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
  .choice{text-align:left;color:var(--text);background:#101713;border:1px solid var(--line);
    border-radius:14px;padding:16px;cursor:pointer}
  .choice:hover{border-color:#52685b}
  .choice.on{border-color:var(--green);box-shadow:0 0 0 2px rgba(88,214,141,.13)}
  .choice strong{display:block;font-size:1.02rem}
  .choice small{display:block;color:var(--muted);margin-top:4px}
  .chain{margin-top:6px}
  .hop{display:grid;grid-template-columns:auto 1fr;gap:14px;padding:14px 0;border-bottom:1px solid var(--line)}
  .hop:last-child{border-bottom:0}
  .mark{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-weight:800;
    font-size:.85rem;background:#29342e;color:var(--muted);border:1px solid var(--line)}
  .mark.ok{background:rgba(88,214,141,.16);color:var(--green);border-color:rgba(88,214,141,.4)}
  .mark.now{background:var(--amber);color:#241d05;border-color:var(--amber)}
  .hop strong{display:block}
  .hop small{color:var(--muted)}
  .err{margin-top:14px;padding:15px 17px;border-radius:12px;border:1px solid rgba(255,120,111,.4);
    background:rgba(255,120,111,.07)}
  .err h3{margin:0 0 8px;font-size:1rem;color:var(--red)}
  .err dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:5px 12px;font-size:.92rem}
  .err dt{color:var(--muted);white-space:nowrap}
  .err dd{margin:0}
  .code{margin-top:6px;color:var(--muted);font-size:.8rem;letter-spacing:.06em}
  .note{margin-top:14px;padding:13px 15px;border-radius:12px;background:#0f1612;border:1px solid var(--line);color:var(--muted)}
  .note.good{border-color:rgba(88,214,141,.4);color:var(--green)}
  .note.bad{border-color:rgba(255,120,111,.4);color:var(--red)}
  .note.busy{border-color:rgba(247,200,93,.4);color:var(--amber)}
  .device{width:100%;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;text-align:left;
    padding:14px 16px;margin-bottom:8px;border:1px solid var(--line);border-radius:12px;background:#101713;
    color:var(--text);cursor:pointer}
  .device:hover{border-color:#52685b}
  .device small{color:var(--muted);display:block}
  .pill{border-radius:99px;padding:5px 10px;font-weight:750;font-size:.74rem;background:#29342e;color:var(--muted)}
  .pill.good{background:rgba(88,214,141,.14);color:var(--green)}
  label{display:block;font-weight:700;margin:14px 0 6px}
  input[type=text]{width:100%;padding:13px 14px;border-radius:12px;border:1px solid var(--line);
    background:#0f1612;color:var(--text);font:inherit;letter-spacing:.2em;font-size:1.3rem;text-align:center}
  details{margin-top:18px}
  summary{cursor:pointer;color:var(--muted);font-weight:700}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:.88rem;margin-top:12px}
  .kv dt{color:var(--muted)}
  .kv dd{margin:0;word-break:break-all}
  .hidden{display:none}
  @media(max-width:560px){.choices{grid-template-columns:1fr}.panel{padding:17px}}
</style>
</head>
<body>
<main>
  <div class="eyebrow">PiTrac</div>
  <h1>Easy Connect</h1>
  <p class="lede" id="lede">Starting…</p>

  <section class="panel">
    <div class="state">
      <div class="dot" id="stateDot"></div>
      <div>
        <h2 id="stateHead">Starting</h2>
        <p class="hint" id="stateDetail" style="margin:4px 0 0"></p>
      </div>
    </div>
    <div id="stateError"></div>
  </section>

  <!-- Pairing -->
  <section class="panel" id="panelPair">
    <h2>Connect to your PiTrac</h2>
    <p class="hint">Easy Connect looks for PiTrac enclosures on this network.</p>
    <div id="deviceList"><p class="hint">Searching…</p></div>
    <div class="actions"><button class="secondary" id="search">Search again</button></div>

    <div id="codeBox" class="hidden">
      <label for="code">Enter the six-digit code shown on the PiTrac setup page</label>
      <input type="text" id="code" inputmode="numeric" maxlength="7" placeholder="000000">
      <div class="actions">
        <button class="primary" id="doPair">Pair</button>
        <button class="secondary" id="cancelPair">Cancel</button>
      </div>
    </div>
  </section>

  <!-- Simulator -->
  <section class="panel" id="panelSim">
    <h2>Your golf simulator</h2>
    <p class="hint">Choose the software running on this computer.</p>
    <div class="choices">
      <button class="choice" data-sim="gspro"><strong>GSPro</strong><small>Uses GSPro Open Connect</small></button>
      <button class="choice" data-sim="e6"><strong>E6 Connect</strong><small>Uses the E6 TruSim interface</small></button>
    </div>
  </section>

  <!-- Chain -->
  <section class="panel" id="panelChain">
    <h2>The path from PiTrac to your simulator</h2>
    <p class="hint" id="chainHint">Each step has to work before a shot can be scored.</p>
    <div class="chain" id="chain"></div>
    <div class="actions">
      <button class="secondary" id="check">Check again</button>
      <button class="primary" id="test">Send a test shot</button>
    </div>
    <div class="note" id="testWarn">A test shot is a real shot to your simulator. If a round is
      open it may be scored. Close or restart the round first if that matters.</div>
    <div id="shotNote"></div>
  </section>

  <!-- Enclosure -->
  <section class="panel" id="panelPi">
    <h2>Your PiTrac enclosure</h2>
    <p class="hint" id="piHint">Not connected.</p>
    <div class="actions">
      <button class="secondary" id="piRestart">Restart PiTrac</button>
      <button class="secondary" id="piCard">Show owner card</button>
      <button class="danger" id="piShutdown">Shut down safely</button>
      <button class="danger" id="piForget">Unpair this computer</button>
    </div>
    <div id="piNote"></div>
    <details>
      <summary>Advanced details</summary>
      <dl class="kv" id="advanced"></dl>
    </details>
  </section>

  <section class="panel" id="panelBackup">
    <h2>Backup and restore</h2>
    <p class="hint">Calibration is the part worth keeping. Save the file on this computer, not
      on PiTrac&mdash;a backup stored on the memory card cannot help you when the memory card
      is the problem.</p>
    <div class="row" style="display:flex;gap:8px;align-items:center;color:var(--muted);font-size:.92rem">
      <input type="checkbox" id="bkSecrets" style="width:auto">
      <label for="bkSecrets" style="margin:0;font-weight:400">Also include the enclosure's
        identity and paired computers</label>
    </div>
    <div class="note" id="bkSecretNote" style="display:none">Include these only if you might
      replace the memory card in this enclosure. The file will then contain the setup Wi-Fi
      password and your pairing keys.</div>
    <div class="actions">
      <button class="primary" id="makeBackup">Save a backup</button>
      <label class="secondary" for="bkFile" style="display:inline-block;cursor:pointer">Restore from a file</label>
      <input type="file" id="bkFile" accept=".pitracbackup,.json,application/json" style="display:none">
    </div>
    <div id="bkPreview"></div>
    <div id="bkNote"></div>
  </section>
</main>

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
function showError(target, error){
  if(!error){target.innerHTML="";return;}
  const info=error.info||{};
  target.innerHTML=`<div class="err"><h3>${esc(info.failed||error.message)}</h3><dl>
    ${info.stillSafe?`<dt>Still safe</dt><dd>${esc(info.stillSafe)}</dd>`:""}
    ${info.nextStep?`<dt>What to do</dt><dd>${esc(info.nextStep)}</dd>`:""}
    </dl>${info.code?`<div class="code">Reference ${esc(info.code)}</div>`:""}</div>`;
}
async function run(button, work){
  if(busy) return; busy=true;
  const label=button?button.textContent:null;
  if(button){button.disabled=true;button.textContent="Working…";}
  showError($("stateError"), null);
  try{ await work(); }
  catch(error){ showError($("stateError"), error); }
  finally{ busy=false; if(button){button.disabled=false;button.textContent=label;} await refresh(); }
}

function render(data){
  status=data;
  $("lede").textContent=data.computerName+" · Easy Connect "+data.version;
  $("stateHead").textContent=data.headline;
  $("stateDetail").textContent=data.detail;
  $("stateDot").className="dot "+(data.ready?"good":data.state==="CONNECTING"?"busy":
    data.state==="SETUP REQUIRED"?"bad":"busy");

  const linked=data.link&&data.link.connected;
  $("panelPair").classList.toggle("hidden", linked && !pairing);
  $("panelSim").classList.toggle("hidden", !linked);
  $("panelChain").classList.toggle("hidden", !linked);
  $("panelPi").classList.toggle("hidden", !linked);
  $("panelBackup").classList.toggle("hidden", !linked);

  if(!linked && data.link && data.link.lastError && !pairing){
    showError($("stateError"), {message:data.link.lastError.failed, info:data.link.lastError});
  }

  document.querySelectorAll(".choice").forEach(b=>b.classList.toggle("on", b.dataset.sim===data.simulator));

  let reached=true;
  $("chain").innerHTML=data.chain.map((hop,index)=>{
    const isNext=reached&&!hop.ok; if(!hop.ok) reached=false;
    return `<div class="hop"><span class="mark ${hop.ok?"ok":isNext?"now":""}">${hop.ok?"&#10003;":index+1}</span>
      <div><strong>${esc(hop.title)}</strong><small>${esc(hop.detail)}</small></div></div>`;
  }).join("");
  $("chainHint").textContent=data.ready?"Everything checks out. Go hit a ball.":
    (data.nextStep?"Next: "+data.nextStep:"Each step has to work before a shot can be scored.");

  const shots=data.shots||{};
  $("shotNote").innerHTML = (shots.delivered||shots.lost) ?
    `<div class="note ${shots.lost?"bad":"good"}">Shots sent to ${esc(data.simulatorLabel)}: ${shots.delivered}.
     Not delivered: ${shots.lost}.</div>` : "";

  const enclosure=data.enclosure||{};
  const device=(data.link&&data.link.device)||{};
  $("piHint").textContent = device.displayName ?
    device.displayName+" · device "+device.deviceId+(enclosure.state?" · "+enclosure.state:"") : "Connected.";
  renderAdvanced(data, enclosure, device);
}

function renderAdvanced(data, enclosure, device){
  const network=enclosure.network||{};
  const rows=[["Companion state",data.state],["Enclosure state",enclosure.state||"unknown"],
    ["Enclosure",device.displayName||"-"],["Device ID",device.deviceId||"-"],
    ["Enclosure address",(data.link&&data.link.address)||"-"],
    ["Enclosure version",device.version||"-"],["Companion version",data.version],
    ["Network mode",network.mode||"-"],
    ["Wi-Fi",(network.connection&&network.connection.ssid)||"-"],
    ["Simulator",data.simulatorLabel+" at "+((enclosure.relay&&JSON.stringify(enclosure.relay.ports))||"-")],
    ["Test shot accepted",data.simulatorStatus.testShotAccepted?"yes":"no"]];
  $("advanced").innerHTML=rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

// --- pairing ------------------------------------------------------------

async function search(){
  const host=$("deviceList");
  host.innerHTML='<p class="hint">Searching…</p>';
  try{
    const data=await api("/api/search");
    host.innerHTML = data.enclosures.length ? data.enclosures.map(e=>`
      <button class="device" data-id="${esc(e.deviceId)}" data-paired="${e.paired?"1":""}">
        <span><strong>${esc(e.displayName)}</strong>
          <small>Device ${esc(e.shortId)} · ${esc(e.state||"")} · ${esc(e.address)}</small></span>
        <span class="pill ${e.paired?"good":""}">${e.paired?"PAIRED":"NEW"}</span>
      </button>`).join("") :
      `<p class="hint">No PiTrac found. Check that it has power and that this computer is on the
        same network. If PiTrac is showing its own setup signal, join that signal first.</p>`;
    host.querySelectorAll(".device").forEach(button=>button.addEventListener("click",()=>{
      const id=button.dataset.id;
      if(button.dataset.paired){ run(button, ()=>api("/api/connect",{deviceId:id})); return; }
      pairing=id; $("codeBox").classList.remove("hidden"); $("code").focus();
    }));
  }catch(error){ showError($("stateError"), error); host.innerHTML=""; }
}

$("search").addEventListener("click",e=>run(e.target, search));
$("cancelPair").addEventListener("click",()=>{pairing=null;$("codeBox").classList.add("hidden");});
$("doPair").addEventListener("click",e=>run(e.target, async()=>{
  const code=$("code").value.replace(/\D/g,"");
  await api("/api/pair",{deviceId:pairing, code});
  pairing=null; $("codeBox").classList.add("hidden"); $("code").value="";
}));

document.querySelectorAll(".choice").forEach(button=>button.addEventListener("click",
  e=>run(e.currentTarget, ()=>api("/api/simulator",{simulator:e.currentTarget.dataset.sim}))));

$("check").addEventListener("click",e=>run(e.target,()=>api("/api/check",{})));
$("test").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Send a test shot to "+status.simulatorLabel+"?\n\nThis is a real shot. If a round is open in your simulator it may be scored.")) return;
  await api("/api/test-shot",{});
}));

$("piRestart").addEventListener("click",e=>run(e.target, async()=>{
  await api("/api/enclosure",{command:"restartPitrac"});
  $("piNote").innerHTML='<div class="note good">PiTrac was restarted.</div>';
}));
$("piCard").addEventListener("click",e=>run(e.target, async()=>{
  const data=await api("/api/enclosure",{command:"ownerCard"});
  $("piNote").innerHTML='<div class="note"><pre style="margin:0;white-space:pre-wrap;font:inherit">'+esc(data.text)+"</pre></div>";
}));
$("piShutdown").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Shut PiTrac down safely?\n\nSettings are saved first. Wait for the green light on the Raspberry Pi to stop blinking before unplugging it.")) return;
  await api("/api/enclosure",{command:"shutdown"});
  $("piNote").innerHTML='<div class="note busy">Shutting down. Wait until the green light on the Raspberry Pi stops blinking, then it is safe to unplug.</div>';
}));
$("piForget").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Unpair this computer from PiTrac?\n\nREMOVED: this computer's access.\nKEPT: PiTrac's Wi-Fi networks, calibration, and other paired computers.\n\nYou can pair again with a new code.")) return;
  await api("/api/forget",{deviceId:status.activeDeviceId});
}));

// --- backup and restore --------------------------------------------------

let pendingBackup=null;

$("bkSecrets").addEventListener("change",e=>{
  $("bkSecretNote").style.display = e.target.checked ? "" : "none";
});

$("makeBackup").addEventListener("click",e=>run(e.target,async()=>{
  window.location.href="/api/backup"+($("bkSecrets").checked?"?identity=1&pairings=1":"");
  $("bkNote").innerHTML='<div class="note good">Your backup is being saved to this computer.</div>';
}));

$("bkFile").addEventListener("change",async event=>{
  const file=event.target.files && event.target.files[0];
  if(!file) return;
  $("bkPreview").innerHTML=""; $("bkNote").innerHTML="";
  try{
    const text=await file.text();
    const info=await api("/api/backup/inspect",{file:text});
    pendingBackup=text;
    renderBackupPreview(info);
  }catch(error){ pendingBackup=null; showError($("stateError"),error); }
  event.target.value="";
});

function renderBackupPreview(info){
  const differs=!info.sameDevice;
  $("bkPreview").innerHTML=`
    <div class="note">
      <strong>${esc(info.displayName)}</strong> &middot; made ${esc(info.createdText)}
      &middot; Easy Connect ${esc(info.createdBy)}
      <div style="margin-top:8px">Contains: ${info.sectionLabels.map(esc).join(" &middot; ")}</div>
      ${differs?'<div style="margin-top:8px;color:var(--amber)">This backup came from a different '+
        'enclosure. Camera calibration only matches the cameras it was made with.</div>':""}
    </div>
    <div class="actions">
      <button class="primary" id="doRestore">Restore</button>
      <button class="secondary" id="cancelRestore">Cancel</button>
    </div>`;
  $("cancelRestore").addEventListener("click",()=>{pendingBackup=null;$("bkPreview").innerHTML="";});
  $("doRestore").addEventListener("click",e=>run(e.target,async()=>{
    if(differs&&!confirm("This backup is from a different enclosure.\n\nCamera calibration only "+
      "matches the cameras it was made with. Restore it anyway?")) return;
    const result=await api("/api/backup/restore",{
      file:pendingBackup, calibration:true, preferences:true,
      identity:info.sections.includes("identity"),
      pairings:info.sections.includes("pairings"),
      confirmDifferentDevice:true,
    });
    pendingBackup=null; $("bkPreview").innerHTML="";
    $("bkNote").innerHTML='<div class="note good">Restored: '+
      (result.restored.map(esc).join(", ")||"nothing")+
      (result.needsRestart?". Press Restart PiTrac so it picks up the restored settings.":"")+'</div>';
  }));
}

async function refresh(){
  try{ render(await api("/api/status")); }
  catch(error){ $("stateHead").textContent="Easy Connect stopped responding"; $("stateDot").className="dot bad"; }
}
refresh().then(()=>{ if(!(status&&status.link&&status.link.connected)) search(); });
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
