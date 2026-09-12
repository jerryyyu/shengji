import math
exec(open(MODELS).read()); M=[m for m in M if m[1] not in TABLE_ONLY]
PAR={256:272716,512:610764,1024:1483468,2048:4015308}
REC={"8k":1168124,"16k":2341808,"48k":7043156,"72k":10559236,"96k":14077520,
     "128k":18764912,"144k":20939532}
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
# ---------- 1: data vs val_ce (LOG y) ----------
s,X,Y,x0,x1,y0,y1=frame(880,470,84,200,26,64,9e5,2.4e7,0.600,0.740,YT,
  [(1e6,"1M"),(2e6,"2M"),(5e6,"5M"),(1e7,"10M"),(2e7,"20M")],
  "training records (log scale)","validation cross-entropy (log)",ylog=True)
b1=[(1168124,0.72772),(7043156,0.64672),(10559236,0.65941),(14077520,0.65944)]
b2=[(10559236,0.62270),(14077520,0.62182),(18764912,0.62313),(20939532,0.61912)]
s.append('<polyline class="ln ln1" points="'+" ".join("%.1f,%.1f"%(X(a),Y(b)) for a,b in b1)+'"/>')
s.append('<polyline class="ln ln2" points="'+" ".join("%.1f,%.1f"%(X(a),Y(b)) for a,b in b2)+'"/>')
s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="drop"/>'%(X(14077520),Y(0.65944),X(14077520),Y(0.62182)))
s.append('<text x="%.1f" y="%.1f" class="note" text-anchor="end">encoder v1 &#8594; v2</text>'%(X(14077520)-12,(Y(0.65944)+Y(0.62182))/2))
s.append('<text x="%.1f" y="%.1f" class="noteb" text-anchor="end">&#8722;0.0376 at identical data</text>'%(X(14077520)-12,(Y(0.65944)+Y(0.62182))/2+16))
n1=n2=n3=0
for d in R:
    if d["ce"] is None: continue
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
NCE=sum(1 for d in R if d["ce"] is not None)
for i,t in enumerate(["All %d models with a"%NCE,"validation number.","Click or tab to any dot","for its full record."]):
    s.append('<text x="%d" y="%d" class="lgs">%s</text>'%(lx,140+i*16,t))
s.append('</svg>'); open(OUT+"/g1.svg","w").write("\n".join(s))

# ---------- 3: width vs val_ce (LOG y) ----------
s,X,Y,x0,x1,y0,y1=frame(880,420,84,200,26,70,2.0e5,5.5e6,0.602,0.740,
  [0.62,0.64,0.66,0.68,0.70,0.72,0.74],
  [(2.72e5,"h256"),(6.11e5,"h512"),(1.48e6,"h1024"),(4.02e6,"h2048")],
  "parameters (log scale)","validation cross-entropy (log)",ylog=True)
for v,lab in [(2.72e5,"273k"),(6.11e5,"611k"),(1.48e6,"1.48M"),(4.02e6,"4.02M")]:
    s.append('<text x="%.1f" y="%d" class="axs am">%s</text>'%(X(v),y1+37,lab))
SER=[([(272716,0.61189),(610764,0.61058),(1483468,0.60661),(4015308,0.60830)],"ln3","pt3"),
     ([(610764,0.62182),(1483468,0.62537)],"ln2","pt2"),
     ([(610764,0.62270),(1483468,0.62320)],"ln4","pt4"),
     ([(272716,0.61525),(610764,0.61912),(1483468,0.62043),(4015308,0.62314)],"ln5","pt5")]
for pts,ln,_ in SER:
    s.append('<polyline class="ln %s" points="'%ln+" ".join("%.1f,%.1f"%(X(a),Y(b)) for a,b in pts)+'"/>')
for d in R:
    if d["ce"] is None: continue
    cls=None
    for pts,_,pt in SER:
        if any(abs(b-d["ce"])<1e-5 and a==d["par"] for a,b in pts): cls="pt "+pt; break
    s.append(dot(X(d["par"]),Y(d["ce"]), 5 if cls else 3.6, cls or "pt ptx", d))
ys=[0.62270,0.62300,0.61750,0.62260,0.62370,0.62180]
s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="spread"/>'%(X(610764)-28,Y(max(ys)),X(610764)-28,Y(min(ys))))
s.append('<text x="%.1f" y="%.1f" class="lab ar">6 models, one cell</text>'%(X(610764)-34,(Y(max(ys))+Y(min(ys)))/2))
s.append('<text x="%.1f" y="%.1f" class="lab ar">spread 0.0062</text>'%(X(610764)-34,(Y(max(ys))+Y(min(ys)))/2+13))
lx=x1+22
s.append('<text x="%d" y="40" class="lgh">BASE RECIPE AT</text>'%lx)
for i,(lab,pt) in enumerate([("96k, lr 1e-4","pt3"),("96k, lr 3e-4","pt2"),("72k, lr 3e-4","pt4"),("144k, lr 3e-4","pt5")]):
    s.append('<circle cx="%d" cy="%d" r="5" class="pt %s"/><text x="%d" y="%d" class="lg">%s</text>'%(lx+6,60+i*22,pt,lx+19,64+i*22,lab))
s.append('<circle cx="%d" cy="148" r="3.6" class="pt ptx"/><text x="%d" y="152" class="lg">every other model</text>'%(lx+6,lx+19))
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
    n=sum(1 for r in R if r["tr"]==d and r["ce"])
    s.append('<text x="%.1f" y="%d" class="ax am">%s</text>'%(XD(i),y1+21,d[5:]))
    s.append('<text x="%.1f" y="%d" class="axs am">%d model%s</text>'%(XD(i),y1+37,n,"s" if n!=1 else ""))
s.append('<text x="%d" y="%d" class="axl am">the day the model was trained</text>'%((x0+x1)/2,y1+56))
s.append('<text x="17" y="%d" class="axl am" transform="rotate(-90 17 %d)">validation cross-entropy (log)</text>'%((y0+y1)/2,(y0+y1)/2))
best=9; pathpts=[]
for i in range(len(DAYS)):
    day=[r["ce"] for r in R if r["tr"]==DAYS[i] and r["ce"]]
    if day: best=min(best,min(day))
    xa=x0+i/len(DAYS)*(x1-x0); xb=x0+(i+1)/len(DAYS)*(x1-x0)
    pathpts.append("%.1f,%.1f %.1f,%.1f"%(xa,YD(best),xb,YD(best)))
s.append('<polyline class="ln ln5" points="'+" ".join(pathpts)+'"/>')
for i,dd in enumerate(DAYS):
    day=[r for r in R if r["tr"]==dd and r["ce"]]
    for k,d in enumerate(sorted(day,key=lambda z:z["ce"])):
        off=(k-(len(day)-1)/2)*9
        s.append(dot(XD(i,off),YD(d["ce"]), 6 if d["ck"]=="3cd27716" else 4.2,
                     "pt pt2" if d["ck"]=="3cd27716" else "pt pt1", d))
s.append('<text x="%.1f" y="%.1f" class="slope s2 am">&#8722;0.0365 in one day</text>'%(XD(2),YD(0.6045)))
s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ref"/>'%(XD(3)+18,YD(0.6066),x1-6,YD(0.6066)))
s.append('<text x="%.1f" y="%.1f" class="reft" text-anchor="end">programme best, unbeaten since 08 Sep</text>'%(x1-6,YD(0.6066)-8))
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
open(OUT+"/_counts.json","w").write(__import__("json").dumps(dict(
    models=len(R), with_ce=NCE, beat_mc=NMC, with_leader=NLD, without_leader=len(R)-NLD,
    since_best=len(_since), best_day=_bst["tr"], best_ce=_bst["ce"])))
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
