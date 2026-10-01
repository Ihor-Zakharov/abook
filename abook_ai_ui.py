"""SPA additions for `abook review`: profile switcher, «Анкета» (questionnaire stepper), Claude results,
the pinned AI block in «Что дальше». Injected into REVIEW_HTML at the /*AI:…*/ and <!--AI:…--> markers
by abook_ai.inject_html(). Uses the page's helpers ($, el, esc, api, post, toast, show, openItem…)."""

CSS = r'''
/* AI additions on cosmos-kit: warm monochrome plates; the AI section inherits the site's gold light (no cold accents) */
.prof{position:relative;width:46px}
/* the profile switch in the icon rail: the avatar is the button; the name and the counts come as the tooltip and in the menu */
.profbtn{width:46px;height:40px;display:grid;place-items:center;border-radius:var(--r-m);background:transparent;border:1px solid transparent;transition:border-color var(--t-fast),background-color var(--t-fast)}
@media (hover:hover){.profbtn:hover{border-color:var(--line-2);background:var(--s2)}}
.profbtn[aria-expanded="true"]{border-color:var(--line-2);background:var(--s3)}
.profbtn .pn,.profbtn>svg{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.av{flex:none;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font:600 13px/1 var(--font-display);background:var(--s4);box-shadow:inset 0 0 0 1px var(--line-2);color:var(--ink);user-select:none}
/* the menu opens to the right of the rail, over every column (the rail is above the page; nothing clips it) */
.pmenu{position:absolute;left:calc(100% + 10px);top:0;z-index:60;width:max-content;min-width:260px;max-width:360px;background:var(--s-raised);border:1px solid var(--line-2);border-radius:14px;padding:6px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:2px}
.pmenu .pmh{padding:8px 10px 6px;font:500 11px/1.2 var(--font-mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3)}
.pmi,.pma{display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;border-radius:9px;font-size:13.5px;color:var(--ink-2);text-align:left}
.pmi:hover,.pma:hover,.pmi:focus-visible,.pma:focus-visible{background:var(--surface-2);color:var(--ink);outline:none}
.pmi.on{background:var(--surface)}
.pmi .pmt{display:flex;flex-direction:column;min-width:0;flex:1;line-height:1.3}.pmi .pmt b{font-weight:600;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pmi .pmt small{font:500 11px/1.3 var(--font-mono);color:var(--ink-3)}
.pmi .chk{color:var(--ink);display:grid;place-items:center}.pmi .chk svg,.pma>svg{width:15px;height:15px;flex:none;color:var(--ink-2)}
.pma.danger{color:var(--ink-2)}.pma.danger:hover{color:var(--err)}.pma[disabled]{opacity:.4;cursor:default;background:none}
.psep{height:1px;background:var(--line-1);margin:4px 2px}
.modal-box h3{margin:0;font:700 22px/1.2 var(--font-display);letter-spacing:-.02em;color:var(--ink)}
.mbody{display:flex;flex-direction:column;gap:12px}
.mbody .in{width:100%}.mbody p{margin:0;color:var(--ink-2);font-size:14.5px;line-height:1.5}.mbody ul{margin:0;padding-left:18px;color:var(--ink-2);font-size:14px;line-height:1.6}
.merr{color:var(--err);font-size:13.5px;margin-top:12px}
.qtop{display:grid;justify-items:center;text-align:center;gap:12px}
.qtop .vh{justify-items:center;margin-bottom:0}
.aibadge{display:inline-flex;align-items:center;gap:8px;font:500 11px/1 var(--font-mono);color:var(--ink-2);background:var(--plate);border:1px solid var(--line-2);border-radius:999px;padding:8px 12px;white-space:nowrap}
.aibadge i{width:6px;height:6px;border-radius:50%;background:var(--el-a);box-shadow:var(--el-glow);display:inline-block}
.qhead{display:flex;flex-direction:column;gap:10px}
.qsaved{font-size:13px;color:var(--ink-3);white-space:nowrap}
/* две дороги в анкету */
.qfill{display:flex;justify-content:center;margin:0 0 18px}
#qText{min-height:260px;font-size:15.5px;line-height:1.6}
.qfoot{display:flex;align-items:center;gap:14px;margin-top:14px}
/* steps: number + short label, joined by hairlines that take the free space — the row runs edge to edge of the card with even gaps */
.qdots{display:flex;align-items:center;gap:8px;min-width:0}
.qdots .qsep{flex:1 1 12px;min-width:8px;height:1px;background:var(--line-2)}
.qdot{flex:none;display:flex;align-items:center;gap:9px;height:38px;padding:0 12px 0 8px;border-radius:999px;color:var(--ink-2);border:1px solid transparent;font-size:14px;
  transition:color var(--t-base),background-color var(--t-base),border-color var(--t-base)}
.qdot .n{flex:none;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font:600 12px/1 var(--font-mono);box-shadow:inset 0 0 0 1px var(--line-3);color:var(--ink-2)}
.qdot .l{white-space:nowrap}
@media (hover:hover){.qdot:hover{color:var(--ink);background:var(--surface)}}
.qdot.on{color:var(--ink);background:var(--surface-2);border-color:var(--line-2)}.qdot.on .n{box-shadow:inset 0 0 0 1.5px var(--ink);color:var(--ink)}
.qdot.on.done .n{box-shadow:none;color:var(--bg)}
@media (max-width:1100px){.qdot:not(.on) .l{display:none}.qdot:not(.on){padding:0 7px}}
@media (max-width:760px){.qdots{gap:4px}.qdots .qsep{min-width:4px}.qdot:not(.on){padding:0;border-width:0}.qdot{height:34px}.qdot.on{padding:0 10px 0 5px}}
.qcard{background:linear-gradient(180deg,rgba(255,226,180,.035),transparent 36%),var(--plate);border:1px solid var(--line-2);border-radius:var(--r-xl);padding:26px 26px 24px;display:flex;flex-direction:column;gap:6px}
.qcard h3.qt{margin:0;font:700 26px/1.15 var(--font-display);letter-spacing:-.025em;color:var(--ink)}
.qcard>.sub{font-size:15px;line-height:1.55;color:var(--ink-2);max-width:62ch}
.qbody{display:flex;flex-direction:column;gap:22px;margin-top:14px}
.qsec{display:flex;flex-direction:column;gap:10px}
.qsec>.ql{display:flex;align-items:baseline;gap:10px;font:600 14.5px/1.35 var(--font-text);color:var(--ink)}
.qsec>.ql b{font-weight:600}.qsec>.ql span{font-weight:400;font-size:13px;color:var(--ink-3)}
.qbody .grid{grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}
.qbody .grid label{font:600 14.5px/1.35 var(--font-text);letter-spacing:0;text-transform:none;color:var(--ink);gap:8px}
.qsec>.in.sm{max-width:560px;height:36px;font-size:14px}
.chip.more{background:transparent;box-shadow:inset 0 0 0 1px var(--line-1);color:var(--ink-3)}
.chip.more:hover{color:var(--ink)}
/* a titled group inside a step: hairline + heading, always open */
.qgroup{border-top:1px solid var(--line-1);padding-top:18px}
.qgroup>h4{margin:0;font:700 17px/1.3 var(--font-display);letter-spacing:-.015em;color:var(--ink)}
.qgroup>.qbody{margin-top:14px}
.qtabs{align-self:flex-start}.qtabs small{font:500 11px/1 var(--font-mono);color:var(--ink-3);margin-left:2px}
.qfoot{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:22px;padding-top:18px;border-top:1px solid var(--line-1)}
.qsearch{position:relative}
.qsearch .qin{display:flex;align-items:center;gap:10px;background:var(--s1);border:1px solid var(--line-2);border-radius:var(--r-l);padding:4px 6px 4px 14px;transition:border-color var(--t-fast),box-shadow var(--t-base) var(--ease-out)}
.qsearch .qin:focus-within{border-color:color-mix(in oklab,var(--el-a) 60%,transparent);box-shadow:var(--focus-ring)}
.qsearch .qin svg{width:18px;height:18px;color:var(--ink-3)}
.qsearch input{flex:1;background:none;border:0;outline:none;font-size:16px;padding:10px 0;min-width:0;color:var(--ink)}
.qsearch input:focus-visible{outline:none;box-shadow:none}
.qsearch .hits{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:20;max-height:360px;overflow:auto}
.qcount{font-size:13.5px;color:var(--ink-2);min-height:20px}.qcount b{color:var(--ink);font-family:var(--font-mono);font-weight:500}
.qents{display:flex;flex-direction:column;gap:10px}
.qent{background:var(--s1);border:1px solid var(--line-1);border-radius:var(--r-l);padding:14px 16px;display:flex;flex-direction:column;gap:12px;animation:qin .5s var(--ease-out)}
@keyframes qin{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.qent .h{display:flex;align-items:flex-start;gap:10px}
.qent .h .tt{flex:1;min-width:0;font-weight:500;font-size:15px;line-height:1.35;color:var(--ink)}
.qent .h .tt small{display:block;font:500 11.5px/1.4 var(--font-mono);color:var(--ink-3);margin-top:3px}
.qent .h .ed{flex:1;display:grid;grid-template-columns:1fr 1.4fr;gap:6px}
.qent .h .ed .in{height:36px;font-size:14px}
.qent .x{color:var(--ink-3);width:32px;height:32px;border-radius:var(--r-s);display:grid;place-items:center;flex:none}
.qent .x:hover{color:var(--err);background:var(--s3)}
.qent .r{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.qent .r .in{flex:1;min-width:200px;height:34px;font-size:13.5px}
.mini{display:flex;gap:2px;align-items:center}
.mini span{font:500 13px/1 var(--font-text);color:var(--ink-2);margin-right:8px}
.mini button{width:30px;height:32px;border-radius:6px;background:var(--s2);font:500 13px/32px var(--font-mono);text-align:center;color:var(--ink-2);font-variant-numeric:tabular-nums;transition:background-color var(--t-base),color var(--t-base)}
@media (hover:hover){.mini button:hover{background:var(--s3);color:var(--ink)}}
.mini button.f{background:color-mix(in oklab,var(--el-a) 24%,var(--s2));color:var(--ink)}.mini button.c{background:var(--el-a);color:#1a1206;font-weight:600;box-shadow:var(--el-glow)}
.fchips{display:flex;gap:6px;flex-wrap:wrap;align-items:center;background:var(--s1);border:1px solid var(--line-2);border-radius:var(--r-m);padding:6px 8px;min-height:44px;transition:border-color var(--t-fast),box-shadow var(--t-base) var(--ease-out)}
.fchips:focus-within{border-color:color-mix(in oklab,var(--el-a) 60%,transparent);box-shadow:var(--focus-ring)}
.fchips .fc{display:inline-flex;align-items:center;gap:4px;font-size:13px;height:28px;padding:0 4px 0 10px;border-radius:var(--r-s);background:var(--s4);color:var(--ink)}
.fchips .fc .fcx{display:grid;place-items:center;width:22px;height:22px;border-radius:var(--r-xs);color:var(--ink-3)}.fchips .fc .fcx:hover{color:var(--err)}.fchips .fc .fcx svg{width:12px;height:12px}
.fchips input{flex:1;min-width:160px;background:none;border:0;outline:none;padding:4px 2px;font-size:14px;color:var(--ink)}
.fchips input:focus-visible{outline:none;box-shadow:none}
.qhint{font-size:13.5px;color:var(--ink-2)}
.qsum{display:flex;flex-direction:column}
.qsum .it{display:grid;grid-template-columns:170px minmax(0,1fr) auto;gap:14px;padding:12px 0;border-bottom:1px solid var(--line-1);align-items:baseline;font-size:14px}
.qsum .it:last-child{border-bottom:0}.qsum .it .k{font:500 13.5px/1.4 var(--font-text);color:var(--ink-2)}.qsum .it .v{color:var(--ink-2);line-height:1.55;overflow-wrap:anywhere}
.qempty{background:var(--s1);border:1px dashed var(--line-2);border-radius:var(--r-l);padding:20px;color:var(--ink-3);text-align:center;font-size:14px}
.qgo{background:var(--plate);border:1px solid var(--line-2);border-radius:var(--r-xl);padding:20px 22px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.qgo .tx{flex:1;min-width:240px;font-size:14px;color:var(--ink-2);line-height:1.6}
.qgo .tx b{color:var(--ink);font-weight:600}
.bigbtn{display:inline-flex;align-items:center;gap:8px;height:46px;padding:0 22px;border-radius:var(--r-m);color:#000;background:var(--white-hot);box-shadow:var(--white-glow);font:600 15px/1 var(--font-text);white-space:nowrap}
.bigbtn[disabled]{opacity:.4;cursor:default;box-shadow:none}
/* running: the scene is spinning behind; here — the timer, an indeterminate kit meter and the live event feed */
.qrun{background:var(--plate);border:1px solid var(--line-2);border-radius:var(--r-xl);padding:34px 24px 26px;display:flex;flex-direction:column;gap:16px;align-items:center;text-align:center}
.qrun h3{margin:0;font:700 22px/1.25 var(--font-display);letter-spacing:-.02em;color:var(--ink)}
.qrun .tm{font:600 44px/1 var(--font-display);color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.qrun .ph{color:var(--ink-2);font-size:14px;min-height:21px}
.ibar{position:relative;width:min(420px,100%);height:6px;background:repeating-linear-gradient(90deg,rgba(255,255,255,.1) 0 6px,transparent 6px 8px);overflow:hidden}
.ibar i{position:absolute;top:0;bottom:0;width:28%;background:repeating-linear-gradient(90deg,var(--el-a) 0 6px,transparent 6px 8px);filter:drop-shadow(0 0 5px var(--el-a));animation:ibar 2.6s ease-in-out infinite}
@keyframes ibar{0%{left:-30%}100%{left:100%}}
.qev{width:min(560px,100%);display:flex;flex-direction:column;gap:5px;text-align:left;font:500 12px/1.5 var(--font-mono);color:var(--ink-3)}
.qev div{display:flex;gap:10px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.qev div span{flex:none;color:var(--ink-3);width:42px}
.qev div b{font-weight:500;color:var(--ink-2);flex:none}.qev div em{font-style:normal;overflow:hidden;text-overflow:ellipsis}
.ares{display:flex;flex-direction:column;gap:16px}
.arh{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;flex-wrap:wrap;margin-top:6px}
.arh h3{margin:0;font:700 20px/1.2 var(--font-display);letter-spacing:-.02em;color:var(--ink)}.arh .sub{font-size:12.5px}
.pcard{background:linear-gradient(180deg,rgba(255,226,180,.035),transparent 36%),var(--plate);border:1px solid var(--line-2);border-radius:var(--r-xl);padding:24px;display:flex;flex-direction:column;gap:16px}
.pcard .sm{font:500 18px/1.55 var(--font-display);letter-spacing:-.01em;color:var(--ink);margin:0;text-wrap:pretty}
.axes{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.axis{background:var(--s1);border:1px solid var(--line-1);border-radius:var(--r-m);padding:12px 14px;display:flex;flex-direction:column;gap:4px}
.axis b{font:500 13px/1.3 var(--font-text);color:var(--ink-2)}.axis span{font-size:14.5px;color:var(--ink)}.axis small{font-size:12.5px;color:var(--ink-3);line-height:1.45}
.lv{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.lv h4{margin:0 0 8px;font:600 14px/1.3 var(--font-text);color:var(--ink)}
.lctx{font-size:14px;color:var(--ink-2);border-top:1px solid var(--line-1);padding-top:14px}.lctx b{color:var(--ink-3);font-weight:500}
.t5{background:var(--plate);border:1px solid var(--line-1);border-radius:var(--r-l);padding:16px;display:flex;gap:16px;align-items:flex-start;transition:border-color var(--t-fast)}
@media (hover:hover){.t5:hover{border-color:var(--line-2)}}
.t5 .rk{flex:none;width:42px;height:42px;border-radius:var(--r-m);display:grid;place-items:center;font:700 20px/1 var(--font-display);background:var(--s2);box-shadow:inset 0 0 0 1px var(--line-2);color:var(--ink)}
.t5 .bd{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px}
.t5 .ti{font:600 16px/1.35 var(--font-text);color:var(--ink);cursor:pointer}.t5 .ti:hover{text-decoration:underline;text-decoration-color:var(--line-3);text-underline-offset:3px}
.t5 .mt{font:500 12.5px/1.5 var(--font-mono);color:var(--ink-3)}
.t5 .wy{font-size:14px;color:var(--ink-2);line-height:1.6}
.conf{display:flex;align-items:center;gap:10px;font:500 12px/1 var(--font-mono);color:var(--ink-3)}
.conf .cb{position:relative;width:96px;height:5px;background:repeating-linear-gradient(90deg,rgba(255,255,255,.1) 0 4px,transparent 4px 6px)}
.conf .cb i{position:absolute;inset:0 auto 0 0;display:block;background:repeating-linear-gradient(90deg,var(--ink) 0 4px,transparent 4px 6px)}
.olist{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}
.oc{background:var(--plate);border:1px solid var(--line-1);border-radius:var(--r-l);padding:14px 16px;display:flex;flex-direction:column;gap:6px}
.oc .ti{font-weight:600;color:var(--ink)}.oc .wy{font-size:13.5px;color:var(--ink-2);line-height:1.55}.oc .wf{font-size:12.5px;color:var(--ink-3);overflow-wrap:anywhere}
.qq{margin:0;padding-left:20px;color:var(--ink-2);font-size:14px;display:flex;flex-direction:column;gap:6px;line-height:1.5}
.hlist{display:flex;flex-direction:column;gap:6px}
.hrow{display:grid;grid-template-columns:150px 110px minmax(0,1fr) auto;gap:12px;align-items:baseline;width:100%;text-align:left;font-size:13px;padding:10px 12px;border-radius:var(--r-m);border:1px solid var(--line-1);background:var(--s1);transition:border-color var(--t-fast),background-color var(--t-fast)}
@media (hover:hover){.hrow:hover{border-color:var(--line-2)}}.hrow.on{background:var(--s3);border-color:var(--line-3)}
.hrow .d{color:var(--ink-2);font-family:var(--font-mono);font-size:12px}.hrow .k{color:var(--ink-3)}.hrow .t{color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hrow .s{font:500 11.5px/1 var(--font-mono)}
.hrow .s.err{color:var(--err)}.hrow .s.ok{color:var(--ok)}
.vbanner{background:var(--plate);border:1px solid var(--line-2);border-radius:var(--r-m);padding:10px 14px;font-size:13.5px;color:var(--ink-2);display:flex;gap:12px;align-items:center}
.aipin{background:linear-gradient(180deg,rgba(255,226,180,.035),transparent 36%),var(--plate);border:1px solid var(--line-2);border-radius:var(--r-xl);padding:18px 20px;display:flex;flex-direction:column;gap:10px}
.aipin .hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.aipin .hd h3{margin:0;font:700 18px/1.25 var(--font-display);letter-spacing:-.02em;color:var(--ink)}
.aipin .hd h3::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--el-a);box-shadow:var(--el-glow);margin:0 10px 3px 0;vertical-align:middle}
.aipin .hd .sub{font-size:12.5px}
.aipin .pi{display:flex;gap:14px;align-items:center;padding:10px 0;border-top:1px solid var(--line-1)}
.aipin .pi .n{flex:none;width:28px;height:28px;border-radius:var(--r-s);display:grid;place-items:center;font:700 14px/1 var(--font-display);background:var(--s2);box-shadow:inset 0 0 0 1px var(--line-2);color:var(--ink)}
.aipin .pi .b{flex:1;min-width:0}.aipin .pi .t{font-weight:500;color:var(--ink);cursor:pointer}.aipin .pi .t:hover{text-decoration:underline;text-decoration-color:var(--line-3);text-underline-offset:3px}
.aipin .pi .w{font-size:13.5px;color:var(--ink-2);line-height:1.5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;margin-top:2px}
.aipin.slim{flex-direction:row;align-items:center;gap:14px;flex-wrap:wrap;padding:14px 18px}
.aipin.slim .tx{flex:1;min-width:220px;font-size:14px;color:var(--ink-2)}
.problem{background:var(--plate);border:1px solid color-mix(in oklab,var(--err) 45%,transparent);border-radius:var(--r-l);padding:16px 18px;color:var(--ink);font-size:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.problem .tx{flex:1;min-width:220px}
.brief{white-space:pre-wrap;font-size:13.5px;line-height:1.6;color:var(--ink-2);background:var(--s1);border:1px solid var(--line-1);border-radius:var(--r-m);padding:12px 14px;max-height:320px;overflow:auto}
details>summary.sub{cursor:pointer}
@media (max-width:760px){.qsum .it{grid-template-columns:1fr auto}.qsum .it .k{grid-column:1/-1}.lv{grid-template-columns:1fr}.hrow{grid-template-columns:1fr auto}.hrow .k,.hrow .t{display:none}
.qent .h .ed{grid-template-columns:1fr}.qcard{padding:18px 16px}.pmenu{left:0;top:calc(100% + 6px);width:min(320px,calc(100vw - 32px))}}
@media (prefers-reduced-motion:reduce){.ibar i{animation:none;left:36%}.qent{animation:none}}
'''

RAIL = r'''<div class="prof" id="prof">
    <button class="profbtn" id="profBtn" aria-haspopup="menu" aria-expanded="false" data-tip="Профиль" title="Профиль слушателя: отзывы, очередь, анкета и файл для ИИ — у каждого свои">
      <span class="av" id="profAv">·</span><span class="pn"><b id="profName">…</b><small id="profSub">&nbsp;</small></span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg></button>
    <div class="pmenu" id="profMenu" role="menu" hidden></div>
  </div>'''

VIEWS = r'''<!-- АНКЕТА -->
<section class="view" id="v-anketa" hidden>
  <div class="qtop"><header class="vh"><p class="kicker">анкета · claude</p><h2 class="vt" id="qaTitle">Анкета</h2><p class="sub" id="qaSub">5–10 минут: книги, кино, путешествия — и Claude составит ваш профиль и топ-5 из библиотеки.</p></header>
    <span class="aibadge" title="Подбор делает Claude через локальный Claude Code CLI; модель может искать в интернете. Запускается только по кнопке."><i></i>Использует Claude (через Claude Code) и интернет</span></div>
  <div id="qaBox" class="view"></div>
</section>
<dialog class="modal" id="modal" aria-labelledby="mT"><div class="modal-box">
  <div class="drawer-head"><h3 id="mT"></h3></div><div class="mbody" id="mB"></div><div class="merr" id="mErr" hidden></div>
  <div class="btn-row modal-actions"><button class="btn" id="mNo" type="button">Отмена</button><button class="btn primary" id="mYes" type="button">OK</button></div></div></dialog>'''

JS = r'''
/* ================= profiles ================= */
let PROFS=[],PDEF=1;
const profCur=()=>PROFS.find(p=>p.id===PROFILE)||PROFS[0];
const plural=(n,a,b,c)=>{const m=n%10,h=n%100;return n+' '+(m===1&&h!==11?a:m>=2&&m<=4&&(h<12||h>14)?b:c)};
function avatar(p){return el('span','av',p.initial)}
function profLine(p){return [p.reviews?plural(p.reviews,'отзыв','отзыва','отзывов'):'нет отзывов',p.queue?'очередь '+p.queue:'',p.running?'ИИ подбирает…':''].filter(Boolean).join(' · ')}
async function loadProfiles(){try{const j=await api('/api/profiles');PROFS=j.profiles;PDEF=j.default;
  if(!PROFS.some(p=>p.id===PROFILE)){PROFILE=j.default;store.set('abook.profile',String(PROFILE))}paintProfile()}catch(e){toast(e.message,'err')}}
function paintProfile(){const p=profCur();if(!p)return;$('#profAv').textContent=p.initial;
  $('#profName').textContent=p.name;$('#profSub').textContent=profLine(p);$('#profBtn').dataset.tip=p.name+' · '+profLine(p);
  const c=$('#c-anketa');const qs=p.questionnaire.status;c.textContent=p.running?'ИИ…':qs==='none'?'новое':qs==='draft'?'черновик':'';c.style.color=p.running||qs!=='submitted'?'var(--amber)':'';
  $$('#v-export a[href^="/api/export/"]').forEach(x=>{x.href=x.getAttribute('href').split('?')[0]+'?profile='+PROFILE});document.title='Аудиотека · '+p.name}
const needsOnboarding=()=>{const p=profCur();return !!p&&!p.is_default&&p.questionnaire.status==='none'&&!p.reviews};
function closeMenu(){$('#profMenu').hidden=true;$('#profBtn').setAttribute('aria-expanded','false')}
function openMenu(){const m=$('#profMenu'),cur=profCur();m.innerHTML='';m.appendChild(el('div','pmh','Профили'));
  for(const p of PROFS){const b=el('button','pmi'+(p.id===PROFILE?' on':''));b.setAttribute('role','menuitem');b.appendChild(avatar(p));const t=el('span','pmt');t.appendChild(el('b',null,p.name));t.appendChild(el('small',null,profLine(p)));b.appendChild(t);
    if(p.id===PROFILE){const c=el('span','chk');c.appendChild(ICON('check'));b.appendChild(c)}b.onclick=()=>switchProfile(p.id);m.appendChild(b)}
  m.appendChild(el('div','psep'));const add=(t,f,cls,icon)=>{const b=el('button','pma'+(cls?' '+cls:''));if(icon)b.appendChild(ICON(icon));b.appendChild(document.createTextNode(t));b.setAttribute('role','menuitem');b.onclick=()=>{closeMenu();f()};m.appendChild(b);return b};
  add('Новый профиль',newProfileDlg,'','folder-plus');add('Переименовать «'+cur.name+'»',renameDlg,'','pencil');const d=add('Удалить «'+cur.name+'»…',deleteDlg,'danger','trash');
  if(cur.is_default){d.disabled=true;d.title='Основной профиль удалить нельзя: его файл для ИИ — главный'}
  m.hidden=false;$('#profBtn').setAttribute('aria-expanded','true');m.querySelector('.pmi.on')?.focus()}
$('#profBtn').onclick=e=>{e.stopPropagation();$('#profMenu').hidden?openMenu():closeMenu()};
document.addEventListener('mousedown',e=>{if(!$('#profMenu').hidden&&!e.target.closest('#prof'))closeMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#profMenu').hidden){closeMenu();$('#profBtn').focus()}});
async function switchProfile(id){closeMenu();if(id===PROFILE)return;PROFILE=id;store.set('abook.profile',String(id));
  CUR=null;F=null;CLOSING=0;$('#card').hidden=true;$('#rateEmpty').hidden=false;QA=null;QMODE=null;VIEWRUN=null;AIST=null;clearTimeout(AIPOLL);
  paintProfile();await refreshMeta();paintMode();toast('Профиль: '+profCur().name);
  show(needsOnboarding()?'anketa':'rate');aiTick()}   // a fresh profile starts with the questionnaire, an existing one with «Отзыв»

/* ---------- modal ---------- */
let MOK=null;
function dlg(title,build,okText,onOk,danger){$('#mT').textContent=title;const b=$('#mB');b.innerHTML='';const focus=build(b);$('#mErr').hidden=true;
  const y=$('#mYes');y.textContent=okText;y.className='btn '+(danger?'solid danger':'primary');y.disabled=false;MOK=onOk;const m=$('#modal');if(!m.open)openDialog(m);setTimeout(()=>(focus||y).focus(),20)}
function dlgClose(){const m=$('#modal');if(m.open&&!m.classList.contains('closing'))closeDialog(m);MOK=null}
async function dlgOk(){if(!MOK||$('#mYes').disabled)return;const y=$('#mYes');setBusy(y,true);try{await MOK();setBusy(y,false);dlgClose()}catch(e){$('#mErr').textContent=e.message;$('#mErr').hidden=false;setBusy(y,false)}}
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
// UX: at most 7 steps; everything that fits is shown at once (only lists longer than 16 fold behind «ещё N»);
// every step is optional, so there is one forward action («Далее»), not «Пропустить» + «Далее» doing the same thing
const QSTEPS=[
 {k:'books_liked',d:'Любимые книги',t:'Книги, которые понравились',s:'Главное в анкете: 3–10 книг — из библиотеки или любые другие — и чем они зацепили.'},
 {k:'books_disliked',d:'Не зашли',t:'Книги, которые не зашли',s:'Что бросили или дослушали через силу. Такие книги точно не попадут в советы.'},
 {k:'prefs',d:'Как слушаете',t:'Как вы слушаете',s:'Жанры, длина, формат, язык и когда обычно слушаете.'},
 {k:'screen',d:'Кино и игры',t:'Кино, сериалы, игры',s:'Любимое на экране многое говорит о вкусе: атмосфера, темп, твисты, идеи. Заполните то, что ближе.'},
 {k:'about',d:'О вас',t:'О вас и увлечения',s:'Музыка, интересы, места и пара слов о себе — подсказывают темы и настроение книг.'},
 {k:'extra',d:'Что ещё',t:'Что ещё нужно знать',s:'Запреты, настроение, где слушаете — и вопросы, которые консультант хочет уточнить. Ответы сразу попадают в память профиля.'},
 {k:'summary',d:'Итог',t:'Итог',s:'Проверьте ответы — Claude составит ваш профиль и топ-5 из библиотеки.'}];
const LINE2STEP={books_liked:0,books_disliked:1,prefs:2,films:3,series:3,games:3,travel:4,music:4,interests:4,about:4,worldview:4,extra:5};
const LINE2TAB={films:'films',series:'series',games:'games'};
let QTAB='films';   // the open tab of the «Кино, сериалы, игры» step
const LANGL={ru:'русский',uk:'украинский',en:'английский'};
function qa(){const a=QA.answers||(QA.answers={});for(const k of ['books_liked','books_disliked','films','series','games','film_genres','series_genres','game_genres'])a[k]=a[k]||[];
  a.prefs=Object.assign({genres:[],genres_text:'',length:[],format:[],lang:[],listen:[],narrators:''},a.prefs||{});
  a.travel=Object.assign({been:[],want:[],types:[],pace:'',text:''},a.travel||{});a.music=Object.assign({chips:[],text:''},a.music||{});a.interests=Object.assign({chips:[],text:''},a.interests||{});
  a.about=Object.assign({name:'',age:'',education:[],education_text:'',profession:'',location:'',family:[],family_text:''},a.about||{});a.worldview=a.worldview||{};
  a.extra=Object.assign({text:'',avoid_authors:[],avoid_topics:[],darkness:'',where:[],hours:'',qa:[]},a.extra||{});
  for(const w of QA.worldview)a.worldview[w.key]=Object.assign({v:'',text:''},a.worldview[w.key]||{});return a}
function filled(k){const a=QA&&QA.answers||{};const nz=o=>o&&Object.values(o).some(v=>Array.isArray(v)?v.length:typeof v==='object'&&v?nz(v):!!v);
  if(k==='screen')return ['films','series','games'].some(filled);if(k==='life')return filled('music')||nz(a.travel);if(k==='about')return nz(a.about)||nz(a.worldview)||filled('music')||nz(a.travel);
  return k==='music'?nz(a.music)||nz(a.interests):k==='films'?(a.films||[]).length||(a.film_genres||[]).length:k==='series'?(a.series||[]).length||(a.series_genres||[]).length:k==='games'?(a.games||[]).length||(a.game_genres||[]).length:Array.isArray(a[k])?a[k].length>0:nz(a[k])}
function qaDirty(){QA.dirty=true;clearTimeout(QTIMER);QTIMER=setTimeout(qaFlush,800);const s=$('#qaSaved');if(s)s.textContent='изменения…'}
async function qaFlush(){clearTimeout(QTIMER);if(!QA||!QA.dirty)return QSAVING;QA.dirty=false;const my=PROFILE;
  QSAVING=(async()=>{try{const j=await post('/api/questionnaire',{answers:QA.answers,step:QSTEP});if(my!==PROFILE||!QA)return;QA.lines=j.lines;QA.status=j.status;QA.source=j.source;
    const s=$('#qaSaved');if(s)s.textContent='✓ черновик сохранён · '+hm(new Date().toISOString());if(j.renamed)loadProfiles()}catch(e){QA.dirty=true;toast('Черновик не сохранён: '+e.message,'err')}})();return QSAVING}
async function goStep(i){if(i<0||i>=QSTEPS.length)return;await qaFlush();QSTEP=i;QMODE='form';renderAnketa();window.scrollTo(0,0)}
async function loadAnketa(){const my=PROFILE;try{const [q,s]=await Promise.all([api('/api/questionnaire'),api('/api/ai/status')]);if(my!==PROFILE)return;QA=q;AIST=s;
  if(s.job&&s.job.kind!=='plus1')QMODE='running';else if(!QMODE||QMODE==='running')QMODE=s.latest?'result':q.source==='brief'?'brief':'form';
  if(QMODE==='form'&&!QA.touched){QSTEP=q.status==='draft'?Math.min(q.step||0,QSTEPS.length-1):0;QA.touched=true}
  renderAnketa();if(s.job)aiTick()}catch(e){toast(e.message,'err')}}
function renderAnketa(){if(!QA)return;const p=profCur();$('#qaTitle').textContent=QMODE==='result'?'Ваш профиль и топ-5':'Анкета'+(p?' · '+p.name:'');
  ({form:renderForm,running:renderRunning,result:renderResult,brief:renderBrief,problem:renderProblem})[QMODE]()}

document.addEventListener('keydown',e=>{if(VIEW==='anketa'&&QMODE==='form'&&e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&QSTEP<QSTEPS.length-1){e.preventDefault();goStep(QSTEP+1)}});

/* ---------- small widgets ---------- */
const CHIP_ALL=24,CHIP_SHOW=10;   // show everything up to 24 (two rows on the wide card — the user asked for no «ещё»); longer lists show 10 (plus whatever is selected) and «ещё N»
function chipSet(opts,arr,onCh,cls,label){const c=el('div','chips');const extra=[];
  opts.forEach((o,i)=>{const v=Array.isArray(o)?o[0]:o,t=Array.isArray(o)?o[1]:o;const on=arr.includes(v);
    const b=el('button','chip'+(cls?' '+cls:'')+(on?' on':''),t);b.type='button';b.setAttribute('aria-pressed',on);
    b.onclick=()=>{const i=arr.indexOf(v);if(i>=0)arr.splice(i,1);else arr.push(v);b.classList.toggle('on');b.setAttribute('aria-pressed',arr.includes(v));onCh()};
    if(opts.length>CHIP_ALL&&i>=CHIP_SHOW&&!on){b.hidden=true;extra.push(b)}c.appendChild(b)});
  if(extra.length){const m=el('button','chip more','ещё '+extra.length);m.type='button';m.setAttribute('aria-expanded','false');
    m.onclick=()=>{const open=m.getAttribute('aria-expanded')!=='true';extra.forEach(b=>b.hidden=!open);m.setAttribute('aria-expanded',String(open));m.textContent=open?'свернуть':'ещё '+extra.length;
      if(open)extra[0].focus()};c.appendChild(m)}
  return c}
function oneOf(opts,obj,key,onCh){const c=el('div','chips');c.setAttribute('role','radiogroup');const bs=[];for(const o of opts){const [v,t]=Array.isArray(o)?o:[o,o];const b=el('button','chip'+(obj[key]===v?' on':''),t);b.type='button';b.dataset.v=v;b.onclick=()=>{obj[key]=obj[key]===v?'':v;bs.forEach(x=>x.classList.toggle('on',x.dataset.v===obj[key]));onCh()};bs.push(b);c.appendChild(b)}return c}
function freeChips(arr,ph,onCh){const w=el('div','fchips');const inp=el('input');inp.placeholder=ph;
  const paint=()=>{w.querySelectorAll('.fc').forEach(x=>x.remove());arr.forEach((v,i)=>{const c=el('span','fc',v);c.appendChild(mkBtn({icon:'x',cls:'fcx',aria:'Убрать «'+v+'»',onClick:()=>{arr.splice(i,1);paint();onCh()}}));w.insertBefore(c,inp)})};
  const addv=()=>{let ch=false;for(const v of inp.value.split(/[,;]/).map(s=>s.trim()).filter(Boolean))if(!arr.some(x=>norm(x)===norm(v))){arr.push(v.slice(0,80));ch=true}inp.value='';if(ch){paint();onCh()}};
  inp.onkeydown=e=>{if(e.key==='Enter'||e.key===','||e.key===';'){e.preventDefault();addv()}else if(e.key==='Backspace'&&!inp.value&&arr.length){arr.pop();paint();onCh()}};inp.onblur=addv;
  w.appendChild(inp);w.onclick=e=>{if(e.target===w)inp.focus()};paint();return w}
function miniRate(obj,onCh){const m=el('div','mini');m.appendChild(el('span',null,'оценка'));const paint=()=>{m.querySelectorAll('button').forEach((b,i)=>{b.className=obj.rating==null?'':i<obj.rating?'f':i===obj.rating?'c':''})};
  for(let i=0;i<=10;i++){const b=el('button',null,String(i));b.title=i+'/10 · повторный клик — убрать';b.onclick=()=>{obj.rating=obj.rating===i?null:i;paint();onCh()};m.appendChild(b)}paint();return m}
function txt(obj,key,ph,max,cls){const i=el('input','in'+(cls?' '+cls:''));i.value=obj[key]||'';i.placeholder=ph||'';i.maxLength=max||300;i.oninput=()=>{obj[key]=i.value;qaDirty()};return i}
// a titled group inside a step (a hairline and a heading), always open — nothing to unfold
function group(body,label,build){const g=el('div','qgroup');g.appendChild(el('h4',null,label));const inner=el('div','qbody');g.appendChild(inner);build(inner);body.appendChild(g);return g}
function sec(body,label,node,hint){const s=el('div','qsec');if(label||hint){const l=el('div','ql');l.appendChild(el('b',null,label));if(hint)l.appendChild(el('span',null,hint));s.appendChild(l)}else s.style.marginTop='-10px';if(node)s.appendChild(node);body.appendChild(s);return s}

/* ---------- entries (books / films / series) ---------- */
function entryCard(list,e,idx,whyOpts,whyLabel,repaint){if(e.kind==='author')whyLabel=whyOpts===QA.options.book_dislike?'Чем не нравится автор':'Чем нравится автор';const c=el('div','qent');const h=el('div','h');
  if(e.kind==='author'){const ed=el('div','ed');ed.appendChild(txt(e,'title','Автор',200));h.appendChild(ed);h.appendChild(el('span','badge','автор целиком'))}
  else if(e.id){const t=el('div','tt',(e.author?e.author+' — ':'')+e.title);t.appendChild(el('small',null,e.meta||'в вашей библиотеке'));h.appendChild(t);h.appendChild(el('span','badge','в библиотеке'))}
  else if(whyOpts===QA.options.book_like||whyOpts===QA.options.book_dislike){const ed=el('div','ed');const a=txt(e,'author','Автор',200);a.setAttribute('list','dlAuthors');ed.appendChild(a);ed.appendChild(txt(e,'title','Название',300));h.appendChild(ed);h.appendChild(el('span','badge out','вне библиотеки'))}
  else{const t=el('div','ed');t.style.gridTemplateColumns='1fr';t.appendChild(txt(e,'title','Название',300));h.appendChild(t)}
  h.appendChild(mkBtn({icon:'x',cls:'x',aria:'Убрать из списка',onClick:()=>{list.splice(idx,1);qaDirty();repaint()}}));c.appendChild(h);
  const l=el('div','ql');l.style.cssText='font-size:13.5px;color:var(--ink-2)';l.textContent=whyLabel;c.appendChild(l);
  e.why=e.why||[];c.appendChild(chipSet(whyOpts,e.why,qaDirty,whyOpts===QA.options.book_dislike?'neg':''));
  const r=el('div','r');r.appendChild(miniRate(e,qaDirty));r.appendChild(txt(e,'comment','Одной строкой: что запомнилось (необязательно)',400));c.appendChild(r);return c}
function bookStep(body,key,whyOpts,whyLabel,ph){const list=qa()[key];const wrap=el('div','qsec');
  const sb=el('div','qsearch');const qin=el('div','qin');qin.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>';
  const inp=el('input');inp.placeholder=ph;inp.autocomplete='off';inp.spellcheck=false;qin.appendChild(inp);sb.appendChild(qin);const hits=el('div','hits');hits.hidden=true;sb.appendChild(hits);wrap.appendChild(sb);
  const cnt=el('div','qcount');wrap.appendChild(cnt);const ents=el('div','qents');wrap.appendChild(ents);body.appendChild(wrap);
  let H=[],act=0,seq=0,tmr=null,q='';
  const repaint=()=>{cnt.innerHTML=list.length?`Добавлено: <b>${list.length}</b>`+(key==='books_liked'&&list.length<3?' · хорошо бы ещё пару':''):'<span class="qhint">Начните вводить название или автора — подскажу из библиотеки. Любую другую книгу — как «Автор — Название»; любимого автора целиком — «Добавить автора» (Alt+Enter) и опишите, чем он цепляет.</span>';
    // newest first, 20 cards a window — a long list of books does not stretch the step
    pager(ents,[...list].reverse(),(e,j)=>entryCard(list,e,list.length-1-j,whyOpts,whyLabel,repaint),{page:20,key:key,small:true})};
  const has=(a,t,id)=>list.some(x=>(id&&x.id===id)||(norm(x.title).trim()===norm(t).trim()&&(!a||!x.author||norm(x.author)===norm(a))));
  const add=it=>{if(has(it.author,it.title,it.id)){toast('Уже в списке','warn');return}list.push({id:it.id||null,author:it.author||'',title:it.title,meta:it.meta||'',kind:it.kind||'book',why:[],rating:null,comment:''});inp.value='';q='';hits.hidden=true;qaDirty();repaint();inp.focus()};
  const free=()=>{const s=q.trim();if(!s)return;const m=s.split(/\s+[—–-]\s+/);add(m.length>1?{author:m[0].trim(),title:m.slice(1).join(' — ').trim()}:{author:'',title:s})};
  const paint=()=>{hits.innerHTML='';if(!q){hits.hidden=true;return}H.forEach((it,i)=>{const h=el('div','hit'+(i===act?' sel':''));const t=el('span');t.appendChild(hl((it.author?it.author+' — ':'')+it.title,q));h.appendChild(t);
      const b=itemBadge(it);h.appendChild(el('span','badge '+b[1],b[0]));h.appendChild(el('small',null,itemSmall(it)));h.onmousedown=ev=>{ev.preventDefault();pick(i)};hits.appendChild(h)});
    const a=el('div','hit add'+(act===H.length?' sel':''));a.appendChild(el('span',null,'＋ Добавить «'+q+'» — любая книга'));a.appendChild(el('span','badge out','Enter'));a.appendChild(el('small',null,'формат «Автор — Название»; можно и без автора'));a.onmousedown=ev=>{ev.preventDefault();pick(H.length)};hits.appendChild(a);
    const au=el('div','hit add'+(act===H.length+1?' sel':''));au.appendChild(el('span',null,'＋ Добавить автора «'+q+'» целиком'));au.appendChild(el('span','badge out','Alt+Enter'));au.appendChild(el('small',null,'если нравится автор в целом — опишите чем'));au.onmousedown=ev=>{ev.preventDefault();addAuthor()};
    if((key==='books_liked'||key==='books_disliked')&&H.filter(x=>norm(x.author||'').includes(norm(q))).length>=2)hits.prepend(au);else if(key==='books_liked'||key==='books_disliked')hits.appendChild(au);
    hits.hidden=false;hits.querySelector('.sel')?.scrollIntoView({block:'nearest'})};
  const addAuthor=()=>{const s=q.trim();if(!s)return;add({author:'',title:s,kind:'author'})};
  const pick=i=>{if(i===H.length+1)return addAuthor();if(i>=H.length)return free();const it=H[i];add({id:it.custom?null:it.id,author:it.author,title:it.title,meta:it.custom?'':itemSmall(it)})};
  inp.oninput=()=>{clearTimeout(tmr);q=inp.value.trim();if(!q){H=[];paint();return}tmr=setTimeout(async()=>{const my=++seq;try{const j=await api('/api/search?q='+encodeURIComponent(q));if(my!==seq)return;H=j.results.filter(x=>x.source!=='read').slice(0,8);act=H.length?0:0;paint()}catch(e){}},90)};
  inp.onkeydown=e=>{const n=H.length+(key==='books_liked'||key==='books_disliked'?2:1);if(e.key==='ArrowDown'){e.preventDefault();act=(act+1)%n;paint()}else if(e.key==='ArrowUp'){e.preventDefault();act=(act-1+n)%n;paint()}
    else if(e.key==='Enter'){e.preventDefault();if(!q)return;pick(e.altKey?H.length+1:act)}else if(e.key==='Escape'){hits.hidden=true}};
  inp.onblur=()=>setTimeout(()=>{hits.hidden=true},150);inp.onfocus=()=>{if(q)paint()};repaint();setTimeout(()=>inp.focus(),30)}
function titleStep(body,key,whyOpts,ph,gKey,gOpts,gLabel){const list=qa()[key];sec(body,gLabel,chipSet(gOpts,qa()[gKey],qaDirty));const wrap=el('div','qsec');const row=el('div','qsearch');const qin=el('div','qin');const inp=el('input');inp.placeholder=ph;inp.autocomplete='off';qin.appendChild(inp);
  const b=mkBtn({label:'Добавить',small:true});qin.appendChild(b);row.appendChild(qin);wrap.appendChild(row);const cnt=el('div','qcount');wrap.appendChild(cnt);const ents=el('div','qents');wrap.appendChild(ents);body.appendChild(wrap);
  const repaint=()=>{cnt.innerHTML=list.length?`Добавлено: <b>${list.length}</b>`:'<span class="qhint">Название и Enter. Год или режиссёра можно дописать в скобках.</span>';pager(ents,[...list].reverse(),(e,j)=>entryCard(list,e,list.length-1-j,whyOpts,'Чем понравился',repaint),{page:20,key:key,small:true})};
  const add=()=>{const t=inp.value.trim();if(!t)return;if(list.some(x=>norm(x.title)===norm(t))){toast('Уже в списке','warn');return}list.push({title:t.slice(0,300),why:[],rating:null,comment:''});inp.value='';qaDirty();repaint();inp.focus()};
  inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();add()}};b.onclick=add;repaint();setTimeout(()=>inp.focus(),30)}

/* ---------- steps ---------- */
const STEPR={
 books_liked:b=>bookStep(b,'books_liked',QA.options.book_like,'Чем понравилась','Книга или автор — «Процесс», «Ремарк», «Стругацкие Пикник»…'),
 books_disliked:b=>bookStep(b,'books_disliked',QA.options.book_dislike,'Что не так','Книга, которая не зашла…'),
 prefs:b=>{const p=qa().prefs;const g=sec(b,'Жанры',chipSet(QA.options.genres,p.genres,qaDirty),'сколько угодно');g.appendChild(txt(p,'genres_text','Свой жанр: «киберпанк, магический реализм»',300,'sm'));
   sec(b,'Длина',chipSet(QA.options.length,p.length,qaDirty));sec(b,'Формат',chipSet(QA.options.format,p.format,qaDirty));
   sec(b,'Язык',chipSet(QA.options.lang.map(x=>[x,LANGL[x]||x]),p.lang,qaDirty),'на каком готовы слушать');
   sec(b,'Главный язык',oneOf([['both','русский и украинский'],['ru','русский'],['uk','украинский']],p,'lang_main',qaDirty),'по умолчанию — оба на равных');sec(b,'Английский',oneOf(['нет','немного','охотно'],p,'en_level',qaDirty),'по умолчанию — немного');sec(b,'Когда слушаете',chipSet(QA.options.listen,p.listen,qaDirty));
   sec(b,'Любимые чтецы',txt(p,'narrators','Например: Князев, Клюквин, Терновский',300),'необязательно')},
 screen:b=>{const T={films:['Кино',()=>titleStep(inner,'films',QA.options.film_like,'Фильм — «Интерстеллар», «Семь», «Остров проклятых»…','film_genres',QA.options.film_genres,'Любимые жанры кино')],
     series:['Сериалы',()=>titleStep(inner,'series',QA.options.film_like,'Сериал — «Настоящий детектив», «Тьма», «Чернобыль»…','series_genres',QA.options.series_genres,'Любимые жанры сериалов')],
     games:['Игры',()=>titleStep(inner,'games',QA.options.game_like,'Игра — «Disco Elysium», «Half-Life 2», «Ведьмак 3»…','game_genres',QA.options.game_genres,'Любимые жанры игр')]};
   const seg=el('div','seg qtabs');seg.setAttribute('role','tablist');const inner=el('div','qbody');inner.style.marginTop='0';
   const open=k=>{QTAB=k;seg.querySelectorAll('button').forEach(x=>{x.classList.toggle('on',x.dataset.k===k);x.setAttribute('aria-selected',String(x.dataset.k===k))});inkSeg(seg);inner.innerHTML='';T[k][1]()};
   for(const [k,[t]] of Object.entries(T)){const x=el('button',null,t);x.type='button';x.dataset.k=k;x.setAttribute('role','tab');const n=(qa()[k]||[]).length;if(n)x.appendChild(el('small',null,' '+n));x.onclick=()=>{if(QTAB!==k)open(k)};seg.appendChild(x)}
   b.appendChild(seg);b.appendChild(inner);open(T[QTAB]?QTAB:'films')},
 life_:b=>{const a=qa(),t=a.travel;const m=sec(b,'Музыка',chipSet(QA.options.music,a.music.chips,qaDirty));m.appendChild(txt(a.music,'text','Исполнители или вещи: «Бетховен 9», «Циммер», «Кипелов»…',500,'sm'));
   const i=sec(b,'Интересы',chipSet(QA.options.interests,a.interests.chips,qaDirty));i.appendChild(txt(a.interests,'text','Подробнее: «ML и DevOps», «алгебраическая топология»…',500,'sm'));
   sec(b,'Где были и понравилось',freeChips(t.been,'Страна или город, Enter',qaDirty));sec(b,'Куда хотели бы',freeChips(t.want,'Страна или город, Enter',qaDirty));
   sec(b,'Тип отдыха',chipSet(QA.options.travel_types,t.types,qaDirty));sec(b,'Темп',oneOf(QA.options.travel_pace,t,'pace',qaDirty));sec(b,'Что запомнилось',txt(t,'text','Одной-двумя фразами',400),'необязательно')},
 about:b=>{STEPR.life_(b);const a=qa().about;if(!a.name&&profCur()&&!profCur().is_default)a.name=profCur().name;
   const g=el('div','grid');const lab=(t,n)=>{const l=el('label',null,t);l.appendChild(n);g.appendChild(l)};lab('Имя профиля',txt(a,'name','Имя',40));lab('Возраст',txt(a,'age','34 или 30–35',20));
   lab('Профессия или сфера',txt(a,'profession','DevOps-инженер, врач, студент-физик',200));lab('Где живёте',txt(a,'location','Город, страна',200));sec(b,'',g);
   const e=sec(b,'Образование',chipSet(QA.options.education,a.education,qaDirty));e.appendChild(txt(a,'education_text','Специальность (необязательно)',200,'sm'));
   const f=sec(b,'Семья',chipSet(QA.options.family,a.family,qaDirty));f.appendChild(txt(a,'family_text','Подробнее, если хочется: «сын 6 лет»',200,'sm'));
   const w=qa().worldview;
   group(b,'Взгляды',x=>{for(const q of QA.worldview){const s=sec(x,q.label,oneOf(q.options,w[q.key],'v',qaDirty));s.appendChild(txt(w[q.key],'text','Свой вариант или комментарий',300,'sm'))}})},
 extra:b=>{const x=qa().extra;
   sec(b,'Не предлагать авторов',freeChips(x.avoid_authors,'Автор, Enter',qaDirty),'никогда');
   sec(b,'Не предлагать темы',freeChips(x.avoid_topics,'Тема, Enter: «насилие над детьми», «война»…',qaDirty));
   sec(b,'Сколько мрачности',oneOf(['лучше светлое','баланс','мрачное — да','чем мрачнее, тем лучше'],x,'darkness',qaDirty));
   sec(b,'Где слушаете',chipSet(['в дороге','за рулём','спорт','дома','перед сном','на работе'],x.where,qaDirty));
   sec(b,'Сколько часов в неделю',oneOf(['до 3','3–10','10–20','больше 20'],x,'hours',qaDirty));
   sec(b,'Что ещё важно',txt(x,'text','Свободно: «люблю, когда финал переворачивает всё», «не выношу медленное начало»…',2000));
   const g=group(b,'Вопросы консультанта',w=>{const L=el('div','qbody');w.appendChild(L);
     const paint=()=>{L.innerHTML='';for(const e of x.qa){const s=sec(L,e.q,oneOf(e.options,e,'a',qaDirty));s.appendChild(txt(e,'a','Свой ответ',300,'sm'))}
       if(!x.qa.length)L.appendChild(el('p','sub','Консультант посмотрит на анкету и спросит то, чего ему не хватает для точных советов.'))};paint();
     const go=mkBtn({icon:'question',label:x.qa.length?'Ещё вопросы':'Задать вопросы',cls:'btn',title:'Консультант спросит то, чего не хватает для точных советов (≈ 10–20 с)'});go.onclick=async()=>{setBusy(go,true,'Думаю…');try{await qaFlush();const j=await post('/api/questionnaire/questions',{});
         const have=new Set(x.qa.map(e=>e.q));for(const q of j.questions||[])if(!have.has(q.q))x.qa.push({q:q.q,options:q.options,a:''});qaDirty();paint();toast('Вопросов: '+(j.questions||[]).length)}
       catch(e){toast(e.message,'err')}finally{setBusy(go,false,go.title)}};w.appendChild(go)})},
 summary:b=>renderSummary(b)};
function renderSummary(b){const L=(QA.lines||[]).filter(x=>x.key!=='brief');const box=el('div','qsum');
  if(!L.length&&!(QA.answers||{}).brief)b.appendChild(el('div','qempty','Анкета пока пустая. Добавьте хотя бы пару книг — это главное для подбора.'));
  for(const x of L){const r=el('div','it');r.appendChild(el('span','k',x.label));r.appendChild(el('span','v',x.text));r.appendChild(mkBtn({icon:'pencil',label:'Изменить',small:true,onClick:()=>{if(LINE2TAB[x.key])QTAB=LINE2TAB[x.key];goStep(LINE2STEP[x.key]??0)}}));box.appendChild(r)}
  if(L.length)b.appendChild(box);if((QA.answers||{}).brief){const d=el('details');d.appendChild(el('summary','sub','+ бриф этого профиля (BRIEF-COMMON.md) тоже будет учтён'));d.appendChild(el('div','brief',QA.answers.brief));b.appendChild(d)}
  const nrev=(profCur()||{}).reviews||0;const go=el('div','qgo');const tx=el('div','tx');
  tx.innerHTML=`<b>Что будет дальше.</b> Claude прочитает анкету${nrev?`, ваши отзывы (${nrev}, свежие весят больше)`:''} и каталог библиотеки, при необходимости поищет в интернете, есть ли подходящие аудиокниги вне библиотеки. Обычно 1–4 минуты; можно уйти на другую вкладку.`;
  go.appendChild(tx);const bt=el('button','bigbtn','Составить профиль и топ-5');bt.disabled=!L.length&&!nrev&&!(QA.answers||{}).brief;bt.onclick=()=>submitRun(bt);go.appendChild(bt);b.appendChild(go)}
// две дороги в анкету: по шагам или «расскажите своими словами» — Claude раскладывает рассказ по полям (пустые
// поля заполняются, ваше не перетирается), потом проверка в «Итоге»
let QFILL=store.get('abook.qfill','steps');
function qFillSwitch(box){const w=el('div','qfill');const sg=el('div','seg');sg.setAttribute('role','radiogroup');sg.setAttribute('aria-label','Как заполнить анкету');
  for(const [k,t] of [['steps','По шагам'],['text','Рассказать своими словами']]){const b=el('button',QFILL===k?'on':'',t);b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked',String(QFILL===k));b.onclick=()=>{if(QFILL===k)return;QFILL=k;store.set('abook.qfill',k);renderAnketa()};sg.appendChild(b)}
  w.appendChild(sg);box.appendChild(w);inkSeg(sg,true)}
function renderTextFill(){const box=$('#qaBox');box.innerHTML='';qFillSwitch(box);const card=el('div','qcard');card.appendChild(el('h3','qt','Расскажите, что вам нравится'));
  card.appendChild(el('p','sub','Свободно, как другу: любимые книги и почему, что бросили, фильмы и игры, когда и где слушаете, чего не хотите. Claude разложит рассказ по анкете — заполненное вами не перетрёт, — и вы проверите всё в «Итоге».'));
  const f=el('div','field area');f.innerHTML='<div class="field-ring"></div><div class="field-body"><textarea id="qText" maxlength="8000" aria-label="Рассказ о вкусе" placeholder="«Обожаю „Убик“ и „Конец вечности“ — люблю, когда реальность трескается. „Улисс“ бросил на трети: слишком словесно. Из кино — „Интерстеллар“, „Остров проклятых“. Слушаю в дороге, часа по два, мрачное — да, но без жестокости к детям…»"></textarea></div></div>';card.appendChild(f);
  const ft=el('div','qfoot');const go=el('button','btn primary','Заполнить анкету');const note=el('span','sub','≈ 10–20 с · Claude Sonnet');
  go.onclick=async()=>{const t=$('#qText').value.trim();if(t.length<20){toast('Расскажите чуть подробнее','warn');$('#qText').focus();return}setBusy(go,true,'Раскладываю по анкете…');procSet('qtext',{label:'Claude раскладывает рассказ по анкете',pct:null});
    try{const j=await post('/api/questionnaire/from_text',{text:t});store.set('abook.qtext.'+PROFILE,'');procEnd('qtext',true);toast('Заполнено: '+(j.filled||[]).length+' разделов — проверьте');QFILL='steps';store.set('abook.qfill','steps');QA=null;await loadAnketa();goStep(QSTEPS.length-1)}
    catch(e){procEnd('qtext',false);toast(e.message,'err');setBusy(go,false,'')}};
  ft.appendChild(go);ft.appendChild(note);card.appendChild(ft);box.appendChild(card);const ta=$('#qText');ta.value=store.get('abook.qtext.'+PROFILE,'');ta.oninput=()=>store.set('abook.qtext.'+PROFILE,ta.value);ta.focus()}
function renderForm(){if(QFILL==='text'){renderTextFill();return}const box=$('#qaBox');box.innerHTML='';qFillSwitch(box);const st=QSTEPS[QSTEP];qa();
  const hd=el('div','qhead');const dots=el('nav','qdots');dots.setAttribute('aria-label','Шаги анкеты');QSTEPS.forEach((x,i)=>{if(i)dots.appendChild(el('span','qsep'));
    const d=el('button','qdot'+(i===QSTEP?' on':'')+(i<QSTEPS.length-1&&filled(x.k)?' done':''));d.type='button';d.title=x.t;
    d.appendChild(el('span','n',String(i+1)));d.appendChild(el('span','l',x.d));if(i===QSTEP)d.setAttribute('aria-current','step');d.onclick=()=>goStep(i);dots.appendChild(d)});hd.appendChild(dots);box.appendChild(hd);
  const card=el('div','qcard');card.appendChild(el('h3','qt',st.t));card.appendChild(el('p','sub',st.s+(QSTEP<QSTEPS.length-1?' Всё необязательно.':'')));const body=el('div','qbody');card.appendChild(body);box.appendChild(card);STEPR[st.k](body);
  const ft=el('div','qfoot');const back=mkBtn({icon:'chev-r',label:'Назад',cls:'btn rot',onClick:()=>goStep(QSTEP-1)});back.hidden=QSTEP===0;ft.appendChild(back);
  if(QA.source==='brief'||AIST&&AIST.latest){const c=el('button','linkbtn','Закрыть анкету');c.onclick=async()=>{await qaFlush();QMODE=AIST&&AIST.latest?'result':'brief';renderAnketa()};ft.appendChild(c)}
  ft.appendChild(el('span','spacer'));const sv=el('span','qsaved');sv.id='qaSaved';sv.textContent=QA.updated?'черновик сохранён · '+fmtDT(QA.updated):'';ft.appendChild(sv);
  if(QSTEP<QSTEPS.length-1){const nx=el('button','btn primary',QSTEP===QSTEPS.length-2?'К итогу →':'Далее →');nx.title='Ctrl+Enter';nx.onclick=()=>goStep(QSTEP+1);ft.appendChild(nx)}
  card.appendChild(ft)}
async function submitRun(btn){btn.disabled=true;try{await qaFlush();const j=await post('/api/questionnaire/submit',{answers:QA.answers,step:QSTEP});QA.lines=j.lines;QA.status=j.status;QA.source=j.source;if(j.out)applyOut(j.out);
    await startAi('initial')}catch(e){toast(e.message,'err');btn.disabled=false}}
async function startAi(kind){try{await post('/api/ai/run',{kind});QMODE='running';VIEWRUN=null;AIST=await api('/api/ai/status');await loadProfiles();
    if(VIEW==='anketa')renderAnketa();else if(VIEW==='next')loadAiPinned();toast(kind==='refresh'?'Claude пересматривает топ-5…':'Claude составляет профиль…');aiTick()}catch(e){toast(e.message,'err');throw e}}

/* ---------- running ---------- */
const mmss=s=>{s=Math.max(0,Math.floor(s));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')};
let RUNT=null;
function renderRunning(){const box=$('#qaBox');const j=AIST&&AIST.job;if(!j){QMODE=AIST&&AIST.latest?'result':'form';return renderAnketa()}
  let r=$('#qaRun');if(!r){box.innerHTML='';r=el('div','qrun');r.id='qaRun';r.innerHTML='<h3 id="qrT"></h3><div class="tm" id="qrTm">00:00</div><div class="ibar"><i></i></div><div class="ph" id="qrPh"></div><div class="qev" id="qrEv"></div>';
    r.appendChild(mkBtn({icon:'x',label:'Отменить',cls:'btn',onClick:async(e,c)=>{setBusy(c,true,'Отменяю…');try{await post('/api/ai/cancel',{});toast('Отменяю…','warn')}catch(er){toast(er.message,'err');setBusy(c,false)}}}));
    r.appendChild(el('p','sub','Обычно 1–4 минуты (не больше 6). Можно перейти на другую вкладку — результат появится здесь и в «Что дальше».'));box.appendChild(r)}
  $('#qrT').textContent=j.kind==='refresh'?'Claude пересматривает топ-5 с учётом отзывов':'Claude составляет ваш профиль и топ-5';
  $('#qrPh').textContent=j.phase+(j.attempt>1?' · попытка '+j.attempt:'');const ev=$('#qrEv');ev.innerHTML='';
  for(const e of j.events.slice(-6)){const d=el('div');d.appendChild(el('span',null,mmss(e.t)));d.appendChild(el('b',null,e.kind==='search'?'поиск':'страница'));d.appendChild(el('em',null,e.kind==='search'?'«'+e.text+'»':e.text.replace(/^https?:\/\//,'')));ev.appendChild(d)}
  const t0=Date.now()-j.elapsed*1000;clearInterval(RUNT);const tick=()=>{const t=$('#qrTm');if(!t){clearInterval(RUNT);return}t.textContent=mmss((Date.now()-t0)/1000)};tick();RUNT=setInterval(tick,500)}
async function aiTick(){clearTimeout(AIPOLL);const my=PROFILE;let s;try{s=await api('/api/ai/status')}catch(e){AIPOLL=setTimeout(aiTick,4000);return}if(my!==PROFILE)return;
  const was=!!(AIST&&AIST.job);AIST=s;
  if(s.job)procSet('ai',{label:'Claude · '+(s.job.kind==='plus1'?'+1 · ':'')+(s.job.phase||(s.job.kind==='refresh'?'пересмотр':'подбор')),pct:null,accent:'white',cancel:async()=>{try{await post('/api/ai/cancel',{});toast('Отменяю…','warn')}catch(e){toast(e.message,'err')}}});
  else if(was)procEnd('ai',!!(s.history[0]&&s.history[0].status==='done'));
  if(s.job){if(VIEW==='anketa'&&QA&&s.job.kind!=='plus1'){QMODE='running';renderRunning()}if(VIEW==='next')paintPinned();AIPOLL=setTimeout(aiTick,VIEW==='anketa'?1000:2500);if(!was)loadProfiles();return}
  if(was){clearInterval(RUNT);await loadProfiles();const h=s.history[0];
    if(h&&h.kind==='plus1'){const x=h.status==='done'&&((s.plus||[])[0]||{}).result;
      if(x){toast('+1: '+(x.pick.author?x.pick.author+' — ':'')+'«'+x.pick.title+'»');}
      else toast(h.status==='cancelled'?'+1 отменён':'+1 не получилось: '+(h.error||'ошибка'),h.status==='cancelled'?'warn':'err');
      if(VIEW==='next')loadAiPinned();refreshMeta();return}
    if(h&&h.status==='done'){toast('Готово: профиль и топ-5 обновлены'+(h.duration_sec?' · '+mmss(h.duration_sec):''));QMODE='result';VIEWRUN=null}
    else{toast(h&&h.status==='cancelled'?'Подбор отменён':'Не получилось: '+(h&&h.error||'ошибка'),h&&h.status==='cancelled'?'warn':'err');QMODE=h&&h.status==='cancelled'?(s.latest?'result':'form'):'problem'}
    if(VIEW==='anketa'&&QA)renderAnketa();if(VIEW==='next')loadAiPinned();refreshMeta()}}

/* ---------- result ---------- */
function linkify(parent,text){const re=/https?:\/\/[^\s<>()«»"]+[^\s<>()«»".,;:!?]/g;let i=0,m;while((m=re.exec(text))){parent.appendChild(document.createTextNode(text.slice(i,m.index)));const a=el('a',null,m[0].replace(/^https?:\/\/(www\.)?/,'').slice(0,60));a.href=m[0];a.target='_blank';a.rel='noopener noreferrer';parent.appendChild(a);i=m.index+m[0].length}parent.appendChild(document.createTextNode(text.slice(i)))}
// «В очередь» как переключатель: aria-pressed + ✓ в отведённом месте, подпись не меняет ширины
function qBtn(it,small){const b=mkBtn({icon:'layers',label:it&&it.in_queue?'В очереди':'В очередь',small,check:true,pressed:!!(it&&it.in_queue),title:it&&it.in_queue?'Убрать из очереди':'Поставить в очередь прослушивания'});if(!it){b.disabled=true;b.title='Книги нет в библиотеке';return b}
  b.onclick=async e=>{e.stopPropagation();try{const j=await post('/api/queue',{op:it.in_queue?'remove':'add',item_id:it.id});it.in_queue=!it.in_queue;b.childNodes[1].textContent=it.in_queue?'В очереди':'В очередь';setPressed(b,it.in_queue);b.title=it.in_queue?'Убрать из очереди':'Поставить в очередь прослушивания';if(it.in_queue)kick(.35);applyOut(j.out);refreshMeta();loadProfiles()}catch(er){toast(er.message,'err')}};return b}
function runMeta(r){return ['Claude'+(r.model?' ('+r.model+')':''),fmtDT(r.finished||r.started),r.duration_sec?mmss(r.duration_sec):'',r.kind==='refresh'?'пересмотр с учётом отзывов':'по анкете'].filter(Boolean).join(' · ')}
async function renderResult(){const box=$('#qaBox');let run=AIST&&AIST.latest;
  if(VIEWRUN&&(!run||VIEWRUN!==run.id)){try{run=await api('/api/ai/run?id='+VIEWRUN)}catch(e){VIEWRUN=null}}
  if(!run||!run.result){QMODE=QA.source==='brief'?'brief':'form';return renderAnketa()}
  const R=run.result,P=R.profile||{};box.innerHTML='';const wrap=el('div','ares');box.appendChild(wrap);
  if(VIEWRUN&&AIST.latest&&VIEWRUN!==AIST.latest.id){const v=el('div','vbanner');v.appendChild(el('span',null,'Вы смотрите прежний подбор от '+fmtDT(run.finished)+'.'));v.appendChild(mkBtn({icon:'chev-r',label:'К последнему',small:true,onClick:()=>{VIEWRUN=null;renderAnketa()}}));wrap.appendChild(v)}
  const h1=el('div','arh');const t=el('div');t.appendChild(el('h3',null,'Ваш профиль'));t.appendChild(el('div','sub',runMeta(run)));h1.appendChild(t);wrap.appendChild(h1);
  const pc=el('div','pcard');if(P.summary)pc.appendChild(el('p','sm',P.summary));
  if((P.taste_axes||[]).length){const ax=el('div','axes');for(const a of P.taste_axes){const d=el('div','axis');d.appendChild(el('b',null,a.axis));d.appendChild(el('span',null,a.value));if(a.evidence)d.appendChild(el('small',null,a.evidence));ax.appendChild(d)}pc.appendChild(ax)}
  const lv=el('div','lv');const col=(tt,arr,cls)=>{const c=el('div');c.appendChild(el('h4',null,tt));const ch=el('div','chips');(arr||[]).forEach(x=>{const s=el('span','chip on '+cls,x);s.style.cursor='default';ch.appendChild(s)});c.appendChild(ch);lv.appendChild(c)};
  col('Любите',P.loves,'pos');col('Лучше избегать',P.avoid,'neg');pc.appendChild(lv);if(P.listening_context){const c=el('div','lctx');c.appendChild(el('b',null,'Как вы слушаете: '));c.appendChild(document.createTextNode(P.listening_context));pc.appendChild(c)}wrap.appendChild(pc);
  const h2=el('div','arh');h2.appendChild(el('h3',null,'Топ-5 из вашей библиотеки'));wrap.appendChild(h2);
  (R.top5||[]).forEach((x,i)=>{const it=x.item;const c=el('div','t5');c.appendChild(el('div','rk',String(i+1)));const bd=el('div','bd');
    const ti=el('div','ti',it?(it.author?it.author+' — ':'')+it.title:x.id);ti.onclick=()=>openItem(x.id);bd.appendChild(ti);if(it)bd.appendChild(el('div','mt',[it.section,it.bucket?LENL[it.bucket]:'',fmtH(it.hours,it.hours_exact),it.narrator,(DL[it.status]||DL.pending)[0],it.rstatus?'отзыв: '+STL[it.rstatus]:''].filter(Boolean).join(' · ')));
    bd.appendChild(el('div','wy',x.why));if(x.confidence!=null){const cf=el('div','conf');const cb=el('span','cb');const ii=el('i');ii.style.width=Math.round(x.confidence*100)+'%';cb.appendChild(ii);cf.appendChild(cb);cf.appendChild(el('span',null,'уверенность '+Math.round(x.confidence*100)+'%'));bd.appendChild(cf)}
    const r=actsEl(it?tgBtn(it,true):null,it?moreBtn(()=>bookMenu(it),true):mkBtn({icon:'file',label:'Открыть карточку',small:true,onClick:()=>openItem(x.id)}));r.classList.add('plain');r.style.marginTop='4px';bd.appendChild(r);c.appendChild(bd);wrap.appendChild(c)});
  if((R.outside_library||[]).length){const h3=el('div','arh');h3.appendChild(el('h3',null,'Вне библиотеки'));h3.appendChild(el('span','sub','Claude проверял наличие аудиокниг в интернете'));wrap.appendChild(h3);const ol=el('div','olist');
    for(const o of R.outside_library){const c=el('div','oc');c.appendChild(el('div','ti',(o.author?o.author+' — ':'')+'«'+o.title+'»'));c.appendChild(el('div','wy',o.why));if(o.where_to_find){const w=el('div','wf');w.appendChild(document.createTextNode('Где найти: '));linkify(w,o.where_to_find);c.appendChild(w)}ol.appendChild(c)}wrap.appendChild(ol)}
  if((R.questions_to_refine||[]).length){const p=el('div','panel');p.appendChild(el('h3',null,'Что уточнить, чтобы подбор стал точнее'));const ol=el('ol','qq');R.questions_to_refine.forEach(q=>ol.appendChild(el('li',null,q)));p.appendChild(ol);
    p.appendChild(el('p','sub','Ответьте в анкете (например, в комментариях) или просто оцените пару книг — и запросите новый топ-5.'));wrap.appendChild(p)}
  const act=el('div','qgo');const tx=el('div','tx');const nrev=(profCur()||{}).reviews||0;tx.innerHTML='<b>Новый топ-5 с учётом отзывов</b> — только по кнопке: Claude прочитает полный файл для ИИ этого профиля (все отзывы'+(nrev?' — сейчас '+nrev:'')+', анкету, прошлые советы) и не повторит без причины то, что уже советовал.';act.appendChild(tx);
  const rb=el('button','bigbtn','Новый топ-5 с учётом отзывов');rb.onclick=()=>{rb.disabled=true;startAi('refresh').catch(()=>{rb.disabled=false})};act.appendChild(rb);act.appendChild(mkBtn({icon:'pencil',label:'Изменить анкету',cls:'btn',onClick:()=>{QMODE='form';QSTEP=0;renderAnketa()}}));wrap.appendChild(act);
  if((run.notes||[]).length){const d=el('details');d.appendChild(el('summary','sub','Проверка ответа ('+run.notes.length+')'));const u=el('ul','qq');u.style.fontSize='12.5px';run.notes.forEach(n=>u.appendChild(el('li',null,n)));d.appendChild(u);wrap.appendChild(d)}
  const hist=(AIST.history||[]);if(hist.length){const p=el('div','panel');p.appendChild(el('h3',null,'История подборов ('+hist.length+')'));const hl=el('div','hlist');
    for(const h of hist){const b=el('button','hrow'+(h.id===run.id?' on':''));b.appendChild(el('span','d',fmtDT(h.started)));b.appendChild(el('span','k',h.kind==='plus1'?'+1 по запросу':h.kind==='refresh'?'пересмотр':'по анкете'));b.appendChild(el('span','t',(h.kind==='plus1'&&h.wish?'«'+h.wish+'» → ':'')+(h.titles.join(' · ')||h.error||'')));
      b.appendChild(el('span','s '+(h.status==='done'?'ok':h.status==='running'?'':'err'),h.status==='done'?(h.duration_sec?mmss(h.duration_sec):'готово'):h.status==='running'?'идёт':h.status==='cancelled'?'отменён':'ошибка'));
      if(h.status==='done')b.onclick=h.kind==='plus1'?()=>show('next'):()=>{VIEWRUN=h.id;renderAnketa();window.scrollTo(0,0)};else b.style.cursor='default';hl.appendChild(b)}p.appendChild(hl);wrap.appendChild(p)}}
function renderBrief(){const box=$('#qaBox');box.innerHTML='';const p=el('div','qcard');p.appendChild(el('h3','qt','Анкета этого профиля — бриф'));
  p.appendChild(el('p','sub','Для профиля «'+(profCur()||{}).name+'» анкету заменяет бриф из BRIEF-COMMON.md (раздел «Кто слушатель») — он считается уже заполненной анкетой. Можно сразу составить профиль и топ-5 или дополнить бриф анкетой.'));
  p.appendChild(el('div','brief',(QA.answers||{}).brief||''));const r=el('div','row');r.style.marginTop='10px';const go=el('button','bigbtn','Составить профиль и топ-5');go.onclick=()=>{go.disabled=true;startAi('initial').catch(()=>{go.disabled=false})};r.appendChild(go);
  r.appendChild(mkBtn({icon:'pencil',label:'Пройти анкету (дополнить бриф)',cls:'btn',onClick:()=>{QMODE='form';QSTEP=0;renderAnketa()}}));p.appendChild(r);box.appendChild(p)}
function renderProblem(){const box=$('#qaBox');box.innerHTML='';const h=(AIST&&AIST.history||[])[0];const p=el('div','problem');p.appendChild(el('div','tx','Подбор не получился: '+((h&&h.error)||'неизвестная ошибка')+'. Анкета сохранена.'));
  const r=mkBtn({icon:'refresh',label:'Попробовать ещё раз',cls:'btn primary'});r.onclick=()=>{setBusy(r,true);startAi(h&&h.kind||'initial').catch(()=>{setBusy(r,false)})};p.appendChild(r);p.appendChild(mkBtn({label:'К анкете',cls:'btn',onClick:()=>{QMODE='form';renderAnketa()}}));box.appendChild(p);
  if(AIST.latest){const b=el('button','linkbtn','Показать прошлый удачный подбор');b.onclick=()=>{QMODE='result';renderAnketa()};box.appendChild(b)}}

/* ---------- pinned block in «Что дальше» ---------- */
async function loadAiPinned(){const my=PROFILE;try{AIST=await api('/api/ai/status');if(my!==PROFILE)return;paintPinned();if(AIST.job)aiTick()}catch(e){$('#nxAi').innerHTML=''}}
function paintPinned(){if(typeof fdChatMount==='function')fdChatMount();const box=$('#nxAi');box.innerHTML='';const s=AIST;if(!s)return;const r=s.latest;
  if(s.job&&s.job.kind!=='plus1'){const p=el('div','aipin slim');p.appendChild(el('div','tx','Claude '+(s.job.kind==='refresh'?'пересматривает топ-5':'составляет профиль и топ-5')+' · '+mmss(s.job.elapsed)+' · '+s.job.phase));p.appendChild(mkBtn({icon:'chev-r',label:'Смотреть',small:true,onClick:()=>show('anketa')}));box.appendChild(p);return}
  if(!r){const p=el('div','aipin slim');p.appendChild(el('div','tx','Рекомендаций ИИ пока нет. Заполните анкету — Claude составит ваш профиль и топ-5 из библиотеки.'));p.appendChild(mkBtn({icon:'clipboard',label:'Открыть анкету',cls:'btn',onClick:()=>show('anketa')}));box.appendChild(p);return}
  const p=el('div','aipin');const hd=el('div','hd');hd.appendChild(el('h3',null,'Рекомендации ИИ ('+new Date(r.finished).toLocaleDateString('ru-RU',{day:'numeric',month:'short'})+')'));
  hd.appendChild(el('span','sub',runMeta(r)));hd.appendChild(el('span','spacer'));hd.appendChild(mkBtn({icon:'file',label:'Профиль и подробности',small:true,onClick:()=>{QMODE='result';VIEWRUN=null;show('anketa')}}));
  const nb=mkBtn({icon:'refresh',label:'Новый топ-5 с учётом отзывов',small:true,title:'Использует Claude (через Claude Code) и интернет; только по кнопке'});nb.onclick=()=>{setBusy(nb,true);startAi('refresh').catch(()=>{setBusy(nb,false)})};hd.appendChild(nb);p.appendChild(hd);
  (r.result.top5||[]).forEach((x,i)=>{const it=x.item;const row=el('div','pi');row.appendChild(el('div','n',String(i+1)));const b=el('div','b');const t=el('div','t',it?(it.author?it.author+' — ':'')+it.title:x.id);t.onclick=()=>openItem(x.id);b.appendChild(t);
    b.appendChild(el('div','w',x.why));row.appendChild(b);if(it&&it.rstatus&&it.rstatus!=='want')row.appendChild(el('span','badge',STL[it.rstatus]));if(it)row.appendChild(actsEl(tgBtn(it,true),moreBtn(()=>bookMenu(it),true)));p.appendChild(row)});
  box.appendChild(p);const hint=el('p','sub','Ниже — детерминированный подбор по формуле, без ИИ.');hint.style.margin='2px 0 0';box.appendChild(hint)}
'''
