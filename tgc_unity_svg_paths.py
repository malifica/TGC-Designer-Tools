"""Small dependency-free SVG path flattener for the TGC local importer.
No network resources, scripts, CSS execution or raster tracing. Coordinates are
transformed before the flatness test, so tolerance is in destination metres.
"""
from __future__ import annotations
import math
import re
import numpy as np

NUMBER=r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?'
TOKEN=re.compile(r'[MmZzLlHhVvCcSsQqTtAa]|'+NUMBER)
COUNTS={'M':2,'L':2,'H':1,'V':1,'C':6,'S':4,'Q':4,'T':2,'A':7}


def matrix(text=''):
    out=np.eye(3,dtype=float)
    remain=re.sub(r'([A-Za-z]+)\s*\(([^)]*)\)', '',text).strip(' ,\t\r\n')
    if remain:raise ValueError('Unsupported SVG transform: '+text)
    for name,args in re.findall(r'([A-Za-z]+)\s*\(([^)]*)\)',text):
        a=[float(x) for x in re.findall(NUMBER,args)];m=np.eye(3)
        if name=='matrix' and len(a)==6:m=np.array([[a[0],a[2],a[4]],[a[1],a[3],a[5]],[0,0,1]],float)
        elif name=='translate' and len(a) in (1,2):m[0,2]=a[0];m[1,2]=a[1] if len(a)==2 else 0
        elif name=='scale' and len(a) in (1,2):m[0,0]=a[0];m[1,1]=a[1] if len(a)==2 else a[0]
        elif name=='rotate' and len(a) in (1,3):
            t=math.radians(a[0]);c,s=math.cos(t),math.sin(t);m[:2,:2]=[[c,-s],[s,c]]
            if len(a)==3:m[:2,2]=np.array(a[1:])-m[:2,:2]@np.array(a[1:])
        elif name in ('skewX','skewY') and len(a)==1:m[0 if name=='skewX' else 1,1 if name=='skewX' else 0]=math.tan(math.radians(a[0]))
        else:raise ValueError('Unsupported SVG transform: '+name+'('+args+')')
        out=out@m
    if not np.isfinite(out).all():raise ValueError('Non-finite SVG transform')
    return out


def _distance(p,a,b):
    v=b-a;d=float(v@v)
    if d<1e-25:return float(np.linalg.norm(p-a))
    q=a+np.clip(float((p-a)@v)/d,0,1)*v
    return float(np.linalg.norm(p-q))


def flatten_path(d, transform=None, tolerance=0.15, max_step=8.0):
    """Return [(points, explicitly_closed)] without changing SVG subpath topology."""
    if tolerance<=0 or max_step<=0:raise ValueError('Positive curve tolerance and segment length required')
    transform=np.eye(3) if transform is None else np.asarray(transform,float)
    # Reject unrecognized characters instead of silently dropping a command.
    residue=TOKEN.sub('',d)
    if residue.strip(' ,\t\r\n'):raise ValueError('Unsupported/invalid SVG path syntax: '+residue[:80])
    tokens=TOKEN.findall(d);i=0;command=None;previous='';cur=np.zeros(2);start=None;last_c=None;last_q=None;parts=[];pts=[]
    def tr(p):return transform[:2,:2]@np.asarray(p,float)+transform[:2,2]
    def line_to(p):
        if not pts:pts.append(tr(cur))
        a=pts[-1];b=tr(p);n=max(1,int(math.ceil(np.linalg.norm(b-a)/max_step)))
        for j in range(1,n+1):pts.append(a+(b-a)*(j/n))
    def bezier(ctrl,depth=0):
        if depth>24:raise ValueError('Curve subdivision limit exceeded')
        chord=np.linalg.norm(ctrl[-1]-ctrl[0]);error=max((_distance(p,ctrl[0],ctrl[-1]) for p in ctrl[1:-1]),default=0.)
        if error<=tolerance and chord<=max_step:
            pts.append(ctrl[-1]);return
        left=[ctrl[0]];right=[ctrl[-1]];q=ctrl
        while len(q)>1:q=(q[:-1]+q[1:])/2;left.append(q[0]);right.append(q[-1])
        bezier(np.array(left),depth+1);bezier(np.array(right[::-1]),depth+1)
    def finish(closed=False):
        nonlocal pts
        if pts:
            out=[pts[0]]
            for p in pts[1:]:
                if np.linalg.norm(p-out[-1])>1e-9:out.append(p)
            if closed:
                if np.linalg.norm(out[-1]-out[0])>1e-9:out.append(out[0].copy())
                else:out[-1]=out[0].copy()
            parts.append((np.asarray(out),closed))
        pts=[]
    while i<len(tokens):
        if tokens[i].isalpha():command=tokens[i];i+=1
        if command is None:raise ValueError('SVG path missing initial command')
        op=command.upper();relative=command.islower()
        if op=='Z':
            if start is None:raise ValueError('Close before SVG move')
            line_to(start);cur=start.copy();finish(True);previous='Z';last_c=last_q=None;command=None;continue
        n=COUNTS[op]
        if i+n>len(tokens) or any(t.isalpha() for t in tokens[i:i+n]):raise ValueError('Incomplete SVG '+op+' command')
        a=np.array([float(t) for t in tokens[i:i+n]],float);i+=n
        if not np.isfinite(a).all():raise ValueError('Non-finite SVG coordinate')
        def p(k):return a[k:k+2]+(cur if relative else 0)
        if op=='M':
            q=p(0);finish(False);cur=q;start=q.copy();pts=[tr(q)];command='l' if relative else 'L';last_c=last_q=None
        elif op=='L':q=p(0);line_to(q);cur=q;last_c=last_q=None
        elif op in ('H','V'):
            q=cur.copy();axis=0 if op=='H' else 1;q[axis]=a[0]+(cur[axis] if relative else 0);line_to(q);cur=q;last_c=last_q=None
        elif op in ('C','S'):
            if op=='C':c1,c2,q=p(0),p(2),p(4)
            else:c1=2*cur-last_c if previous in ('C','S') and last_c is not None else cur.copy();c2,q=p(0),p(2)
            bezier(np.array([tr(cur),tr(c1),tr(c2),tr(q)]));cur=q;last_c=c2;last_q=None
        elif op in ('Q','T'):
            if op=='Q':c1,q=p(0),p(2)
            else:c1=2*cur-last_q if previous in ('Q','T') and last_q is not None else cur.copy();q=p(0)
            bezier(np.array([tr(cur),tr(c1),tr(q)]));cur=q;last_q=c1;last_c=None
        elif op=='A':
            rx,ry=abs(a[0]),abs(a[1]);phi=math.radians(a[2]);large,sweep=a[3],a[4];q=p(5)
            if large not in (0,1) or sweep not in (0,1):raise ValueError('SVG arc flags must be 0 or 1')
            if rx==0 or ry==0:line_to(q)
            elif np.linalg.norm(q-cur)>1e-12:
                cs,sn=math.cos(phi),math.sin(phi);rot=np.array([[cs,-sn],[sn,cs]])
                xp,yp=rot.T@((cur-q)/2);lam=xp*xp/(rx*rx)+yp*yp/(ry*ry)
                if lam>1:rx*=math.sqrt(lam);ry*=math.sqrt(lam)
                num=max(0.,rx*rx*ry*ry-rx*rx*yp*yp-ry*ry*xp*xp);den=rx*rx*yp*yp+ry*ry*xp*xp
                coeff=(-1 if large==sweep else 1)*math.sqrt(num/max(den,1e-30))
                center_prime=np.array([coeff*rx*yp/ry,-coeff*ry*xp/rx]);center=rot@center_prime+(cur+q)/2
                u=(np.array([xp,yp])-center_prime)/[rx,ry];v=(-np.array([xp,yp])-center_prime)/[rx,ry]
                t0=math.atan2(u[1],u[0]);dt=math.atan2(u[0]*v[1]-u[1]*v[0],float(u@v))
                if not sweep and dt>0:dt-=2*math.pi
                if sweep and dt<0:dt+=2*math.pi
                rmax=max(rx,ry)*float(np.linalg.norm(transform[:2,:2],ord=2))
                da=min(max_step/max(rmax,1e-10),2*math.acos(max(-1.,1-tolerance/max(rmax,1e-10))))
                steps=max(1,int(math.ceil(abs(dt)/max(da,1e-7))))
                if steps>1000000:raise ValueError('SVG arc exceeds sample limit')
                for j in range(1,steps+1):
                    t=t0+dt*j/steps;pts.append(tr(center+rot@np.array([rx*math.cos(t),ry*math.sin(t)])))
                pts[-1]=tr(q)
            cur=q;last_c=last_q=None
        previous=op
        if sum(len(x[0]) for x in parts)+len(pts)>1000000:raise ValueError('SVG path exceeds node limit')
    finish(False)
    return parts
