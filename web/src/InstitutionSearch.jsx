import React,{useId,useMemo,useRef,useState} from 'react';
import {Search} from 'lucide-react';
import {groupName,searchInstitutions} from './landing-data.js';

const quarterLabel=period=>{const [year,quarter]=String(period||'').split('-Q');return quarter?`${['mar','jun','set','dez'][+quarter-1]}/${year}`:period||'N/D';};

export default function InstitutionSearch({catalog,onSelect,suggested=[],placeholder='Busque outra instituição',label='Buscar instituição'}){
  const id=useId(),ref=useRef(null);
  const [query,setQuery]=useState(''),[open,setOpen]=useState(false),[active,setActive]=useState(-1);
  const results=useMemo(()=>query.trim()?searchInstitutions(catalog,query,{limit:8}):suggested,[catalog,query,suggested]);
  function select(bank){onSelect(bank);setQuery('');setOpen(false);setActive(-1);}
  function keyDown(event){
    if(event.key==='Escape'){setOpen(false);setActive(-1);return;}
    if(event.key==='ArrowDown'||event.key==='ArrowUp'){
      event.preventDefault();setOpen(true);
      setActive(current=>results.length?Math.max(0,Math.min(results.length-1,current+(event.key==='ArrowDown'?1:-1))):-1);
    }
    if(event.key==='Enter'&&open&&results.length){event.preventDefault();select(results[Math.max(0,active)]);}
  }
  return <div className="institution-search" ref={ref} onBlur={event=>{if(!ref.current?.contains(event.relatedTarget))setOpen(false);}}>
    <div className="institution-search__field"><Search size={19} strokeWidth={1.6} aria-hidden="true"/><input
      type="search" role="combobox" aria-label={label} aria-autocomplete="list" aria-expanded={open}
      aria-controls={`${id}-results`} aria-activedescendant={open&&active>=0&&results[active]?`${id}-${results[active].id}`:undefined}
      autoComplete="off" spellCheck={false} placeholder={placeholder} value={query}
      onFocus={()=>setOpen(true)} onChange={event=>{setQuery(event.target.value);setActive(-1);setOpen(true);}} onKeyDown={keyDown}/>
    </div>
    {open&&<div className="institution-search__results" role="listbox" id={`${id}-results`} aria-label="Instituições encontradas">
      {results.map((bank,index)=><button type="button" role="option" id={`${id}-${bank.id}`} key={bank.id}
        className="institution-search__result" aria-selected={index===active}
        onPointerMove={()=>setActive(index)} onClick={()=>select(bank)}>
        <span>{bank.displayName||groupName(bank)}</span><small>{bank.perimeter} · {quarterLabel(bank.latestPeriod)}</small>
      </button>)}
      {query.trim()&&!results.length&&<p className="institution-search__empty" role="status">Nenhuma instituição com esse nome.</p>}
    </div>}
  </div>;
}
