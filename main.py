"""Image Watermarking Tool.

A small tkinter + Pillow desktop app for stamping a watermark image onto a
batch of photos, with a live before/after preview so the effect of every
slider is visible before anything gets saved to disk.
"""

import os
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog

from PIL import Image, ImageTk

FONT_TITLE = ('Helvetica', 16, 'bold')
FONT_LABEL = ('Helvetica', 10)
FONT_SMALL = ('Helvetica', 9)

PREVIEW_MAX = 300  # max width/height (px) of each preview canvas

# Position presets: given the base and watermark sizes, return the top-left
# (x, y) corner the watermark should be pasted at.
POSITION_PRESETS = {
    'top-left':      lambda bw, bh, ww, wh: (0, 0),
    'top-center':    lambda bw, bh, ww, wh: ((bw - ww) // 2, 0),
    'top-right':     lambda bw, bh, ww, wh: (bw - ww, 0),
    'middle-left':   lambda bw, bh, ww, wh: (0, (bh - wh) // 2),
    'center':        lambda bw, bh, ww, wh: ((bw - ww) // 2, (bh - wh) // 2),
    'middle-right':  lambda bw, bh, ww, wh: (bw - ww, (bh - wh) // 2),
    'bottom-left':   lambda bw, bh, ww, wh: (0, bh - wh),
    'bottom-center': lambda bw, bh, ww, wh: ((bw - ww) // 2, bh - wh),
    'bottom-right':  lambda bw, bh, ww, wh: (bw - ww, bh - wh),
}

POSITION_LABELS = {
    'top-left': 'TL', 'top-center': 'TC', 'top-right': 'TR',
    'middle-left': 'ML', 'center': 'C', 'middle-right': 'MR',
    'bottom-left': 'BL', 'bottom-center': 'BC', 'bottom-right': 'BR',
}


def compute_watermark_box(watermark, max_width, max_height):
    """Resize a copy of the watermark to fit within (max_width, max_height),
    preserving aspect ratio, same as the original Image.thumbnail behaviour."""
    resized = watermark.copy()
    resized.thumbnail((max_width, max_height), Image.LANCZOS)
    return resized


def apply_opacity(watermark, opacity_percent):
    """Return a copy of the watermark (forced to RGBA) with its alpha
    channel scaled by opacity_percent (0-100)."""
    wm = watermark.convert('RGBA')
    r, g, b, a = wm.split()
    scale = opacity_percent / 100.0
    a = a.point(lambda v: int(v * scale))
    wm.putalpha(a)
    return wm


def compute_position(base_w, base_h, wm_w, wm_h, preset, offset_x_pct, offset_y_pct):
    """Work out the (x, y) paste position for a watermark on a base image,
    combining a named preset with a fine percentage-of-image offset."""
    base_x, base_y = POSITION_PRESETS[preset](base_w, base_h, wm_w, wm_h)
    x = base_x + int((offset_x_pct / 100.0) * base_w)
    y = base_y + int((offset_y_pct / 100.0) * base_h)
    return x, y


def paste_watermark_at(base_image, watermark, x, y):
    """Paste watermark onto a copy of base_image at (x, y) with correct
    alpha blending, and return the result.

    The historical bug here was calling `base.paste(watermark, (x, y))`
    with no mask, which makes Pillow overwrite the destination pixels
    (RGB and alpha) instead of blending. Passing the watermark itself as
    the third argument uses its alpha channel as the paste mask, which is
    what actually blends the watermark over the photo underneath.
    """
    result = base_image.convert('RGBA') if watermark.mode == 'RGBA' else base_image.copy()
    if watermark.mode == 'RGBA':
        result.paste(watermark, (x, y), watermark)
    else:
        result.paste(watermark, (x, y))
    return result


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        root.title('Image Watermarking Tool')
        root.geometry('980x620')
        root.minsize(860, 560)

        self.watermark_original = None   # raw uploaded watermark, Pillow Image
        self.photo_paths = ()            # tuple of source photo paths
        self._preview_after_id = None
        self._before_imgtk = None        # keep references so Tk doesn't GC them
        self._after_imgtk = None

        self.width_var = tk.IntVar(value=150)
        self.height_var = tk.IntVar(value=150)
        self.opacity_var = tk.IntVar(value=50)
        self.position_var = tk.StringVar(value='bottom-right')
        self.offset_x_var = tk.IntVar(value=0)
        self.offset_y_var = tk.IntVar(value=0)
        self.format_var = tk.StringVar(value='JPEG')
        self.location_var = tk.StringVar(value='')

        self.watermark_label_var = tk.StringVar(value='No watermark loaded')
        self.photos_label_var = tk.StringVar(value='No photos loaded')
        self.status_var = tk.StringVar(value='')

        self._build_layout()
        self._schedule_preview()

    # ---------------------------------------------------------------- layout

    def _build_layout(self):
        title = tk.Label(self.root, text='Image Watermarking Tool', font=FONT_TITLE)
        title.pack(pady=(10, 4))

        body = ttk.Frame(self.root)
        body.pack(fill='both', expand=True, padx=12, pady=8)

        controls = ttk.Frame(body)
        controls.pack(side='left', fill='y', padx=(0, 12))

        preview = ttk.Frame(body)
        preview.pack(side='left', fill='both', expand=True)

        self._build_controls(controls)
        self._build_preview(preview)

        status = tk.Label(self.root, textvariable=self.status_var, fg='#b00020',
                           font=FONT_LABEL, anchor='w')
        status.pack(fill='x', padx=12, pady=(0, 8))

    def _build_controls(self, parent):
        # Upload buttons
        upload_frame = ttk.LabelFrame(parent, text='1. Load images')
        upload_frame.pack(fill='x', pady=(0, 10))

        tk.Button(upload_frame, text='Upload Watermark', width=22,
                  command=self.upload_watermark).grid(row=0, column=0, padx=6, pady=6)
        tk.Label(upload_frame, textvariable=self.watermark_label_var,
                  font=FONT_SMALL, wraplength=180, justify='left').grid(
            row=0, column=1, sticky='w', padx=6)

        tk.Button(upload_frame, text='Upload Photos', width=22,
                  command=self.upload_photos).grid(row=1, column=0, padx=6, pady=6)
        tk.Label(upload_frame, textvariable=self.photos_label_var,
                  font=FONT_SMALL, wraplength=180, justify='left').grid(
            row=1, column=1, sticky='w', padx=6)

        # Size + opacity sliders
        adjust_frame = ttk.LabelFrame(parent, text='2. Size and opacity')
        adjust_frame.pack(fill='x', pady=(0, 10))

        self._add_slider(adjust_frame, 'Max width (px)', self.width_var, 10, 600, 0)
        self._add_slider(adjust_frame, 'Max height (px)', self.height_var, 10, 600, 1)
        self._add_slider(adjust_frame, 'Opacity (%)', self.opacity_var, 0, 100, 2)

        # Position controls
        pos_frame = ttk.LabelFrame(parent, text='3. Position')
        pos_frame.pack(fill='x', pady=(0, 10))

        grid_frame = ttk.Frame(pos_frame)
        grid_frame.pack(pady=6)
        order = ['top-left', 'top-center', 'top-right',
                 'middle-left', 'center', 'middle-right',
                 'bottom-left', 'bottom-center', 'bottom-right']
        for i, key in enumerate(order):
            r, c = divmod(i, 3)
            ttk.Radiobutton(grid_frame, text=POSITION_LABELS[key], value=key,
                             variable=self.position_var,
                             command=self._schedule_preview).grid(
                row=r, column=c, padx=3, pady=3, ipadx=4)

        offset_frame = ttk.Frame(pos_frame)
        offset_frame.pack(fill='x')
        self._add_slider(offset_frame, 'Fine X offset (%)', self.offset_x_var, -20, 20, 0)
        self._add_slider(offset_frame, 'Fine Y offset (%)', self.offset_y_var, -20, 20, 1)

        # Output controls
        out_frame = ttk.LabelFrame(parent, text='4. Output')
        out_frame.pack(fill='x', pady=(0, 10))

        tk.Label(out_frame, text='Format', font=FONT_LABEL).grid(row=0, column=0, sticky='w', padx=6, pady=4)
        format_menu = ttk.OptionMenu(out_frame, self.format_var, 'JPEG', 'JPEG', 'PNG')
        format_menu.grid(row=0, column=1, sticky='w', padx=6, pady=4)

        tk.Label(out_frame, text='Save folder\n(blank = next to source)', font=FONT_SMALL,
                  justify='left').grid(row=1, column=0, sticky='w', padx=6, pady=4)
        location_entry = tk.Entry(out_frame, textvariable=self.location_var, width=22)
        location_entry.grid(row=1, column=1, sticky='w', padx=6, pady=4)
        tk.Button(out_frame, text='Browse', command=self._browse_folder, width=8).grid(
            row=1, column=2, padx=4)

        tk.Button(parent, text='Apply Watermark & Save All', width=28,
                  bg='#2e7d32', fg='white', command=self.apply_and_save).pack(pady=(4, 0))

    def _add_slider(self, parent, label, var, lo, hi, row):
        tk.Label(parent, text=label, font=FONT_LABEL).grid(
            row=row, column=0, sticky='w', padx=6, pady=4)
        scale = ttk.Scale(parent, from_=lo, to=hi, orient='horizontal',
                           variable=var, command=lambda _v: self._schedule_preview())
        scale.grid(row=row, column=1, sticky='we', padx=6, pady=4)
        value_label = tk.Label(parent, width=4, font=FONT_SMALL)
        value_label.grid(row=row, column=2, padx=(0, 6))

        def refresh(*_):
            value_label.config(text=str(int(var.get())))
        var.trace_add('write', refresh)
        refresh()
        parent.grid_columnconfigure(1, weight=1)

    def _build_preview(self, parent):
        label = tk.Label(parent, text='Live preview (before / after)', font=FONT_LABEL)
        label.pack(anchor='w')

        canvases = ttk.Frame(parent)
        canvases.pack(fill='both', expand=True, pady=6)

        before_box = ttk.Frame(canvases)
        before_box.pack(side='left', expand=True, padx=6)
        tk.Label(before_box, text='Before', font=FONT_LABEL).pack()
        self.before_canvas = tk.Canvas(before_box, width=PREVIEW_MAX, height=PREVIEW_MAX,
                                        bg='#dddddd', highlightthickness=1,
                                        highlightbackground='#999999')
        self.before_canvas.pack()

        after_box = ttk.Frame(canvases)
        after_box.pack(side='left', expand=True, padx=6)
        tk.Label(after_box, text='After', font=FONT_LABEL).pack()
        self.after_canvas = tk.Canvas(after_box, width=PREVIEW_MAX, height=PREVIEW_MAX,
                                       bg='#dddddd', highlightthickness=1,
                                       highlightbackground='#999999')
        self.after_canvas.pack()

    # ------------------------------------------------------------- actions

    def _browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.location_var.set(folder)

    def upload_watermark(self):
        path = filedialog.askopenfilename(filetypes=[
            ('PNG files', '*.png'), ('JPEG files', '*.jpg;*.jpeg')])
        if not path:
            return
        try:
            self.watermark_original = Image.open(path)
            self.watermark_original.load()
        except Exception:
            self.status_var.set('Could not open watermark image.')
            return
        self.watermark_label_var.set(Path(path).name)
        self.status_var.set('')
        self._schedule_preview()

    def upload_photos(self):
        paths = filedialog.askopenfilenames(filetypes=[
            ('Image files', '*.jpg;*.jpeg;*.png')])
        if not paths:
            return
        self.photo_paths = tuple(paths)
        self.photos_label_var.set(f'{len(paths)} photo(s) selected')
        self.status_var.set('')
        self._schedule_preview()

    def _schedule_preview(self, *_):
        # Debounce slider drags so we don't re-render on every pixel of
        # motion; 60ms feels instant but avoids redundant work.
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(60, self._render_preview)

    def _render_preview(self):
        self._preview_after_id = None
        self.before_canvas.delete('all')
        self.after_canvas.delete('all')

        if not self.photo_paths:
            self._canvas_message(self.before_canvas, 'Upload a photo to preview')
            self._canvas_message(self.after_canvas, 'Upload a photo to preview')
            return

        try:
            base = Image.open(self.photo_paths[0])
            base.load()
        except Exception:
            self._canvas_message(self.before_canvas, 'Could not open photo')
            self._canvas_message(self.after_canvas, 'Could not open photo')
            return

        base_preview = base.copy()
        base_preview.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
        scale = base_preview.width / base.width if base.width else 1.0

        self._before_imgtk = ImageTk.PhotoImage(base_preview.convert('RGB'))
        self._draw_centered(self.before_canvas, self._before_imgtk)

        if self.watermark_original is None:
            self._canvas_message(self.after_canvas, 'Upload a watermark to preview')
            return

        max_w = max(1, int(self.width_var.get() * scale))
        max_h = max(1, int(self.height_var.get() * scale))
        wm_preview = compute_watermark_box(self.watermark_original, max_w, max_h)
        wm_preview = apply_opacity(wm_preview, self.opacity_var.get())

        x, y = compute_position(base_preview.width, base_preview.height,
                                 wm_preview.width, wm_preview.height,
                                 self.position_var.get(),
                                 self.offset_x_var.get(), self.offset_y_var.get())

        composited = paste_watermark_at(base_preview, wm_preview, x, y)
        self._after_imgtk = ImageTk.PhotoImage(composited.convert('RGB'))
        self._draw_centered(self.after_canvas, self._after_imgtk)

    def _canvas_message(self, canvas, text):
        canvas.create_text(PREVIEW_MAX // 2, PREVIEW_MAX // 2, text=text,
                            fill='#555555', font=FONT_LABEL, width=PREVIEW_MAX - 20)

    def _draw_centered(self, canvas, imgtk):
        canvas.create_image(PREVIEW_MAX // 2, PREVIEW_MAX // 2, image=imgtk)

    def apply_and_save(self):
        if self.watermark_original is None:
            self.status_var.set('Upload a watermark first.')
            return
        if not self.photo_paths:
            self.status_var.set('Upload at least one photo first.')
            return

        file_format = self.format_var.get()
        location = self.location_var.get().strip() or None

        saved = 0
        for path in self.photo_paths:
            try:
                base = Image.open(path)
                base.load()
            except Exception:
                continue

            wm = compute_watermark_box(self.watermark_original,
                                        self.width_var.get(), self.height_var.get())
            wm = apply_opacity(wm, self.opacity_var.get())
            x, y = compute_position(base.width, base.height, wm.width, wm.height,
                                     self.position_var.get(),
                                     self.offset_x_var.get(), self.offset_y_var.get())
            result = paste_watermark_at(base, wm, x, y)
            save_watermarked_file(result, path, location, file_format)
            saved += 1

        self.status_var.set(f'Saved {saved} watermarked photo(s).')


def save_watermarked_file(image, source_path, location, file_format):
    """Save a watermarked Pillow image next to its source (in a
    'watermarked/' subfolder) or in a custom location, using pathlib so the
    path handling works the same on Windows as on Linux/macOS."""
    source = Path(source_path)
    out_dir = Path(location) if location else source.parent / 'watermarked'
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = 'png' if image.mode == 'RGBA' else file_format.lower()
    out_path = out_dir / f'{source.stem}_watermarked.{suffix}'

    if image.mode == 'RGBA':
        # JPEG has no alpha channel, so force PNG whenever the composited
        # result carries transparency, regardless of the format dropdown.
        image.save(out_path, 'PNG')
    else:
        image.save(out_path, file_format)


def main():
    root = tk.Tk()
    WatermarkApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
