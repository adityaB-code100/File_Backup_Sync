import os
import sys
import threading
import queue
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging

# Ensure app package is importable
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
PROJECT_ROOT = APP_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
import auth
import drive_client
import sync_engine
from watcher import IndividualFileMonitor

logger = logging.getLogger("vaultcloud.gui")

class VaultCloudGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VaultCloud — Desktop Sync Agent")
        self.geometry("860x700")
        self.minsize(740, 580)

        # Style configuration
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 9))
        self.style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"))
        self.style.configure("Status.TLabel", font=("Segoe UI", 9, "italic"))
        self.style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        self.style.configure("Treeview", font=("Segoe UI", 9), rowheight=24)

        self.drive_auth = None
        self.current_user = None
        self.device_id = None
        self.selected_file_path = None
        self.log_queue = queue.Queue()
        self.event_queue = queue.Queue()

        self._tree_paths = {}  # iid -> abs_path

        # Initialize Individual File Watcher
        self.monitor = IndividualFileMonitor(
            self.event_queue,
            debounce_seconds=1.0,
            on_start_editing=self._on_start_editing
        )

        self._init_database()
        self._build_ui()
        self._start_event_consumer()
        self._check_initial_auth()

        self.after(100, self._process_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_database(self):
        try:
            db.init_db()
            self.device_id = db.get_device_id()
        except Exception as e:
            logger.error(f"DB init failed: {e}")
            self.device_id = "unknown"

    def _log(self, message: str, level: str = "INFO"):
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] [{level}] {message}")

    def _process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.after(100, self._process_log_queue)

    def _on_start_editing(self, path: str):
        # Optional lock pre-acquisition when editor touches file
        if self.drive_auth:
            try:
                rec = db.get_record(path)
                if rec and rec.get("cloud_id"):
                    drive_client.acquire_lock(self.drive_auth, rec["cloud_id"], self.device_id)
            except Exception:
                pass

    def _build_ui(self):
        # Top banner: Account & Status
        self.banner_frame = ttk.Frame(self, padding="12 12 12 6")
        self.banner_frame.pack(fill=tk.X)

        self.account_label = ttk.Label(self.banner_frame, text="Active Account: Initializing...", style="Header.TLabel")
        self.account_label.pack(side=tk.LEFT)

        self.logout_btn = ttk.Button(self.banner_frame, text="Switch Account", command=self._on_logout)
        self.logout_btn.pack(side=tk.RIGHT)

        self.device_label = ttk.Label(self, text=f"Device ID: {self.device_id}", style="SubHeader.TLabel", foreground="#666666")
        self.device_label.pack(fill=tk.X, padx=12, pady=(0, 6))

        # Main separator
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=12, pady=4)

        # File Selection Frame
        self.file_frame = ttk.LabelFrame(self, text=" Upload & Track Individual File ", padding=10)
        self.file_frame.pack(fill=tk.X, padx=12, pady=6)

        file_btn_frame = ttk.Frame(self.file_frame)
        file_btn_frame.pack(fill=tk.X, pady=(0, 6))

        self.pick_file_btn = ttk.Button(file_btn_frame, text="Choose File...", command=self._pick_file)
        self.pick_file_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.upload_btn = ttk.Button(
            file_btn_frame, text="Upload to VaultCloud", style="Primary.TButton",
            command=self._start_upload, state=tk.DISABLED
        )
        self.upload_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.progress_bar = ttk.Progressbar(file_btn_frame, mode="indeterminate", length=180)
        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = ttk.Label(file_btn_frame, textvariable=self.status_var, style="Status.TLabel")
        self.status_lbl.pack(side=tk.LEFT)

        # Path display entry
        self.path_var = tk.StringVar(value="No file selected.")
        self.path_entry = ttk.Entry(self.file_frame, textvariable=self.path_var, state="readonly", font=("Consolas", 9))
        self.path_entry.pack(fill=tk.X, pady=(0, 4))

        # Tracked Files Table Section
        self.table_frame = ttk.LabelFrame(self, text=" Monitored Files (Auto-Sync) ", padding=10)
        self.table_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        # Treeview definition
        columns = ("name", "path", "version", "status", "last_sync", "error")
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings", selectmode="browse", height=6)
        self.tree.heading("name", text="File Name")
        self.tree.heading("path", text="Local Path")
        self.tree.heading("version", text="Version")
        self.tree.heading("status", text="Sync Status")
        self.tree.heading("last_sync", text="Last Successful Sync")
        self.tree.heading("error", text="Error Details")

        self.tree.column("name", width=140, minwidth=100)
        self.tree.column("path", width=220, minwidth=140)
        self.tree.column("version", width=60, minwidth=50, anchor=tk.CENTER)
        self.tree.column("status", width=110, minwidth=90, anchor=tk.CENTER)
        self.tree.column("last_sync", width=140, minwidth=110)
        self.tree.column("error", width=140, minwidth=80)

        # Colors for status tags
        self.tree.tag_configure("Synced", foreground="#2e7d32")
        self.tree.tag_configure("Monitoring", foreground="#1565c0")
        self.tree.tag_configure("Changes detected", foreground="#e65100")
        self.tree.tag_configure("Uploading", foreground="#e65100")
        self.tree.tag_configure("Conflict", foreground="#b71c1c")
        self.tree.tag_configure("Error", foreground="#c62828")
        self.tree.tag_configure("Stopped", foreground="#757575")

        tree_scroll_y = ttk.Scrollbar(self.table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(self.table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Table action controls
        table_ctrl_frame = ttk.Frame(self.table_frame, padding="0 6 0 0")
        table_ctrl_frame.pack(fill=tk.X)

        self.sync_now_btn = ttk.Button(table_ctrl_frame, text="Sync Selected", command=self._sync_selected_now)
        self.sync_now_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.toggle_monitor_btn = ttk.Button(table_ctrl_frame, text="Stop / Resume Monitoring", command=self._toggle_monitoring)
        self.toggle_monitor_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.open_file_btn = ttk.Button(table_ctrl_frame, text="Open File", command=self._open_selected_file)
        self.open_file_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.open_dir_btn = ttk.Button(table_ctrl_frame, text="Show in Explorer", command=self._open_selected_folder)
        self.open_dir_btn.pack(side=tk.LEFT)

        # Activity Log Section
        self.log_frame = ttk.LabelFrame(self, text=" Activity Log ", padding=8)
        self.log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 10))

        self.log_text = tk.Text(self.log_frame, wrap=tk.WORD, font=("Consolas", 9), state=tk.DISABLED, bg="#1e1e1e", fg="#d4d4d4", height=6)
        self.log_scroll = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)

        self.log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _start_event_consumer(self):
        def _consumer():
            while True:
                try:
                    event = self.event_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                except Exception:
                    break

                event_path = event.get("path")
                event_type = event.get("type", "changed")
                self._handle_tracked_file_event(event_path, event_type)

        thread = threading.Thread(target=_consumer, daemon=True, name="IndividualFileConsumer")
        thread.start()

    def _check_initial_auth(self):
        def _bg_check():
            try:
                self.drive_auth = auth.get_drive_service()
                user = self.drive_auth.get_current_user()
                if user:
                    self.current_user = user
                    email = user.get("email", "Authenticated")
                    uid = user.get("id", "")
                    db.set_sync_user(str(uid), email)
                    self.after(0, lambda: self._on_auth_success(email, str(uid)))
                else:
                    self.after(0, self._show_login_modal)
            except Exception as e:
                self._log(f"Authentication check: {e}", "WARNING")
                self.after(0, self._show_login_modal)

        threading.Thread(target=_bg_check, daemon=True).start()

    def _on_auth_success(self, email: str, uid: str):
        self.account_label.config(text=f"Active Account: {email}", foreground="#2e7d32")
        self._log(f"Successfully authenticated as {email} (ID: {uid})")
        self._log("Initializing auto-sync monitor...")
        self.monitor.start()
        self._restore_tracked_files()

    def _restore_tracked_files(self):
        records = db.get_tracked_individual_files()
        self._log(f"Restoring {len(records)} individually tracked file(s) from local database...")
        for rec in records:
            abs_p = rec.get("abs_path") or rec.get("path")
            if not abs_p:
                continue
            abs_p = os.path.abspath(abs_p)
            is_active = rec.get("is_active", 1)
            status = rec.get("status", "Synced")
            cloud_ver = rec.get("cloud_version", 1)
            last_sync = rec.get("last_sync_time") or rec.get("updated_at", "")
            err = rec.get("error_message", "")

            # Format timestamp for display
            if last_sync and "T" in last_sync:
                try:
                    last_sync = last_sync.replace("T", " ").split(".")[0]
                except Exception:
                    pass

            self._update_file_status_ui(
                abs_p,
                status=status if is_active else "Stopped",
                version=cloud_ver,
                last_sync=last_sync,
                error=err
            )

            if is_active and os.path.exists(abs_p):
                self.monitor.track_file(abs_p)
                self._log(f"Monitoring resumed for: {os.path.basename(abs_p)} ({abs_p})")
                # Asynchronously check if file changed while agent was offline
                threading.Thread(target=self._check_offline_changes, args=(abs_p,), daemon=True).start()
            elif is_active and not os.path.exists(abs_p):
                self._update_file_status_ui(abs_p, status="Error", error="File missing on disk")
                self._log(f"Tracked file not found on disk: {abs_p}", "WARNING")

    def _check_offline_changes(self, abs_path: str):
        if not os.path.exists(abs_path) or not self.drive_auth:
            return
        try:
            current_hash = drive_client.hash_file(abs_path)
            rec = db.get_record(abs_path)
            if rec and rec.get("last_synced_hash") != current_hash:
                self._log(f"Offline edits detected on '{os.path.basename(abs_path)}'. Synchronizing now...")
                self._handle_tracked_file_event(abs_path, "changed")
        except Exception as e:
            logger.warning(f"Error checking offline changes for '{abs_path}': {e}")

    def _handle_tracked_file_event(self, path: str, event_type: str):
        abs_path = os.path.abspath(path)
        filename = os.path.basename(abs_path)
        if not self.drive_auth:
            self._log(f"Skipping auto-sync for '{filename}' (not authenticated)", "WARNING")
            return

        # Update GUI status to Changes detected
        self.after(0, lambda: self._update_file_status_ui(abs_path, status="Changes detected"))
        self._log(f"Detected modification in '{filename}'...")

        # Wait briefly and verify file stability
        if not drive_client.is_file_stable(abs_path, wait_seconds=0.5, retries=4):
            self._log(f"File '{filename}' is being written or locked. Retrying shortly...", "WARNING")
            return

        if not os.path.exists(abs_path):
            self.after(0, lambda: self._update_file_status_ui(abs_path, status="Error", error="File deleted locally"))
            return

        try:
            current_hash = drive_client.hash_file(abs_path)
        except Exception as e:
            self.after(0, lambda: self._update_file_status_ui(abs_path, status="Error", error=str(e)))
            return

        rec = db.get_record(abs_path) or db.get_record(filename)
        if rec and rec.get("last_synced_hash") == current_hash:
            # File timestamp changed but content is identical - do not duplicate versions
            now_str = rec.get("last_sync_time") or time.strftime("%Y-%m-%d %H:%M:%S")
            self.after(0, lambda: self._update_file_status_ui(abs_path, status="Synced", last_sync=now_str))
            self._log(f"File '{filename}' saved without content changes (SHA-256 verified).")
            return

        # Uploading changed content
        self.after(0, lambda: self._update_file_status_ui(abs_path, status="Uploading"))
        self._log(f"Auto-syncing '{filename}' to VaultCloud...")

        try:
            resp = sync_engine.sync_individual_file(self.drive_auth, abs_path, self.device_id)
            status_code = resp.get("status")

            if status_code == "conflict":
                self.after(0, lambda: self._update_file_status_ui(abs_path, status="Conflict", error="Conflict: cloud copy updated"))
                self._log(f"Conflict on '{filename}': Created conflicted copy and refreshed.", "WARNING")
            elif status_code == "locked":
                self.after(0, lambda: self._update_file_status_ui(abs_path, status="Error", error="File locked by another user"))
                self._log(f"Upload blocked for '{filename}': File is locked.", "WARNING")
            else:
                new_ver = resp.get("version_number", 1)
                cloud_id = resp.get("id")
                now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                self.after(0, lambda: self._update_file_status_ui(abs_path, status="Synced", version=new_ver, last_sync=now_str, error=""))
                self._log(f"Auto-sync COMPLETE: '{filename}' updated to Version {new_ver} (Cloud ID: {cloud_id})")
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: self._update_file_status_ui(abs_path, status="Error", error=err_msg))
            self._log(f"Auto-sync FAILED for '{filename}': {err_msg}", "ERROR")

    def _update_file_status_ui(self, abs_path: str, status: str, version: int = None, last_sync: str = None, error: str = None):
        norm_key = os.path.normcase(abs_path)
        filename = os.path.basename(abs_path)

        if self.tree.exists(norm_key):
            current_vals = list(self.tree.item(norm_key, "values"))
            if version is not None:
                current_vals[2] = f"v{version}"
            if status is not None:
                current_vals[3] = status
            if last_sync is not None:
                current_vals[4] = last_sync
            if error is not None:
                current_vals[5] = error
            self.tree.item(norm_key, values=current_vals, tags=(status,))
        else:
            ver_str = f"v{version}" if version is not None else "v1"
            self.tree.insert(
                "", tk.END, iid=norm_key,
                values=(filename, abs_path, ver_str, status, last_sync or "-", error or ""),
                tags=(status,)
            )
            self._tree_paths[norm_key] = abs_path

    def _pick_file(self):
        chosen = filedialog.askopenfilename(title="Select File to Upload & Track")
        if chosen:
            self.selected_file_path = os.path.abspath(chosen)
            self.path_var.set(self.selected_file_path)
            size_kb = round(os.path.getsize(self.selected_file_path) / 1024, 1)
            self.status_var.set(f"Selected: {os.path.basename(self.selected_file_path)} ({size_kb} KB)")
            self.upload_btn.config(state=tk.NORMAL)
            self._log(f"Selected file: {self.selected_file_path} ({size_kb} KB)")

    def _start_upload(self):
        if not self.selected_file_path or not os.path.exists(self.selected_file_path):
            messagebox.showwarning("Warning", "Please select a valid local file first.")
            return

        if not self.drive_auth:
            messagebox.showerror("Error", "Not authenticated. Please sign in.")
            return

        filepath = os.path.abspath(self.selected_file_path)
        filename = os.path.basename(filepath)

        self.upload_btn.config(state=tk.DISABLED)
        self.pick_file_btn.config(state=tk.DISABLED)
        self.progress_bar.pack(side=tk.LEFT, padx=(0, 12))
        self.progress_bar.start(10)
        self.status_var.set("Uploading & encrypting...")
        self._update_file_status_ui(filepath, status="Uploading")

        def _bg_upload():
            try:
                self._log(f"Starting initial upload for '{filename}'...")
                resp = sync_engine.upload_new_individual_file(self.drive_auth, filepath, self.device_id)
                cloud_id = resp.get("id")
                ver = resp.get("version_number", 1)
                now_str = time.strftime("%Y-%m-%d %H:%M:%S")

                # Begin monitoring this file
                self.monitor.track_file(filepath)

                self.after(0, lambda: self._update_file_status_ui(filepath, status="Synced", version=ver, last_sync=now_str, error=""))
                self.after(0, lambda: self._on_upload_finished(f"Success! Cloud ID: {cloud_id}"))
                self._log(f"Upload SUCCESS: '{filename}' (Cloud ID: {cloud_id}, Version: {ver}). Monitoring active!")
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self._update_file_status_ui(filepath, status="Error", error=err_msg))
                self._log(f"Upload FAILED for '{filename}': {err_msg}", "ERROR")
                self.after(0, lambda: self._on_upload_finished(f"Failed: {err_msg}", is_error=True))

        threading.Thread(target=_bg_upload, daemon=True).start()

    def _on_upload_finished(self, status_msg: str, is_error: bool = False):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.status_var.set(status_msg)
        self.upload_btn.config(state=tk.NORMAL)
        self.pick_file_btn.config(state=tk.NORMAL)
        if is_error:
            messagebox.showerror("Upload Status", status_msg)
        else:
            messagebox.showinfo("Upload Complete", status_msg)

    def _get_selected_tree_path(self) -> str | None:
        selected = self.tree.selection()
        if not selected:
            return None
        iid = selected[0]
        return self._tree_paths.get(iid)

    def _sync_selected_now(self):
        abs_p = self._get_selected_tree_path()
        if not abs_p:
            messagebox.showinfo("Select File", "Please select a file from the monitored list first.")
            return

        if not self.drive_auth:
            messagebox.showerror("Error", "Not authenticated.")
            return

        self._log(f"Manual sync triggered for: '{os.path.basename(abs_p)}'...")
        threading.Thread(target=self._handle_tracked_file_event, args=(abs_p, "changed"), daemon=True).start()

    def _toggle_monitoring(self):
        abs_p = self._get_selected_tree_path()
        if not abs_p:
            messagebox.showinfo("Select File", "Please select a file from the monitored list first.")
            return

        rec = db.get_record(abs_p)
        is_active = rec.get("is_active", 1) if rec else 1

        if is_active:
            # Stop monitoring safely
            self.monitor.untrack_file(abs_p)
            db.set_file_active(abs_p, 0, status="Stopped")
            self._update_file_status_ui(abs_p, status="Stopped")
            self._log(f"Stopped monitoring '{os.path.basename(abs_p)}'. Local and cloud files remain safe.")
        else:
            # Resume monitoring
            if os.path.exists(abs_p):
                self.monitor.track_file(abs_p)
                db.set_file_active(abs_p, 1, status="Monitoring")
                self._update_file_status_ui(abs_p, status="Monitoring")
                self._log(f"Resumed monitoring for '{os.path.basename(abs_p)}'.")
                threading.Thread(target=self._check_offline_changes, args=(abs_p,), daemon=True).start()
            else:
                messagebox.showerror("Error", f"File '{abs_p}' not found on disk.")

    def _open_selected_file(self):
        abs_p = self._get_selected_tree_path() or self.selected_file_path
        if abs_p and os.path.exists(abs_p):
            try:
                os.startfile(abs_p)
            except Exception as e:
                messagebox.showerror("Open File Error", str(e))
        else:
            messagebox.showwarning("Warning", "File does not exist or none selected.")

    def _open_selected_folder(self):
        abs_p = self._get_selected_tree_path() or self.selected_file_path
        if abs_p and os.path.exists(abs_p):
            try:
                subprocess.Popen(f'explorer /select,"{abs_p}"')
            except Exception as e:
                messagebox.showerror("Open Explorer Error", str(e))
        else:
            messagebox.showwarning("Warning", "File does not exist or none selected.")

    def _show_login_modal(self):
        modal = tk.Toplevel(self)
        modal.title("VaultCloud Login")
        modal.geometry("380x260")
        modal.resizable(False, False)
        modal.grab_set()

        ttk.Label(modal, text="Sign In to VaultCloud", font=("Segoe UI", 11, "bold")).pack(pady=(16, 12))

        form = ttk.Frame(modal, padding=16)
        form.pack(fill=tk.BOTH, expand=True)

        ttk.Label(form, text="Email:").grid(row=0, column=0, sticky=tk.W, pady=6)
        email_entry = ttk.Entry(form, width=30)
        email_entry.grid(row=0, column=1, pady=6)
        email_entry.focus()

        # Prefill default email if credentials exist
        creds_path = auth.CANONICAL_CREDS_PATH
        if os.path.exists(creds_path):
            try:
                import json
                with open(creds_path) as f:
                    c = json.load(f)
                    if c.get("email"):
                        email_entry.insert(0, c["email"])
            except Exception:
                pass

        ttk.Label(form, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=6)
        pwd_entry = ttk.Entry(form, show="*", width=30)
        pwd_entry.grid(row=1, column=1, pady=6)

        err_lbl = ttk.Label(form, text="", foreground="red", font=("Segoe UI", 8))
        err_lbl.grid(row=2, column=0, columnspan=2, pady=4)

        def _do_login():
            em = email_entry.get().strip()
            pw = pwd_entry.get()
            if not em or not pw:
                err_lbl.config(text="Please provide email and password.")
                return

            err_lbl.config(text="Authenticating...", foreground="#555555")
            def _bg():
                try:
                    srv = auth.get_drive_service(email=em, password=pw)
                    u = srv.get_current_user()
                    if u:
                        self.drive_auth = srv
                        self.current_user = u
                        db.set_sync_user(str(u["id"]), u["email"])
                        modal.after(0, modal.destroy)
                        self.after(0, lambda: self._on_auth_success(u["email"], str(u["id"])))
                    else:
                        modal.after(0, lambda: err_lbl.config(text="Login failed. Check credentials.", foreground="red"))
                except Exception as e:
                    modal.after(0, lambda: err_lbl.config(text=f"Error: {e}", foreground="red"))

            threading.Thread(target=_bg, daemon=True).start()

        ttk.Button(form, text="Sign In", command=_do_login, style="Primary.TButton").grid(row=3, column=0, columnspan=2, pady=12)

    def _on_logout(self):
        confirm = messagebox.askyesno(
            "Switch Account",
            "Are you sure you want to log out of the current account?\nYour local files will remain safe."
        )
        if confirm:
            try:
                if os.path.exists(auth.CANONICAL_TOKEN_PATH):
                    os.remove(auth.CANONICAL_TOKEN_PATH)
                self.current_user = None
                self.drive_auth = None
                self.monitor.stop()
                self.tree.delete(*self.tree.get_children())
                self._tree_paths.clear()
                self.account_label.config(text="Active Account: Logged Out", foreground="#888888")
                self._log("Logged out of session. Please sign in with desired account.")
                self._show_login_modal()
            except Exception as e:
                messagebox.showerror("Logout Error", str(e))

    def _on_close(self):
        try:
            self.monitor.stop()
        except Exception:
            pass
        self.destroy()

def main():
    app = VaultCloudGUI()
    app.mainloop()

if __name__ == "__main__":
    main()
