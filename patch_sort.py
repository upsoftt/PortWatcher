import re

import os
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'port_watcher.py')
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add instance variables to store current sort state
init_old = '''        self.tree.column("Cmdline", width=400, minwidth=200)'''
init_new = '''        self.tree.column("Cmdline", width=400, minwidth=200)\n        \n        self.current_sort_col = "Port"\n        self.current_sort_reverse = False'''
content = content.replace(init_old, init_new)

# Update sort_column to save state
sort_old = '''    def sort_column(self, col, reverse):
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]'''
sort_new = '''    def sort_column(self, col, reverse):
        self.current_sort_col = col
        self.current_sort_reverse = reverse
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]'''
content = content.replace(sort_old, sort_new)

# Update refresh_data to re-apply sort
refresh_old = '''            self.tree.insert("", tk.END, values=(port, pid, name, user, path, cmdline))'''
refresh_new = '''            self.tree.insert("", tk.END, values=(port, pid, name, user, path, cmdline))\n            \n        if hasattr(self, 'current_sort_col') and self.current_sort_col:\n            self.sort_column(self.current_sort_col, self.current_sort_reverse)\n            # We need to invert back the reverse flag because sort_column toggles it for the NEXT click\n            self.current_sort_reverse = not self.current_sort_reverse\n            self.tree.heading(self.current_sort_col, command=lambda c=self.current_sort_col, r=not self.current_sort_reverse: self.sort_column(c, r))'''
content = content.replace(refresh_old, refresh_new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Patched sorting logic')
