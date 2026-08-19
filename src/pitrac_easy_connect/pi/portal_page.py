"""The markup for the enclosure's setup page.

Kept apart from the request handling so the wording and the plumbing can be
changed without disturbing each other.

Three rules from the product requirements shape every screen here: one primary
action per screen, never an IP address or a port in the normal path, and status
carried by words as well as colour.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PiTrac setup</title>
<style>
  :root{color-scheme:dark;--bg:#0c1210;--panel:#151d19;--line:#2b3931;--text:#f4f7f5;
    --muted:#9eada5;--green:#58d68d;--red:#ff786f;--amber:#f7c85d;--accent:#dff86d;--accent-text:#172008}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(circle at 15% -10%,#22372b 0,#0c1210 38%);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;line-height:1.5}
  main{width:min(680px,calc(100% - 28px));margin:32px auto 64px}
  .eyebrow{color:var(--green);font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:.72rem}
  h1{margin:.3rem 0 .2rem;font-size:clamp(1.8rem,5vw,2.8rem);line-height:1.05}
  .lede{color:var(--muted);font-size:1.05rem;margin:0 0 4px}
  .panel{margin-top:22px;padding:22px;border:1px solid var(--line);border-radius:18px;
    background:rgba(21,29,25,.94);box-shadow:0 18px 60px rgba(0,0,0,.25)}
  h2{margin:0 0 6px;font-size:1.15rem}
  .hint{color:var(--muted);font-size:.92rem;margin:0 0 14px}
  .state{display:flex;gap:14px;align-items:flex-start}
  .dot{width:12px;height:12px;border-radius:50%;background:var(--muted);margin-top:7px;flex:none}
  .dot.good{background:var(--green)}.dot.bad{background:var(--red)}.dot.busy{background:var(--amber)}
  .state h2{margin:0}
  button{font:inherit}
  .primary{border:0;border-radius:12px;padding:13px 20px;font-weight:800;cursor:pointer;
    background:var(--accent);color:var(--accent-text)}
  .secondary{border:1px solid var(--line);border-radius:12px;padding:12px 18px;font-weight:700;
    cursor:pointer;background:#2a352f;color:var(--text)}
  .danger{border:1px solid rgba(255,120,111,.4);border-radius:12px;padding:12px 18px;font-weight:700;
    cursor:pointer;background:rgba(255,120,111,.12);color:var(--red)}
  button:disabled{opacity:.5;cursor:progress}
  .actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}
  .net{width:100%;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;text-align:left;
    padding:14px 16px;margin-bottom:8px;border:1px solid var(--line);border-radius:12px;background:#101713;
    color:var(--text);cursor:pointer}
  .net:hover{border-color:#52685b}
  .net.unsupported{opacity:.55;cursor:not-allowed}
  .net strong{display:block;font-size:1rem;word-break:break-word}
  .net small{color:var(--muted)}
  .bars{display:flex;gap:2px;align-items:flex-end;height:16px}
  .bars i{width:4px;background:#3d4a43;border-radius:1px}
  .bars i.on{background:var(--green)}
  label{display:block;font-weight:700;margin:14px 0 6px}
  input[type=text],input[type=password],select{width:100%;padding:13px 14px;border-radius:12px;
    border:1px solid var(--line);background:#0f1612;color:var(--text);font:inherit}
  .row{display:flex;gap:10px;align-items:center;margin-top:10px;color:var(--muted);font-size:.92rem}
  .note{margin-top:14px;padding:13px 15px;border-radius:12px;background:#0f1612;border:1px solid var(--line);
    color:var(--muted)}
  .note.good{border-color:rgba(88,214,141,.4);color:var(--green)}
  .note.bad{border-color:rgba(255,120,111,.4);color:var(--red)}
  .note.busy{border-color:rgba(247,200,93,.4);color:var(--amber)}
  .err{margin-top:14px;padding:15px 17px;border-radius:12px;border:1px solid rgba(255,120,111,.4);
    background:rgba(255,120,111,.07)}
  .err h3{margin:0 0 8px;font-size:1rem;color:var(--red)}
  .err dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:5px 12px;font-size:.92rem}
  .err dt{color:var(--muted);white-space:nowrap}
  .err dd{margin:0}
  .code{margin-top:6px;color:var(--muted);font-size:.8rem;letter-spacing:.06em}
  .pairing{font-size:clamp(2.4rem,11vw,3.6rem);font-weight:800;letter-spacing:.16em;text-align:center;
    margin:10px 0 4px;font-variant-numeric:tabular-nums}
  .checks{margin-top:8px}
  .check{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding:11px 0;
    border-bottom:1px solid var(--line)}
  .check:last-child{border-bottom:0}
  .tag{font-size:.7rem;font-weight:800;letter-spacing:.06em;padding:4px 9px;border-radius:99px;
    background:#29342e;color:var(--muted)}
  .tag.pass{background:rgba(88,214,141,.14);color:var(--green)}
  .tag.fail{background:rgba(255,120,111,.13);color:var(--red)}
  .tag.warn{background:rgba(247,200,93,.14);color:var(--amber)}
  .check small{display:block;color:var(--muted)}
  .steps{display:flex;gap:8px;margin:0 0 6px;padding:0;list-style:none;flex-wrap:wrap}
  .steps li{font-size:.74rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
    color:var(--muted);padding:4px 10px;border-radius:99px;border:1px solid var(--line)}
  .steps li.now{color:var(--accent-text);background:var(--accent);border-color:var(--accent)}
  .steps li.done{color:var(--green);border-color:rgba(88,214,141,.4)}
  .advanced{margin-top:18px}
  .advanced summary{cursor:pointer;color:var(--muted);font-weight:700}
  .advanced .body{margin-top:12px;font-size:.9rem;color:var(--muted)}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:.88rem}
  .kv dt{color:var(--muted)}
  .kv dd{margin:0;word-break:break-all}
  .hidden{display:none}
  @media(max-width:520px){main{margin:20px auto 48px}.panel{padding:17px}}
</style>
</head>
<body>
<main>
  <div class="eyebrow">PiTrac</div>
  <h1 id="deviceName">PiTrac setup</h1>
  <p class="lede" id="deviceSub">Getting ready…</p>

  <section class="panel">
    <div class="state">
      <div class="dot" id="stateDot"></div>
      <div>
        <h2 id="stateHead">Starting up</h2>
        <p class="hint" id="stateDetail" style="margin:4px 0 0">Checking hardware and services.</p>
      </div>
    </div>
    <div id="stateError"></div>
  </section>

  <section class="panel" id="stepPanel">
    <div id="actionError"></div>
    <ul class="steps" id="steps">
      <li data-step="country">Country</li>
      <li data-step="network">Network</li>
      <li data-step="pair">Pair your PC</li>
      <li data-step="play">Play</li>
    </ul>

    <!-- Country -->
    <div id="viewCountry" class="hidden">
      <h2>Which country is PiTrac in?</h2>
      <p class="hint">Wi-Fi rules differ by country. PiTrac needs this once before it can use Wi-Fi.</p>
      <label for="country">Country</label>
      <select id="country"></select>
      <div class="actions"><button class="primary" id="saveCountry">Save and continue</button></div>
    </div>

    <!-- Network list -->
    <div id="viewNetworks" class="hidden">
      <h2>Choose your Wi-Fi network</h2>
      <p class="hint">Pick the network this computer normally uses.</p>
      <div id="netList"></div>
      <div class="actions">
        <button class="secondary" id="rescan">Search again</button>
        <button class="secondary" id="showHidden">Type a network name</button>
        <button class="secondary" id="showDirect">Play without a router</button>
      </div>
    </div>

    <!-- Password -->
    <div id="viewPassword" class="hidden">
      <h2 id="pwTitle">Wi-Fi password</h2>
      <p class="hint" id="pwHint">Enter the password for this network.</p>
      <div id="hiddenName" class="hidden">
        <label for="ssid">Network name</label>
        <input type="text" id="ssid" autocapitalize="none" autocorrect="off" spellcheck="false">
      </div>
      <label for="password">Password</label>
      <input type="password" id="password" autocapitalize="none" autocorrect="off" spellcheck="false">
      <div class="row"><input type="checkbox" id="showPw" style="width:auto"><label for="showPw"
        style="margin:0;font-weight:400">Show password</label></div>
      <div class="actions">
        <button class="primary" id="join">Connect</button>
        <button class="secondary" id="backToList">Back</button>
      </div>
    </div>

    <!-- Direct mode -->
    <div id="viewDirect" class="hidden">
      <h2>Play without a router</h2>
      <p class="hint">Your computer connects straight to PiTrac's own signal. Useful where there
        is no Wi-Fi you can join.</p>
      <div class="note busy">While Direct Mode is on, this computer's Wi-Fi internet connection is
        usually unavailable. Your simulator may still need the internet to sign in, download
        courses, or play online — that part is up to the simulator, not PiTrac.</div>
      <div class="actions">
        <button class="primary" id="enableDirect">Turn on Direct Mode</button>
        <button class="secondary" id="backFromDirect">Back</button>
      </div>
    </div>

    <!-- Waiting for confirmation -->
    <div id="viewConfirm" class="hidden">
      <h2>Now reconnect this computer</h2>
      <p class="hint" id="confirmHint">PiTrac has joined your network.</p>
      <ol style="color:var(--muted);padding-left:20px">
        <li>Reconnect this computer to your normal Wi-Fi network.</li>
        <li>Open PiTrac Easy Connect on your Windows PC.</li>
        <li>It will find PiTrac and finish the setup.</li>
      </ol>
      <div class="note busy" id="confirmTimer">Waiting…</div>
      <p class="hint" style="margin-top:12px">If nothing connects in time, PiTrac puts its setup
        signal back automatically so you are never locked out.</p>
    </div>

    <!-- Pairing -->
    <div id="viewPair" class="hidden">
      <h2>Pair your Windows PC</h2>
      <p class="hint">Open PiTrac Easy Connect on your PC and type this code.</p>
      <div class="pairing" id="pairCode">------</div>
      <p class="hint" style="text-align:center" id="pairTimer"></p>
      <div class="actions"><button class="secondary" id="newCode">New code</button></div>
    </div>

    <!-- Ready -->
    <div id="viewReady" class="hidden">
      <h2>PiTrac is set up</h2>
      <p class="hint">Everything is managed from Easy Connect on your PC from here on.</p>
      <div class="note good" id="readyNote">Ready.</div>
    </div>
  </section>

  <section class="panel">
    <h2>Enclosure checks</h2>
    <p class="hint">What PiTrac can confirm about itself right now.</p>
    <div class="checks" id="checks"></div>
  </section>

  <section class="panel">
    <h2>Maintenance</h2>
    <p class="hint">Everything here explains what it keeps and what it removes.</p>
    <div class="actions">
      <button class="secondary" id="printCard">Show owner card</button>
      <button class="secondary" id="restartPitrac">Restart PiTrac</button>
      <button class="danger" id="resetNetwork">Forget Wi-Fi networks</button>
      <button class="danger" id="shutdown">Shut down safely</button>
    </div>
    <div id="maintNote"></div>

    <details class="advanced">
      <summary>Advanced details</summary>
      <div class="body">
        <dl class="kv" id="advanced"></dl>
      </div>
    </details>
  </section>
</main>

<script>
"use strict";
const COUNTRIES=[["US","United States"],["CA","Canada"],["GB","United Kingdom"],["IE","Ireland"],
 ["AU","Australia"],["NZ","New Zealand"],["DE","Germany"],["FR","France"],["ES","Spain"],["IT","Italy"],
 ["NL","Netherlands"],["BE","Belgium"],["SE","Sweden"],["NO","Norway"],["DK","Denmark"],["FI","Finland"],
 ["PL","Poland"],["PT","Portugal"],["AT","Austria"],["CH","Switzerland"],["CZ","Czechia"],["JP","Japan"],
 ["KR","South Korea"],["SG","Singapore"],["ZA","South Africa"],["MX","Mexico"],["BR","Brazil"]];

const $=id=>document.getElementById(id);
let status=null, chosen=null, busy=false;
// The page polls every few seconds. Without this, a refresh landing while
// someone is halfway through typing a Wi-Fi password would throw them back to
// the network list and discard what they had entered.
let manualView=null;

async function api(path, body){
  const options={method: body?"POST":"GET", headers:{"X-PiTrac-Portal":"1"}};
  if(body){options.headers["Content-Type"]="application/json";options.body=JSON.stringify(body);}
  const response=await fetch(path, options);
  const data=await response.json().catch(()=>({}));
  if(!response.ok){const e=new Error((data.error&&data.error.failed)||"That did not work");e.info=data.error;throw e;}
  return data;
}

function showError(target, error){
  if(!error){target.innerHTML="";return;}
  const info=error.info||{};
  target.innerHTML=`<div class="err"><h3>${esc(info.failed||error.message)}</h3><dl>
    ${info.stillSafe?`<dt>Still safe</dt><dd>${esc(info.stillSafe)}</dd>`:""}
    ${info.nextStep?`<dt>What to do</dt><dd>${esc(info.nextStep)}</dd>`:""}
    </dl>${info.code?`<div class="code">Reference ${esc(info.code)}</div>`:""}</div>`;
}
function esc(value){const d=document.createElement("div");d.textContent=value==null?"":String(value);return d.innerHTML;}

function view(name){
  ["Country","Networks","Password","Direct","Confirm","Pair","Ready"].forEach(v=>
    $("view"+v).classList.toggle("hidden", v.toLowerCase()!==name));
}
function step(current){
  const order=["country","network","pair","play"];
  const at=order.indexOf(current);
  document.querySelectorAll("#steps li").forEach(li=>{
    const i=order.indexOf(li.dataset.step);
    li.className = i<at ? "done" : (i===at ? "now" : "");
  });
}

async function run(button, work){
  if(busy) return; busy=true;
  const label=button?button.textContent:null;
  if(button){button.disabled=true;button.textContent="Working…";}
  showError($("actionError"), null);
  try{ await work(); }
  catch(error){ showError($("actionError"), error); }
  finally{ busy=false; if(button){button.disabled=false;button.textContent=label;} }
}

// --- rendering ----------------------------------------------------------

function render(data){
  status=data;
  $("deviceName").textContent=data.device.displayName;
  $("deviceSub").textContent="Device "+data.device.deviceId+" · Easy Connect "+data.version;
  $("stateHead").textContent=data.headline;
  $("stateDetail").textContent=data.detail;
  const dot=$("stateDot");
  dot.className="dot "+(data.ready?"good":(data.state==="CONNECTING"||data.state==="STARTING"?"busy":
    (data.state==="SETUP REQUIRED"?"":"bad")));

  // While the enclosure is still being set up, the numbered steps below are the
  // instructions. Repeating "no computer is connected" as a red failure above
  // them describes a step the user simply has not reached yet.
  const problem=data.selfTest&&data.selfTest.firstProblem;
  const settingUp=data.state==="SETUP REQUIRED"||data.state==="STARTING";
  showError($("stateError"), (problem&&problem.error&&!data.ready&&!settingUp)?
    {message:problem.error.failed,info:problem.error}:null);

  renderChecks(data.selfTest);
  renderAdvanced(data);

  if(busy||manualView) return;
  const net=data.network||{};
  if(!net.country){ step("country"); view("country"); return; }
  if(net.awaitingConfirmation){
    step("network"); view("confirm");
    $("confirmHint").textContent="PiTrac has joined "+(net.connection&&net.connection.ssid||"your network")+".";
    $("confirmTimer").textContent="Waiting for your computer — "+net.secondsLeftToConfirm+" seconds left.";
    return;
  }
  const onHotspot=net.connection&&net.connection.isHotspot;
  if(onHotspot&&!net.directMode){ step("network"); view("networks"); loadNetworks(); return; }
  if(data.trustedComputerCount===0||!data.pairedComputer){ step("pair"); view("pair"); loadCode(); return; }
  step("play"); view("ready");
  $("readyNote").textContent=data.ready?"Ready to play.":data.detail;
}

function renderChecks(report){
  const host=$("checks");
  if(!report){host.innerHTML='<p class="hint">Running checks…</p>';return;}
  host.innerHTML=report.checks.map(check=>`<div class="check">
      <span class="tag ${check.status==="pass"?"pass":check.status==="fail"?"fail":check.status==="warn"?"warn":""}">${
        check.status==="pass"?"OK":check.status==="fail"?"PROBLEM":check.status==="warn"?"NOTE":"NOT CHECKED"}</span>
      <div><strong>${esc(check.title)}</strong><small>${esc(check.detail)}</small></div>
      <span class="code">${check.error?esc(check.error.code):""}</span>
    </div>`).join("");
}

function renderAdvanced(data){
  const rows=[["State",data.state],["Device ID",data.device.deviceId],
    ["Hostname",data.device.hostname+".local"],["Network mode",data.network.mode],
    ["Address",(data.network.connection&&data.network.connection.address)||"none"],
    ["Setup signal",data.device.setupSsid],["Simulator",data.simulatorLabel],
    ["Relay ports",JSON.stringify(data.relay.ports)],
    ["PiTrac pointed at relay",data.pitrac.relayConfigured?"yes":"no"],
    ["Shots forwarded",data.relay.shotsForwarded],["Shots not delivered",data.relay.shotsFailed],
    ["Trusted computers",data.trustedComputerCount],
    ["Model",data.system.model],["Temperature",data.system.temperatureC+" C"],
    ["Free space",(data.system.freeBytes/1073741824).toFixed(1)+" GB"]];
  $("advanced").innerHTML=rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

// --- networks -----------------------------------------------------------

async function loadNetworks(force){
  const host=$("netList");
  if(host.dataset.loaded&&!force) return;
  host.dataset.loaded="1";
  host.innerHTML='<p class="hint">Looking for networks…</p>';
  try{
    const data=await api("/api/networks");
    host.innerHTML = data.networks.length ? data.networks.map(n=>`
      <button class="net ${n.supported?"":"unsupported"}" data-ssid="${esc(n.ssid)}"
        data-password="${n.needsPassword?"1":""}" ${n.supported?"":"disabled"}>
        <span><strong>${esc(n.ssid)}</strong>
          <small>${n.band}${n.supported?(n.needsPassword?" · password needed":" · open network"):
            " · not supported by PiTrac"}</small></span>
        <span class="bars">${[1,2,3,4].map(b=>`<i class="${b<=n.bars?"on":""}" style="height:${b*4}px"></i>`).join("")}</span>
      </button>`).join("") : '<p class="hint">No networks found. Move PiTrac closer to your router and search again.</p>';
    host.querySelectorAll(".net").forEach(button=>button.addEventListener("click",()=>{
      chosen={ssid:button.dataset.ssid, needsPassword:!!button.dataset.password, hidden:false};
      openPassword();
    }));
  }catch(error){ showError($("stateError"), error); host.innerHTML=""; }
}

function openPassword(){
  manualView="password";
  view("password");
  $("hiddenName").classList.toggle("hidden", !chosen.hidden);
  $("pwTitle").textContent=chosen.hidden?"Type your network details":"Password for "+chosen.ssid;
  $("pwHint").textContent=chosen.needsPassword?"Enter the password for this network.":
    "This network has no password.";
  $("password").value=""; $("ssid").value="";
  $("password").parentElement.querySelector("label[for=password]").classList.toggle("hidden",!chosen.needsPassword);
  $("password").classList.toggle("hidden", !chosen.needsPassword);
  (chosen.hidden?$("ssid"):$("password")).focus();
}

// --- pairing ------------------------------------------------------------

async function loadCode(){
  try{
    const data=await api("/api/pairing-code");
    $("pairCode").textContent=data.code.replace(/(\d{3})(\d{3})/,"$1 $2");
    $("pairTimer").textContent="This code works for "+Math.round(data.secondsLeft/60*10)/10+" more minutes.";
  }catch(error){ showError($("actionError"), error); }
}

// --- events -------------------------------------------------------------

COUNTRIES.forEach(([code,name])=>{
  const option=document.createElement("option"); option.value=code; option.textContent=name+" ("+code+")";
  $("country").appendChild(option);
});

$("saveCountry").addEventListener("click",e=>run(e.target,async()=>{
  await api("/api/country",{country:$("country").value}); await refresh();
}));
$("rescan").addEventListener("click",e=>run(e.target,()=>loadNetworks(true)));
$("showHidden").addEventListener("click",()=>{chosen={ssid:"",needsPassword:true,hidden:true};openPassword();});
$("showDirect").addEventListener("click",()=>{manualView="direct";view("direct");});
$("backFromDirect").addEventListener("click",()=>{manualView=null;view("networks");refresh();});
$("backToList").addEventListener("click",()=>{manualView=null;view("networks");refresh();});
$("showPw").addEventListener("change",e=>{$("password").type=e.target.checked?"text":"password";});

$("join").addEventListener("click",e=>run(e.target,async()=>{
  const ssid=chosen.hidden?$("ssid").value.trim():chosen.ssid;
  if(!ssid){throw new Error("Type the name of your network");}
  const result=await api("/api/join",{ssid,password:$("password").value,hidden:chosen.hidden});
  manualView=null;
  if(!result.ok){
    // A failed attempt is the user's own action failing. It always gets said
    // out loud, whatever state the enclosure is in.
    showError($("actionError"),{message:result.message,info:result.error});
    $("netList").dataset.loaded="";
  }
  await refresh();
}));

$("enableDirect").addEventListener("click",e=>run(e.target,async()=>{
  await api("/api/direct-mode",{enabled:true}); manualView=null; await refresh();
}));
$("newCode").addEventListener("click",e=>run(e.target,async()=>{
  await api("/api/pairing-code",{refresh:true}); await loadCode();
}));

$("printCard").addEventListener("click",e=>run(e.target,async()=>{
  const data=await api("/api/owner-card");
  $("maintNote").innerHTML='<div class="note"><pre style="margin:0;white-space:pre-wrap;font:inherit">'+
    esc(data.text)+"</pre></div>";
}));
$("restartPitrac").addEventListener("click",e=>run(e.target,async()=>{
  await api("/api/restart-pitrac",{});
  $("maintNote").innerHTML='<div class="note good">PiTrac was restarted.</div>';
  await refresh();
}));
$("resetNetwork").addEventListener("click",e=>run(e.target,async()=>{
  if(!confirm("Forget all saved Wi-Fi networks?\n\nKEPT: camera calibration, paired computers, simulator settings.\nREMOVED: saved Wi-Fi networks only.\n\nPiTrac will restart its setup signal.")) return;
  await api("/api/reset-network",{});
  $("maintNote").innerHTML='<div class="note good">Wi-Fi networks were removed. Calibration and paired computers were kept.</div>';
  await refresh();
}));
$("shutdown").addEventListener("click",e=>run(e.target,async()=>{
  if(!confirm("Shut PiTrac down safely?\n\nSettings are saved first. Wait for the green light on the Raspberry Pi to stop blinking before unplugging it.")) return;
  await api("/api/shutdown",{});
  $("maintNote").innerHTML='<div class="note busy">Shutting down. Wait until the green light on the Raspberry Pi stops blinking, then it is safe to unplug.</div>';
}));

async function refresh(){
  try{ render(await api("/api/status")); }
  catch(error){ $("stateHead").textContent="Cannot reach PiTrac"; $("stateDot").className="dot bad";
    $("stateDetail").textContent="This page lost contact with the enclosure. It may be restarting."; }
}
refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""
