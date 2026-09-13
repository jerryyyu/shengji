import math
if "M" not in globals():          # build.py may inject M / TABLE_ONLY / SERIES (tests)
    exec(open(MODELS).read())
M=[m for m in M if m[1] not in TABLE_ONLY]
PAR={256:272716,512:610764,1024:1483468,2048:4015308,
     330:610704}   # depth-4 residual at the h512 budget (grid S-d4, from its receipt)
REC={"8k":1168124,"16k":2341808,"48k":7043156,"72k":10559236,"96k":14077520,
     "128k":18764912,"144k":20939532,"176k":25388708}
R=[]
for (n,ck,tr,enc,w,lr,cl,rec,ce,rg,mc,w32,ten,note) in M:
    r=int(rec.replace(",","")) if rec and rec[0].isdigit() else REC.get(cl)
    R.append(dict(n=n,ck=ck,tr=tr.lstrip("~"),ap=tr.startswith("~"),enc=enc,w=w,lr=lr,cl=cl,
                  rec=r,ce=float(ce) if ce else None,par=PAR[w],note=note,mc=mc,w32=w32,ten=ten))
def esc(t): return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
def tip(d):
    lines=["%s  (%s)"%(d["n"],d["ck"]),
           "trained %s%s"%(d["tr"]," (approx)" if d["ap"] else ""),
           "encoder %s | width %d | lr %s | %s clusters"%(d["enc"],d["w"],d["lr"],d["cl"])]
    if d["ce"] is not None: lines.append("val_ce %.5f"%d["ce"])
    if d["mc"]: lines.append("vs MC-LCB  %s"%d["mc"])
    if d["w32"] and d["w32"] not in ("REF","GAP"): lines.append("vs leader  %s"%d["w32"].replace("RES",""))
    elif d["w32"]=="GAP": pass
    elif d["w32"]=="GAP": lines.append("vs leader  never paired")
    if d["ten"] and d["ten"] not in ("REF","CONTROL","QUEUED","RUNNING","SCREENING","CODEX"):
        lines.append("ten windows  %s"%d["ten"])
    if d["note"]: lines.append(d["note"])
    return esc("\n".join(lines))
def dot(cx,cy,r,cls,d):
    return ('<circle cx="%.1f" cy="%.1f" r="%s" class="%s hit" tabindex="0" data-t="%s">'
            '<title>%s</title></circle>')%(cx,cy,r,cls,tip(d).replace("\n","&#10;"),tip(d))
def sc(v,lo,hi,a,b): return a+(v-lo)/(hi-lo)*(b-a)
def lgs(v,lo,hi,a,b): return sc(math.log10(v),math.log10(lo),math.log10(hi),a,b)
open(OUT+"/_R.py","w").write(repr(R))
BYCK={d["ck"]:d for d in R}
def series(key, axis):
    """Measured (x, ce) of the checkpoints SERIES[key] names, sorted by x."""
    pts=[]
    for ck in SERIES[key]:
        if ck not in BYCK: raise SystemExit(f"SERIES[{key!r}] names {ck}, which is not a charted row")
        d=BYCK[ck]
        if d["ce"] is None: raise SystemExit(f"SERIES[{key!r}] names {ck}, which has no val_ce")
        pts.append((d[axis], d["ce"]))
    return sorted(pts)
def fmt_signed(v, nd=4):
    return ("&#8722;" if v<0 else "+")+("%%.%df"%nd)%abs(v)
print("models:",len(R),"with ce:",sum(1 for d in R if d["ce"]))

def frame(W,H,L,Rm,T,B,XLO,XHI,ylo,yhi,yt,xt,xlab,ylab,ylog=False,yfmt="{:.2f}"):
    x0,x1,y0,y1=L,W-Rm,T,H-B
    X=lambda v,k=0: lgs(v,XLO,XHI,x0,x1)+k
    if ylog: Y=lambda v: y0+(math.log(yhi)-math.log(v))/(math.log(yhi)-math.log(ylo))*(y1-y0)
    else:    Y=lambda v: y0+(yhi-v)/(yhi-ylo)*(y1-y0)
    s=['<svg viewBox="0 0 %d %d">'%(W,H)]
    for v in yt:
        z=" zero" if v==0 else ""
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid%s"/>'%(x0,Y(v),x1,Y(v),z))
        s.append('<text x="%d" y="%.1f" class="ax ar">%s</text>'%(x0-11,Y(v)+4,yfmt.format(v)))
    for v,lab in xt:
        s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="grid"/>'%(X(v),y0,X(v),y1))
        s.append('<text x="%.1f" y="%d" class="ax am">%s</text>'%(X(v),y1+21,lab))
    s.append('<text x="%d" y="%d" class="axl am">%s</text>'%((x0+x1)/2,y1+45,xlab))
    s.append('<text x="17" y="%d" class="axl am" transform="rotate(-90 17 %d)">%s</text>'%((y0+y1)/2,(y0+y1)/2,ylab))
    return s,X,Y,x0,x1,y0,y1

YT=[0.60,0.62,0.64,0.66,0.68,0.70,0.72,0.74]
CE_HI=0.740   # every CE chart's top; a model above it is listed by name, never drawn off-canvas
OFFSCALE=[d for d in R if d["ce"] is not None and d["ce"]>CE_HI]
ONSCALE=[d for d in R if d["ce"] is not None and d["ce"]<=CE_HI]
def offscale_note(s, lx, y0):
    """Legend lines naming every model above the CE axis (visible, not silent)."""
    if not OFFSCALE: return y0
    s.append('<text x="%d" y="%d" class="lgh">OFF THIS SCALE</text>'%(lx,y0))
    for i,d in enumerate(OFFSCALE):
        s.append('<text x="%d" y="%d" class="lgs">%s: CE %.3f</text>'%(lx,y0+16+i*14,esc(d["n"]),d["ce"]))
    return y0+16+len(OFFSCALE)*14+6
# ---------- 1: data vs val_ce (LOG y) ----------
s,X,Y,x0,x1,y0,y1=frame(880,470,84,200,26,64,9e5,2.4e7,0.600,0.740,YT,
  [(1e6,"1M"),(2e6,"2M"),(5e6,"5M"),(1e7,"10M"),(2e7,"20M")],
  "training records (log scale)","validation cross-entropy (log)",ylog=True)
b1=series("base_v1","rec"); b2=series("base_v2","rec")
_g1,_g2=(BYCK[c] for c in SERIES["enc_gap"]); ENC_GAP=_g2["ce"]-_g1["ce"]
if _g1["rec"]!=_g2["rec"]: raise SystemExit("enc_gap rows are not at identical data")
s.append('<polyline class="ln ln1" points="'+" ".join("%.1f,%.1f"%(X(a),Y(b)) for a,b in b1)+'"/>')
s.append('<polyline class="ln ln2" points="'+" ".join("%.1f,%.1f"%(X(a),Y(b)) for a,b in b2)+'"/>')
_gx=_g1["rec"]; _gy=(Y(_g1["ce"])+Y(_g2["ce"]))/2
s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="drop"/>'%(X(_gx),Y(_g1["ce"]),X(_gx),Y(_g2["ce"])))
s.append('<text x="%.1f" y="%.1f" class="note" text-anchor="end">encoder v1 &#8594; v2</text>'%(X(_gx)-12,_gy))
s.append('<text x="%.1f" y="%.1f" class="noteb" text-anchor="end">%s at identical data</text>'%(X(_gx)-12,_gy+16,fmt_signed(ENC_GAP)))
n1=n2=n3=0
for d in R:
    if d["ce"] is None or d["ce"]>CE_HI: continue
    # v3 gets its own class. Folding it into the v2 branch would have mislabelled the
    # legend and hidden a whole encoder generation inside another one.
    if d["enc"]=="v1": cls="pt pt1"; n1+=1
    elif d["enc"]=="v3": cls="pt pt5"; n3+=1
    else: cls="pt pt2"; n2+=1
    s.append(dot(X(d["rec"]),Y(d["ce"]), 6 if d["ck"]=="3cd27716" else 4.4, cls, d))
lx=x1+22
s.append('<text x="%d" y="40" class="lgh">ENCODER</text>'%lx)
s.append('<circle cx="%d" cy="60" r="4.4" class="pt pt1"/><text x="%d" y="64" class="lg">v1 &middot; %d runs</text>'%(lx+6,lx+19,n1))
s.append('<circle cx="%d" cy="82" r="4.4" class="pt pt2"/><text x="%d" y="86" class="lg">v2 &middot; %d runs</text>'%(lx+6,lx+19,n2))
s.append('<circle cx="%d" cy="104" r="4.4" class="pt pt5"/><text x="%d" y="108" class="lg">v3 &middot; %d run%s</text>'%(lx+6,lx+19,n3,"s" if n3!=1 else ""))
NCE=len(ONSCALE)
for i,t in enumerate(["All %d models with a"%NCE,"validation number on","this scale.","Click or tab to any dot","for its full record."]):
    s.append('<text x="%d" y="%d" class="lgs">%s</text>'%(lx,140+i*16,t))
offscale_note(s, lx, 236)
s.append('</svg>'); open(OUT+"/g1.svg","w").write("\n".join(s))

# ---------- 3: width vs val_ce (LOG y) ----------
s,X,Y,x0,x1,y0,y1=frame(880,420,84,200,26,70,2.0e5,5.5e6,0.602,0.740,
  [0.62,0.64,0.66,0.68,0.70,0.72,0.74],
  [(2.72e5,"h256"),(6.11e5,"h512"),(1.48e6,"h1024"),(4.02e6,"h2048")],
  "parameters (log scale)","validation cross-entropy (log)",ylog=True)
for v,lab in [(2.72e5,"273k"),(6.11e5,"611k"),(1.48e6,"1.48M"),(4.02e6,"4.02M")]:
    s.append('<text x="%.1f" y="%d" class="axs am">%s</text>'%(X(v),y1+37,lab))
SER=[("width_lr1e4_96k","ln3","pt3"),("width_3e4_96k","ln2","pt2"),
     ("width_3e4_72k","ln4","pt4"),("width_3e4_144k","ln5","pt5")]
for key,ln,_ in SER:
    pts=series(key,"par")
    s.append('<polyline class="ln %s" points="'%ln+" ".join("%.1f,%.1f"%(X(a),Y(b)) for a,b in pts)+'"/>')
_member={ck:pt for key,_,pt in SER for ck in SERIES[key]}
for d in R:
    if d["ce"] is None or d["ce"]>CE_HI: continue
    cls=("pt "+_member[d["ck"]]) if d["ck"] in _member else None
    s.append(dot(X(d["par"]),Y(d["ce"]), 5 if cls else 3.6, cls or "pt ptx", d))
_cell=[BYCK[c] for c in SERIES["one_cell_72k"]]
if len({(d["cl"],d["w"],d["lr"],d["enc"]) for d in _cell})!=1: raise SystemExit("one_cell_72k rows are not one recipe cell")
ys=[d["ce"] for d in _cell]; CELL_N=len(ys); CELL_SPREAD=max(ys)-min(ys); _cx=_cell[0]["par"]
s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="spread"/>'%(X(_cx)-28,Y(max(ys)),X(_cx)-28,Y(min(ys))))
s.append('<text x="%.1f" y="%.1f" class="lab ar">%d models, one cell</text>'%(X(_cx)-34,(Y(max(ys))+Y(min(ys)))/2,CELL_N))
s.append('<text x="%.1f" y="%.1f" class="lab ar">spread %.4f</text>'%(X(_cx)-34,(Y(max(ys))+Y(min(ys)))/2+13,CELL_SPREAD))
lx=x1+22
s.append('<text x="%d" y="40" class="lgh">BASE RECIPE AT</text>'%lx)
for i,(lab,pt) in enumerate([("96k, lr 1e-4","pt3"),("96k, lr 3e-4","pt2"),("72k, lr 3e-4","pt4"),("144k, lr 3e-4","pt5")]):
    s.append('<circle cx="%d" cy="%d" r="5" class="pt %s"/><text x="%d" y="%d" class="lg">%s</text>'%(lx+6,60+i*22,pt,lx+19,64+i*22,lab))
s.append('<circle cx="%d" cy="148" r="3.6" class="pt ptx"/><text x="%d" y="152" class="lg">every other model</text>'%(lx+6,lx+19))
offscale_note(s, lx, 184)
s.append('</svg>'); open(OUT+"/g3.svg","w").write("\n".join(s))
print("charts 1 and 3 rebuilt with clickable dots")

# ---------- 5: by trained date (LOG y) ----------
DAYS=["2026-09-05","2026-09-06","2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-12"]
W,H=880,440; L,Rm,T,B=84,206,30,64
x0,x1,y0,y1=L,W-Rm,T,H-B
YLO,YHI=0.600,0.740
XD=lambda i,k=0: x0+(i+0.5)/len(DAYS)*(x1-x0)+k
YD=lambda v: y0+(math.log(YHI)-math.log(v))/(math.log(YHI)-math.log(YLO))*(y1-y0)
s=['<svg viewBox="0 0 %d %d">'%(W,H)]
for v in YT:
    s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid"/>'%(x0,YD(v),x1,YD(v)))
    s.append('<text x="%d" y="%.1f" class="ax ar">%.2f</text>'%(x0-11,YD(v)+4,v))
for i,d in enumerate(DAYS):
    n=sum(1 for r in ONSCALE if r["tr"]==d)
    s.append('<text x="%.1f" y="%d" class="ax am">%s</text>'%(XD(i),y1+21,d[5:]))
    s.append('<text x="%.1f" y="%d" class="axs am">%d model%s</text>'%(XD(i),y1+37,n,"s" if n!=1 else ""))
s.append('<text x="%d" y="%d" class="axl am">the day the model was trained</text>'%((x0+x1)/2,y1+56))
s.append('<text x="17" y="%d" class="axl am" transform="rotate(-90 17 %d)">validation cross-entropy (log)</text>'%((y0+y1)/2,(y0+y1)/2))
best=9; pathpts=[]; DROPS=[]
for i in range(len(DAYS)):
    day=[r["ce"] for r in ONSCALE if r["tr"]==DAYS[i]]
    prev=best
    if day: best=min(best,min(day))
    DROPS.append((prev-best) if prev<9 and best<prev else 0.0)
    xa=x0+i/len(DAYS)*(x1-x0); xb=x0+(i+1)/len(DAYS)*(x1-x0)
    pathpts.append("%.1f,%.1f %.1f,%.1f"%(xa,YD(best),xb,YD(best)))
BIG_I=max(range(len(DAYS)),key=lambda i:DROPS[i]); BIG_DROP=DROPS[BIG_I]; BIG_DAY=DAYS[BIG_I]
BIG_BEATS_REST=BIG_DROP>sum(DROPS[BIG_I+1:])
s.append('<polyline class="ln ln5" points="'+" ".join(pathpts)+'"/>')
for i,dd in enumerate(DAYS):
    day=[r for r in ONSCALE if r["tr"]==dd]
    for k,d in enumerate(sorted(day,key=lambda z:z["ce"])):
        off=(k-(len(day)-1)/2)*9
        s.append(dot(XD(i,off),YD(d["ce"]), 6 if d["ck"]=="3cd27716" else 4.2,
                     "pt pt2" if d["ck"]=="3cd27716" else "pt pt1", d))
_ce=list(ONSCALE)
_bst=min(_ce,key=lambda d:d["ce"]); _bi=DAYS.index(_bst["tr"])
s.append('<text x="%.1f" y="%.1f" class="slope s2 am">%s in one day</text>'%(XD(BIG_I),YD(_bst["ce"]-0.0021),fmt_signed(-BIG_DROP)))
s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ref"/>'%(XD(_bi)+18,YD(_bst["ce"]),x1-6,YD(_bst["ce"])))
s.append('<text x="%.1f" y="%.1f" class="reft" text-anchor="end">programme best, unbeaten since %s Sep</text>'%(x1-6,YD(_bst["ce"])-8,_bst["tr"][8:]))
lx=x1+22
s.append('<text x="%d" y="44" class="lgh">READING IT</text>'%lx)
s.append('<circle cx="%d" cy="64" r="4.2" class="pt pt1"/><text x="%d" y="68" class="lg">one model</text>'%(lx+6,lx+19))
s.append('<circle cx="%d" cy="86" r="6" class="pt pt2"/><text x="%d" y="90" class="lg">the deployed leader</text>'%(lx+6,lx+19))
s.append('<line x1="%d" y1="106" x2="%d" y2="106" class="ln ln5"/><text x="%d" y="110" class="lg">best so far</text>'%(lx,lx+13,lx+19))
_ce=[d for d in R if d["ce"] is not None]
_bst=min(_ce,key=lambda d:d["ce"])
_aft=[d for d in _ce if d["tr"]>_bst["tr"]]
_bt=[d for d in _aft if d["ce"]<_bst["ce"]]
# derived, not hand-counted: a hardcoded "31 of the 38" stood here and was simply wrong.
for i,t in enumerate(["%d of the %d models"%(len(_aft),len(_ce)),"were trained AFTER","the best was set.","%s beat it."%("None" if not _bt else str(len(_bt)))]):
    s.append('<text x="%d" y="%d" class="lgs">%s</text>'%(lx,142+i*16,t))
offscale_note(s, lx, 216)
s.append('</svg>'); open(OUT+"/g5.svg","w").write("\n".join(s))

# ---------- leader-axis charts: 2 (data), 4 (width), 6 (date) ----------
SCR=[d for d in R if (d["w32"] and d["w32"] not in ("GAP",)) or (d["ten"] and d["ten"] not in ("QUEUED","RUNNING","SCREENING","CODEX"))]
def eff(d):
    if d["ck"]=="3cd27716": return (0.0,None,None,"ref")
    t=d["ten"]
    if t and t not in ("REF","CONTROL","QUEUED","RUNNING","SCREENING","CODEX"):
        m,rest=t.split(" [",1); lo,hi=rest.rstrip("]").split(", ")
        return (float(m),float(lo),float(hi),"ten")
    w=d["w32"]
    if w and w not in ("REF","GAP"):
        w=w.replace("RES","").replace(" SUPERSEDED","")
        m,rest=w.split(" [",1); lo,hi=rest.rstrip("]").split(", ")
        return (float(m),float(lo),float(hi),"one")
    return None
def leaderchart(keyfn, XLO, XHI, xt, xlab, out, extra):
    W,H=880,400; L,Rm,T,B=84,206,30,64
    x0,x1,y0,y1=L,W-Rm,T,H-B
    YLO2,YHI2=-0.135,0.045
    X=lambda v,k=0: lgs(v,XLO,XHI,x0,x1)+k
    Y=lambda v: y0+(YHI2-v)/(YHI2-YLO2)*(y1-y0)
    s=['<svg viewBox="0 0 %d %d">'%(W,H)]
    for v in [-0.12,-0.09,-0.06,-0.03,0,0.03]:
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid%s"/>'%(x0,Y(v),x1,Y(v)," zero" if v==0 else ""))
        s.append('<text x="%d" y="%.1f" class="ax ar">%+.2f</text>'%(x0-11,Y(v)+4,v))
    for v,lab in xt:
        s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="grid"/>'%(X(v),y0,X(v),y1))
        s.append('<text x="%.1f" y="%d" class="ax am">%s</text>'%(X(v),y1+21,lab))
    s.append('<text x="%d" y="%d" class="axl am">%s</text>'%((x0+x1)/2,y1+45,xlab))
    s.append('<text x="17" y="%d" class="axl am" transform="rotate(-90 17 %d)">effect vs the leader</text>'%((y0+y1)/2,(y0+y1)/2))
    grp={}
    for d in SCR:
        e=eff(d)
        if e: grp.setdefault(keyfn(d),[]).append((d,e))
    for xv,items in grp.items():
        for k,(d,(m,lo,hi,inst)) in enumerate(sorted(items,key=lambda z:-z[1][0])):
            off=(k-(len(items)-1)/2)*17
            if inst=="ref":
                s.append(dot(X(xv,off),Y(0),6,"pt pt2",d))
                s.append('<text x="%.1f" y="%.1f" class="lab am">leader</text>'%(X(xv,off),Y(0)-13)); continue
            col="ci1" if inst=="one" else "ci2"; pt="pt3" if inst=="one" else "pt2"
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci %s"/>'%(X(xv,off),Y(lo),X(xv,off),Y(hi),col))
            for e2 in (lo,hi):
                s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci %s"/>'%(X(xv,off)-5,Y(e2),X(xv,off)+5,Y(e2),col))
            s.append(dot(X(xv,off),Y(m),4.8,"pt "+pt,d))
    lx=x1+22
    s.append('<text x="%d" y="44" class="lgh">INSTRUMENT</text>'%lx)
    s.append('<circle cx="%d" cy="64" r="4.8" class="pt pt3"/><text x="%d" y="68" class="lg">one 520-deal window</text>'%(lx+6,lx+19))
    s.append('<circle cx="%d" cy="86" r="4.8" class="pt pt2"/><text x="%d" y="90" class="lg">ten windows</text>'%(lx+6,lx+19))
    for i,t in enumerate(extra):
        s.append('<text x="%d" y="%d" class="lgs">%s</text>'%(lx,124+i*16,t))
    s.append('</svg>'); open(out,"w").write("\n".join(s))
leaderchart(lambda d:d["rec"], 9e5,2.4e7,[(1e6,"1M"),(2e6,"2M"),(5e6,"5M"),(1e7,"10M"),(2e7,"20M")],
  "training records (log scale)",OUT+"/g2.svg",
  ["Only 3 of 7 corpus sizes","have ANY leader number.","Nothing below 14M does.","Click a dot for detail."])
leaderchart(lambda d:d["par"], 2.0e5,5.5e6,[(2.72e5,"h256"),(6.11e5,"h512"),(1.48e6,"h1024"),(4.02e6,"h2048")],
  "parameters (log scale)",OUT+"/g4.svg",
  ["Every width screened, but","at one corpus size and","mostly one learning rate."])
print("all charts rebuilt")

# ---------- 6: leader effect by trained date ----------
W,H=880,430; L,Rm,T,B=84,206,30,64
x0,x1,y0,y1=L,W-Rm,T,H-B
YLO2,YHI2=-0.135,0.045
XE=lambda i,k=0: x0+(i+0.5)/len(DAYS)*(x1-x0)+k
YE=lambda v: y0+(YHI2-v)/(YHI2-YLO2)*(y1-y0)
s=['<svg viewBox="0 0 %d %d">'%(W,H)]
for v in [-0.12,-0.09,-0.06,-0.03,0,0.03]:
    s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid%s"/>'%(x0,YE(v),x1,YE(v)," zero" if v==0 else ""))
    s.append('<text x="%d" y="%.1f" class="ax ar">%+.2f</text>'%(x0-11,YE(v)+4,v))
byday={}
for d in SCR:
    e=eff(d)
    if e: byday.setdefault(d["tr"],[]).append((d,e))
for i,dd in enumerate(DAYS):
    n=len(byday.get(dd,[]))
    s.append('<text x="%.1f" y="%d" class="ax am">%s</text>'%(XE(i),y1+21,dd[5:]))
    s.append('<text x="%.1f" y="%d" class="axs am">%s</text>'%(XE(i),y1+37,"%d vs leader"%n if n else "none vs leader"))
s.append('<text x="%d" y="%d" class="axl am">the day the model was trained</text>'%((x0+x1)/2,y1+56))
s.append('<text x="17" y="%d" class="axl am" transform="rotate(-90 17 %d)">effect vs the leader</text>'%((y0+y1)/2,(y0+y1)/2))
for i,dd in enumerate(DAYS):
    items=byday.get(dd,[])
    for k,(d,(m,lo,hi,inst)) in enumerate(sorted(items,key=lambda z:-z[1][0])):
        off=(k-(len(items)-1)/2)*26
        if inst=="ref":
            s.append(dot(XE(i,off),YE(0),6,"pt pt2",d))
            s.append('<text x="%.1f" y="%.1f" class="lab am">leader</text>'%(XE(i,off),YE(0)-13)); continue
        col="ci1" if inst=="one" else "ci2"; pt="pt3" if inst=="one" else "pt2"
        s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci %s"/>'%(XE(i,off),YE(lo),XE(i,off),YE(hi),col))
        for e2 in (lo,hi):
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci %s"/>'%(XE(i,off)-6,YE(e2),XE(i,off)+6,YE(e2),col))
        s.append(dot(XE(i,off),YE(m),5,"pt "+pt,d))
lx=x1+22
s.append('<text x="%d" y="44" class="lgh">INSTRUMENT</text>'%lx)
s.append('<circle cx="%d" cy="64" r="5" class="pt pt3"/><text x="%d" y="68" class="lg">one 520-deal window</text>'%(lx+6,lx+19))
s.append('<circle cx="%d" cy="86" r="5" class="pt pt2"/><text x="%d" y="90" class="lg">ten windows</text>'%(lx+6,lx+19))
def _hasld(d):
    return (d["w32"] and d["w32"]!="GAP") or (d["ten"] and d["ten"] not in ("QUEUED","RUNNING","SCREENING","CODEX"))
_no=sum(1 for d in R if not _hasld(d))
for i,t in enumerate(["The 10 Sep points are","NOT better models. They","are the same question","asked with a better","instrument.","","%d of %d models have"%(_no,len(R)),"no point here at all."]):
    s.append('<text x="%d" y="%d" class="lgs">%s</text>'%(lx,122+i*16,t))
s.append('</svg>'); open(OUT+"/g6.svg","w").write("\n".join(s))
print("chart 6 built; total charts:", 6)

# ---------- leader-axis charts, NOW WITH the vs-MC-LCB series too ----------
def parse(v):
    v=v.replace("RES","")
    m,rest=v.split(" [",1); lo,hi=rest.rstrip("]").split(", ")
    return float(m),float(lo),float(hi)
def both(keyfn, XLO, XHI, xt, xlab, out, extra):
    W,H=880,470; L,Rm,T,B=84,206,30,64
    x0,x1,y0,y1=L,W-Rm,T,H-B
    YLO2,YHI2=-0.145,0.195
    X=lambda v,k=0: lgs(v,XLO,XHI,x0,x1)+k
    Y=lambda v: y0+(YHI2-v)/(YHI2-YLO2)*(y1-y0)
    s=['<svg viewBox="0 0 %d %d">'%(W,H)]
    for v in [-0.12,-0.08,-0.04,0,0.04,0.08,0.12,0.16]:
        s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid%s"/>'%(x0,Y(v),x1,Y(v)," zero" if v==0 else ""))
        s.append('<text x="%d" y="%.1f" class="ax ar">%+.2f</text>'%(x0-11,Y(v)+4,v))
    for v,lab in xt:
        s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="grid"/>'%(X(v),y0,X(v),y1))
        s.append('<text x="%.1f" y="%d" class="ax am">%s</text>'%(X(v),y1+21,lab))
    s.append('<text x="%d" y="%d" class="axl am">%s</text>'%((x0+x1)/2,y1+45,xlab))
    s.append('<text x="17" y="%d" class="axl am" transform="rotate(-90 17 %d)">effect per round</text>'%((y0+y1)/2,(y0+y1)/2))
    s.append('<text x="%d" y="%.1f" class="lab">beats MC-LCB &#8593;</text>'%(x0+6,Y(0.175)))
    s.append('<text x="%d" y="%.1f" class="lab">loses to the leader &#8595;</text>'%(x0+6,Y(-0.125)))
    # vs MC-LCB
    g={}
    for d in R:
        if d["mc"]: g.setdefault(keyfn(d),[]).append(d)
    for xv,items in g.items():
        for k,d in enumerate(sorted(items,key=lambda z:-parse(z["mc"])[0])):
            off=(k-(len(items)-1)/2)*15
            m,lo,hi=parse(d["mc"])
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci ci3"/>'%(X(xv,off),Y(lo),X(xv,off),Y(hi)))
            for e in (lo,hi):
                s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci ci3"/>'%(X(xv,off)-5,Y(e),X(xv,off)+5,Y(e)))
            s.append(dot(X(xv,off),Y(m),4.8,"pt pt6",d))
    # vs the leader
    g2={}
    for d in SCR:
        e=eff(d)
        if e: g2.setdefault(keyfn(d),[]).append((d,e))
    for xv,items in g2.items():
        for k,(d,(m,lo,hi,inst)) in enumerate(sorted(items,key=lambda z:-z[1][0])):
            off=(k-(len(items)-1)/2)*15
            if inst=="ref":
                s.append(dot(X(xv,off),Y(0),6,"pt pt2",d)); continue
            col="ci1" if inst=="one" else "ci2"; pt="pt3" if inst=="one" else "pt2"
            s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci %s"/>'%(X(xv,off),Y(lo),X(xv,off),Y(hi),col))
            for e2 in (lo,hi):
                s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ci %s"/>'%(X(xv,off)-5,Y(e2),X(xv,off)+5,Y(e2),col))
            s.append(dot(X(xv,off),Y(m),4.8,"pt "+pt,d))
    lx=x1+22
    s.append('<text x="%d" y="44" class="lgh">BENCHMARK</text>'%lx)
    s.append('<circle cx="%d" cy="64" r="4.8" class="pt pt6"/><text x="%d" y="68" class="lg">vs MC-LCB</text>'%(lx+6,lx+19))
    s.append('<text x="%d" y="84" class="lgs">one 520-deal window</text>'%(lx+19))
    s.append('<circle cx="%d" cy="108" r="4.8" class="pt pt3"/><text x="%d" y="112" class="lg">vs leader, 1 window</text>'%(lx+6,lx+19))
    s.append('<circle cx="%d" cy="130" r="4.8" class="pt pt2"/><text x="%d" y="134" class="lg">vs leader, 10 windows</text>'%(lx+6,lx+19))
    for i,t in enumerate(extra):
        s.append('<text x="%d" y="%d" class="lgs">%s</text>'%(lx,164+i*16,t))
    s.append('</svg>'); open(out,"w").write("\n".join(s))
both(lambda d:d["rec"], 9e5,2.4e7,[(1e6,"1M"),(2e6,"2M"),(5e6,"5M"),(1e7,"10M"),(2e7,"20M")],
  "training records (log scale)",OUT+"/h2.svg",
  ["Every point above zero","is vs the OLD production","bot. Every point below","is vs the CURRENT leader.","Same models, both true."])
both(lambda d:d["par"], 2.0e5,5.5e6,[(2.72e5,"h256"),(6.11e5,"h512"),(1.48e6,"h1024"),(4.02e6,"h2048")],
  "parameters (log scale)",OUT+"/h4.svg",
  ["Both benchmarks, same","models, one axis."])
print("dual-benchmark charts built")

# ---------- derived caption numbers and the by-day table ----------
NMC=sum(1 for d in R if d["mc"])
NLD=sum(1 for d in R if _hasld(d))
_since=[d for d in _ce if d["tr"]>_bst["tr"]]
_effs=[(d,eff(d)) for d in SCR if eff(d) and eff(d)[3]!="ref"]
_above=sum(1 for d,(m,lo,hi,inst) in _effs if lo>0)
_ten=[(d,eff(d)) for d in R if d["ten"] and eff(d) and eff(d)[3]=="ten"]
_ten_cross=sum(1 for d,(m,lo,hi,inst) in _ten if lo<=0<=hi)   # touching zero is not resolving
_lead=BYCK["3cd27716"]; _lead_mc=parse(_lead["mc"])[0]
_paired=[d for d in R if d["mc"] and d["w32"] and d["w32"] not in ("REF","GAP") and d["ck"]!="3cd27716"]
_paired_exact=sum(1 for d in _paired if abs(parse(d["w32"].replace(" SUPERSEDED",""))[0]-(parse(d["mc"])[0]-_lead_mc))<5e-5)
_b2=series("base_v2","rec"); LAST_DOUBLING=_b2[-1][1]-[p for p in _b2 if abs(p[0]*2-_b2[-1][0])<0.05*_b2[-1][0]][0][1]
# result-dependent prose: corpus coverage of leader comparisons, the 144k width line
_ld_rows=[d for d,e in _effs]
_sizes_all=sorted({d["cl"] for d in R if d["ce"] is not None}, key=lambda c: REC.get(c, 0))
_sizes_ld=sorted({d["cl"] for d in _ld_rows}, key=lambda c: REC.get(c, 0))
_min_ld_rec=min(d["rec"] for d in _ld_rows)
_w144=[BYCK[c] for c in SERIES["width_3e4_144k"]]; _w144.sort(key=lambda d:d["par"])
_w144_mono=all(a["ce"]<b["ce"] for a,b in zip(_w144,_w144[1:]))
_w144_by={d["w"]:d for d in _w144}
_w144_gap=_w144_by[512]["ce"]-_w144_by[256]["ce"] if 512 in _w144_by and 256 in _w144_by else None
_w144_worst=max(_w144,key=lambda d:d["ce"]); _w144_best=min(_w144,key=lambda d:d["ce"])
_w144_span=_w144_worst["ce"]-_w144_best["ce"]
_lr14=[BYCK[c] for c in SERIES["width_lr1e4_96k"]]; _lr14_best=min(_lr14,key=lambda d:d["ce"])
open(OUT+"/_counts.json","w").write(__import__("json").dumps(dict(
    sizes_all=len(_sizes_all), sizes_with_leader=len(_sizes_ld), min_leader_records=_min_ld_rec,
    w144_monotone=_w144_mono, w144_gap_256_vs_512=_w144_gap, w144_worst_w=_w144_worst["w"], w144_best_w=_w144_best["w"],
    w144_worst_over_best_params=_w144_worst["par"]/_w144_best["par"], w144_256_param_frac=PAR[256]/PAR[512],
    w144_span=_w144_span, w144_n=len(_w144), w144_rec=_w144[0]["rec"], lr14_best_w=_lr14_best["w"],
    models=len(R), with_ce=NCE, off_scale=[(d["n"],d["ce"]) for d in OFFSCALE], beat_mc=NMC, with_leader=NLD, without_leader=len(R)-NLD,
    since_best=len(_since), best_day=_bst["tr"], best_ce=_bst["ce"],
    above_leader=_above, ten_total=len(_ten), ten_cross=_ten_cross,
    enc_gap=ENC_GAP, cell_n=CELL_N, cell_spread=CELL_SPREAD,
    big_day=BIG_DAY, big_drop=BIG_DROP, big_beats_rest=BIG_BEATS_REST,
    paired_one=len(_paired), paired_exact=_paired_exact, last_doubling=LAST_DOUBLING)))
rows=[]; run=9.0; prev=None
for dd in DAYS:
    day=[d for d in R if d["tr"]==dd and d["ce"] is not None]
    if not day: continue
    b=min(day,key=lambda z:z["ce"]); newrun=min(run,b["ce"])
    gained=("&minus;%.4f"%(run-newrun)) if newrun<run and run<9 else ("&mdash;" if run<9 else "start")
    names=", ".join(d["n"] for d in sorted(day,key=lambda z:z["ce"]))
    rows.append('<tr><td class="mono">%s</td><td class="n">%d</td><td class="n">%.5f<br><span class="small">%s</span></td><td class="n">%.5f</td><td class="n">%s</td><td>%s</td></tr>'%(dd[5:],len(day),b["ce"],b["n"],newrun,gained,names))
    run=newrun
open(OUT+"/daytable_rows.html","w").write("\n".join(rows))
print("counts:",open(OUT+"/_counts.json").read()); print("day rows:",len(rows))
