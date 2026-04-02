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
        tk.Label(frame_top, text="File:").pack(side=tk.LEFT, padx=5)
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
        # Update filetypes to allow selecting the _p payload files
        path = filedialog.askopenfilename(filetypes=[("Alias Files", "*.wld *_p.cat *.all"), ("WLD Files", "*.wld"), ("CAT Files", "*_p.cat"), ("ALL Files", "*.all")])
        if path: self.perform_load(path)

    def perform_load(self, path):
        self.wld_path = path
        self.path_entry.delete(0, tk.END)
        self.path_entry.insert(0, path)
        
        with open(path, "rb") as f:
            raw = f.read()
            self.wld_bytes, self.original_wld_bytes = bytearray(raw), bytearray(raw)

        path_lower = path.lower()
        if path_lower.endswith('.all'):
            self.parse_all_file()
        elif "_p.cat" in path_lower or "_s.cat" in path_lower:
            # Handle CAT pairs (need to load _s.cat for names)
            s_path = path.replace('_p.cat', '_s.cat') if '_p.cat' in path_lower else path
            if os.path.exists(s_path):
                with open(s_path, "rb") as f: self.s_bytes = f.read()
            self.parse_cat_files()
        else:
            self.parse_wld()

    def parse_all_file(self):
        self.listbox.delete(0, tk.END)
        self.textures = []
        
        # 1. Find the FIRST DDS header to determine where the name table ends
        all_dds_markers = [m.start() for m in re.finditer(b'DDS ', self.wld_bytes)]
        if not all_dds_markers:
            messagebox.showerror("Error", "No DDS textures found in this .all file.")
            return
            
        first_dds_offset = all_dds_markers[0]

        # 2. Extract names only from the header area (before the first DDS)
        header_area = self.wld_bytes[:first_dds_offset]
        # This pattern looks for .tex filenames
        name_pattern = re.compile(b'([a-zA-Z0-9_-]+\\.[tT][eE][xX])')
        names = [n.decode('ascii', 'ignore') for n in name_pattern.findall(header_area)]
        
        print(f"Header ends at {hex(first_dds_offset)}. Found {len(names)} names.")

        # 3. Process each DDS found in the file
        for i, m_off in enumerate(all_dds_markers):
            try:
                # Read standard DDS Header info
                h = int.from_bytes(self.wld_bytes[m_off+12 : m_off+16], 'little')
                w = int.from_bytes(self.wld_bytes[m_off+16 : m_off+20], 'little')
                
                # Format (FourCC) at offset 84
                fmt_bytes = self.wld_bytes[m_off+84 : m_off+88]
                fmt = fmt_bytes.decode('ascii', 'ignore').strip('\x00')
                if not fmt: fmt = "RGBA"

                # Calculate size: distance to next DDS or end of file
                if i + 1 < len(all_dds_markers):
                    size = all_dds_markers[i+1] - m_off
                else:
                    size = len(self.wld_bytes) - m_off
                
                # Match name from the list we scanned
                # We use the index to match the name to the texture
                tex_name = names[i] if i < len(names) else f"unnamed_{i:02d}.tex"

                self.textures.append({
                    "offset": m_off,
                    "size": size,
                    "name": tex_name,
                    "res": f"{w}x{h}",
                    "fmt": fmt,
                    "mips": int.from_bytes(self.wld_bytes[m_off+28:m_off+32], 'little'),
                    "alpha": "No" if "1" in fmt else "Yes",
                    "modified": False
                })
                
                self.listbox.insert(tk.END, f"{i:02d} | {tex_name} | {fmt} | {w}x{h}")
            except Exception as e:
                print(f"Error parsing DDS at {hex(m_off)}: {e}")

    def parse_cat_files(self):
        self.listbox.delete(0, tk.END)
        self.textures = []
        
        # 1. Pull texture names from the _s.cat file
        # Finds all strings ending in .tex, .TEX, etc.
        name_pattern = re.compile(b'([a-zA-Z0-9_-]+\\.[tT][eE][xX])')
        names = [n.decode('ascii') for n in name_pattern.findall(self.s_bytes)]
        
        # 2. Find all 'DDS ' headers in the _p.cat file
        # These are standard DDS files, so we use standard DDS offsets
        dds_markers = [m.start() for m in re.finditer(b'DDS ', self.wld_bytes)]
        
        print(f"Found {len(names)} names and {len(dds_markers)} textures.")

        for i, m_off in enumerate(dds_markers):
            try:
                # --- STANDARD DDS HEADER OFFSETS ---
                # Height is at offset 12, Width is at offset 16
                h = int.from_bytes(self.wld_bytes[m_off+12:m_off+16], 'little')
                w = int.from_bytes(self.wld_bytes[m_off+16:m_off+20], 'little')
                
                # Mipmap count is at offset 28
                mips = int.from_bytes(self.wld_bytes[m_off+28:m_off+32], 'little')
                
                # Format (FourCC) is at offset 84 (e.g., 'DXT1', 'DXT3', 'DXT5')
                fmt_bytes = self.wld_bytes[m_off+84:m_off+88]
                fmt = fmt_bytes.decode('ascii', 'ignore').strip('\x00')
                
                # If FourCC is empty, it's usually an uncompressed format (RGBA)
                if not fmt:
                    fmt = "RGBA"

                # Calculate size: distance to the next 'DDS ' marker or end of file
                if i + 1 < len(dds_markers):
                    size = dds_markers[i+1] - m_off
                else:
                    size = len(self.wld_bytes) - m_off

                # Link to the name found in the _s.cat file
                tex_name = names[i] if i < len(names) else f"unnamed_{i:02d}.tex"
                
                self.textures.append({
                    "offset": m_off,
                    "size": size,
                    "name": tex_name,
                    "res": f"{w}x{h}",
                    "fmt": fmt,
                    "mips": mips,
                    "alpha": "Yes" if "1" not in fmt else "No",
                    "modified": False
                })
                
                self.listbox.insert(tk.END, f"{i:02d} | {tex_name} | {fmt} | {w}x{h}")
                
            except Exception as e:
                print(f"Skipping index {i} due to error: {e}")

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
        
        # Update information labels
        self.info_label.config(text=f"FILE: {t['name']} | FORMAT: {t['fmt']}\nRES: {t['res']} | HAS ALPHA: {t['alpha']} | MIPS: {t['mips']}\nOFFSET: {hex(t['offset'])}")
        
        # Get raw DDS bytes from memory
        dds_data = self.wld_bytes[t['offset'] : t['offset'] + t['size']]
        
        try:
            # 1. Standard loading (Works for DXT1, DXT5, etc.)
            img = Image.open(io.BytesIO(dds_data))
            img.thumbnail((400, 400))
            self.preview_img = ImageTk.PhotoImage(img)
            self.img_label.config(image=self.preview_img, text="")
            
        except Exception:
            # 2. RGBA/BGRA Fallback (For uncompressed textures)
            if t['fmt'] == "RGBA":
                try:
                    res = t['res'].split('x')
                    w, h = int(res[0]), int(res[1])
                    
                    # Standard DDS header is 128 bytes; raw pixels start after it.
                    pixel_data = dds_data[128 : 128 + (w * h * 4)]
                    
                    # Create image using BGRA decoder (Matches Alias PC's uncompressed format)
                    img = Image.frombytes("RGBA", (w, h), pixel_data, "raw", "BGRA")
                    
                    img.thumbnail((400, 400))
                    self.preview_img = ImageTk.PhotoImage(img)
                    self.img_label.config(image=self.preview_img, text="")
                except Exception:
                    self.img_label.config(image="", text="Preview Not Available")
            else:
                self.img_label.config(image="", text="Format not previewable")

    def swap_selected(self):
        idx_list = self.listbox.curselection()
        if not idx_list: return
        idx = idx_list[0]
        t = self.textures[idx]
        
        path = filedialog.askopenfilename(filetypes=[("DDS Files", "*.dds")])
        if path:
            with open(path, "rb") as f:
                new_data = f.read()
            
            new_size = len(new_data)
            
            if new_size > t['size']:
                messagebox.showerror("Size Error", f"The new file is too large!\nMaximum allowed: {t['size']} bytes\nSelected: {new_size} bytes")
                return
            
            # --- UPDATE HEADER INFO (Mips & Alpha) ---
            # Get Mipmap count from the new file (Offset 28)
            new_mips = int.from_bytes(new_data[28:32], 'little')
            
            # Get FourCC from the new file (Offset 84) to determine Alpha
            new_fcc = new_data[84:88].decode('ascii', 'ignore').strip('\x00') or "RGBA"
            new_alpha = "Yes" if "1" not in new_fcc else "No"

            # If the new file is smaller, pad it with null bytes to match the original slot size
            if new_size < t['size']:
                padding_needed = t['size'] - new_size
                new_data = new_data + (b'\x00' * padding_needed)

            # Apply the data to the memory buffer
            self.wld_bytes[t['offset'] : t['offset'] + t['size']] = new_data
            
            # Update the local texture list data so the UI reflects the change
            t['modified'] = True
            t['mips'] = new_mips
            t['fmt'] = new_fcc
            t['alpha'] = new_alpha
            
            self.listbox.delete(idx)
            self.listbox.insert(idx, f"{idx:02d} | [MODIFIED] {t['name']} | {t['fmt']} | {t['res']}")
            self.listbox.selection_set(idx)
            self.on_select_change(None)

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
