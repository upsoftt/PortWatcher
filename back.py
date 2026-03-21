import os
import sys
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import webbrowser
import textwrap

try:
    from trayconsole_client import TrayConsoleClient
    _trayconsole_available = True
except ImportError:
    _trayconsole_available = False

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

class ToolTip(object):
    def __init__(self, widget):
        self.widget = widget
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0
        self.text = ""
        self.current_item = None
        self.current_col = None

    def showtip(self, text, x, y, item, col):
        if self.tipwindow and self.current_item == item and self.current_col == col:
            return
        self.hidetip()
        self.text = text
        self.current_item = item
        self.current_col = col
        if not self.text:
            return
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry(f"+{x}+{y}")
        try:
            tw.tk.call("::tk::unsupported::MacWindowStyle", "style", tw._w, "help", "noActivates")
        except tk.TclError:
            pass
        
        wrapped_text = textwrap.fill(self.text, width=100)
        label = tk.Label(tw, text=wrapped_text, justify=tk.LEFT,
                      background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                      font=("Segoe UI", 9, "normal"))
        label.pack(ipadx=4, ipady=4)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        self.current_item = None
        self.current_col = None
        if tw:
            tw.destroy()

class PortWatcherApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Port Watcher (Убийца Портов)")
        self.root.geometry("1200x600")
        
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except:
            pass
        style.configure("Treeview", rowheight=25, font=('Segoe UI', 10))
        style.configure("Treeview.Heading", font=('Segoe UI', 10, 'bold'))
        
        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        cols = ("Port", "PID", "Name", "User", "Path", "Cmdline")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        
        self.tree.heading("Port", text="Порт", command=lambda: self.sort_column("Port", False))
        self.tree.heading("PID", text="PID", command=lambda: self.sort_column("PID", False))
        self.tree.heading("Name", text="Процесс", command=lambda: self.sort_column("Name", False))
        self.tree.heading("User", text="Пользователь")
        self.tree.heading("Path", text="Путь (Где лежит)")
        self.tree.heading("Cmdline", text="Строка запуска (Параметры)")
        
        self.tree.column("Port", width=60, anchor=tk.CENTER, minwidth=60)
        self.tree.column("PID", width=60, anchor=tk.CENTER, minwidth=60)
        self.tree.column("Name", width=150, minwidth=100)
        self.tree.column("User", width=120, minwidth=100)
        self.tree.column("Path", width=300, minwidth=150)
        self.tree.column("Cmdline", width=400, minwidth=200)
        
        self.current_sort_col = "Port"
        self.current_sort_reverse = False
        
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        
        # Интерактивность
        self.tooltip = ToolTip(self.tree)
        self.tree.bind("<Motion>", self.on_mouse_motion)
        self.tree.bind("<Leave>", lambda e: self.tooltip.hidetip())
        self.tree.bind('<Double-1>', self.on_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu)
        
        # Контекстное меню
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="🌐 Открыть в браузере (localhost:порт)", command=self.open_in_browser)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="💀 Убить выделенные процессы", command=self.kill_selected)
        
        # Панель управления (кнопки)
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="🔄 Обновить список", command=self.refresh_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💀 УБИТЬ ВЫДЕЛЕННОЕ", command=self.kill_selected).pack(side=tk.LEFT, padx=5)
        
        if not is_admin():
            ttk.Label(btn_frame, text="⚠️ Для управления системными портами нужны права Администратора!", foreground="red").pack(side=tk.LEFT, padx=15)
            ttk.Button(btn_frame, text="🛡️ Перезапустить от имени Администратора", command=self.run_as_admin).pack(side=tk.RIGHT, padx=5)
            
        self.refresh_data()
        
    def on_mouse_motion(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if item and col:
            col_idx = int(col.replace('#', '')) - 1
            values = self.tree.item(item, 'values')
            if values and col_idx < len(values):
                text = str(values[col_idx])
                # Если текст достаточно длинный, показываем подсказку
                if len(text) > 15:
                    self.tooltip.showtip(text, event.x_root + 15, event.y_root + 15, item, col)
                else:
                    self.tooltip.hidetip()
            else:
                self.tooltip.hidetip()
        else:
            self.tooltip.hidetip()

    def on_double_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "separator":
            col = self.tree.identify_column(event.x)
            col_idx = int(col.replace('#', '')) - 1
            
            header_text = self.tree.heading(col, 'text')
            max_len = len(header_text) * 10 
            
            for item in self.tree.get_children(''):
                val = str(self.tree.item(item, 'values')[col_idx])
                width = len(val) * 8
                if width > max_len:
                    max_len = width
            
            self.tree.column(col, width=min(max_len + 20, 1000))
            return "break"

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def open_in_browser(self):
        for item in self.tree.selection():
            port = self.tree.item(item, 'values')[0]
            webbrowser.open(f"http://localhost:{port}")

    def sort_column(self, col, reverse):
        self.current_sort_col = col
        self.current_sort_reverse = reverse
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        try:
            l.sort(key=lambda t: int(t[0]), reverse=reverse)
        except ValueError:
            l.sort(key=lambda t: str(t[0]).lower(), reverse=reverse)
            
        for index, (val, k) in enumerate(l):
            self.tree.move(k, '', index)
        self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))

    def run_as_admin(self):
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
            self.quit_app()
        except:
            pass

    def refresh_data(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        try:
            connections = psutil.net_connections(kind='inet')
        except psutil.AccessDenied:
            connections = []
            
        listen_conns = [c for c in connections if c.status == psutil.CONN_LISTEN and c.pid]
        
        for c in listen_conns:
            port = c.laddr.port
            pid = c.pid
            
            name = "Неизвестно"
            user = "Неизвестно"
            path = "Доступ запрещен / Не найдено"
            cmdline = ""
            
            try:
                p = psutil.Process(pid)
                name = p.name()
                try: user = p.username()
                except: pass
                try: path = p.exe()
                except: pass
                try: cmdline = " ".join(p.cmdline())
                except: pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
            self.tree.insert("", tk.END, values=(port, pid, name, user, path, cmdline))
            
        if hasattr(self, 'current_sort_col') and self.current_sort_col:
            self.sort_column(self.current_sort_col, self.current_sort_reverse)
            # We need to invert back the reverse flag because sort_column toggles it for the NEXT click
            self.current_sort_reverse = not self.current_sort_reverse
            self.tree.heading(self.current_sort_col, command=lambda c=self.current_sort_col, r=not self.current_sort_reverse: self.sort_column(c, r))

    def kill_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Сначала выберите процесс(ы) в таблице!")
            return
        
        processes_to_kill = []
        for item in sel:
            values = self.tree.item(item, 'values')
            processes_to_kill.append((values[0], values[1], values[2]))
            
        if len(processes_to_kill) == 1:
            msg = f"Убить процесс {processes_to_kill[0][2]} (PID: {processes_to_kill[0][1]}), который держит порт {processes_to_kill[0][0]}?"
        else:
            msg = f"Убить {len(processes_to_kill)} выделенных процессов?"
            
        if messagebox.askyesno("Подтверждение", msg):
            killed = 0
            errors = []
            for port, pid, name in processes_to_kill:
                try:
                    p = psutil.Process(int(pid))
                    p.terminate()
                    p.wait(timeout=3)
                    killed += 1
                except Exception as e:
                    errors.append(f"{name} (PID: {pid}): {e}")
            
            if errors:
                err_str = "\n".join(errors[:5])
                if len(errors) > 5: err_str += "\n..."
                messagebox.showerror("Результат", f"Убито: {killed} из {len(processes_to_kill)}\nОшибки:\n{err_str}")
            else:
                self.refresh_data()

    def hide_window(self):
        self.root.withdraw()
        
    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.refresh_data()

    def quit_app(self):
        self.root.quit()
        os._exit(0)

def _setup_trayconsole(root, app):
    if not _trayconsole_available:
        return

    client = TrayConsoleClient("trayconsole_portwatcher")

    @client.on("show")
    def handle_show():
        root.after(0, app.show_window)
        return {"ok": True}

    @client.on("hide")
    def handle_hide():
        root.after(0, app.hide_window)
        return {"ok": True}

    @client.on("status")
    def handle_status():
        return {"status": "running", "visible": bool(root.winfo_viewable())}

    @client.on("shutdown")
    def handle_shutdown():
        root.after(0, app.quit_app)
        return {"status": "ok"}

    client.start()

if __name__ == "__main__":
    app = PortWatcherApp()
    _setup_trayconsole(app.root, app)
    app.root.mainloop()
