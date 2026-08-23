//! The entire IPC surface: one command, forwarding to the core.
//!
//! Adding a second command is almost always the wrong move. A new capability is a
//! new *method* in the Python core, reachable through this same passthrough.

use serde_json::Value;
use tauri::AppHandle;

use crate::sidecar;

#[tauri::command]
pub async fn core_request(app: AppHandle, method: String, params: Value) -> Result<Value, String> {
    let state = sidecar::sidecar(&app)?;
    state.request(method, params).await
}
