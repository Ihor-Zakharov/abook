"""Вкладка «Найти» для SPA `abook review`: поиск источника и скачивание, очередь загрузок, консультант с памятью,
карта связей и блок «Связи» под карточкой книги. Вставляется в REVIEW_HTML по маркерам /*FIND:CSS*/, <!--FIND:NAV-->,
<!--FIND:VIEWS-->, /*FIND:JS*/ (abook_find.inject_html). Пользуется помощниками страницы ($, el, api, post, toast, show,
openItem, procSet/procEnd, inkSeg, confirmDlg…). Дизайн — cosmos-kit: монохромные плиты, цвет только в излучении
(кайма поля, заливка прогресса, live-dot), одно раскалённое действие на экран."""

CSS = r'''
/* ---------- «Найти»: поиск, загрузки, консультант, память, карта связей (cosmos-kit, монохромно) ---------- */
.fdsearch .field-body{padding:6px 12px 6px 8px}
.fdsearch .field-body input{font-size:17px}
.fdms{flex:none;min-width:56px;text-align:right;font:500 13px/1 var(--font-mono);color:var(--ink-3);font-variant-numeric:tabular-nums}
.fdkbd{flex:none;height:24px;min-width:24px;padding:0 6px;display:grid;place-items:center;border-radius:var(--r-xs);box-shadow:inset 0 0 0 1px var(--line-2);font:500 13px/1 var(--font-mono);color:var(--ink-3)}
.fdhint{text-align:center;min-height:21px;font-size:13px}
.fdres{display:flex;flex-direction:column;gap:14px}
/* мгновенная выдача: три группы строк одной высоты — ничего не прыгает при вводе, строки обновляются на месте */
.fdlive{padding:14px 10px 12px;gap:12px}
.fdgrp{display:flex;flex-direction:column;gap:2px;min-width:0}
.fdgh{display:flex;align-items:baseline;gap:10px;padding:0 12px 6px}.fdgh h3{margin:0;font:600 14px/1.4 var(--font-text);color:var(--ink-2)}
.fdgh .sub{font-size:13px}.fdgh .ms{margin-left:auto;font:500 13px/1 var(--font-mono);color:var(--ink-3);font-variant-numeric:tabular-nums}
.fdit{display:flex;flex-direction:column;min-width:0}
.fdrow{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-rows:22px 19px;column-gap:16px;row-gap:2px;align-items:center;height:60px;padding:0 12px;border-radius:var(--r-m);cursor:pointer;min-width:0;transition:background-color var(--t-fast),box-shadow var(--t-fast)}
.fdrow:hover{background:var(--s1)}.fdrow.sel{background:var(--s3)}
.fdrow .t{display:flex;align-items:center;gap:8px;min-width:0;font:600 15px/22px var(--font-text);color:var(--ink)}
.fdrow .t .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.fdrow .t mark{background:none;color:var(--ink);box-shadow:inset 0 -1px 0 var(--line-3)}
.fdrow .m,.fdrec .m{font:500 13px/19px var(--font-mono);color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.fdrow .a,.fdrec .a{display:flex;align-items:center;gap:4px;flex:none}
.fdrow .a{grid-row:1/span 2;grid-column:2}
.fdrow .a .ghost,.fdrec .a .ghost{white-space:nowrap}
.fdn{height:24px;padding:0 8px;border-radius:var(--r-xs);box-shadow:inset 0 0 0 1px var(--line-1);font:500 13px/1 var(--font-mono);color:var(--ink-3);white-space:nowrap;flex:none}
.fdn:hover,.fdit.open .fdn{color:var(--ink);box-shadow:inset 0 0 0 1px var(--line-3)}
.fdrecl{display:none;flex-direction:column;gap:3px;padding:3px 0 8px 28px}.fdit.open .fdrecl{display:flex}
.fdrec{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:16px;align-items:center;height:40px;padding:0 12px;border-radius:var(--r-s);background:var(--s1)}
.fdrec.best .m{color:var(--ink)}
.fdact{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 12px 0;border-top:1px solid var(--line-1)}
.fdact .tx{font-size:14.5px;color:var(--ink-2)}.fdact .note{margin-left:auto;font-size:13px;color:var(--ink-3)}
.fdqplate{padding:14px 16px;gap:10px}.fdqplate .fdqi{padding:8px 12px}
.fdplate{background:linear-gradient(180deg,rgba(255,255,255,.02),transparent 40%),var(--plate);border:1px solid var(--line-2);border-radius:var(--r-xl);padding:20px 22px;display:flex;flex-direction:column;gap:14px;min-width:0}
.fdplate>h3,.fdh h3{margin:0;font:700 19px/1.25 var(--font-display);letter-spacing:-.02em;color:var(--ink)}
.fdh{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.fdh .sub{font-size:13px}
.fdrun{display:flex;flex-direction:column;gap:12px}
.fdrun .top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:14px;color:var(--ink-2)}
.fdrun .top b{font:500 13px/1 var(--font-mono);color:var(--ink);font-variant-numeric:tabular-nums}
.fdrun .top span{flex:1;min-width:200px}
.fdsrc{display:flex;flex-wrap:wrap;gap:6px}
.fdsrc>span{display:inline-flex;align-items:center;gap:7px;height:28px;padding:0 10px;border-radius:var(--r-s);box-shadow:inset 0 0 0 1px var(--line-1);font:500 12px/1 var(--font-mono);color:var(--ink-3);white-space:nowrap}
.fdsrc>span.on{color:var(--ink-2);box-shadow:inset 0 0 0 1px var(--line-2)}.fdsrc>span.ok{color:var(--ink)}.fdsrc>span.bad{color:var(--ink-3);text-decoration:line-through;text-decoration-color:var(--line-3)}
.fdev{display:flex;flex-direction:column;gap:4px;font:500 12px/1.5 var(--font-mono);color:var(--ink-3)}
.fdev div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fdev b{font-weight:500;color:var(--ink-2)}
.fdwork{font-size:14.5px;color:var(--ink-2);line-height:1.55}.fdwork b{color:var(--ink);font-weight:600}
.fdlib{display:flex;align-items:center;gap:12px;flex-wrap:wrap;background:var(--s1);border:1px solid var(--line-3);border-radius:var(--r-l);padding:12px 16px;font-size:14px;color:var(--ink)}
.fdlib .tx{flex:1;min-width:220px}
.fdc{background:var(--s1);border:1px solid var(--line-1);border-radius:var(--r-l);padding:14px 16px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px;align-items:start}
.fdc.best{background:var(--s2);border-color:var(--line-3)}
.fdc .tt{font:600 15.5px/1.4 var(--font-text);color:var(--ink);overflow-wrap:anywhere}
.fdc .mt{font:500 12.5px/1.6 var(--font-mono);color:var(--ink-2)}
.fdc .by{font-size:13px;color:var(--ink-3)}.fdc .by a{color:var(--ink-2)}
.fdc .fl{display:flex;flex-wrap:wrap;gap:6px}
.fdc .act{grid-row:1/span 4;grid-column:2;display:flex;flex-direction:column;gap:8px;align-items:stretch}
.fdc .note{font-size:13px;color:var(--ink-3);line-height:1.5}
.fdnone{background:var(--s1);border:1px dashed var(--line-2);border-radius:var(--r-l);padding:18px 20px;color:var(--ink-2);font-size:14.5px;line-height:1.6}
.fdnone b{color:var(--ink)}
.fdrej{font-size:13px;color:var(--ink-3);display:flex;flex-direction:column;gap:3px;margin-top:6px}
details>summary.fdsum{cursor:pointer;font-size:13px;color:var(--ink-3);list-style:none}details>summary.fdsum::before{content:"▸ ";}details[open]>summary.fdsum::before{content:"▾ "}
/* очередь загрузок */
.fdq{display:flex;flex-direction:column;gap:8px}
.fdqi{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 14px;align-items:center;padding:12px 14px;border-radius:var(--r-l);background:var(--s1);border:1px solid var(--line-1)}
.fdqi .t{font-weight:500;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fdqi .s{font:500 12.5px/1.5 var(--font-mono);color:var(--ink-2);min-height:19px}
.fdqi .w{font-size:12.5px;color:var(--ink-3);grid-column:1/-1}
.fdqi .b{grid-column:2;grid-row:1/span 2;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.fdqi .meter{grid-column:1/-1;margin:0}
/* «Чат» — отдельный экран, как браузерный Claude: слева разговоры, в центре колонка ≤ 780 px, поле ввода — последний ряд */
.main>#v-chat.view{max-width:none;width:auto;margin:0 calc(-1 * clamp(20px,3.4vw,56px)) -112px;padding:0}
.fdchat{display:grid;grid-template-columns:268px minmax(0,1fr);height:100vh;height:100dvh;min-height:520px}
.fdside{display:flex;flex-direction:column;gap:8px;padding:18px 12px 14px;border-right:1px solid var(--line-1);min-height:0}
.fdside .btn{justify-content:center}
.fdsl{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:2px;margin:4px -4px 0;padding:0 4px}
.fdsl .grp{font:500 11px/1.4 var(--font-mono);color:var(--ink-3);padding:12px 10px 4px}
.fdsl .si{display:flex;align-items:center;gap:4px;border-radius:var(--r-m);color:var(--ink-2)}
.fdsl .si>button:first-child{flex:1;min-width:0;text-align:left;padding:8px 10px;font-size:13.5px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fdsl .si small{display:block;font:500 11.5px/1.4 var(--font-mono);color:var(--ink-3)}
.fdsl .si:hover{background:var(--s1);color:var(--ink)}.fdsl .si.on{background:var(--s3);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line-2)}
.fdsl .si .x{flex:none;width:24px;height:24px;margin-right:4px;border-radius:var(--r-s);display:grid;place-items:center;color:var(--ink-3);opacity:0}
.fdsl .si:hover .x,.fdsl .si.on .x{opacity:1}.fdsl .si .x:hover{color:var(--ink);background:var(--s2)}
.fdside .foot{font-size:12.5px;color:var(--ink-3);line-height:1.5;padding:10px 6px 0;border-top:1px solid var(--line-1)}
.fdside .foot button{color:var(--ink-2)}.fdside .foot button:hover{color:var(--ink)}
.fdmain{display:flex;flex-direction:column;min-width:0;min-height:0}
.fdtop{display:flex;align-items:center;gap:12px;width:min(880px,100%);margin:0 auto;padding:14px 24px;min-height:60px}   /* the same column as the messages: nothing drifts to the far edge of a wide window */
.fdtop h2{margin:0;flex:0 1 auto;font:600 16px/1.3 var(--font-text);color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.fdtop .seg,.fdtop .switch{flex:none}.fdtop .spacer{flex:1 0 8px}
.fdtop .sub{flex:0 1 auto;min-width:0;max-width:38%;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fdmsgs{flex:1;min-height:0;overflow:auto;scroll-behavior:smooth}
.fdcol{width:min(880px,100%);margin:0 auto;padding:12px 24px 24px;display:flex;flex-direction:column;gap:22px}
.fdempty{display:flex;flex-direction:column;gap:12px;align-items:center;text-align:center;padding-top:clamp(40px,18vh,200px)}
.fdempty h3{margin:0;font:600 30px/1.2 var(--font-display);letter-spacing:-.02em;color:var(--ink)}
.fdempty p{margin:0;max-width:560px;font-size:14.5px;color:var(--ink-2);line-height:1.6}
.fdm{display:flex;flex-direction:column;gap:12px;max-width:100%}
.fdwrapu{align-self:flex-end;display:flex;flex-direction:column;max-width:85%}
.fdm.u{background:var(--s3);border:1px solid var(--line-1);border-radius:var(--r-l);padding:10px 16px;font-size:15.5px;line-height:1.6;color:var(--ink);white-space:pre-wrap;overflow-wrap:anywhere}
.fdm.u small{display:block;font:500 11.5px/1.4 var(--font-mono);color:var(--ink-3);margin-top:4px;white-space:normal;text-align:right}
.fdm.a .rp{font-size:16px;line-height:1.75;color:var(--ink-2)}.fdm.a .rp p{margin:0 0 12px}.fdm.a .rp>:last-child{margin-bottom:0}
.fdm.a .run{display:flex;align-items:center;gap:10px;font-size:14px;color:var(--ink-3)}.fdm.a .run b{font:500 12px/1 var(--font-mono);color:var(--ink-2);font-variant-numeric:tabular-nums}
.fdm.a .err{font-size:14px;color:var(--ink-2)}
.fdm .acts,.fdwrapu .acts{display:flex;align-items:center;gap:2px;opacity:0;transition:opacity var(--t-fast)}
.fdm:hover .acts,.fdm:focus-within .acts,.fdm.last .acts,.fdwrapu:hover .acts,.fdwrapu:focus-within .acts{opacity:1}
.fdwrapu .acts{justify-content:flex-end;margin-top:4px}
.fdm .acts button,.fdwrapu .acts button{height:26px;padding:0 8px;border-radius:var(--r-s);font:500 12px/1 var(--font-text);color:var(--ink-3)}
.fdm .acts button:hover,.fdwrapu .acts button:hover{color:var(--ink);background:var(--s2)}
.fdm .acts .fdfoot{margin-left:auto}
.fdm.u.edit{padding:6px;width:min(640px,100%)}.fdm.u.edit textarea{width:100%;min-height:64px;background:transparent;border:0;color:var(--ink);font:inherit;resize:vertical;outline:none;padding:6px 8px}
.fdm.u.edit .b{display:flex;gap:6px;justify-content:flex-end}
.rp h4{margin:14px 0 6px;font:600 16px/1.4 var(--font-text);color:var(--ink)}.rp strong{color:var(--ink);font-weight:600}
.rp ul,.rp ol{margin:0 0 12px;padding-left:22px}.rp li{margin:4px 0}.rp code{font:500 13px/1 var(--font-mono);background:var(--s2);padding:2px 5px;border-radius:var(--r-xs)}
.rp a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line-3);text-underline-offset:3px}
.rp .caret{display:inline-block;width:8px;height:1.05em;margin-left:3px;vertical-align:-2px;background:var(--ink-2);border-radius:1px}
.fdcomp{width:min(880px,100%);margin:0 auto;padding:6px 24px 18px}
.fdbox{background:var(--s2);border:1px solid var(--line-2);border-radius:var(--r-xl);padding:12px 12px 10px 16px;display:flex;flex-direction:column;gap:8px;transition:border-color var(--t-fast)}
.fdbox:focus-within{border-color:var(--line-3)}
.fdbox textarea{width:100%;min-height:28px;max-height:240px;background:transparent;border:0;outline:none;resize:none;color:var(--ink);font:400 16px/1.55 var(--font-text);padding:4px 0}
.fdbox textarea::placeholder{color:var(--ink-3)}
.fdbox textarea,.fdbox textarea:hover,.fdbox textarea:focus,.fdbox textarea:focus-visible{box-shadow:none;border:0;outline:none;background:transparent;border-radius:0}
.fdbar{display:flex;align-items:center;gap:10px;flex-wrap:nowrap}.fdbar .spacer{flex:1;min-width:8px}.fdbar .seg,.fdbar .btn{flex:none}
.fdbar .btn{height:36px}
.fdlbl{font:500 13px/1 var(--font-text);color:var(--ink-3)}
.fdkeys{margin:8px 0 0;font:400 12.5px/1.4 var(--font-text);color:var(--ink-3);text-align:center}
@media (min-width:2000px){.fdmain.blank .fdmsgs{display:flex;align-items:flex-end}.fdmain.blank .fdcomp{padding-bottom:24vh}.fdmain.blank .fdempty{padding:0 0 18px}}
.fdmain.incog .fdbox{border-style:dashed}
.fdsfind{height:32px;font-size:13px}
/* мини-вход в «Что дальше» */
.ndb{display:contents}
#v-find .fdms,#v-find .fdgh .ms{display:none}
/* «Чат»: рельса приложения и так одна колонка иконок (см. .rail в abook) — здесь только своё */
.fdfbb{filter:grayscale(1)}.fdfbb.on,.fdfbb:hover{filter:grayscale(1) brightness(1.4)}
.fdchat{grid-template-columns:260px minmax(0,1fr)}
/* «Для вас»: модель вкуса по всему каталогу (библиотека + нескачанные записи). На 2560 — третья колонка во всю высоту,
   уже 2000 px — лента внутри пустого состояния нового чата; одни и те же строки .fdr, что и советы консультанта */
.fdfor{display:none;min-height:0;overflow:auto;scrollbar-width:thin;border-left:1px solid var(--line-1);padding:16px 20px 24px}
.fdforbox{display:flex;flex-direction:column;gap:10px;width:100%;text-align:left}
.fdforbox>.fdh{align-items:center}.fdforbox>.fdh .spacer{flex:1}
.fdforbox .fdrecs{gap:6px}.fdforbox .fdr{padding:12px 14px;gap:14px}.fdforbox .fdr .ac{max-width:46%}.fdforbox .fdr .mt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fdforwait{display:flex;flex-direction:column;gap:10px;padding:10px 0 4px;color:var(--ink-2);font-size:14px}
.fdforwait .meter{margin:0}.fdforwait b{font:500 12.5px/1 var(--font-mono);color:var(--ink-3);font-variant-numeric:tabular-nums}
.fdempty .fdforbox{margin-top:26px}
.fdmain.blank .fdempty{padding-top:clamp(24px,8vh,80px)}
@media (min-width:2000px){.fdchat{grid-template-columns:260px minmax(0,1fr) 600px}.fdfor{display:block}.fdmain.blank .fdempty{padding-top:clamp(40px,18vh,200px)}}
.rdscale{display:grid;grid-template-columns:repeat(10,1fr);gap:6px;margin:6px 0 18px}.rdscale button{height:44px;border-radius:var(--r-m);background:var(--s2);border:1px solid var(--line-1);font:600 16px/1 var(--font-display);color:var(--ink-2)}.rdscale button:hover,.rdscale button:focus-visible{background:var(--s3);color:var(--ink);border-color:var(--line-3)}
#rdDlg .modal-actions{display:flex;align-items:center;gap:8px}
#rpDlg .chips{margin:4px 0 14px}.rpnote{display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--ink-2);margin-bottom:14px}
.fdrep{height:28px;padding:0 9px;border-radius:var(--r-s);font:500 12.5px/1 var(--font-text);color:var(--ink-3)}.fdrep:hover{color:var(--ink);background:var(--s2)}
.fdfb{display:flex;align-items:center;justify-content:flex-end;gap:2px}
.fdfbb{height:28px;padding:0 9px;border-radius:var(--r-s);font:500 12.5px/1 var(--font-text);color:var(--ink-3)}.fdfbb:hover{color:var(--ink);background:var(--s2)}.fdfbb.on{color:var(--ink);box-shadow:inset 0 0 0 1px var(--line-3)}
.fdask{display:flex;gap:10px;align-items:center;margin:0 0 18px}
.fdask .field{flex:1}
/* advice: one row per book, like the AI list in «Что дальше» — text on the left, actions and the reaction on the right; rows share one structure, so nothing differs in height */
.fdrecs{display:flex;flex-direction:column;gap:8px}
.fdr{background:var(--plate);border:1px solid var(--line-1);border-radius:var(--r-l);padding:14px 16px;display:flex;gap:18px;align-items:flex-start;min-width:0;transition:opacity var(--t-base)}
.fdr .bd{flex:1;min-width:0;display:flex;flex-direction:column;gap:7px}
.fdr .ac{flex:none;display:flex;flex-direction:column;align-items:flex-end;gap:6px;max-width:46%}
.fdr.gone{opacity:.45}
.fdr .h{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.fdr .ti{font:600 15px/1.4 var(--font-text);color:var(--ink);overflow-wrap:anywhere}.fdr .ti.link{cursor:pointer}.fdr .ti.link:hover{text-decoration:underline;text-decoration-color:var(--line-3);text-underline-offset:3px}
.fdr .chain{font:500 12.5px/1.55 var(--font-mono);color:var(--ink);background:var(--s1);border:1px solid var(--line-1);border-radius:var(--r-m);padding:7px 10px;overflow-wrap:anywhere}
.fdr .chain i{font-style:normal;color:var(--ink-3)}
.fdr .wy{font-size:13.5px;color:var(--ink-2);line-height:1.55}
.fdr .mt{font:500 12px/1.5 var(--font-mono);color:var(--ink-3)}
.fdr .row{display:flex;align-items:center;justify-content:flex-end;gap:6px;flex-wrap:wrap}
.fdr .row .on{color:var(--ink);box-shadow:inset 0 0 0 1px var(--line-3)}
.fdr .st{font:500 11.5px/1.4 var(--font-mono);color:var(--ink-3);min-height:16px}
.fdfu{display:flex;gap:6px;flex-wrap:wrap}
.fdfoot{font-size:12.5px;color:var(--ink-3)}
/* память и карта */
.fdmem{display:flex;flex-direction:column;gap:6px}
.fdmi{display:flex;align-items:flex-start;gap:10px;padding:8px 10px;border-radius:var(--r-m);background:var(--s1);border:1px solid var(--line-1);font-size:14px;color:var(--ink-2);line-height:1.5}
.fdmi .k{flex:none;font:500 11px/20px var(--font-mono);color:var(--ink-3);width:92px}
.fdmi .f{flex:1;min-width:0;cursor:text;overflow-wrap:anywhere}.fdmi .f:hover{color:var(--ink)}
.fdmi .in{flex:1;height:32px;font-size:13.5px}
.fdmi .x{flex:none;width:26px;height:26px;border-radius:var(--r-s);display:grid;place-items:center;color:var(--ink-3)}.fdmi .x:hover{color:var(--err);background:var(--s3)}
.fdmap .big{font:600 30px/1 var(--font-display);color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.fdmap .big small{font:500 13px/1 var(--font-text);color:var(--ink-3);margin-left:6px;letter-spacing:0}
.fdmap .tx{font-size:14px;color:var(--ink-2);line-height:1.55}
.fdtags{display:flex;flex-wrap:wrap;gap:6px}
.fdtags span{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 9px;border-radius:var(--r-xs);box-shadow:inset 0 0 0 1px var(--line-1);font-size:12.5px;color:var(--ink-2)}
.fdtags span i{font:500 10.5px/1 var(--font-mono);font-style:normal;color:var(--ink-3)}
/* «Связи» под карточкой книги */
.fdlinks{position:relative;display:flex;flex-direction:column;gap:14px;width:min(var(--card-w,620px),100%);margin:14px 0 0;padding:22px 26px;border-radius:var(--r-xl);background:var(--plate);border:1px solid var(--line-2)}
.fdlinks .hd{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.fdlinks .hd h3{margin:0;font:700 18px/1.25 var(--font-display);letter-spacing:-.02em;color:var(--ink)}
.fdlinks .feats{font-size:13px;color:var(--ink-3);line-height:1.6}.fdlinks .feats b{font-weight:500;color:var(--ink-2)}
.fdgroups{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
.fdg{background:var(--s1);border:1px solid var(--line-1);border-radius:var(--r-l);padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.fdg .gl{display:flex;align-items:baseline;gap:8px}.fdg .gl b{font:600 14px/1.35 var(--font-text);color:var(--ink)}.fdg .gl small{font:500 11px/1 var(--font-mono);color:var(--ink-3)}
.fdg button{display:block;text-align:left;font-size:13.5px;line-height:1.45;color:var(--ink-2);padding:2px 0;overflow-wrap:anywhere}
.fdg button:hover{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line-3);text-underline-offset:3px}
.fdg button small{font:500 11px/1 var(--font-mono);color:var(--ink-3);margin-left:6px}
@media (max-width:760px){.fdr{flex-direction:column}.fdr .ac{max-width:none;align-items:flex-start}.fdc{grid-template-columns:1fr}.fdc .act{grid-row:auto;grid-column:1;flex-direction:row;flex-wrap:wrap}
  .fdplate{padding:16px}.fdlinks{padding:16px}.fdmi .k{width:auto}.fdmi{flex-wrap:wrap}.fdsearch .field-body .btn{padding:0 12px}
  .main>#v-chat.view{margin:0}.fdtop .sub{display:none}
  .fdchat{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr);height:calc(100dvh - 160px)}.fdside{border-right:0;border-bottom:1px solid var(--line-1);padding:10px}.fdsl{max-height:110px}.fdcol,.fdcomp,.fdtop{padding-left:12px;padding-right:12px}.fdkeys{display:none}
  .fdqi{grid-template-columns:1fr}.fdqi .b{grid-column:1;grid-row:auto;justify-content:flex-start}}
'''

NAV = r'''<button data-v="chat" data-tip="Что дальше"><svg><use href="/kit/icons/sprite.svg#i-play"/></svg><span class="l">Что дальше</span></button><button data-v="find" data-tip="Найти"><svg><use href="/kit/icons/sprite.svg#i-download"/></svg><span class="l">Найти</span><small id="c-find"></small></button>'''

VIEWS = r'''<!-- ЧАТ -->
<section class="view" id="v-chat" hidden>
  <div class="fdchat" id="fdChat">
    <aside class="fdside"><button class="btn sm" id="fdNew">+ Новый чат</button><div class="fdsl" id="fdSess"></div>
      <div class="foot" id="fdSideFoot"></div></aside>
    <div class="fdmain" id="fdMain">
      <div class="fdtop"><h2 class="vt" id="fdTitle">Новый чат</h2><span class="sub" id="fdChSub"></span><span class="spacer"></span>
        <div class="seg sm" id="fdLlm" role="radiogroup" aria-label="ИИ-провайдер"></div>
        <label class="switch" title="Не видит анкету, отзывы и память и ничего не запоминает; разговор удалится через сутки"><input type="checkbox" id="fdIncog"><span class="switch-track" aria-hidden="true"><span class="switch-thumb"></span></span><span class="switch-text">инкогнито</span></label></div>
      <div class="fdmsgs" id="fdMsgs" aria-live="polite"><div class="fdcol" id="fdCol"></div></div>
      <div class="fdcomp">
        <div class="fdbox"><textarea id="fdAsk" rows="1" maxlength="2000" aria-label="Сообщение консультанту" placeholder="Чего хочется послушать?"></textarea>
          <div class="fdbar"><span class="fdlbl">Прыжок</span><div class="seg sm" id="fdDist" role="radiogroup" aria-label="Насколько далеко от запроса"></div>
            <span class="fdlbl">Книг</span><div class="seg sm" id="fdCnt" role="radiogroup" aria-label="Сколько книг советовать"></div>
            <input type="checkbox" id="fdSurp" hidden>
            <span class="spacer"></span><button class="ghost sm" id="fdDown" hidden>↓ вниз</button><button class="btn primary" id="fdSend">Отправить</button></div></div>
        <p class="fdkeys">Enter — отправить · Shift+Enter — новая строка · ↑ — изменить последнее · Esc — остановить</p>
      </div>
    </div>
    <aside class="fdfor" id="fdFor" aria-label="Для вас"></aside>
  </div>
</section>

<dialog class="modal" id="rpDlg" aria-labelledby="rpT"><div class="modal-box">
  <div class="drawer-head"><h3 id="rpT">Что не так с записью?</h3></div><p class="modal-text" id="rpB"></p>
  <div class="chips" id="rpR" role="radiogroup" aria-label="Причина"></div>
  <label class="rpnote">Подробнее, если хочется<input class="in" id="rpN" maxlength="500" placeholder="«обрывается на 3-й части», «это пересказ»…"></label>
  <label class="switch"><input type="checkbox" id="rpO"><span class="switch-track" aria-hidden="true"><span class="switch-thumb"></span></span><span class="switch-text">найти другую запись</span></label>
  <div class="modal-actions"><button class="ghost" id="rpNo">Отмена</button><button class="btn solid" id="rpYes">Пожаловаться</button></div></div></dialog>

<dialog class="modal" id="rdDlg" aria-labelledby="rdT"><div class="modal-box">
  <div class="drawer-head"><h3 id="rdT">Уже читали</h3></div><p class="modal-text" id="rdB">Оцените одним нажатием — это сразу уточнит подбор.</p>
  <div class="rdscale" id="rdS" role="group" aria-label="Оценка от 1 до 10"></div>
  <div class="modal-actions"><button class="ghost" id="rdNo">Отмена</button><span class="spacer"></span><button class="ghost" id="rdMark">Просто отметить</button><button class="btn solid" id="rdFull">Полный отзыв →</button></div></div></dialog>

<!-- НАЙТИ -->
<section class="view" id="v-find" hidden>
  <header class="vh"><p class="kicker">найти</p><h2 class="vt">Любая книга — одной строкой</h2>
    <p class="sub" id="fdSub">Печатайте — ищу сразу в библиотеке и в каталоге интернета. Не нашлось — пошлю на площадки и к ИИ, а пожелание передам консультанту.</p></header>
  <div class="field lit fdsearch"><div class="field-ring"></div><div class="field-body"><span class="field-glyph accent"><svg><use href="/kit/icons/sprite.svg#i-search"/></svg></span>
    <input id="fdQ" autocomplete="off" spellcheck="false" maxlength="300" aria-label="Название книги, автор или пожелание" placeholder="«Пикник на обочине», «Стругацкие, чтец Кузнецов», «мрачное про космос»">
    <span class="fdms" id="fdMs" aria-live="off"></span><kbd class="fdkbd" title="/ или Ctrl+K — в поиск">/</kbd></div></div>
  <p class="sub fdhint" id="fdHint">↑↓ — по строкам · Enter — открыть или скачать лучшую запись · Esc — стереть · Ctrl+Enter — искать в сети</p>
  <div class="fdplate fdlive" id="fdLive" hidden>
    <section class="fdgrp" id="fdGLib" hidden aria-label="В библиотеке"><div class="fdgh"><h3>В библиотеке</h3><span class="sub">скачано или в каталоге библиотеки</span><span class="ms"></span></div><div class="fdrows"></div></section>
    <section class="fdgrp" id="fdGCat" hidden aria-label="Каталог интернета"><div class="fdgh"><h3>Каталог интернета</h3><span class="sub">произведения: одна строка — книга, внутри все записи</span><span class="ms"></span></div><div class="fdrows"></div></section>
    <section class="fdgrp" id="fdGSem" hidden aria-label="По смыслу"><div class="fdgh"><h3>По смыслу</h3><span class="sub">не по буквам, а по близости: аннотации и признаки</span><span class="ms"></span></div><div class="fdrows"></div></section>
    <div class="fdact" id="fdAct" hidden></div>
  </div>
  <div class="fdres" id="fdRes"></div>
  <div class="fdplate fdqplate" id="fdDl" hidden></div>
</section>'''

JS = r'''
/* ================= «Найти»: поиск источника, загрузки, консультант, память, карта связей ================= */
let FDS=null,FDT=null,FDCUR=null,FDCH=null,FDCHT=null,FDSESS=0,FDMAPJ=false,FDTICK=null;
let FDDIST=Math.max(0,Math.min(3,+store.get('abook.fd.dist','1')||0));
const FD_DONE=new Set();   // поиски-пожелания, уже переданные консультанту
const fdmm=s=>{s=Math.max(0,Math.floor(s||0));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')};
const fdH=sec=>sec?fmtH(sec/3600,true):'';
const fdPl=(n,a,b,c)=>{const m=n%10,h=n%100;return n+' '+(m===1&&h!==11?a:m>=2&&m<=4&&(h<12||h>14)?b:c)};
const FD_QST={queued:'в очереди',downloading:'скачиваю',merging:'склеиваю и проверяю файл',checking:'проверка полноты',done:'✓ готово',error:'ошибка',cancelled:'отменено'};
const FD_ACT=['queued','downloading','merging','checking'];
const FD_KIND={audiobook:'аудиокнига',radioplay:'радиоспектакль',reading:'чтение',other:''};

let FDCS=null;   // счётчики каталога — один раз, для подзаголовка
function loadFind(){fdPoll(true);api('/api/find/memory').then(j=>fdPaintMem(j.memory||[])).catch(()=>{});
  api('/api/find/vec/status').then(j=>{const d=j.daemon||{},sub=$('#fdGSem .sub');sub.textContent=!j.enabled?'векторы выключены':d.todo?'не по буквам, а по близости · индекс ещё строится: '+(d.n||0)+' из '+((d.n||0)+d.todo):'не по буквам, а по близости: аннотации и признаки'}).catch(()=>{});
  if(!FDCS)api('/api/find/catalog/status').then(j=>{FDCS=j;const k=n=>n>=1000?Math.round(n/1000)+' тыс.':String(n);if(j.works)$('#fdSub').textContent='Библиотека и '+k(j.works)+' книг из интернета: слушайте онлайн или скачивайте';
  if(!FDWARM){FDWARM=true;for(const u of ['/api/search?q=книга','/api/find/catalog?group=work&limit=1&q=книга'])api(u).catch(()=>{})}   // прогрев индексов: первый запрос без холодного старта
  setTimeout(()=>{if(VIEW==='find'&&!typing())fdFocus()},60)}
let FDWARM=false;
function fdFocus(){const q=$('#fdQ');q.focus();q.select()}
// «/» и Ctrl+K на этом экране — в поиск (перехват раньше палитры страницы; диалоги и палитра — не трогаем)
document.addEventListener('keydown',e=>{if(VIEW!=='find'||!$('#pal').hidden||document.querySelector('dialog[open]'))return;
  const ck=(e.ctrlKey||e.metaKey)&&!e.shiftKey&&!e.altKey&&(e.key==='k'||e.key==='K'||e.code==='KeyK'),sl=e.key==='/'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!typing();
  if(ck||sl){e.preventDefault();e.stopImmediatePropagation();fdFocus()}},true);
// поиск-задание в сети (площадки + ИИ, 20–60 с) — запрос остаётся в поле, мгновенная выдача не исчезает
async function fdSearch(q,auto){q=(q??$('#fdQ').value).trim();if(q.length<2){toast('Введите название книги или пожелание','warn');fdFocus();return}
  const b=$('#fdAct .btn');if(b)b.disabled=true;try{const j=await post('/api/find/search',{q,auto:!!auto});FDCUR=j.id;
    toast(auto?'Ищу запись «'+q+'» — если вариант однозначный, скачаю сам':'Ищу в сети: '+q);await fdPoll(true)}
  catch(e){toast(e.message,'err')}finally{if(b)b.disabled=false}}

/* ---------- мгновенный поиск по мере ввода: библиотека + каталог произведений + смысл ---------- */
// три запроса параллельно; библиотека и каталог рисуются вместе (≈ 50 мс), смысловой — когда придёт (векторный демон;
// нет демона — группы просто нет). Устаревшие ответы отбрасываются по номеру, запросы в полёте — отменяются.
let FDQSEQ=0,FDQT=null,FDQT2=null,FDQAC=null,FDSEL=0,FDROWS=[];
const FDL={q:'',lib:null,cat:null,sem:null};
const FD_LIM={lib:6,cat:8,sem:6};
const fdWish=q=>q.trim().split(/\s+/).length>=2&&/(^|\s)(что|чего|чем|как|про|похож\S*|нибудь|какой|какую|какие|мрачн\S*|весел\S*|коротк\S*|длинн\S*|лёгк\S*|легк\S*|страшн\S*|грустн\S*|добр\S*|умн\S*|вечер\S*|настроен\S*|без|не)(\s|$)/i.test(q);
const fdNT=(a,t)=>'t:'+norm((a||'')+'|'+(t||'')).replace(/[^\p{L}\p{N}|]+/gu,' ').trim();
$('#fdQ').addEventListener('input',()=>{clearTimeout(FDQT);FDQT=setTimeout(fdLive,120)});
$('#fdQ').addEventListener('keydown',e=>{const n=FDROWS.length;
  if(e.key==='ArrowDown'&&n){e.preventDefault();fdSelect((FDSEL+1)%n)}
  else if(e.key==='ArrowUp'&&n){e.preventDefault();fdSelect((FDSEL-1+n)%n)}
  else if(e.key==='Enter'){e.preventDefault();clearTimeout(FDQT);if(e.ctrlKey||e.metaKey){fdSearch();return}if(FDL.q!==$('#fdQ').value.trim()){fdLive();return}if(n&&FDROWS[FDSEL])fdMain(FDROWS[FDSEL]);else fdPrimary()}
  else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();if($('#fdQ').value){$('#fdQ').value='';clearTimeout(FDQT);fdLive()}else $('#fdQ').blur()}});
function fdLive(){const q=$('#fdQ').value.trim();if(q===FDL.q)return;Object.assign(FDL,{q,lib:null,cat:null,sem:null});const my=++FDQSEQ;
  if(FDQAC)FDQAC.abort();FDQAC=new AbortController();const sig=FDQAC.signal;clearTimeout(FDQT2);FDSEL=0;$('#fdMs').textContent='';
  if(q.length<2){fdPaintLive();return}
  const e=encodeURIComponent(q),t0=performance.now();
  const go=(url,k)=>api(url,{signal:sig}).then(j=>{if(my!==FDQSEQ)return;j._ms=Math.round(performance.now()-t0);FDL[k]=j;fdPaintLive();
      if(k==='cat'&&j.expanding&&!url.includes('&again=1'))setTimeout(()=>{if(my===FDQSEQ)go(url+'&again=1','cat')},2600)})   // другие названия считаются в фоне
    .catch(err=>{if(my!==FDQSEQ||err.name==='AbortError')return;FDL[k]={items:[],results:[],err:err.message};fdPaintLive()});
  go('/api/search?q='+e,'lib');go('/api/find/catalog?group=work&limit='+FD_LIM.cat+'&q='+e,'cat');
  FDQT2=setTimeout(()=>{if(my===FDQSEQ)go('/api/find/hybrid?scope=all&k=16&q='+e,'sem')},200)}   // смысл — только когда пауза в наборе
function fdPaintLive(){const box=$('#fdLive'),q=FDL.q;
  if(q.length<2){box.hidden=true;FDROWS=[];['#fdGLib','#fdGCat','#fdGSem'].forEach(s=>{const g=$(s);g.hidden=true;g.querySelector('.fdrows').replaceChildren();g.querySelector('.fdrows')._m=null});$('#fdAct').hidden=true;$('#fdAct')._sig='';return}
  if(!FDL.lib||!FDL.cat)return;   // библиотека и каталог — одним кадром; до ответа видна прошлая выдача
  box.hidden=false;const lib=FDL.lib.results||[],cat=FDL.cat.items||[],sem=FDL.sem;const seen=new Set();
  const L=lib.slice(0,FD_LIM.lib).map(it=>({key:'i:'+it.id,kind:'item',it}));L.forEach(r=>seen.add(fdNT(r.it.author,r.it.title)));
  const C=cat.slice(0,FD_LIM.cat).map(w=>({key:'w:'+w.work_id,kind:'work',w}));C.forEach(r=>{seen.add(fdNT(r.w.author,r.w.title));(r.w.alt_titles||[]).forEach(t=>seen.add(fdNT(r.w.author,t)));(r.w.records||[]).forEach(x=>seen.add('k:'+x.key))});
  const S=[];if(sem&&sem.vec)for(const x of sem.items||[]){if(S.length>=FD_LIM.sem)break;if(!x.vec)continue;   // только векторные попадания: буквенные уже в группах выше
    if(x.kind==='item'){if(L.some(r=>r.it.id===x.id)||seen.has(fdNT(x.author,x.title)))continue;x.status=x.has_file?'done':'pending';x.narrator=x.reader;S.push({key:'i:'+x.id,kind:'item',it:x})}
    else if(x.kind==='src'){if(seen.has('k:'+x.src_key)||seen.has(fdNT(x.author,x.title))||x.availability==='members')continue;seen.add(fdNT(x.author,x.title));S.push({key:'s:'+x.src_key,kind:'src',s:x})}}
  fdPaintGroup($('#fdGLib'),L,FDL.lib);fdPaintGroup($('#fdGCat'),C,FDL.cat);fdPaintGroup($('#fdGSem'),S,sem&&sem.vec?sem:null);
  FDROWS=[...L,...C,...S];if(FDSEL>=FDROWS.length)FDSEL=0;fdSelect(FDSEL,true);
  $('#fdMs').textContent=Math.max(FDL.lib._ms||0,FDL.cat._ms||0)+' мс';fdPaintAct()}
// группа: строки по ключу переиспользуются (раскрытые записи не схлопываются), меняется только то, что изменилось
function fdPaintGroup(g,rows,resp){g.hidden=!rows.length;if(!rows.length){g.querySelector('.fdrows').replaceChildren();g.querySelector('.fdrows')._m=null;return}
  g.querySelector('.ms').textContent=resp&&resp.ms!=null?Math.round(resp.ms)+' мс':'';
  const list=g.querySelector('.fdrows'),old=list._m||new Map(),m=new Map();
  const els=rows.map(r=>{const sig=fdSig(r);let e=old.get(r.key);if(!e||e._sig!==sig){const n=fdRowEl(r);if(e&&e.classList.contains('open')){n.classList.add('open');fdRecsFill(n,r)}e=n;e._sig=sig}r.el=e;m.set(r.key,e);return e});
  list._m=m;list.replaceChildren(...els)}
function fdSig(r){const Q=(FDS&&FDS.queue)||[];if(r.kind==='item'){const it=r.it;return JSON.stringify(['i',FDL.q,it.id,it.has_file,it.in_queue,it.rstatus,it.overall,it.status])}
  if(r.kind==='work'){const w=r.w,b=w.records[0]||{};return JSON.stringify(['w',FDL.q,w.work_id,w.in_library,w.records.length,b.key,Q.filter(x=>w.records.some(y=>y.key===x.source_key)).map(x=>x.source_key+x.state)])}
  const s=r.s;return JSON.stringify(['s',FDL.q,s.src_key,Q.filter(x=>x.source_key===s.src_key).map(x=>x.state)])}
function fdSelect(i,quiet){FDSEL=i;FDROWS.forEach((r,j)=>{const row=r.el&&r.el.querySelector('.fdrow');if(row)row.classList.toggle('sel',j===i)});
  if(!quiet){const r=FDROWS[i];if(r&&r.el)r.el.scrollIntoView({block:'nearest'})}}
const fdKeyIdx=key=>FDROWS.findIndex(r=>r.key===key);
function fdRowEl(r){const wrap=el('div','fdit');wrap.dataset.key=r.key;const row=el('div','fdrow '+r.kind);wrap.appendChild(row);
  const t=el('div','t'),n=el('span','n'),m=el('div','m'),a=el('div','a');t.appendChild(n);row.appendChild(t);row.appendChild(m);row.appendChild(a);
  const sel=()=>{const i=fdKeyIdx(r.key);if(i>=0)fdSelect(i,true)};
  if(r.kind==='item'){const it=r.it;n.appendChild(hl((it.author?it.author+' — ':'')+it.title,FDL.q));const b=itemBadge(it);t.appendChild(el('span','badge '+b[1],b[0]));
    m.textContent=itemSmall(it)||'в библиотеке';
    if(!it.custom)a.appendChild(tgBtn(it,true));
    a.appendChild(moreBtn(()=>[{label:'Открыть карточку',onClick:()=>openItem(it.id)},it.has_file&&!it.custom?btnItem(qBtn(it,true)):null],true));
    row.onclick=()=>{sel();openItem(it.id)}}
  else if(r.kind==='work'){const w=r.w,best=w.records[0];n.appendChild(hl(fdClean((w.author?w.author+' — ':'')+w.title),FDL.q));
    if(w.in_library)t.appendChild(el('span','badge','в библиотеке'));
    const nb=el('button','fdn',fdPl(w.records.length,'запись','записи','записей')+' ▾');nb.type='button';nb.title='Показать все записи этой книги';nb.setAttribute('aria-expanded','false');nb.onclick=e=>{e.stopPropagation();fdToggleRecs(r)};t.appendChild(nb);
    m.textContent=[w.genre,(w.langs||[]).join('/'),best?fdRecLine(best):''].filter(Boolean).join(' · ');if(best&&(best.flags||[]).length)m.title=best.flags.join(' · ');
    if(best)fdSrcActs(a,{key:best.key,url:best.link||best.url,platform:best.platform,author:w.author,title:w.title,downloadable:best.downloadable,item_id:w.in_library});
    wrap.appendChild(el('div','fdrecl'));row.onclick=()=>{sel();fdToggleRecs(r)}}
  else{const s=r.s;n.appendChild(hl(fdClean((s.author?s.author+' — ':'')+s.title),FDL.q));t.appendChild(el('span','badge no',s.platform||'каталог'));
    m.textContent=[s.reader,s.hours!=null?fmtH(s.hours):'',s.channel&&s.channel!==s.platform?s.channel:'',s.lang,s.downloadable?'':'только ссылка'].filter(Boolean).join(' · ')||'запись каталога';
    fdSrcActs(a,{key:s.src_key,url:s.url,platform:s.platform,author:s.author,title:s.title,downloadable:s.downloadable});row.onclick=sel}
  return wrap}
const fdComp=x=>x.complete_score==null?'':x.complete_score>=.9?'полная':'неполная';
const fdClean=t=>String(t||'').replace(/[\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu,'').replace(/^[\s#|•·\-–—\[\]()]+/u,'').trim();
function fdRecLine(x){return [x.platform,x.narrator||'',fdH(x.duration),x.parts>1?fdPl(x.parts,'часть','части','частей'):'',fdComp(x),x.verified?'✓ проверено':'',x.availability==='members'?'только для спонсоров':'',!x.downloadable?'только ссылка':''].filter(Boolean).join(' · ')}
function fdToggleRecs(r){const w=r.el;if(!w)return;const open=!w.classList.contains('open');w.classList.toggle('open',open);const nb=w.querySelector('.fdn');if(nb){nb.setAttribute('aria-expanded',String(open));nb.textContent=fdPl(r.w.records.length,'запись','записи','записей')+(open?' ▴':' ▾')}
  if(open)fdRecsFill(w,r)}
function fdRecsFill(w,r){const L=w.querySelector('.fdrecl');if(!L||L.childElementCount)return;const best=r.w.records[0];
  const words=t=>norm(t).replace(/[^\p{L}\p{N}]+/gu,' ').trim().split(' ').sort().join(' '),same=t=>words(t)===words((r.w.author||'')+' '+r.w.title);   // своё название записи — только если это не те же слова
  for(const x of r.w.records.slice(0,16)){const d=el('div','fdrec'+(x===best?' best':''));const m=el('div','m',fdRecLine(x)+(x.title&&!same(x.title)?' · «'+x.title+'»':''));m.title=[x.title,...(x.flags||[])].filter(Boolean).join('\n');d.appendChild(m);
    const a=el('div','a');fdSrcActs(a,{key:x.key,url:x.link||x.url,platform:x.platform,author:r.w.author,title:r.w.title,downloadable:x.downloadable,item_id:x.in_library});d.appendChild(a);L.appendChild(d)}}
// действия у записи каталога: ссылка, скачать, в Telegram, в очередь, пожаловаться; книга уже в библиотеке — открыть
function fdSrcActs(a,c){const stop=(b,f)=>{b.onclick=e=>{e.stopPropagation();f(b)};b.onmousedown=e=>e.stopPropagation();return b};
  // строка «Найти»: слушать онлайн — главное; скачать — одной кнопкой с вариантами; пожаловаться — в том же меню
  const listen=el('button','ghost sm','▶ Слушать');listen.title='Открыть запись у источника и слушать онлайн (ссылка копируется)';stop(listen,()=>fdOpenLink(c.url,c.platform));
  const rep={label:'⚑ Что-то не так с записью',onClick:()=>reportDlg({src_key:c.key,url:c.url,author:c.author,title:c.title})};
  if(c.item_id){a.appendChild(listen);a.appendChild(stop(el('button','ghost sm','Открыть'),()=>openItem(c.item_id)));return}
  a.appendChild(listen);
  if(!c.downloadable){a.appendChild(moreBtn([rep],true));return}
  const Q=(FDS&&FDS.queue)||[],q=Q.find(x=>x.source_key===c.key);
  if(q&&q.state!=='cancelled'&&q.state!=='error'){a.appendChild(el('span','badge q',q.state==='done'?'✓ скачано':FD_QST[q.state]||q.state));if(q.state==='done')a.appendChild(stop(el('button','ghost sm','Открыть'),()=>openItem(q.item_id)));a.appendChild(moreBtn([rep],true));return}
  const act=(action,ok)=>async()=>{try{const j=await post('/api/find/act',{action,src_key:c.key,author:c.author,title:c.title});toast(j.message||ok,j.state==='failed'?'err':undefined);if(action==='tg'&&typeof pollTgNow==='function')pollTgNow(true);fdPoll(true)}catch(er){toast(er.message,'err')}};
  const dl=el('button','ghost sm','↓ Скачать ▾');dl.title='Скачать полную запись: проверка частей, склейка, проверка целостности';dl.setAttribute('aria-haspopup','menu');
  stop(dl,b=>ctxMenu(b,[{label:'На диск',title:'В библиотеку: проверка частей, склейка, проверка целостности',onClick:()=>fdDownload({catalog_key:c.key})},
    {label:'На диск и в очередь',onClick:act('queue','Скачаю и поставлю в очередь')},{label:'В Telegram',title:'Скачать, проверить и сразу отправить',onClick:act('tg','Скачаю и отправлю')},'-',rep]));
  a.appendChild(dl)}
async function fdOpenLink(url,platform){if(!url){toast('Ссылки нет','warn');return}window.open(url,'_blank','noopener');try{await navigator.clipboard.writeText(url);toast('Ссылка скопирована'+(platform?' · '+platform:''))}catch(e){}}
// Enter: книга библиотеки — открыть карточку; произведение — скачать лучшую запись (или открыть, если уже в библиотеке); запись — скачать
function fdMain(r){if(r.kind==='item')return openItem(r.it.id);
  if(r.kind==='work'){const w=r.w,b=w.records[0];if(w.in_library)return openItem(w.in_library);if(!b)return;return b.downloadable?fdDownload({catalog_key:b.key}):fdOpenLink(b.link||b.url,b.platform)}
  const s=r.s;return s.downloadable?fdDownload({catalog_key:s.src_key}):fdOpenLink(s.url,s.platform)}
function fdPrimary(){if(fdWish(FDL.q)&&!fdStrong())fdAsk(FDL.q,true);else fdSearch()}
const fdStrong=()=>{const lib=(FDL.lib&&FDL.lib.results)||[],cat=(FDL.cat&&FDL.cat.items)||[];return lib.length>0||!!(cat[0]&&cat[0].score>=55)};
// под выдачей — одна дорогая кнопка: в сеть (площадки + ИИ) или к консультанту; раскалённая, только если локально пусто
function fdPaintAct(){const a=$('#fdAct');if(FDL.q.length<2||!FDL.lib||!FDL.cat){a.hidden=true;a._sig='';return}a.hidden=false;
  const lib=(FDL.lib&&FDL.lib.results)||[],cat=(FDL.cat&&FDL.cat.items)||[],strong=fdStrong(),wish=fdWish(FDL.q)&&!strong,none=!lib.length&&!cat.length,hot=!best_primary();
  const sig=[strong,wish,none,hot,!!(FDS&&FDS.agy),none&&!!FDROWS.length].join();if(a._sig===sig)return;a._sig=sig;a.innerHTML='';
  a.appendChild(el('span','tx',none?(FDROWS.length?'По буквам ничего нет — выше только похожее по смыслу.':'В библиотеке и в каталоге ничего нет.'):wish?'Похоже на пожелание, а не на название.':'Не то?'));
  const net=el('button',!strong&&!wish&&hot?'btn primary':'btn','Искать в сети — площадки + ИИ');net.title='20–60 с: YouTube, archive.org, сайты, Claude'+(FDS&&FDS.agy?' и Antigravity':'')+'; каждая запись проверяется yt-dlp без скачивания';net.onclick=()=>fdSearch();a.appendChild(net);
  const ch=el('button',wish&&hot?'btn primary':'ghost','Спросить в чате');ch.title='Консультант помнит ваш вкус и советует по настроению';ch.onclick=()=>fdAsk(FDL.q,true);a.appendChild(ch);
  a.appendChild(el('span','note',FDS&&FDS.claude===false?'Claude Code CLI не найден — в сети только площадки':'в сети: 20–60 с, результат появится ниже'))}

/* ---------- общий опрос состояния ---------- */
async function fdPoll(now){clearTimeout(FDT);const my=PROFILE;let s;
  try{s=await api('/api/find/state')}catch(e){FDT=setTimeout(fdPoll,6000);return}if(my!==PROFILE)return;FDS=s;
  const sj=s.searches.find(x=>x.job),dl=s.queue.filter(x=>FD_ACT.includes(x.state)),mj=!!(s.map&&s.map.job);
  // процессы в рельсе: энергия сцены одна на всё (kit: «Сцена и процесс»)
  if(sj)procSet('fd-search',{label:'Поиск: '+sj.query,pct:null});else procEnd('fd-search',true);
  const cur=dl.find(x=>x.state!=='queued');
  if(cur)procSet('fd-dl',{label:(FD_QST[cur.state]||'')+' · '+(cur.title||cur.item_id)+(cur.state==='downloading'&&cur.n>1?' · '+cur.k+'/'+cur.n:''),pct:cur.state==='downloading'&&cur.pct!=null?cur.pct:null});else procEnd('fd-dl',true);
  if(mj)procSet('fd-map',{label:'Карта связей · пачка '+s.map.job.batch+'/'+s.map.job.batches,pct:s.map.job.batches?(s.map.job.batch-1)/s.map.job.batches:null});else procEnd('fd-map',true);
  const c=$('#c-find');if(c)c.textContent=dl.length?String(dl.length):'';
  if(FDMAPJ&&!mj&&s.map.last)toast(s.map.last.status==='done'?'Карта связей готова: '+s.map.have+' книг':'Карта связей: '+(s.map.last.error||s.map.last.status),s.map.last.status==='done'?'':'warn');FDMAPJ=mj;
  if(VIEW==='find'){fdPaintSearch();fdPaintQueue();fdPaintMap();if(FDL.lib&&FDL.cat)fdPaintLive()}
  for(const x of s.searches)if(x.status==='done'&&x.result&&x.result.kind==='prompt'&&!FD_DONE.has(x.id)&&x.id===FDCUR){FD_DONE.add(x.id);fdAsk(x.query,true)}
  const busy=sj||dl.length||mj;FDT=setTimeout(fdPoll,busy?1500:VIEW==='find'?8000:30000)}

/* ---------- результат поиска ---------- */
function fdCurSearch(){const L=(FDS&&FDS.searches)||[];return FDCUR?L.find(x=>x.id===FDCUR)||null:null}
function fdPaintSearch(){const box=$('#fdRes'),s=fdCurSearch();
  if(!s){box.innerHTML='';fdPaintAct();return}
  const sig=JSON.stringify([s.id,s.status,s.job&&[s.job.phase,s.job.sources,s.job.events.length],s.result&&s.result.library&&s.result.library.state,(FDS.queue||[]).map(q=>q.source_key+q.state).join()]);
  if(box._sig===sig&&!s.job){return}box._sig=sig;
  if(s.job){fdPaintRunning(box,s);fdPaintAct();return}
  box.innerHTML='';const p=el('div','fdplate');box.appendChild(p);
  const h=el('div','fdh');h.appendChild(el('h3',null,'«'+s.query+'»'));h.appendChild(el('span','sub',[fmtDT(s.finished||s.started),s.meta&&s.meta.seconds?fdmm(s.meta.seconds):'',s.auto?'из совета консультанта':''].filter(Boolean).join(' · ')));
  h.appendChild(el('span','spacer'));const hist=(FDS.searches||[]).filter(x=>x.id!==s.id&&!x.job).slice(0,4);
  if(hist.length){const sel=el('select','in sm');sel.setAttribute('aria-label','Прошлые поиски');sel.appendChild(new Option('прошлые поиски…',''));for(const x of hist)sel.appendChild(new Option('«'+x.query+'»',String(x.id)));sel.onchange=()=>{if(sel.value){FDCUR=+sel.value;$('#fdRes')._sig='';fdPaintSearch()}};h.appendChild(sel)}
  p.appendChild(h);const R=s.result||{};
  if(s.status==='cancelled'){p.appendChild(el('div','fdnone','Поиск отменён.'));return}
  if(s.status==='error'||!s.result){const n=el('div','fdnone','Поиск не получился: '+(s.error||'неизвестная ошибка')+'.');p.appendChild(n);const b=el('button','ghost sm','Повторить');b.onclick=()=>fdSearch(s.query);p.appendChild(b);return}
  if(R.kind==='prompt'){p.appendChild(el('div','fdwork','Это пожелание, а не название — отвечает консультант в «Что дальше».'));const b=el('button','ghost sm','Открыть разговор');b.onclick=()=>fdAsk(s.query,true);p.appendChild(b);return}
  const w=R.work||{};if(w.title){const d=el('div','fdwork');d.innerHTML='<b>'+esc((w.author?w.author+' — ':'')+'«'+w.title+'»')+'</b>'+esc([w.original_title&&norm(w.original_title)!==norm(w.title)?' ('+w.original_title+')':'',w.expected_h?' · полная запись ≈ '+fmtH(w.expected_h,true):'',w.narrator_wanted?' · чтец: '+w.narrator_wanted:'',w.kind_wanted==='radioplay'?' · радиоспектакль':''].join(''));p.appendChild(d)}
  const lib=R.library;if(lib&&lib.item){const it=lib.item,b=el('div','fdlib');const tx=el('div','tx');
    tx.textContent={downloaded:'Уже есть в библиотеке и скачано: ',downloading:'Уже качается: ',catalog:'Есть в каталоге библиотеки, но ещё не скачано: ',known:'Уже отмечено у вас: '}[lib.state]+(it.author?it.author+' — ':'')+'«'+it.title+'»'+(it.narrator?' · '+it.narrator:'')+(it.hours?' · '+fmtH(it.hours,it.hours_exact):'');b.appendChild(tx);
    const o=el('button','ghost sm','Открыть в библиотеке');o.onclick=()=>openItem(it.id);b.appendChild(o);
    if(lib.state==='catalog'){const d=el('button','ghost sm','Скачать эту запись');d.onclick=()=>fdDownload({item_id:it.id},d);b.appendChild(d)}p.appendChild(b)}
  if(R.kind==='unclear'&&R.clarify)p.appendChild(el('div','fdnone',R.clarify));
  const ch=R.choices||[];
  if(!ch.length){const n=el('div','fdnone');n.innerHTML='<b>Полной записи, которую можно скачать, не нашёл.</b> '+esc(R.clarify||'Уточните запрос: автор и название точнее, другой перевод или оригинальное название, чтец — или попробуйте «радиоспектакль».')+(R.checked?' Проверено кандидатов: '+R.checked+'.':'');p.appendChild(n)}
  else{const best=R.best,amb=R.ambiguous;
    if(!amb&&best){p.appendChild(fdCand(s,best,true));const rest=ch.filter(c=>c.key!==best.key);if(rest.length){p.appendChild(el('div','sub','Другие проверенные записи'));rest.forEach(c=>p.appendChild(fdCand(s,c,false)))}}
    else{p.appendChild(el('div','fdwork','Нашлось несколько подходящих записей — выберите:'));ch.forEach(c=>p.appendChild(fdCand(s,c,false)))}}
  const rej=R.rejected||[],src=R.sources||{};if(rej.length||Object.keys(src).length){const d=el('details');d.appendChild(el('summary','fdsum','Как искал: '+Object.keys(src).length+' источников · отсеяно '+rej.length));
    const sl=el('div','fdsrc');sl.style.marginTop='8px';for(const [k,v] of Object.entries(src))sl.appendChild(fdSrcChip(k,v));d.appendChild(sl);
    if(rej.length){const r=el('div','fdrej');rej.forEach(c=>r.appendChild(el('div',null,'✕ '+(c.title||c.url).slice(0,90)+' — '+(c.drop||''))));d.appendChild(r)}
    if((R.notes||[]).length)d.appendChild(el('div','fdrej',R.notes.join(' · ')));p.appendChild(d)}
  fdPaintAct()}
// одно раскалённое действие: пока на экране есть «Скачать» лучшего варианта, кнопки под мгновенной выдачей — обычные плиты
const best_primary=()=>!!$('#fdRes .fdc.best .btn.primary');
function fdSrcChip(k,v){const sp=el('span',v.state==='running'?'on':v.state==='done'&&v.n?'ok':v.state==='error'||v.state==='skip'?'bad':'');
  if(v.state==='running')sp.appendChild(el('i','live-dot'));sp.appendChild(document.createTextNode(k+(v.state==='done'?' · '+(v.n||0):v.state==='running'?' …':v.state==='skip'?' · нет':v.state==='error'?' · недоступно':'')));if(v.note)sp.title=v.note;return sp}
function fdPaintRunning(box,s){let r=box.querySelector('.fdrun');const j=s.job;
  if(!r||r.dataset.id!==String(s.id)){box.innerHTML='';const p=el('div','fdplate');r=el('div','fdrun');r.dataset.id=s.id;
    r.innerHTML='<div class="top"><i class="live-dot"></i><span class="ph"></span><b class="tm">00:00</b></div><div class="meter indet"><div class="meter-fill"></div><div class="meter-glow"></div></div><div class="fdsrc"></div><div class="fdev"></div>';
    const h=el('div','fdh');h.appendChild(el('h3',null,'Ищу «'+s.query+'»'));h.appendChild(el('span','spacer'));const c=el('button','ghost sm','Отменить');c.onclick=async()=>{c.disabled=true;try{await post('/api/find/search/cancel',{id:s.id});toast('Отменяю…','warn')}catch(e){toast(e.message,'err')}};h.appendChild(c);
    p.appendChild(h);p.appendChild(r);p.appendChild(el('p','sub','Обычно 1–4 минуты. Можно уйти на другую вкладку — результат будет здесь.'));box.appendChild(p)}
  r.querySelector('.ph').textContent=j.phase;const sl=r.querySelector('.fdsrc');sl.innerHTML='';for(const [k,v] of Object.entries(j.sources||{}))sl.appendChild(fdSrcChip(k,v));
  const ev=r.querySelector('.fdev');ev.innerHTML='';for(const e of (j.events||[]).slice(-5)){const d=el('div');d.innerHTML='<b>'+esc(e.who||'')+' · '+(e.kind==='search'?'поиск':'страница')+'</b> '+esc(e.kind==='search'?'«'+e.text+'»':e.text.replace(/^https?:\/\//,''));ev.appendChild(d)}
  const t0=Date.now()-j.elapsed*1000;clearInterval(FDTICK);const tick=()=>{const t=r.querySelector('.tm');if(!t||!t.isConnected){clearInterval(FDTICK);return}t.textContent=fdmm((Date.now()-t0)/1000)};tick();FDTICK=setInterval(tick,500)}
function fdCand(s,c,best){const d=el('div','fdc'+(best?' best':''));
  const tt=el('div','tt',c.title||c.url);d.appendChild(tt);
  const parts=c.type==='playlist'?'плейлист · '+fdPl(c.parts,'часть','части','частей'):c.type==='files'?fdPl(c.parts,'файл','файла','файлов'):c.type==='parts'?fdPl(c.parts,'часть','части','частей'):'один файл';
  d.appendChild(el('div','mt',[c.platform,c.narrator?'читает '+c.narrator:'',fdH(c.duration),parts,FD_KIND[c.kind]||'',c.lang].filter(Boolean).join(' · ')));
  const fl=el('div','fl');fl.appendChild(el('span','badge q','✓ проверено: скачивается'));if(c.narrator_match)fl.appendChild(el('span','badge','чтец совпал'));(c.flags||[]).forEach(f=>fl.appendChild(el('span','badge no',f)));d.appendChild(fl);
  const by=el('div','by');by.appendChild(document.createTextNode('нашли: '+(c.found_by||[]).join(', ')+' · '));const a=el('a',null,'открыть источник');a.href=c.url;a.target='_blank';a.rel='noopener noreferrer';by.appendChild(a);d.appendChild(by);
  if(c.note)d.appendChild(el('div','note',c.note));
  const act=el('div','act');const q=(FDS.queue||[]).find(x=>x.source_key===c.key);
  const listen=el('button','ghost sm','▶ Слушать');listen.title='Открыть у источника и слушать онлайн (ссылка копируется)';listen.onclick=()=>fdOpenLink(c.url,c.platform);act.appendChild(listen);
  if(q&&q.state!=='cancelled'&&q.state!=='error'){act.appendChild(el('span','badge q',q.state==='done'?'✓ скачано':FD_QST[q.state]||q.state));if(q.state==='done'){const o=el('button','ghost sm','Открыть');o.onclick=()=>openItem(q.item_id);act.appendChild(o)}}
  else{const dl=el('button',best?'btn primary sm':'ghost sm','↓ Скачать ▾');dl.title='Скачать полную запись: проверка частей, склейка, проверка целостности';dl.setAttribute('aria-haspopup','menu');
    const viaCat=(action,ok)=>async()=>{try{const j=await post('/api/find/act',{action,src_key:c.key,author:(s.result&&s.result.work&&s.result.work.author)||'',title:c.title});toast(j.message||ok,j.state==='failed'?'err':undefined);fdPoll(true)}catch(er){toast(er.message,'err')}};
    dl.onclick=()=>ctxMenu(dl,[{label:'На диск',title:'В библиотеку: проверка частей, склейка, проверка целостности',onClick:()=>fdDownload({search_id:s.id,key:c.key},dl)},
      c.catalog_id?{label:'На диск и в очередь',onClick:viaCat('queue','Скачаю и поставлю в очередь')}:null,c.catalog_id?{label:'В Telegram',title:'Скачать, проверить и сразу отправить',onClick:viaCat('tg','Скачаю и отправлю')}:null,'-',
      {label:'⚑ Что-то не так с записью',onClick:()=>reportDlg({url:c.url,src_key:c.catalog_id?c.key:'',author:(s.result&&s.result.work&&s.result.work.author)||'',title:c.title,other:false})}]);act.appendChild(dl)}
  d.appendChild(act);return d}
async function fdDownload(body,btn){if(btn)btn.disabled=true;try{const j=await post('/api/find/download',body);
    toast(j.already?'Уже в загрузках · №'+(j.position||'?'):j.started?'Скачиваю — прогресс в «Загрузки» и в рельсе':'В очереди загрузок · №'+(j.position||'?'));kick(.35);$('#fdRes')._sig='';await fdPoll(true)}
  catch(e){toast(e.message,'err');if(btn)btn.disabled=false}}

/* ---------- очередь загрузок ---------- */
function fdPaintQueue(){const box=$('#fdDl'),Q=(FDS&&FDS.queue)||[];box.hidden=!Q.length;if(!Q.length)return;
  const sig=JSON.stringify(Q.map(q=>[q.key,q.state,q.k,q.n,q.pct,q.stage,q.message,q.warn,q.check&&q.check.verdict,q.has_file]));if(box._sig===sig)return;box._sig=sig;
  box.innerHTML='';const h=el('div','fdh');h.appendChild(el('h3',null,'Загрузки'));h.appendChild(el('span','sub','abook get · по одной книге · очередь переживает перезапуск'));box.appendChild(h);const L=el('div','fdq');box.appendChild(L);
  const fin=Q.filter(q=>!FD_ACT.includes(q.state));const shown=FDQALL?Q:Q.filter(q=>FD_ACT.includes(q.state)||fin.indexOf(q)<16);
  for(const q of shown){const r=el('div','fdqi');r.appendChild(el('div','t',(q.author?q.author+' — ':'')+(q.title||q.item_id)));
    const act=FD_ACT.includes(q.state);let st=q.state==='queued'?'в очереди · №'+(q.position||'?')+(q.resumed?' (после перезапуска)':''):FD_QST[q.state]||q.state;
    if(q.state==='downloading')st+=(q.n>1?' '+q.k+'/'+q.n:'')+(q.pct!=null?' · '+Math.round(q.pct*100)+'%':'')+(q.stage&&q.stage!=='скачиваю'?' · '+q.stage:'');
    else if(q.state==='checking')st=q.stage||st;else if(q.state==='done')st+=(q.message?' · '+q.message:'')+(q.check?' · проверка: '+q.check.verdict_ru:'');
    else if(q.state==='error')st+=': '+(q.message||'');
    r.appendChild(el('div','s',st));const b=el('div','b');
    if(q.state==='done'||q.has_file){const o=el('button','ghost sm','Открыть в библиотеке');o.onclick=()=>openItem(q.item_id);b.appendChild(o)}
    if(q.state==='error'||q.state==='cancelled'){const rb=el('button','ghost sm','Повторить');rb.onclick=()=>fdQop('retry',q.key);b.appendChild(rb)}
    if(q.state==='error'||q.state==='done')b.appendChild(reportBtn({item_id:q.item_id,author:q.author,title:q.title}));
    const x=el('button','ghost sm',act?(q.state==='queued'?'Убрать':'Отменить'):'Убрать');x.onclick=async()=>{if(act&&q.state!=='queued'&&!await confirmDlg('Отменить загрузку?','«'+(q.title||q.item_id)+'»: скачивание будет прервано, недокачанное удалится. Повторить можно в любой момент.','Прервать','plain'))return;fdQop('remove',q.key)};b.appendChild(x);r.appendChild(b);
    if(act&&q.state!=='queued'){const m=el('div','meter'+(q.state==='downloading'&&q.pct!=null?'':' indet'));m.innerHTML='<div class="meter-fill"></div><div class="meter-glow"></div>';m.style.setProperty('--p',q.pct!=null&&q.state==='downloading'?q.pct:1);r.appendChild(m)}
    const w=[q.warn,q.check&&q.check.problem?'⚠ '+q.check.summary:''].filter(Boolean).join(' · ');if(w)r.appendChild(el('div','w',w));L.appendChild(r)}
  if(fin.length>16){const m=el('button','linkbtn',FDQALL?'свернуть':'ещё '+(fin.length-16)+' завершённых');m.onclick=()=>{FDQALL=!FDQALL;box._sig='';fdPaintQueue()};box.appendChild(m)}}
let FDQALL=false;
async function fdQop(op,key){try{await post('/api/find/queue',{op,key});toast(op==='retry'?'Снова в очереди':'Готово');$('#fdDl')._sig='';await fdPoll(true)}catch(e){toast(e.message,'err')}}

/* ---------- карта связей ---------- */
function fdPaintMap(){const box=$('#fdMap'),m=FDS&&FDS.map;if(!m)return;const sig=JSON.stringify([m.have,m.todo,m.job,m.last,m.top.length]);if(box._sig===sig)return;box._sig=sig;box.innerHTML='';
  const h=el('div','fdh');h.appendChild(el('h3',null,'Карта связей'));h.appendChild(el('span','sub','глубинные признаки книг · для «мостов»'));box.appendChild(h);
  const big=el('div','big',String(m.have));big.appendChild(el('small',null,'из '+m.total+' книг с признаками'));box.appendChild(big);
  if(m.job){const t=el('div','tx',m.job.phase+' · готово книг: '+m.job.done_books+' из '+m.job.todo_books);box.appendChild(t);const mt=el('div','meter');mt.innerHTML='<div class="meter-fill"></div><div class="meter-glow"></div>';mt.style.setProperty('--p',m.job.batches?(m.job.batch-1+.5)/m.job.batches:0);box.appendChild(mt);
    if((m.job.errors||[]).length)box.appendChild(el('div','sub',m.job.errors.slice(-2).join(' · ')));const c=el('button','ghost sm','Остановить');c.onclick=async()=>{c.disabled=true;try{await post('/api/find/map',{op:'cancel'});toast('Останавливаю после текущей пачки…','warn')}catch(e){toast(e.message,'err')}};box.appendChild(c);return}
  const tx=el('div','tx');tx.textContent=m.have?(m.todo?'Новых или изменённых книг: '+m.todo+' → ≈ '+fdPl(m.calls,'вызов','вызова','вызовов')+' Claude '+m.model+', ≈ '+m.minutes+' мин в фоне.':'Все книги с признаками. Новые скачанные книги досчитываются по кнопке.')
    :'Не построена. Для '+m.total+' книг — ≈ '+fdPl(m.calls,'вызов','вызова','вызовов')+' Claude '+m.model+' (по '+m.batch+' книг), ≈ '+m.minutes+' мин в фоне. Один раз: дальше досчитываются только новые книги. Нужна для «мостов» консультанта и блока «Связи» в карточке книги.';box.appendChild(tx);
  if(m.last&&m.last.status!=='done')box.appendChild(el('div','sub','Прошлый запуск: '+(m.last.error||m.last.status)+((m.last.errors||[]).length?' · '+m.last.errors.slice(-1)[0]:'')));
  if(m.todo){const b=el('button','btn',m.have?'Досчитать '+fdPl(m.todo,'книгу','книги','книг'):'Построить карту связей');b.disabled=!m.claude;b.onclick=async()=>{b.disabled=true;try{const j=await post('/api/find/map',{op:'start'});toast('Карта связей: '+fdPl(j.calls,'вызов','вызова','вызовов')+' Claude, '+j.books+' книг');FDMAPJ=true;$('#fdMap')._sig='';fdPoll(true)}catch(e){toast(e.message,'err');b.disabled=false}};box.appendChild(b);if(!m.claude)box.appendChild(el('div','sub','Claude Code CLI не найден'))}
  if(m.top.length){box.appendChild(el('div','sub','Самые связующие признаки'));const t=el('div','fdtags');m.top.forEach(x=>{const s=el('span',null,x.label);s.appendChild(el('i',null,String(x.n)));t.appendChild(s)});box.appendChild(t)}}

/* ---------- консультант: обычный чат в «Что дальше» ---------- */
// разметка лежит в <template> во вкладке «Найти» и при загрузке переезжает над рекомендациями «Что дальше»
let FDCHP=null,FDCHAT=0,FDPEND=null;   // профиль и время последней загрузки; отправленное, но ещё не подтверждённое сервером
function loadChat(){if(FDCHP!==PROFILE){FDSESS=0;FDCH=null;FDCHP=PROFILE}fdPaintDist();fdChatLoad(true);requestAnimationFrame(()=>{fdGrow();$('#fdAsk').focus()})}
// «Что дальше»: короткий вход в чат — вопрос уходит в новый разговор на экране «Чат»
function fdChatMount(){if($('#fdAskNx'))return;const w=el('div','fdask');w.innerHTML='<div class="field"><div class="field-ring"></div><div class="field-body"><input id="fdAskNx" maxlength="2000" autocomplete="off" aria-label="Вопрос консультанту" placeholder="Спросите консультанта: «как Солярис, но короче»…"></div></div>';
  const b=el('button','btn','Открыть чат');b.onclick=()=>show('chat');w.appendChild(b);$('#nxAi').before(w);
  $('#fdAskNx').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.value.trim()){e.preventDefault();const t=e.target.value.trim();e.target.value='';show('chat');FDSESS=-1;fdAsk(t)}})}
// «Прыжок»: одна шкала — близко … далеко, крайняя точка «✦ Удиви» = совсем далеко + режим «удиви меня».
// «Книг»: Авто (сколько сильных попаданий, 1–7) или ровно 3 / 5 / 10. Оба выбора помнятся.
let FDCNT=+store.get('abook.fd.cnt','0')||0;
const FD_JUMP=[['Близко','тот же жанр и настроение'],['Рядом','соседние жанры'],['Дальше','другой жанр, эпоха или форма'],['Далеко','то, о чём вы вряд ли думали'],['✦ Удиви','смелые мосты в неожиданное']];
function fdSeg(s,items,cur,on){s.innerHTML='';items.forEach(([t,ti],i)=>{const b=el('button',i===cur?'on':'',t);b.type='button';b.title=ti||'';b.setAttribute('role','radio');b.setAttribute('aria-checked',String(i===cur));
    b.onclick=()=>{on(i);s.querySelectorAll('button').forEach((x,j)=>{x.classList.toggle('on',j===i);x.setAttribute('aria-checked',String(j===i))});inkSeg(s)};s.appendChild(b)});inkSeg(s,true)}
function fdPaintDist(){if($('#fdDist').childElementCount)return;const surp=store.get('abook.fd.surp','0')==='1';$('#fdSurp').checked=surp;
  fdSeg($('#fdDist'),FD_JUMP,surp?4:FDDIST,i=>{FDDIST=Math.min(i,3);$('#fdSurp').checked=i===4;store.set('abook.fd.dist',String(FDDIST));store.set('abook.fd.surp',i===4?'1':'0')});
  const C=[[0,'Авто','столько, сколько действительно сильных попаданий'],[3,'3'],[5,'5'],[10,'10']];
  fdSeg($('#fdCnt'),C.map(([,t,ti])=>[t,ti]),Math.max(0,C.findIndex(x=>x[0]===FDCNT)),i=>{FDCNT=C[i][0];store.set('abook.fd.cnt',String(FDCNT))})}
const fdGrow=()=>{const t=$('#fdAsk');t.style.height='auto';t.style.height=Math.min(200,t.scrollHeight)+'px'};
$('#fdAsk').addEventListener('input',()=>{fdGrow();store.set('abook.fd.draft.'+PROFILE,$('#fdAsk').value)});
$('#fdAsk').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();e.stopPropagation();if(FDCH&&FDCH.job)return;fdAsk()}
  else if(e.key==='ArrowUp'&&!$('#fdAsk').value&&!(FDCH&&FDCH.job)){const w=$('#fdLastU');if(w&&w._m){e.preventDefault();fdEdit(w,w._m)}}
  else if(e.key==='Escape'&&FDCH&&FDCH.job&&!$('#fdAsk').value){e.preventDefault();e.stopPropagation();fdStop()}});
$('#fdNew').onclick=()=>{FDSESS=-1;$('#fdIncog').checked=false;fdPaintChat({...(FDCH||{}),messages:[],session_id:null,job:null});$('#fdAsk').focus()};
$('#fdIncog').onchange=()=>{if(FDSESS>0){FDSESS=-1}fdPaintChat({...(FDCH||{}),messages:[],session_id:null,job:null});$('#fdAsk').focus()};
function fdOpenSess(id){FDSESS=id;fdChatLoad(true)}
// память консультанта и карта связей живут в «Настройке», а не в поиске
(()=>{const c=el('div','cols');c.id='fdMemMap';c.innerHTML='<div class="fdplate" id="fdMem"></div><div class="fdplate fdmap" id="fdMap"></div>';const f=$('#v-setup .sufoot');if(f)f.before(c);else $('#v-setup')?.appendChild(c)})();
function loadMemMap(){api('/api/find/memory').then(j=>fdPaintMem(j.memory||[])).catch(()=>{});fdPoll(true)}
// ИИ-провайдер для всего приложения: Claude или Antigravity (Gemini) — переключатель в шапке чата
let FDLLM=null;
async function fdPaintLlm(cur,busy){const sg=$('#fdLlm');if(!FDLLM){try{FDLLM=await api('/api/llm')}catch(e){return}}
  const k=sg.dataset.k;if(k===cur+'|'+busy)return;sg.dataset.k=cur+'|'+busy;sg.innerHTML='';
  for(const [p,t] of [['claude','Claude'],['agy','Antigravity']]){const b=el('button',p===cur?'on':'',t);b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked',String(p===cur));
    b.disabled=busy||!FDLLM.available[p];b.title=FDLLM.available[p]?(p==='claude'?'Claude Code: Opus / Sonnet / Haiku':'Antigravity: Gemini 3.1 Pro / 3.8 Flash')+' — для всех функций ИИ':'CLI не найден';
    b.onclick=async()=>{if(p===cur)return;try{FDLLM=await post('/api/llm',{provider:p});toast('ИИ: '+FDLLM.label);fdChatLoad()}catch(e){toast(e.message,'err')}};sg.appendChild(b)}inkSeg(sg,true)}
// режим чата: класс на body по видимости экрана (подписи пунктов меню — в подсказки, раз в свёрнутом виде их нет)
$$('#nav button').forEach(b=>{const l=b.querySelector('.l');if(l&&!b.title)b.title=l.textContent});
new MutationObserver(()=>document.body.classList.toggle('chatmode',!$('#v-chat').hidden)).observe($('#v-chat'),{attributes:true,attributeFilter:['hidden']});
document.body.classList.toggle('chatmode',!$('#v-chat').hidden);
$('#fdDown').onclick=()=>{const b=$('#fdMsgs');b.scrollTop=b.scrollHeight};
async function fdAsk(text,fromSearch){text=(text??$('#fdAsk').value).trim();if(!text){$('#fdAsk').focus();return}
  if(FDCH&&FDCH.job){toast('Консультант ещё отвечает','warn');return}
  if(fromSearch&&VIEW!=='chat'){show('chat');FDSESS=-1}
  const own=!fromSearch||$('#fdAsk').value.trim()===text;if(own){$('#fdAsk').value='';store.set('abook.fd.draft.'+PROFILE,'');fdGrow()}
  FDPEND={text,distance:FDDIST,surprise:$('#fdSurp').checked,count:FDCNT};$('#fdSend').disabled=true;
  if(FDCH)fdPaintChat(FDSESS===-1?{...FDCH,messages:[],session_id:null}:FDCH,true);   // сообщение — в ленту сразу, не дожидаясь сервера
  try{const j=await post('/api/find/chat',{session_id:FDSESS>0?FDSESS:null,...FDPEND,incognito:FDSESS>0?undefined:$('#fdIncog').checked});FDSESS=j.session_id;FDPEND=null;await fdChatLoad(true)}
  catch(e){FDPEND=null;toast(e.message,'err');if(own&&!$('#fdAsk').value){$('#fdAsk').value=text;fdGrow()}if(FDCH)fdPaintChat(FDCH)}finally{$('#fdSend').disabled=!!(FDCH&&!FDCH.claude)}}   // while the job runs the button reads «Остановить» — it must stay live
// Markdown ответа: экранируем всё, потом разрешаем узкий набор — абзацы, **жирный**, *курсив*, `код`, списки, заголовки, ссылки
function fdMd(t){const inl=x=>esc(x).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>').replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,'$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  const out=[];let list=null;
  for(const raw of String(t||'').split('\n')){const l=raw.trimEnd();const m=l.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/);
    if(m){const tag=m[1]?'ol':'ul';if(!list||list.tag!==tag){list={tag,items:[]};out.push(list)}list.items.push(inl(m[2]));continue}
    list=null;if(!l.trim())continue;const h=l.match(/^#{1,4}\s+(.*)$/);out.push(h?'<h4>'+inl(h[1])+'</h4>':'<p>'+inl(l)+'</p>')}
  return out.map(x=>typeof x==='string'?x:'<'+x.tag+'>'+x.items.map(i=>'<li>'+i+'</li>').join('')+'</'+x.tag+'>').join('')}
const fdMdC=t=>{const h=fdMd(t),c='<span class="caret"></span>';const i=h.search(/<\/(p|li|h4)>(<\/[ou]l>)?$/);return i<0?h+c:h.slice(0,i)+c+h.slice(i)};
async function fdCopy(t){try{await navigator.clipboard.writeText(t);toast('Скопировано')}catch(e){toast('Не удалось скопировать','err')}}
// поток: пока Claude пишет — лёгкий опрос /chat/live 4 раза в секунду, полная перезагрузка разговора — по окончании
let FDLIVE=null;
async function fdLiveTick(){clearTimeout(FDLIVE);FDLIVE=null;let j;try{j=(await api('/api/find/chat/live')).job}catch(e){FDLIVE=setTimeout(fdLiveTick,1500);return}
  if(!j){fdChatLoad(true);return}
  if(FDCH&&FDCH.job){FDCH.job={...FDCH.job,...j};const box=$('#fdMsgs'),end=box.scrollHeight-box.scrollTop-box.clientHeight<80;
    const rp=box.querySelector('.fdm.a.live .rp'),ph=box.querySelector('.fdm.a.live .run span');if(ph)ph.textContent=j.phase;
    if(rp&&rp._t!==j.text){rp._t=j.text;rp.innerHTML=fdMdC(j.text);rp.hidden=!j.text}
    if(end)box.scrollTop=box.scrollHeight;fdJump()}
  FDLIVE=setTimeout(fdLiveTick,250)}
function fdJump(){const box=$('#fdMsgs'),b=$('#fdDown');if(b)b.hidden=box.scrollHeight-box.scrollTop-box.clientHeight<120}
$('#fdMsgs').addEventListener('scroll',fdJump,{passive:true});
async function fdChatLoad(stick){clearTimeout(FDCHT);FDCHT=null;const my=PROFILE;let c;try{c=await api('/api/find/chat'+(FDSESS>0?'?session='+FDSESS:''))}catch(e){FDCHT=setTimeout(fdChatLoad,6000);return}if(my!==PROFILE)return;
  FDCHAT=Date.now();const was=!!(FDCH&&FDCH.job);FDCH=c;if(FDSESS!==-1)FDSESS=c.session_id||0;
  if(c.job)procSet('fd-chat',{label:'Консультант · '+c.job.phase,pct:null});else if(was){procEnd('fd-chat',true);stick=true;const last=(c.messages||[]).slice(-1)[0];if(last&&last.status==='done'){kick(.3);const mm=(last.data||{}).memory||{};if(mm.added)toast('Память консультанта: +'+fdPl(mm.added,'факт','факта','фактов'))}else if(last&&last.status==='error')toast('Консультант: '+(last.error||'ошибка'),'err')}
  fdPaintChat(FDSESS===-1&&!c.job?{...c,messages:[],session_id:null}:c,stick);
  if(c.job){if(!FDLIVE)fdLiveTick();return}
  const live=(c.messages||[]).some(m=>((m.data||{}).recs||[]).some(r=>Object.values(r.act||{}).some(a=>a.state==='search'||a.state==='download')||(r.dl&&FD_ACT.includes(r.dl.state))));
  if(live)FDCHT=setTimeout(fdChatLoad,4000)}
async function fdStop(){try{await post('/api/find/chat/cancel',{});toast('Останавливаю…','warn')}catch(e){toast(e.message,'err')}}
async function fdRegen(){if(!FDCH||!FDCH.session_id)return;try{await post('/api/find/chat/regen',{session_id:FDCH.session_id});await fdChatLoad(true)}catch(e){toast(e.message,'err')}}
function fdEdit(wrap,m){const u=wrap.querySelector('.fdm.u');const e=el('div','fdm u edit');const ta=el('textarea');ta.value=m.text;e.appendChild(ta);const b=el('div','b');
  const no=el('button','ghost sm','Отмена');no.onclick=()=>fdPaintChat(FDCH);const ok=el('button','btn sm primary','Отправить');
  const go=async()=>{const t=ta.value.trim();if(!t)return;ok.disabled=true;try{await post('/api/find/chat/edit',{session_id:FDCH.session_id,message_id:m.id,text:t,distance:FDDIST,surprise:$('#fdSurp').checked,count:FDCNT});await fdChatLoad(true)}catch(er){toast(er.message,'err');ok.disabled=false}};
  ok.onclick=go;ta.onkeydown=ev=>{if(ev.key==='Enter'&&!ev.shiftKey){ev.preventDefault();go()}else if(ev.key==='Escape'){ev.preventDefault();ev.stopPropagation();fdPaintChat(FDCH)}};
  b.appendChild(no);b.appendChild(ok);e.appendChild(b);wrap.replaceChildren(e);ta.focus();ta.setSelectionRange(ta.value.length,ta.value.length)}
function fdPaintChat(c,stick){if(!c)return;const box=$('#fdMsgs'),col=$('#fdCol');
  const atEnd=stick||box.scrollHeight-box.scrollTop-box.clientHeight<60,keep=box.scrollTop;
  // разговоры — список слева: фильтр, переименование двойным щелчком, удаление
  const sl=$('#fdSess');sl.innerHTML='';const flt=($('#fdSFind')?.value||'').trim().toLowerCase();
  const cur=(c.sessions||[]).find(x=>x.id===c.session_id);if(cur)$('#fdIncog').checked=!!cur.incognito;$('#fdIncog').disabled=!!c.job;
  $('#fdTitle').textContent=cur?cur.title||'Без названия':'Новый чат';$('#fdMain').classList.toggle('incog',$('#fdIncog').checked);
  const day=d=>{const t=new Date(d),n=new Date();const k=Math.floor((new Date(n.toDateString())-new Date(t.toDateString()))/864e5);return k<=0?'Сегодня':k===1?'Вчера':k<7?'На этой неделе':'Раньше'};let lastG='';
  for(const x of (c.sessions||[]).filter(x=>!flt||(x.title||'').toLowerCase().includes(flt))){const g=day(x.updated);if(g!==lastG){sl.appendChild(el('div','grp',g));lastG=g}
    const r=el('div','si'+(x.id===c.session_id?' on':''));const b=el('button',null,(x.incognito?'◌ ':'')+(x.title||'без названия'));b.title=(x.title||'')+'\nдвойной щелчок — переименовать';b.appendChild(el('small',null,hm(x.updated)+' · '+fdPl(x.n||0,'вопрос','вопроса','вопросов')+(x.incognito?' · инкогнито':'')));b.onclick=()=>fdOpenSess(x.id);
    b.ondblclick=()=>{const i=el('input','in fdsfind');i.value=x.title||'';r.replaceChild(i,b);i.focus();i.select();const done=async sv=>{if(!i.isConnected)return;if(sv&&i.value.trim()&&i.value.trim()!==x.title){try{await post('/api/find/chat/rename',{session_id:x.id,title:i.value});x.title=i.value.trim()}catch(e){toast(e.message,'err')}}fdPaintChat(FDCH)};
      i.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();done(true)}else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();done(false)}};i.onblur=()=>done(true)};r.appendChild(b);
    const d=el('button','x','×');d.title='удалить разговор';d.setAttribute('aria-label','удалить разговор');d.onclick=async()=>{if(!await confirmDlg('Удалить разговор?','«'+(x.title||'без названия')+'» исчезнет вместе с ответами. Память консультанта останется.','Удалить'))return;
      try{await post('/api/find/chat/delete',{session_id:x.id});if(FDSESS===x.id)FDSESS=0;fdChatLoad(true)}catch(e){toast(e.message,'err')}};r.appendChild(d);sl.appendChild(r)}
  if(!(c.sessions||[]).length)sl.appendChild(el('div','sub','Здесь будут разговоры.'));
  if(!$('#fdSFind')&&(c.sessions||[]).length>6){const f=el('input','in fdsfind');f.id='fdSFind';f.placeholder='Найти разговор';f.oninput=()=>fdPaintChat(FDCH);sl.before(f)}
  const nm=(c.memory||[]).filter(m=>m.kind!=='not_interested').length;const ft=$('#fdSideFoot');ft.innerHTML='';const mb=el('button',null,'Память: '+fdPl(nm,'факт','факта','фактов'));mb.onclick=()=>{show('setup');setTimeout(()=>$('#fdMemMap')?.scrollIntoView({block:'start'}),300)};mb.title='Что консультант помнит о вашем вкусе — правится в «Настройке»';ft.appendChild(mb);
  const ob=el('button',null,'Obsidian ↗');ob.title='Выгрузить память, профиль, книги и разговоры в vault Obsidian (D:). Двойной щелчок — забрать оттуда ваши новые факты';
  ob.onclick=async()=>{ob.disabled=true;try{const j=await post('/api/find/vault',{op:'export'});try{await navigator.clipboard.writeText(j.windows_path)}catch(e){}toast('Obsidian: '+j.notes+' заметок ('+j.written+' обновлено) · путь скопирован: '+j.windows_path)}catch(e){toast(e.message,'err')}finally{ob.disabled=false}};
  ob.ondblclick=async()=>{try{const j=await post('/api/find/vault',{op:'import'});toast('Из Obsidian: +'+j.added+' фактов');fdChatLoad()}catch(e){toast(e.message,'err')}};
  ft.appendChild(document.createTextNode(' · '));ft.appendChild(ob);
  $('#fdChSub').textContent=!c.claude?'CLI выбранного ИИ не найден — консультант недоступен':$('#fdIncog').checked?'инкогнито · без профиля и памяти · '+c.model:'помнит ваш вкус · '+c.model;fdPaintLlm(c.provider,!!c.job);
  // одна кнопка: «Отправить» ↔ «Остановить», как в браузерных чатах
  const sb=$('#fdSend');const busy=!!c.job||!!FDPEND;sb.textContent=busy?'■ Остановить':'Отправить';sb.classList.toggle('primary',!busy);sb.disabled=!c.claude||(!!FDPEND&&!c.job);sb.onclick=busy?fdStop:()=>fdAsk();
  if(!$('#fdAsk').value&&!FDPEND){const d=store.get('abook.fd.draft.'+PROFILE,'');if(d){$('#fdAsk').value=d;fdGrow()}}
  col.innerHTML='';const M=[...(c.messages||[])];
  if(FDPEND)M.push({role:'user',text:FDPEND.text,created:new Date().toISOString(),meta:FDPEND},{role:'assistant',status:'running'});
  $('#fdMain').classList.toggle('blank',!M.length);if(!M.length){const e=el('div','fdempty');e.appendChild(el('h3',null,$('#fdIncog').checked?'Инкогнито: начнём с чистого листа':'Что послушать дальше?'));
    e.appendChild(el('p',null,$('#fdIncog').checked?'Не вижу ваших отзывов, анкеты и памяти и ничего не запомню. Ищу по всей библиотеке и каталогу источников.':'Ниже — подбор по вашему вкусу из всего каталога; спросите консультанта, если хочется точнее: он видит отзывы, анкету и память. Любую книгу — в очередь или в Telegram одной кнопкой, даже если её ещё нет на диске.'));
    const f=el('div','fdfu');['Что после последней пятёрки?','Мрачное и короткое, до 5 часов','Удиви меня чем-нибудь не из фантастики','Радиоспектакль на вечер'].forEach(t=>{const b=el('button','chip',t);b.type='button';b.onclick=()=>fdAsk(t);f.appendChild(b)});e.appendChild(f);col.appendChild(e)}
  fdForPlace();if(!$('#fdIncog').checked)fdForLoad();
  const lastA=M.map(m=>m.role).lastIndexOf('assistant'),lastU=M.map(m=>m.role).lastIndexOf('user');
  M.forEach((m,i)=>{if(m.role==='user'){const w=el('div','fdwrapu');const u=el('div','fdm u',m.text);const mt=m.meta||{};u.appendChild(el('small',null,[m.created?hm(m.created):'',mt.surprise?'✦ удиви':['близко','рядом','дальше','далеко'][mt.distance||0],mt.count?mt.count+' книг':'авто'].filter(Boolean).join(' · ')));w.appendChild(u);
      if(m.id){const ac=el('div','acts');const cp=el('button',null,'Копировать');cp.onclick=()=>fdCopy(m.text);ac.appendChild(cp);if(!c.job){const ed=el('button',null,'Изменить');ed.onclick=()=>fdEdit(w,m);ac.appendChild(ed)}w.appendChild(ac);w._m=m}
      if(i===lastU)w.id='fdLastU';col.appendChild(w);return}
    const a=el('div','fdm a'+(i===lastA?' last':''));col.appendChild(a);
    if(m.status==='running'){a.classList.add('live');const rp=el('div','rp');const lt=(c.job||{}).text||'';rp.innerHTML=fdMdC(lt);rp._t=lt;rp.hidden=!lt;a.appendChild(rp);
      const r=el('div','run');r.appendChild(el('i','live-dot'));r.appendChild(el('span',null,c.job?c.job.phase:'Отправляю…'));const tm=el('b',null,'');r.appendChild(tm);
      if(c.job){const t0=Date.now()-c.job.elapsed*1000;const tick=()=>{if(!tm.isConnected)return;tm.textContent=fdmm((Date.now()-t0)/1000);setTimeout(tick,500)};tick()}a.appendChild(r);return}
    if(m.status!=='done'){a.appendChild(el('div','err',m.status==='cancelled'?'Ответ остановлен.':'Не получилось: '+(m.error||'ошибка')));
      if(i===lastA&&!c.job){const b=el('button','ghost sm','↻ Повторить');b.onclick=fdRegen;a.appendChild(b)}return}
    const rp=el('div','rp');rp.innerHTML=fdMd(m.text);a.appendChild(rp);
    const d=m.data||{};if((d.recs||[]).length){const g=el('div','fdrecs');d.recs.forEach(r=>g.appendChild(fdRec(r)));a.appendChild(g)}
    if(i===lastA&&(d.followups||[]).length&&!c.job){const f=el('div','fdfu');d.followups.forEach(t=>{const b=el('button','chip',t);b.type='button';b.onclick=()=>fdAsk(t);f.appendChild(b)});a.appendChild(f)}
    const ac=el('div','acts');const cp=el('button',null,'Копировать');cp.onclick=()=>fdCopy(m.text+((d.recs||[]).length?'\n\n'+d.recs.map(r=>'• '+(r.author?r.author+' — ':'')+'«'+r.title+'»'+(r.why?': '+r.why:'')).join('\n'):''));ac.appendChild(cp);
    if(i===lastA&&!c.job){const rg=el('button',null,'↻ Другой ответ');rg.onclick=fdRegen;ac.appendChild(rg)}
    const foot=[];const mm=d.memory||{};if(mm.added)foot.push('память +'+mm.added);if(mm.removed)foot.push('память −'+mm.removed);const mt=m.meta||{};if(mt.seconds)foot.push(fdmm(mt.seconds));
    const ftx=el('span','fdfoot',foot.join(' · '));if((d.notes||[]).length){ftx.title=d.notes.join('\n');ftx.textContent+=(foot.length?' · ':'')+'проверка ответа: '+d.notes.length}ac.appendChild(ftx);a.appendChild(ac)});
  box.scrollTop=atEnd?box.scrollHeight:keep;fdJump()}
// нескачанная книга на любой карточке системы: «Ссылка» на источник, «Скачать» (полный конвейер: загрузка → склейка →
// проверка полноты), «✈» — скачать и сразу отправить в Telegram. Обёртка display:contents — встаёт в любой ряд кнопок.
function ndBtns(it,small){const w=el('span','ndb');const sm=small?' sm':'';
  const stop=b=>{b.onmousedown=e=>e.stopPropagation();return b};
  const act=(action,ok)=>async(b)=>{if(b)b.disabled=true;try{const j=await post('/api/find/act',{action,item_id:it.id,author:it.author,title:it.title});toast(j.message||ok,j.state==='failed'?'err':undefined);
      if(b)b.textContent=j.state==='failed'?'не вышло':action==='tg'?'✈ после загрузки':'↓ качается';if(typeof fdPoll==='function')fdPoll(true)}catch(er){toast(er.message,'err');if(b)b.disabled=false}};
  const t=stop(el('button','ghost'+sm,'✈ в Telegram'));t.title='Скачать, проверить полноту и отправить в Telegram — одной кнопкой';t.onclick=e=>{e.stopPropagation();act('tg','Скачаю и отправлю')(t)};
  w.appendChild(t);w.appendChild(moreBtn([{label:'↓ Скачать в библиотеку',title:'Проверка частей, склейка, проверка полноты',onClick:()=>act('get','Скачиваю')(null)},
    {label:'Ссылка на источник',title:'Открыть источник и скопировать ссылку (записи «только для спонсоров» пропускаются)',onClick:async()=>{try{const j=await api('/api/find/link?id='+encodeURIComponent(it.id));if(!j.url){toast('Открытой записи не нашлось — «Скачать» поищет в сети','warn');return}
      window.open(j.url,'_blank','noopener');try{await navigator.clipboard.writeText(j.url)}catch(er){}toast('Ссылка скопирована · '+(j.source||''))}catch(er){toast(er.message,'err')}}},'-',
    {label:'⚑ Что-то не так с записью',onClick:()=>reportDlg({item_id:it.id,author:it.author,title:it.title})}],small));return w}

// «Уже читал»: оценка 1–10 одним нажатием (отзыв «прослушано» с оценкой), полный отзыв или просто отметка
let RDCTX=null;
function readDlg(r,it,send){RDCTX={r,it,send};$('#rdT').textContent='«'+r.title+'» — уже читали';const S=$('#rdS');S.innerHTML='';
  for(let n=1;n<=10;n++){const b=el('button',null,String(n));b.type='button';b.setAttribute('aria-label','Оценка '+n);b.onclick=()=>rdSave(n);S.appendChild(b)}
  openDialog($('#rdDlg'));setTimeout(()=>S.children[6].focus(),20)}
async function rdReview(extra){const {r,it}=RDCTX;const body=it?{item_id:it.id,status:'listened',...extra}:{item_id:'custom:new',author:r.author,title:r.title,status:'listened',...extra};
  const j=await post('/api/review',body);if(j.out&&typeof applyOut==='function')applyOut(j.out);if(typeof refreshMeta==='function')refreshMeta();return j}
async function rdSave(n){const c=RDCTX;closeDialog($('#rdDlg'));try{await c.send('read');await rdReview({overall:n});kick(.3);toast('Оценка '+n+'/10 сохранена · учту в подборе')}catch(e){toast(e.message,'err')}}
$('#rdNo').onclick=()=>closeDialog($('#rdDlg'));
$('#rdMark').onclick=async()=>{const c=RDCTX;closeDialog($('#rdDlg'));try{await c.send('read');toast('Отмечено как прочитанное')}catch(e){toast(e.message,'err')}};
$('#rdFull').onclick=async()=>{const c=RDCTX;closeDialog($('#rdDlg'));try{await c.send('read');const j=await rdReview({});const id=c.it?c.it.id:(j.item_id||(j.review&&j.review.item_id));if(id)openItem(id);else show('reviews')}catch(e){toast(e.message,'err')}};
$('#rdDlg').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeDialog($('#rdDlg'))}else if(/^[0-9]$/.test(e.key)){e.preventDefault();rdSave(e.key==='0'?10:+e.key)}});

// жалоба на источник: ctx = {url?, src_key?, item_id?, author, title, other?} — запись сразу перестаёт предлагаться
const RP_R=[['members','Только для спонсоров'],['partial','Неполная — часть книги'],['wrong','Не та книга'],['quality','ИИ-голос / плохое качество'],['broken','Не скачивается'],['other','Другое']];
let RPCTX=null,RPV='';
function reportDlg(ctx){RPCTX=ctx;RPV='';const m=$('#rpDlg');$('#rpB').textContent=(ctx.author?ctx.author+' — ':'')+'«'+(ctx.title||'запись')+'». Отметка сразу убирает запись из поиска и ссылок.';
  const R=$('#rpR');R.innerHTML='';for(const [v,t] of RP_R){const b=el('button','chip',t);b.type='button';b.setAttribute('role','radio');b.onclick=()=>{RPV=v;R.querySelectorAll('button').forEach(x=>{x.classList.toggle('on',x===b);x.setAttribute('aria-checked',String(x===b))});$('#rpYes').disabled=false};R.appendChild(b)}
  $('#rpN').value='';$('#rpO').checked=ctx.other!==false;$('#rpYes').disabled=true;openDialog(m);setTimeout(()=>R.querySelector('button').focus(),20)}
function reportBtn(ctx,label){const b=el('button','fdrep',label||'⚑ Пожаловаться');b.title='Пожаловаться на запись: только для спонсоров, неполная, не та книга, плохое качество…';b.setAttribute('aria-label',b.title);b.onmousedown=e=>e.stopPropagation();b.onclick=e=>{e.stopPropagation();reportDlg(typeof ctx==='function'?ctx():ctx)};return b}
$('#rpNo').onclick=()=>closeDialog($('#rpDlg'));
$('#rpDlg').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeDialog($('#rpDlg'))}});
$('#rpYes').onclick=async()=>{if(!RPV||!RPCTX)return;$('#rpYes').disabled=true;try{const j=await post('/api/find/report',{...RPCTX,reason:RPV,note:$('#rpN').value,find_other:$('#rpO').checked});closeDialog($('#rpDlg'));toast(j.message);
    if(j.search_id){FDCUR=j.search_id;show('find');fdPoll(true)}else if(VIEW==='chat')fdChatLoad();else if(VIEW==='find')fdPoll(true)}catch(e){toast(e.message,'err');$('#rpYes').disabled=false}};

// действие совета: книга на диске — сразу; нет — скачать (поиск полной записи), потом сделать
const FD_AST={search:'ищу запись…',download:'скачиваю…',choose:'выберите запись →',failed:'не вышло · ещё раз'};
function fdActBtn(r,action,label){const a=(r.act||{})[action],b=el('button','ghost sm'+(a&&a.state==='done'?' on':''));const it=r.item;
  b.textContent=a?(a.state==='done'?(action==='tg'?'✓ в Telegram':'✓ в очереди'):(action==='tg'?'✈ ':'')+FD_AST[a.state]):label;
  if(a&&a.message)b.title=a.message;
  if(a&&(a.state==='search'||a.state==='download')){b.disabled=true;return b}
  if(a&&a.state==='choose'){b.onclick=()=>{show('find');FDCUR=a.search_id;fdPoll(true)};return b}
  if(a&&a.state==='done'&&action==='queue')b.disabled=true;
  b.onclick=async()=>{b.disabled=true;try{const j=await post('/api/find/act',{action,item_id:it?it.id:'',src_key:r.src_key||'',author:r.author,title:r.title});
      toast(j.message||(j.state==='done'?'Готово':'Принято'),j.state==='failed'?'err':undefined);if(j.state==='done'&&action==='queue')kick(.35);if(action==='tg'&&typeof pollTgNow==='function')pollTgNow(true);refreshMeta();fdChatLoad()}
    catch(e){toast(e.message,'err');b.disabled=false}};return b}
/* ---------- «Для вас»: модель вкуса по всему каталогу (GET /api/find/foryou) — работает и при 0 отзывов (анкета, профиль ИИ),
   реакции 👍/👎/«читал» уточняют её и перестраивают ленту. Первый запрос греет векторный демон — до 15 с, показываем ход ---------- */
let FDFOR=null,FDFORT=0,FDFORP=null,FDFORQ=null,FDFORRT=null;
const fdWide=matchMedia('(min-width:2000px)');
function fdForBox(){let b=$('#fdForBox');if(b)return b;b=el('div','fdforbox');b.id='fdForBox';
  b.innerHTML='<div class="fdh"><h3>Для вас</h3><span class="sub" id="fdForSub"></span><span class="spacer"></span><button class="ghost sm" id="fdForRe" title="Пересобрать подбор по текущему вкусу"><svg><use href="/kit/icons/sprite.svg#i-refresh"/></svg>Обновить</button></div><div id="fdForList"></div>';
  b.querySelector('#fdForRe').onclick=()=>fdForLoad(true);return b}
function fdForPlace(){const b=fdForBox(),aside=$('#fdFor');if(!aside)return;const blank=$('#fdMain').classList.contains('blank');
  if(fdWide.matches){if(b.parentNode!==aside)aside.appendChild(b)}
  else{const e=$('#fdCol .fdempty');if(blank&&e){if(b.parentNode!==e)e.appendChild(b)}else if(b.parentNode)b.remove()}}
fdWide.addEventListener('change',()=>{fdForPlace();fdForLoad()});
async function fdForLoad(force){if(FDFORP!==PROFILE){FDFOR=null;FDFORT=0;FDFORP=PROFILE}const list=$('#fdForList');if(!list||!list.isConnected)return;
  // последний подбор помнится между открытиями (localStorage): лента видна сразу, свежая версия подъезжает в фоне
  if(!FDFOR){try{const c=JSON.parse(localStorage.getItem('abook.foryou.'+PROFILE)||'null');if(c&&c.items){FDFOR=c;FDFORT=c._t||0}}catch(e){}}
  if(FDFOR&&!force&&Date.now()-FDFORT<15*60e3){fdForPaint();return}
  if(FDFOR&&!list.childElementCount)fdForPaint();
  if(FDFORQ)return;const my=PROFILE,t0=Date.now();
  if(!FDFOR){list.innerHTML='<div class="fdforwait"><span>Собираю подбор по вашему вкусу: анкета, отзывы, память и реакции — по всему каталогу. Первый раз — до 15 с.</span><div class="meter indet"><div class="meter-fill"></div><div class="meter-glow"></div></div><b>00:00</b></div>'}
  else $('#fdForSub').textContent='обновляю…';
  const tm=setInterval(()=>{const b=list.querySelector('.fdforwait b');if(b)b.textContent=fdmm((Date.now()-t0)/1000)},500);
  FDFORQ=api('/api/find/foryou?k=12').then(j=>{if(my!==PROFILE)return;FDFOR=j;FDFORT=Date.now();j._t=FDFORT;try{localStorage.setItem('abook.foryou.'+PROFILE,JSON.stringify(j))}catch(e){}fdForPaint()})
    .catch(e=>{if(my!==PROFILE)return;list.innerHTML='';list.appendChild(el('p','sub','Подбор не собрался: '+e.message));const b=el('button','ghost sm','Попробовать ещё раз');b.onclick=()=>fdForLoad(true);list.appendChild(b)})
    .finally(()=>{FDFORQ=null;clearInterval(tm)})}
function fdForPaint(){const list=$('#fdForList'),j=FDFOR;if(!list||!j)return;const items=(j.items||[]);list.innerHTML='';
  $('#fdForSub').textContent=items.length?fdPl(items.length,'книга','книги','книг')+' из '+(j.pool?fdPl(j.pool,'кандидата','кандидатов','кандидатов'):'каталога')+(j.ms?' · '+(j.ms>=1000?Math.round(j.ms/100)/10+' с':Math.round(j.ms)+' мс'):''):'';
  if(!items.length){list.appendChild(el('p','sub','Пока нечего предложить: заполните анкету или оцените пару книг — подбор появится сразу.'));const b=el('button','ghost sm','Открыть анкету');b.onclick=()=>show('anketa');list.appendChild(b);return}
  const g=el('div','fdrecs');items.forEach(x=>g.appendChild(fdForRow(x)));list.appendChild(g)}
function fdForRow(x){const lib=x.kind==='item'||x.in_library;const it=lib?{id:x.id,has_file:!!x.has_file,hours:x.hours,narrator:x.reader,author:x.author,title:x.title,in_library:1}:null;
  const r={author:x.author||'',title:x.title||'',src_key:x.src_key||'',url:x.url||'',item:it,act:{},fb:''};
  const c0=el('div','fdr');const c=el('div','bd');c0.appendChild(c);const ac=el('div','ac');c0.appendChild(ac);
  const h=el('div','h');h.appendChild(el('span','badge'+(lib?'':' no'),lib?(it.has_file?'✓ на диске':'в библиотеке'):(x.platform||'каталог')));
  if(x.hours)h.appendChild(el('span','badge no',fdH(x.hours*3600)));if(x.lang&&x.lang!=='ru')h.appendChild(el('span','badge no',x.lang));c.appendChild(h);
  const t=el('div','ti'+(lib?' link':''),(r.author?r.author+' — ':'')+'«'+r.title+'»');if(lib)t.onclick=()=>openItem(it.id);c.appendChild(t);
  if(x.about)c.appendChild(el('div','wy',x.about.length>190?x.about.slice(0,188).replace(/\s+\S*$/,'')+'…':x.about));
  const why=(x.facet_label||'').split(' / ').filter(Boolean)[0]||'';
  c.appendChild(el('div','mt',[why?'похоже на: '+why:'',x.reader||'',x.quality&&x.quality.rating?'рейтинг '+Math.round(x.quality.rating*10)/10:''].filter(Boolean).join(' · ')));
  const row=el('div','row');const rep={label:'⚑ Что-то не так с записью',onClick:()=>reportDlg({src_key:r.src_key,url:r.url,item_id:it?it.id:'',author:r.author,title:r.title})};
  if(it&&it.has_file){row.appendChild(tgBtn(it,true));row.appendChild(moreBtn(()=>[btnItem(qBtn(it,true)),{label:'Открыть карточку',onClick:()=>openItem(it.id)}],true))}
  else{row.appendChild(fdActBtn(r,'tg','✈ в Telegram'));row.appendChild(moreBtn(()=>[btnItem(fdActBtn(r,'queue','+ в очередь')),r.url?{label:'Ссылка на запись',title:'Открыть в источнике и скопировать ссылку',onClick:()=>{window.open(r.url,'_blank','noopener');fdCopy(r.url)}}:null,'-',rep],true))}
  ac.appendChild(row);ac.appendChild(fdFbBar(r,c0,it,()=>{clearTimeout(FDFORRT);FDFORRT=setTimeout(()=>fdForLoad(true),600)}));return c0}
// реакция на совет: сразу уточняет вкус (rec_feedback), «не моё» — ещё и в «не интересно», «читал» — в «уже знакомо»; повторное нажатие снимает
function fdFbBar(r,c0,it,onChange){const fb=el('div','fdfb');
  const paintFb=()=>fb.querySelectorAll('button[data-v]').forEach(x=>{const on=r.fb===x.dataset.v;x.classList.toggle('on',on);x.setAttribute('aria-pressed',String(on));if(x.dataset.v==='read')x.textContent=on?'✓ Читал':'Уже читал'});
  const send=async v=>{await post('/api/find/feedback',{verdict:v||'none',author:r.author,title:r.title,item_id:it?it.id:'',src_key:r.src_key||''});r.fb=v||'';paintFb();c0.classList.toggle('gone',!!v&&v!=='like');if(onChange)onChange(v)};
  for(const [v,t,ti] of [['like','👍','Нравится — больше такого'],['dislike','👎','Не моё — меньше такого'],['read','Уже читал','Читали: оценить, написать отзыв или просто отметить']]){
    const b=el('button','fdfbb',t);b.dataset.v=v;b.title=ti;b.setAttribute('aria-label',ti);
    b.onclick=async()=>{try{
        if(r.fb===v){await send(null);toast('Отметка снята');return}          // повторное нажатие — отменить
        if(v==='read'){readDlg(r,it,send);return}
        await send(v);if(v==='dislike')post('/api/find/memory',{op:'dismiss',author:r.author,title:r.title,item_id:it?it.id:''}).catch(()=>{});
        toast(v==='like'?'Учту: больше такого':'Учту: «'+r.title+'» не предлагать')}catch(e){toast(e.message,'err')}};fb.appendChild(b)}
  paintFb();
  return fb}
function fdRec(r){const c0=el('div','fdr');const c=el('div','bd');c0.appendChild(c);const ac=el('div','ac');c0.appendChild(ac);const it=r.item;const h=el('div','h');h.appendChild(el('span','badge'+(r.kind==='bridge'?' q':''),r.kind==='bridge'?'мост':'рядом'));if(r.medium)h.appendChild(el('span','badge no',r.medium));c.appendChild(h);
  const t=el('div','ti'+(it?' link':''),(r.author?r.author+' — ':'')+'«'+r.title+'»');if(it)t.onclick=()=>openItem(it.id);c.appendChild(t);
  if(r.chain&&r.chain.feature){const ch=el('div','chain');ch.innerHTML=esc(r.chain.from||'ваш запрос')+' <i>→</i> '+esc(r.chain.feature)+' <i>→</i> '+esc(r.chain.to||r.title);c.appendChild(ch)}
  if(r.why)c.appendChild(el('div','wy',r.why));
  c.appendChild(el('div','mt',it?[it.hours?fmtH(it.hours,it.hours_exact):'',it.narrator,it.has_file?'✓ на диске':'○ в каталоге, не скачана',it.rstatus?'отзыв: '+(STL[it.rstatus]||it.rstatus):''].filter(Boolean).join(' · '):'нет в библиотеке — найду и скачаю'+(r.confidence!=null?' · уверенность '+Math.round(r.confidence*100)+'%':'')));
  const row=el('div','row');const link=async()=>{if(r.url){window.open(r.url,'_blank','noopener');fdCopy(r.url);return}
      try{const j=await api('/api/find/catalog?limit=5&q='+encodeURIComponent((r.author?r.author+' ':'')+r.title));const x=(j.items||[]).find(x=>!x.drop&&x.availability!=='members');
        if(x){window.open(x.link||x.url,'_blank','noopener');try{await navigator.clipboard.writeText(x.link||x.url);toast('Ссылка скопирована: '+x.platform+(x.duration?' · '+fdH(x.duration):''))}catch(e){}}
        else toast('В каталоге нет — нажмите «+ в очередь», найду в сети','warn')}catch(e){toast(e.message,'err')}};
  const rep={label:'⚑ Что-то не так с записью',onClick:()=>reportDlg({src_key:r.src_key||'',url:r.url||'',item_id:it?it.id:'',author:r.author,title:r.title})};
  if(it&&it.has_file){row.appendChild(tgBtn(it,true));row.appendChild(moreBtn(()=>[it.rstatus&&it.rstatus!=='want'?{label:'Отзыв: '+STL[it.rstatus],onClick:()=>openItem(it.id)}:btnItem(qBtn(it,true)),{label:'Открыть карточку',onClick:()=>openItem(it.id)},r.src_key?rep:null],true))}
  else{row.appendChild(fdActBtn(r,'tg','✈ в Telegram'));row.appendChild(moreBtn(()=>[btnItem(fdActBtn(r,'queue','+ в очередь')),{label:'Ссылка на запись',title:'Лучшая открытая запись из каталога источников',onClick:link},'-',rep],true))}
  const fb=fdFbBar(r,c0,it);
  ac.appendChild(row);ac.appendChild(fb);
  if(r.dl&&FD_ACT.includes(r.dl.state))c.appendChild(el('div','st',FD_QST[r.dl.state]+(r.dl.state==='downloading'&&r.dl.n>1?' · часть '+r.dl.k+'/'+r.dl.n:'')+(r.dl.pct!=null?' · '+Math.round(r.dl.pct)+'%':'')));
  return c0}

/* ---------- память консультанта ---------- */
const FD_MK={taste:'вкус',dislike:'не нравится',context:'контекст',not_interested:'не интересно'};
function fdPaintMem(mem){const box=$('#fdMem');box.innerHTML='';const h=el('div','fdh');h.appendChild(el('h3',null,'Память консультанта'));h.appendChild(el('span','sub',mem.length?fdPl(mem.length,'факт','факта','фактов'):'пока пусто'));box.appendChild(h);
  box.appendChild(el('div','sub','Короткие факты о вашем вкусе. Консультант дополняет их после каждого ответа; щёлкните, чтобы поправить, × — удалить. Поправленное вами он не удаляет.'));
  const L=el('div','fdmem');box.appendChild(L);const sorted=[...mem.filter(m=>m.kind!=='not_interested'),...mem.filter(m=>m.kind==='not_interested')];
  for(const m of sorted){const r=el('div','fdmi');r.appendChild(el('span','k',FD_MK[m.kind]||m.kind));const f=el('span','f',m.fact);f.title=m.source==='user'?'поправлено вами':'записал консультант';r.appendChild(f);
    f.onclick=()=>{const i=el('input','in');i.value=m.fact;i.maxLength=300;r.replaceChild(i,f);i.focus();i.select();
      const done=async save=>{if(!i.isConnected)return;if(!save||i.value.trim()===m.fact){r.replaceChild(f,i);return}try{const j=await post('/api/find/memory',{op:'edit',id:m.id,fact:i.value});fdPaintMem(j.memory);toast('Факт исправлен')}catch(e){toast(e.message,'err')}};
      i.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();done(true)}else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();done(false)}};i.onblur=()=>done(true)};
    const x=el('button','x','×');x.title='удалить факт';x.setAttribute('aria-label','удалить факт');x.onclick=async()=>{try{const j=await post('/api/find/memory',{op:'delete',id:m.id});fdPaintMem(j.memory)}catch(e){toast(e.message,'err')}};r.appendChild(x);L.appendChild(r)}
  const add=el('input','in');add.placeholder='Добавить факт: «не люблю длинные описания природы», Enter';add.maxLength=300;add.onkeydown=async e=>{if(e.key==='Enter'&&add.value.trim()){e.preventDefault();try{const j=await post('/api/find/memory',{op:'add',fact:add.value});fdPaintMem(j.memory);$('#fdMem input.in:last-of-type')?.focus()}catch(er){toast(er.message,'err')}}};box.appendChild(add)}

/* ---------- «Связи» под карточкой книги ---------- */
// карточку рисует основной код; блок «Связи» живёт рядом и следит за ней (заголовок сменился — другая книга; карточка скрыта — прячемся)
let FDLID=null,FDLSEQ=0;
function fdLinksSync(){const card=$('#card');let box=$('#fdLinks');
  if(card.hidden||!CUR||!CUR.item||CUR.item.id==='custom:new'){if(box)box.hidden=true;FDLID=null;return}
  if(!box){box=el('section','fdlinks');box.id='fdLinks';box.setAttribute('aria-label','Связи книги');card.after(box)}
  box.style.setProperty('--card-w',getComputedStyle(card).getPropertyValue('--card-w')||card.offsetWidth+'px');
  const id=CUR.item.id;if(FDLID===id&&!box.hidden)return;FDLID=id;box.hidden=false;box.innerHTML='<div class="hd"><h3>Связи</h3><span class="sub">ищу соседей по глубинным признакам…</span></div>';
  const my=++FDLSEQ;api('/api/find/links?id='+encodeURIComponent(id)).then(j=>{if(my!==FDLSEQ)return;fdLinksPaint(box,j)}).catch(()=>{if(my===FDLSEQ)box.hidden=true})}
function fdLinksPaint(box,j){box.innerHTML='';const hd=el('div','hd');hd.appendChild(el('h3',null,'Связи'));box.appendChild(hd);
  if(!j.ready){hd.appendChild(el('span','sub',j.map&&j.map.have?'для этой книги признаки ещё не посчитаны':'карта связей ещё не построена'));const b=el('button','ghost sm','Во вкладку «Найти» → карта связей');b.onclick=()=>show('find');box.appendChild(b);return}
  hd.appendChild(el('span','sub',[j.meta.genre,j.meta.medium,j.meta.era].filter(Boolean).join(' · ')));
  if((j.features||[]).length){const f=el('div','feats');f.innerHTML=j.features.map(x=>'<b>'+esc(x.facet)+':</b> '+esc(x.tags.join(', '))).join(' · ');box.appendChild(f)}
  if(!(j.groups||[]).length){box.appendChild(el('div','sub','Соседей с общими признаками пока нет.'));return}
  const g=el('div','fdgroups');for(const x of j.groups){const d=el('div','fdg');const gl=el('div','gl');gl.appendChild(el('b',null,x.label));gl.appendChild(el('small',null,x.facet));d.appendChild(gl);
    for(const b of x.books){const bt=el('button',null,(b.author?b.author+' — ':'')+'«'+b.title+'»');if(b.far)bt.appendChild(el('small',null,'другой жанр'));if(b.overall!=null)bt.appendChild(el('small',null,b.overall+'/10'));bt.title=b.also.length?'ещё общее: '+b.also.join(', '):'';bt.onclick=()=>openItem(b.id);d.appendChild(bt)}g.appendChild(d)}box.appendChild(g)}
new MutationObserver(()=>fdLinksSync()).observe($('#cT'),{childList:true,characterData:true,subtree:true});
new MutationObserver(()=>fdLinksSync()).observe($('#card'),{attributes:true,attributeFilter:['hidden']});
setTimeout(()=>fdPoll(),1200);   // загрузки и карта связей могли идти до перезагрузки страницы — показать их в рельсе
'''
