"""LiDAR output-stage reporting and scoped, numerically identical projection reuse.

No terrain, OSM classification, mask morphology or tree algorithms live here.
Percentages are explicit phase milestones, NOT estimated remaining time.
"""
from pathlib import Path
import copy
import json
import os
import tempfile
import time
import types

import numpy as np

PREFIX = 'TGC_OUTPUT_PROGRESS|'


class OutputProgress:
    def __init__(self, printf=print, label='LiDAR crop output'):
        self.printf = printf
        self.label = label
        self.started = self.last_stage = time.perf_counter()
        self.last_emit = 0.0
        self.percent = 0
        self.message = 'Preparing output'
        self.timings = []
        self.stage(0, self.message)

    def _emit(self, detail='', force=True):
        now = time.perf_counter()
        if not force and now - self.last_emit < 0.5:
            return
        self.last_emit = now
        event = dict(label=self.label, percent=self.percent, message=self.message,
                     detail=detail, elapsed=now-self.started,
                     stage_elapsed=now-self.last_stage, done=self.percent == 100)
        self.printf(PREFIX + json.dumps(event, separators=(',', ':')))

    def stage(self, percent, message):
        now = time.perf_counter()
        if self.timings or now != self.started:
            if now - self.last_stage > 0.001:
                self.timings.append({'stage': self.message, 'seconds': round(now-self.last_stage, 4)})
        self.percent = max(self.percent, min(100, int(percent)))
        self.message = str(message)
        self.last_stage = now
        self._emit()

    def note(self, detail, force=False):
        self._emit(str(detail), force=force)

    def finish(self, message='Output files saved and closed'):
        self.stage(100, message)
        self.printf(self.label + ' timings: ' + '; '.join(
            '%s %.2f s' % (row['stage'], row['seconds']) for row in self.timings
        ) + '; total %.2f s.' % (time.perf_counter()-self.started))


class _ChunkedWriter:
    def __init__(self, stream, progress):
        self.stream = stream
        self.progress = progress
        self.total = 0

    def write(self, data):
        view = memoryview(data).cast('B')
        for start in range(0, len(view), 4 * 1024 * 1024):
            block = view[start:start + 4 * 1024 * 1024]
            written = self.stream.write(block)
            if written != len(block):
                raise OSError('Incomplete heightmap write')
            self.total += written
            if self.progress is not None:
                self.progress.note('%.1f MiB written; serializing/saving heightmap' % (self.total / 1048576.0))
        return len(view)

    def flush(self):
        return self.stream.flush()

    def tell(self):
        return self.stream.tell()


def save_npy(path, data, progress=None):
    """Same NumPy dictionary format, streamed in chunks into a same-folder temp.

    Byte count is measured. No speculative byte total or extra serialization pass.
    Existing heightmap survives an encode/write/replace failure.
    """
    path = Path(path)
    if path.suffix.lower() != '.npy':
        path = Path(str(path) + '.npy')
    fd, temp_name = tempfile.mkstemp(prefix='.' + path.stem + '-', suffix='.npy', dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            writer = _ChunkedWriter(stream, progress)
            np.save(writer, data)
            writer.flush()
        os.replace(temp, path)
        if progress is not None:
            progress.note('%.1f MiB saved and closed' % (writer.total / 1048576.0), force=True)
    finally:
        if temp.exists():
            temp.unlink()


def save_png(path, image, progress=None):
    """Use unchanged OpenCV defaults/pixels; check failure and replace after close."""
    import cv2
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(prefix='.' + path.stem + '-', suffix='.png', dir=str(path.parent))
    os.close(fd)
    temp = Path(temp_name)
    try:
        if not cv2.imwrite(str(temp), image):
            raise OSError('Could not encode/write mask: ' + str(path))
        os.replace(temp, path)
        if progress is not None:
            progress.note('mask.png saved (%.1f MiB)' % (path.stat().st_size / 1048576.0), force=True)
        return True
    finally:
        if temp.exists():
            temp.unlink()


def image_projector(pc, progress=None):
    """Reuse the IDENTICAL transformer, only for a standard image-rendering PC.

    Shallow copy: original object's projection, origin and methods are untouched.
    No vectorized arithmetic, changed axis order, offsets, cell rounding or grids.
    Specialized/custom projectors and instance-overridden methods are preserved.
    """
    from GeoPointCloud import GeoPointCloud
    if type(pc) is not GeoPointCloud or 'latlonToProj' in vars(pc):
        return pc
    import pyproj
    transformer = pyproj.Transformer.from_proj(pc._platlon, pc.proj, True)
    cached = copy.copy(pc)

    visits = [0]
    def latlon_to_proj(self, lat, lon):
        result = transformer.transform(lon, lat)
        visits[0] += 1
        if progress is not None and visits[0] % 512 == 0:
            progress.note('%s coordinate lookups processed (this output pass)' % format(visits[0], ','))
        return result

    cached.latlonToProj = types.MethodType(latlon_to_proj, cached)
    return cached


def decode_event(message):
    if not isinstance(message, str) or not message.startswith(PREFIX):
        return None
    try:
        event = json.loads(message[len(PREFIX):])
        if not isinstance(event, dict) or not 0 <= float(event['percent']) <= 100:
            return None
        return event
    except (ValueError, KeyError, TypeError):
        return None


class OutputProgressPanel:
    """Tk widget owned and updated by the existing main-thread log pump only."""
    def __init__(self, parent, console_printf):
        import tkinter as tk
        from tkinter import ttk
        self.frame = ttk.Frame(parent)
        self.text = tk.StringVar(value='Output progress: idle')
        self.label = ttk.Label(self.frame, textvariable=self.text, anchor='w', width=100, wraplength=900)
        self.label.pack(fill='x')
        self.bar = ttk.Progressbar(self.frame, maximum=100, mode='determinate')
        self.bar.pack(fill='x', pady=(2, 0))
        self.activity = ttk.Progressbar(self.frame, mode='indeterminate', length=90)
        self.activity.pack(anchor='e')
        self.console_printf = console_printf
        self.event = None
        self.received = 0.0
        self.active = False
        self.after_id = self.frame.after(250, self._tick)
        self.frame.bind('<Destroy>', self._destroy, add='+')
        self.frame.bind('<Configure>', lambda e: self.label.configure(wraplength=max(200, e.width - 12)), add='+')

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def _destroy(self, event):
        if event.widget is self.frame and self.after_id:
            try:
                self.frame.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def printf(self, message):
        event = decode_event(message)
        if event is not None:
            previous = self.event
            self.event = event
            self.received = time.perf_counter()
            self.active = not event.get('done', False)
            self.bar.configure(value=float(event['percent']))
            if self.active:
                if not previous or previous.get('done', False):
                    self.activity.start(70)
            else:
                self.activity.stop()
            self._display()
            # Log milestones once; byte counts remain visible without flooding Tk.
            if not previous or previous.get('label') != event.get('label') or previous.get('message') != event.get('message'):
                self.console_printf('%s: %d%% (phase-based) - %s' % (
                    event.get('label', 'Output'), event['percent'], event.get('message', '')))
            return
        message = str(message)
        low = message.lower()
        if 'processing failed' in low or 'traceback (most recent call last)' in low or 'preview/crop failed' in low:
            self.active = False
            self.activity.stop()
            self.text.set('Output interrupted - see the processing log below')
        elif 'job started in background' in low:
            self.active = False
            self.event = None
            self.activity.stop()
            self.bar.configure(value=0)
            self.text.set('Processing source data - output progress starts after detection')
        self.console_printf(message)

    def _display(self):
        if self.event is None:
            return
        e = self.event
        extra = max(0.0, time.perf_counter() - self.received) if self.active else 0.0
        self.text.set('%s: %d%% (phase-based) | %s%s | elapsed %.1f s | current phase %.1f s' % (
            e.get('label', 'Output'), e['percent'], e.get('message', ''),
            (' - ' + e['detail']) if e.get('detail') else '',
            e.get('elapsed', 0.0) + extra, e.get('stage_elapsed', 0.0) + extra))

    def _tick(self):
        if self.active:
            self._display()
        self.after_id = self.frame.after(250, self._tick)
