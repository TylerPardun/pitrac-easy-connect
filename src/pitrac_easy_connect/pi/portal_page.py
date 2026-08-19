"""The enclosure's setup page.

Four short steps to get on Wi-Fi and pair a computer, then it says it is done
and stops asking for attention. Everything that is not part of getting set up —
the self-test, maintenance, backup, resets — lives behind Advanced.

Shot data is not here. PiTrac's own dashboard already does that; this links to
it.
"""

STYLE = r"""
  :root{color-scheme:dark;
    --bg:#0b0f0d;--panel:#141b17;--line:#26312b;--line-soft:#1c2420;
    --text:#f2f6f3;--muted:#93a49b;--faint:#68786f;
    --green:#5ddc93;--amber:#f5c65c;--red:#ff7d73;
    --accent:#dff86d;--accent-text:#151d06}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
    line-height:1.5;display:flex;align-items:center;justify-content:center}
  main{width:min(460px,calc(100% - 40px));padding:40px 0}
  .brand{font-size:.68rem;font-weight:800;letter-spacing:.22em;color:var(--faint);
    text-transform:uppercase;text-align:center;margin-bottom:26px}
  .steps{display:flex;gap:6px;margin-bottom:26px}
  .steps i{flex:1;height:3px;border-radius:2px;background:var(--line);display:block}
  .steps i.done{background:rgba(93,220,147,.5)}
  .steps i.now{background:var(--accent)}
  h1{margin:0;font-size:1.6rem;font-weight:650;letter-spacing:-.02em;line-height:1.2}
  .sub{color:var(--muted);font-size:.95rem;margin-top:6px}
  .why{color:var(--faint);font-size:.88rem;margin-top:10px;line-height:1.45}
  .status{display:flex;gap:16px;align-items:flex-start}
  .dot{width:11px;height:11px;border-radius:50%;flex:none;margin-top:9px;background:var(--faint);
    box-shadow:0 0 0 4px rgba(255,255,255,.03)}
  .dot.good{background:var(--green);box-shadow:0 0 0 4px rgba(93,220,147,.12)}
  .dot.busy{background:var(--amber);box-shadow:0 0 0 4px rgba(245,198,92,.12);
    animation:pulse 1.8s ease-in-out infinite}
  .dot.bad{background:var(--red);box-shadow:0 0 0 4px rgba(255,125,115,.12)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
  @media (prefers-reduced-motion:reduce){.dot.busy{animation:none}}
  button,.linkbtn{font:inherit;width:100%;text-align:center;border-radius:11px;padding:14px 18px;
    font-weight:700;cursor:pointer;border:1px solid transparent;text-decoration:none;display:block}
  .primary{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}
  .primary:hover{filter:brightness(1.06)}
  .quiet{background:transparent;color:var(--text);border-color:var(--line)}
  .quiet:hover{border-color:#3b4a42}
  button:disabled{opacity:.45;cursor:progress}
  button:focus-visible,a:focus-visible,summary:focus-visible,input:focus-visible,
  select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .do{margin-top:24px;display:flex;flex-direction:column;gap:10px}
  .list{margin-top:20px;display:flex;flex-direction:column;gap:8px}
  .net{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 16px;
    border:1px solid var(--line);border-radius:11px;background:var(--panel);color:var(--text);
    cursor:pointer;text-align:left;width:100%}
  .net:hover{border-color:#3b4a42}
  .net[disabled]{opacity:.4;cursor:not-allowed}
  .net small{display:block;color:var(--faint);margin-top:3px;font-size:.8rem}
  .bars{display:flex;gap:2px;align-items:flex-end;height:15px;flex:none}
  .bars i{width:3px;border-radius:1px;background:#33403a}
  .bars i.on{background:var(--green)}
  label.field{display:block;color:var(--muted);font-size:.88rem;margin:20px 0 9px}
  input[type=text],input[type=password],select{width:100%;padding:14px 16px;border-radius:11px;
    border:1px solid var(--line);background:var(--panel);color:var(--text);font:inherit}
  .reveal{display:flex;gap:9px;align-items:center;margin-top:11px;color:var(--muted);font-size:.86rem}
  .reveal input{width:auto}
  .code{font-size:2.6rem;font-weight:800;letter-spacing:.22em;text-align:center;margin:18px 0 4px;
    font-variant-numeric:tabular-nums}
  .err{margin-top:20px;padding:14px 16px;border-radius:11px;border:1px solid rgba(255,125,115,.35);
    background:rgba(255,125,115,.06)}
  .err h2{margin:0 0 6px;font-size:.95rem;font-weight:650;color:var(--red)}
  .err p{margin:0;color:var(--muted);font-size:.88rem}
  .err .ref{margin-top:8px;color:var(--faint);font-size:.74rem;letter-spacing:.07em;
    font-family:ui-monospace,Menlo,Consolas,monospace}
  details.adv{margin-top:34px;border-top:1px solid var(--line-soft);padding-top:16px}
  details.adv > summary{list-style:none;cursor:pointer;color:var(--faint);font-size:.82rem;
    font-weight:600;display:flex;align-items:center;gap:7px}
  details.adv > summary::-webkit-details-marker{display:none}
  details.adv > summary::before{content:"";width:5px;height:5px;border-right:1.5px solid currentColor;
    border-bottom:1.5px solid currentColor;transform:rotate(-45deg);transition:transform .15s}
  details.adv[open] > summary::before{transform:rotate(45deg)}
  details.adv > summary:hover{color:var(--muted)}
  .advbody{margin-top:18px;display:flex;flex-direction:column;gap:9px}
  .advbody h3{margin:10px 0 2px;font-size:.72rem;font-weight:800;letter-spacing:.13em;
    text-transform:uppercase;color:var(--faint)}
  .advbody button,.advbody .linkbtn{padding:11px 14px;font-size:.9rem;font-weight:600}
  .danger{border-color:rgba(255,125,115,.3);color:var(--red)}
  .danger:hover{border-color:rgba(255,125,115,.55)}
  .checks{display:flex;flex-direction:column;gap:1px;margin-top:4px}
  .check{display:flex;justify-content:space-between;gap:12px;padding:8px 0;font-size:.85rem;
    border-bottom:1px solid var(--line-soft)}
  .check span:first-child{color:var(--muted)}
  .check .ok{color:var(--green)}.check .no{color:var(--red)}.check .warn{color:var(--amber)}
  .check .na{color:var(--faint)}
  .note{padding:12px 14px;border-radius:10px;background:var(--panel);border:1px solid var(--line);
    color:var(--muted);font-size:.85rem}
  .note.good{border-color:rgba(93,220,147,.35);color:var(--green)}
  .note pre{margin:0;white-space:pre-wrap;font:inherit;font-size:.82rem}
  .hidden{display:none}
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PiTrac setup</title>
<style>__STYLE__</style>
</head>
<body>
<main>
  <div class="brand" id="brand">PiTrac</div>
  <div class="steps" id="steps"><i></i><i></i><i></i></div>

  <div class="status">
    <div class="dot" id="dot"></div>
    <div style="flex:1">
      <h1 id="head">Starting</h1>
      <div class="sub" id="sub"></div>
      <div class="why" id="why"></div>
    </div>
  </div>

  <div id="err"></div>
  <div id="body"></div>
  <div class="do" id="do"></div>

  <details class="adv" id="adv">
    <summary>Advanced</summary>
    <div class="advbody">
      <h3>Enclosure</h3>
      <div class="checks" id="checks"></div>

      <h3>Network</h3>
      <button class="quiet" id="changeNetwork">Change Wi-Fi network</button>
      <button class="quiet" id="directMode">Play without a router</button>

      <h3>Maintenance</h3>
      <button class="quiet" id="ownerCard">Show owner card</button>
      <button class="quiet" id="restart">Restart PiTrac</button>
      <button class="quiet danger" id="resetNetwork">Forget Wi-Fi networks</button>
      <button class="quiet danger" id="shutdown">Shut down safely</button>

      <h3>Backup</h3>
      <button class="quiet" id="makeBackup">Save a backup</button>
      <label class="linkbtn quiet" for="bkFile" style="cursor:pointer">Restore from a file</label>
      <input type="file" id="bkFile" accept=".pitracbackup,.json,application/json" class="hidden">
      <div id="bkPreview"></div>

      <div id="note"></div>
    </div>
  </details>
</main>

<script>
"use strict";
const COUNTRIES=[["US","United States"],["CA","Canada"],["GB","United Kingdom"],["IE","Ireland"],
 ["AU","Australia"],["NZ","New Zealand"],["DE","Germany"],["FR","France"],["ES","Spain"],
 ["IT","Italy"],["NL","Netherlands"],["BE","Belgium"],["SE","Sweden"],["NO","Norway"],
 ["DK","Denmark"],["FI","Finland"],["PL","Poland"],["PT","Portugal"],["AT","Austria"],
 ["CH","Switzerland"],["CZ","Czechia"],["JP","Japan"],["KR","South Korea"],["SG","Singapore"],
 ["ZA","South Africa"],["MX","Mexico"],["BR","Brazil"]];

const $=id=>document.getElementById(id);
let status=null, busy=false, view=null, chosen=null, downloads=[];

async function api(path, body){
  const options={method: body?"POST":"GET", headers:{"X-PiTrac-Portal":"1"}};
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
    ${info.code?`<div class="ref">${esc(info.code)}</div>`:""}</div>`;
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

// --- which of the three steps we are on ----------------------------------

function decide(data){
  const net=data.network||{};
  if(view==="password") return {step:1, ...passwordView()};
  if(view==="networks") return {step:1, ...networkView()};

  if(!net.country) return {step:0, dot:"", head:"Where are you?",
    sub:"Wi-Fi rules differ by country. PiTrac asks once.",
    why:"", body:countryPicker(), actions:[{label:"Continue", id:"country", primary:true}]};

  if(net.awaitingConfirmation) return {step:1, dot:"busy",
    head:"Reconnect your computer", sub:"PiTrac has joined "+esc(net.connection&&net.connection.ssid||"your network"),
    why:"Its setup signal has gone, so this page will stop responding. Reconnect this computer "+
      "to your normal Wi-Fi, then open Easy Connect. "+net.secondsLeftToConfirm+" seconds left.",
    body:"", actions:[]};

  const onHotspot=net.connection&&net.connection.isHotspot;
  if(onHotspot && !net.directMode) return {step:1, ...networkView()};

  if(!data.pairedComputer && !data.setupComplete) return {step:2, dot:"busy",
    head:"Pair your computer", sub:"",
    why:"Open Easy Connect on your computer and enter this code."+
      (downloads.length?" Do not have it yet? Get it below.":""),
    body:pairingBody(), actions:downloads.length
      ? [{label:"Get Easy Connect for this computer", id:"downloads", primary:false}] : []};

  return {step:3, dot:"good", head:"PiTrac is set up",
    sub:(net.connection&&net.connection.ssid ? "On "+esc(net.connection.ssid) : "")+
        (data.pairedComputer ? " · "+esc(data.pairedComputer.computerName)+" is paired" : ""),
    why:"You can close this page. Play from Easy Connect on your computer.",
    body:"", actions:[{label:"View shot data", id:"dash", primary:false}]};
}

function countryPicker(){
  return `<label class="field" for="country">Country</label>
    <select id="country">${COUNTRIES.map(([c,n])=>
      `<option value="${c}">${esc(n)}</option>`).join("")}</select>`;
}

function networkView(){
  return {dot:"", head:"Choose your Wi-Fi", sub:"Pick the network your computer uses.",
    why:"", body:'<div class="list" id="netList"><div class="why">Looking…</div></div>',
    actions:[{label:"Search again", id:"scan", primary:false},
             {label:"Type a network name", id:"hidden", primary:false}],
    after:loadNetworks};
}

function passwordView(){
  return {dot:"", head:chosen.hidden?"Type your network":"Password for "+esc(chosen.ssid),
    sub:"", why:"",
    body:(chosen.hidden?'<label class="field" for="ssid">Network name</label>'+
            '<input type="text" id="ssid" autocapitalize="none" autocorrect="off" spellcheck="false">':"")+
      (chosen.needsPassword?'<label class="field" for="password">Password</label>'+
        '<input type="password" id="password" autocapitalize="none" autocorrect="off" spellcheck="false">'+
        '<div class="reveal"><input type="checkbox" id="showPw">'+
        '<label for="showPw">Show password</label></div>':""),
    actions:[{label:"Connect", id:"join", primary:true},{label:"Back", id:"back", primary:false}],
    after:()=>{
      const first=$("ssid")||$("password"); if(first) first.focus();
      const box=$("showPw");
      if(box) box.addEventListener("change",e=>{$("password").type=e.target.checked?"text":"password";});
      const password=$("password");
      if(password) password.addEventListener("keydown",e=>{if(e.key==="Enter") act("join");});
    }};
}

function pairingBody(){
  const code=(status&&status.pairingCode)||"------";
  return `<div class="code">${esc(code.replace(/(\d{3})(\d{3})/,"$1 $2"))}</div>`;
}

// --- rendering ------------------------------------------------------------

function render(data){
  status=data;
  const decided=decide(data);
  $("brand").textContent=data.device?data.device.displayName:"PiTrac";
  $("dot").className="dot "+(decided.dot||"");
  $("head").textContent=decided.head;
  $("sub").innerHTML=decided.sub||"";
  $("why").innerHTML=decided.why||"";
  $("body").innerHTML=decided.body||"";

  const marks=$("steps").querySelectorAll("i");
  marks.forEach((mark,index)=>{
    mark.className = index<decided.step ? "done" : (index===decided.step ? "now" : "");
  });
  $("steps").classList.toggle("hidden", decided.step>=3);

  $("do").innerHTML="";
  (decided.actions||[]).forEach(action=>{
    const button=document.createElement("button");
    button.className=action.primary?"primary":"quiet";
    button.textContent=action.label;
    button.addEventListener("click",()=>act(action.id,button));
    $("do").appendChild(button);
  });
  if(decided.after) decided.after();
  renderChecks(data.selfTest);
}

function act(id, button){
  if(id==="country") return run(button, async()=>{
    await api("/api/country",{country:$("country").value});});
  if(id==="scan"){ $("netList").dataset.loaded=""; return run(button, loadNetworks); }
  if(id==="hidden"){ chosen={ssid:"",needsPassword:true,hidden:true}; view="password"; return render(status); }
  if(id==="back"){ view="networks"; chosen=null; return render(status); }
  if(id==="join") return run(button, async()=>{
    const ssid=chosen.hidden?$("ssid").value.trim():chosen.ssid;
    if(!ssid) throw new Error("Type the name of your network");
    const result=await api("/api/join",
      {ssid, password:($("password")||{}).value||"", hidden:chosen.hidden});
    view=null; chosen=null;
    if(!result.ok) showError({message:result.message, info:result.error});
  });
  if(id==="dash" && status.dashboardUrl) window.open(status.dashboardUrl,"_blank","noopener");
  if(id==="downloads") window.open("/companion","_blank","noopener");
}

async function loadNetworks(){
  const host=$("netList");
  if(!host || host.dataset.loaded) return;
  host.dataset.loaded="1";
  try{
    const data=await api("/api/networks");
    host.innerHTML = data.networks.length ? data.networks.map(n=>`
      <button class="net" data-ssid="${esc(n.ssid)}" data-pw="${n.needsPassword?"1":""}"
        ${n.supported?"":"disabled"}>
        <span><strong>${esc(n.ssid)}</strong><small>${n.supported?
          (n.needsPassword?"Password needed":"Open network"):"Not supported"}</small></span>
        <span class="bars">${[1,2,3,4].map(b=>
          `<i class="${b<=n.bars?"on":""}" style="height:${b*3.5}px"></i>`).join("")}</span>
      </button>`).join("") :
      '<div class="why">No networks found. Move PiTrac closer to your router.</div>';
    host.querySelectorAll(".net").forEach(button=>button.addEventListener("click",()=>{
      chosen={ssid:button.dataset.ssid, needsPassword:!!button.dataset.pw, hidden:false};
      view="password"; render(status);
    }));
  }catch(error){ showError(error); host.innerHTML=""; }
}

function renderChecks(report){
  if(!report){ $("checks").innerHTML=""; return; }
  const word={pass:["OK","ok"],fail:["Problem","no"],warn:["Note","warn"],unavailable:["-","na"]};
  $("checks").innerHTML=report.checks.map(c=>{
    const [label,klass]=word[c.status]||["?","na"];
    return `<div class="check"><span>${esc(c.title)}</span><span class="${klass}">${label}</span></div>`;
  }).join("");
}

// --- advanced -------------------------------------------------------------

$("changeNetwork").addEventListener("click",()=>{ view="networks"; $("adv").open=false; render(status); });
$("directMode").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Play without a router?\n\nYour computer connects straight to PiTrac's own signal. "+
    "Your computer usually loses its internet connection while this is on.")) return;
  await api("/api/direct-mode",{enabled:true});
}));
$("ownerCard").addEventListener("click",e=>run(e.target, async()=>{
  const data=await api("/api/owner-card");
  $("note").innerHTML='<div class="note"><pre>'+esc(data.text)+"</pre></div>";
}));
$("restart").addEventListener("click",e=>run(e.target, async()=>{
  await api("/api/restart-pitrac",{});
  $("note").innerHTML='<div class="note good">PiTrac was restarted.</div>';
}));
$("resetNetwork").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Forget all saved Wi-Fi networks?\n\nKEPT: calibration, paired computers, simulator settings.\nREMOVED: saved Wi-Fi networks only.")) return;
  await api("/api/reset-network",{});
  $("note").innerHTML='<div class="note good">Wi-Fi networks removed. Everything else was kept.</div>';
}));
$("shutdown").addEventListener("click",e=>run(e.target, async()=>{
  if(!confirm("Shut PiTrac down safely?\n\nWait for the green light on the Raspberry Pi to stop blinking before unplugging it.")) return;
  await api("/api/shutdown",{});
  $("note").innerHTML='<div class="note">Shutting down. Wait for the green light to stop blinking.</div>';
}));
$("makeBackup").addEventListener("click",e=>run(e.target, async()=>{
  window.location.href="/api/backup";
  $("note").innerHTML='<div class="note good">Saving. Keep it somewhere other than PiTrac.</div>';
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

async function refresh(){
  try{
    const data=await api("/api/status");
    if(!data.pairedComputer && !data.setupComplete){
      try{ data.pairingCode=(await api("/api/pairing-code")).code; }catch(e){}
      if(!downloads.length){
        try{ downloads=(await api("/api/downloads")).downloads||[]; }catch(e){}
      }
    }
    render(data);
  }catch(error){
    $("dot").className="dot bad";
    $("head").textContent="Cannot reach PiTrac";
    $("sub").textContent="This page lost contact with the enclosure.";
    $("why").textContent="It may be restarting, or it may have joined your Wi-Fi and left this signal.";
  }
}
refresh();
setInterval(()=>{ if(!busy && view!=="password") refresh(); }, 4000);
</script>
</body>
</html>
""".replace("__STYLE__", STYLE)


def downloads_page(downloads, enclosure_name: str, version: str) -> str:
    """The page a computer lands on to fetch Easy Connect from the enclosure."""

    def escape(value):
        return (
            str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
        )

    if downloads:
        items = "".join(
            '<a class="net" href="{url}" download><span><strong>{label}</strong>'
            "<small>{note}</small></span><span class=\"tag\">{size}</span></a>".format(
                url=escape(item["url"]), label=escape(item["label"]),
                note=escape(item["note"]), size=escape(item["sizeText"]),
            )
            for item in downloads
        )
        body = (
            '<h1>Easy Connect</h1>'
            '<div class="sub">Version {version}, the same version this PiTrac is running.</div>'
            '<div class="list">{items}</div>'
            '<div class="why">Windows may say it does not recognise the program. '
            "Choose <strong>More info</strong>, then <strong>Run anyway</strong>.</div>"
        ).format(version=escape(version), items=items)
    else:
        body = (
            "<h1>Nothing stored here</h1>"
            '<div class="sub">This PiTrac is not carrying a copy of Easy Connect.</div>'
            '<div class="why">Ask whoever set it up for the installer.</div>'
        )

    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Easy Connect</title>\n<style>{style}"
        "\n  .tag{{font-size:.72rem;font-weight:700;color:var(--accent);flex:none}}"
        "\n  a.net{{text-decoration:none}}\n</style>\n</head>\n<body>\n<main>\n"
        '<div class="brand">{name}</div>\n{body}\n'
        '<div class="do"><a class="linkbtn quiet" href="/">Back to setup</a></div>\n'
        "</main>\n</body>\n</html>\n"
    ).format(style=STYLE, name=escape(enclosure_name), body=body)
