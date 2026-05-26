use tauri::Manager;

#[tauri::command]
fn set_vault_path(path: String) -> String {
    format!("Vault path set to: {}", path)
}

#[tauri::command]
fn get_data_dir(app: tauri::AppHandle) -> String {
    app.path()
        .app_data_dir()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![set_vault_path, get_data_dir])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
