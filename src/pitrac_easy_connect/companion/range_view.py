"""The practice range: what it looks like, and how it is drawn.

Kept apart from the rest of the window because it is a different kind of thing:
everything else here is a page, and this is a scene. ``page.py`` puts the three
pieces below into place.

Hand-written WebGL rather than a rendering library. The scene is turf, sky,
trees, a flag and a ball, which is not worth a dependency in a project that
otherwise ships only the standard library, and it has to work with no internet.

The page does no physics. Trajectories arrive from the companion already
computed and this draws them; the bounce after landing is dressing, scaled to
finish where the flight model says the ball stops.
"""

CSS = r"""
  /* Scoped to .on. An unscoped #pane-range beats .pane{display:none} on
     specificity, which left the range rendering underneath every other tab
     with its HUD and controls showing through. */
  #pane-range{padding:0}
  #pane-range.on{display:flex;height:100%;overflow:hidden}
  .rangewrap{position:relative;flex:1;min-width:0;min-height:0;background:#8fa9b8;overflow:hidden;
    user-select:none;-webkit-user-select:none}
  #rangeCanvas{display:block;width:100%;height:100%;outline:none;cursor:grab}
  #rangeCanvas:active{cursor:grabbing}
  #rangeCanvas:focus-visible{box-shadow:inset 0 0 0 2px var(--accent)}
  .rangeshade{position:absolute;inset:0;pointer-events:none;
    background:radial-gradient(ellipse at 50% 45%,transparent 55%,rgba(4,10,8,.34) 100%),
      linear-gradient(to top,rgba(4,10,8,.62),transparent 30%)}
  .rangefallback{position:absolute;inset:0;display:flex;align-items:center;
    justify-content:center;text-align:center;padding:28px;color:var(--muted);
    font-size:.9rem;line-height:1.6;background:#0a0f0d}

  /* One material for everything laid over the scene. */
  .glass{background:rgba(9,15,12,.62);border:1px solid rgba(255,255,255,.10);
    border-radius:16px;-webkit-backdrop-filter:blur(16px) saturate(1.2);
    backdrop-filter:blur(16px) saturate(1.2);box-shadow:0 10px 34px rgba(0,0,0,.28)}
  .rangewrap button,.statpanel button{font-family:inherit;cursor:pointer}
  .rangewrap button:focus-visible,.statpanel button:focus-visible{
    outline:2px solid var(--accent);outline-offset:2px}

  .rangelabels{position:absolute;inset:0;pointer-events:none;overflow:hidden}
  .rangelabel{position:absolute;transform:translate(-50%,-100%);white-space:nowrap;
    font-size:.66rem;font-weight:700;color:rgba(255,255,255,.82);
    text-shadow:0 1px 4px rgba(0,0,0,.75);font-variant-numeric:tabular-nums}
  .rangelabel.pin{padding:4px 9px;border-radius:999px;font-size:.78rem;font-weight:800;
    background:rgba(9,15,12,.72);color:#fff;text-shadow:none;border:1px solid rgba(255,255,255,.16)}

  .rangetop{position:absolute;top:14px;left:14px;right:14px;display:flex;
    justify-content:space-between;align-items:flex-start;gap:12px;pointer-events:none}
  .rangetop>*{pointer-events:auto}
  .targetbox{display:flex;align-items:center;gap:4px;padding:6px}
  .targetbox button{width:34px;height:34px;padding:0;border:0;border-radius:11px;
    background:rgba(255,255,255,.08);color:#fff;font-size:1.1rem;font-weight:600}
  .targetbox button:hover{background:rgba(255,255,255,.18)}
  .targetbox .now{width:auto;min-width:98px;height:34px;background:transparent;line-height:1.05}
  .targetbox .now b{display:block;font-size:1.12rem;font-weight:800;font-variant-numeric:tabular-nums}
  .targetbox .now span{display:block;font-size:.56rem;font-weight:800;letter-spacing:.13em;
    text-transform:uppercase;color:rgba(255,255,255,.62)}
  .targetmenu{position:absolute;top:56px;left:0;display:grid;grid-template-columns:repeat(4,1fr);
    gap:6px;padding:10px;z-index:6;background:rgba(9,15,12,.86)}
  .targetmenu button{width:60px;padding:9px 0;border:0;border-radius:10px;
    background:rgba(255,255,255,.08);color:#fff;font-size:.86rem;font-weight:700}
  .targetmenu button:hover{background:rgba(255,255,255,.18)}
  .targetmenu button.on{background:var(--accent);color:var(--accent-text)}

  .rangestate{display:flex;align-items:center;gap:9px;padding:10px 16px;border-radius:999px;
    font-size:.84rem;font-weight:700;color:#fff;max-width:44%}
  .rangestate i{flex:none;width:9px;height:9px;border-radius:50%;background:var(--faint)}
  .rangestate.ready i{background:var(--green);box-shadow:0 0 0 5px rgba(93,220,147,.20)}
  .rangestate.waiting i{background:var(--amber)}
  .rangestate.bad i{background:var(--red)}

  .views{position:relative;display:flex;gap:6px}
  .viewbtn{width:auto;background:rgba(9,15,12,.62);color:#fff;border:1px solid rgba(255,255,255,.10);
    border-radius:12px;padding:10px 13px;font-size:.8rem;font-weight:700;
    -webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px)}
  .viewbtn:hover{background:rgba(40,52,46,.85)}
  .viewbtn.on{background:var(--accent);color:var(--accent-text);border-color:transparent}
  .viewmenu{position:absolute;top:calc(100% + 8px);right:0;z-index:6;display:flex;
    flex-direction:column;gap:4px;padding:8px;min-width:170px}
  .viewmenu.hidden{display:none}
  .viewmenu .viewbtn{width:100%;text-align:left;background:transparent;border-color:transparent;
    -webkit-backdrop-filter:none;backdrop-filter:none}
  .viewmenu .viewbtn:hover{background:rgba(255,255,255,.12)}
  .viewmenu .viewbtn.on{background:var(--accent)}

  .rangebottom{position:absolute;left:14px;right:14px;bottom:14px;display:flex;
    align-items:flex-end;gap:12px;pointer-events:none}
  .rangebottom>*{pointer-events:auto}
  .clubcard{flex:none;display:flex;align-items:stretch;padding:6px}
  .clubcard button{margin:0;min-height:0;border:0;background:transparent;color:#fff;border-radius:11px}
  .clubcard button:hover{background:rgba(255,255,255,.12)}
  .clubcard button:disabled{opacity:.35;cursor:default;background:transparent}
  .clubcard .step{width:34px;padding:0;font-size:1.15rem;color:rgba(255,255,255,.75)}
  .clubcard .pick{width:auto;min-width:142px;padding:7px 10px;text-align:left}
  .clubcard .name{display:block;font-size:1.16rem;font-weight:800;line-height:1.15}
  .clubcard .about{display:block;font-size:.74rem;color:rgba(255,255,255,.68);
    font-variant-numeric:tabular-nums}
  .clubcard .auto{align-self:center;white-space:nowrap;width:auto;padding:6px 10px;margin:0 4px;font-size:.62rem;
    font-weight:800;letter-spacing:.1em;border:1px solid rgba(255,255,255,.24);border-radius:999px;
    color:rgba(255,255,255,.75)}
  .clubcard .auto.on{background:var(--accent);color:var(--accent-text);border-color:transparent}

  /* Whatever does not fit wraps out of sight, least important last. */
  .tiles{flex:1;min-width:0;display:flex;flex-wrap:wrap;justify-content:center;gap:0 1px;
    height:72px;padding:4px;overflow:hidden}
  .tile{flex:1 1 84px;max-width:128px;height:62px;padding:9px 6px;text-align:center;border-radius:12px}
  .tile b{display:block;font-size:1.06rem;font-weight:800;color:#fff;line-height:1.2;
    font-variant-numeric:tabular-nums;white-space:nowrap}
  .tile b small{font-size:.62em;font-weight:700;color:rgba(255,255,255,.62);margin-left:2px}
  .tile span{display:block;margin-top:2px;font-size:.56rem;font-weight:800;letter-spacing:.09em;
    text-transform:uppercase;color:rgba(255,255,255,.58);white-space:nowrap}
  .tile.lead{flex-basis:104px;max-width:150px;background:rgba(223,248,109,.13)}
  .tile.lead .count{font-size:1.62rem;line-height:1.1;color:var(--accent)}
  .tilenote{align-self:center;padding:10px 14px;color:rgba(255,255,255,.72);font-size:.84rem}

  .sheet{position:absolute;left:14px;bottom:96px;width:min(560px,calc(100% - 28px));
    padding:16px;z-index:7;max-height:calc(100% - 172px);overflow:auto;background:rgba(9,15,12,.86)}
  .sheet h4{margin:0 0 4px;font-size:.95rem;color:#fff}
  .sheet p{margin:0 0 12px;font-size:.78rem;line-height:1.45;color:rgba(255,255,255,.66)}
  .clubgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
  .clubgrid button{padding:8px 11px;border:1px solid transparent;border-radius:12px;text-align:left;
    background:rgba(255,255,255,.07);color:#fff;width:auto}
  .clubgrid button:hover{background:rgba(255,255,255,.16)}
  .clubgrid button.on{background:var(--accent);color:var(--accent-text)}
  .clubgrid button.out{opacity:.38}
  .clubgrid b{display:block;font-size:.84rem;font-weight:750}
  .clubgrid span{font-size:.72rem;opacity:.72;font-variant-numeric:tabular-nums}
  .sheetfoot{display:flex;justify-content:space-between;gap:8px;margin-top:12px}
  .sheetfoot button{width:auto;padding:9px 13px;border-radius:11px;font-size:.78rem;font-weight:700;
    color:#fff;background:rgba(255,255,255,.08);border:0}
  .sheetfoot button:hover{background:rgba(255,255,255,.18)}

  .statpanel{flex:none;width:338px;height:100%;overflow-y:auto;background:var(--bg);
    border-left:1px solid var(--line-soft);padding:16px}
  .statpanel.hidden{display:none}
  .statpanel h4{margin:20px 0 8px;font-size:.66rem;font-weight:800;letter-spacing:.12em;
    text-transform:uppercase;color:var(--faint)}
  .statpanel h4:first-child{margin-top:0}
  .stathead{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .stathead div{background:var(--panel);border-radius:12px;padding:10px}
  .stathead b{display:block;font-size:1.15rem;font-weight:800;color:var(--text);
    font-variant-numeric:tabular-nums}
  .stathead span{font-size:.68rem;color:var(--muted)}
  #rangePlot{display:block;width:100%;height:210px;border-radius:12px;background:#16241b}
  .statrow{display:grid;grid-template-columns:1fr 54px 54px 60px;gap:6px;padding:8px 0;
    border-bottom:1px solid var(--line-soft);font-size:.8rem;align-items:baseline}
  .statrow.head{font-size:.62rem;font-weight:700;color:var(--faint)}
  .statrow b{font-weight:700;color:var(--text)}
  .statrow span{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
  .statfoot{display:flex;gap:8px;align-items:center;margin-top:16px}
  .statfoot button{width:auto;padding:9px 13px;border-radius:11px;font-size:.78rem;font-weight:700;
    background:var(--panel);color:var(--text);border:1px solid var(--line)}
  .statfoot .rangecount{margin-left:auto;font-size:.76rem;color:var(--muted)}
  body.immersive .tabs{display:none}
  @media (prefers-reduced-motion:reduce){.viewbtn{transition:none}}
"""

MARKUP = r"""
<div class="pane" id="pane-range">
  <div class="rangewrap" id="rangeWrap">
    <canvas id="rangeCanvas" tabindex="0"
      aria-label="Practice range. Shots are drawn as they are measured."></canvas>
    <div class="rangeshade"></div>
    <div class="rangelabels" id="rangeLabels" aria-hidden="true"></div>
    <div class="rangefallback hidden" id="rangeFallback"></div>

    <div class="rangetop">
      <div style="position:relative" id="targetArea">
        <div class="targetbox glass">
          <button id="targetLess" aria-label="Target 5 yards nearer" title="Nearer (down arrow)">&minus;</button>
          <button class="now" id="targetNow" aria-haspopup="true" aria-expanded="false"
            title="Choose a distance"><b id="targetYards">150 yd</b><span>Target</span></button>
          <button id="targetMore" aria-label="Target 5 yards farther" title="Farther (up arrow)">+</button>
        </div>
        <div class="targetmenu glass hidden" id="targetMenu"></div>
      </div>

      <div class="rangestate glass" id="rangeState" role="status"><i></i><span id="rangeStateText"></span></div>

      <div class="views">
        <button class="viewbtn" id="viewToggle" aria-expanded="false" title="Camera (V)"
          aria-haspopup="true" aria-controls="viewMenu">View</button>
        <button class="viewbtn" id="statToggle" aria-pressed="false" title="Stats (S)">Stats</button>
        <button class="viewbtn" id="fullToggle" aria-pressed="false" title="Full screen (F)">Full screen</button>
        <div class="viewmenu glass hidden" id="viewMenu" role="menu" aria-label="Camera">
          <button class="viewbtn on" data-view="first" role="menuitem">First person</button>
          <button class="viewbtn" data-view="chase" role="menuitem">Follow the ball</button>
          <button class="viewbtn" data-view="behind" role="menuitem">From behind</button>
          <button class="viewbtn" data-view="top" role="menuitem">Top down</button>
        </div>
      </div>
    </div>

    <div class="sheet glass hidden" id="clubSheet" role="dialog" aria-label="Choose a club">
      <h4 id="clubSheetTitle">Choose a club</h4>
      <p id="clubSheetNote"></p>
      <div class="clubgrid" id="clubGrid"></div>
      <div class="sheetfoot">
        <button id="bagEdit">Edit my bag</button>
        <button id="clubClose">Done</button>
      </div>
    </div>

    <div class="rangebottom">
      <div class="clubcard glass" id="clubCard">
        <button class="step" id="clubLonger" aria-label="Longer club" title="Longer club (left arrow)">&lsaquo;</button>
        <button class="pick" id="clubPick" aria-haspopup="dialog" title="Choose a club (C)">
          <span class="name" id="clubName">Club</span><span class="about" id="clubAbout"></span></button>
        <button class="auto" id="clubAuto" aria-pressed="false" title="Choose the club from the target distance (A)">AUTO</button>
        <button class="step" id="clubShorter" aria-label="Shorter club" title="Shorter club (right arrow)">&rsaquo;</button>
      </div>
      <div class="tiles glass" id="rangeTiles" aria-live="polite"></div>
    </div>
  </div>

  <aside class="statpanel hidden" id="statPanel" aria-label="Session statistics">
    <h4>This session</h4>
    <div class="stathead" id="statHead"></div>
    <h4 id="plotTitle">Where they finished</h4>
    <canvas id="rangePlot"></canvas>
    <h4>By club</h4>
    <div id="rangeClubs"></div>
    <h4>Shots</h4>
    <div id="rangeShots"></div>
    <div class="statfoot">
      <button id="rangeClear">Clear session</button>
      <button id="rangeDemo">Demo shot</button>
      <span class="rangecount" id="rangeCount"></span>
    </div>
  </aside>
</div>
"""

SCRIPT = r"""
// --- the practice range: the scene ---------------------------------------

const YARD = 0.9144;
const RANGE = (function(){
  let gl=null, canvas=null, programs=null, raf=null, lost=false;
  let meshes={}, dynamic={}, skyBuffer=null, lastViewProj=null, sceneKey="";
  let shots=[], markers=[], target=150, scoring=11;
  // Kept in one place: the declaration and setView must not drift apart, or
  // the range opens on a camera no button can reproduce.
  const VIEWS = {
    first:  {yaw:0.0,  pitch:0.0,  dist:1},
    chase:  {yaw:0.0,  pitch:0.0,  dist:1},
    behind: {yaw:0.50, pitch:0.26, dist:150},
    top:    {yaw:0.0,  pitch:0.0,  dist:1},
  };
  // Where the player stands, over the ball. That is what a simulator is.
  let view="first", orbit=Object.assign({}, VIEWS.first), drag=null;
  let animation=null, lastFrame=0, clock=0, lastIdle=0;
  // Where the camera is and what it is looking at, eased towards where it
  // should be, so following a ball is a head turning rather than a cut.
  let rig=null;
  let onFlight=null, primed=false;

  const reduced = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const EYE = 2.05, BACK = 4.7;            // standing just behind the ball
  const FAIRWAY = 21, TREELINE = 64;       // metres either side of the middle

  // Scenery greens, off to the sides so the one being played to is never
  // confused with them: [across, yards out, radius].
  const SIDE_GREENS = [[-39,78,8],[43,112,8.5],[-46,168,9.5],[45,208,9.5],[-37,252,10]];

  // --- shaders ----------------------------------------------------------

  const SUN = [-0.46, 0.62, 0.52];         // direction toward the sun: left, ahead
  const HAZE = [0.600, 0.690, 0.705];
  const NOISE = `
    float hash(vec2 p){ p = fract(p*vec2(123.34, 456.21)); p += dot(p, p+45.32); return fract(p.x*p.y); }
    float noise(vec2 p){
      vec2 i = floor(p), f = fract(p);
      vec2 u = f*f*(3.0-2.0*f);
      return mix(mix(hash(i), hash(i+vec2(1,0)), u.x),
                 mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), u.x), u.y);
    }
    float fbm(vec2 p){
      float v = 0.0, a = 0.5;
      for(int i=0;i<4;i++){ v += a*noise(p); p = p*2.03 + 17.1; a *= 0.5; }
      return v;
    }`;

  // A full-screen triangle, coloured by the direction each pixel looks in:
  // sky, sun, drifting cloud, and two lines of hills along the horizon.
  const SKY_VERT = `#version 300 es
    in vec2 aClip;
    uniform mat4 uInverseViewProj;
    out vec3 vRay;
    void main(){
      gl_Position = vec4(aClip, 1.0, 1.0);
      vec4 near = uInverseViewProj * vec4(aClip, -1.0, 1.0);
      vec4 far  = uInverseViewProj * vec4(aClip,  1.0, 1.0);
      // Not normalised here: it has to change evenly across the triangle, or
      // the horizon comes out tilted.
      vRay = far.xyz/far.w - near.xyz/near.w;
    }`;
  const SKY_FRAG = `#version 300 es
    precision highp float;
    in vec3 vRay;
    uniform vec3 uSun, uHaze;
    uniform float uTime;
    out vec4 outColor;
    ${NOISE}
    float ridge(float a, float scale, float height, float seed){
      return height * (0.35 + fbm(vec2(a*scale+seed, seed)) * 1.1);
    }
    void main(){
      vec3 ray = normalize(vRay), sun = normalize(uSun);
      float up = clamp(ray.y, 0.0, 1.0);
      vec3 sky = mix(vec3(0.760,0.840,0.885), vec3(0.205,0.425,0.690), pow(up, 0.52));
      float toSun = max(dot(ray, sun), 0.0);
      sky += vec3(1.0,0.86,0.62) * pow(toSun, 6.0) * 0.16;
      sky += vec3(1.0,0.95,0.84) * pow(toSun, 900.0) * 1.4;
      if(ray.y > 0.015){
        vec2 p = ray.xz / (ray.y + 0.10) * 1.15 + vec2(uTime*0.006, uTime*0.002);
        float cover = smoothstep(0.50, 0.82, fbm(p));
        float lit = fbm(p + sun.xz*0.22);
        vec3 cloud = mix(vec3(0.99,0.985,0.97), vec3(0.74,0.79,0.84), smoothstep(0.35,0.80,lit));
        sky = mix(sky, cloud, cover * smoothstep(0.015, 0.17, ray.y) * 0.90);
      }
      float a = atan(ray.x, ray.z);
      float far  = ridge(a, 11.0, 0.072, 3.1);
      float near = ridge(a, 21.0, 0.040, 8.7);
      sky = mix(sky, vec3(0.520,0.630,0.690), 1.0 - smoothstep(far-0.0025, far+0.0025, ray.y));
      sky = mix(sky, mix(vec3(0.330,0.455,0.375), vec3(0.430,0.545,0.470), fbm(vec2(a*60.0, ray.y*220.0))),
                1.0 - smoothstep(near-0.002, near+0.002, ray.y));
      sky = mix(uHaze, sky, smoothstep(-0.010, 0.002, ray.y));
      outColor = vec4(sky, 1.0);
    }`;

  // Turf. Everything on it, tee, fairway, greens and sand, is painted here by
  // position, so edges stay crisp at any distance and nothing fights for depth.
  const GROUND_VERT = `#version 300 es
    in vec3 aPos;
    uniform mat4 uViewProj;
    out vec3 vWorld;
    void main(){ vWorld = aPos; gl_Position = uViewProj * vec4(aPos, 1.0); }`;
  const GROUND_FRAG = `#version 300 es
    precision highp float;
    in vec3 vWorld;
    uniform vec3 uSun, uEye, uHaze;
    uniform vec3 uGreens[6];
    uniform float uTime, uFairway, uScoring;
    out vec4 outColor;
    ${NOISE}
    float blob(vec2 p, vec2 c, float r){
      vec2 d = p - c;
      float wobble = (noise(vec2(atan(d.y,d.x)*1.6, r)) - 0.5) * r * 0.16;
      return length(d) - r - wobble;
    }
    void main(){
      vec2 p = vWorld.xz;
      float away = length(vWorld - uEye);
      // Fine grain only where a pixel can hold it. Past that it is noise.
      float fine = 1.0 - smoothstep(6.0, 60.0, away);
      float grain = fbm(p*0.55)*0.6 + noise(p*5.0)*0.25*fine + noise(p*24.0)*0.35*fine;
      float broad = fbm(p*0.035);

      vec3 rough = mix(vec3(0.150,0.255,0.110), vec3(0.285,0.385,0.165), grain*0.75 + broad*0.35);
      float edge = uFairway + (fbm(vec2(p.y*0.018, sign(p.x)*7.0)) - 0.5) * 13.0;
      float lane = abs(p.x);
      float cut = 1.0 - smoothstep(edge-0.35, edge+0.35, lane);
      float first = 1.0 - smoothstep(edge+3.2, edge+3.8, lane);
      float within = smoothstep(9.0, 16.0, p.y) * (1.0 - smoothstep(318.0, 324.0, p.y));
      cut *= within; first *= within;

      // Mown in crossing bands, which is why a fairway shows light and dark.
      float across = step(0.5, fract(p.x/9.2 + 0.25)), along = step(0.5, fract(p.y/18.4));
      float stripe = 1.0 + (abs(across-along) - 0.5) * 0.13;
      vec3 fair = mix(vec3(0.215,0.400,0.165), vec3(0.300,0.490,0.210), grain*0.55 + broad*0.45) * stripe;
      vec3 base = mix(rough, mix(rough, fair, 0.55), first);
      base = mix(base, fair, cut);

      // The tee: a tight, level box under the player's feet.
      float tee = (1.0 - smoothstep(4.1, 4.25, lane)) * smoothstep(-5.2, -5.05, p.y)
                * (1.0 - smoothstep(4.6, 4.75, p.y));
      vec3 teeTurf = mix(vec3(0.250,0.440,0.190), vec3(0.315,0.510,0.225), grain)
                   * (1.0 + (step(0.5, fract(p.x/1.4)) - 0.5) * 0.10);
      base = mix(base, teeTurf, tee);

      float sandy = 0.0, shadow = 0.0;
      for(int i=0;i<6;i++){
        vec3 g = uGreens[i];
        if(g.z <= 0.0) continue;
        float d = blob(p, g.xy, g.z);
        float apron = 1.0 - smoothstep(2.4, 2.9, d);
        float green = 1.0 - smoothstep(-0.18, 0.18, d);
        base = mix(base, fair*1.06, apron*0.8);
        vec3 putting = mix(vec3(0.300,0.530,0.235), vec3(0.365,0.600,0.275), grain*0.5+0.25)
                     * (1.0 + (step(0.5, fract((p.x+p.y)/3.2)) - 0.5) * 0.06);
        base = mix(base, putting, green);
        // The one being played to is ringed, where "on the green" is counted.
        if(i==0){
          float ring = abs(length(p - g.xy) - uScoring);
          base = mix(base, vec3(0.94,1.0,0.62), (1.0 - smoothstep(0.10, 0.10 + away*0.0035, ring)) * 0.75);
        }
        float b1 = blob(p, g.xy + vec2(-g.z*1.42, -g.z*0.35), g.z*0.44);
        float b2 = blob(p, g.xy + vec2( g.z*1.36,  g.z*0.30), g.z*0.50);
        float s = min(b1, b2);
        sandy = max(sandy, 1.0 - smoothstep(-0.12, 0.12, s));
        shadow = max(shadow, (1.0 - smoothstep(0.0, 0.7, abs(s+0.35))) * step(s, 0.1));
      }
      vec3 sand = mix(vec3(0.80,0.735,0.58), vec3(0.885,0.83,0.69), noise(p*3.0)*0.6+grain*0.4);
      base = mix(base, sand * (1.0 - shadow*0.22), sandy);

      // Under the trees it is darker and browner.
      float wood = max(smoothstep(58.0, 76.0, lane + (broad-0.5)*16.0), smoothstep(336.0, 352.0, p.y));
      base = mix(base, vec3(0.125,0.175,0.085)*(0.7+grain*0.6), wood*0.85);

      vec3 jitter = normalize(vec3((fbm(p*0.9)-0.5)*0.55, 1.0, (fbm(p*0.9+31.0)-0.5)*0.55));
      float sun = max(dot(jitter, normalize(uSun)), 0.0);
      float cloud = smoothstep(0.42, 0.72, fbm(p*0.006 + vec2(uTime*0.004, 0.0)));
      vec3 lit = base * (vec3(0.50,0.56,0.62) + vec3(1.12,1.04,0.86) * sun * (1.0 - cloud*0.36));

      lit = mix(lit, uHaze, pow(clamp(away/900.0, 0.0, 1.0), 1.6) * 0.80);
      outColor = vec4(lit, 1.0);
    }`;

  // Lit solid things: trees, flag, posts, tee, ball.
  const SOLID_VERT = `#version 300 es
    in vec3 aPos; in vec3 aNormal; in vec3 aColor;
    uniform mat4 uViewProj;
    uniform vec3 uOffset; uniform float uScale;
    out vec3 vNormal; out vec3 vColor; out vec3 vWorld;
    void main(){
      vNormal = aNormal; vColor = aColor; vWorld = aPos*uScale + uOffset;
      gl_Position = uViewProj * vec4(vWorld, 1.0);
    }`;
  const SOLID_FRAG = `#version 300 es
    precision highp float;
    in vec3 vNormal; in vec3 vColor; in vec3 vWorld;
    uniform vec3 uSun, uEye, uHaze;
    uniform float uAlpha, uGloss;
    out vec4 outColor;
    void main(){
      vec3 n = normalize(vNormal), toSun = normalize(uSun);
      float sun = max(dot(n, toSun), 0.0);
      float sky = 0.5 + 0.5*n.y;
      vec3 toEye = normalize(uEye - vWorld);
      float spec = pow(max(dot(reflect(-toSun, n), toEye), 0.0), 36.0) * uGloss;
      // Light also comes through and around a thing with the sun behind it.
      float through = max(dot(-toEye, toSun), 0.0) * 0.22;
      vec3 lit = vColor * (mix(vec3(0.50,0.52,0.48), vec3(0.74,0.79,0.84), sky)
               + vec3(1.02,0.93,0.74)*sun + vec3(0.9,0.85,0.5)*through + uGloss*0.28)
               + vec3(1.0,0.97,0.90)*spec;
      float away = clamp(length(vWorld - uEye)/760.0, 0.0, 1.0);
      outColor = vec4(mix(lit, uHaze, pow(away, 1.5)*0.82), uAlpha);
    }`;

  // Tracers: a ribbon that always faces the camera, soft at its edges.
  const RIBBON_VERT = `#version 300 es
    in vec3 aPos; in float aSide; in float aAge;
    uniform mat4 uViewProj;
    out float vSide; out float vAge;
    void main(){ vSide = aSide; vAge = aAge; gl_Position = uViewProj * vec4(aPos, 1.0); }`;
  const RIBBON_FRAG = `#version 300 es
    precision highp float;
    in float vSide; in float vAge;
    uniform vec3 uColor; uniform float uAlpha;
    out vec4 outColor;
    void main(){
      float across = 1.0 - abs(vSide);
      float core = smoothstep(0.35, 0.75, across), glow = across*across*0.45;
      outColor = vec4(mix(uColor, vec3(1.0), core*0.35),
                      (core + glow) * uAlpha * smoothstep(0.0, 0.06, vAge));
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
    const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for(let i=0;i<n;i++){
      const name = gl.getActiveUniform(prog, i).name;
      record.uniform[name] = gl.getUniformLocation(prog, name);
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
  const add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]];
  const scale=(a,k)=>[a[0]*k,a[1]*k,a[2]*k];
  const mix=(a,b,k)=>[a[0]+(b[0]-a[0])*k,a[1]+(b[1]-a[1])*k,a[2]+(b[2]-a[2])*k];
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
  function norm(v){ const l=Math.hypot(v[0],v[1],v[2])||1; return [v[0]/l,v[1]/l,v[2]/l]; }
  function invert(m){
    // The sky turns corners of the screen back into directions, which needs
    // the whole inverse. Gauss-Jordan: eight lines instead of sixteen formulae.
    const a=[];
    for(let r=0;r<4;r++){ a.push([]);
      for(let c=0;c<4;c++) a[r].push(m[c*4+r]);
      for(let c=0;c<4;c++) a[r].push(c===r?1:0); }
    for(let c=0;c<4;c++){
      let best=c; for(let r=c+1;r<4;r++) if(Math.abs(a[r][c])>Math.abs(a[best][c])) best=r;
      const t=a[c]; a[c]=a[best]; a[best]=t;
      const k=a[c][c]||1e-12; for(let j=0;j<8;j++) a[c][j]/=k;
      for(let r=0;r<4;r++) if(r!==c){ const f=a[r][c]; for(let j=0;j<8;j++) a[r][j]-=f*a[c][j]; }
    }
    const o=new Array(16);
    for(let r=0;r<4;r++) for(let c=0;c<4;c++) o[c*4+r]=a[r][4+c];
    return o;
  }

  // --- geometry ---------------------------------------------------------

  function shape(){ return {pos:[], normal:[], color:[]}; }
  function corner(out, v, n, c){
    out.pos.push(v[0],v[1],v[2]); out.normal.push(n[0],n[1],n[2]); out.color.push(c[0],c[1],c[2]);
  }
  function mesh(parts){
    return {pos:new Float32Array(parts.pos),
      normal: parts.normal ? new Float32Array(parts.normal) : null,
      color: parts.color ? new Float32Array(parts.color) : null, count: parts.pos.length/3};
  }
  function release(m){
    // The scene is rebuilt whenever the flag moves. Dropping the last one
    // without this leaked a set of buffers every time.
    if(m && m.buffers) Object.keys(m.buffers).forEach(k=>gl.deleteBuffer(m.buffers[k]));
  }

  function sphere(out, centre, radius, colour, rings, segments, squash){
    const at=(phi,theta)=>[Math.sin(phi)*Math.cos(theta), Math.cos(phi), Math.sin(phi)*Math.sin(theta)];
    for(let r=0;r<rings;r++) for(let s=0;s<segments;s++){
      const p0=Math.PI*r/rings, p1=Math.PI*(r+1)/rings;
      const t0=2*Math.PI*s/segments, t1=2*Math.PI*(s+1)/segments;
      const a=at(p0,t0), b=at(p1,t0), c=at(p1,t1), d=at(p0,t1);
      [a,b,c,a,c,d].forEach(n=>{
        // Darker underneath: cheap, and most of what makes foliage look solid.
        const shade = squash ? 0.72 + 0.28*(n[1]*0.5+0.5) : 1;
        corner(out, [centre[0]+n[0]*radius, centre[1]+n[1]*radius*(squash||1), centre[2]+n[2]*radius],
               n, scale(colour, shade));
      });
    }
  }

  function cone(out, base, radius, height, colour, sides, turn){
    for(let i=0;i<sides;i++){
      const a0=turn+2*Math.PI*i/sides, a1=turn+2*Math.PI*(i+1)/sides, am=(a0+a1)/2;
      const slope=radius/height, n=norm([Math.cos(am), slope, Math.sin(am)]);
      corner(out, [base[0]+Math.cos(a0)*radius, base[1], base[2]+Math.sin(a0)*radius], n, scale(colour,0.70));
      corner(out, [base[0], base[1]+height, base[2]], n, scale(colour,1.16));
      corner(out, [base[0]+Math.cos(a1)*radius, base[1], base[2]+Math.sin(a1)*radius], n, scale(colour,0.70));
    }
  }

  function box(out, x0,y0,z0, x1,y1,z1, colour){
    const face=(a,b,c,d,n)=>[a,b,c,a,c,d].forEach(v=>corner(out, v, n, colour));
    face([x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1],[0,0,1]);
    face([x1,y0,z0],[x0,y0,z0],[x0,y1,z0],[x1,y1,z0],[0,0,-1]);
    face([x1,y0,z1],[x1,y0,z0],[x1,y1,z0],[x1,y1,z1],[1,0,0]);
    face([x0,y0,z0],[x0,y0,z1],[x0,y1,z1],[x0,y1,z0],[-1,0,0]);
    face([x0,y1,z1],[x1,y1,z1],[x1,y1,z0],[x0,y1,z0],[0,1,0]);
  }

  function groundMesh(){
    // One large quad. All the detail is in the fragment shader.
    const far=1250, side=950, back=130;
    return mesh({pos:[-side,0,-back, side,0,-back, side,0,far, -side,0,-back, side,0,far, -side,0,far]});
  }

  function woodland(){
    // The same trees every time: a range that rearranges itself is unsettling.
    let seed=20261; const random=()=>{ seed=(seed*16807)%2147483647; return seed/2147483647; };
    const out=shape();
    const plant=function(x,z,size){
      const tint=1.05+random()*0.45;
      // Undergrowth, so there is no daylight beneath the branches.
      sphere(out,[x,size*0.5,z],size*(2.1+random()*0.9),scale([0.125,0.205,0.095],tint),3,6,0.62);
      if(random()<0.45){
        const leaf=scale([0.135,0.255,0.135], tint), h=size*(8.5+random()*6);
        cone(out,[x,h*0.10,z],h*0.23,h*0.50,leaf,7,random()*3);
        cone(out,[x,h*0.36,z],h*0.185,h*0.42,scale(leaf,1.06),7,random()*3);
        cone(out,[x,h*0.62,z],h*0.125,h*0.38,scale(leaf,1.12),7,random()*3);
      }else{
        const warm=random(), leaf=scale([0.205+warm*0.075,0.325,0.120], tint), h=size*(5.5+random()*4.5);
        box(out,x-0.25,0,z-0.25,x+0.25,h*0.5,z+0.25,[0.235,0.175,0.125]);
        sphere(out,[x,h*0.68,z],h*0.36,leaf,5,7,0.92);
        sphere(out,[x-h*0.21,h*0.55,z+h*0.07],h*0.25,scale(leaf,0.92),4,6,0.92);
        sphere(out,[x+h*0.20,h*0.57,z-h*0.08],h*0.26,scale(leaf,1.06),4,6,0.92);
      }
    };
    for(let z=-18; z<390; z+=5.6) [-1,1].forEach(function(side){
      plant(side*(TREELINE+4+random()*9), z+random()*5, 0.95+random()*0.35);
      if(random()<0.75) plant(side*(TREELINE+16+random()*18), z+random()*6, 1.15+random()*0.5);
      if(random()<0.35) plant(side*(TREELINE+38+random()*40), z+random()*6, 1.4+random()*0.5);
    });
    for(let x=-150; x<150; x+=6.2){
      plant(x+random()*4, 352+random()*16, 1.15+random()*0.4);
      plant(x+random()*5, 376+random()*28, 1.5+random()*0.5);
    }
    return mesh(out);
  }

  function greens(){
    const list=[[0, target*YARD, 10]];
    SIDE_GREENS.forEach(g=>list.push([g[0], g[1]*YARD, g[2]]));
    return list;
  }

  function furnitureMesh(){
    const out=shape();
    greens().forEach(function(g, index){
      const x=g[0], z=g[1], main=index===0;
      // Taller than a real one, or it would be four pixels high.
      const h=main ? 3.4 : 2.3, w=main ? 1.45 : 0.9;
      const flag=main ? [0.90,0.20,0.16] : [0.93,0.92,0.86];
      box(out, x-0.04,0,z-0.04, x+0.04,h,z+0.04, [0.93,0.93,0.90]);
      box(out, x-w,h-0.86*w,z-0.02, x-0.04,h,z+0.02, flag);
    });
    markers.forEach(function(yards){
      [-1,1].forEach(function(side){
        const x=side*(FAIRWAY+11), z=yards*YARD;
        box(out, x-0.07,0,z-0.07, x+0.07,1.05,z+0.07, [0.36,0.29,0.22]);
        box(out, x-0.95,0.85,z-0.05, x+0.95,1.75,z+0.05, [0.94,0.94,0.91]);
      });
    });
    // Tee markers either side of the player, and the peg.
    [-2.6,2.6].forEach(x=>sphere(out,[x,0.07,0.4],0.075,[0.87,0.965,0.43],8,10));
    box(out,-0.006,0,-0.006,0.006,0.035,0.006,[0.86,0.78,0.60]);
    return mesh(out);
  }

  function shadowMesh(){
    const out=shape(), steps=26;
    for(let i=0;i<steps;i++){
      const a0=2*Math.PI*i/steps, a1=2*Math.PI*(i+1)/steps;
      [[0,0,0],[Math.cos(a0),0,Math.sin(a0)],[Math.cos(a1),0,Math.sin(a1)]].forEach(
        v=>corner(out, v, [0,1,0], [0.01,0.02,0.01]));
    }
    return mesh(out);
  }

  function build(){
    programs = {
      sky:    link(SKY_VERT, SKY_FRAG, ["aClip"]),
      ground: link(GROUND_VERT, GROUND_FRAG, ["aPos"]),
      solid:  link(SOLID_VERT, SOLID_FRAG, ["aPos", "aNormal", "aColor"]),
      ribbon: link(RIBBON_VERT, RIBBON_FRAG, ["aPos", "aSide", "aAge"]),
    };
    gl.bindVertexArray(gl.createVertexArray());
    // One oversized triangle covering the screen, for the sky.
    skyBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, skyBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
    dynamic = {};
    const ball=shape(); sphere(ball,[0,0,0],1,[0.975,0.975,0.955],14,20);
    meshes = {ground: groundMesh(), trees: woodland(), furniture: furnitureMesh(),
              ball: mesh(ball), shadow: shadowMesh()};
    sceneKey = target+"|"+markers.join(",");
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.clearColor(HAZE[0], HAZE[1], HAZE[2], 1);
  }

  function rebuildScenery(){
    // Only when something in it moved. This is asked several times a second.
    const key = target+"|"+markers.join(",");
    if(!gl || !programs || key===sceneKey) return;
    sceneKey = key;
    release(meshes.furniture);
    meshes.furniture = furnitureMesh();
  }

  // Where a point of a flight is drawn. Flights are [downrange, up, right];
  // the scene is [x, up, downrange], and with the camera looking downrange its
  // +x is on the LEFT. Without this every slice was drawn as a hook, while the
  // numbers beside it said the opposite.
  function place(point){ return [-point[2], point[1], point[0]]; }

  // After it lands: a few dying hops out to where the flight model says the
  // ball stops. Only the finishing place is claimed to be right.
  function runOut(shot){
    const pts=shot.points, last=pts[pts.length-1];
    const roll=Math.max(0, (shot.totalYards-shot.carryYards)*YARD);
    if(roll<0.4) return [];
    const heading=Math.atan2(last[2], last[0]||1e-9), out=[], steps=46, hops=3;
    const high=Math.min(1.9, 0.22+roll*0.10);
    for(let i=1;i<=steps;i++){
      const t=i/steps, gone=roll*(1-Math.pow(1-t,1.9)), along=t*hops*1.35;
      const hop=along<hops ? Math.abs(Math.sin(along*Math.PI))*high*Math.pow(0.36,Math.floor(along)) : 0;
      out.push([last[0]+Math.cos(heading)*gone, hop, last[2]+Math.sin(heading)*gone]);
    }
    return out;
  }

  // --- the camera -------------------------------------------------------

  function rest(){
    // Standing over the ball, looking out at the flag.
    const flag=[0, 1.1, target*YARD];
    const turn=orbit.yaw, tilt=orbit.pitch;
    const eye=[0, EYE, -BACK], reach=target*YARD+BACK;
    return {eye:eye, fov:(view==="first" ? 48 : 50)*Math.PI/180/orbit.dist,
      at:[eye[0]+Math.sin(turn)*reach, flag[1]+reach*(tilt-0.112), eye[2]+Math.cos(turn)*reach]};
  }

  function wanted(ballAt, heading){
    if(view==="top"){
      const mid=Math.max(95, target*0.62*YARD);
      return {eye:[0, 470*Math.max(0.55, mid/140), mid], at:[0,0,mid], up:[0,0,1], fov:Math.PI/7, cut:true};
    }
    if(view==="behind"){
      const focus=[0, 11, Math.max(60, target*0.55*YARD)], flat=orbit.dist*Math.cos(orbit.pitch);
      return {eye:[focus[0]+Math.sin(orbit.yaw)*flat, focus[1]+orbit.dist*Math.sin(orbit.pitch),
                   focus[2]-Math.cos(orbit.yaw)*flat], at:focus, fov:Math.PI/4, cut:true};
    }
    const still=rest();
    if(!ballAt) return still;
    if(view==="chase"){
      const back=scale(heading, -11);
      const eye=add(ballAt, [back[0], 3.4, back[2]]);
      eye[1]=Math.max(1.5, eye[1]);
      return {eye:eye, at:add(ballAt, scale(heading, 7)), fov:52*Math.PI/180, quick:true};
    }
    // First person: the player stays put and watches it go, as a lens would,
    // closing in as it gets smaller.
    const off=Math.hypot(ballAt[0]-still.eye[0], ballAt[1]-still.eye[1], ballAt[2]-still.eye[2]);
    const close=48-28*Math.min(1, Math.max(0, off-20)/120), lens=close*Math.PI/180;
    // Held a little above the middle, so there is ground to land on and the
    // numbers along the bottom are never in front of it.
    const aim=[ballAt[0], ballAt[1]-off*Math.tan(lens/2)*0.30, ballAt[2]];
    return {eye:still.eye, at:mix(still.at, aim, Math.min(1, off/14)), fov:lens/orbit.dist};
  }

  function camera(aspect, dt){
    const ball=animation ? animation.ballAt : null;
    const want=wanted(ball, animation ? animation.heading : null);
    const up=want.up||[0,1,0];
    if(!rig || want.cut || rig.view!==view || reduced) rig={eye:want.eye, at:want.at, fov:want.fov};
    else{
      const k=1-Math.exp(-dt*(want.quick ? 7.5 : ball ? 5.5 : 2.6));
      rig.eye=mix(rig.eye, want.eye, k); rig.at=mix(rig.at, want.at, k);
      rig.fov+=(want.fov-rig.fov)*(1-Math.exp(-dt*(ball ? 1.5 : 2.2)));
    }
    rig.view=view;
    // Narrow windows see less to either side, so open the lens to compensate.
    const fov=rig.fov*(aspect<1.5 && view!=="top" ? Math.min(1.35, 1.5/aspect) : 1);
    const matrix=multiply(perspective(fov, aspect, 0.08, 2600), lookAt(rig.eye, rig.at, up));
    lastViewProj=matrix;
    return {matrix:matrix, eye:rig.eye, inverse:invert(matrix)};
  }

  function settled(){
    if(!rig || animation) return false;
    const want=wanted(null,null);
    return Math.abs(rig.fov-want.fov)<0.002
      && Math.hypot.apply(null, sub(rig.at,want.at))<0.4 && Math.hypot.apply(null, sub(rig.eye,want.eye))<0.05;
  }

  // --- drawing ----------------------------------------------------------

  function attach(location, buffer, size){
    if(location===undefined || location<0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
  }
  function bindMesh(program, m){
    if(!m.buffers){
      m.buffers={};
      ["pos","normal","color"].forEach(function(key){
        if(!m[key]) return;
        m.buffers[key]=gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, m.buffers[key]);
        gl.bufferData(gl.ARRAY_BUFFER, m[key], gl.STATIC_DRAW);
      });
    }
    attach(program.attrib.aPos, m.buffers.pos, 3);
    if(m.buffers.normal) attach(program.attrib.aNormal, m.buffers.normal, 3);
    if(m.buffers.color) attach(program.attrib.aColor, m.buffers.color, 3);
  }
  function use(program, at){
    gl.useProgram(program.prog);
    const u=program.uniform;
    if(u.uViewProj) gl.uniformMatrix4fv(u.uViewProj, false, new Float32Array(at.matrix));
    if(u.uSun) gl.uniform3fv(u.uSun, SUN);
    if(u.uHaze) gl.uniform3fv(u.uHaze, HAZE);
    if(u.uEye) gl.uniform3fv(u.uEye, at.eye);
    if(u.uTime) gl.uniform1f(u.uTime, clock);
    return u;
  }
  function solid(m, offset, size, alpha, gloss){
    const p=programs.solid;
    bindMesh(p, m);
    gl.uniform3fv(p.uniform.uOffset, offset||[0,0,0]);
    gl.uniform1f(p.uniform.uScale, size||1);
    gl.uniform1f(p.uniform.uAlpha, alpha===undefined ? 1 : alpha);
    gl.uniform1f(p.uniform.uGloss, gloss||0);
    gl.drawArrays(gl.TRIANGLES, 0, m.count);
  }

  function draw(dt){
    if(!gl || lost || !programs) return;
    const w=canvas.width, h=Math.max(1,canvas.height);
    gl.viewport(0,0,w,h);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const at=camera(w/h, dt||0.016);

    let u=use(programs.sky, at);
    gl.depthMask(false); gl.disable(gl.DEPTH_TEST);
    attach(programs.sky.attrib.aClip, skyBuffer, 2);
    gl.uniformMatrix4fv(u.uInverseViewProj, false, new Float32Array(at.inverse));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.enable(gl.DEPTH_TEST); gl.depthMask(true);

    u=use(programs.ground, at);
    const flat=[]; greens().forEach(g=>flat.push(g[0],g[1],g[2]));
    gl.uniform3fv(u["uGreens[0]"], new Float32Array(flat));
    gl.uniform1f(u.uFairway, FAIRWAY);
    gl.uniform1f(u.uScoring, scoring*YARD);
    bindMesh(programs.ground, meshes.ground);
    gl.drawArrays(gl.TRIANGLES, 0, meshes.ground.count);

    use(programs.solid, at);
    solid(meshes.trees);
    solid(meshes.furniture);

    drawTracers(at);
    drawBall(at);
    drawLabels(w, h);
  }

  function drawTracers(at){
    const traced=shots.filter(s=>s.points && s.points.length>1).slice(-7);
    const u=use(programs.ribbon, at);
    gl.depthMask(false);
    traced.forEach(function(shot, index){
      const fresh=index===traced.length-1;
      let pts=shot.points;
      if(fresh && animation) pts=animation.path.slice(0, Math.max(2, animation.upto));
      else if(fresh) pts=pts.concat(runOut(shot));
      // From where the player stands, earlier shots are in the way of this one.
      const old=view==="first" || view==="chase" ? 0.20 : 0.50;
      ribbon(pts, at.eye, u, fresh ? [0.875,0.972,0.427] : [0.93,0.96,0.90],
        fresh ? 0.95 : old*(1-(traced.length-2-index)*0.13));
    });
    gl.depthMask(true);
  }

  function ribbon(pts, eye, u, colour, alpha){
    if(pts.length<2 || alpha<=0.02) return;
    const pos=[], side=[], age=[];
    for(let i=0;i<pts.length;i++){
      const here=place(pts[i]), next=place(pts[Math.min(i+1,pts.length-1)]), prev=place(pts[Math.max(0,i-1)]);
      const gone=Math.hypot(here[0]-eye[0],here[1]-eye[1],here[2]-eye[2]);
      let out=cross(sub(next,prev), sub(eye,here));
      const l=Math.hypot(out[0],out[1],out[2]);
      out = l>1e-6 ? scale(out,1/l) : [1,0,0];
      const half=Math.max(0.012, gone*(view==="top" ? 0.0022 : 0.0030));
      const a=add(here, scale(out,half)), b=sub(here, scale(out,half));
      pos.push(a[0],a[1]+0.02,a[2], b[0],b[1]+0.02,b[2]); side.push(1,-1);
      const t=i/(pts.length-1); age.push(t,t);
    }
    [["pos",pos],["side",side],["age",age]].forEach(function(pair){
      if(!dynamic[pair[0]]) dynamic[pair[0]]=gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, dynamic[pair[0]]);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(pair[1]), gl.DYNAMIC_DRAW);
    });
    attach(programs.ribbon.attrib.aPos, dynamic.pos, 3);
    attach(programs.ribbon.attrib.aSide, dynamic.side, 1);
    attach(programs.ribbon.attrib.aAge, dynamic.age, 1);
    gl.uniform3fv(u.uColor, colour);
    gl.uniform1f(u.uAlpha, alpha);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, pos.length/3);
  }

  function drawBall(at){
    use(programs.solid, at);
    // On the tee between shots, in the air during one.
    const [x, y, z] = animation && animation.ballAt ? animation.ballAt : [0, 0.056, 0];
    const gone=Math.hypot(x-at.eye[0], y-at.eye[1], z-at.eye[2]);
    // Never smaller than can be seen, however far away it is.
    const size=Math.max(0.0214, gone*(animation ? 0.0030 : 0.0052)*Math.min(1, (rig.fov/0.8)+0.25));
    gl.depthMask(false);
    solid(meshes.shadow, [x, 0.02, z], size*(1.25+Math.min(y,30)*0.12), Math.max(0.06, 0.40-y*0.012));
    gl.depthMask(true);
    solid(meshes.ball, [x, Math.max(y, size), z], size, 1, 0.55);
  }

  function project(point, w, h){
    const m=lastViewProj;
    const cw=m[3]*point[0]+m[7]*point[1]+m[11]*point[2]+m[15];
    if(cw<=0.1) return null;
    const cx=(m[0]*point[0]+m[4]*point[1]+m[8]*point[2]+m[12])/cw;
    const cy=(m[1]*point[0]+m[5]*point[1]+m[9]*point[2]+m[13])/cw;
    if(Math.abs(cx)>1.02 || Math.abs(cy)>1.02) return null;
    return [(cx*0.5+0.5)*w, (0.5-cy*0.5)*h];
  }

  let labels={};
  function label(key, text, point, kind, w, h){
    const host=$("rangeLabels");
    let el=labels[key];
    if(!el){ el=labels[key]=document.createElement("div"); el.className="rangelabel "+kind; host.appendChild(el); }
    const where=point && project(point, w, h);
    el.style.display=where ? "" : "none";
    if(!where) return;
    if(el.textContent!==text) el.textContent=text;
    el.style.left=where[0].toFixed(1)+"px"; el.style.top=where[1].toFixed(1)+"px";
  }
  function drawLabels(){
    const w=canvas.clientWidth, h=canvas.clientHeight;
    label("pin", target+" yd", [0, view==="top" ? 0 : 4.1, target*YARD], "pin", w, h);
    // Far ones bunch up on the horizon, so a label gives way to a nearer one.
    let last=null;
    markers.slice().sort((a,b)=>a-b).forEach(function(yards){
      const point=[FAIRWAY+11, view==="top" ? 0 : 2.0, yards*YARD], where=project(point, w, h);
      const clear=where && (!last || Math.hypot(where[0]-last[0], where[1]-last[1])>30);
      label("m"+yards, String(yards), clear ? point : null, "", w, h);
      if(clear) last=where;
    });
  }

  // --- running ----------------------------------------------------------

  function frame(now){
    raf=null;
    const dt=lastFrame ? Math.min((now-lastFrame)/1000, 0.1) : 0.016;
    if(animation) step(dt);
    else if(settled()){
      // Nothing is moving but the sky. A few frames a second is plenty, and
      // a laptop running on its battery will thank us.
      if(now-lastIdle < 110){ schedule(); return; }
      lastIdle=now;
    }
    lastFrame=now; clock+=dt;
    draw(dt);
    if(!reduced || animation) schedule();
  }

  function step(dt){
    // Fractional progress, so the ball takes as long to fly as the shot
    // actually took. Advancing by a whole point per frame made every shot
    // last the same two seconds regardless of the club.
    animation.progress += dt / animation.seconds;
    const flown=Math.min(1, animation.progress);
    if(flown<1){
      const exact=flown*(animation.air-1);
      animation.upto=Math.floor(exact)+2;
      set(Math.floor(exact), exact-Math.floor(exact));
    }else{
      if(!animation.landed){ animation.landed=true; if(onFlight) onFlight(animation.shot, 1, true); }
      animation.rolling += dt/animation.rollSeconds;
      const exact=(animation.air-1)+Math.min(1,animation.rolling)*(animation.path.length-animation.air);
      animation.upto=Math.floor(exact)+2;
      set(Math.floor(exact), exact-Math.floor(exact));
      // Long enough to see where it finished before looking back up.
      if(animation.rolling>=1){ animation.hold+=dt; if(animation.hold>1.5){ animation=null; return; } }
    }
    if(onFlight && !animation.landed) onFlight(animation.shot, flown, false);
  }
  function set(index, part){
    const path=animation.path, a=path[Math.min(index,path.length-1)], b=path[Math.min(index+1,path.length-1)];
    animation.ballAt=place(mix(a,b,part));
    const ahead=sub(place(b),place(a));
    if(Math.hypot(ahead[0],ahead[2])>0.01) animation.heading=norm([ahead[0],0,ahead[2]]);
  }

  function schedule(){
    if(raf===null && !document.hidden && pane==="range") raf=requestAnimationFrame(frame);
  }

  function resize(){
    if(!canvas) return;
    // Cap the pixel ratio: a 3x panel at full size costs fill rate for no
    // visible gain.
    const ratio=Math.min(window.devicePixelRatio||1, 1.75);
    const w=Math.max(1, Math.round(canvas.clientWidth*ratio));
    const h=Math.max(1, Math.round(canvas.clientHeight*ratio));
    if(canvas.width!==w || canvas.height!==h){ canvas.width=w; canvas.height=h; }
    schedule();
  }

  function start(){
    canvas=$("rangeCanvas");
    if(!canvas || gl) return true;
    try{
      gl=canvas.getContext("webgl2", {antialias:true, alpha:false, depth:true, powerPreference:"high-performance"});
      if(!gl) throw new Error("WebGL 2 is not available");
      build();
    }catch(err){ gl=null; fallback(err && err.message); return false; }
    canvas.addEventListener("webglcontextlost", function(e){
      e.preventDefault(); lost=true;
      if(raf){ cancelAnimationFrame(raf); raf=null; }
    });
    canvas.addEventListener("webglcontextrestored", function(){
      // Windows does this on a driver update. Rebuild rather than go black.
      lost=false;
      try{ build(); schedule(); }catch(e){ fallback(e.message); }
    });
    bindPointer();
    return true;
  }

  function fallback(reason){
    const host=$("rangeFallback");
    if(!host) return;
    host.classList.remove("hidden");
    host.innerHTML="<div><strong>The 3D range cannot run on this computer.</strong><br>"+
      "Your shots are still measured, and their numbers are still shown here and "+
      "under Stats.<br><small>"+esc(reason||"no WebGL")+"</small></div>";
    if(canvas) canvas.style.display="none";
  }

  function bindPointer(){
    canvas.addEventListener("pointerdown", function(e){
      drag={x:e.clientX, y:e.clientY};
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", function(e){
      if(!drag) return;
      const dx=e.clientX-drag.x, dy=e.clientY-drag.y;
      if(view==="behind"){
        orbit.yaw+=dx*0.006;
        orbit.pitch=Math.max(0.03, Math.min(1.4, orbit.pitch+dy*0.004));
      }else if(view==="first"){
        // Dragging the world: pull it right to look left.
        orbit.yaw=Math.max(-0.9, Math.min(0.9, orbit.yaw+dx*0.0016));
        orbit.pitch=Math.max(-0.10, Math.min(0.35, orbit.pitch+dy*0.0012));
      }
      drag={x:e.clientX, y:e.clientY};
      schedule();
    });
    const stop=function(){ drag=null; };
    canvas.addEventListener("pointerup", stop);
    canvas.addEventListener("pointercancel", stop);
    canvas.addEventListener("dblclick", ()=>setView(view));
    canvas.addEventListener("wheel", function(e){
      e.preventDefault();
      if(view==="behind") orbit.dist=Math.max(30, Math.min(420, orbit.dist*(1+e.deltaY*0.0012)));
      else if(view==="first") orbit.dist=Math.max(0.75, Math.min(2.6, orbit.dist*(1-e.deltaY*0.0012)));
      schedule();
    }, {passive:false});
  }

  function setView(name){
    view=name;
    // From behind is deliberately off to one side. From directly behind, the
    // apex and the landing project to nearly the same height on screen and
    // every shot reads as a vertical line. In first person that is honest.
    if(VIEWS[name]) orbit=Object.assign({}, VIEWS[name]);
    schedule();
  }

  function apply(data){
    const previous=shots.length ? shots[shots.length-1].id : 0;
    shots=data.shots||[]; markers=data.markers||[]; target=data.target||target;
    scoring=data.greenRadius||scoring;
    rebuildScenery();
    const newest=shots.length ? shots[shots.length-1] : null;
    if(newest && newest.id!==previous && newest.points && newest.points.length>1 && primed){
      const roll=runOut(newest), path=newest.points.concat(roll);
      animation = reduced ? null : {shot:newest, path:path, air:newest.points.length, upto:2, progress:0,
        seconds:Math.max(0.8, newest.flightSeconds||3), rolling:roll.length ? 0 : 1,
        rollSeconds:Math.max(0.9, roll.length ? 1.5+(newest.totalYards-newest.carryYards)*0.045 : 0.9),
        hold:0, landed:false, ballAt:[0,0.056,0], heading:[0,0,1]};
      lastFrame=0;
    }
    // Whatever was already here when the range was opened is not a new swing.
    primed=true;
    schedule();
  }

  return {start, apply, resize, setView, schedule,
    view:()=>view, flying:()=>!!animation, watch:f=>{ onFlight=f; }};
})();

// --- the practice range: what is laid over it ----------------------------

const SHEET={open:false, bag:false};
let rangeData=null, targetTimer=null, targetWanted=null;

const yd=v=>Math.round(v)+"<small>yd</small>";
function sideways(value, unit, digits){
  // Zero is a measurement: a ball hit dead straight has a direction of 0.
  if(value==null) return "-";
  const shown=Math.abs(value).toFixed(digits);
  if(Number(shown)===0) return (0).toFixed(digits)+"<small>"+unit+"</small>";
  return shown+"<small>"+unit+" "+(value>0?"R":"L")+"</small>";
}
function amount(value, unit, digits){
  return value==null ? "-" : Number(value).toFixed(digits)+"<small>"+unit+"</small>";
}

// Every number here was measured by PiTrac or modelled from what it measured.
// A dash means it was not given, which is not the same as zero.
function tileRows(shot){
  const ball=shot.ball||{};
  return [
    {name:"Carry", html:yd(shot.carryYards), lead:true},
    {name:"Total", html:yd(shot.totalYards)},
    {name:"To pin", html:shot.onGreen ? (shot.toPinYards*3).toFixed(0)+"<small>ft</small>" : yd(shot.toPinYards)},
    {name:"Offline", html:sideways(shot.offlineYards,"yd",0)},
    {name:"Ball speed", html:amount(ball.speed,"mph",1)},
    {name:"Launch", html:amount(ball.launch,"°",1)},
    {name:"Direction", html:sideways(ball.direction,"°",1)},
    {name:"Back spin", html:amount(ball.backSpin,"rpm",0)},
    {name:"Side spin", html:sideways(ball.sideSpin,"rpm",0)},
    {name:"Height", html:amount(shot.apexFeet,"ft",0)},
    {name:"Descent", html:amount(shot.descentDegrees,"°",0)},
  ];
}
function tiles(rows){
  return rows.map(row=>(row.lead ? '<div class="tile lead"><b class="count">' : '<div class="tile"><b>')+
    row.html+"</b><span>"+esc(row.name)+"</span></div>").join("");
}

function renderTiles(data){
  const host=$("rangeTiles"), newest=data.shots.length ? data.shots[data.shots.length-1] : null;
  let html;
  if(data.unflown){
    // Newer than any flight here: a later one would have cleared it.
    const ball=data.unflown.ball||{};
    html=tiles([
      {name:data.unflown.club||"On the ground", html:amount(ball.speed,"mph",1), lead:true},
      {name:"Launch", html:amount(ball.launch,"°",1)},
      {name:"Direction", html:sideways(ball.direction,"°",1)},
    ])+'<div class="tilenote">Recorded. It stayed on the ground, so there is no flight to draw.</div>';
  }else if(!newest) html='<div class="tilenote">Hit a ball and its numbers appear here.</div>';
  else html=tiles(tileRows(newest));
  if(changed(host, html)) host.innerHTML=html;
}

// While it flies, the carry counts up with the ball.
RANGE.watch(function(shot, flown, landed){
  const tile=document.querySelector("#rangeTiles .count");
  if(!tile || !rangeData || rangeData.unflown) return;
  const newest=rangeData.shots[rangeData.shots.length-1];
  if(!newest || newest.id!==shot.id) return;
  const at=shot.points[Math.min(shot.points.length-1, Math.floor(flown*(shot.points.length-1)))];
  tile.innerHTML=yd(landed ? shot.carryYards : at[0]/YARD);
});

function renderState(data){
  const linked=!!(status && status.link && status.link.connected);
  const measuring=((status && status.chain)||[]).find(s=>s.key==="pitrac");
  let kind="", text="";
  if(!linked){ kind="bad"; text="PiTrac is not connected"; }
  else if(measuring && !measuring.ok){ kind="bad"; text=measuring.detail||"PiTrac needs attention"; }
  else if(data.ballDetected===true){ kind="ready"; text="Ball ready. Swing when you like"; }
  else { kind="waiting"; text=data.ballDetected===false ? "Place a ball" : "Waiting for a ball"; }
  $("rangeState").className="rangestate glass "+kind;
  if($("rangeStateText").textContent!==text) $("rangeStateText").textContent=text;
}

function bagClubs(data){ return (data.clubs||[]).filter(c=>c.inBag); }

function renderClubCard(data){
  const club=(data.clubs||[]).find(c=>c.club===data.club);
  $("clubName").textContent=data.club||"Choose a club";
  $("clubAbout").textContent=!club ? "" : club.club==="Putter" ? "Measuring putts"
    : (club.measured ? "You carry " : "About ")+club.carry+" yd";
  $("clubAuto").classList.toggle("on", !!data.autoClub);
  $("clubAuto").setAttribute("aria-pressed", data.autoClub?"true":"false");
  $("clubAuto").classList.toggle("hidden", !data.clubIsOurs);
  // The caddie changes its mind as it learns, and says so rather than swapping
  // the club in somebody's hands.
  const rethink=data.autoClub && data.suggested && data.suggested!==data.club;
  $("clubAuto").textContent=rethink ? "TRY "+data.suggested.toUpperCase() : "AUTO";
  $("clubAuto").dataset.rethink=rethink ? "1" : "";
  const bag=bagClubs(data), at=bag.findIndex(c=>c.club===data.club);
  $("clubLonger").disabled=at===0;
  $("clubShorter").disabled=at===bag.length-1 && at>=0;
}

function renderSheet(data){
  $("clubSheet").classList.toggle("hidden", !SHEET.open);
  if(!SHEET.open) return;
  $("clubSheetTitle").textContent=SHEET.bag ? "My bag" : "Choose a club";
  $("clubSheetNote").textContent=SHEET.bag
    ? "Press the clubs you carry. Auto only ever picks from these."
    : data.clubIsOurs
      ? "Auto picks from the target distance and how far you hit each club. Choosing one here turns Auto off."
      : "Your simulator sets this when you change club there.";
  $("bagEdit").textContent=SHEET.bag ? "Back to clubs" : "Edit my bag";
  const shown=SHEET.bag ? data.clubs : data.clubs.filter(c=>c.inBag || c.club===data.club);
  const html=shown.map(c=>`<button data-club="${esc(c.club)}" class="${
    esc(SHEET.bag ? (c.inBag?"on":"out") : (c.club===data.club?"on":""))}"><b>${esc(c.club)}</b><span>${
    esc(c.club==="Putter" ? "on the green" : c.carry+" yd"+(c.measured?", yours":""))}</span></button>`).join("");
  if(changed($("clubGrid"), html)) $("clubGrid").innerHTML=html;
}

function renderTarget(data){
  const shown=targetWanted==null ? data.target : targetWanted;
  $("targetYards").textContent=shown+" yd";
  const html=(data.targets||[]).map(t=>
    `<button data-yards="${esc(String(t))}" class="${esc(t===shown?"on":"")}">${esc(String(t))}</button>`).join("");
  if(changed($("targetMenu"), html)) $("targetMenu").innerHTML=html;
}

function renderStats(data){
  const shots=data.shots, n=shots.length;
  $("rangeCount").textContent=n ? n+(n===1?" shot":" shots") : "";
  if($("statPanel").classList.contains("hidden")) return;
  const key=JSON.stringify([n, n && shots[n-1].id, data.target]);
  if(!changed($("statHead"), key)) return;
  const average=f=>n ? shots.reduce((sum,s)=>sum+f(s),0)/n : null;
  const onGreen=shots.filter(s=>s.onGreen).length;
  const head=[[n||"-", "shots"],
    [n ? Math.round(average(s=>s.toPinYards))+" yd" : "-", "average to pin"],
    [n ? Math.round(100*onGreen/n)+"%" : "-", "on the green"]];
  $("statHead").innerHTML=head.map(([v,t])=>`<div><b>${esc(String(v))}</b><span>${esc(t)}</span></div>`).join("");
  $("rangeClubs").innerHTML=data.byClub.length
    ? '<div class="statrow head"><span style="text-align:left">Club</span><span>carry</span><span>best</span><span>spread</span></div>'+
      data.byClub.map(row=>`<div class="statrow"><b>${esc(row.club)}</b><span>${esc(String(Math.round(row.carryAvg)))}</span><span>${
        esc(String(Math.round(row.carryBest)))}</span><span>&plusmn;${esc(String(Math.round(row.offlineSigma)))} yd</span></div>`).join("")
    : '<div class="empty">Hit a ball and it will appear here.</div>';
  $("rangeShots").innerHTML=n
    ? '<div class="statrow head"><span style="text-align:left">Club</span><span>carry</span><span>mph</span><span>to pin</span></div>'+
      shots.slice().reverse().map(s=>`<div class="statrow"><b>${esc(s.club||"-")}</b><span>${esc(String(Math.round(s.carryYards)))}</span><span>${
        esc(s.ball.speed==null?"-":String(Math.round(s.ball.speed)))}</span><span>${esc(String(Math.round(s.toPinYards)))} yd</span></div>`).join("")
    : '<div class="empty">Nothing yet.</div>';
  drawPlot(data);
}

// Seen from above, with the flag where it stands. Both directions use one
// scale, so a wide miss looks as wide as it was.
function drawPlot(data){
  const plot=$("rangePlot"), ratio=Math.min(window.devicePixelRatio||1,2);
  const w=plot.clientWidth, h=plot.clientHeight;
  if(!w) return;
  plot.width=w*ratio; plot.height=h*ratio;
  const c=plot.getContext("2d"); c.scale(ratio,ratio); c.clearRect(0,0,w,h);
  const now=data.shots.filter(s=>s.target===data.target);
  $("plotTitle").textContent="Where they finished, "+data.target+" yd target";
  let reach=24;
  now.forEach(s=>{ reach=Math.max(reach, Math.abs(s.offlineYards)+6, (Math.abs(s.totalYards-data.target)+6)); });
  const k=Math.min(w,h)/2/reach, X=x=>w/2+x*k, Y=y=>h/2-(y-data.target)*k;
  const step=reach>80 ? 50 : reach>40 ? 20 : 10;
  c.strokeStyle="rgba(255,255,255,.08)"; c.fillStyle="rgba(255,255,255,.42)"; c.font="10px system-ui"; c.lineWidth=1;
  for(let r=step;r<reach*1.5;r+=step){
    c.beginPath(); c.arc(w/2,h/2,r*k,0,7); c.stroke();
    if(r*k<h/2-4) c.fillText(r+" yd", w/2+4, h/2-r*k+11);
  }
  c.fillStyle="rgba(116,190,104,.45)"; c.beginPath(); c.arc(w/2,h/2,(data.greenRadius||11)*k,0,7); c.fill();
  now.forEach((s,i)=>{
    const last=i===now.length-1;
    c.beginPath(); c.arc(X(s.offlineYards),Y(s.totalYards),last?5:3.6,0,7);
    c.fillStyle=last ? "#dff86d" : "rgba(255,255,255,.62)"; c.fill();
  });
  c.strokeStyle="#fff"; c.lineWidth=1.5; c.beginPath(); c.moveTo(w/2,h/2); c.lineTo(w/2,h/2-15); c.stroke();
  c.fillStyle="#ff6a5c"; c.beginPath(); c.moveTo(w/2,h/2-15); c.lineTo(w/2+10,h/2-11.5); c.lineTo(w/2,h/2-8); c.fill();
}

function showRange(data){
  rangeData=data;
  RANGE.apply(data);
  renderTiles(data); renderState(data); renderClubCard(data);
  renderSheet(data); renderTarget(data); renderStats(data);
}

async function refreshRange(){
  if(pane !== "range") return;
  try{ showRange(await api("/api/range")); }catch(e){}
}
async function rangeAction(path, body){
  // Not run(): these answer at once, and greying a button out and rewording it
  // for a tenth of a second is worse than nothing.
  try{ showRange(await api(path, body)); }catch(error){ showError(error); }
}

// --- the target ---
function wantTarget(yards){
  // Pressing + five times should be one request for the last of them.
  targetWanted=Math.max(20, Math.min(300, yards));
  if(rangeData) renderTarget(rangeData);
  clearTimeout(targetTimer);
  targetTimer=setTimeout(async()=>{
    const asked=targetWanted;
    await rangeAction("/api/range-target",{yards:asked});
    if(targetWanted===asked){ targetWanted=null; if(rangeData) renderTarget(rangeData); }
  }, 220);
}
function nudgeTarget(by){
  if(!rangeData) return;
  const now=targetWanted==null ? rangeData.target : targetWanted;
  wantTarget(by>0 ? Math.floor(now/5)*5+5 : Math.ceil(now/5)*5-5);
}
function closeTargetMenu(){
  $("targetMenu").classList.add("hidden"); $("targetNow").setAttribute("aria-expanded","false");
}
$("targetLess").addEventListener("click", ()=>nudgeTarget(-5));
$("targetMore").addEventListener("click", ()=>nudgeTarget(5));
$("targetNow").addEventListener("click", function(){
  const opening=$("targetMenu").classList.contains("hidden");
  $("targetMenu").classList.toggle("hidden", !opening);
  $("targetNow").setAttribute("aria-expanded", opening?"true":"false");
});
$("targetMenu").addEventListener("click", function(event){
  const button=event.target.closest("[data-yards]");
  if(button){ wantTarget(Number(button.dataset.yards)); closeTargetMenu(); }
});

// --- the club ---
async function chooseClub(club){
  await rangeAction("/api/range-club",{club:club});
}
function stepClub(by){
  if(!rangeData) return;
  const bag=bagClubs(rangeData), at=bag.findIndex(c=>c.club===rangeData.club);
  const next=at<0 ? bag[0] : bag[Math.max(0, Math.min(bag.length-1, at+by))];
  if(next && next.club!==rangeData.club) chooseClub(next.club);
}
function openSheet(open){
  SHEET.open=open; SHEET.bag=false;
  if(rangeData) renderSheet(rangeData);
}
$("clubLonger").addEventListener("click", ()=>stepClub(-1));
$("clubShorter").addEventListener("click", ()=>stepClub(1));
$("clubPick").addEventListener("click", ()=>openSheet(!SHEET.open));
$("clubClose").addEventListener("click", ()=>openSheet(false));
$("bagEdit").addEventListener("click", ()=>{ SHEET.bag=!SHEET.bag; if(rangeData) renderSheet(rangeData); });
$("clubAuto").addEventListener("click", ()=>rangeAction("/api/range-auto",
  {on: $("clubAuto").dataset.rethink==="1" || !(rangeData && rangeData.autoClub)}));
$("clubGrid").addEventListener("click", async function(event){
  const button=event.target.closest("[data-club]");
  if(!button || !rangeData) return;
  const club=button.dataset.club;
  if(SHEET.bag){
    const bag=bagClubs(rangeData).map(c=>c.club);
    await rangeAction("/api/range-bag",{bag: bag.includes(club) ? bag.filter(c=>c!==club) : bag.concat(club)});
  }else{
    await chooseClub(club);
    openSheet(false);
  }
});

// --- the camera, the numbers, the whole screen ---
function closeViewMenu(){
  $("viewMenu").classList.add("hidden");
  $("viewToggle").setAttribute("aria-expanded","false");
}
$("viewToggle").addEventListener("click", function(){
  const opening=$("viewMenu").classList.contains("hidden");
  $("viewMenu").classList.toggle("hidden", !opening);
  $("viewToggle").setAttribute("aria-expanded", opening ? "true" : "false");
});
function chooseView(name){
  document.querySelectorAll(".viewbtn[data-view]").forEach(b=>b.classList.toggle("on", b.dataset.view===name));
  RANGE.setView(name);
  closeViewMenu();
}
document.querySelectorAll(".viewbtn[data-view]").forEach(button=>
  button.addEventListener("click", ()=>chooseView(button.dataset.view)));
function toggleStats(){
  const opening=$("statPanel").classList.contains("hidden");
  $("statPanel").classList.toggle("hidden", !opening);
  $("statToggle").classList.toggle("on", opening);
  $("statToggle").setAttribute("aria-pressed", opening?"true":"false");
  $("statHead").dataset.sig="";
  RANGE.resize();
  if(rangeData) renderStats(rangeData);
}
$("statToggle").addEventListener("click", toggleStats);
async function setImmersive(on){
  document.body.classList.toggle("immersive", on);
  $("fullToggle").classList.toggle("on", on);
  $("fullToggle").setAttribute("aria-pressed", on?"true":"false");
  $("fullToggle").textContent=on ? "Exit full screen" : "Full screen";
  try{ await api("/api/fullscreen",{on:on}); }catch(_error){}
  RANGE.resize();
}
$("fullToggle").addEventListener("click", ()=>setImmersive(!document.body.classList.contains("immersive")));

// Anywhere else, or Escape, puts whatever is open away again.
document.addEventListener("click", function(event){
  if(!event.target.closest) return;
  if(!event.target.closest(".views")) closeViewMenu();
  if(!event.target.closest("#targetArea")) closeTargetMenu();
  if(SHEET.open && !event.target.closest("#clubSheet") && !event.target.closest("#clubCard")
     && document.contains(event.target)) openSheet(false);
});
document.addEventListener("keydown", function(event){
  if(event.key==="Escape"){
    if(SHEET.open) openSheet(false);
    else if(document.body.classList.contains("immersive")) setImmersive(false);
    closeViewMenu(); closeTargetMenu();
    return;
  }
  // Hands are on a club, so one key each. Never while typing somewhere.
  if(pane!=="range" || event.metaKey || event.ctrlKey || event.altKey
     || /^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName||"")) return;
  const order=["first","chase","behind","top"];
  const keys={
    ArrowLeft:()=>stepClub(-1), ArrowRight:()=>stepClub(1),
    ArrowUp:()=>nudgeTarget(5), ArrowDown:()=>nudgeTarget(-5),
    a:()=>$("clubAuto").click(), c:()=>openSheet(!SHEET.open), s:toggleStats,
    v:()=>chooseView(order[(order.indexOf(RANGE.view())+1)%order.length]),
    f:()=>$("fullToggle").click(),
  };
  const act=keys[event.key.length===1 ? event.key.toLowerCase() : event.key];
  if(act){ event.preventDefault(); act(); }
});

$("simCheck").addEventListener("click", e=>doAction("check", e.target));
$("simTest").addEventListener("click", e=>doAction("test", e.target));
$("rangeClear").addEventListener("click", ()=>rangeAction("/api/range-clear",{}));
$("rangeDemo").addEventListener("click", e=>run(e.target, async()=>{
  await api("/api/range-demo",{});
  await refreshRange();
}));
window.addEventListener("resize", function(){
  clearTimeout(window.__rangeResize);
  window.__rangeResize = setTimeout(()=>{
    RANGE.resize();
    if(rangeData){ $("statHead").dataset.sig=""; renderStats(rangeData); }
  }, 120);
});
document.addEventListener("visibilitychange", ()=>{ if(!document.hidden) RANGE.schedule(); });

"""
