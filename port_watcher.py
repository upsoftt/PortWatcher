import os
import sys
import ctypes
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import pystray
from PIL import Image, ImageDraw
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
        self.root.geometry("1300x600")

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except:
            pass
        style.configure("Treeview", rowheight=25, font=('Segoe UI', 10))
        style.configure("Treeview.Heading", font=('Segoe UI', 10, 'bold'))

        # Основной фрейм для таблиц
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(right_frame, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        hsb = ttk.Scrollbar(right_frame, orient="horizontal")
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        # Деревья: show="tree headings" — включает #0 колонку для expand/collapse
        self.tree_left = ttk.Treeview(left_frame, columns=("Port", "PID", "Name"),
                                       show="tree headings", selectmode="extended")
        self.tree_right = ttk.Treeview(right_frame, columns=("User", "Path", "Cmdline"),
                                        show="tree headings", selectmode="extended")

        self.tree_left.pack(side=tk.LEFT, fill=tk.Y)
        self.tree_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # #0 колонка: стрелки раскрытия слева, скрыта справа
        self.tree_left.column("#0", width=24, stretch=False)
        self.tree_left.heading("#0", text="")
        self.tree_right.column("#0", width=0, stretch=False)
        self.tree_right.heading("#0", text="")

        # Заголовки с сортировкой
        self.tree_left.heading("Port", text="Порт", command=lambda: self.sort_data("Port"))
        self.tree_left.heading("PID", text="PID", command=lambda: self.sort_data("PID"))
        self.tree_left.heading("Name", text="Процесс", command=lambda: self.sort_data("Name"))

        self.tree_right.heading("User", text="Пользователь", command=lambda: self.sort_data("User"))
        self.tree_right.heading("Path", text="Путь (Где лежит)", command=lambda: self.sort_data("Path"))
        self.tree_right.heading("Cmdline", text="Строка запуска (Параметры)", command=lambda: self.sort_data("Cmdline"))

        # Колонки
        self.tree_left.column("Port", width=60, anchor=tk.CENTER, stretch=False)
        self.tree_left.column("PID", width=60, anchor=tk.CENTER, stretch=False)
        self.tree_left.column("Name", width=180, stretch=False)

        self.tree_right.column("User", width=120, stretch=False)
        self.tree_right.column("Path", width=350, stretch=False)
        self.tree_right.column("Cmdline", width=600, stretch=False)

        # --- Синхронизация скроллов ---
        def on_vscroll(*args):
            self.tree_left.yview(*args)
            self.tree_right.yview(*args)
        vsb.configure(command=on_vscroll)

        def on_left_scroll(f, l):
            vsb.set(f, l)
            self.tree_right.yview_moveto(f)

        def on_right_scroll(f, l):
            vsb.set(f, l)
            self.tree_left.yview_moveto(f)

        self.tree_left.configure(yscrollcommand=on_left_scroll)
        self.tree_right.configure(yscrollcommand=on_right_scroll, xscrollcommand=hsb.set)
        hsb.configure(command=self.tree_right.xview)

        # --- Синхронизация выделения ---
        self._syncing = False
        def sync_sel(source, target):
            def handler(e):
                if self._syncing:
                    return
                self._syncing = True
                try:
                    sel = source.selection()
                    if sel != target.selection():
                        target.selection_set(sel)
                    f = source.focus()
                    if f and target.focus() != f:
                        target.focus(f)
                except Exception:
                    pass
                finally:
                    self._syncing = False
            return handler

        self.tree_left.bind("<<TreeviewSelect>>", sync_sel(self.tree_left, self.tree_right))
        self.tree_right.bind("<<TreeviewSelect>>", sync_sel(self.tree_right, self.tree_left))

        # --- Синхронизация expand/collapse (left → right, right → left) ---
        self._syncing_tree = False
        def sync_open(source, target):
            def handler(e):
                if self._syncing_tree:
                    return
                self._syncing_tree = True
                try:
                    item = source.focus()
                    if item and target.exists(item):
                        target.item(item, open=source.item(item, 'open'))
                except Exception:
                    pass
                finally:
                    self._syncing_tree = False
            return handler

        self.tree_left.bind("<<TreeviewOpen>>", sync_open(self.tree_left, self.tree_right))
        self.tree_left.bind("<<TreeviewClose>>", sync_open(self.tree_left, self.tree_right))
        self.tree_right.bind("<<TreeviewOpen>>", sync_open(self.tree_right, self.tree_left))
        self.tree_right.bind("<<TreeviewClose>>", sync_open(self.tree_right, self.tree_left))

        # --- Колёсико мыши ---
        def on_mousewheel(event):
            self.tree_left.yview_scroll(int(-1*(event.delta/120)), "units")
            self.tree_right.yview_scroll(int(-1*(event.delta/120)), "units")
            return "break"
        self.tree_left.bind("<MouseWheel>", on_mousewheel)
        self.tree_right.bind("<MouseWheel>", on_mousewheel)

        # --- Tooltips ---
        self.tooltip_left = ToolTip(self.tree_left)
        self.tooltip_right = ToolTip(self.tree_right)

        self.tree_left.bind("<Motion>", lambda e: self._handle_motion(e, self.tree_left, self.tooltip_left))
        self.tree_right.bind("<Motion>", lambda e: self._handle_motion(e, self.tree_right, self.tooltip_right))
        self.tree_left.bind("<Leave>", lambda e: self.tooltip_left.hidetip())
        self.tree_right.bind("<Leave>", lambda e: self.tooltip_right.hidetip())

        # Двойной клик по разделителю колонок — автоподгон ширины
        self.tree_left.bind('<Double-1>', lambda e: self.on_double_click(e, self.tree_left))
        self.tree_right.bind('<Double-1>', lambda e: self.on_double_click(e, self.tree_right))

        # --- Контекстное меню ---
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="🌐 Открыть в браузере (localhost:порт)", command=self.open_in_browser)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="💀 Убить выделенные процессы", command=self.kill_selected)

        self.tree_left.bind("<Button-3>", lambda e: self.show_context_menu(e, self.tree_left))
        self.tree_right.bind("<Button-3>", lambda e: self.show_context_menu(e, self.tree_right))

        # --- Панель кнопок ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="🔄 Обновить список", command=self.refresh_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💀 УБИТЬ ВЫДЕЛЕННОЕ", command=self.kill_selected).pack(side=tk.LEFT, padx=5)

        # Sizegrip в правом нижнем углу
        sizegrip = ttk.Sizegrip(btn_frame)
        sizegrip.pack(side=tk.RIGHT, anchor=tk.SE)

        # Расширенная зона ресайза на всех границах окна (Windows API)
        self._setup_wide_resize_border()

        # --- Данные и состояние ---
        self.data_list = []
        self.current_sort_col = "Port"
        self.current_sort_reverse = False

        # Первоначальная загрузка — синхронно
        self.data_list = self._collect_data()
        self._sort_data()
        self._apply_diff(self.data_list)
        self._start_auto_refresh()

    # ── Расширенная зона ресайза ──────────────────────────────────

    def _setup_wide_resize_border(self):
        """Расширяет невидимую зону захвата границ окна для удобного ресайза.
        Перехватывает WM_NCHITTEST и расширяет граничную зону до BORDER_WIDTH пикселей."""
        try:
            import ctypes.wintypes
            GWL_WNDPROC = -4
            BORDER_WIDTH = 8  # пикселей — зона захвата по краям

            # WM_NCHITTEST результаты
            HTCLIENT = 1
            HTLEFT = 10
            HTRIGHT = 11
            HTTOP = 12
            HTTOPLEFT = 13
            HTTOPRIGHT = 14
            HTBOTTOM = 15
            HTBOTTOMLEFT = 16
            HTBOTTOMRIGHT = 17

            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_uint,
                                         ctypes.c_uint, ctypes.c_long)
            user32 = ctypes.windll.user32

            hwnd = self.root.winfo_id()
            # Получаем HWND верхнего уровня (Tk wraps в child window)
            GetParent = user32.GetParent
            parent = GetParent(hwnd)
            if parent:
                hwnd = parent

            CallWindowProc = user32.CallWindowProcW
            CallWindowProc.restype = ctypes.c_long
            CallWindowProc.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_uint,
                                       ctypes.c_uint, ctypes.c_long]

            SetWindowLongPtr = user32.SetWindowLongPtrW
            SetWindowLongPtr.restype = ctypes.c_void_p
            SetWindowLongPtr.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_void_p]

            old_proc = SetWindowLongPtr(hwnd, GWL_WNDPROC, 0)
            # Восстанавливаем — нам нужен адрес
            old_proc = SetWindowLongPtr(hwnd, GWL_WNDPROC, old_proc)

            def wnd_proc(hw, msg, wparam, lparam):
                if msg == 0x0084:  # WM_NCHITTEST
                    result = CallWindowProc(old_proc, hw, msg, wparam, lparam)
                    if result == HTCLIENT:
                        # Получаем координаты мыши относительно окна
                        import ctypes.wintypes as wt
                        class RECT(ctypes.Structure):
                            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                        rect = RECT()
                        user32.GetWindowRect(hw, ctypes.byref(rect))

                        x = (lparam & 0xFFFF)
                        y = ((lparam >> 16) & 0xFFFF)
                        # Unsigned to signed
                        if x > 32767: x -= 65536
                        if y > 32767: y -= 65536

                        bw = BORDER_WIDTH
                        at_left = x - rect.left < bw
                        at_right = rect.right - x < bw
                        at_top = y - rect.top < bw
                        at_bottom = rect.bottom - y < bw

                        if at_top and at_left: return HTTOPLEFT
                        if at_top and at_right: return HTTOPRIGHT
                        if at_bottom and at_left: return HTBOTTOMLEFT
                        if at_bottom and at_right: return HTBOTTOMRIGHT
                        if at_left: return HTLEFT
                        if at_right: return HTRIGHT
                        if at_top: return HTTOP
                        if at_bottom: return HTBOTTOM
                    return result
                return CallWindowProc(old_proc, hw, msg, wparam, lparam)

            # Prevent garbage collection of the callback
            self._wnd_proc_ref = WNDPROC(wnd_proc)
            SetWindowLongPtr(hwnd, GWL_WNDPROC, ctypes.cast(self._wnd_proc_ref, ctypes.c_void_p).value)
        except Exception:
            pass  # На не-Windows — просто пропускаем

    # ── UI-обработчики ─────────────────────────────────────────────

    def _handle_motion(self, event, tree, tooltip):
        item = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if item and col and col != '#0':
            col_idx = int(col.replace('#', '')) - 1
            values = tree.item(item, 'values')
            if values and col_idx < len(values):
                text = str(values[col_idx])
                if len(text) > 20:
                    tooltip.showtip(text, event.x_root + 15, event.y_root + 15, item, col)
                else:
                    tooltip.hidetip()
            else:
                tooltip.hidetip()
        else:
            tooltip.hidetip()

    def on_double_click(self, event, tree):
        region = tree.identify_region(event.x, event.y)
        if region == "separator":
            col = tree.identify_column(event.x)
            col_idx = int(col.replace('#', '')) - 1

            header_text = tree.heading(col, 'text')
            max_len = len(header_text) * 10

            for item in tree.get_children(''):
                val = str(tree.item(item, 'values')[col_idx])
                width = len(val) * 7.5
                if width > max_len:
                    max_len = width

            tree.column(col, width=int(min(max_len + 30, 2000)))
            return "break"

    def show_context_menu(self, event, tree):
        item = tree.identify_row(event.y)
        if item:
            if item not in tree.selection():
                tree.selection_set(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def open_in_browser(self):
        for item in self.tree_left.selection():
            # Если выбран дочерний (интерфейс) — берём порт родителя
            parent = self.tree_left.parent(item)
            target = parent if parent else item
            port = self.tree_left.item(target, 'values')[0]
            webbrowser.open(f"http://localhost:{port}")

    # ── Сортировка ─────────────────────────────────────────────────

    def sort_data(self, col):
        if self.current_sort_col == col:
            self.current_sort_reverse = not self.current_sort_reverse
        else:
            self.current_sort_col = col
            self.current_sort_reverse = False
        self._sort_data()
        self._apply_diff(self.data_list)

    def _sort_data(self):
        col_map = {"Port": 0, "PID": 1, "Name": 2, "User": 3, "Path": 4, "Cmdline": 5}
        idx = col_map[self.current_sort_col]
        try:
            self.data_list.sort(key=lambda x: int(x[idx]), reverse=self.current_sort_reverse)
        except ValueError:
            self.data_list.sort(key=lambda x: str(x[idx]).lower(), reverse=self.current_sort_reverse)

    # ── Сбор данных (фоновый поток) ───────────────────────────────

    def _collect_data(self):
        try:
            connections = psutil.net_connections(kind='inet')
        except psutil.AccessDenied:
            connections = []

        listen_conns = [c for c in connections if c.status == psutil.CONN_LISTEN and c.pid]

        # Группировка по (port, pid), сбор всех адресов
        groups = {}
        for c in listen_conns:
            key = (c.laddr.port, c.pid)
            if key not in groups:
                groups[key] = []
            groups[key].append(c.laddr.ip)

        result = []
        for (port, pid), addresses in groups.items():
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

            result.append((port, pid, name, user, path, cmdline, tuple(sorted(set(addresses)))))
        return result

    # ── Diff-based обновление UI ──────────────────────────────────

    @staticmethod
    def _row_key(row):
        return f"{row[0]}|{row[1]}"

    def _apply_diff(self, sorted_data):
        """Обновляет только изменившиеся строки. Не трогает скролл, выделение, фокус."""
        new_keys = [self._row_key(d) for d in sorted_data]
        new_map = {self._row_key(d): d for d in sorted_data}

        old_children = list(self.tree_left.get_children(''))
        old_set = set(old_children)
        new_set = set(new_keys)

        # 1) Удаляем исчезнувшие строки (дети удалятся автоматически)
        to_delete = old_set - new_set
        for iid in to_delete:
            self.tree_left.delete(iid)
            self.tree_right.delete(iid)

        # 2) Обновляем существующие родительские строки
        for iid in old_children:
            if iid in to_delete:
                continue
            d = new_map[iid]
            left_vals = (str(d[0]), str(d[1]), str(d[2]))
            right_vals = (str(d[3]), str(d[4]), str(d[5]))
            if tuple(str(v) for v in self.tree_left.item(iid, 'values')) != left_vals:
                self.tree_left.item(iid, values=left_vals)
            if tuple(str(v) for v in self.tree_right.item(iid, 'values')) != right_vals:
                self.tree_right.item(iid, values=right_vals)
            # Обновляем дочерние (интерфейсы)
            self._update_children(iid, d[6])

        # 3) Добавляем новые строки
        to_add = new_set - old_set
        for iid in new_keys:
            if iid in to_add:
                d = new_map[iid]
                self.tree_left.insert("", tk.END, iid=iid, values=(d[0], d[1], d[2]))
                self.tree_right.insert("", tk.END, iid=iid, values=(d[3], d[4], d[5]))
                self._update_children(iid, d[6])

        # 4) Порядок строк (move только если реально сдвинулось)
        current_order = list(self.tree_left.get_children(''))
        for idx, key in enumerate(new_keys):
            if idx < len(current_order) and current_order[idx] == key:
                continue
            self.tree_left.move(key, '', idx)
            self.tree_right.move(key, '', idx)

    def _update_children(self, parent_iid, addresses):
        """Обновляет дочерние строки (интерфейсы) родительской записи."""
        old_child_ids = set(self.tree_left.get_children(parent_iid))
        new_child_ids = set()

        for addr in addresses:
            child_iid = f"{parent_iid}|{addr}"
            new_child_ids.add(child_iid)
            if child_iid not in old_child_ids:
                self.tree_left.insert(parent_iid, tk.END, iid=child_iid,
                                      values=(f"↳ {addr}", "", ""))
                self.tree_right.insert(parent_iid, tk.END, iid=child_iid,
                                       values=("", "", ""))

        # Удаляем интерфейсы, которых больше нет
        for old_id in old_child_ids - new_child_ids:
            self.tree_left.delete(old_id)
            self.tree_right.delete(old_id)

    # ── Действия ──────────────────────────────────────────────────

    def refresh_data(self):
        threading.Thread(target=self._refresh_data_bg, daemon=True).start()

    def _refresh_data_bg(self):
        new_data = self._collect_data()
        self.root.after(0, lambda: self._apply_data(new_data))

    def kill_selected(self):
        sel = self.tree_left.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Сначала выберите процесс(ы) в таблице!")
            return

        processes_to_kill = []
        seen_pids = set()
        for item in sel:
            # Дочерние строки (интерфейсы) пропускаем — убиваем по родителю
            parent = self.tree_left.parent(item)
            target = parent if parent else item
            values = self.tree_left.item(target, 'values')
            pid = values[1]
            if pid not in seen_pids:
                seen_pids.add(pid)
                processes_to_kill.append((values[0], values[1], values[2]))

        if len(processes_to_kill) == 1:
            msg = (f"Убить процесс {processes_to_kill[0][2]} "
                   f"(PID: {processes_to_kill[0][1]}), "
                   f"который держит порт {processes_to_kill[0][0]}?")
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
                if len(errors) > 5:
                    err_str += "\n..."
                messagebox.showerror("Результат",
                                     f"Убито: {killed} из {len(processes_to_kill)}\nОшибки:\n{err_str}")
            else:
                self.refresh_data()

    # ── Автообновление ────────────────────────────────────────────

    def _start_auto_refresh(self):
        self._refresh_lock = threading.Lock()
        self._auto_refresh_id = self.root.after(5000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        threading.Thread(target=self._collect_data_bg, daemon=True).start()

    def _collect_data_bg(self):
        if not self._refresh_lock.acquire(blocking=False):
            self.root.after(5000, self._auto_refresh_tick)
            return
        try:
            new_data = self._collect_data()
            self.root.after(0, lambda: self._apply_data(new_data))
        finally:
            self._refresh_lock.release()

    def _apply_data(self, new_data):
        # Если данные не изменились — не трогаем UI вообще (главная оптимизация)
        if new_data == self.data_list:
            self._auto_refresh_id = self.root.after(5000, self._auto_refresh_tick)
            return
        self.data_list = new_data
        self._sort_data()
        self._apply_diff(self.data_list)
        self._auto_refresh_id = self.root.after(5000, self._auto_refresh_tick)

    # ── Окно ──────────────────────────────────────────────────────

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.refresh_data()

    def quit_app(self):
        self.root.quit()
        os._exit(0)


# ── Tray-иконка (pystray) ────────────────────────────────────────

def create_tray_icon(app):
    img = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=(220, 50, 50))
    d.rectangle((18, 28, 46, 36), fill=(255, 255, 255))

    def on_open(icon, item):
        app.root.after(0, app.show_window)

    def on_exit(icon, item):
        icon.stop()
        app.root.after(0, app.quit_app)

    menu = pystray.Menu(
        pystray.MenuItem('Открыть Port Watcher', on_open, default=True),
        pystray.MenuItem('Обновить список', lambda icon, item: app.root.after(0, app.refresh_data)),
        pystray.MenuItem('Выход', on_exit)
    )

    icon = pystray.Icon("PortWatcher", img, "Port Watcher", menu)
    icon.run()


# ── TrayConsole ───────────────────────────────────────────────────

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
    # Автоматический запуск от имени Администратора
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                            " ".join(sys.argv), None, 1)
        sys.exit(0)

    app = PortWatcherApp()
    _setup_trayconsole(app.root, app)
    tray_thread = threading.Thread(target=create_tray_icon, args=(app,), daemon=True)
    tray_thread.start()
    app.root.mainloop()
