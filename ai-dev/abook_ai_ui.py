"""SPA additions for `abook review`: profile switcher, «Анкета» (questionnaire stepper), Claude results,
the pinned AI block in «Что дальше». Injected into REVIEW_HTML at the /*AI:…*/ and <!--AI:…--> markers
by abook_ai.inject_html(). Uses the page's helpers ($, el, esc, api, post, toast, show, openItem…)."""

CSS = r'''
.prof{position:relative;margin:0 0 10px}
.profbtn{all:unset;box-sizing:border-box;width:100%;cursor:pointer;display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;background:var(--s2);border:1px solid var(--line)}
.profbtn:hover{border-color:var(--line2)}.profbtn:focus-visible{outline:2px solid var(--accent)}
.profbtn .pn{display:flex;flex-direction:column;min-width:0;flex:1;line-height:1.25}
.profbtn .pn b{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.profbtn .pn small{font-size:11.5px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.profbtn svg{flex:none;color:var(--dim)}
.av{flex:none;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font:650 14px/1 var(--sans);background:#27303B;color:var(--ink);user-select:none}
.pmenu{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:50;background:var(--s2);border:1px solid var(--line2);border-radius:12px;padding:6px;box-shadow:0 18px 50px rgba(0,0,0,.55);display:flex;flex-direction:column;gap:2px;min-width:230px}
.pmi,.pma{all:unset;box-sizing:border-box;cursor:pointer;display:flex;align-items:center;gap:10px;padding:7px 8px;border-radius:8px;font-size:13.5px;color:var(--soft)}
.pmi:hover,.pma:hover,.pmi:focus-visible,.pma:focus-visible{background:#1F2630;color:var(--ink)}
.pmi.on{background:#1B2330}
.pmi .pmt{display:flex;flex-direction:column;min-width:0;flex:1;line-height:1.25}.pmi .pmt b{font-weight:550;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pmi .pmt small{font-size:11.5px;color:var(--dim)}
.pmi .chk{color:var(--accent);font-size:13px}
.pma{padding:7px 10px}.pma.danger{color:#D9A79F}.pma.danger:hover{color:var(--red)}.pma[disabled]{opacity:.4;cursor:default;background:none}
.psep{height:1px;background:var(--line);margin:4px 2px}
.modal{position:fixed;inset:0;background:rgba(5,7,10,.66);backdrop-filter:blur(2px);z-index:70;display:flex;align-items:flex-start;justify-content:center;padding:14vh 16px 16px}
.mbox{width:min(460px,100%);background:var(--s1);border:1px solid var(--line2);border-radius:14px;padding:18px 18px 14px;display:flex;flex-direction:column;gap:12px;box-shadow:0 24px 70px rgba(0,0,0,.6)}
.mbox h3{margin:0;font:650 18px/1.3 var(--serif)}
.mbox .in{width:100%}.mbox p{margin:0;color:var(--soft);font-size:14px}.mbox ul{margin:0;padding-left:18px;color:var(--soft);font-size:13.5px}
.merr{color:#F0B3AA;font-size:13px}
.mfoot{justify-content:flex-end}
.btn.danger{background:var(--red);color:#1A0B09}
.qtop{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.aibadge{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:#C9B48E;background:var(--amberbg);border:1px solid #3F3320;border-radius:999px;padding:5px 11px;white-space:nowrap}
.aibadge i{width:7px;height:7px;border-radius:50%;background:var(--amber);display:inline-block}
.qhead{display:flex;flex-direction:column;gap:8px}
.qrow{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:12.5px;color:var(--muted)}
.qstep{font-variant-numeric:tabular-nums;color:var(--soft)}.qsaved{color:var(--dim)}
.qbar{height:6px;border-radius:99px;background:var(--s3);overflow:hidden}.qbar i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),#A9C8EA);border-radius:99px;transition:width .3s}
.qdots{display:flex;gap:4px;flex-wrap:wrap}
.qdot{all:unset;cursor:pointer;font-size:12px;padding:4px 9px;border-radius:999px;color:var(--dim);background:transparent;border:1px solid transparent}
.qdot:hover{color:var(--ink);background:var(--s2)}.qdot.done{color:#9CC2EA}.qdot.done::before{content:"● ";font-size:8px;vertical-align:2px}
.qdot.on{color:var(--ink);background:#1B2330;border-color:var(--line2)}.qdot:focus-visible{outline:2px solid var(--accent)}
.qcard{background:var(--s1);border:1px solid var(--line);border-radius:14px;padding:20px 20px 22px;display:flex;flex-direction:column;gap:6px}
.qcard h3.qt{margin:0;font:650 22px/1.25 var(--serif)}
.qbody{display:flex;flex-direction:column;gap:18px;margin-top:12px}
.qsec{display:flex;flex-direction:column;gap:8px}
.qsec>.ql{font-size:12.5px;color:var(--muted);display:flex;justify-content:space-between;gap:8px}
.qsec>.ql b{font-weight:500;color:var(--soft)}
.qfoot{display:flex;align-items:center;gap:12px;position:sticky;bottom:0;background:linear-gradient(transparent,var(--bg) 30%);padding:18px 0 6px;z-index:5}
.qfoot .btn{padding:10px 20px}
.qsearch{position:relative}
.qsearch .qin{display:flex;align-items:center;gap:10px;background:var(--s2);border:1px solid var(--accentln);border-radius:12px;padding:3px 6px 3px 14px}
.qsearch .qin:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px rgba(134,174,218,.12)}
.qsearch input{flex:1;background:none;border:0;outline:none;font-size:16px;padding:10px 0;min-width:0}
.qsearch .hits{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:20;max-height:360px;overflow:auto;box-shadow:0 18px 50px rgba(0,0,0,.55)}
.qcount{font-size:12.5px;color:var(--muted)}.qcount b{color:var(--ink);font-variant-numeric:tabular-nums}
.qents{display:flex;flex-direction:column;gap:10px}
.qent{background:var(--s2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:10px;animation:qin .18s ease-out}
@keyframes qin{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
.qent .h{display:flex;align-items:flex-start;gap:10px}
.qent .h .tt{flex:1;min-width:0;font-weight:550;font-size:15px;line-height:1.35}
.qent .h .tt small{display:block;font-weight:400;color:var(--muted);font-size:12.5px;margin-top:2px}
.qent .h .ed{flex:1;display:grid;grid-template-columns:1fr 1.4fr;gap:6px}
.qent .h .ed .in{padding:6px 9px;font-size:14px}
.qent .x{all:unset;cursor:pointer;color:var(--dim);width:26px;height:26px;border-radius:7px;display:grid;place-items:center;flex:none}
.qent .x:hover{color:var(--red);background:var(--redbg)}
.qent .r{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.qent .r .in{flex:1;min-width:200px;padding:6px 10px;font-size:13.5px}
.mini{display:flex;gap:2px;align-items:center}
.mini span{font-size:12px;color:var(--dim);margin-right:6px}
.mini button{all:unset;cursor:pointer;width:22px;height:24px;border-radius:5px;background:var(--s4);font:500 11.5px/24px var(--sans);text-align:center;color:#8E98A5;font-variant-numeric:tabular-nums}
.mini button:hover{background:#27303B;color:var(--ink)}.mini button.f{background:var(--amberf);color:#F3DDB2}.mini button.c{background:var(--amber);color:#1A1405;font-weight:700}
.mini button:focus-visible{outline:2px solid var(--accent)}
.fchips{display:flex;gap:6px;flex-wrap:wrap;align-items:center;background:var(--s2);border:1px solid var(--line);border-radius:10px;padding:6px 8px;min-height:42px}
.fchips:focus-within{border-color:var(--accentln)}
.fchips .fc{display:inline-flex;align-items:center;gap:4px;font-size:13px;padding:4px 6px 4px 10px;border-radius:999px;background:var(--accentbg);color:#B9D3EF}
.fchips .fc button{all:unset;cursor:pointer;color:#7FA3C9;padding:0 4px;border-radius:50%}.fchips .fc button:hover{color:var(--red)}
.fchips input{flex:1;min-width:160px;background:none;border:0;outline:none;padding:4px 2px;font-size:14px}
.qhint{font-size:12.5px;color:var(--dim)}
.qsum{display:flex;flex-direction:column;gap:2px}
.qsum .it{display:grid;grid-template-columns:170px 1fr auto;gap:12px;padding:10px 0;border-bottom:1px solid #1A2027;align-items:baseline;font-size:14px}
.qsum .it:last-child{border-bottom:0}.qsum .it .k{color:var(--muted);font-size:13px}.qsum .it .v{color:var(--soft);line-height:1.55;overflow-wrap:anywhere}
.qempty{background:var(--s2);border:1px dashed var(--line2);border-radius:12px;padding:18px;color:var(--muted);text-align:center;font-size:14px}
.qgo{background:linear-gradient(135deg,#1B2533,#171C24);border:1px solid var(--accentln);border-radius:14px;padding:18px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.qgo .tx{flex:1;min-width:240px;font-size:13.5px;color:var(--soft);line-height:1.6}
.qgo .tx b{color:var(--ink);font-weight:600}
.bigbtn{all:unset;cursor:pointer;background:var(--amber);color:#1A1405;font-weight:650;padding:12px 20px;border-radius:10px;font-size:15px;display:inline-flex;gap:8px;align-items:center}
.bigbtn:hover{filter:brightness(1.08)}.bigbtn[disabled]{opacity:.5;cursor:default;filter:none}.bigbtn:focus-visible{outline:2px solid var(--accent)}
.qrun{background:var(--s1);border:1px solid var(--line);border-radius:14px;padding:26px 22px;display:flex;flex-direction:column;gap:14px;align-items:center;text-align:center}
.qrun h3{margin:0;font:650 20px/1.3 var(--serif)}
.qrun .tm{font:600 40px/1 var(--mono);color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:.02em}
.qrun .ph{color:var(--soft);font-size:14px;min-height:21px}
.ibar{width:min(420px,100%);height:5px;border-radius:99px;background:var(--s3);overflow:hidden;position:relative}
.ibar i{position:absolute;top:0;bottom:0;width:38%;border-radius:99px;background:linear-gradient(90deg,transparent,var(--amber),transparent);animation:ibar 1.6s ease-in-out infinite}
@keyframes ibar{0%{left:-40%}100%{left:100%}}
.qev{width:min(560px,100%);display:flex;flex-direction:column;gap:4px;text-align:left;font-size:12.5px;color:var(--muted)}
.qev div{display:flex;gap:8px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.qev div span{flex:none;color:var(--dim);font-variant-numeric:tabular-nums;width:38px}
.qev div b{font-weight:500;color:#C9B48E;flex:none}.qev div em{font-style:normal;overflow:hidden;text-overflow:ellipsis}
.ares{display:flex;flex-direction:column;gap:14px}
.arh{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;flex-wrap:wrap}
.arh h3{margin:0;font:650 18px/1.3 var(--serif)}.arh .sub{font-size:12.5px}
.pcard{background:linear-gradient(160deg,#171D26,#13171C 60%);border:1px solid var(--line2);border-radius:14px;padding:20px;display:flex;flex-direction:column;gap:14px}
.pcard .sm{font:500 17px/1.6 var(--serif);color:#EDE6DA;margin:0}
.axes{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.axis{background:var(--s2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:3px}
.axis b{font-size:12px;font-weight:500;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.axis span{font-size:14px;color:var(--ink)}.axis small{font-size:12px;color:var(--dim);line-height:1.45}
.lv{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.lv h4{margin:0 0 6px;font-size:12.5px;font-weight:500;color:var(--muted)}
.ctx{font-size:13.5px;color:var(--soft);border-top:1px solid var(--line);padding-top:12px}.ctx b{color:var(--muted);font-weight:500}
.t5{background:var(--s1);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;gap:14px;align-items:flex-start}
.t5:hover{border-color:#34404D}
.t5 .rk{flex:none;width:38px;height:38px;border-radius:10px;display:grid;place-items:center;font:650 19px/1 var(--serif);background:var(--amberbg);color:var(--amber);border:1px solid #3F3320}
.t5 .bd{flex:1;min-width:0;display:flex;flex-direction:column;gap:5px}
.t5 .ti{font:600 16px/1.35 var(--sans);cursor:pointer}.t5 .ti:hover{color:var(--accent)}
.t5 .mt{font-size:12.5px;color:var(--muted)}
.t5 .wy{font-size:14px;color:var(--soft);line-height:1.55}
.conf{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim)}
.conf .cb{width:90px;height:5px;border-radius:99px;background:var(--s4);overflow:hidden}.conf .cb i{display:block;height:100%;background:var(--green);border-radius:99px}
.olist{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}
.oc{background:var(--s1);border:1px solid var(--line);border-radius:12px;padding:13px 14px;display:flex;flex-direction:column;gap:6px}
.oc .ti{font-weight:600}.oc .wy{font-size:13.5px;color:var(--soft);line-height:1.5}.oc .wf{font-size:12.5px;color:#C9B48E;overflow-wrap:anywhere}
.oc .wf a{color:#E0C48E}
.qq{margin:0;padding-left:20px;color:var(--soft);font-size:14px;display:flex;flex-direction:column;gap:4px}
.hlist{display:flex;flex-direction:column;gap:6px}
.hrow{all:unset;cursor:pointer;display:grid;grid-template-columns:150px 110px 1fr auto;gap:10px;align-items:baseline;font-size:13px;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--s1)}
.hrow:hover{border-color:#34404D}.hrow.on{border-color:var(--accentln);background:var(--accentbg)}
.hrow .d{color:var(--soft);font-variant-numeric:tabular-nums}.hrow .k{color:var(--muted)}.hrow .t{color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hrow .s{font-size:12px}
.hrow .s.err{color:var(--red)}.hrow .s.ok{color:var(--green)}
.vbanner{background:var(--accentbg);border:1px solid var(--accentln);border-radius:10px;padding:9px 12px;font-size:13px;color:#B9D3EF;display:flex;gap:10px;align-items:center}
.aipin{background:linear-gradient(160deg,#1D1A12,#15171B 70%);border:1px solid #4A3B20;border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:10px}
.aipin .hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.aipin .hd h3{margin:0;font:650 17px/1.3 var(--serif);color:#F3DDB2}
.aipin .hd .sub{font-size:12.5px}
.aipin .pi{display:flex;gap:12px;align-items:flex-start;padding:8px 0;border-top:1px solid #2E2718}
.aipin .pi .n{flex:none;width:26px;height:26px;border-radius:7px;display:grid;place-items:center;font:650 14px/1 var(--serif);background:#2A2217;color:var(--amber)}
.aipin .pi .b{flex:1;min-width:0}.aipin .pi .t{font-weight:550;cursor:pointer}.aipin .pi .t:hover{color:var(--accent)}
.aipin .pi .w{font-size:13px;color:#CDBFA6;line-height:1.5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.aipin.slim{flex-direction:row;align-items:center;gap:14px;flex-wrap:wrap;padding:12px 16px}
.aipin.slim .tx{flex:1;min-width:220px;font-size:13.5px;color:#CDBFA6}
.problem{background:var(--redbg);border:1px solid #5A2F2A;border-radius:12px;padding:14px 16px;color:#F0B3AA;font-size:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.problem .tx{flex:1;min-width:220px}
.brief{white-space:pre-wrap;font-size:13.5px;line-height:1.6;color:var(--soft);background:var(--s2);border:1px solid var(--line);border-radius:10px;padding:12px 14px;max-height:320px;overflow:auto}
@media (max-width:760px){.qsum .it{grid-template-columns:1fr auto}.qsum .it .k{grid-column:1/-1}.lv{grid-template-columns:1fr}.hrow{grid-template-columns:1fr auto}.hrow .k,.hrow .t{display:none}
.qent .h .ed{grid-template-columns:1fr}.qcard{padding:16px}.prof{margin-bottom:6px}.pmenu{right:auto;width:min(320px,calc(100vw - 32px))}}
@media (prefers-reduced-motion:reduce){.ibar i{animation:none;left:31%}.qent{animation:none}}
'''

RAIL = r'''<div class="prof" id="prof">
    <button class="profbtn" id="profBtn" aria-haspopup="menu" aria-expanded="false" title="Профиль слушателя: отзывы, очередь, анкета и файл для ИИ — у каждого свои">
      <span class="av" id="profAv">·</span><span class="pn"><b id="profName">…</b><small id="profSub">&nbsp;</small></span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg></button>
    <div class="pmenu" id="profMenu" role="menu" hidden></div>
  </div>'''

VIEWS = r'''<!-- АНКЕТА -->
<section class="view" id="v-anketa" hidden>
  <div class="qtop"><div><h2 class="vt" id="qaTitle">Анкета</h2><p class="sub" id="qaSub">5–10 минут: книги, кино, путешествия — и Claude составит ваш профиль и топ-5 из библиотеки.</p></div>
    <span class="aibadge" title="Подбор делает Claude через локальный Claude Code CLI; модель может искать в интернете. Запускается только по кнопке."><i></i>Использует Claude (через Claude Code) и интернет</span></div>
  <div id="qaBox" class="view"></div>
</section>
<div class="modal" id="modal" hidden><div class="mbox" role="dialog" aria-modal="true" aria-labelledby="mT">
  <h3 id="mT"></h3><div id="mB" style="display:flex;flex-direction:column;gap:10px"></div><div class="merr" id="mErr" hidden></div>
  <div class="row mfoot"><button class="ghost" id="mNo">Отмена</button><button class="btn" id="mYes">OK</button></div></div></div>'''

JS = r'''
/* ================= profiles ================= */
let PROFS=[],PDEF=1;
const profCur=()=>PROFS.find(p=>p.id===PROFILE)||PROFS[0];
const plural=(n,a,b,c)=>{const m=n%10,h=n%100;return n+' '+(m===1&&h!==11?a:m>=2&&m<=4&&(h<12||h>14)?b:c)};
function avatar(p){const a=el('span','av',p.initial);a.style.background=`hsl(${p.hue},34%,27%)`;a.style.color=`hsl(${p.hue},75%,86%)`;return a}
function profLine(p){return [p.reviews?plural(p.reviews,'отзыв','отзыва','отзывов'):'нет отзывов',p.queue?'очередь '+p.queue:'',p.running?'ИИ подбирает…':''].filter(Boolean).join(' · ')}
async function loadProfiles(){try{const j=await api('/api/profiles');PROFS=j.profiles;PDEF=j.default;
  if(!PROFS.some(p=>p.id===PROFILE)){PROFILE=j.default;store.set('abook.profile',String(PROFILE))}paintProfile()}catch(e){toast(e.message,'err')}}
function paintProfile(){const p=profCur();if(!p)return;const a=$('#profAv');a.textContent=p.initial;a.style.background=`hsl(${p.hue},34%,27%)`;a.style.color=`hsl(${p.hue},75%,86%)`;
  $('#profName').textContent=p.name;$('#profSub').textContent=profLine(p);
  const c=$('#c-anketa');const qs=p.questionnaire.status;c.textContent=p.running?'ИИ…':qs==='none'?'новое':qs==='draft'?'черновик':'';c.style.color=p.running||qs!=='submitted'?'var(--amber)':'';
  $$('#v-export a[href^="/api/export/"]').forEach(x=>{x.href=x.getAttribute('href').split('?')[0]+'?profile='+PROFILE});document.title='Аудиотека · '+p.name}
const needsOnboarding=()=>{const p=profCur();return !!p&&!p.is_default&&p.questionnaire.status==='none'&&!p.reviews};
function closeMenu(){$('#profMenu').hidden=true;$('#profBtn').setAttribute('aria-expanded','false')}
function openMenu(){const m=$('#profMenu'),cur=profCur();m.innerHTML='';
  for(const p of PROFS){const b=el('button','pmi'+(p.id===PROFILE?' on':''));b.setAttribute('role','menuitem');b.appendChild(avatar(p));const t=el('span','pmt');t.appendChild(el('b',null,p.name));t.appendChild(el('small',null,profLine(p)));b.appendChild(t);
    if(p.id===PROFILE)b.appendChild(el('span','chk','✓'));b.onclick=()=>switchProfile(p.id);m.appendChild(b)}
  m.appendChild(el('div','psep'));const add=(t,f,cls)=>{const b=el('button','pma'+(cls?' '+cls:''),t);b.setAttribute('role','menuitem');b.onclick=()=>{closeMenu();f()};m.appendChild(b);return b};
  add('＋ Новый профиль',newProfileDlg);add('Переименовать «'+cur.name+'»',renameDlg);const d=add('Удалить «'+cur.name+'»…',deleteDlg,'danger');
  if(cur.is_default){d.disabled=true;d.title='Основной профиль удалить нельзя: его файл для ИИ — главный'}
  m.hidden=false;$('#profBtn').setAttribute('aria-expanded','true');m.querySelector('.pmi.on')?.focus()}
$('#profBtn').onclick=e=>{e.stopPropagation();$('#profMenu').hidden?openMenu():closeMenu()};
document.addEventListener('mousedown',e=>{if(!$('#profMenu').hidden&&!e.target.closest('#prof'))closeMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#profMenu').hidden){closeMenu();$('#profBtn').focus()}});
async function switchProfile(id){closeMenu();if(id===PROFILE)return;PROFILE=id;store.set('abook.profile',String(id));
  CUR=null;F=null;$('#card').hidden=true;$('#rateEmpty').hidden=false;QA=null;QMODE=null;VIEWRUN=null;AIST=null;clearTimeout(AIPOLL);
  paintProfile();await refreshMeta();paintMode();toast('Профиль: '+profCur().name);
  if(needsOnboarding())show('anketa');else show(VIEW);aiTick()}

/* ---------- modal ---------- */
let MOK=null;
function dlg(title,build,okText,onOk,danger){$('#mT').textContent=title;const b=$('#mB');b.innerHTML='';const focus=build(b);$('#mErr').hidden=true;
  const y=$('#mYes');y.textContent=okText;y.className='btn'+(danger?' danger':'');y.disabled=false;MOK=onOk;$('#modal').hidden=false;setTimeout(()=>(focus||y).focus(),20)}
function dlgClose(){$('#modal').hidden=true;MOK=null}
async function dlgOk(){if(!MOK||$('#mYes').disabled)return;const y=$('#mYes');y.disabled=true;try{await MOK();dlgClose()}catch(e){$('#mErr').textContent=e.message;$('#mErr').hidden=false;y.disabled=false}}
$('#mNo').onclick=dlgClose;$('#mYes').onclick=dlgOk;$('#modal').onmousedown=e=>{if(e.target.id==='modal')dlgClose()};
$('#modal').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();dlgClose()}else if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();dlgOk()}});
function nameInput(v){const i=el('input','in');i.maxLength=40;i.value=v||'';i.placeholder='Имя, например «Марина»';i.autocomplete='off';return i}
function newProfileDlg(){let i;dlg('Новый профиль',b=>{b.appendChild(el('p',null,'У каждого профиля свои отзывы, очередь, анкета, подборы ИИ и свой файл для ИИ. Библиотека общая.'));i=nameInput('');b.appendChild(i);return i},'Создать',async()=>{
  const j=await post('/api/profiles',{op:'create',name:i.value});PROFS=j.profiles;await switchProfile(j.created);show('anketa')})}
function renameDlg(){const p=profCur();let i;dlg('Переименовать профиль',b=>{i=nameInput(p.name);b.appendChild(i);setTimeout(()=>i.select(),30);return i},'Сохранить',async()=>{
  const j=await post('/api/profiles',{op:'rename',id:p.id,name:i.value});PROFS=j.profiles;paintProfile();toast('Профиль переименован')})}
function deleteDlg(){const p=profCur();if(p.is_default)return;let i;dlg('Удалить профиль «'+p.name+'»?',b=>{
    b.appendChild(el('p',null,'Будут удалены только данные этого профиля:'));const u=el('ul');[plural(p.reviews,'отзыв','отзыва','отзывов')+' вместе с историей правок','очередь ('+p.queue+')','анкета и все подборы ИИ','его файлы для ИИ на D:'].forEach(t=>u.appendChild(el('li',null,t)));b.appendChild(u);
    b.appendChild(el('p',null,'Библиотека и другие профили не затрагиваются. Перед удалением JSON-копия профиля сохраняется в ~/abook/reviews-backups/.'));
    i=el('input','in');i.placeholder='Введите «'+p.name+'» для подтверждения';i.autocomplete='off';const y=$('#mYes');i.oninput=()=>{y.disabled=norm(i.value.trim())!==norm(p.name)};b.appendChild(i);setTimeout(()=>{y.disabled=true},0);return i},
  'Удалить навсегда',async()=>{const j=await post('/api/profiles',{op:'delete',id:p.id,confirm:i.value});PROFS=j.profiles;await switchProfile(j.default);toast('Профиль удалён · копия: '+j.backup.split('/').pop())},true)}

/* ================= questionnaire ================= */
let QA=null,QSTEP=0,QTIMER=null,QMODE=null,AIST=null,AIPOLL=null,VIEWRUN=null,QSAVING=null;
const QSTEPS=[
 {k:'books_liked',t:'Книги, которые понравились',s:'Главное в анкете. Добавьте книги, которые вам понравились, — из библиотеки или любые другие — и отметьте, чем зацепили. Хорошо бы 3–10.'},
 {k:'books_disliked',t:'Книги, которые не понравились',s:'Что бросили или дослушали через силу. Это помогает не меньше любимых — и такие книги точно не попадут в советы.'},
 {k:'prefs',t:'Книжные предпочтения',s:'Жанры, длина, формат, язык — и когда вы обычно слушаете.'},
 {k:'films',t:'Фильмы',s:'Любимое кино многое говорит о вкусе: атмосфера, темп, твисты, идеи.'},
 {k:'series',t:'Сериалы',s:'То же для сериалов — они близки к длинным аудиокнигам.'},
 {k:'games',t:'Видеоигры',s:'Любимые игры и чем именно зацепили — сюжет, мир, атмосфера, свобода выбора. Отличный сигнал вкуса.'},
 {k:'travel',t:'Путешествия',s:'Места и тип отдыха подсказывают сеттинги и настроение книг.'},
 {k:'music',t:'Музыка и интересы',s:'Коротко и по желанию.'},
 {k:'about',t:'О себе',s:'Пара слов о вас — чтобы советы звучали по-человечески. Всё необязательно.'},
 {k:'worldview',t:'Мировоззрение',s:'Четыре коротких вопроса о темах и интонациях, которые вам ближе. Можно пропустить.'},
 {k:'summary',t:'Итог',s:'Проверьте ответы — Claude составит ваш профиль и топ-5 из библиотеки.'}];
const LINE2STEP={books_liked:0,books_disliked:1,prefs:2,films:3,series:4,games:5,travel:6,music:7,interests:7,about:8,worldview:9};
const LANGL={ru:'русский',uk:'украинский',en:'английский'};
function qa(){const a=QA.answers||(QA.answers={});for(const k of ['books_liked','books_disliked','films','series','games','film_genres','series_genres','game_genres'])a[k]=a[k]||[];
  a.prefs=Object.assign({genres:[],genres_text:'',length:[],format:[],lang:[],listen:[],narrators:''},a.prefs||{});
  a.travel=Object.assign({been:[],want:[],types:[],pace:'',text:''},a.travel||{});a.music=Object.assign({chips:[],text:''},a.music||{});a.interests=Object.assign({chips:[],text:''},a.interests||{});
  a.about=Object.assign({name:'',age:'',education:[],education_text:'',profession:'',location:'',family:[],family_text:''},a.about||{});a.worldview=a.worldview||{};
  for(const w of QA.worldview)a.worldview[w.key]=Object.assign({v:'',text:''},a.worldview[w.key]||{});return a}
function filled(k){const a=QA&&QA.answers||{};const nz=o=>o&&Object.values(o).some(v=>Array.isArray(v)?v.length:typeof v==='object'&&v?nz(v):!!v);
  return k==='music'?nz(a.music)||nz(a.interests):k==='films'?(a.films||[]).length||(a.film_genres||[]).length:k==='series'?(a.series||[]).length||(a.series_genres||[]).length:k==='games'?(a.games||[]).length||(a.game_genres||[]).length:Array.isArray(a[k])?a[k].length>0:nz(a[k])}
function qaDirty(){QA.dirty=true;clearTimeout(QTIMER);QTIMER=setTimeout(qaFlush,800);const s=$('#qaSaved');if(s)s.textContent='изменения…'}
async function qaFlush(){clearTimeout(QTIMER);if(!QA||!QA.dirty)return QSAVING;QA.dirty=false;const my=PROFILE;
  QSAVING=(async()=>{try{const j=await post('/api/questionnaire',{answers:QA.answers,step:QSTEP});if(my!==PROFILE||!QA)return;QA.lines=j.lines;QA.status=j.status;QA.source=j.source;
    const s=$('#qaSaved');if(s)s.textContent='✓ черновик сохранён · '+hm(new Date().toISOString());if(j.renamed)loadProfiles()}catch(e){QA.dirty=true;toast('Черновик не сохранён: '+e.message,'err')}})();return QSAVING}
async function goStep(i){if(i<0||i>=QSTEPS.length)return;await qaFlush();QSTEP=i;QMODE='form';renderAnketa();window.scrollTo(0,0)}
async function loadAnketa(){const my=PROFILE;try{const [q,s]=await Promise.all([api('/api/questionnaire'),api('/api/ai/status')]);if(my!==PROFILE)return;QA=q;AIST=s;
  if(s.job)QMODE='running';else if(!QMODE||QMODE==='running')QMODE=s.latest?'result':q.source==='brief'?'brief':'form';
  if(QMODE==='form'&&!QA.touched){QSTEP=q.status==='draft'?Math.min(q.step||0,QSTEPS.length-1):0;QA.touched=true}
  renderAnketa();if(s.job)aiTick()}catch(e){toast(e.message,'err')}}
function renderAnketa(){if(!QA)return;const p=profCur();$('#qaTitle').textContent=QMODE==='result'?'Ваш профиль и топ-5':'Анкета'+(p?' · '+p.name:'');
  ({form:renderForm,running:renderRunning,result:renderResult,brief:renderBrief,problem:renderProblem})[QMODE]()}

/* ---------- small widgets ---------- */
function chipSet(opts,arr,onCh,cls,label){const c=el('div','chips');for(const o of opts){const v=Array.isArray(o)?o[0]:o,t=Array.isArray(o)?o[1]:o;const on=arr.includes(v);
    const b=el('button','chip'+(cls?' '+cls:'')+(on?' on':''),t);b.setAttribute('aria-pressed',on);b.onclick=()=>{const i=arr.indexOf(v);if(i>=0)arr.splice(i,1);else arr.push(v);b.classList.toggle('on');b.setAttribute('aria-pressed',arr.includes(v));onCh()};c.appendChild(b)}return c}
function oneOf(opts,obj,key,onCh){const c=el('div','chips');const bs=[];for(const v of opts){const b=el('button','chip'+(obj[key]===v?' on':''),v);b.onclick=()=>{obj[key]=obj[key]===v?'':v;bs.forEach(x=>x.classList.toggle('on',x.textContent===obj[key]));onCh()};bs.push(b);c.appendChild(b)}return c}
function freeChips(arr,ph,onCh){const w=el('div','fchips');const inp=el('input');inp.placeholder=ph;
  const paint=()=>{w.querySelectorAll('.fc').forEach(x=>x.remove());arr.forEach((v,i)=>{const c=el('span','fc',v);const x=el('button',null,'×');x.title='убрать';x.onclick=()=>{arr.splice(i,1);paint();onCh()};c.appendChild(x);w.insertBefore(c,inp)})};
  const addv=()=>{let ch=false;for(const v of inp.value.split(/[,;]/).map(s=>s.trim()).filter(Boolean))if(!arr.some(x=>norm(x)===norm(v))){arr.push(v.slice(0,80));ch=true}inp.value='';if(ch){paint();onCh()}};
  inp.onkeydown=e=>{if(e.key==='Enter'||e.key===','||e.key===';'){e.preventDefault();addv()}else if(e.key==='Backspace'&&!inp.value&&arr.length){arr.pop();paint();onCh()}};inp.onblur=addv;
  w.appendChild(inp);w.onclick=e=>{if(e.target===w)inp.focus()};paint();return w}
function miniRate(obj,onCh){const m=el('div','mini');m.appendChild(el('span',null,'оценка'));const paint=()=>{m.querySelectorAll('button').forEach((b,i)=>{b.className=obj.rating==null?'':i<obj.rating?'f':i===obj.rating?'c':''})};
  for(let i=0;i<=10;i++){const b=el('button',null,String(i));b.title=i+'/10 · повторный клик — убрать';b.onclick=()=>{obj.rating=obj.rating===i?null:i;paint();onCh()};m.appendChild(b)}paint();return m}
function txt(obj,key,ph,max,cls){const i=el('input','in'+(cls?' '+cls:''));i.value=obj[key]||'';i.placeholder=ph||'';i.maxLength=max||300;i.oninput=()=>{obj[key]=i.value;qaDirty()};return i}
function sec(body,label,node,hint){const s=el('div','qsec');if(label||hint){const l=el('div','ql');l.appendChild(el('b',null,label));if(hint)l.appendChild(el('span',null,hint));s.appendChild(l)}else s.style.marginTop='-10px';if(node)s.appendChild(node);body.appendChild(s);return s}

/* ---------- entries (books / films / series) ---------- */
function entryCard(list,e,idx,whyOpts,whyLabel,repaint){const c=el('div','qent');const h=el('div','h');
  if(e.id){const t=el('div','tt',(e.author?e.author+' — ':'')+e.title);t.appendChild(el('small',null,e.meta||'в вашей библиотеке'));h.appendChild(t);h.appendChild(el('span','badge','в библиотеке'))}
  else if(whyOpts===QA.options.book_like||whyOpts===QA.options.book_dislike){const ed=el('div','ed');const a=txt(e,'author','Автор',200);a.setAttribute('list','dlAuthors');ed.appendChild(a);ed.appendChild(txt(e,'title','Название',300));h.appendChild(ed);h.appendChild(el('span','badge out','вне библиотеки'))}
  else{const t=el('div','ed');t.style.gridTemplateColumns='1fr';t.appendChild(txt(e,'title','Название',300));h.appendChild(t)}
  const x=el('button','x','×');x.title='убрать';x.onclick=()=>{list.splice(idx,1);qaDirty();repaint()};h.appendChild(x);c.appendChild(h);
  const l=el('div','ql');l.style.cssText='font-size:12px;color:var(--muted)';l.textContent=whyLabel;c.appendChild(l);
  e.why=e.why||[];c.appendChild(chipSet(whyOpts,e.why,qaDirty,whyOpts===QA.options.book_dislike?'neg':''));
  const r=el('div','r');r.appendChild(miniRate(e,qaDirty));r.appendChild(txt(e,'comment','Одной строкой: что запомнилось (необязательно)',400));c.appendChild(r);return c}
function bookStep(body,key,whyOpts,whyLabel,ph){const list=qa()[key];const wrap=el('div','qsec');
  const sb=el('div','qsearch');const qin=el('div','qin');qin.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8E98A5" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>';
  const inp=el('input');inp.placeholder=ph;inp.autocomplete='off';inp.spellcheck=false;qin.appendChild(inp);sb.appendChild(qin);const hits=el('div','hits');hits.hidden=true;sb.appendChild(hits);wrap.appendChild(sb);
  const cnt=el('div','qcount');wrap.appendChild(cnt);const ents=el('div','qents');wrap.appendChild(ents);body.appendChild(wrap);
  let H=[],act=0,seq=0,tmr=null,q='';
  const repaint=()=>{ents.innerHTML='';cnt.innerHTML=list.length?`Добавлено: <b>${list.length}</b>`+(key==='books_liked'&&list.length<3?' · хорошо бы ещё пару':''):'<span class="qhint">Начните вводить название или автора — подскажу из библиотеки. Любую другую книгу добавьте как «Автор — Название».</span>';
    for(let i=list.length-1;i>=0;i--)ents.appendChild(entryCard(list,list[i],i,whyOpts,whyLabel,repaint))};
  const has=(a,t,id)=>list.some(x=>(id&&x.id===id)||(norm(x.title).trim()===norm(t).trim()&&(!a||!x.author||norm(x.author)===norm(a))));
  const add=it=>{if(has(it.author,it.title,it.id)){toast('Уже в списке','warn');return}list.push({id:it.id||null,author:it.author||'',title:it.title,meta:it.meta||'',why:[],rating:null,comment:''});inp.value='';q='';hits.hidden=true;qaDirty();repaint();inp.focus()};
  const free=()=>{const s=q.trim();if(!s)return;const m=s.split(/\s+[—–-]\s+/);add(m.length>1?{author:m[0].trim(),title:m.slice(1).join(' — ').trim()}:{author:'',title:s})};
  const paint=()=>{hits.innerHTML='';if(!q){hits.hidden=true;return}H.forEach((it,i)=>{const h=el('div','hit'+(i===act?' sel':''));const t=el('span');t.appendChild(hl((it.author?it.author+' — ':'')+it.title,q));h.appendChild(t);
      const b=itemBadge(it);h.appendChild(el('span','badge '+b[1],b[0]));h.appendChild(el('small',null,itemSmall(it)));h.onmousedown=ev=>{ev.preventDefault();pick(i)};hits.appendChild(h)});
    const a=el('div','hit add'+(act===H.length?' sel':''));a.appendChild(el('span',null,'＋ Добавить «'+q+'» — любая книга'));a.appendChild(el('span','badge out','Enter'));a.appendChild(el('small',null,'формат «Автор — Название»; можно и без автора'));a.onmousedown=ev=>{ev.preventDefault();pick(H.length)};hits.appendChild(a);
    hits.hidden=false;hits.querySelector('.sel')?.scrollIntoView({block:'nearest'})};
  const pick=i=>{if(i>=H.length)return free();const it=H[i];add({id:it.custom?null:it.id,author:it.author,title:it.title,meta:it.custom?'':itemSmall(it)})};
  inp.oninput=()=>{clearTimeout(tmr);q=inp.value.trim();if(!q){H=[];paint();return}tmr=setTimeout(async()=>{const my=++seq;try{const j=await api('/api/search?q='+encodeURIComponent(q));if(my!==seq)return;H=j.results.filter(x=>x.source!=='read').slice(0,8);act=H.length?0:0;paint()}catch(e){}},90)};
  inp.onkeydown=e=>{const n=H.length+1;if(e.key==='ArrowDown'){e.preventDefault();act=(act+1)%n;paint()}else if(e.key==='ArrowUp'){e.preventDefault();act=(act-1+n)%n;paint()}
    else if(e.key==='Enter'){e.preventDefault();if(!q)return;pick(e.altKey?H.length:act)}else if(e.key==='Escape'){hits.hidden=true}};
  inp.onblur=()=>setTimeout(()=>{hits.hidden=true},150);inp.onfocus=()=>{if(q)paint()};repaint();setTimeout(()=>inp.focus(),30)}
function titleStep(body,key,whyOpts,ph,gKey,gOpts,gLabel){const list=qa()[key];const wrap=el('div','qsec');const row=el('div','qsearch');const qin=el('div','qin');const inp=el('input');inp.placeholder=ph;inp.autocomplete='off';qin.appendChild(inp);
  const b=el('button','ghost sm','Добавить');qin.appendChild(b);row.appendChild(qin);wrap.appendChild(row);const cnt=el('div','qcount');wrap.appendChild(cnt);const ents=el('div','qents');wrap.appendChild(ents);body.appendChild(wrap);
  const repaint=()=>{ents.innerHTML='';cnt.innerHTML=list.length?`Добавлено: <b>${list.length}</b>`:'<span class="qhint">Название и Enter. Год или режиссёра можно дописать в скобках.</span>';for(let i=list.length-1;i>=0;i--)ents.appendChild(entryCard(list,list[i],i,whyOpts,'Чем понравился',repaint))};
  const add=()=>{const t=inp.value.trim();if(!t)return;if(list.some(x=>norm(x.title)===norm(t))){toast('Уже в списке','warn');return}list.push({title:t.slice(0,300),why:[],rating:null,comment:''});inp.value='';qaDirty();repaint();inp.focus()};
  inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();add()}};b.onclick=add;repaint();sec(body,gLabel,chipSet(gOpts,qa()[gKey],qaDirty));setTimeout(()=>inp.focus(),30)}

/* ---------- steps ---------- */
const STEPR={
 books_liked:b=>bookStep(b,'books_liked',QA.options.book_like,'Чем понравилась','Книга или автор — «Процесс», «Ремарк», «Стругацкие Пикник»…'),
 books_disliked:b=>bookStep(b,'books_disliked',QA.options.book_dislike,'Что не так','Книга, которая не зашла…'),
 prefs:b=>{const p=qa().prefs;sec(b,'Жанры',chipSet(QA.options.genres,p.genres,qaDirty),'сколько угодно');const g=txt(p,'genres_text','Другое: например «киберпанк, магический реализм»',300);sec(b,'',g);
   sec(b,'Длина',chipSet(QA.options.length,p.length,qaDirty));sec(b,'Формат',chipSet(QA.options.format,p.format,qaDirty));
   sec(b,'Язык',chipSet(QA.options.lang.map(x=>[x,LANGL[x]||x]),p.lang,qaDirty),'на каком готовы слушать');sec(b,'Когда слушаете',chipSet(QA.options.listen,p.listen,qaDirty));
   sec(b,'Любимые чтецы',txt(p,'narrators','Например: Князев, Клюквин, Терновский',300))},
 films:b=>titleStep(b,'films',QA.options.film_like,'Фильм — «Интерстеллар», «Семь», «Остров проклятых»…','film_genres',QA.options.film_genres,'Любимые жанры кино'),
 series:b=>titleStep(b,'series',QA.options.film_like,'Сериал — «Настоящий детектив», «Тьма», «Чернобыль»…','series_genres',QA.options.series_genres,'Любимые жанры сериалов'),
 games:b=>titleStep(b,'games',QA.options.game_like,'Игра — «Disco Elysium», «Half-Life 2», «Ведьмак 3»…','game_genres',QA.options.game_genres,'Любимые жанры игр'),
 travel:b=>{const t=qa().travel;sec(b,'Где были и понравилось',freeChips(t.been,'Страна или город, Enter',qaDirty));sec(b,'Куда хотели бы',freeChips(t.want,'Страна или город, Enter',qaDirty));
   sec(b,'Тип отдыха',chipSet(QA.options.travel_types,t.types,qaDirty));sec(b,'Темп',oneOf(QA.options.travel_pace,t,'pace',qaDirty));sec(b,'Комментарий',txt(t,'text','Что запомнилось больше всего (необязательно)',400))},
 music:b=>{const a=qa();sec(b,'Музыка',chipSet(QA.options.music,a.music.chips,qaDirty));sec(b,'',txt(a.music,'text','Любимые исполнители или вещи: «Бетховен 9», «Циммер», «Кипелов»…',500));
   sec(b,'Интересы',chipSet(QA.options.interests,a.interests.chips,qaDirty));sec(b,'',txt(a.interests,'text','Подробнее: «ML и DevOps», «алгебраическая топология»…',500))},
 about:b=>{const a=qa().about;if(!a.name&&profCur()&&!profCur().is_default)a.name=profCur().name;
   sec(b,'Профессия или сфера',txt(a,'profession','Например: DevOps-инженер, врач, студент-физик',200));sec(b,'Где живёте',txt(a,'location','Город, страна',200));
   const g=el('div','grid');const lab=(t,n)=>{const l=el('label',null,t);l.appendChild(n);g.appendChild(l)};lab('Имя (так будет называться профиль)',txt(a,'name','Имя',40));lab('Возраст',txt(a,'age','34 или 30–35',20));sec(b,'',g);
   sec(b,'Образование',chipSet(QA.options.education,a.education,qaDirty));sec(b,'',txt(a,'education_text','Специальность (необязательно)',200));
   sec(b,'Семья',chipSet(QA.options.family,a.family,qaDirty));sec(b,'',txt(a,'family_text','Подробнее, если хочется: «сын 6 лет»',200))},
 worldview:b=>{const w=qa().worldview;for(const q of QA.worldview){const s=sec(b,q.label,oneOf(q.options,w[q.key],'v',qaDirty));s.appendChild(txt(w[q.key],'text','Свой вариант или комментарий (необязательно)',300,'sm'))}},
 summary:b=>renderSummary(b)};
function renderSummary(b){const L=(QA.lines||[]).filter(x=>x.key!=='brief');const box=el('div','qsum');
  if(!L.length&&!(QA.answers||{}).brief)b.appendChild(el('div','qempty','Анкета пока пустая. Добавьте хотя бы пару книг — это главное для подбора.'));
  for(const x of L){const r=el('div','it');r.appendChild(el('span','k',x.label));r.appendChild(el('span','v',x.text));const e=el('button','ghost sm','Изменить');e.onclick=()=>goStep(LINE2STEP[x.key]??0);r.appendChild(e);box.appendChild(r)}
  if(L.length)b.appendChild(box);if((QA.answers||{}).brief){const d=el('details');d.appendChild(el('summary','sub','+ бриф этого профиля (BRIEF-COMMON.md) тоже будет учтён'));d.appendChild(el('div','brief',QA.answers.brief));b.appendChild(d)}
  const nrev=(profCur()||{}).reviews||0;const go=el('div','qgo');const tx=el('div','tx');
  tx.innerHTML=`<b>Что будет дальше.</b> Claude прочитает анкету${nrev?`, ваши отзывы (${nrev}, свежие весят больше)`:''} и каталог библиотеки, при необходимости поищет в интернете, есть ли подходящие аудиокниги вне библиотеки. Обычно 1–4 минуты; можно уйти на другую вкладку.`;
  go.appendChild(tx);const bt=el('button','bigbtn','Составить профиль и топ-5');bt.disabled=!L.length&&!nrev&&!(QA.answers||{}).brief;bt.onclick=()=>submitRun(bt);go.appendChild(bt);b.appendChild(go)}
function renderForm(){const box=$('#qaBox');box.innerHTML='';const st=QSTEPS[QSTEP];qa();
  const hd=el('div','qhead');const top=el('div','qrow');top.appendChild(el('span','qstep',`Шаг ${QSTEP+1} из ${QSTEPS.length} · ${st.t}`));const sv=el('span','qsaved');sv.id='qaSaved';sv.textContent=QA.updated?'черновик · '+fmtDT(QA.updated):'';top.appendChild(sv);hd.appendChild(top);
  const bar=el('div','qbar');const f=el('i');f.style.width=Math.round(100*(QSTEP+1)/QSTEPS.length)+'%';bar.appendChild(f);hd.appendChild(bar);
  const dots=el('div','qdots');QSTEPS.forEach((x,i)=>{const d=el('button','qdot'+(i===QSTEP?' on':'')+(i<QSTEPS.length-1&&filled(x.k)?' done':''),x.t.replace('Книги, которые понравились','Любимые книги').replace('Книги, которые не понравились','Не понравились').replace('Книжные предпочтения','Предпочтения'));d.onclick=()=>goStep(i);dots.appendChild(d)});hd.appendChild(dots);box.appendChild(hd);
  const card=el('div','qcard');card.appendChild(el('h3','qt',st.t));card.appendChild(el('p','sub',st.s));const body=el('div','qbody');card.appendChild(body);box.appendChild(card);STEPR[st.k](body);
  const ft=el('div','qfoot');const back=el('button','ghost','← Назад');back.hidden=QSTEP===0;back.onclick=()=>goStep(QSTEP-1);ft.appendChild(back);
  if(QA.source==='brief'||AIST&&AIST.latest){const c=el('button','linkbtn','Закрыть анкету');c.onclick=async()=>{await qaFlush();QMODE=AIST&&AIST.latest?'result':'brief';renderAnketa()};ft.appendChild(c)}
  ft.appendChild(el('span','spacer'));
  if(QSTEP<QSTEPS.length-1){const sk=el('button','linkbtn','Пропустить');sk.onclick=()=>goStep(QSTEP+1);ft.appendChild(sk);const nx=el('button','btn','Далее →');nx.onclick=()=>goStep(QSTEP+1);ft.appendChild(nx)}
  box.appendChild(ft)}
async function submitRun(btn){btn.disabled=true;try{await qaFlush();const j=await post('/api/questionnaire/submit',{answers:QA.answers,step:QSTEP});QA.lines=j.lines;QA.status=j.status;QA.source=j.source;if(j.out)applyOut(j.out);
    await startAi('initial')}catch(e){toast(e.message,'err');btn.disabled=false}}
async function startAi(kind){try{await post('/api/ai/run',{kind});QMODE='running';VIEWRUN=null;AIST=await api('/api/ai/status');await loadProfiles();
    if(VIEW==='anketa')renderAnketa();else if(VIEW==='next')loadAiPinned();toast(kind==='refresh'?'Claude пересматривает топ-5…':'Claude составляет профиль…');aiTick()}catch(e){toast(e.message,'err');throw e}}

/* ---------- running ---------- */
const mmss=s=>{s=Math.max(0,Math.floor(s));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')};
let RUNT=null;
function renderRunning(){const box=$('#qaBox');const j=AIST&&AIST.job;if(!j){QMODE=AIST&&AIST.latest?'result':'form';return renderAnketa()}
  let r=$('#qaRun');if(!r){box.innerHTML='';r=el('div','qrun');r.id='qaRun';r.innerHTML='<h3 id="qrT"></h3><div class="tm" id="qrTm">00:00</div><div class="ibar"><i></i></div><div class="ph" id="qrPh"></div><div class="qev" id="qrEv"></div>';
    const c=el('button','ghost','Отменить');c.onclick=async()=>{c.disabled=true;try{await post('/api/ai/cancel',{});toast('Отменяю…','warn')}catch(e){toast(e.message,'err')}};r.appendChild(c);
    r.appendChild(el('p','sub','Обычно 1–4 минуты (не больше 6). Можно перейти на другую вкладку — результат появится здесь и в «Что дальше».'));box.appendChild(r)}
  $('#qrT').textContent=j.kind==='refresh'?'Claude пересматривает топ-5 с учётом отзывов':'Claude составляет ваш профиль и топ-5';
  $('#qrPh').textContent=j.phase+(j.attempt>1?' · попытка '+j.attempt:'');const ev=$('#qrEv');ev.innerHTML='';
  for(const e of j.events.slice(-6)){const d=el('div');d.appendChild(el('span',null,mmss(e.t)));d.appendChild(el('b',null,e.kind==='search'?'поиск':'страница'));d.appendChild(el('em',null,e.kind==='search'?'«'+e.text+'»':e.text.replace(/^https?:\/\//,'')));ev.appendChild(d)}
  const t0=Date.now()-j.elapsed*1000;clearInterval(RUNT);const tick=()=>{const t=$('#qrTm');if(!t){clearInterval(RUNT);return}t.textContent=mmss((Date.now()-t0)/1000)};tick();RUNT=setInterval(tick,500)}
async function aiTick(){clearTimeout(AIPOLL);const my=PROFILE;let s;try{s=await api('/api/ai/status')}catch(e){AIPOLL=setTimeout(aiTick,4000);return}if(my!==PROFILE)return;
  const was=!!(AIST&&AIST.job);AIST=s;
  if(s.job){if(VIEW==='anketa'&&QA){QMODE='running';renderRunning()}if(VIEW==='next')paintPinned();AIPOLL=setTimeout(aiTick,VIEW==='anketa'?1000:2500);if(!was)loadProfiles();return}
  if(was){clearInterval(RUNT);await loadProfiles();const h=s.history[0];
    if(h&&h.status==='done'){toast('Готово: профиль и топ-5 обновлены'+(h.duration_sec?' · '+mmss(h.duration_sec):''));QMODE='result';VIEWRUN=null}
    else{toast(h&&h.status==='cancelled'?'Подбор отменён':'Не получилось: '+(h&&h.error||'ошибка'),h&&h.status==='cancelled'?'warn':'err');QMODE=h&&h.status==='cancelled'?(s.latest?'result':'form'):'problem'}
    if(VIEW==='anketa'&&QA)renderAnketa();if(VIEW==='next')loadAiPinned();refreshMeta()}}

/* ---------- result ---------- */
function linkify(parent,text){const re=/https?:\/\/[^\s<>()«»"]+[^\s<>()«»".,;:!?]/g;let i=0,m;while((m=re.exec(text))){parent.appendChild(document.createTextNode(text.slice(i,m.index)));const a=el('a',null,m[0].replace(/^https?:\/\/(www\.)?/,'').slice(0,60));a.href=m[0];a.target='_blank';a.rel='noopener noreferrer';parent.appendChild(a);i=m.index+m[0].length}parent.appendChild(document.createTextNode(text.slice(i)))}
function qBtn(it,small){const b=el('button','ghost'+(small?' sm':'')+(it&&it.in_queue?' on':''),it&&it.in_queue?'✓ в очереди':'+ в очередь');if(!it){b.disabled=true;return b}
  b.onclick=async e=>{e.stopPropagation();try{const j=await post('/api/queue',{op:it.in_queue?'remove':'add',item_id:it.id});it.in_queue=!it.in_queue;b.textContent=it.in_queue?'✓ в очереди':'+ в очередь';b.classList.toggle('on',it.in_queue);applyOut(j.out);refreshMeta();loadProfiles()}catch(er){toast(er.message,'err')}};return b}
function runMeta(r){return ['Claude'+(r.model?' ('+r.model+')':''),fmtDT(r.finished||r.started),r.duration_sec?mmss(r.duration_sec):'',r.kind==='refresh'?'пересмотр с учётом отзывов':'по анкете'].filter(Boolean).join(' · ')}
async function renderResult(){const box=$('#qaBox');let run=AIST&&AIST.latest;
  if(VIEWRUN&&(!run||VIEWRUN!==run.id)){try{run=await api('/api/ai/run?id='+VIEWRUN)}catch(e){VIEWRUN=null}}
  if(!run||!run.result){QMODE=QA.source==='brief'?'brief':'form';return renderAnketa()}
  const R=run.result,P=R.profile||{};box.innerHTML='';const wrap=el('div','ares');box.appendChild(wrap);
  if(VIEWRUN&&AIST.latest&&VIEWRUN!==AIST.latest.id){const v=el('div','vbanner');v.appendChild(el('span',null,'Вы смотрите прежний подбор от '+fmtDT(run.finished)+'.'));const bk=el('button','ghost sm','К последнему');bk.onclick=()=>{VIEWRUN=null;renderAnketa()};v.appendChild(bk);wrap.appendChild(v)}
  const h1=el('div','arh');const t=el('div');t.appendChild(el('h3',null,'Ваш профиль'));t.appendChild(el('div','sub',runMeta(run)));h1.appendChild(t);wrap.appendChild(h1);
  const pc=el('div','pcard');if(P.summary)pc.appendChild(el('p','sm',P.summary));
  if((P.taste_axes||[]).length){const ax=el('div','axes');for(const a of P.taste_axes){const d=el('div','axis');d.appendChild(el('b',null,a.axis));d.appendChild(el('span',null,a.value));if(a.evidence)d.appendChild(el('small',null,a.evidence));ax.appendChild(d)}pc.appendChild(ax)}
  const lv=el('div','lv');const col=(tt,arr,cls)=>{const c=el('div');c.appendChild(el('h4',null,tt));const ch=el('div','chips');(arr||[]).forEach(x=>{const s=el('span','chip on '+cls,x);s.style.cursor='default';ch.appendChild(s)});c.appendChild(ch);lv.appendChild(c)};
  col('Любите',P.loves,'pos');col('Лучше избегать',P.avoid,'neg');pc.appendChild(lv);if(P.listening_context){const c=el('div','ctx');c.appendChild(el('b',null,'Как вы слушаете: '));c.appendChild(document.createTextNode(P.listening_context));pc.appendChild(c)}wrap.appendChild(pc);
  const h2=el('div','arh');h2.appendChild(el('h3',null,'Топ-5 из вашей библиотеки'));wrap.appendChild(h2);
  (R.top5||[]).forEach((x,i)=>{const it=x.item;const c=el('div','t5');c.appendChild(el('div','rk',String(i+1)));const bd=el('div','bd');
    const ti=el('div','ti',it?(it.author?it.author+' — ':'')+it.title:x.id);ti.onclick=()=>openItem(x.id);bd.appendChild(ti);if(it)bd.appendChild(el('div','mt',[it.section,it.bucket?LENL[it.bucket]:'',fmtH(it.hours,it.hours_exact),it.narrator,(DL[it.status]||DL.pending)[0],it.rstatus?'отзыв: '+STL[it.rstatus]:''].filter(Boolean).join(' · ')));
    bd.appendChild(el('div','wy',x.why));if(x.confidence!=null){const cf=el('div','conf');const cb=el('span','cb');const ii=el('i');ii.style.width=Math.round(x.confidence*100)+'%';cb.appendChild(ii);cf.appendChild(cb);cf.appendChild(el('span',null,'уверенность '+Math.round(x.confidence*100)+'%'));bd.appendChild(cf)}
    const r=el('div','row');r.style.marginTop='4px';const o=el('button','ghost sm','Открыть карточку');o.onclick=()=>openItem(x.id);r.appendChild(o);r.appendChild(qBtn(it,true));
    if(it&&it.has_file){const pl=el('button','ghost sm','▶ слушать');pl.onclick=()=>post('/api/open',{item_id:it.id,what:'file'}).then(()=>toast('Открываю в плеере…')).catch(e=>toast(e.message,'err'));r.appendChild(pl)}bd.appendChild(r);c.appendChild(bd);wrap.appendChild(c)});
  if((R.outside_library||[]).length){const h3=el('div','arh');h3.appendChild(el('h3',null,'Вне библиотеки'));h3.appendChild(el('span','sub','Claude проверял наличие аудиокниг в интернете'));wrap.appendChild(h3);const ol=el('div','olist');
    for(const o of R.outside_library){const c=el('div','oc');c.appendChild(el('div','ti',(o.author?o.author+' — ':'')+'«'+o.title+'»'));c.appendChild(el('div','wy',o.why));if(o.where_to_find){const w=el('div','wf');w.appendChild(document.createTextNode('Где найти: '));linkify(w,o.where_to_find);c.appendChild(w)}ol.appendChild(c)}wrap.appendChild(ol)}
  if((R.questions_to_refine||[]).length){const p=el('div','panel');p.appendChild(el('h3',null,'Что уточнить, чтобы подбор стал точнее'));const ol=el('ol','qq');R.questions_to_refine.forEach(q=>ol.appendChild(el('li',null,q)));p.appendChild(ol);
    p.appendChild(el('p','sub','Ответьте в анкете (например, в комментариях) или просто оцените пару книг — и запросите новый топ-5.'));wrap.appendChild(p)}
  const act=el('div','qgo');const tx=el('div','tx');const nrev=(profCur()||{}).reviews||0;tx.innerHTML='<b>Новый топ-5 с учётом отзывов</b> — только по кнопке: Claude прочитает полный файл для ИИ этого профиля (все отзывы'+(nrev?' — сейчас '+nrev:'')+', анкету, прошлые советы) и не повторит без причины то, что уже советовал.';act.appendChild(tx);
  const rb=el('button','bigbtn','Новый топ-5 с учётом отзывов');rb.onclick=()=>{rb.disabled=true;startAi('refresh').catch(()=>{rb.disabled=false})};act.appendChild(rb);const eb=el('button','ghost','Изменить анкету');eb.onclick=()=>{QMODE='form';QSTEP=0;renderAnketa()};act.appendChild(eb);wrap.appendChild(act);
  if((run.notes||[]).length){const d=el('details');d.appendChild(el('summary','sub','Проверка ответа ('+run.notes.length+')'));const u=el('ul','qq');u.style.fontSize='12.5px';run.notes.forEach(n=>u.appendChild(el('li',null,n)));d.appendChild(u);wrap.appendChild(d)}
  const hist=(AIST.history||[]);if(hist.length){const p=el('div','panel');p.appendChild(el('h3',null,'История подборов ('+hist.length+')'));const hl=el('div','hlist');
    for(const h of hist){const b=el('button','hrow'+(h.id===run.id?' on':''));b.appendChild(el('span','d',fmtDT(h.started)));b.appendChild(el('span','k',h.kind==='refresh'?'пересмотр':'по анкете'));b.appendChild(el('span','t',h.titles.join(' · ')||h.error||''));
      b.appendChild(el('span','s '+(h.status==='done'?'ok':h.status==='running'?'':'err'),h.status==='done'?(h.duration_sec?mmss(h.duration_sec):'готово'):h.status==='running'?'идёт':h.status==='cancelled'?'отменён':'ошибка'));
      if(h.status==='done')b.onclick=()=>{VIEWRUN=h.id;renderAnketa();window.scrollTo(0,0)};else b.style.cursor='default';hl.appendChild(b)}p.appendChild(hl);wrap.appendChild(p)}}
function renderBrief(){const box=$('#qaBox');box.innerHTML='';const p=el('div','qcard');p.appendChild(el('h3','qt','Анкета этого профиля — бриф'));
  p.appendChild(el('p','sub','Для профиля «'+(profCur()||{}).name+'» анкету заменяет бриф из BRIEF-COMMON.md (раздел «Кто слушатель») — он считается уже заполненной анкетой. Можно сразу составить профиль и топ-5 или дополнить бриф анкетой.'));
  p.appendChild(el('div','brief',(QA.answers||{}).brief||''));const r=el('div','row');r.style.marginTop='10px';const go=el('button','bigbtn','Составить профиль и топ-5');go.onclick=()=>{go.disabled=true;startAi('initial').catch(()=>{go.disabled=false})};r.appendChild(go);
  const f=el('button','ghost','Пройти анкету (дополнить бриф)');f.onclick=()=>{QMODE='form';QSTEP=0;renderAnketa()};r.appendChild(f);p.appendChild(r);box.appendChild(p)}
function renderProblem(){const box=$('#qaBox');box.innerHTML='';const h=(AIST&&AIST.history||[])[0];const p=el('div','problem');p.appendChild(el('div','tx','Подбор не получился: '+((h&&h.error)||'неизвестная ошибка')+'. Анкета сохранена.'));
  const r=el('button','btn','Попробовать ещё раз');r.onclick=()=>{r.disabled=true;startAi(h&&h.kind||'initial').catch(()=>{r.disabled=false})};p.appendChild(r);const f=el('button','ghost','К анкете');f.onclick=()=>{QMODE='form';renderAnketa()};p.appendChild(f);box.appendChild(p);
  if(AIST.latest){const b=el('button','linkbtn','Показать прошлый удачный подбор');b.onclick=()=>{QMODE='result';renderAnketa()};box.appendChild(b)}}

/* ---------- pinned block in «Что дальше» ---------- */
async function loadAiPinned(){const my=PROFILE;try{AIST=await api('/api/ai/status');if(my!==PROFILE)return;paintPinned();if(AIST.job)aiTick()}catch(e){$('#nxAi').innerHTML=''}}
function paintPinned(){const box=$('#nxAi');box.innerHTML='';const s=AIST;if(!s)return;const r=s.latest;
  if(s.job){const p=el('div','aipin slim');p.appendChild(el('div','tx','Claude '+(s.job.kind==='refresh'?'пересматривает топ-5':'составляет профиль и топ-5')+' · '+mmss(s.job.elapsed)+' · '+s.job.phase));const b=el('button','ghost sm','Смотреть');b.onclick=()=>show('anketa');p.appendChild(b);box.appendChild(p);return}
  if(!r){const p=el('div','aipin slim');p.appendChild(el('div','tx','Рекомендаций ИИ пока нет. Заполните анкету — Claude составит ваш профиль и топ-5 из библиотеки.'));const b=el('button','btn','Открыть анкету');b.onclick=()=>show('anketa');p.appendChild(b);box.appendChild(p);return}
  const p=el('div','aipin');const hd=el('div','hd');hd.appendChild(el('h3',null,'Рекомендации ИИ ('+new Date(r.finished).toLocaleDateString('ru-RU',{day:'numeric',month:'short'})+')'));
  hd.appendChild(el('span','sub',runMeta(r)));hd.appendChild(el('span','spacer'));const more=el('button','ghost sm','Профиль и подробности');more.onclick=()=>{QMODE='result';VIEWRUN=null;show('anketa')};hd.appendChild(more);
  const nb=el('button','ghost sm','Новый топ-5 с учётом отзывов');nb.title='Использует Claude (через Claude Code) и интернет; только по кнопке';nb.onclick=()=>{nb.disabled=true;startAi('refresh').catch(()=>{nb.disabled=false})};hd.appendChild(nb);p.appendChild(hd);
  (r.result.top5||[]).forEach((x,i)=>{const it=x.item;const row=el('div','pi');row.appendChild(el('div','n',String(i+1)));const b=el('div','b');const t=el('div','t',it?(it.author?it.author+' — ':'')+it.title:x.id);t.onclick=()=>openItem(x.id);b.appendChild(t);
    b.appendChild(el('div','w',x.why));row.appendChild(b);if(it&&it.rstatus&&it.rstatus!=='want')row.appendChild(el('span','badge',STL[it.rstatus]));else row.appendChild(qBtn(it,true));p.appendChild(row)});
  box.appendChild(p);const hint=el('p','sub','Ниже — детерминированный подбор по формуле, без ИИ.');hint.style.margin='2px 0 0';box.appendChild(hint)}
'''
