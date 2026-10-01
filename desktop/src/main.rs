// Аудиотека — оконная оболочка для веб-интерфейса abook (сервер в WSL).
// Окно сразу показывает встроенный сплэш, проверяет сервер, при необходимости поднимает его
// через wsl.exe (скрыто) и переходит на http://127.0.0.1:<порт>/. Сервер, поднятый оболочкой,
// останавливается при выходе; уже работавший сервер не трогается.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct Server {
    port: u16,
    distro: String,
    child: Mutex<Option<Child>>,
}

fn settings() -> (u16, String) {
    let mut port: u16 = std::env::var("ABOOK_PORT").ok().and_then(|v| v.parse().ok()).unwrap_or(8790);
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--port") {
        if let Some(p) = args.get(i + 1).and_then(|v| v.parse().ok()) {
            port = p;
        }
    }
    let distro = std::env::var("ABOOK_DISTRO").unwrap_or_else(|_| "Ubuntu".into());
    (port, distro)
}

fn wsl(distro: &str, script: &str) -> Command {
    let mut c = Command::new(r"C:\Windows\System32\wsl.exe");
    c.args(["-d", distro, "-e", "bash", "-lc", script])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    c.creation_flags(CREATE_NO_WINDOW);
    c
}

fn pidfile(port: u16) -> String {
    format!("/tmp/abook-desktop-{port}.pid")
}

/// Сервер отвечает, если принимает TCP и отдаёт HTTP-ответ на GET /.
fn alive(port: u16) -> bool {
    use std::io::{Read, Write};
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut s) = TcpStream::connect_timeout(&addr, Duration::from_millis(400)) else { return false };
    let _ = s.set_read_timeout(Some(Duration::from_secs(3)));
    if s.write_all(b"HEAD / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").is_err() {
        return false;
    }
    let mut buf = [0u8; 8];
    matches!(s.read(&mut buf), Ok(n) if n >= 5 && &buf[..5] == b"HTTP/")
}

fn show_error(w: &tauri::WebviewWindow, msg: &str) {
    let js = format!("window.abookError({})", serde_json_string(msg));
    let _ = w.eval(&js);
}

fn serde_json_string(s: &str) -> String {
    let mut o = String::from("\"");
    for ch in s.chars() {
        match ch {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

fn boot(app: tauri::AppHandle) {
    let w = app.get_webview_window("main").unwrap();
    let st = app.state::<Server>();
    let (port, distro) = (st.port, st.distro.clone());
    let url = format!("http://127.0.0.1:{port}/");

    if !alive(port) {
        let script = format!(
            "echo $$ > {pf}; exec ~/.local/bin/abook-ui --no-browser --port {port}",
            pf = pidfile(port)
        );
        match wsl(&distro, &script).spawn() {
            Ok(child) => *st.child.lock().unwrap() = Some(child),
            Err(e) => {
                show_error(&w, &format!("Не найден wsl.exe ({e}).\nНужен WSL с дистрибутивом {distro}."));
                return;
            }
        }
        let t0 = Instant::now();
        loop {
            std::thread::sleep(Duration::from_millis(250));
            if alive(port) {
                break;
            }
            let exited = st.child.lock().unwrap().as_mut().and_then(|c| c.try_wait().ok().flatten());
            if let Some(code) = exited {
                *st.child.lock().unwrap() = None;
                show_error(&w, &format!(
                    "Сервер abook не запустился (wsl.exe завершился: {code}).\nПроверьте WSL: wsl.exe -d {distro} -e bash -lc \"~/.local/bin/abook-ui --no-browser --port {port}\""
                ));
                return;
            }
            if t0.elapsed() > Duration::from_secs(60) {
                show_error(&w, &format!("Сервер abook не ответил за 60 с на порту {port}."));
                return;
            }
        }
    }
    let _ = w.navigate(url.parse().unwrap());
}

const RETRY_URL: &str = "https://abook-desktop.invalid/retry";

/// Внешние ссылки — в системный браузер (без консольного окна).
fn open_external(url: &str) {
    let mut c = Command::new(r"C:\Windows\System32\rundll32.exe");
    c.args(["url.dll,FileProtocolHandler", url]);
    #[cfg(windows)]
    c.creation_flags(CREATE_NO_WINDOW);
    let _ = c.spawn();
}

/// Поведение «приложения, а не браузера» поверх страниц abook; веб-код abook не меняется.
const SHELL_JS: &str = r#"(function(){
  var h = location.hostname;
  if (h !== '127.0.0.1' && h !== 'localhost') return;
  var TXT = 'input,textarea,select,[contenteditable],[contenteditable] *';
  var SEL = TXT + ',p,blockquote,pre,code,article,.fdmsgs,.fdchat,.mbody,.modal-text,.rpnote,.field-body';
  function ok(t, s){ return t && t.closest && t.closest(s); }
  addEventListener('contextmenu', function(e){
    if (ok(e.target, TXT) || String(getSelection()).length) return;
    e.preventDefault();
  }, true);
  addEventListener('wheel', function(e){ if (e.ctrlKey) e.preventDefault(); }, {passive:false, capture:true});
  addEventListener('keydown', function(e){
    var k = e.key;
    if ((e.ctrlKey || e.metaKey) && (k==='+'||k==='-'||k==='='||k==='0'||k==='p'||k==='P'||k==='s'||k==='S'||k==='u'||k==='U'||k==='g'||k==='G'))
      e.preventDefault();
    if (k==='F3' || k==='F7' || (e.ctrlKey && (k==='f'||k==='F') && !ok(e.target, TXT))) e.preventDefault();
  }, true);
  addEventListener('dragstart', function(e){ if (!ok(e.target, '[draggable=true]')) e.preventDefault(); }, true);
  addEventListener('click', function(e){
    var a = ok(e.target, 'a[href]');
    if (!a || e.defaultPrevented) return;
    var u = new URL(a.href, location.href);
    if (u.origin !== location.origin && /^https?:$/.test(u.protocol)) { e.preventDefault(); location.href = u.href; }
    else if (a.target === '_blank') { e.preventDefault(); location.href = u.href; }
  });
  var wo = window.open;
  window.open = function(u){
    try { var x = new URL(u, location.href);
      if (x.origin !== location.origin) { location.href = x.href; return null; } } catch(_){}
    return wo.apply(window, arguments);
  };
  var st = document.createElement('style');
  st.textContent = 'html{user-select:none;-webkit-user-select:none}' + SEL.split(',').join(',') + '{user-select:text;-webkit-user-select:text}img,a{-webkit-user-drag:none}';
  (function put(){ var r = document.head || document.documentElement;
    if (r) r.appendChild(st); else document.addEventListener('readystatechange', put, {once:true}); })();
})();"#;

fn stop_server(app: &tauri::AppHandle) {
    let st = app.state::<Server>();
    let Some(mut child) = st.child.lock().unwrap().take() else { return };
    let pf = pidfile(st.port);
    let script = format!("p=$(cat {pf} 2>/dev/null) && kill -TERM \"$p\" 2>/dev/null; rm -f {pf}");
    let _ = wsl(&st.distro, &script).status();
    let t0 = Instant::now();
    while t0.elapsed() < Duration::from_secs(3) {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
}

fn main() {
    let (port, distro) = settings();
    tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(Server { port, distro, child: Mutex::new(None) })
        .setup(|app| {
            let retry = app.handle().clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Аудиотека")
                .inner_size(1920.0, 1040.0)
                .min_inner_size(800.0, 500.0)
                .center()
                .background_color(tauri::window::Color(0, 0, 0, 255))
                .theme(Some(tauri::Theme::Dark))
                .disable_drag_drop_handler()
                .initialization_script(SHELL_JS)
                .on_navigation(move |u| {
                    if u.as_str().starts_with(RETRY_URL) {
                        let h = retry.clone();
                        std::thread::spawn(move || {
                            if let Some(w) = h.get_webview_window("main") {
                                let _ = w.eval("location.replace('/index.html')");
                            }
                            std::thread::sleep(Duration::from_millis(300));
                            boot(h)
                        });
                        return false;
                    }
                    let local = matches!(u.scheme(), "tauri" | "about" | "data")
                        || matches!(u.host_str(), Some("127.0.0.1" | "localhost" | "tauri.localhost"));
                    if !local {
                        open_external(u.as_str());
                    }
                    local
                })
                .build()?;
            let h = app.handle().clone();
            std::thread::spawn(move || boot(h));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tauri")
        .run(|app, ev| {
            if let RunEvent::Exit = ev {
                stop_server(app);
            }
        });
}
