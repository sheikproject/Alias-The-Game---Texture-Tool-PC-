import os
import io
import re
import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel
from PIL import Image, ImageTk

class AliasTextureTool:
    def __init__(self, root):
        self.root = root
        self.root.title("Alias The Game - Texture Tool (PC)")
        self.root.geometry("1000x670")
        
        self.wld_path = ""
        self.textures = [] 
        self.wld_bytes = None
        self.original_wld_bytes = None
        self.preview_img = None
        self.full_img_refs = [] 
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- UI LAYOUT ---
        frame_top = tk.Frame(root)
        frame_top.pack(pady=10, fill=tk.X)
        tk.Label(frame_top, text=".wld File:").pack(side=tk.LEFT, padx=5)
        self.path_entry = tk.Entry(frame_top, width=80)
        self.path_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(frame_top, text="Browse", command=self.load_wld_btn).pack(side=tk.LEFT)

        paned = tk.PanedWindow(root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10)

        list_frame = tk.Frame(paned)
        tk.Label(list_frame, text="Texture List (Right-click to Change/Restore/Extract)").pack()
        self.listbox = tk.Listbox(list_frame, font=("Segoe UI", 10), selectmode=tk.SINGLE)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.on_select_change)
        
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Change Texture", command=self.swap_selected)
        self.menu.add_command(label="Restore Original", command=self.cancel_swap)
        self.menu.add_separator()
        self.menu.add_command(label="Extract Selected", command=self.extract_selected)
        self.listbox.bind("<Button-3>", self.show_context_menu)
        
        paned.add(list_frame, width=400)

        preview_frame = tk.Frame(paned, bg="#1e1e1e")
        self.img_label = tk.Label(preview_frame, text="Select a texture", fg="gray", bg="#1e1e1e")
        self.img_label.pack(fill=tk.BOTH, expand=True)
        self.info_label = tk.Label(preview_frame, text="", bg="#1e1e1e", fg="white", justify=tk.LEFT)
        self.info_label.pack(pady=10)
        paned.add(preview_frame)

        frame_bottom = tk.Frame(root)
        frame_bottom.pack(pady=15)
        tk.Button(frame_bottom, text="Extract All", command=self.extract_all, width=15).pack(side=tk.LEFT, padx=5)
        self.save_btn = tk.Button(frame_bottom, text="Save File", command=self.save_wld, 
                                  width=25, bg="#1976d2", fg="white", font=("Arial", 10, "bold"))
        self.save_btn.pack(side=tk.LEFT, padx=10)

    def calculate_dds_size(self, data, offset):
        try:
            h = int.from_bytes(data[offset+12:offset+16], 'little')
            w = int.from_bytes(data[offset+16:offset+20], 'little')
            fourcc = data[offset+84:offset+88].decode('ascii', 'ignore').strip('\x00')
            mips = int.from_bytes(data[offset+28:offset+32], 'little')
            block_size = 8 if fourcc == "DXT1" else 16
            size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block_size
            if mips > 1:
                cw, ch = w, h
                for _ in range(mips - 1):
                    cw, ch = max(1, cw // 2), max(1, ch // 2)
                    size += max(1, (cw + 3) // 4) * max(1, (ch + 3) // 4) * block_size
            return size + 128
        except: return 0

    def check_unsaved(self):
        """Returns True to save, False to discard, None to cancel close."""
        if self.textures and any(t['modified'] for t in self.textures):
            return messagebox.askyesnocancel("Unsaved Changes", "You have modified textures. Save before closing?")
        return False

    def on_closing(self):
        choice = self.check_unsaved()
        if choice is True:
            self.save_wld()
            self.root.destroy()
        elif choice is False:
            self.root.destroy()

    def show_context_menu(self, event):
        idx = self.listbox.nearest(event.y)
        if idx >= 0:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(idx)
            self.on_select_change(None)
            state = tk.NORMAL if self.textures[idx]['modified'] else tk.DISABLED
            self.menu.entryconfigure(1, state=state)
            self.menu.post(event.x_root, event.y_root)

    def load_wld_btn(self):
        path = filedialog.askopenfilename(filetypes=[("WLD Files", "*.wld")])
        if path: self.perform_load(path)

    def perform_load(self, path):
        self.wld_path = path
        self.path_entry.delete(0, tk.END)
        self.path_entry.insert(0, path)
        with open(path, "rb") as f:
            raw = f.read()
            self.wld_bytes, self.original_wld_bytes = bytearray(raw), bytearray(raw)
        self.parse_wld()

    def parse_wld(self):
        self.listbox.delete(0, tk.END)
        self.textures = []
        data = self.wld_bytes
        names = [n.decode('ascii') for n in re.findall(b'([a-zA-Z0-9_]+\\.tex)', data[:0x4000])]
        offsets = [m.start() for m in re.finditer(b'DDS ', data)]
        for i, off in enumerate(offsets):
            w = int.from_bytes(data[off+16:off+20], 'little')
            h = int.from_bytes(data[off+12:off+16], 'little')
            mips = int.from_bytes(data[off+28:off+32], 'little')
            fcc = data[off+84:off+88].decode('ascii', 'ignore').strip('\x00') or "RGBA"
            sz = self.calculate_dds_size(data, off)
            name = names[i] if i < len(names) else f"tex_{i:02d}.tex"
            self.textures.append({"offset": off, "size": sz, "name": name, "res": f"{w}x{h}", 
                                  "fmt": fcc, "mips": mips, "alpha": "Yes" if "DXT" in fcc and fcc != "DXT1" else "No", "modified": False})
            self.listbox.insert(tk.END, f"{i:02d} | {name} | {fcc} | {w}x{h}")

    def on_select_change(self, event):
        sel = self.listbox.curselection()
        if not sel: return
        t = self.textures[sel[0]]
        self.info_label.config(text=f"FILE: {t['name']} | FORMAT: {t['fmt']}\nRES: {t['res']} | HAS ALPHA: {t['alpha']} | MIPS: {t['mips']}\nOFFSET: {hex(t['offset'])}")
        try:
            img = Image.open(io.BytesIO(self.wld_bytes[t['offset'] : t['offset'] + t['size']]))
            img.thumbnail((400, 400)); self.preview_img = ImageTk.PhotoImage(img)
            self.img_label.config(image=self.preview_img, text="")
        except: self.img_label.config(image="", text="Preview Not Available")

    def swap_selected(self):
        idx = self.listbox.curselection()[0]; t = self.textures[idx]
        path = filedialog.askopenfilename(filetypes=[("DDS Files", "*.dds")])
        if path:
            with open(path, "rb") as f: d = f.read()
            if len(d) != t['size']:
                messagebox.showerror("Size Mismatch", f"Required: {t['size']} bytes\nSelected: {len(d)} bytes")
                return
            self.wld_bytes[t['offset']:t['offset']+t['size']] = d
            t['modified'] = True
            self.listbox.delete(idx); self.listbox.insert(idx, f"{idx:02d} | [MODIFIED] {t['name']} | {t['fmt']} | {t['res']}")
            self.listbox.selection_set(idx); self.on_select_change(None)

    def cancel_swap(self):
        idx = self.listbox.curselection()[0]; t = self.textures[idx]
        self.wld_bytes[t['offset']:t['offset']+t['size']] = self.original_wld_bytes[t['offset']:t['offset']+t['size']]
        t['modified'] = False
        self.listbox.delete(idx); self.listbox.insert(idx, f"{idx:02d} | {t['name']} | {t['fmt']} | {t['res']}")
        self.listbox.selection_set(idx); self.on_select_change(None)

    def save_wld(self):
        path = filedialog.asksaveasfilename(defaultextension=".wld", initialfile="mod_" + os.path.basename(self.wld_path))
        if path:
            with open(path, "wb") as f: f.write(self.wld_bytes)
            messagebox.showinfo("Success", "Saved!"); self.perform_load(path)

    def extract_selected(self):
        t = self.textures[self.listbox.curselection()[0]]
        p = filedialog.asksaveasfilename(defaultextension=".dds", initialfile=t['name'].replace('.tex', '.dds'))
        if p:
            with open(p, "wb") as f: f.write(self.wld_bytes[t['offset']:t['offset']+t['size']])

    def extract_all(self):
        fld = filedialog.askdirectory()
        if fld:
            for t in self.textures:
                with open(os.path.join(fld, t['name'].replace('.tex', '.dds')), "wb") as f:
                    f.write(self.wld_bytes[t['offset']:t['offset']+t['size']])
            messagebox.showinfo("Success", "Done.")

if __name__ == "__main__":
    root = tk.Tk(); app = AliasTextureTool(root); root.mainloop()
