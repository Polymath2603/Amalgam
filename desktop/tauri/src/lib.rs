use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;
use tauri::Manager;
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
        .setup(|app| {
            let child = launch_backend();
            app.manage(BackendChild(Mutex::new(child)));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![launch_godot, get_data_dir])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<BackendChild>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        }
    });
}
