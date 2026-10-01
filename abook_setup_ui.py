"""Экран «Настройка» (мастер первого запуска) для SPA `abook review`. Вставляется в REVIEW_HTML после модулей AI и
FIND (inject): стиль — перед </style>, пункт меню — после «Экспорт», экран — перед «МОИ ОТЗЫВЫ», скрипт — в конец
модуля страницы. Пять шагов сверху вниз, каждый — карточка с состоянием и одним действием; всё можно «позже».
Открывается сам при первом запуске (ИИ ещё не проверен и мастер не закрыт)."""

CSS = r'''
/* ---------- «Настройка»: пять шагов первого запуска ---------- */
.su{display:flex;flex-direction:column;gap:12px;width:min(880px,100%);margin:0 auto}
.sustep{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:6px 16px;align-items:start;background:var(--plate);border:1px solid var(--line-1);border-radius:var(--r-xl);padding:18px 20px}
.sustep.done{border-color:var(--line-2)}
.sustep .n{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;font:600 15px/1 var(--font-display);color:var(--ink-2);box-shadow:inset 0 0 0 1px var(--line-2)}
.sustep.done .n{color:var(--ink);background:var(--s3)}
.sustep h3{margin:4px 0 2px;font:600 17px/1.3 var(--font-text);color:var(--ink)}
.sustep .tx{grid-column:2;font-size:14px;line-height:1.6;color:var(--ink-2)}
.sustep .tx code{font:500 12.5px/1 var(--font-mono);background:var(--s2);padding:2px 6px;border-radius:var(--r-xs)}
.sustep .st{grid-column:3;grid-row:1;font:500 12px/36px var(--font-mono);color:var(--ink-3);white-space:nowrap}
.sustep.done .st{color:var(--ink)}
.sustep .act{grid-column:2/-1;display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:6px}
.sustep .act .in{width:auto;min-width:340px}
.suthemes{display:flex;align-items:center;justify-content:center;gap:12px;margin:0 0 16px}
.sufoot{display:flex;justify-content:center;gap:10px;margin:10px 0 0}
'''

NAV = r'''<button data-v="setup" data-tip="Настройка"><svg><use href="/kit/icons/sprite.svg#i-sliders"/></svg><span class="l">Настройка</span><small id="c-setup"></small></button>'''

VIEW = r'''<!-- НАСТРОЙКА -->
<section class="view" id="v-setup" hidden>
  <header class="vh"><p class="kicker">настройка</p><h2 class="vt">Шесть шагов — и аудиотека готова</h2>
    <p class="sub">Любой шаг можно пройти позже: приложение работает и без Telegram, а каталог дособирается сам.</p></header>
  <div class="suthemes"><span class="sub">Оформление</span><div class="seg" id="suTheme" role="radiogroup" aria-label="Оформление"></div></div>
  <div class="su" id="suBox"></div>
  <div class="sufoot"><button class="ghost" id="suLater">Закрыть, настрою потом</button></div>
</section>

'''

JS = r'''
/* ================= «Настройка»: мастер первого запуска ================= */
let SUST=null,SUT=null;
const SU_TXT={
  llm:['ИИ-помощник','Чат, подбор и поиск работают через Claude Code или Antigravity (Gemini) — выберите, что установлено на этом компьютере. Сменить можно в любой момент в шапке чата.'],
  library:['Папка библиотеки','Куда класть скачанные аудиокниги. На Windows лучше диск с местом (например <code>D:\\Аудиокниги</code>): временные файлы склейки тоже пойдут рядом, а не на диск C:.'],
  catalog:['Каталог книг из интернета','~50 тыс. книг с YouTube-каналов, knigavuhe, akniga и archive.org — для поиска и советов. Быстрее всего скачать готовый снимок; можно и обойти источники заново (около 2,5 часа в фоне).'],
  profile:['Ваш вкус','Анкета — по шагам или одним рассказом своими словами. По ней консультант советует книги.'],
  sync:['Другие компьютеры (необязательно)','Профили, анкеты, отзывы и память о вкусе — в вашем приватном репозитории GitHub <code>abook-data</code>: на другом компьютере советы будут такими же. Нужен <code>gh</code> с входом (<code>gh auth login</code>). Каталог и аудио не синхронизируются — у каждого компьютера свои.'],
  telegram:['Telegram (необязательно)','Отправка книг в ваш канал одной кнопкой. Настраивается в терминале: <code>abook-tg setup</code> — понадобятся api_id и api_hash с my.telegram.org и название канала.']};
async function loadSetup(){try{SUST=await api('/api/setup')}catch(e){toast(e.message,'err');return}paintSetup()}
function paintSetup(){paintTheme();const s=SUST;if(!s)return;const box=$('#suBox');box.innerHTML='';const left=s.steps.filter(x=>!x.done).length;$('#c-setup').textContent=left?String(left):'';
  s.steps.forEach((st,i)=>{const [t,tx]=SU_TXT[st.k];const c=el('div','sustep'+(st.done?' done':''));c.appendChild(el('div','n',st.done?'✓':String(i+1)));
    const h=el('div');h.appendChild(el('h3',null,t));c.appendChild(h);const stt=el('div','st',st.done?'готово':'не сделано');c.appendChild(stt);
    const p=el('div','tx');p.innerHTML=tx;c.appendChild(p);const a=el('div','act');c.appendChild(a);const I=st.info||{};
    if(st.k==='llm'){const sg=el('div','seg');for(const [k,lab] of [['claude','Claude'],['agy','Antigravity']]){const b=el('button',I.provider===k?'on':'',lab);b.type='button';b.disabled=!(I.available||{})[k];b.title=(I.available||{})[k]?'':'CLI не найден на этом компьютере';
        b.onclick=async()=>{try{await post('/api/llm',{provider:k});FDLLM=null;loadSetup()}catch(e){toast(e.message,'err')}};sg.appendChild(b)}a.appendChild(sg);inkSeg(sg,true);
      const tb=el('button','btn'+(st.done?'':' primary'),'Проверить связь');tb.onclick=async()=>{tb.disabled=true;tb.textContent='Проверяю…';try{const j=await post('/api/setup',{op:'test_llm'});toast(j.ok?'ИИ отвечает · '+j.seconds+' с':'Не отвечает: '+(j.error||''),j.ok?undefined:'err');loadSetup()}catch(e){toast(e.message,'err')}finally{tb.disabled=false;tb.textContent='Проверить связь'}};a.appendChild(tb);
      if(!(I.available||{}).claude&&!(I.available||{}).agy)a.appendChild(el('span','sub','Установите Claude Code (npm i -g @anthropic-ai/claude-code, затем claude и вход) или Antigravity (agy).'))}
    if(st.k==='library'){const i=el('input','in');i.value=I.windows||I.path||'';i.setAttribute('aria-label','Папка библиотеки');a.appendChild(i);const b=el('button','btn'+(st.done?'':' primary'),'Сохранить');
      b.onclick=async()=>{try{const j=await post('/api/setup',{op:'library',path:i.value});toast('Папка: '+j.path+(j.restart?' · перезапустите приложение':''));loadSetup()}catch(e){toast(e.message,'err')}};a.appendChild(b)}
    if(st.k==='catalog'){a.appendChild(el('span','sub',(I.records||0).toLocaleString('ru-RU')+' записей · '+(I.works||0).toLocaleString('ru-RU')+' книг'));
      if(I.job&&I.job.running){a.appendChild(el('span','sub','· '+I.job.phase+'…'));clearTimeout(SUT);SUT=setTimeout(loadSetup,3000)}
      else{if(I.job&&I.job.error)a.appendChild(el('span','sub','· ошибка: '+I.job.error));
        const d=el('button','btn'+(st.done?'':' primary'),'Скачать готовый каталог');d.disabled=!I.snapshot;d.title=I.snapshot?'':'Нет снимка: положите catalog.db в ~/abook или установите gh';d.onclick=async()=>{try{await post('/api/setup',{op:'catalog_download'});loadSetup()}catch(e){toast(e.message,'err')}};a.appendChild(d);
        const cr=el('button','ghost','Обойти источники заново');cr.onclick=async()=>{try{await post('/api/setup',{op:'catalog_crawl'});toast('Обход начат — прогресс во «Найти»')}catch(e){toast(e.message,'err')}};a.appendChild(cr)}}
    if(st.k==='profile'){const b=el('button','btn'+(st.done?'':' primary'),st.done?'Открыть анкету':'Заполнить анкету');b.onclick=()=>show('anketa');a.appendChild(b)}
    if(st.k==='sync'){if(!I.enabled)a.appendChild(el('span','sub','нужны git и gh (GitHub CLI)'));
      else if(I.configured){a.appendChild(el('span','sub',(I.repo||'')+(I.last?' · последняя '+I.last:'')+(I.error?' · ошибка: '+I.error:'')));const b=el('button','ghost','Синхронизировать сейчас');b.onclick=async()=>{b.disabled=true;try{const j=await post('/api/sync',{op:'now'});toast(j.ok?'Синхронизировано':(j.error||'ошибка'),j.ok?undefined:'err');loadSetup()}finally{b.disabled=false}};a.appendChild(b)}
      else{const b=el('button','btn','Включить синхронизацию');b.onclick=async()=>{b.disabled=true;b.textContent='Создаю приватный репозиторий…';try{const j=await post('/api/sync',{op:'enable'});toast(j.ok?'Синхронизация включена: '+(j.repo||''):(j.error||'ошибка'),j.ok?undefined:'err');loadSetup()}finally{b.disabled=false}};a.appendChild(b);
        if(!st.done){const l=el('button','ghost','Позже');l.onclick=async()=>{await post('/api/setup',{op:'skip_sync'});loadSetup()};a.appendChild(l)}}}
    if(st.k==='telegram'){if(I.configured)a.appendChild(el('span','sub','подключено'));else if(!st.done){const b=el('button','ghost','Позже');b.onclick=async()=>{await post('/api/setup',{op:'skip_tg'});loadSetup()};a.appendChild(b)}}
    box.appendChild(c)})}
const THEMES=[['gold','Золотистая','тёплая бумага, золотой свет'],['grey','Серая','нейтральные чернила, белый свет']];
const themeCur=()=>{try{return localStorage.getItem('abook.theme')==='grey'?'grey':'gold'}catch(e){return 'gold'}};
function applyTheme(k){try{localStorage.setItem('abook.theme',k)}catch(e){}const h=document.documentElement;
  if(k==='grey'){h.removeAttribute('data-palette');h.dataset.accent='white'}else{h.dataset.palette='paper';h.dataset.accent='gold'}
  if(SC&&SC.api&&SC.api.setAccent)SC.api.setAccent(getComputedStyle(h).getPropertyValue('--el-a').trim());paintTheme()}
function paintTheme(){const cur=themeCur();const sg=$('#suTheme');if(sg){sg.innerHTML='';
    for(const [k,t,d] of THEMES){const b=el('button',k===cur?'on':'',t);b.type='button';b.title=d;b.setAttribute('role','radio');b.setAttribute('aria-checked',String(k===cur));b.onclick=()=>applyTheme(k);sg.appendChild(b)}inkSeg(sg,true)}
  const tb=$('#themeBtn');if(tb){const nxt=THEMES.find(x=>x[0]!==cur);tb.dataset.tip='Оформление: '+THEMES.find(x=>x[0]===cur)[1]+' → '+nxt[1];tb.querySelector('use').setAttribute('href','/kit/icons/sprite.svg#'+(cur==='gold'?'i-sun':'i-moon'))}}
$('#themeBtn').onclick=()=>applyTheme(themeCur()==='gold'?'grey':'gold');paintTheme();
$('#suLater').onclick=async()=>{try{await post('/api/setup',{op:'dismiss'})}catch(e){}show('rate')};
setTimeout(async()=>{try{const s=await api('/api/setup');SUST=s;const left=s.steps.filter(x=>!x.done).length;$('#c-setup').textContent=left?String(left):'';
  if(!s.dismissed&&!s.steps[0].done&&!s.steps[3].done&&VIEW==='rate')show('setup')}catch(e){}},900);
'''


THEME_HEAD = r"""<script>/* оформление до первой отрисовки: «Золотистая» (по умолчанию: тёплая бумага, золотой свет) или «Серая»
(нейтральные чернила кита, белый свет). Выбор — в рельсе и в «Настройке», хранится в localStorage */
(function(){var t='gold';try{t=localStorage.getItem('abook.theme')||'gold'}catch(e){}var h=document.documentElement;
if(t==='grey'){h.removeAttribute('data-palette');h.dataset.accent='white'}else{h.dataset.palette='paper';h.dataset.accent='gold'}})();</script>"""


def inject(html):
    html = html.replace("<head>", "<head>" + THEME_HEAD, 1)
    html = html.replace("</style>", CSS + "</style>", 1)
    html = html.replace('<span class="l">Экспорт</span></button>', '<span class="l">Экспорт</span></button>\n    ' + NAV, 1)
    html = html.replace("<!-- МОИ ОТЗЫВЫ -->", VIEW + "<!-- МОИ ОТЗЫВЫ -->", 1)
    i = html.rfind("</script>")
    return html[:i] + JS + html[i:] if i >= 0 else html
