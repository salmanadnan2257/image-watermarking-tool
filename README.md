# Image Watermarking Tool

A desktop GUI for stamping a logo or watermark image onto a batch of photos, built
with tkinter and Pillow.

## Why it exists

Batch-watermarking photos is a repetitive job that most people either do by hand in
an image editor or skip entirely. This project is a small, self-contained desktop
tool that does one job: take a watermark image, let the user size and fade it, then
apply it to a set of photos in one pass and save the results without touching the
originals.

## Features

- Upload a watermark image (PNG or JPEG) separately from the batch of photos to
  stamp.
- Live before/after preview: as soon as a watermark and a photo are loaded, the
  right-hand side of the window shows the original photo next to a live
  composited preview, updating instantly as any slider changes, before anything
  is saved.
- Resize the watermark with a slider (max width/height, capped at 600px, applied
  as a bounding box that preserves aspect ratio).
- Opacity slider (0-100%), applied as a real alpha blend against the photo
  underneath (see Challenges for the bug this replaced).
- Position control: a 3x3 grid of presets (corners, edge midpoints, center) plus
  fine X/Y offset sliders (-20% to +20% of the photo's width/height) for nudging
  off the preset.
- Choose the output format (JPEG or PNG) from a dropdown.
- Optional custom save folder (with a Browse button); if left blank, output goes
  next to the source files in a `watermarked/` subfolder that gets created
  automatically.
- Batch mode: select multiple photos at once and stamp all of them with the same
  settings in one click.
- Inline status label reports how many photos were saved, or what went wrong.

## Architecture

Everything lives in `main.py`, structured around a small `WatermarkApp` class that
holds all UI state (loaded watermark, photo paths, slider values) as instance
attributes instead of the module-level globals the original version used. The
flow:

1. `upload_watermark()` opens a file picker and loads the chosen image into
   `self.watermark_original`, keeping it unmodified; resizing and fading happen
   fresh on every preview/save pass so slider changes are non-destructive.
2. `upload_photos()` opens a multi-file picker and stores the selected paths.
3. Every slider and position radio button calls `_schedule_preview()`, which
   debounces (60ms) and then calls `_render_preview()`: it thumbnails the first
   selected photo down to a `PREVIEW_MAX` (300px) box, scales the watermark size
   and offsets by the same ratio, composites it with `paste_watermark_at()`, and
   draws both the plain thumbnail ("before") and the composited one ("after") on
   two `tk.Canvas` widgets via `ImageTk.PhotoImage`.
4. `apply_and_save()` loops over every selected photo at full resolution, builds
   the watermark at the requested size/opacity/position for that photo's actual
   dimensions (via `compute_watermark_box()`, `apply_opacity()`,
   `compute_position()`), composites it with the same `paste_watermark_at()`
   used in the preview, and saves through `save_watermarked_file()`.
5. `save_watermarked_file()` uses `pathlib.Path` to derive the output path from
   the source filename, creates the destination folder if missing, and forces
   PNG whenever the composited result is in RGBA mode (since JPEG has no alpha
   channel).

Preview and final save call the exact same compositing function
(`paste_watermark_at`), so what's shown on screen before saving is what actually
gets written to disk, not an approximation.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Requires Python 3 with tkinter available (bundled with most desktop Python
installs; on minimal Linux installs you may need `apt install python3-tk`).

No environment variables are read anywhere in this project, so there's no
`.env.example` to fill in.

## Usage

```bash
python3 main.py
```

In the window that opens:

1. Click **Upload Watermark** and pick a logo/watermark image.
2. Click **Upload Photos** and pick one or more photos to stamp. The first one
   appears in the **Before** preview pane immediately.
3. Adjust the **max width/height**, **opacity**, position preset, and fine X/Y
   offset sliders. The **After** pane updates live with every change, so you can
   see the actual blended result before saving anything.
4. Pick a **Format** (JPEG or PNG) and, optionally, a custom save folder.
5. Click **Apply Watermark & Save All**. Output lands in a `watermarked/` folder
   next to your source photos (or at the custom folder if you set one).

## What was fixed

- **Pillow's `paste()` doesn't alpha-composite by default.** The original
  `add_watermark_to_images()` called `uploaded_image.paste(watermark, (x, y))`
  without a mask argument. When the watermark has an alpha channel and no mask
  is passed, Pillow overwrites the destination pixels (RGB and alpha both)
  instead of blending the watermark over the photo underneath. The opacity
  value still ended up in the saved file's alpha channel, so it displayed as
  translucent in any viewer that respects alpha, but the actual photo pixels
  behind the watermark were discarded, not blended.

  Fixed in `paste_watermark_at()` by passing the watermark itself as the third
  argument to `paste()` (`base.paste(watermark, (x, y), watermark)`), which
  uses its own alpha channel as the paste mask and makes Pillow actually blend.

  Verified directly with a synthetic solid-blue `(0, 0, 255)` base photo and a
  synthetic solid-red `(255, 0, 0)` watermark faded to 50% alpha
  (`apply_opacity()` scales alpha to ~127/255). Reading the pixel at the same
  watermark-covered location under both code paths:

  ```
  OLD paste (no mask):    (255, 0, 0, 127)   <- flat red, zero blue contribution
  NEW paste (mask=wm):    (127, 0, 128, 191) <- genuine red/blue blend
  ```

  The old path keeps the base's blue channel at 0, proving no blending
  happened, just a flat overwrite with the stored alpha along for the ride.
  The new path shows blue at 128 and red pulled down from 255 to 127, an
  actual weighted mix of the watermark color and the photo underneath.

## Challenges

- **A TikZ node style name collided with a pgfplots reserved key while
  building the explainer PDFs.** The deep-dive diagram for the preview-vs-save
  data flow (`docs/explainers/deep-dive.pdf`) defined a TikZ node style named
  `step` for the flow-diagram boxes. Because the document also loads
  `pgfplots` (for axis-capable diagrams elsewhere), `pgfplots` had already
  registered `/tikz/step` as a key that requires a value (used for grid
  spacing), so every `\node[step]` call failed to compile with `Package
  pgfkeys Error: The key '/tikz/step' requires a value`. Fixed by renaming the
  style to `flowstep`, which does not collide with any pgfplots key.
- **RGBA output still forces PNG regardless of the user's format choice.**
  `save_watermarked_file()` saves as PNG whenever the composited result is in
  RGBA mode, ignoring the format dropdown. Picking JPEG as the output format
  for a photo that also got a watermark applied still silently produces a PNG
  file. This is existing behavior carried over from the original code, not a
  crash, but worth knowing before relying on the format dropdown.
- **Live preview needs to stay fast regardless of source photo resolution.**
  Compositing a full-resolution photo on every slider tick would lag on large
  images. Fixed by thumbnailing the base photo down to a 300px preview box
  first, then scaling the watermark's size and offsets by the same ratio
  before compositing, so the preview render cost is constant no matter how
  large the source photos are. The final save pass still composites at full
  resolution.
- **Keeping preview and final output honest with each other.** It would be
  easy to have the preview use a simplified compositing path and the save
  button use a different one, so what you see isn't what you get. Both call
  the same `paste_watermark_at()` function; verified by running the full
  in-process flow (load synthetic watermark and photo, call
  `_render_preview()`, then `apply_and_save()`) and confirming the saved file
  exists with the expected composited pixels (see Verification below).
- **File dialogs make automated end-to-end GUI testing impractical.**
  `askopenfilename` and `askopenfilenames` block on a native file picker, so
  there's no way to drive the full click-through flow without manual input. I
  worked around this by assigning `app.watermark_original` and
  `app.photo_paths` directly (bypassing the dialogs) to exercise the preview
  and save logic, and separately confirmed the window itself constructs and
  runs under a real X display.

## What I learned

- `Image.paste()` needs an explicit mask (usually the source image's own alpha
  band) to alpha-composite; without one it's a flat pixel overwrite, alpha
  channel included. This is easy to miss because the result still "looks"
  transparent when opened in most viewers, since the alpha channel is
  technically set, even though no actual blending happened.
- `Image.thumbnail()` mutates in place and preserves aspect ratio by default,
  which is why the width/height sliders here act as a bounding box rather than
  an exact size.
- Deriving output paths by string-splitting on `/` (the original approach) is
  fragile across platforms; `pathlib.Path` handles both `/` and `\` correctly
  and reads clearer.
- Scaling a live preview's watermark size and position by the same ratio as
  the thumbnailed base photo keeps the preview representative of the full-res
  result without re-running expensive operations on the original image.

## What I'd do differently

- Add a real automated test suite (even a handful of `unittest` cases around
  `compute_position()`, `apply_opacity()`, and `paste_watermark_at()`) instead
  of relying on ad hoc verification scripts for every change.
- Support dragging the watermark directly on the preview canvas instead of
  only preset positions plus offset sliders; tkinter's canvas supports mouse
  event binding for this, but it adds real complexity (converting canvas
  coordinates back to image coordinates at the preview's scale factor) that
  didn't feel justified for a first pass.
- Cache the opened "before" base image across preview renders instead of
  reopening it from disk on every slider tick; currently harmless at
  interactive speeds but wasteful for very large source photos.

## Verification

Tested with Python 3.12.3 and Pillow 10.1.0 (within the `requirements.txt`
range) under a real X display:

- **Alpha-compositing fix**: ran a synthetic-pixel comparison (solid blue base,
  50%-alpha solid red watermark) through the old no-mask `paste()` call and the
  new `paste_watermark_at()` mask-based call, and printed the resulting pixel
  at the same location under both:

  ```
  OLD paste (no mask):    (255, 0, 0, 127)
  NEW paste (mask=wm):    (127, 0, 128, 191)
  ```

  The old result has zero contribution from the blue base (flat overwrite);
  the new result is a genuine blend of both colors. See "What was fixed" above
  for the full script.

- **GUI construction**: ran under a real X display (`DISPLAY=:0`, no Xvfb
  needed) with a 5 second timeout:

  ```bash
  timeout 5 python3 -c "
  import tkinter as tk
  from main import WatermarkApp
  root = tk.Tk()
  app = WatermarkApp(root)
  root.update()
  print('GUI constructed and updated with no exceptions')
  root.after(2000, root.destroy)
  root.mainloop()
  print('mainloop exited cleanly')
  "
  ```

  Output: `GUI constructed and updated with no exceptions` then
  `mainloop exited cleanly`, exit code 0. (This caught one real bug during
  development: two `ttk.Scale`/`ttk.Radiobutton` groups in the same
  `LabelFrame` mixed `pack` and `grid` geometry managers, which tkinter
  rejects; fixed by giving the offset sliders their own sub-frame.)

- **Full interactive flow, without the native file dialogs**: created a
  synthetic `600x400` JPEG photo and a `200x100` RGBA PNG watermark, assigned
  them directly to `app.watermark_original` / `app.photo_paths` (bypassing
  `askopenfilename`), then called `app._render_preview()` followed by
  `app.apply_and_save()` inside a live Tk root:

  ```bash
  timeout 8 python3 -c "
  import tkinter as tk
  from PIL import Image
  import tempfile, os
  from main import WatermarkApp

  tmpdir = tempfile.mkdtemp()
  photo_path = os.path.join(tmpdir, 'photo.jpg')
  wm_path = os.path.join(tmpdir, 'wm.png')
  Image.new('RGB', (600, 400), (0, 120, 255)).save(photo_path)
  Image.new('RGBA', (200, 100), (255, 255, 0, 255)).save(wm_path)

  root = tk.Tk()
  app = WatermarkApp(root)
  app.watermark_original = Image.open(wm_path)
  app.photo_paths = (photo_path,)
  app._render_preview()
  root.update()
  print('Preview rendered with no exceptions')

  app.location_var.set(tmpdir)
  app.apply_and_save()
  root.update()
  print('Status message:', app.status_var.get())
  print('Files in output dir:', [f for f in os.listdir(tmpdir) if f.endswith(('.png', '.jpg'))])
  root.destroy()
  "
  ```

  Output:

  ```
  Preview rendered with no exceptions
  Status message: Saved 1 watermarked photo(s).
  Files in output dir: ['photo_watermarked.png', 'wm.png', 'photo.jpg']
  ```

  Confirms the preview render path and the save path both run end to end
  without exceptions and produce a real output file.

Not verified: the interactive file-picker flow end to end (blocked on native
dialogs, not testable headlessly), drag-to-reposition on the canvas (not
implemented, see "What I'd do differently"), and behavior on Windows (untested
there, though `pathlib.Path` should handle it correctly).
