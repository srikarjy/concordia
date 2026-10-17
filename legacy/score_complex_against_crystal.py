import json, itertools, numpy as np
from Bio.PDB import MMCIFParser
from Bio import Align
from Bio.PDB.Polypeptide import three_to_index, index_to_one
p=MMCIFParser(QUIET=True)
pred=p.get_structure("p","pred.cif")[0]; xt=p.get_structure("x","crystal.cif")[0]
def chains(m): return {c.id:[r for r in c if r.id[0]==" " and "CA" in r] for c in m}
_cp,cx=chains(pred),chains(xt); cp={"H":_cp["A"],"L":_cp["B"],"Y":_cp["C"]}
print("pred chains:",{k:len(v) for k,v in cp.items()}); print("xtal chains:",{k:len(v) for k,v in cx.items()})
def seq(rs):
    out=""
    for r in rs:
        try: out+=index_to_one(three_to_index(r.get_resname()))
        except Exception: out+="X"
    return out
al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
def matched(a,b):
    aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
    for (s1,e1),(s2,e2) in zip(*aln.aligned):
        for i,j in zip(range(s1,e1),range(s2,e2)): pa.append(a[i]);pb.append(b[j])
    return pa,pb
def xyz(rs): return np.array([r["CA"].coord for r in rs])
def kabsch(P,Q):
    pc,qc=P.mean(0),Q.mean(0); H=(P-pc).T@(Q-qc); U,S,Vt=np.linalg.svd(H); d=np.sign(np.linalg.det(Vt.T@U.T))
    R=Vt.T@np.diag([1,1,d])@U.T; return R,pc,qc
def rmsd(P,Q): return float(np.sqrt(((P-Q)**2).sum(1).mean()))
pairs={k:matched(cp[k],cx[k]) for k in ("H","L","Y")}
print("aligned residues:",{k:len(v[0]) for k,v in pairs.items()})
res={}
for k,(a,b) in pairs.items():
    P,Q=xyz(a),xyz(b); R,pc,qc=kabsch(P,Q); res[f"{k}_rmsd_CA"]=round(rmsd((P-pc)@R.T+qc,Q),2)
# antibody frame (H+L), then antigen RMSD in that frame (docking quality)
Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
R,pc,qc=kabsch(Pab,Qab); res["antibody_HL_rmsd_CA"]=round(rmsd((Pab-pc)@R.T+qc,Qab),2)
Pag=(xyz(pairs["Y"][0])-pc)@R.T+qc; Qag=xyz(pairs["Y"][1]); res["antigen_rmsd_in_antibody_frame_CA"]=round(rmsd(Pag,Qag),2)
# interface contacts (CA-CA < 8A between antibody and antigen) crystal vs predicted, residue-aligned
def contacts(chain_pairs, which):
    ab=[(k,i) for k in ("H","L") for i in range(len(chain_pairs[k][which]))]
    ag=[("Y",i) for i in range(len(chain_pairs["Y"][which]))]
    out=set()
    for (k,i) in ab:
        a=chain_pairs[k][which][i]["CA"].coord
        for (_,j) in ag:
            if np.linalg.norm(a-chain_pairs["Y"][which][j]["CA"].coord)<8.0: out.add((k,chain_pairs[k][which][i].id[1] if which==1 else None,j))
    return out
def cset(which):
    s=set()
    for k in ("H","L"):
        for i,ra in enumerate(pairs[k][which]):
            for j,rb in enumerate(pairs["Y"][which]):
                if np.linalg.norm(ra["CA"].coord-rb["CA"].coord)<8.0: s.add((k,i,j))
    return s
cx_set,cp_set=cset(1),cset(0)
tp=len(cx_set&cp_set); res["interface_pairs_crystal"]=len(cx_set); res["interface_pairs_pred"]=len(cp_set)
res["interface_precision"]=round(tp/max(1,len(cp_set)),3); res["interface_recall"]=round(tp/max(1,len(cx_set)),3)
print(json.dumps(res,indent=1)); json.dump(res,open("3hfm_scores.json","w"))
