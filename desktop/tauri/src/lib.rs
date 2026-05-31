use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;
use tauri::Manager;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{TrayIconBuilder, TrayIconEvent, MouseButton, MouseButtonState};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::ShellExt;

struct BackendChild(Mutex<Option<std::process::Child>>);

fn find_godot() -> &'static str {
    if Command::new("godot4").arg("--version").output().is_ok() {
        "godot4"
    } else {
        "godot"
    }
}

fn project_root() -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    p.pop();
    p
}

fn godot_path() -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    p.push("godot");
    p
}

#[tauri::command]
fn launch_godot(app: tauri::AppHandle) -> Result<String, String> {
    let godot_bin = find_godot();
    let path = godot_path().to_string_lossy().to_string();
    let shell = app.shell();
    let (_rx, child) = shell
        .command(godot_bin)
        .arg("--path")
        .arg(&path)
        .spawn()
        .map_err(|e| format!("Failed to spawn {}: {}", godot_bin, e))?;
    Ok(format!("{} launched with pid: {}", godot_bin, child.pid()))
}

#[tauri::command]
fn get_data_dir(app: tauri::AppHandle) -> String {
    app.path()
        .app_data_dir()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string()
}

#[tauri::command]
fn show_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        let _ = window.unminimize();
    }
    Ok(())
}

#[tauri::command]
fn exit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn show_notification(app: tauri::AppHandle, title: String, body: String) -> Result<(), String> {
    app.notification()
        .builder()
        .title(&title)
        .body(&body)
        .show()
        .map_err(|e| e.to_string())
}

fn launch_backend() -> Option<std::process::Child> {
    let root = project_root();
    let main_py = root.join("main.py");
    if !main_py.exists() {
        eprintln!("Backend not found at: {}", main_py.display());
        return None;
    }
    match Command::new("python3")
        .arg(&main_py)
        .arg("webui")
        .arg("-vvv")
        .current_dir(&root)
        .spawn()
    {
        Ok(child) => {
            println!("Backend started with pid: {}", child.id());
            Some(child)
        }
        Err(e) => {
            eprintln!("Failed to start backend: {}", e);
            None
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "Show", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;

            let icon = tauri::image::Image::from_bytes(include_bytes!("../icons/32x32.png"))
                .expect("Failed to load tray icon");

            TrayIconBuilder::new()
                .icon(icon)
                .menu(&menu)
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            let child = if std::env::var("AMALGAM_SKIP_BACKEND").is_ok() {
                println!("Backend launched externally, skipping");
                None
            } else {
                launch_backend()
            };
            app.manage(BackendChild(Mutex::new(child)));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            launch_godot,
            get_data_dir,
            show_notification,
            show_window,
            exit_app
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        match event {
            tauri::RunEvent::WindowEvent { label, event: window_event, .. } => {
                if label == "main" {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = window_event {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.hide();
                            api.prevent_close();
                        }
                    }
                }
            }
            tauri::RunEvent::Exit => {
                if let Some(state) = app_handle.try_state::<BackendChild>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
            _ => {}
        }
    });
}
