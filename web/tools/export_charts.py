"""Materializa o mesmo catálogo/transformações do app Python para o cliente web."""
from pathlib import Path
import sys,json,math,hashlib,re,argparse,os
import pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from utils.sgs_credit_analytics import to_wide
from tabs.mercado_credito import SECOES_DECK,_figuras_da_secao
from utils.mercado_imobiliario import CHARTS
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,default=ROOT,help='Raiz explícita da geração de fontes')
parser.add_argument('--output',type=Path)
args=parser.parse_args()
SOURCE_ROOT=args.root.resolve()
OUT=args.output or SOURCE_ROOT/'web/public/data';OUT.mkdir(parents=True,exist_ok=True)
def dump(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf8')
def value(v):
    try:return float(v) if math.isfinite(float(v)) else None
    except (TypeError,ValueError):return None
def fig_json(fig,key,section):
    meta=dict(fig.layout.meta or {});series=[]
    for tr in fig.data:
        if tr.y is None:continue
        points=[[pd.Timestamp(x).strftime('%Y-%m-%d') if isinstance(x,(pd.Timestamp,)) or hasattr(x,'year') or str(x)[:4].isdigit() and '-' in str(x) else str(x),value(y)] for x,y in zip(tr.x,tr.y)]
        series.append({'name':re.sub('<[^>]*>','',tr.name or ''), 'data':points,'type':'bar' if tr.type=='bar' else 'line','axis':1 if tr.yaxis=='y2' else 0})
    unit=fig.layout.yaxis.title.text or ''
    return {'id':key,'title':fig.layout.title.text or key,'section':section,'source':meta.get('source','BCB · SGS'),'unit':unit,'axes':[unit,fig.layout.yaxis2.title.text or unit] if any(t.yaxis=='y2' for t in fig.data) else [unit],'note':meta.get('source_note',''),'percent':'%' in unit,'stacked':fig.layout.barmode=='stack','series':series}
sgs=pd.read_parquet(SOURCE_ROOT/'data/bundled/mercado_credito_sgs/dados.parquet');wide=to_wide(sgs);wide.attrs['full_history']=wide.copy()
charts=[]
for section,key,render in SECOES_DECK:
    if render:
        for i,f in enumerate(_figuras_da_secao(render,wide)):charts.append(fig_json(f,f'{key}-{i}',section))
dump('sfn.json',charts)
imob=pd.read_parquet(SOURCE_ROOT/'data/bundled/mercado_imobiliario/dados.parquet')
specs=[{'id':s.key,'title':s.title,'section':s.section,'unit':s.unit,'scale':s.scale,'stacked':s.stacked,'note':s.note,'historical':s.historical,'prefix':s.prefix,'labels':s.labels} for s in CHARTS]
for uf in sorted(set(imob.uf)-{'na'}):
    rows=[]
    for s in CHARTS:
        sub=imob[(imob.uf==uf)&(imob.grafico==s.key)&(imob.linha=='')]
        rows.append({'id':s.key,'title':s.title,'section':s.section,'unit':s.unit,'stacked':s.stacked,'percent':s.unit.startswith('%'),'source':f'BCB · Olinda/MercadoImobiliario · {uf.upper()}','note':s.note,'historical':s.historical,'series':[{'name':label,'category':cat,'data':[[d.strftime('%Y-%m-%d'),value(v*s.scale)] for d,v in zip(sub[sub.categoria==cat].data,sub[sub.categoria==cat].valor)],'type':'bar' if s.stacked else 'line'} for cat,label in s.labels.items() if cat in set(sub.categoria)]})
    dump(f'imob-{uf}.json',rows)
dump('imob-catalog.json',specs)
dump('sgs-series.json',[{'alias':a,'code':int(d.codigo.iloc[0]),'name':d.nome_oficial.iloc[0],'unit':d.unidade.iloc[0],'data':[[v.strftime('%Y-%m-%d'),value(n)] for v,n in zip(d.data,d.valor)]} for a,d in sgs.groupby('serie') if int(d.codigo.iloc[0])>0])
manifest={'builtAt':pd.Timestamp.now(tz='UTC').isoformat(),'sourceCommit':os.environ.get('GITHUB_SHA') or os.environ.get('TOMACONTA_SOURCE_COMMIT'),'sourceInputs':{kind:hashlib.sha256((SOURCE_ROOT/'data/bundled'/kind/'dados.parquet').read_bytes()).hexdigest() for kind in ('mercado_credito_sgs','mercado_imobiliario')},'sources':[{'id':'sfn','name':'Séries SGS (competência por gráfico)','provider':'BCB · SGS','period':sgs.data.max().strftime('%Y-%m'),'rows':len(sgs),'url':'https://www.bcb.gov.br/estatisticas/estatisticasmonetariascredito'},{'id':'imob','name':'Mercado Imobiliário','provider':'BCB · Olinda','period':imob.data.max().strftime('%Y-%m'),'rows':len(imob),'url':'https://www.bcb.gov.br/estatisticas/mercadoimobiliario'}],'ufs':['br',*sorted(set(imob.uf)-{'na','br'})],'imobSections':list(dict.fromkeys(s.section for s in CHARTS)),'sfnSections':list(dict.fromkeys(c['section'] for c in charts)),'chartCount':len(charts)+24}
if (OUT/'extra.json').exists():
    extra=json.loads((OUT/'extra.json').read_text())
    for key,name,provider in [('scr','Inadimplência por renda e região','BCB · SCR.data'),('spb','Meios de pagamento','BCB · Olinda/MPV')]:
        group=[c for c in extra if c['section'].startswith('SCR') == (key=='scr')]
        manifest['sources'].append({'id':key,'name':name,'provider':provider,'period':max(c.get('latestPeriod','') for c in group),'rows':sum(len(s['data']) for c in group for s in c['series'])})
    manifest['chartCount']+=len(extra)
dump('manifest.json',manifest)
print('SGS charts',len(charts),'imob charts',24,'UFs',len(manifest['ufs']))
