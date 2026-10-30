"""Paired RAW/SVG import dialog; no terrain or OSM placement occurs independently."""
from __future__ import annotations
import datetime,json,math,queue,re,threading,traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import ImageTk
import numpy as np
import tgc_unity_raw_svg as core

class Value:
    def __init__(self,value):self.value=value
    def get(self):return self.value

class UnityImportDialog(tk.Toplevel):
    def __init__(self,parent,project,map_scale=2.,printf=print,on_ready=None,on_close=None):
        super().__init__(parent)
        from tgc_ui_style import install as install_shared_ui
        install_shared_ui(self)
        self.project=Path(project);self.printf=printf;self.on_ready=on_ready;self.on_close=on_close;self.busy=False;self.closed=False;self.photo=None;self.features=[];self.mapping={};self.metadata={};self.queue=queue.Queue()
        self.title('Import Unity RAW + Course SVG')
        self.transient(parent);self.grab_set();self.protocol('WM_DELETE_WINDOW',self.close)
        w=min(1120,int(self.winfo_screenwidth()*.92));h=min(850,int(self.winfo_screenheight()*.90));self.geometry(f'{w}x{h}');self.minsize(min(w,800),min(h,560))
        self.columnconfigure(0,weight=1);self.rowconfigure(2,weight=1)
        paths=ttk.Frame(self,padding=8);paths.grid(row=0,column=0,sticky='ew');paths.columnconfigure(1,weight=1)
        self.raw=tk.StringVar();self.svg=tk.StringVar()
        for row,(label,var,ext) in enumerate([('Unity RAW',self.raw,'*.raw *.r16'),('Course SVG',self.svg,'*.svg')]):
            ttk.Label(paths,text=label).grid(row=row,column=0,sticky='w',padx=4)
            ttk.Entry(paths,textvariable=var).grid(row=row,column=1,sticky='ew',padx=4,pady=3)
            ttk.Button(paths,text='Browse',command=lambda v=var,e=ext:self.browse(v,e)).grid(row=row,column=2)
        controls=ttk.Frame(self,padding=(8,0));controls.grid(row=1,column=0,sticky='ew')
        defaults={'width_m':'','length_m':'','height_m':'','base_elevation_m':'0','rows':'','cols':'','bits':'16','byte_order':'little','orientation':'as_stored','output_spacing_m':str(map_scale)}
        self.v={k:tk.StringVar(value=v) for k,v in defaults.items()}
        fields=[('Width (m)','width_m'),('Length (m)','length_m'),('Height scale (m)','height_m'),('Base Z (m)','base_elevation_m'),('Output step (m)','output_spacing_m'),('Rows','rows'),('Columns','cols'),('Bits','bits'),('Byte order','byte_order'),('RAW orientation','orientation')]
        for i,(label,key) in enumerate(fields):
            rr=(i//5)*2;cc=i%5
            ttk.Label(controls,text=label).grid(row=rr,column=cc,sticky='w',padx=5)
            choices={'bits':('8','16'),'byte_order':('little','big'),'orientation':core.ORIENTATIONS}
            widget=ttk.Combobox(controls,textvariable=self.v[key],values=choices[key],state='readonly',width=17) if key in choices else ttk.Entry(controls,textvariable=self.v[key],width=17)
            widget.grid(row=rr+1,column=cc,sticky='ew',padx=5,pady=(0,5));controls.columnconfigure(cc,weight=1)
        main=ttk.Panedwindow(self,orient='horizontal');main.grid(row=2,column=0,sticky='nsew',padx=8)
        left=ttk.Frame(main);right=ttk.Frame(main);main.add(left,weight=1);main.add(right,weight=2)
        left.columnconfigure(0,weight=1);left.rowconfigure(1,weight=1)
        ttk.Label(left,text='SVG feature mapping — select a row to change its type').grid(row=0,column=0,sticky='w')
        self.tree=ttk.Treeview(left,columns=('group','fill','kind'),show='headings',height=13)
        for name,width in [('group',95),('fill',75),('kind',85)]:self.tree.heading(name,text=name.title());self.tree.column(name,width=width,stretch=True)
        self.tree.grid(row=1,column=0,sticky='nsew');bar=ttk.Scrollbar(left,command=self.tree.yview);bar.grid(row=1,column=1,sticky='ns');self.tree.configure(yscrollcommand=bar.set)
        self.kind=tk.StringVar(value='unclassified');choice=ttk.Combobox(left,textvariable=self.kind,values=core.KINDS,state='readonly');choice.grid(row=2,column=0,sticky='ew',pady=5)
        self.tree.bind('<<TreeviewSelect>>',self.selected);choice.bind('<<ComboboxSelected>>',self.assign)
        self.preview=ttk.Label(right,text='Inspect files, then preview to confirm the terrain/layout orientation.',anchor='center');self.preview.pack(fill='both',expand=True)
        self.status=tk.StringVar(value='Terrain dimensions are metres; the SVG viewBox is mapped across the full RAW extent.')
        ttk.Label(self,textvariable=self.status,wraplength=w-30,padding=8).grid(row=3,column=0,sticky='ew')
        ttk.Label(self,text='Local synthetic coordinates only. Custom / Unmatched is OFF for this matched pair. No hole numbers or pars are guessed.',wraplength=w-30,padding=(8,2)).grid(row=4,column=0,sticky='ew')
        buttons=ttk.Frame(self,padding=8);buttons.grid(row=5,column=0,sticky='ew')
        self.buttons=[]
        for label,fn in [('Load settings',self.load_settings),('Inspect files',self.inspect),('Preview',self.show_preview),('Find SVG orientation',self.match_orientation),('Convert + DEM process',self.convert),('Cancel',self.close)]:
            b=ttk.Button(buttons,text=label,command=fn);b.pack(side='left',padx=3);self.buttons.append(b)
        self._pump_job = self.after(80,self.pump)
    def browse(self,var,ext):
        if self.busy:return
        p=filedialog.askopenfilename(parent=self,initialdir=self.project,filetypes=[('Source files',ext),('All files','*')])
        if p:var.set(p)
    def set_busy(self,b,text):
        self.busy=b;self.status.set(text)
        for widget in self.buttons:widget.configure(state='disabled' if b else 'normal')
    def worker(self,fn,done):
        if self.busy:return
        self.set_busy(True,'Processing local files…')
        def work():
            try:self.queue.put(('ok',done,fn()))
            except Exception:self.queue.put(('error',None,traceback.format_exc()))
        threading.Thread(target=work,daemon=True,name='TGC-Unity-RAW-SVG').start()
    def pump(self):
        self._pump_job = None
        if self.closed:return
        try:
            while True:
                kind,done,result=self.queue.get_nowait();self.set_busy(False,'Ready')
                if kind=='error':self.printf(result);messagebox.showerror('Unity import',result.splitlines()[-1],parent=self)
                else:done(result)
        except queue.Empty:pass
        if not self.closed:self._pump_job = self.after(80,self.pump)
    def settings(self):
        s={k:(int(v.get()) if k in ('rows','cols','bits') else v.get() if k in ('byte_order','orientation') else float(v.get())) for k,v in self.v.items()}
        s.update({'mapping':dict(self.mapping),'output_prefix':Path(self.svg.get()).stem,'epsg':32631,'center_e':500000.,'center_n':5000000.,'normalization_divisor':2**s['bits'],'curve_tolerance_m':.15,'max_segment_m':8.})
        return s
    def load_settings(self):
        p=filedialog.askopenfilename(parent=self,initialdir=self.project,filetypes=[('Unity import settings','*.json')])
        if not p:return
        try:
            s=json.loads(Path(p).read_text(encoding='utf-8-sig'))
            if 'settings' in s:s=s['settings']
            for k,v in self.v.items():
                if k in s:v.set(str(s[k]))
            self.mapping=dict(s.get('mapping',{}));self.status.set('Settings loaded; select the original RAW/SVG, then Inspect files and Preview.')
        except Exception as exc:messagebox.showerror('Settings',str(exc),parent=self)
    def inspect(self):
        raw=self.raw.get();svg=self.svg.get();mapping=dict(self.mapping)
        # Snapshot UI values before using the worker.
        try:w0=self.v['width_m'].get();h0=self.v['length_m'].get()
        except Exception:return
        def safe_run():
            info=core.inspect_raw(raw)
            import xml.etree.ElementTree as ET
            root=ET.parse(svg).getroot();vb=[float(x) for x in re.findall(core.NUMBER,root.get('viewBox',''))]
            if len(vb)!=4:raise ValueError('SVG needs a viewBox')
            w=float(w0 or vb[2]);h=float(h0 or vb[3]);features,meta=core.read_svg(svg,w,h,mapping)
            return info,vb,w,h,features,meta
        def done(result):
            info,vb,w,h,self.features,self.metadata=result
            c=info['square_candidates']
            if len(c)==1:
                for k in ('rows','cols','bits'):self.v[k].set(str(c[0][k]))
            if info['suggested_byte_order']:self.v['byte_order'].set(info['suggested_byte_order'])
            self.v['width_m'].set(str(w));self.v['length_m'].set(str(h))
            self.mapping.update({k:v for k,v in self.metadata['classification_groups'].items() if k not in self.mapping})
            self.tree.delete(*self.tree.get_children())
            for key,val in self.mapping.items():
                if '|' in key:group,fill=key.split('|',1);self.tree.insert('', 'end',iid=key,values=(group,fill,val))
            self.status.set(f'{info["bytes"]:,} RAW bytes; {len(self.features)} SVG paths. Confirm dimensions, height scale, mapping and orientation. Unclassified shapes are preserved but not imported as turf.')
        self.worker(safe_run,done)
    def selected(self,event=None):
        q=self.tree.selection()
        if q:self.kind.set(self.mapping[q[0]])
    def assign(self,event=None):
        for key in self.tree.selection():
            self.mapping[key]=self.kind.get();g,f=key.split('|',1);self.tree.item(key,values=(g,f,self.kind.get()))
    def show_preview(self):
        try:s=self.settings()
        except Exception as exc:messagebox.showerror('Parameters','Complete dimensions/height and inspect RAW resolution first. '+str(exc),parent=self);return
        raw=self.raw.get();svg=self.svg.get()
        def work():
            a=core.load_raw(raw,s);fs,meta=core.read_svg(svg,s['width_m'],s['length_m'],s['mapping']);im=core.preview_image(a,fs,s['width_m'],s['length_m'],650)
            return im,float(a.min()),float(a.max())
        def done(result):
            im,lo,hi=result;im.thumbnail((max(200,self.preview.winfo_width()),max(200,self.preview.winfo_height())))
            self.photo=ImageTk.PhotoImage(im);self.preview.configure(image=self.photo,text='');self.status.set(f'Elevation {lo:.2f}–{hi:.2f} m; white outlines are the source SVG. Confirm alignment before converting.')
        self.worker(work,done)
    def match_orientation(self):
        try:s=self.settings()
        except Exception as exc:messagebox.showerror('Parameters','Inspect files and enter terrain height first.',parent=self);return
        raw=self.raw.get();svg=self.svg.get()
        def work():
            from rasterio.features import rasterize
            from rasterio.transform import from_origin
            s['orientation']='as_stored';a=core.load_raw(raw,s);fs,_=core.read_svg(svg,s['width_m'],s['length_m'],s['mapping']);masks=[]
            h,w=a.shape;dx=s['width_m']/(w-1);dy=s['length_m']/(h-1)
            if h!=w:raise ValueError('Automatic orientation ranking is only offered for square heightmaps; use the manual preview for rectangular RAW.')
            for f in fs:
                if f['kind']!='green' or f['geometry'].area<40:continue
                p=f['geometry'].buffer(-2)
                if p.is_empty:continue
                mask=rasterize([(p,1)],out_shape=(h,w),transform=from_origin(-dx/2,-dy/2,dx,-dy),dtype='uint8')
                rr,cc=np.where(mask)
                if len(rr)<8:continue
                mat=np.c_[np.ones(len(rr)),(cc-cc.mean())*dx,(rr-rr.mean())*dy];masks.append((rr,cc,mat))
            if len(masks)<4:raise ValueError('Need at least four labeled greens for orientation ranking; choose orientation manually.')
            results={}
            for name in core.ORIENTATIONS:
                b=core.orient(a,name);scores=[]
                for rr,cc,mat in masks:
                    z=b[rr,cc];fit=np.linalg.lstsq(mat,z,rcond=None)[0];scores.append(float(np.sqrt(np.mean((z-mat@fit)**2))))
                results[name]=float(np.median(scores))
            return sorted(results.items(),key=lambda item:item[1])
        def done(result):
            best,score=result[0];self.v['orientation'].set(best)
            text='Suggested '+best+' (green planar residual '+f'{score:.3f}'+' m). This is a geometric heuristic, not a georeferencing guarantee. Check Preview.'
            self.status.set(text);self.printf(text+' All scores: '+repr(result));self.show_preview()
        self.worker(work,done)
    def convert(self):
        try:s=self.settings()
        except Exception as exc:messagebox.showerror('Parameters',str(exc),parent=self);return
        raw=self.raw.get();svg=self.svg.get()
        notice='This exports a synthetic, matched DEM/OSM pair and starts normal DEM processing. Confirm the preview and feature mapping first. No hole routing/par is inferred; if absent, the result is surfaces only. Existing project heightmap/mask may be replaced after you accept the normal DEM crop. Continue?'
        if not messagebox.askyesno('Convert + process',notice,parent=self):return
        folder=self.project/('Unity_Import_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        def work():return core.create_pair(raw,svg,folder,s,printf=lambda text:None)[0]
        def done(report):
            for text in report['limitations']:self.printf('NOTICE: '+text)
            self.printf('Matched Unity pair: '+str(folder));self.close()
            if self.on_ready:self.on_ready(report)
        self.worker(work,done)
    def close(self):
        if self.busy:return
        if self.closed:return
        self.closed=True
        job=getattr(self,"_pump_job",None)
        if job is not None:
            try:self.after_cancel(job)
            except tk.TclError:pass
            self._pump_job=None
        try:self.grab_release()
        except Exception:pass
        self.destroy()
        if self.on_close:self.on_close()
