//! The bridge to the Python core.
//!
//! Spawns the sidecar, writes NDJSON requests to its stdin, reads NDJSON responses
//! from its stdout, and matches each response to its caller by `id`.
//!
//! This file is transport. It assigns request ids, it moves bytes, it hands back
//! whatever the core said. It never inspects a method name, never interprets a
//! result, and never decides anything -- all of that is the core's job.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::async_runtime::{self, Receiver};
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::oneshot;

/// A core request that has not been answered yet.
type Pending = HashMap<u64, oneshot::Sender<serde_json::Value>>;

/// How long a caller waits before giving up on the core.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

pub struct Sidecar {
    child: Mutex<Option<CommandChild>>,
    pending: Arc<Mutex<Pending>>,
    next_id: AtomicU64,
}

impl Sidecar {
    /// Start the core and begin pumping its stdout.
    pub fn spawn(app: &AppHandle) -> Result<Self, String> {
        let (rx, child) = app
            .shell()
            .sidecar("aibuilder-core")
            .map_err(|e| format!("sidecar not configured: {e}"))?
            .spawn()
            .map_err(|e| format!("sidecar failed to start: {e}"))?;

        let pending: Arc<Mutex<Pending>> = Arc::new(Mutex::new(HashMap::new()));
        async_runtime::spawn(pump(rx, Arc::clone(&pending)));

        Ok(Self {
            child: Mutex::new(Some(child)),
            pending,
            next_id: AtomicU64::new(1),
        })
    }

    /// Send one request and await the core's answer.
    pub async fn request(
        &self,
        method: String,
        params: serde_json::Value,
    ) -> Result<serde_json::Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let line = serde_json::json!({ "id": id, "method": method, "params": params });

        let (tx, rx) = oneshot::channel();
        self.pending
            .lock()
            .map_err(|_| "pending table poisoned".to_string())?
            .insert(id, tx);

        // Written inside a block so the child lock is released before awaiting.
        {
            let mut guard = self
                .child
                .lock()
                .map_err(|_| "sidecar lock poisoned".to_string())?;
            let child = guard.as_mut().ok_or("core is not running")?;
            child
                .write(format!("{line}\n").as_bytes())
                .map_err(|e| format!("write to core failed: {e}"))?;
        }

        match tokio::time::timeout(REQUEST_TIMEOUT, rx).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => {
                self.forget(id);
                Err("core closed the connection".into())
            }
            Err(_) => {
                self.forget(id);
                Err(format!("core did not answer within {REQUEST_TIMEOUT:?}"))
            }
        }
    }

    fn forget(&self, id: u64) {
        if let Ok(mut pending) = self.pending.lock() {
            pending.remove(&id);
        }
    }

    /// Stop the core. Closing stdin is enough -- the core exits on EOF.
    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

/// Read the core's output stream and resolve waiting callers.
async fn pump(mut rx: Receiver<CommandEvent>, pending: Arc<Mutex<Pending>>) {
    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(bytes) => {
                let line = String::from_utf8_lossy(&bytes);
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }

                let Ok(value) = serde_json::from_str::<serde_json::Value>(line) else {
                    eprintln!("[shell] core sent a non-JSON line: {line}");
                    continue;
                };

                let Some(id) = value.get("id").and_then(serde_json::Value::as_u64) else {
                    eprintln!("[shell] core response without a usable id: {line}");
                    continue;
                };

                let waiting = pending.lock().ok().and_then(|mut p| p.remove(&id));
                if let Some(tx) = waiting {
                    let _ = tx.send(value);
                }
            }
            // The core logs on stderr; surface it in the dev console untouched.
            CommandEvent::Stderr(bytes) => {
                eprint!("{}", String::from_utf8_lossy(&bytes));
            }
            CommandEvent::Terminated(status) => {
                eprintln!("[shell] core exited: {status:?}");
                if let Ok(mut p) = pending.lock() {
                    p.clear(); // drops every sender, unblocking callers with an error
                }
            }
            _ => {}
        }
    }
}

/// Convenience for command handlers.
pub fn sidecar(app: &AppHandle) -> Result<tauri::State<'_, Sidecar>, String> {
    app.try_state::<Sidecar>().ok_or_else(|| "core is not running".to_string())
}
