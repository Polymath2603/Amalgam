# Tauri Desktop Integration Plan

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Tauri Shell (Rust)                                   │
│  ┌─────────────────┐  ┌──────────────────────────┐  │
│  │ WebView (webkit) │  │ Sidecar (Python backend) │  │
│  │  - frontend/     │  │  - Started via Tauri    │  │
│  │  - index.html    │  │  - Communicates via     │  │
│  │  - app.js        │  │    HTTP/WS on localhost  │  │
│  │  - style.css     │  │  - Bundled as binary    │  │
│  └────────┬─────────┘  │    (PyInstaller/Nuitka) │  │
│           │            └──────────┬───────────────┘  │
│           └──────────┬────────────┘                   │
│                   HTTP :8000                          │
└─────────────────────────────────────────────────────┘
```

## Steps

### 1. Frontend Build Step
Currently `frontend/` is static files served by FastAPI. For Tauri:
- Add `package.json` with a build script (minify + copy to `dist/`)
- Use Vite or esbuild to bundle app.js + CSS
- Output goes to `frontend/dist/`

### 2. Backend Sidecar
Package `backend/` into a standalone binary:
```
PyInstaller: pyinstaller --onefile --name k-backend backend/__main__.py
```
The sidecar starts an HTTP server on a random port and writes the port + a secret token to stdout. Tauri reads this to configure the webview's API base URL.

### 3. Tauri Config (`src-tauri/`)
- `tauri.conf.json`: 
  - Point `build.devUrl` to `http://localhost:8000` (dev) or `frontend/dist/index.html` (prod)
  - Register sidecar binary under `bundle.externalBin`
  - Configure window size, title ("Amalgam"), icons
- `main.rs`:
  - Start sidecar on app launch, kill on exit
  - Expose IPC commands: `set_vault_path`, `get_data_dir`
  - Use Tauri's `shell` plugin to manage sidecar lifecycle

### 4. Required Dependencies
- Rust + Cargo (via rustup)
- Tauri CLI: `cargo install tauri-cli` or `npm install @tauri-apps/cli`
- For Linux: `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, etc.

### 5. Development Workflow
```
npm install        # Install frontend deps
npm run dev        # Build frontend + start Tauri dev server
                   # Sidecar launched automatically in debug
```

### 6. Distribution
```
npm run build          # Build release frontend
cargo tauri build      # Package .deb/.AppImage (Linux), .dmg (macOS), .msi (Windows)
```
Output: `src-tauri/target/release/bundle/`

## Build Configuration Files to Create

- `package.json` (root)
- `vite.config.ts` (frontend build)
- `src-tauri/Cargo.toml`
- `src-tauri/tauri.conf.json`
- `src-tauri/src/main.rs`
- `src-tauri/src/lib.rs`
- `src-tauri/icons/` (app icons)

## Not Done Yet

Requires `cargo` (Rust) which is not available in this environment.
Once installed:
```bash
npm init tauri-app@latest
# Select existing frontend path: ./frontend
# Select dev server command: (leave empty, static files)
cargo tauri dev
```
