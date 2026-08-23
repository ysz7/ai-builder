//! Tauri shell.
//!
//! Responsibilities, in full: open a window, start the Python core, carry JSON
//! between the two, stop the core on exit. Anything that looks like a decision --
//! parsing, gating, writing code, repair -- belongs in the core, not here.

mod commands;
mod sidecar;

use tauri::{Manager, RunEvent};

use crate::sidecar::Sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![commands::core_request])
        .setup(|app| {
            // A window with no core behind it is a dead window, so a failure to
            // spawn is fatal rather than something the UI has to discover later.
            let core = Sidecar::spawn(app.handle())?;
            app.manage(core);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Tauri application")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(core) = app.try_state::<Sidecar>() {
                    core.shutdown();
                }
            }
        });
}
