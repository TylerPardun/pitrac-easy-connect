"""The desktop interface for connection, setup, practice and shot history."""

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
  main{width:min(1080px,calc(100% - 64px));padding:40px 0}
  body.guiding main{width:min(920px,calc(100% - 40px))}
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

  /* A newer version, at the top of the startup page until it is installed. */
  .update{margin:0 0 22px;padding:13px 15px;border-radius:11px;border:1px solid var(--line);
    background:var(--panel);display:flex;gap:12px;align-items:center;justify-content:space-between}
  .update.offer{border-color:var(--accent)}
  .update.offer strong{display:block;color:var(--text);font-size:.95rem;margin-bottom:2px}
  .update span{color:var(--muted);font-size:.87rem}
  .update button{width:auto;padding:8px 14px;font-size:.84rem;flex:none}
  .update-actions{display:flex;gap:8px;flex:none}

  /* An update in progress, said quietly. Nothing to press. */
  .update-pill{margin:0 0 18px;padding:7px 12px;border-radius:20px;border:1px solid var(--line);
    background:var(--panel);display:flex;gap:8px;align-items:center;font-size:.8rem;
    color:var(--muted);width:fit-content}

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
  .askway{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0;
    background:var(--panel)}
  .askway strong{display:block;font-size:.92rem;margin-bottom:2px}
  .askway form{display:flex;gap:8px;margin-top:6px}
  .askway form button{width:auto;flex:none;padding-left:22px;padding-right:22px;margin:0}
  .askway input{flex:1;min-width:0;padding:11px 12px;border-radius:10px;border:1px solid var(--line);
    background:var(--bg);color:var(--text);font:inherit}
  .asknote{color:var(--faint);font-size:.82rem;line-height:1.45;margin:2px 0 8px}
  .device{display:flex;justify-content:space-between;align-items:center;gap:12px;
    padding:14px 16px;border:1px solid var(--line);border-radius:11px;background:var(--panel);
    color:var(--text);cursor:pointer;text-align:left;width:100%}
  .device:hover{border-color:#3b4a42}
  .device small{display:block;color:var(--faint);margin-top:3px;font-size:.8rem}
  .tag{font-size:.68rem;font-weight:800;letter-spacing:.06em;color:var(--faint)}
  .tag.on{color:var(--green)}
  .wifibox{margin-top:20px;display:flex;flex-direction:column;gap:8px}
  .wifibox.hidden{display:none}
  .wifilist{display:flex;flex-direction:column;gap:8px;max-height:300px;overflow:auto}
  .wifibox label{font-size:.8rem;font-weight:650;color:var(--muted);margin-top:6px}
  .wifibox .wififield{width:100%;padding:13px 15px;border-radius:11px;border:1px solid var(--line);
    background:var(--panel);color:var(--text);font:inherit;font-size:1rem;font-weight:500;
    letter-spacing:0;text-align:left;text-transform:none}
  .wifibox .wifishow{display:flex;align-items:center;gap:8px;font-weight:500}
  .device .bars{display:flex;align-items:flex-end;gap:2px;height:14px}
  .device .bars i{width:4px;background:var(--line);border-radius:1px}
  .device .bars i.on{background:var(--green)}
  .wificount{font-size:2rem;font-weight:800;font-variant-numeric:tabular-nums;color:var(--text)}
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
  .row2.three{grid-template-columns:repeat(3,1fr)}
  .danger{border-color:rgba(255,125,115,.3);color:var(--red)}
  .danger:hover{border-color:rgba(255,125,115,.55)}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;font-size:.8rem;color:var(--faint);
    margin-top:6px}
  .kv dd{margin:0;color:var(--muted);word-break:break-all}
  .note{padding:12px 14px;border-radius:10px;background:var(--panel);border:1px solid var(--line);
    color:var(--muted);font-size:.85rem}
  .note.good{border-color:rgba(93,220,147,.35);color:var(--green)}
  .note pre{margin:0;white-space:pre-wrap;font:inherit}
  .masthead{flex:none;display:flex;align-items:center;gap:26px;min-height:58px;padding:0 3.2%;
    background:#101813;border-bottom:1px solid var(--line);color:var(--text)}
  .wordmark{display:flex;align-items:center;gap:10px;color:#f6f9ec;font-weight:800;font-size:1.24rem;
    letter-spacing:-.05em;white-space:nowrap}
  .wordmark i{display:inline-block;width:25px;height:25px;border-radius:50%;background:var(--accent);
    position:relative;overflow:hidden}
  .wordmark i::before{content:"";position:absolute;left:7px;top:4px;width:12px;height:17px;
    background:#213121;clip-path:polygon(0 0,100% 14%,20% 48%,20% 100%,0 100%)}
  .masthead .tabs{padding:0;background:none;border:0;align-self:stretch;align-items:stretch;gap:6px}
  .tabs button{border-radius:0;color:#b3c1b6}
  .masthead .tool{margin-left:auto;width:auto;padding:6px 10px;border-radius:6px;
    background:transparent;color:#bac9bd;border:1px solid var(--line);font:600 15px ui-monospace,monospace}
  body.immersive .masthead{display:none}
  .centre{align-items:flex-start}
  main{padding:24px 0 36px}
  .hero{padding:26px 32px;border:1px solid #415242;border-radius:14px;overflow:hidden;
    background:linear-gradient(90deg,rgba(12,23,16,.96),rgba(12,23,16,.79) 44%,rgba(12,23,16,.05) 83%),
      url('/links-course.jpg') center 55%/cover,#192c1e}
  .hero .status{align-items:center;gap:12px}
  .hero .dot{margin:0}
  .hero h1{font-size:clamp(28px,3.6vw,44px);font-weight:650;line-height:1.08;letter-spacing:-.045em}
  .hero .sub,.hero .why{color:#d3ded4;max-width:56ch}
  .hero .why:empty,.hero .sub:empty,.do:empty{display:none}
  .hero .do{margin-top:20px;max-width:390px;flex-direction:row;flex-wrap:wrap}
  .hero .do button{width:auto;padding:10px 19px;font-size:.92rem}
  .hero .quiet{background:#15221b;border-color:#526156}
  .hero .wiz{max-width:240px;margin-bottom:17px}
  .hero .wizstep{color:#c6d7c8}
  body.guiding .centre{align-items:center}
  body.guiding .hero{padding:clamp(32px,5vw,64px) 5%;min-height:255px;display:flex;
    flex-direction:column;justify-content:center}
  body.guiding .help,body.guiding .wifibox,body.guiding .pick{max-width:680px;margin-inline:auto}
  .board{margin:16px 0 0;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}
  .board button{grid-column:span 2;border-radius:10px;
    background:#17231b;position:relative;padding:18px 33px 18px 16px}
  .board button::after{content:"›";position:absolute;right:14px;top:15px;color:#b5ce9c}
  .board button:nth-child(n+4){grid-column:span 3;background:#111a15}
  .board .d{font-size:.81rem;color:#b1c1b4}
  .advbody{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:18px}
  .advbody section{display:grid;gap:7px}
  .advbody #note,.advbody #knownPis{grid-column:1/-1}
  .shots h1{font-size:2rem;letter-spacing:-.04em;margin:2px 0 20px}
  .shots .clubrow{padding:15px 18px;background:var(--panel);border-radius:12px}
  .shots select{flex:0 1 210px}
  .shots .clubnote{flex:1;min-width:180px}
  dialog{width:min(700px,92vw);max-height:82vh;overflow:auto;padding:22px;
    color:var(--text);background:#111b15;border:1px solid #405347;border-radius:14px}
  dialog::backdrop{background:rgba(3,8,5,.74)}
  .dialoghead{display:flex;align-items:center;justify-content:space-between;gap:16px}
  .dialoghead h2{margin:0;font-size:1.35rem}
  .dialoghead button,dialog .quiet{width:auto;padding:7px 14px}
  dialog .raw{white-space:pre-wrap;overflow-wrap:anywhere}
  .panealert{margin:0 3%;flex:none}
  .panealert .err{margin:8px 0}
  @media(max-width:740px){
    .masthead{gap:8px;padding:0 10px}.tabs button{padding:8px;font-size:.78rem}
    .board{grid-template-columns:1fr 1fr}.board button,.board button:nth-child(n+4),
    .board button:last-child:nth-child(odd){grid-column:auto}
    .advbody{grid-template-columns:1fr}.hero{padding:24px 18px}
  }
  body.starting #pane-play{visibility:hidden}
  .hidden{display:none}
</style>
</head>
<body class="starting">
<header class="masthead">
  <div class="wordmark" aria-label="PiTrac"><i aria-hidden="true"></i>PiTrac</div>
  <nav class="tabs hidden" id="tabs" aria-label="Main navigation">
    <button data-pane="play" class="on" aria-current="page">Home</button>
    <button data-pane="range">Practice range</button>
    <button data-pane="shots">Shot history</button>
    <button data-pane="simulator">Play mode</button>
  </nav>
  <button class="tool" id="openConsole" title="Developer console (Alt+Shift+D)"
    aria-label="Open developer console" aria-haspopup="dialog">›_</button>
</header>
<div class="panealert" id="paneAlert"></div>

<div class="pane on" id="pane-play"><div class="centre">
<main>


  <!-- A newer version, offered first and kept until it is installed: nobody
       should play on outdated code without knowing. PiTrac follows by itself
       once this computer is updated. See renderUpdate(). -->
  <div id="update"></div>
  <div class="update-pill hidden" id="updateIndicator"></div>

  <div class="hero" id="playHero">
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

    <div class="do" id="do"></div>
  </div>
  <div id="homeAlert"><div id="err" role="alert"></div></div>

  <details class="help hidden" id="help">
    <summary id="helpTitle"></summary>
    <div class="helpbody" id="helpBody"></div>
  </details>

  <div class="wifibox hidden" id="wifiBox"></div>
  <div id="wifiActions"></div>


  <!-- Where to go next, shown once setup is done. The tab bar says the
       same thing in five words; this says it with the state of each
       place attached, which is what tells you which one you wanted. -->
  <div class="board hidden" id="board"></div>


  <div class="pick hidden" id="pick"></div>

  <!-- This computer's own saved pairings. Reachable regardless of setup or
       link state, so a pairing for a PiTrac that can never answer again
       (reset, replaced) can always be found and removed locally, even
       during first run and even when it is not the device just found. -->
  <div class="pick hidden" id="knownPis"></div>

  <div class="pick hidden" id="askBox">
    <h3 id="askHead">This PiTrac already has a computer</h3>
    <div class="asknote">PiTrac remembers every computer it has paired with and talks to one at a
      time. To add this one, put PiTrac in pairing mode in either of these ways.</div>
    <div class="askway">
      <strong>With the owner card</strong>
      <div class="asknote">Type the password printed on PiTrac's owner card. It is the same as the
        PiTrac setup Wi-Fi password.</div>
      <form id="askCardForm" autocomplete="off">
        <input type="password" id="askCard" placeholder="Owner card password" autocomplete="off">
        <button class="primary" id="askCardPair" type="submit">Pair this computer</button>
      </form>
    </div>
    <div class="askway">
      <strong>From a computer PiTrac already knows</strong>
      <div class="asknote">On that computer, open Device settings and press Add another computer. Then,
        within five minutes, press Pair this computer here.</div>
      <button class="quiet" id="askRetry">Pair this computer</button>
    </div>
    <div class="asknote">Once paired, this computer is the one connected. The other stays paired.</div>
    <button class="quiet" id="cancelPair">Back</button>
  </div>

  <details class="adv" id="adv">
    <summary>Device settings</summary>
    <div class="advbody">
      <section><h3>PiTrac</h3>
      <button class="quiet" id="changeWifi">Change PiTrac's Wi-Fi</button>
      <button class="quiet" id="setupLink">Open the PiTrac setup page</button>
      <button class="quiet" id="testShot">Send a test shot</button>
      <button class="quiet" id="pairAnotherComputer">Add another computer</button>
      <button class="quiet" id="restart">Restart PiTrac</button>
      <button class="quiet danger" id="shutdown">Shut down PiTrac safely</button>

      </section><section><h3>Backup</h3>
      <button class="quiet" id="makeBackup">Save a backup</button>
      <button class="quiet" id="fullBackup">Save a complete recovery backup</button>
      <label class="linkbtn quiet" for="bkFile" style="cursor:pointer">Restore from a file</label>
      <input type="file" id="bkFile" accept=".pitracbackup,.json,application/json" class="hidden">
      <div id="bkPreview"></div>

      </section><section><h3>This computer</h3>
      <button class="quiet danger" id="forget">Unpair this computer</button>
      <button class="quiet" id="setupAgain">Run setup again</button>
      <button class="quiet" id="quit">Stop Easy-Connect</button>

      </section>
      <div id="note"></div>
    </div>
  </details>
</main>
</div></div>

<!--__RANGE_MARKUP__-->

<div class="pane" id="pane-simulator"><div class="shots">
  <h1>Play mode</h1>
  <div class="row2 three">
    <button class="quiet" data-sim="local">Local Range</button>
    <button class="quiet" data-sim="ogs">OpenGolfSim</button>
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
  <h1>Shot history</h1>
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

<dialog id="devConsole" aria-labelledby="consoleTitle">
  <div class="dialoghead"><h2 id="consoleTitle">Developer console</h2>
    <button class="quiet" id="closeConsole" autofocus>Close</button></div>
  <h3 class="sech">Connection</h3><dl class="kv" id="kv"></dl>
  <h3 class="sech">Recent events</h3><pre class="raw" id="eventLog">No events yet.</pre>
  <h3 class="sech">Cameras</h3>
  <div id="cameras" class="empty">Checking…</div>
      <h3>What PiTrac sent</h3>
      <button class="quiet" id="showRaw">Show the last shots as received</button>
      <div id="rawShots"></div>

</dialog>

<script>
"use strict";
const $=id=>document.getElementById(id);
let status=null, busy=false;
let refreshSequence=0, statusReads=0;
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

async function api(path, body, headers){
  const options=apiOptions(body);
  Object.assign(options.headers, headers);
  const response=await fetch(path, options);
  const data=await response.json().catch(()=>({}));
  if(!response.ok){
    const info=data.error || {};
    if(response.status>=500){
      info.detail=info.detail || info.failed;
      info.failed="Easy-Connect couldn’t complete that request.";
    }
    const error=new Error(info.failed || "That did not work");
    error.info=info;
    throw error;
  }
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
  logDiagnostic(source || "Action", [info.code, info.failed || error.message, info.detail].filter(Boolean).join(" · "));
  // A saved pairing that can never succeed again (the enclosure was reset or
  // replaced) needs its own way out, distinct from every other recovery
  // flow: removing it is a local, no-confirmation-from-the-Pi action, so it
  // has to work even though the Pi that issued it may be unreachable.
  const stale=deviceId && info.code && STALE_PI_CODES.has(info.code);
  $("err").innerHTML=`<div class="err"><h2>${esc(info.failed||error.message)}</h2>
    ${info.nextStep?`<p>${esc(info.nextStep)}</p>`:""}
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
  {key:"wifi",  label:"Wi-Fi", wifi:true},
  {key:"sim",   label:"Play mode"},
  {key:"open",  label:"Open it",   outside:true},
  {key:"test",  label:"Test shot", outside:true},
  {key:"done",  label:"Ready"},
];
//: The Local Range has nothing to open and nothing to prove.
function wizardSteps(data){
  return WIZARD.filter(step=>(!step.outside || !isLocal(data)) && (!step.wifi || WIFI.seen));
}
function isLocal(data){ return data.simulator==="local"; }

//: The same thing in a sentence, for where there is only room for one.
function howToOpen(data){
  return data.simulator==="ogs"
    ? "In OpenGolfSim, choose Developer API as the launch monitor, then go to its range or start a round."
    : "In GSPro, open the Open Connect screen so it is waiting for a device. "+modeNote(data,"gspro");
}

//: Why a play mode cannot be used on this computer, if it cannot.
function modeNote(data, value){
  const mode=(data.playModes||[]).find(m=>m.value===value);
  return (mode && mode.note) || "";
}
let wizard={started:false, simPicked:false, reachedEnclosure:false};

const CANNOT_FIND=`<ol>
  <li>Check the Raspberry Pi has power and its light is on.</li>
  <li>Give it two minutes after switching on. It is slower than a phone.</li>
  <li>If this is its first time, or it is somewhere new, it makes a Wi-Fi network
      of its own. Open the Wi-Fi menu on this computer and join the one called
      <strong id="setupName">PiTrac-</strong>, using the password on the owner card.</li>
  <li>Come back here. It connects by itself, and asks which Wi-Fi to use.</li>
</ol>`;

function wizardView(data){
  const linked=data.link && data.link.connected;
  const sim=data.simulatorStatus||{};
  const steps={}; (data.chain||[]).forEach(s=>steps[s.key]=s);

  if(!wizard.started && !data.pairedEnclosures.length) return {step:null,
    dot:"", head:"Connect your PiTrac", sub:"",
    why:"Power on your launch monitor to pair it with this computer.",
    actions:[{label:"Find my PiTrac", id:"wizStart", primary:true}]};

  const network=wifiView(data);
  if(network) return network;

  if(!linked) return {step:"find",
    dot:"busy", head:"Find your PiTrac", sub:"",
    why:"It needs to be powered on and on this same Wi-Fi.",
    actions:[{label:"Search again", id:"find", primary:true}], find:true,
    help:{title:"I cannot find it", body:CANNOT_FIND}};

  const name=(data.link.device&&data.link.device.displayName)||"PiTrac";

  if(steps.pitrac && !steps.pitrac.ok) return {step:"find",
    dot:"bad", head:"PiTrac needs attention", sub:steps.pitrac.detail,
    why:steps.pitrac.next || "Connected, but the launch monitor cannot measure a shot yet.",
    actions:[{label:"Open the PiTrac setup page", id:"setup", primary:true}]};

  if(!wizard.simPicked) return {step:"sim",
    dot:"", head:"How do you want to play?", sub:name,
    why:"Local Range works on its own, with nothing else to buy or open. "+
        "OpenGolfSim is a free simulator with courses, installed separately. "+
        (modeNote(data,"gspro") || "GSPro needs its own license.")+
        " You can change this later.",
    actions:[{label:"Local Range", id:"wizLocal", primary:true},
             {label:"OpenGolfSim", id:"wizOgs", primary:false},
             {label:"GSPro", id:"wizGspro", primary:false}]};

  if(isLocal(data)) return sim.ready ? {step:"done",
    dot:"good", head:"You're ready to play", sub:"Local Range · "+name,
    why:"Hit a ball and it appears on the range. You will not see these steps "+
        "again — next time you open this it goes straight to playing.",
    actions:[{label:"Go to the range", id:"wizRange", primary:true}]}
  : {step:"sim", dot:"bad", head:"Shots cannot be saved", sub:name, why:"Check the available storage on this computer and try again.",
    actions:[{label:"Check again", id:"check", primary:true},
             {label:"Finish later", id:"wizFinish", primary:false}]};

  if(!sim.connected) return {step:"open",
    dot:"bad", head:"Open "+data.simulatorLabel, sub:name,
    why:howToOpen(data),
    // Finish later, because these last steps need a simulator running and
    // the rest of the app does not. Without it, anyone who opened this
    // before starting GSPro was held here.
    actions:[{label:"Check again", id:"check", primary:true},
             {label:"Back", id:"wizBackSim", primary:false},
             {label:"Finish later", id:"wizFinish", primary:false}]};

  if(!sim.ready) return {step:"test",
    dot:"busy", head:"One shot to make sure", sub:data.simulatorLabel+" · "+name,
    why:"Hit a ball, or send a test shot from here. Either is a real shot to "+
        data.simulatorLabel+", so close any open round first.",
    actions:[{label:"Send a test shot", id:"test", primary:true},
             {label:"Finish later", id:"wizFinish", primary:false}]};

  return {step:"done",
    dot:"good", head:"You're ready to play", sub:data.simulatorLabel+" · "+name,
    why:"That's setup done. You will not see these steps again — next time you "+
        "open this it goes straight to playing.",
    actions:[{label:"Finish", id:"wizFinish", primary:true}]};
}

// --- PiTrac's Wi-Fi --------------------------------------------------------
//
// Asked here rather than on a page the enclosure serves. The only thing this
// app cannot do is put the computer itself on another network, so that is the
// only thing it ever asks somebody to go and do.

const WIFI={stage:null, networks:null, scanning:false, chosen:null, ssid:"", until:0,
            error:null, open:false, seen:false, dropped:false, dismissed:""};
const COUNTRIES=__COUNTRIES_JSON__;

function networkOf(data){ return (data.enclosure && data.enclosure.network) || {}; }
function onSetupSignal(data){
  const net=networkOf(data);
  return !!(net.connection && net.connection.isHotspot);
}
function closeWifi(){
  Object.assign(WIFI,{stage:null, networks:null, chosen:null, error:null, open:false});
}

function wifiView(data){
  const linked=!!(data.link && data.link.connected);
  const net=networkOf(data), setup=onSetupSignal(data);
  const name=(data.link && data.link.device && data.link.device.displayName)||"PiTrac";

  if(WIFI.stage==="joining") return {step:"wifi", wifi:"joining", dot:"busy",
    head:"Joining "+WIFI.ssid, sub:name, why:"This can take a minute.", actions:[]};

  if(WIFI.stage==="wait"){
    const left=Math.max(0, Math.round((WIFI.until-Date.now())/1000));
    if(!linked) WIFI.dropped=true;
    // Until the connection has gone and come back, what is known about where
    // PiTrac is was true before it moved.
    const since=WIFI.dropped || left<110;
    if(linked && !setup && net.connection && net.connection.ssid===WIFI.ssid && !net.awaitingConfirmation){ closeWifi(); }
    else if(linked && setup && since){
      // It is back on its own signal, which only happens when it did not work.
      WIFI.error=net.lastError||{failed:name+" could not be reached on "+WIFI.ssid+"."};
      WIFI.stage=null; WIFI.networks=null; WIFI.chosen=null;
    }else if(left===0 && !linked && WIFI.until && Date.now()-WIFI.until>45000){
      WIFI.error={failed:name+" was not reached on "+WIFI.ssid+".",
        nextStep:"Join "+(net.setupSsid||"its own Wi-Fi")+" from this computer's Wi-Fi menu and try again."};
      closeWifiKeeping();
    }else return {step:"wifi", wifi:"wait", left:left, dot:"busy", find:!linked,
      head:"Put this computer on "+WIFI.ssid, sub:name,
      why:"Choose "+WIFI.ssid+" in this computer's Wi-Fi menu. Easy-Connect will reconnect automatically.",
      actions:[{label:"Search again", id:"find", primary:true}]};
  }

  if(!linked || !(WIFI.open || (setup && !net.directMode))) return null;
  if(setup) WIFI.seen=true;
  // Whatever went wrong may have taken the connection with it, so this is the
  // first chance to say what it was.
  if(setup && net.lastError && !WIFI.error && !WIFI.stage && WIFI.dismissed!==JSON.stringify(net.lastError))
    WIFI.error=net.lastError;
  const back=WIFI.open && !setup;

  if(!net.country) return {step:"wifi", wifi:"country", dot:"", head:"Which country are you in?",
    sub:name, why:"Wi-Fi radios follow different rules in different countries.",
    actions:[{label:"Continue", id:"wifiCountry", primary:true}]};

  if(WIFI.stage==="password"){
    const c=WIFI.chosen;
    return {step:"wifi", wifi:"password", dot:"",
      head:c.hidden ? "Type your network" : "Password for "+c.ssid, sub:name, why:"",
      actions:[{label:"Connect", id:"wifiJoin", primary:true}, {label:"Back", id:"wifiBack"}]};
  }
  if(WIFI.networks===null && !WIFI.scanning) scanWifi();
  return {step:"wifi", wifi:"list", dot:WIFI.error?"bad":"", head:"Choose PiTrac's Wi-Fi", sub:name,
    why:"Pick the network this computer uses at home.",
    actions:[{label:"Search again", id:"wifiScan"}, {label:"Type a network name", id:"wifiHidden"},
      back ? {label:"Cancel", id:"wifiClose"} : {label:"Play without a router", id:"wifiDirect"}]};
}
function closeWifiKeeping(){ WIFI.stage=null; WIFI.networks=null; WIFI.chosen=null; WIFI.until=0; }

async function scanWifi(){
  WIFI.scanning=true;
  try{
    const data=await api("/api/enclosure",{command:"scanNetworks"});
    WIFI.networks=data.networks||[];
  }catch(error){
    WIFI.networks=[]; WIFI.error=error.info||{failed:error.message};
  }finally{ WIFI.scanning=false; }
  if(status) render(status);
}

function wifiRow(n){
  return `<button class="device" data-ssid="${esc(n.ssid)}" ${n.supported?"":"disabled"}>
    <span><strong>${esc(n.ssid)}</strong><small>${esc(n.inUse?"Connected now":
      !n.supported?"Not supported":n.known?"Saved":n.needsPassword?"Password needed":"Open")}</small></span>
    <span class="bars" aria-label="${esc(n.bars+" of 4")}">${[1,2,3,4].map(b=>
      `<i class="${b<=n.bars?"on":""}" style="height:${b*3.5}px"></i>`).join("")}</span></button>`;
}

function renderWifi(view){
  const host=$("wifiBox"), kind=view && view.wifi;
  host.classList.toggle("hidden", !kind);
  if(!kind){ host.dataset.sig=""; host.innerHTML=""; return; }
  let html="";
  if(WIFI.error && kind==="list") html+=`<div class="err"><h2>${esc(WIFI.error.failed||"That did not work")}</h2>
    <p>${esc(WIFI.error.nextStep||"")}</p></div>`;
  if(kind==="country"){
    const mine=((navigator.language||"").split("-")[1]||"US").toUpperCase();
    html+='<select class="wififield" id="wifiCountryPick" aria-label="Country">'+COUNTRIES.map(c=>
      `<option value="${esc(c[0])}"${c[0]===mine?" selected":""}>${esc(c[1])}</option>`).join("")+"</select>";
  }else if(kind==="password"){
    const c=WIFI.chosen;
    html+=(c.hidden?'<label for="wifiName">Network name</label><input class="wififield" type="text" id="wifiName" autocapitalize="none" autocorrect="off" spellcheck="false">':"")+
      '<label for="wifiPassword">Password</label><input class="wififield" type="password" id="wifiPassword" autocapitalize="none" autocorrect="off" spellcheck="false">'+
      '<label class="wifishow"><input type="checkbox" id="wifiShow"> Show password</label>'+
      '<div class="clubnote">It goes to PiTrac over the encrypted link and is kept only there.</div>';
  }else if(kind==="list"){
    const list=WIFI.networks;
    html+=list===null ? '<div class="empty">Looking for networks…</div>'
      : !list.length ? '<div class="empty">No networks were found. Move PiTrac closer to your router, or type the name.</div>'
      : '<div class="wifilist">'+list.slice().sort((a,b)=>(b.inUse-a.inUse)||(b.known-a.known)).map(wifiRow).join("")+"</div>";
  }else if(kind==="wait"){
    html+=`<div class="wificount">${esc(Math.floor(view.left/60)+":"+String(view.left%60).padStart(2,"0"))}</div>`;
  }
  if(!changed(host, html)) return;
  host.innerHTML=html;
  const first=$("wifiName")||$("wifiPassword");
  if(first) first.focus();
  const show=$("wifiShow");
  if(show) show.addEventListener("change",()=>{ $("wifiPassword").type=show.checked?"text":"password"; });
  if($("wifiPassword")) $("wifiPassword").addEventListener("keydown",e=>{ if(e.key==="Enter") doAction("wifiJoin"); });
  host.querySelectorAll("[data-ssid]").forEach(button=>button.addEventListener("click",()=>{
    const picked=WIFI.networks.find(n=>n.ssid===button.dataset.ssid);
    WIFI.error=null;
    WIFI.dismissed=JSON.stringify(networkOf(status).lastError||null);
    // Saved, so it needs nothing typed. Open, so there is nothing to type.
    if(picked.known || !picked.needsPassword) return joinWifi(picked.ssid, "", false);
    WIFI.chosen={ssid:picked.ssid, hidden:false}; WIFI.stage="password"; render(status);
  }));
}

async function joinWifi(ssid, password, hidden){
  const before=onSetupSignal(status);
  Object.assign(WIFI,{stage:"joining", ssid:ssid, error:null});
  render(status);
  const waiting=()=>Object.assign(WIFI,{stage:"wait", dropped:false, until:Date.now()+150000});
  try{
    const result=await api("/api/enclosure",{command:"joinNetwork",
      arguments:{ssid:ssid, password:password, hidden:hidden}});
    if(result.ok) waiting();
    else{
      WIFI.error=Object.assign({failed:result.message}, result.error||{});
      const retype=!hidden && (result.error||{}).code===__WRONG_PASSWORD_CODE_JSON__;
      WIFI.stage=retype ? "password" : null;
      WIFI.chosen=retype ? {ssid:ssid, hidden:false} : null;
      WIFI.networks=null;
      if(retype) showError({message:WIFI.error.failed,
        info:{failed:WIFI.error.failed, nextStep:"Check it and try again. Watch for capital letters."}});
    }
  }catch(error){
    // Moving takes PiTrac off the Wi-Fi this answer would have come over, so
    // silence here is what success looks like. Being told no is not.
    const said=error.info && error.info.code && !/^PT-LINK/.test(error.info.code);
    if(before && !said) waiting();
    else Object.assign(WIFI,{stage:null, networks:null, error:error.info||{failed:error.message}});
  }
  render(status);
}

//: The places the app can take you, and what each is doing right now. The
//: enclosure's own pages need a live link -- the same rule that sends a pane
//: back to Play when the link drops -- so those two say so rather than
//: leading somewhere empty.
function boardCards(data){
  const linked=!!(data.link && data.link.connected);
  const shots=(data.shotLog&&data.shotLog.total)||0;
  return [
    {pane:"range", title:"Practice range", detail:"Aim at a target and track your ball flight."},
    {pane:"shots", title:"Shot history", detail:shots ? shots+(shots===1?" shot recorded":" shots recorded") : "Distances and dispersion by club."},
    {pane:"simulator", title:"Play mode", detail:isLocal(data) ? "Local Range" : data.simulatorLabel || "Choose a simulator"},
    {pane:"setup", title:"Wi-Fi & setup", needsLink:true, detail:linked ? "Manage the enclosure and its network." : "Connect to PiTrac to open settings."},
    {pane:"pitrac", title:"Launch monitor", needsLink:true, detail:linked ? "Camera alignment and calibration." : "Connect to PiTrac to open the dashboard."},
  ].map(card=>Object.assign(card, {disabled: !!card.needsLink && !linked}));
}

//: Where the desktop dials each simulator. Shown because when this fails,
//: "nothing is listening on 127.0.0.1:921" is the fact that identifies which
//: side is wrong, and it is otherwise invisible.
const SIM_WHERE = {
  gspro: {port: 921, screen: "Open Connect",
          how: "In GSPro, open the <strong>Open Connect</strong> screen so it is waiting for a device."},
  ogs:   {port: 3111, screen: "Developer API",
          how: "In OpenGolfSim, choose <strong>Developer API</strong> as the launch monitor, then go to its range or start a round."},
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
      : "Check the available storage on this computer and try again.";
    $("simSteps").innerHTML = "";
    $("simWhere").textContent = linked ? ""
      : "PiTrac is not connected, so there are no shots to record yet.";
    return;
  }
  const where = SIM_WHERE[data.simulator];

  $("simDot").className = "dot " + (sim.ready ? "good" : sim.connected ? "busy" : "bad");
  $("simHead").textContent = sim.ready ? "Ready to play"
    : sim.connected ? "Waiting for the first shot" : "Not connected";
  $("simWhy").textContent = (sim.ready ? label + " has accepted a shot from PiTrac."
        : sim.connected ? "Connected to " + label + ". Hit a ball, or send a test shot, to make sure."
        : label + " is not answering on this computer yet.");

  const steps = [
    {done: true, text: "Choose " + esc(label) + " above."},
    {done: !!sim.connected, text: "Open " + esc(label) + " on this computer. " + where.how},
    {done: !!sim.ready, text: "Hit a ball. When " + esc(label) + " plays it, everything from the "
                             + "cameras on is working. A test shot checks only this computer and "
                             + esc(label) + "."},
  ];
  $("simSteps").innerHTML = "<ol class='simsteps'>" + steps.map(s=>
    `<li class="${s.done?"done":""}">${s.text}</li>`).join("") + "</ol>";

  $("simWhere").textContent = linked ? "" : "Connect PiTrac to send a test shot.";
  $("simTest").disabled = !linked || !sim.connected;
}

function renderBoard(data, guiding){
  const board=$("board");
  board.classList.toggle("hidden", guiding);
  if(guiding){ board.innerHTML=""; delete board.dataset.sig; return; }
  const cards=boardCards(data);
  if(!changed(board, JSON.stringify(cards))) return;
  board.innerHTML=cards.map(card=>
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

// Two situations come before everything else, because each has exactly one
// thing to press and the ordinary views would bury it under an error.
//
// PiTrac is with another of its computers. Like a remembered Bluetooth device,
// it talks to one at a time and keeps the others; choosing this one moves it.
// Nothing moves it on its own, so two computers never fight over it.
//
// PiTrac is too old to talk to, and needs reinstalling once.
const ELSEWHERE_CODES=__ELSEWHERE_CODES_JSON__;
const VERSION_MISMATCH_CODE=__VERSION_MISMATCH_CODE_JSON__;
function linkView(data){
  const old=data.oldEnclosure;
  // Too old to talk to, and too old to update itself: its updater cannot swap
  // versions under its own service protections. Saying so beats a button
  // that can only ever fail.
  if(old) return {
    dot:"bad", head:"PiTrac needs a one-time reinstall",
    sub:"PiTrac is running Easy-Connect "+(old.version||"(an older version)")+
      ". This app is "+old.targetVersion+", and that version is too old to work with it or to update itself.",
    why:"Reinstall it once from the Easy-Connect kit, as READ ME FIRST describes. Its Wi-Fi, "+
      "pairings and calibration are kept, and from then on it updates itself.",
    actions:[]};
  const error=data.link&&data.link.lastError;
  if(error && ELSEWHERE_CODES.includes(error.code)){
    const moved=error.code===ELSEWHERE_CODES[1];
    return {
      dot:"", head:moved?"PiTrac moved to another computer":"PiTrac is connected to another computer",
      sub:"PiTrac talks to one computer at a time and remembers the others.",
      why:"Connect here to move it to this computer. The other computer stays paired and can take it back the same way.",
      actions:[{label:"Connect here", id:"connectHere", primary:true}]};
  }
  return null;
}

function present(data){
  const linked=data.link && data.link.connected;
  const sim=data.simulatorStatus||{};
  const steps={}; (data.chain||[]).forEach(s=>steps[s.key]=s);

  if(!data.pairedEnclosures.length) return {
    dot:"", head:"Set up PiTrac", sub:"Let's find your enclosure.",
    why:"PiTrac needs to be powered on and on this network.",
    actions:[{label:"Find my PiTrac", id:"find", primary:true}], find:true};

  const network=wifiView(data);
  if(network) return network;

  if(!linked) return {
    dot:"busy", head:"Looking for PiTrac", sub:"",
    why:"Check PiTrac has power and is on this network.",
    actions:[{label:"Search again", id:"find", primary:false}], find:true,
    help:{title:"It is somewhere new", body:CANNOT_FIND}};

  const name=(data.link.device&&data.link.device.displayName)||"PiTrac";

  if(steps.pitrac && !steps.pitrac.ok) return {
    dot:"bad", head:"PiTrac needs attention", sub:steps.pitrac.detail,
    why:steps.pitrac.next || "Easy-Connect is connected, but the launch monitor cannot measure a shot yet.",
    actions:[{label:"Open the PiTrac setup page", id:"setup", primary:true}]};

  if(isLocal(data)) return sim.ready ? {
    dot:"good", head:"Ready to play", sub:"Local Range · "+name,
    why:"", actions:[{label:"Go to the range", id:"range", primary:true}]}
  : {
    dot:"bad", head:"Shots cannot be saved", sub:name, why:"Check the available storage on this computer and try again.",
    actions:[{label:"Check again", id:"check", primary:true}]};

  if(!sim.connected) return {
    dot:"bad", head:"Open "+data.simulatorLabel, sub:name,
    why:howToOpen(data),
    actions:[{label:"Check again", id:"check", primary:true}]};

  if(!sim.ready) return {
    dot:"busy", head:"Almost ready", sub:data.simulatorLabel+" · "+name,
    why:"Hit a ball, or send a test shot from here. Either is a real shot, so close any open round first.",
    actions:[{label:"Send a test shot", id:"test", primary:true}]};

  return {
    dot:"good", head:"Ready to play", sub:data.simulatorLabel+" · "+name,
    why:"", actions:[{label:"View shot data", id:"dash", primary:false}]};
}

function render(data){
  document.body.classList.remove("starting");
  status=data;
  const guiding=!data.setupComplete;
  const special=linkView(data);
  const view=special || (guiding ? wizardView(data) : present(data));
  renderWizard(guiding && !special ? view : null);

  // The link client can stop retrying on its own (a device-id mismatch, a
  // revoked pairing) with nothing else ever telling the user why — no
  // synchronous API call failed, so nothing else would have shown this.
  // Surface it here, from status, rather than only from a caught exception.
  // What linkView already explains, with its button, is not also an error.
  const explained=special && data.link && data.link.lastError &&
    (ELSEWHERE_CODES.includes(data.link.lastError.code) || data.link.lastError.code===VERSION_MISMATCH_CODE);
  const linkError=!explained && data.link && data.link.lastError;
  if(linkError&&!busy&&!asking()&&!WIFI.stage){
    showError({info:linkError}, data.link.lastErrorDeviceId||data.activeDeviceId, "link");
  }else if(WIFI.stage&&$("err").dataset.from==="link"){
    // Losing the link is what changing networks looks like from here.
    showError(null);
  }else if(!linkError&&!busy&&!asking()&&$("err").dataset.from==="link"){
    // The connection this message described has since succeeded, or the
    // attempt that failed is no longer the last word. Taking it down here is
    // what lets a search stop doing it: render puts link errors up, so render
    // is what removes them.
    showError(null);
  }
  const pairingHost=guiding || !(data.link && data.link.connected) ? $("askBox").parentElement : $("adv").querySelector(".advbody");
  if($("knownPis").parentElement!==pairingHost) pairingHost.appendChild($("knownPis"));
  if(!data.link || !data.link.connected) cameraDevice=null;
  renderKnownPis(data);

  const help=view.help;
  $("help").classList.toggle("hidden", !help);
  if(help){ $("helpTitle").textContent=help.title; $("helpBody").innerHTML=help.body; }

  $("dot").className="dot "+view.dot;
  $("head").textContent=view.head;
  $("sub").textContent=view.sub||"";
  $("why").textContent=view.why||"";

  renderWifi(view);
  const actionHost=view.wifi ? $("wifiActions") : $("playHero");
  if($("do").parentElement!==actionHost) actionHost.appendChild($("do"));
  const setupName=$("setupName");
  if(setupName && data.activeDeviceId) setupName.textContent="PiTrac-"+data.activeDeviceId;
  if(!busy){
    if(changed($("do"), JSON.stringify(view.actions))){
      $("do").innerHTML="";
      view.actions.forEach(action=>{
        const button=document.createElement("button");
        button.className=action.primary?"primary":"quiet";
        button.textContent=action.label;
        button.addEventListener("click",()=>doAction(action.id,button));
        $("do").appendChild(button);
      });
    }
    if(view.find){
      // Rendering must stay free of state-changing side effects: only start
      // a fresh broadcast when nothing recent is cached and none is already
      // running. Every render while waiting must not mean another search.
      const stale=!lastSearchAt||(Date.now()-lastSearchAt)>SEARCH_CACHE_MS;
      if(!searchInFlight&&stale) findDevices();
    } else $("pick").classList.add("hidden");
  }

  renderUpdate(data.update);
  if(pane==="shots"){ renderShots(data.shotLog); renderImages(data.enclosure); }
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
  if(pane==="range" && rangeData) renderState(rangeData);
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
  if($("devConsole").open) renderConsole();
}

function doAction(id, button){
  if(id==="wifiScan"){
    WIFI.networks=null; WIFI.error=null;
    WIFI.dismissed=JSON.stringify(networkOf(status).lastError||null);
    return render(status);
  }
  if(id==="wifiHidden"){ WIFI.chosen={ssid:"", hidden:true}; WIFI.stage="password"; return render(status); }
  if(id==="wifiBack"){ WIFI.stage=null; WIFI.chosen=null; showError(null); return render(status); }
  if(id==="wifiClose"){ closeWifi(); return render(status); }
  if(id==="wifiCountry") return run(button, ()=>api("/api/enclosure",
    {command:"setCountry", arguments:{country:$("wifiCountryPick").value}}));
  if(id==="wifiDirect") return run(button, async()=>{
    if(!confirm("Play without a router?\n\nThis computer stays on PiTrac's own Wi-Fi, which has no internet. You can change this later.")) return;
    await api("/api/enclosure",{command:"setDirectMode", arguments:{enabled:true}});
    closeWifi();
  });
  if(id==="wifiJoin"){
    const c=WIFI.chosen, ssid=c.hidden ? $("wifiName").value.trim() : c.ssid, password=$("wifiPassword").value;
    if(!ssid) return showError(new Error("Type the name of your network"));
    showError(null);
    return joinWifi(ssid, password, c.hidden);
  }
  if(id==="wizStart"){ wizard.started=true; return refresh(); }
  if(id==="wizBackSim"){ wizard.simPicked=false; return refresh(); }
  const modes={wizLocal:"local", wizOgs:"ogs", wizGspro:"gspro"};
  if(modes[id]) return run(button, async()=>{
    await api("/api/simulator",{simulator:modes[id]});
    wizard.simPicked=true;
  });
  if(id==="wizRange") return run(button, async()=>{
    await api("/api/finish-setup",{done:true});
    showPane("range");
  });
  if(id==="range") return showPane("range");
  if(id==="wizFinish") return run(button, ()=>api("/api/finish-setup",{done:true}));
  if(id==="find") return run(button, findDevices);
  if(id==="connectHere") return run(button, ()=>api("/api/connect",{deviceId:status.activeDeviceId, takeOver:true}));
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

//: The states in which this computer tried to install an update itself and
//: could not. Everything else either is quietly fine or is still going.
const DESKTOP_UPDATE_STUCK_STATES=new Set([
  "preflight-failed","rolled-back","download-failed","verify-failed","install-failed",
]);

// What an update is doing right now, in one line, or nothing. Updates check,
// download, verify and install themselves -- the desktop first, then PiTrac to
// exactly the same version -- so there is nothing here to press and nothing
// to dismiss, only something to read while it happens.
function updateActivity(state, desktop, plan){
  const version=desktop.stagedTargetVersion||desktop.availableVersion||plan.targetVersion||"";
  switch(state){
    case "downloading": case "verifying": case "staging":
      // Fetched ahead of the click; only worth saying once it was asked for.
      return desktop.installWhenReady ? "Getting update "+version+" ready…" : "";
    case "ready-to-restart": return "";
    case "installing": case "awaiting-restart-verification": return "Installing update "+version+"…";
    case "rollback": return "Putting the previous version back…";
    case "restart-required": return "Update installed. Start PiTrac Easy-Connect again to finish.";
  }
  if(plan.phase==="pi-update-required" || plan.phase==="verifying-pi")
    return "Updating PiTrac to "+(plan.targetVersion||"")+"…";
  return "";
}

function renderUpdate(update){
  const host=$("update"), indicator=$("updateIndicator");
  const plan=(update&&update.coordination)||{};
  const desktop=(update&&update.desktop)||{};
  const state=desktop.state||"idle";
  const line=update?updateActivity(state, desktop, plan):"";
  indicator.classList.toggle("hidden", !line);
  indicator.textContent=line;
  // An update this computer could not install by itself -- typically an app
  // run from where it cannot replace itself. The verified package is kept;
  // this shows where.
  if(update && DESKTOP_UPDATE_STUCK_STATES.has(state) && desktop.savedPackagePath){
    host.innerHTML='<div class="update"><span>'+esc(desktop.detail||
      "Easy-Connect could not update itself.")+'</span><span class="update-actions">'+
      '<button class="quiet" id="getUpdate">'+esc(desktop.revealAction||"Show downloaded file")+
      '</button></span></div>';
    wireDesktopDownload(host, desktop.savedPackagePath);
    return;
  }
  // A newer version: offered at the top of the startup page, with one button,
  // until it is installed. There is no "later" -- playing on outdated code
  // should be a choice made knowingly, not a dismissed card. PiTrac is
  // brought to the same version by itself once this computer restarts.
  if(update && plan.phase==="desktop-update-required" && plan.targetVersion &&
     !["installing","awaiting-restart-verification","rollback","restart-required"].includes(state)){
    const asked=!!desktop.installWhenReady;
    host.innerHTML='<div class="update offer"><span><strong>PiTrac Easy-Connect '+
      esc(plan.targetVersion)+' is available</strong>This computer has '+
      esc(desktop.installedVersion||plan.installedVersion||"")+
      '. Updating restarts Easy-Connect, then updates PiTrac by itself.</span>'+
      '<button class="primary" id="updateNow"'+(asked?" disabled":"")+'>'+
      (asked?"Getting it ready…":"Update now")+'</button></div>';
    if(!asked) $("updateNow").addEventListener("click",e=>run(e.target, async()=>{
      const result=await api("/api/update/now",{});
      if(result && result.started===false && result.detail)
        throw Object.assign(new Error(result.detail),{info:{failed:result.detail}});
    }));
    return;
  }
  host.innerHTML="";
}

function wireDesktopDownload(host,savedPath){
  const get=$("getUpdate");
  if(!get) return;
  get.addEventListener("click",e=>run(e.target,async()=>{
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
  }));
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

const diagnosticEvents=[];
function logDiagnostic(source, message){
  if(!message) return;
  const line=source+" · "+message;
  if(diagnosticEvents.length && diagnosticEvents[diagnosticEvents.length-1].line===line) return;
  diagnosticEvents.push({line, at:new Date().toLocaleTimeString()});
  if(diagnosticEvents.length>50) diagnosticEvents.shift();
  if($("devConsole").open) renderEvents();
}
function renderEvents(){
  $("eventLog").textContent=diagnosticEvents.map(e=>e.at+"  "+e.line).join("\n") || "No events yet.";
}
function renderConsole(){
  renderEvents();
  if(status){ renderDetails(status); loadCameras(); }
}
function openConsole(){
  if(!$("devConsole").open) $("devConsole").showModal();
  renderConsole();
}
$("openConsole").addEventListener("click", openConsole);
$("closeConsole").addEventListener("click", ()=>$("devConsole").close());
document.addEventListener("keydown", event=>{
  if(event.altKey && event.shiftKey && event.code==="KeyD"){
    event.preventDefault();
    if($("devConsole").open) $("devConsole").close(); else openConsole();
  }
});
window.addEventListener("error", event=>logDiagnostic("Interface", event.message));
window.addEventListener("unhandledrejection", event=>
  logDiagnostic("Interface", event.reason && event.reason.message));

function renderDetails(data){
  const device=(data.link&&data.link.device)||{};
  const enclosure=data.enclosure||{};
  const network=enclosure.network||{};
  const shots=data.shots||{};
  const sim=data.simulatorStatus||{};
  const update=data.update||{};
  const rows=[["Enclosure",device.displayName||"-"],["Device",device.deviceId||"-"],
    ["Address",(data.link&&data.link.address)||"-"],
    ["Simulator",sim.endpoint || data.simulatorLabel || "-"],
    ["Simulator status",[sim.errorCode,sim.message].filter(Boolean).join(" · ")],
    ["Wi-Fi",(network.connection&&network.connection.ssid)||"-"],
    [isLocal(data)?"Shots recorded":"Shots sent",shots.delivered!=null?shots.delivered:"-"],
    [isLocal(data)?"Not recorded":"Not delivered",shots.lost!=null?shots.lost:"-"],
    ["PiTrac",device.version||"-"],["Easy-Connect",data.version],
    ["Versions match",update.enclosureVersion?(update.versionsMatch?"yes":"no — update both"):"-"],
    ["Updates",update.detail||"-"]];
  // What the enclosure saw at each level when a camera is missing, so a cable
  // fault and a software fault can be told apart without opening a terminal.
  const cameraCheck=((enclosure.selfTest||{}).checks||[]).find(c=>c.key==="cameras");
  const seen=cameraCheck&&cameraCheck.diagnosis&&cameraCheck.diagnosis.evidence;
  if(seen){
    rows.push(["Camera detection", seen.autoDetect?"automatic at power-on":"off in config.txt"]);
    rows.push(["Cameras the Pi looked for", seen.expectedSensors.length?seen.expectedSensors.join(", "):"none answered"]);
    rows.push(["Cameras working", seen.boundSensors.length?seen.boundSensors.join(", "):"none"]);
    rows.push(["Camera software", seen.rpicamMessage||(seen.listed+" listed")]);
    if(seen.kernelLines.length) rows.push(["Kernel said", seen.kernelLines[seen.kernelLines.length-1]]);
  }
  $("kv").innerHTML=rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

// --- pairing, which happens once ----------------------------------------

async function findDevices(){
  if(searchInFlight) return;
  searchInFlight=true;
  const host=$("pick");
  try{
    const data=await api("/api/search",{});
    for(const e of data.enclosures || []) logDiagnostic("Discovery", e.displayName+" · "+e.address);
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
      if(!data.problem && !WIFI.stage){
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
        <span><strong>${esc(e.displayName)}</strong></span>
        <span class="tag ${e.paired?"on":""}">${e.paired?"Saved":"Pair"}</span>
      </button>`).join("");
    host.querySelectorAll(".device").forEach(button=>button.addEventListener("click",()=>{
      const id=button.dataset.id;
      if(button.dataset.paired==="1") return run(button, ()=>api("/api/connect",{deviceId:id}));
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
  if(!changed(host, JSON.stringify([list, data.activeDeviceId, !!(data.link && data.link.connected)]))) return;
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
  askingFor=enclosure||null;
  $("askHead").textContent=((enclosure&&enclosure.displayName)||"This PiTrac")+" already has a computer";
  $("askCard").value="";
  document.body.classList.add("pairing");
  $("askBox").classList.remove("hidden");
  $("askCard").focus();
}

function closeAsk(){
  askingFor=null;
  $("askCard").value="";  // never left lying in the page
  document.body.classList.remove("pairing");
  $("askBox").classList.add("hidden");
  $("err").innerHTML="";  // the panel is gone, so the reason for it is stale
}

let askingFor=null;
async function pairAsked(button, body){
  if(!askingFor) return;
  const id=askingFor.deviceId;
  await run(button, async()=>{
    await api("/api/pair",{deviceId:id, ...body});
    closeAsk();
  });
}
$("askCardForm").addEventListener("submit",e=>{
  e.preventDefault();
  const password=$("askCard").value;
  if(!password){ $("askCard").focus(); return; }
  pairAsked($("askCardPair"), {ownerCardPassword:password});
});
$("askRetry").addEventListener("click",e=>pairAsked(e.target, {}));

$("cancelPair").addEventListener("click",()=>{ closeAsk(); refresh(); });

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
$("changeWifi").addEventListener("click",()=>{
  closeWifi(); WIFI.open=true; showPane("play"); render(status);
});
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
      ${info.sameDevice&&info.sameHardware!==false?"":"<br><span style='color:var(--amber)'>From a different enclosure.</span>"}
      </div><button class="quiet" id="doRestore" style="margin-top:9px">Restore this</button>`;
    $("doRestore").addEventListener("click",b=>run(b.target, async()=>{
      // Calibration describes one particular pair of cameras in one
      // particular enclosure. Sending the override without asking meant an
      // amber note was the only thing between somebody and a machine
      // calibrated for a different unit.
      const elsewhere=!info.sameDevice||info.sameHardware===false;
      if(elsewhere){
        if(!confirm("This backup is from a different PiTrac.\n\n"+
            "Its camera calibration describes that enclosure's cameras, not "+
            "this one's. Restoring it will make this PiTrac measure shots "+
            "incorrectly until it is calibrated again.\n\n"+
            "Restore it anyway?")) return;
      }
      // How hard the strobe is driven is only right for one circuit board, and
      // too hard for it can damage it. Only offered on the same Raspberry Pi,
      // and even then only the owner knows whether the board was changed.
      const sameBoard=info.canRestoreStrobe && confirm(
        "Restore the strobe settings too?\n\n"+
        "Press OK only if the connector board and strobe have NOT been changed since "+
        "this backup was made. The wrong settings can damage the strobe.\n\n"+
        "Cancel keeps the settings this PiTrac has now. Everything else is restored either way.");
      const result=await api("/api/backup/restore",{file:text, calibration:true, preferences:true,
        identity:info.sections.includes("identity"), pairings:info.sections.includes("pairings"),
        confirmDifferentDevice:elsewhere, confirmSameBoard:sameBoard});
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
            'not be restarted. Restart it from Device settings before playing.</div>';
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
  (name==="play" ? $("homeAlert") : $("paneAlert")).appendChild($("err"));
  if(name==="shots" && status){ renderShots(status.shotLog); renderImages(status.enclosure); }
  document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("on", p.id==="pane-"+name));
  document.querySelectorAll("#tabs button").forEach(b=>{
    b.classList.toggle("on", b.dataset.pane===name);
    if(b.dataset.pane===name) b.setAttribute("aria-current","page"); else b.removeAttribute("aria-current");
  });
  if(name==="range"){
    // The canvas has no size until its pane is shown, so the context is
    // created on first open rather than at load.
    if(RANGE.start()) RANGE.resize();
    refreshRange();
  }
  unloadHiddenFrames();
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
let clubReady=false, cameraDevice=null;

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

// What became of a shot, in the simulator's own terms. "Sent" is what is known
// when nothing was said back, and no more than that.
function outcomeText(s){
  switch(s.outcome){
    case "played": return s.simCarry==null ? "Played" : "Played, "+Math.round(s.simCarry)+" yd";
    case "accepted": return "Taken";
    case "unknown": return "Sent, no answer";
    case "rejected": return "Refused";
    case "undelivered": return "Not sent";
    case "local": return "";
  }
  return s.delivered===false ? "Not sent" : s.delivered ? "Sent" : "";
}

function renderRecent(log){
  const recent=log.recent||[];
  const played=recent.some(s=>outcomeText(s));
  if(!changed($("recent"), JSON.stringify(recent))) return;
  $("recent").className = recent.length ? "scroller" : "empty";
  $("recent").innerHTML = recent.length ? `<table class="shot">
    <thead><tr><th>Time</th><th>Club</th><th class="num">Speed</th><th class="num">Launch</th>
      <th class="num">Direction</th><th class="num">Spin</th><th class="num">Carry</th>${
      played?"<th>Simulator</th>":""}</tr></thead>
    <tbody>${recent.map(s=>`<tr class="${esc(s.delivered===false?"lost":"")}">
      <td>${esc(s.timeText)}</td><td>${esc(s.club||"-")}</td>
      <td class="num">${s.speed==null?"-":s.speed}</td>
      <td class="num">${s.launch==null?"-":s.launch}</td>
      <td class="num">${s.direction==null?"-":s.direction===0?"0":Math.abs(s.direction)+(s.direction>0?" R":" L")}</td>
      <td class="num">${s.backSpin==null?"-":s.backSpin}</td>
      <td class="num">${s.carry==null?"-":Math.round(s.carry)+" yd"}</td>${
      played?"<td>"+esc(outcomeText(s))+"</td>":""}</tr>`).join("")}
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
  // Build tiles only while the shot history is visible.
  host.className="shotgrid";
  host.innerHTML=images.map(image=>{
    const url=base+image.url;
    return `<div title="${esc(image.name)}">
      <img src="${esc(url)}" alt="${esc(image.name)}" decoding="async">
      <small>${esc(image.name)}</small></div>`;
  }).join("");
}

async function loadCameras(){
  const id=status.link && status.link.connected && status.activeDeviceId;
  if(!id){ cameraDevice=null; $("cameras").textContent="Connect PiTrac to inspect the cameras."; return; }
  if(cameraDevice===id) return;
  cameraDevice=id;
  $("cameras").textContent="Checking…";
  try{
    const data=await api("/api/cameras",{});
    if(cameraDevice!==id) return;
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
       Launch monitor dashboard. PiTrac measures the ball with still images and does not record swing video.</div>`;
  }catch(error){ if(cameraDevice!==id) return; $("cameras").className="empty"; $("cameras").textContent="Could not ask PiTrac."; }
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
  // A refusal is not retried on every 3-second render; a minute is plenty.
  if(!ownerToken && Date.now()-ownerTokenAt<60*1000) return ownerToken;
  ownerTokenAt=Date.now();
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
  // Keyed by the address, not the token in it: a renewed token changed the
  // URL, and the frame reloaded under whatever was being typed into it.
  frameInto("setupFrame","setupHint", token?base+"?ownerToken="+encodeURIComponent(token):base,
    "Connect to PiTrac to change its settings.", base);
}

function loadFrames(){
  if(!status) return;
  // Load a frame the first time its tab is opened, so the enclosure is not
  // serving two extra pages to a window nobody has looked at.

  if(pane==="pitrac"){
    const url=status.dashboardUrl;
    frameInto("pitracFrame","pitracHint",url,
      "Connect to PiTrac to see shot data.");
  }
  if(pane==="setup") openSetupFrame();
}

function frameInto(frameId, hintId, url, emptyText, key){
  const frame=$(frameId), hint=$(hintId);
  if(!url){ frame.style.display="none"; hint.style.display=""; hint.textContent=emptyText; return; }
  hint.style.display="none"; frame.style.display="";
  const same=key||url;
  if(frame.dataset.src!==same){ frame.dataset.src=same; frame.src=url; }
}

// A frame left loaded after its tab is closed goes on polling the enclosure:
// the setup page asks for PiTrac's status every few seconds, and each answer
// costs the Pi a round of system checks, for the rest of the session.
function unloadHiddenFrames(){
  [["pitracFrame","pitrac"],["setupFrame","setup"]].forEach(([id,owner])=>{
    const frame=$(id);
    if(pane!==owner && frame.dataset.src){
      // A fresh empty frame in its place: no navigation, nothing for the
      // page's security policy to judge, and the old page is gone.
      frame.removeAttribute("src");
      const empty=frame.cloneNode(false);
      delete empty.dataset.src;
      frame.replaceWith(empty);
    }
  });
}

async function refresh(){
  const sequence=++refreshSequence;
  statusReads++;
  try{ const data=await api("/api/status"); if(sequence===refreshSequence) render(data); }
  catch(error){
    if(sequence!==refreshSequence) return;
    document.body.classList.remove("starting");
    logDiagnostic("Desktop status", error.message);
    $("dot").className="dot bad";
    $("head").textContent="Reconnecting to Easy-Connect";
    $("sub").textContent="If this persists, reopen the app.";
    $("why").textContent="";
  }finally{ statusReads--; }
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
setInterval(()=>{ if(!statusReads && !busy && !asking() && !document.hidden) refresh(); }, 3000);
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

    from ..common.countries import COUNTRIES
    from ..common.errors import (
        LINK_DEVICE_MISMATCH,
        LINK_DEVICE_REPLACED,
        LINK_BUSY,
        LINK_TAKEN_OVER,
        LINK_VERSION_MISMATCH,
        NET_WRONG_PASSWORD,
        PAIR_NOT_ACCEPTING,
    )

    return page.replace(
        "__STALE_PI_CODES_JSON__",
        json.dumps([LINK_DEVICE_MISMATCH.code, LINK_DEVICE_REPLACED.code]),
    ).replace(
        "__WRONG_PASSWORD_CODE_JSON__", json.dumps(NET_WRONG_PASSWORD.code)
    ).replace(
        "__COUNTRIES_JSON__", json.dumps(COUNTRIES)
    ).replace(
        "__PAIR_NOT_ACCEPTING_CODE_JSON__", json.dumps(PAIR_NOT_ACCEPTING.code)
    ).replace(
        "__ELSEWHERE_CODES_JSON__", json.dumps([LINK_BUSY.code, LINK_TAKEN_OVER.code])
    ).replace(
        "__VERSION_MISMATCH_CODE_JSON__", json.dumps(LINK_VERSION_MISMATCH.code)
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
