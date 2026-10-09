"""Generate reproducible offline search data from Unicode 17.0 (no runtime networking)."""
import argparse,hashlib,json,urllib.request,unicodedata,zipfile
from pathlib import Path
from datetime import datetime,timezone
BASE="https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip"
LICENSE="https://www.unicode.org/license.txt"
def download(url,path):
    if path.exists(): return path.read_bytes()
    request=urllib.request.Request(url,headers={"User-Agent":"QinBan-offline-search-data/0.4"})
    with urllib.request.urlopen(request,timeout=40) as response: data=response.read(30*1024*1024+1)
    if len(data)>30*1024*1024: raise ValueError("source exceeded 30 MiB")
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as f: f.write(data)
    return data

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--cache",type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    data=download(BASE,args.cache/"Unihan-17.0.0.zip")
    license_data=download(LICENSE,args.cache/"Unicode-License.txt")
    if b"UNICODE LICENSE" not in license_data: raise ValueError("unexpected Unicode license document")
    out=root/"QinBan.Core"/"Resources";out.mkdir(exist_ok=True)
    pronunciations={};variants={}
    with zipfile.ZipFile(args.cache/"Unihan-17.0.0.zip") as z:
        for line in z.read("Unihan_Readings.txt").decode("utf-8").splitlines():
            parts=line.split("\t")
            if len(parts)==3 and parts[1]=="kMandarin":
                value=parts[2].split()[0]
                value="".join(c for c in unicodedata.normalize("NFD",value.lower()) if unicodedata.category(c)!="Mn")
                pronunciations[int(parts[0][2:],16)]=value
        for line in z.read("Unihan_Variants.txt").decode("utf-8").splitlines():
            parts=line.split("\t")
            if len(parts)==3 and parts[1]=="kSimplifiedVariant":
                target=parts[2].split()[0].split("<")[0]
                variants[int(parts[0][2:],16)]=int(target[2:],16)
    files={
        "pinyin-17.tsv":"# Unicode 17.0 kMandarin; primary pronunciation; not context-aware\n"+"".join(f"{cp:X}\t{value}\n" for cp,value in sorted(pronunciations.items())),
        "simplified-17.tsv":"# Unicode 17.0 kSimplifiedVariant; primary variant for search only\n"+"".join(f"{cp:X}\t{value:X}\n" for cp,value in sorted(variants.items()))
    }
    manifest={"sourceVersion":"17.0.0","sourceUrl":BASE,"licenseUrl":LICENSE,"retrievedAtUtc":datetime.now(timezone.utc).isoformat(),"archiveSha256":hashlib.sha256(data).hexdigest(),"pinyinEntries":len(pronunciations),"variantEntries":len(variants),"limitations":"primary reading/variant only; contextual polyphony must use aliases","generated":[]}
    for name,text in files.items():
        path=out/name;path.write_text(text,encoding="utf-8",newline="\n")
        manifest["generated"].append({"path":str(path.relative_to(root)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    (root/"licenses"/"Unicode-License.txt").write_bytes(license_data)
    (root/"tools"/"search-data-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
