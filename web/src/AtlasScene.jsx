import React, {useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {geoArea, geoMercator, geoPath} from 'd3-geo';
import './AtlasScene.css';

const finite = value => typeof value === 'number' && Number.isFinite(value);
const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
const mix = (a, b, t) => a + (b - a) * t;
const easeOut = t => 1 - Math.pow(1 - t, 4);
const pct = value => finite(value) ? `${value.toLocaleString('pt-BR', {minimumFractionDigits:1, maximumFractionDigits:1})}%` : 'N/D';
const featureUF = feature => feature.properties?.uf || feature.properties?.sigla || feature.properties?.SIGLA_UF || feature.properties?.abbrev_state;
export const ATLAS_RATE_SCALE=Object.freeze([{min:0,color:'#e0ecef'},{min:3,color:'#c7dfe7'},{min:5,color:'#9ac4d4'},{min:7,color:'#6ba5bd'},{min:10,color:'#47869f'},{min:15,color:'#2c657f'}]);
const mapFill=value=>!finite(value)?null:ATLAS_RATE_SCALE[ATLAS_RATE_SCALE.slice(1).filter(stop=>value>=stop.min).length].color;

function normalizeGeometry(geo) {
  return {...geo, features:(geo?.features || []).map(feature => geoArea(feature) > 2 * Math.PI
    ? {...feature, geometry:{...feature.geometry, coordinates:feature.geometry.type === 'Polygon'
      ? feature.geometry.coordinates.map(ring => ring.slice().reverse())
      : feature.geometry.coordinates.map(polygon => polygon.map(ring => ring.slice().reverse()))}}
    : feature)};
}

function plotFrame(width, height) {
  return {left:width < 500 ? 38 : 64, right:width - (width < 500 ? 32 : 62), top:46, axis:height - 80};
}

/** A collision-packed strip. Vertical displacement has no metric meaning. */
function distribute(values, width, height) {
  const frame = plotFrame(width, height);
  const center = (frame.top + frame.axis - 24) / 2;
  const available = frame.axis - 26 - frame.top;
  const baseRadius = width < 500 ? 5.3 : 7.5;
  const x = value => frame.left + clamp(value, 0, 25) / 25 * (frame.right - frame.left);
  const finiteNodes = values.map((value, index) => ({value,index})).filter(node => finite(node.value));
  const targetXs = finiteNodes.map(node => x(node.value));
  const densest = Math.max(1, ...targetXs.map(at => targetXs.filter(other => Math.abs(other - at) < baseRadius * 2 + 3).length));
  // The centered candidate stack has an odd number of slots. Reserve the next
  // odd count for an even dense cluster so its last point never falls back
  // onto another UF in the 25%+ overflow lane.
  const levels = Math.max(1, 2 * Math.ceil((densest - 1) / 2));
  const radius = Math.min(baseRadius, Math.max(2, (available / levels - 3) / 2));
  const separation = radius * 2 + 3;
  const candidates = [center];
  for (let step = 1; step <= 32; step++) {
    for (const sign of [-1,1]) {
      const y = center + sign * step * separation;
      if (y >= frame.top && y <= frame.axis - 24) candidates.push(y);
    }
  }
  const placed = [];
  const result = new Array(values.length);
  // Stable identity order avoids a gratuitous rank race when two rates cross.
  for (const node of finiteNodes) {
    const at = node.value > 25 ? frame.right + 13 : x(node.value);
    let cy = candidates.find(candidate => placed.every(other => Math.hypot(other.x - at, other.y - candidate) >= separation - .1));
    if (cy === undefined) cy = center + ((node.index * 37) % Math.max(1, Math.floor(available))) - available / 2;
    const point = {x:at,y:cy,r:radius,missing:false};
    placed.push(point); result[node.index] = point;
  }
  let missing = 0;
  values.forEach((value,index) => {
    if (!finite(value)) {
      result[index] = {x:frame.left + (missing % 12) * 19,y:frame.axis + 35 + Math.floor(missing / 12) * 13,r:3.4,missing:true};
      missing++;
    }
  });
  return result;
}

function annotationPositions(points, states, highlighted, selected, hovered, width, height, blend) {
  const frame=plotFrame(width,height),fontSize=width<500?11:13;
  const finiteDots=points.filter(point=>!point.dot.missing);
  const cloudTop=finiteDots.length?Math.min(...finiteDots.map(point=>point.dot.y-point.dot.r-2)):height*.4;
  const cloudBottom=finiteDots.length?Math.max(...finiteDots.map(point=>point.dot.y+point.dot.r+2)):height*.6;
  const attention=hovered>=0?hovered:selected;
  return points.map(point=>{
    const {index,x,y,dot}=point,state=states[index];
    const visible=(attention>=0?index===attention:highlighted.has(index))&&(blend>.5||(x>=0&&x<=width&&y>=0&&y<=height));
    const textWidth=Math.max(state.name.length*fontSize*.61,7*fontSize*.61);
    const end=dot.x>width*.62;
    const anchorX=end?clamp(dot.x,textWidth+32,width-18):clamp(dot.x,18,width-textWidth-32);
    const above=state.uf==='AM'?true:state.uf==='SP'?false:dot.y<=(cloudTop+cloudBottom)/2;
    const anchorY=dot.missing?clamp(dot.y-22,24,height-30):above
      ?clamp(cloudTop-30,24,Math.max(24,frame.axis-45))
      :clamp(cloudBottom+30,44,Math.max(44,frame.axis-34));
    const mapTextX=end?clamp(x-14,textWidth+10,width-10):clamp(x+14,10,width-textWidth-10);
    const mapTextY=clamp(y-9,18,height-24);
    return {...point,visible,end,
      textX:mix(mapTextX,anchorX+(end?-20:20),blend),textY:mix(mapTextY,anchorY-4,blend),
      iconX:mix(x,anchorX,blend),iconY:mix(y-18,anchorY,blend)};
  });
}

export default function AtlasScene({
  geo, states = [], series = [], month = 0, layout = 'map', selected = -1,
  highlights = [], playing = false, onSelect, onMonthChange, onPlayingChange,
  motionRequested = false,
}) {
  const rootRef = useRef(null), svgRef = useRef(null), mapRef = useRef(null), axisRef = useRef(null);
  const marksRef = useRef([]), polygonsRef = useRef([]), annotationsRef = useRef([]), drawRef = useRef(null), rafRef = useRef(null);
  const visibleRef = useRef(true), pageRef = useRef(typeof document === 'undefined' || !document.hidden);
  const cameraRef = useRef({k:1,x:0,y:0});
  const positionRef = useRef(clamp(month, 0, Math.max(0,series.length-1)));
  const lastEmittedRef = useRef(Math.floor(month)), lastPropMonthRef = useRef(month), previousTickRef = useRef(null);
  const currentRatesRef = useRef(series[Math.floor(month)]?.slice() || states.map(() => null));
  const currentDistributionRef = useRef([]), previousPlayingRef = useRef(false);
  const seriesTweenRef = useRef(null), manualTweenRef = useRef(null);
  const layoutRef = useRef({value:layout === 'distribution' ? 1 : 0,from:layout === 'distribution' ? 1 : 0,to:layout === 'distribution' ? 1 : 0,start:0,duration:0});
  const draggingRef = useRef(null), movedRef = useRef(false), pointsRef = useRef(new Map()), pinchRef = useRef(null);
  const [size,setSize] = useState({width:900,height:540});
  const [hovered,setHovered] = useState(-1), [cameraChanged,setCameraChanged] = useState(false);
  const [reduced,setReduced] = useState(() => typeof window !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const id = useId().replace(/:/g,'');
  const observed = clamp(Math.floor(month), 0, Math.max(0,series.length-1));
  const values = series[observed] || states.map(() => null);
  const highlighted = useMemo(() => new Map(highlights.map(item => [item.index,item.color])),[highlights]);
  const normalized = useMemo(() => normalizeGeometry(geo),[geo]);
  const geography = useMemo(() => {
    if (!normalized.features.length) return [];
    const projection = geoMercator().fitExtent([[22,24],[size.width-22,size.height-24]],normalized);
    const path = geoPath(projection);
    return states.map(state => {
      const feature = normalized.features.find(feature => featureUF(feature) === state.uf);
      if (!feature) return {path:'',center:[size.width/2,size.height/2],iconScale:1};
      const bounds=path.bounds(feature),span=Math.max(bounds[1][0]-bounds[0][0],bounds[1][1]-bounds[0][1]);
      return {path:path(feature),center:path.centroid(feature),iconScale:24/Math.max(1,span)};
    });
  },[normalized,states,size.width,size.height]);
  const seriesKey = useMemo(() => series.map(row => row.map(value => finite(value) ? value : '_').join(',')).join('|'),[series]);
  const distributed = useMemo(() => series.map(row => distribute(row,size.width,size.height)),[seriesKey,size.width,size.height]);
  const frame = plotFrame(size.width,size.height);
  const liveRef = useRef(null);
  liveRef.current = {geo:geography,states,series,distributed,observed,values,layout,selected,highlighted,hovered,playing,onSelect,onMonthChange,onPlayingChange,motionRequested,reduced,size};

  const wake = useCallback(() => {
    if (rafRef.current === null && visibleRef.current && pageRef.current) {
      rafRef.current = requestAnimationFrame(timestamp => drawRef.current?.(timestamp));
    }
  },[]);

  const changeCamera = useCallback((next) => {
    const {width,height} = liveRef.current.size;
    const k = clamp(next.k,1,7);
    cameraRef.current = {k,x:clamp(next.x,width*(1-k)-width*.16,width*.16),y:clamp(next.y,height*(1-k)-height*.16,height*.16)};
    setCameraChanged(k !== 1 || Math.abs(next.x) > 1 || Math.abs(next.y) > 1);
    wake();
  },[wake]);
  const zoomAt = useCallback((factor,x,y) => {
    const camera = cameraRef.current, k = clamp(camera.k * factor,1,7);
    changeCamera({k,x:x-(x-camera.x)/camera.k*k,y:y-(y-camera.y)/camera.k*k});
  },[changeCamera]);
  const resetCamera = useCallback(() => {cameraRef.current={k:1,x:0,y:0};setCameraChanged(false);wake();},[wake]);

  useLayoutEffect(() => {
    const value = clamp(month,0,Math.max(0,series.length-1));
    const previous = lastPropMonthRef.current;
    if (!(playing && Math.floor(value) === lastEmittedRef.current)) {
      const canTween = (!reduced || motionRequested) && Math.abs(value-previous) <= 1 && Math.abs(value-previous) > 0;
      if (canTween) manualTweenRef.current = {from:currentRatesRef.current.slice(),points:currentDistributionRef.current.map(point=>({...point})),start:performance.now(),duration:180};
      else manualTweenRef.current = null;
      positionRef.current=value;lastEmittedRef.current=Math.floor(value);previousTickRef.current=null;
    }
    lastPropMonthRef.current=value;
    if(playing&&!previousPlayingRef.current&&(!reduced||motionRequested)&&positionRef.current>=Math.max(0,series.length-1)&&series.length>1){
      positionRef.current=0;lastEmittedRef.current=0;onMonthChange?.(0);
    }
    previousPlayingRef.current=playing;
    wake();
  },[month,playing,reduced,motionRequested,series.length,wake]);

  useLayoutEffect(() => {
    seriesTweenRef.current={from:currentRatesRef.current.slice(),points:currentDistributionRef.current.map(point=>({...point})),start:performance.now(),duration:(!reduced||motionRequested)?260:0};
    wake();
  },[seriesKey,reduced,motionRequested,wake]);

  useLayoutEffect(() => {
    const target=layout==='distribution'?1:0;
    if (layoutRef.current.to!==target) layoutRef.current={value:layoutRef.current.value,from:layoutRef.current.value,to:target,start:performance.now(),duration:(!reduced||motionRequested)?700:0};
    wake();
  },[layout,reduced,motionRequested,wake]);

  useEffect(() => {
    const root=rootRef.current, svg=svgRef.current;
    if (!root||!svg) return;
    const resize=new ResizeObserver(([entry])=>setSize({width:Math.max(280,entry.contentRect.width),height:Math.max(190,entry.contentRect.height)}));
    resize.observe(root);
    const intersection=new IntersectionObserver(([entry])=>{
      visibleRef.current=entry.isIntersecting;
      previousTickRef.current=null;
      if(entry.isIntersecting)wake();else if(rafRef.current!==null){cancelAnimationFrame(rafRef.current);rafRef.current=null;}
    },{threshold:.03});
    intersection.observe(root);
    const visibility=()=>{pageRef.current=!document.hidden;previousTickRef.current=null;if(pageRef.current)wake();else if(rafRef.current!==null){cancelAnimationFrame(rafRef.current);rafRef.current=null;}};
    const query=matchMedia('(prefers-reduced-motion: reduce)');
    const preference=()=>{setReduced(query.matches);if(query.matches)liveRef.current.onPlayingChange?.(false);};
    const wheel=event=>{
      if(liveRef.current.layout!=='map')return;
      event.preventDefault();
      const rect=svg.getBoundingClientRect();
      zoomAt(Math.exp(-event.deltaY*.0014),event.clientX-rect.left,event.clientY-rect.top);
    };
    svg.addEventListener('wheel',wheel,{passive:false});
    document.addEventListener('visibilitychange',visibility);query.addEventListener('change',preference);wake();
    return()=>{resize.disconnect();intersection.disconnect();svg.removeEventListener('wheel',wheel);document.removeEventListener('visibilitychange',visibility);query.removeEventListener('change',preference);if(rafRef.current!==null)cancelAnimationFrame(rafRef.current);};
  },[wake,zoomAt]);

  useLayoutEffect(()=>{wake();},[size,selected,hovered,highlighted,wake]);

  drawRef.current = timestamp => {
    rafRef.current=null;
    if(!visibleRef.current||!pageRef.current)return;
    const live=liveRef.current;
    const last=Math.max(0,live.series.length-1);
    const animate=!live.reduced||live.motionRequested;
    let continuing=false;
    if(live.playing&&animate&&last>0){
      const elapsed=previousTickRef.current===null?0:Math.min(80,timestamp-previousTickRef.current);
      positionRef.current=Math.min(last,positionRef.current+elapsed/500);
      previousTickRef.current=timestamp;
      const actual=Math.floor(positionRef.current);
      if(actual!==lastEmittedRef.current){lastEmittedRef.current=actual;live.onMonthChange?.(actual);}
      if(positionRef.current>=last){previousTickRef.current=null;live.onPlayingChange?.(false);}else continuing=true;
    }else previousTickRef.current=null;
    const before=clamp(Math.floor(positionRef.current),0,last),after=Math.min(before+1,last),fraction=positionRef.current-before;
    const a=live.series[before]||[],b=live.series[after]||[];
    let rates=live.states.map((_,i)=>finite(a[i])?animate&&fraction>0&&finite(b[i])?mix(a[i],b[i],fraction):a[i]:null);
    const tween=seriesTweenRef.current||manualTweenRef.current;
    let dataPhase=1;
    if(tween){
      const t=tween.duration?clamp((timestamp-tween.start)/tween.duration,0,1):1;
      dataPhase=easeOut(t);
      if(t<1){rates=rates.map((value,i)=>finite(value)&&finite(tween.from[i])?mix(tween.from[i],value,easeOut(t)):value);continuing=true;}
      else {seriesTweenRef.current=null;manualTweenRef.current=null;}
    }
    currentRatesRef.current=rates;
    const morph=layoutRef.current;
    const phase=morph.duration?clamp((timestamp-morph.start)/morph.duration,0,1):1;
    morph.value=mix(morph.from,morph.to,easeOut(phase));
    if(phase<1)continuing=true;
    const blend=morph.value,camera=cameraRef.current;
    mapRef.current?.setAttribute('transform',`translate(${camera.x} ${camera.y}) scale(${camera.k})`);
    mapRef.current?.setAttribute('opacity',String(1-blend*.96));
    if(mapRef.current)mapRef.current.style.pointerEvents=blend>.05?'none':'auto';
    axisRef.current?.setAttribute('opacity',String(blend));
    const annotationPoints=[];
    live.states.forEach((state,index)=>{
      const node=marksRef.current[index],polygon=polygonsRef.current[index], geographyPoint=live.geo[index]?.center;
      if(!node||!geographyPoint)return;
      const observedValue=live.values[index];
      const color=live.highlighted.get(index)||(live.selected===index?'#ec7000':'#315f78');
      const at=live.distributed[before]?.[index];
      const next=live.distributed[after]?.[index];
      const dot=at?{...at}: {x:live.size.width/2,y:live.size.height/2,r:5,missing:true};
      if(fraction>0&&next&&!dot.missing&&!next.missing){dot.x=mix(dot.x,next.x,fraction);dot.y=mix(dot.y,next.y,fraction);dot.r=mix(dot.r,next.r,fraction);}
      const previousPoint=tween?.points?.[index];
      if(tween&&dataPhase<1&&previousPoint&&!previousPoint.missing&&!dot.missing){dot.x=mix(previousPoint.x,dot.x,dataPhase);dot.y=mix(previousPoint.y,dot.y,dataPhase);dot.r=mix(previousPoint.r,dot.r,dataPhase);}
      currentDistributionRef.current[index]={...dot};
      const x=mix(geographyPoint[0]*camera.k+camera.x,dot.x,blend);
      const y=mix(geographyPoint[1]*camera.k+camera.y,dot.y,blend);
      node.setAttribute('transform',`translate(${x} ${y})`);
      node.setAttribute('opacity',String(live.selected<0||live.selected===index||live.highlighted.has(index)||live.hovered===index?1:.42));
      const circle=node.querySelector('circle');
      const emphasized=live.selected===index||live.highlighted.has(index)||live.hovered===index;
      circle?.setAttribute('r',String(emphasized?Math.max(6.5,dot.r+2):mix(4.4,dot.r,blend)));
      circle?.setAttribute('fill',finite(observedValue)?color:'#f5f6f2');
      circle?.setAttribute('stroke',finite(observedValue)?'#f5f6f2':'#829ca5');
      annotationPoints.push({index,x,y,dot,color});
      if(polygon){
        polygon.setAttribute('fill',mapFill(observedValue)||`url(#${id}-missing)`);
        polygon.setAttribute('stroke',emphasized?color:'#f5f6f2');
        polygon.setAttribute('stroke-width',String((live.selected===index?2.3:emphasized?1.5:.8)/camera.k));
      }
    });
    for(const item of annotationPositions(annotationPoints,live.states,live.highlighted,live.selected,live.hovered,live.size.width,live.size.height,blend)){
      const annotation=annotationsRef.current[item.index];
      if(!annotation)continue;
      annotation.setAttribute('opacity',item.visible?'1':'0');
      annotation.setAttribute('transform',`translate(${item.x} ${item.y})`);
      const label=annotation.querySelector('text'),leader=annotation.querySelector('line'),mini=annotation.querySelector('.atlas-scene-mini');
      const textX=item.textX-item.x,textY=item.textY-item.y;
      if(label){label.setAttribute('x',String(textX));label.setAttribute('y',String(textY));label.setAttribute('text-anchor',item.end?'end':'start');label.querySelector('.atlas-scene-label-value')?.setAttribute('x',String(textX));}
      if(leader){
        const dx=item.iconX-item.x,dy=item.iconY-item.y,length=Math.hypot(dx,dy),start=Math.min(length,Math.max(8,item.dot.r+3));
        leader.setAttribute('x1',String(length?dx/length*start:0));leader.setAttribute('y1',String(length?dy/length*start:0));
        leader.setAttribute('x2',String(dx));leader.setAttribute('y2',String(dy));leader.setAttribute('opacity',String(blend*.78));
      }
      if(mini){
        const shape=live.geo[item.index];
        mini.setAttribute('transform',`translate(${item.iconX-item.x} ${item.iconY-item.y}) scale(${shape.iconScale}) translate(${-shape.center[0]} ${-shape.center[1]})`);
        mini.setAttribute('opacity',String(blend*.95));mini.setAttribute('fill',item.color);
      }
    }
    if(continuing)wake();
  };

  const pointFor = event => {const rect=svgRef.current.getBoundingClientRect();return {x:event.clientX-rect.left,y:event.clientY-rect.top};};
  const down = event => {
    if(layout!=='map'||event.button>0)return;
    const point=pointFor(event);pointsRef.current.set(event.pointerId,point);movedRef.current=false;
    if(pointsRef.current.size===1)draggingRef.current={id:event.pointerId,point,camera:{...cameraRef.current}};
    if(pointsRef.current.size===2){const [a,b]=[...pointsRef.current.values()];pinchRef.current={distance:Math.hypot(a.x-b.x,a.y-b.y),camera:{...cameraRef.current},center:{x:(a.x+b.x)/2,y:(a.y+b.y)/2}};movedRef.current=true;for(const pointerId of pointsRef.current.keys())svgRef.current.setPointerCapture(pointerId);}
  };
  const pointerMove = event => {
    if(!pointsRef.current.has(event.pointerId))return;
    const point=pointFor(event);pointsRef.current.set(event.pointerId,point);
    if(pointsRef.current.size===2&&pinchRef.current){
      const [a,b]=[...pointsRef.current.values()],start=pinchRef.current,center={x:(a.x+b.x)/2,y:(a.y+b.y)/2};
      const k=clamp(start.camera.k*Math.hypot(a.x-b.x,a.y-b.y)/Math.max(1,start.distance),1,7);
      changeCamera({k,x:center.x-(start.center.x-start.camera.x)/start.camera.k*k,y:center.y-(start.center.y-start.camera.y)/start.camera.k*k});movedRef.current=true;
    }else if(draggingRef.current?.id===event.pointerId){
      const start=draggingRef.current,dx=point.x-start.point.x,dy=point.y-start.point.y;
      if(Math.hypot(dx,dy)>4){movedRef.current=true;if(!svgRef.current.hasPointerCapture(event.pointerId))svgRef.current.setPointerCapture(event.pointerId);}
      changeCamera({...start.camera,x:start.camera.x+dx,y:start.camera.y+dy});
    }
  };
  const up = event => {
    pointsRef.current.delete(event.pointerId);pinchRef.current=null;draggingRef.current=null;
    if(svgRef.current.hasPointerCapture(event.pointerId))svgRef.current.releasePointerCapture(event.pointerId);
    if(pointsRef.current.size===1){const [id,point]=[...pointsRef.current.entries()][0];draggingRef.current={id,point,camera:{...cameraRef.current}};}
  };
  const keys = event => {
    if(layout!=='map')return;
    const camera=cameraRef.current;
    const pans={ArrowLeft:[36,0],ArrowRight:[-36,0],ArrowUp:[0,36],ArrowDown:[0,-36]};
    if(pans[event.key]){event.preventDefault();const [x,y]=pans[event.key];changeCamera({...camera,x:camera.x+x,y:camera.y+y});}
    else if(event.key==='Home'){event.preventDefault();resetCamera();}
    else if(['+','=','-','_'].includes(event.key)){event.preventDefault();zoomAt(['-','_'].includes(event.key)?1/1.35:1.35,size.width/2,size.height/2);}
  };
  const select = (index,event) => {if(layout!=='map'||event.detail===0||!movedRef.current)onSelect?.(index);};
  const markKey = (index,event) => {if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();onSelect?.(index);}};

  return <div className={`atlas-scene atlas-scene--${layout}`} ref={rootRef}>
    <svg ref={svgRef} className="atlas-scene-svg" viewBox={`0 0 ${size.width} ${size.height}`} tabIndex="0" role="group" aria-label={layout==='map'?'Mapa de inadimplência por UF. Setas movem a vista; mais e menos ajustam o zoom; Home retorna ao Brasil.':'Distribuição da inadimplência por UF. O eixo horizontal apresenta a taxa; o empilhamento vertical evita sobreposição.'} onPointerDown={down} onPointerMove={pointerMove} onPointerUp={up} onPointerCancel={up} onKeyDown={keys}>
      <defs><pattern id={`${id}-missing`} width="7" height="7" patternUnits="userSpaceOnUse"><rect width="7" height="7" fill="#e1e7e8"/><path d="M0 7 7 0" stroke="#a1b5bd" strokeWidth=".8"/></pattern></defs>
      <g className="atlas-scene-map" ref={mapRef}>
        {geography.map((item,index)=><path key={states[index].uf} ref={node=>{polygonsRef.current[index]=node;}} d={item.path} fill="#cfdee3" stroke="#f5f6f2" strokeWidth=".8" aria-hidden="true" focusable="false" className="atlas-scene-state" onClick={event=>select(index,event)} onPointerEnter={()=>setHovered(index)} onPointerLeave={()=>setHovered(-1)}/>)}
      </g>
      <g className="atlas-scene-axis" ref={axisRef} opacity={layout==='distribution'?1:0} pointerEvents="none" aria-hidden="true">
        <line x1={frame.left} y1={frame.axis} x2={frame.right} y2={frame.axis}/>
        {[0,5,10,15,20,25].map(value=>{const x=mix(frame.left,frame.right,value/25);return <g key={value}><line x1={x} x2={x} y1={frame.axis-4} y2={frame.axis+4}/><text x={x} y={frame.axis+22} textAnchor="middle">{value===25?'25%+':value===0?'0%':value}</text></g>;})}
        {values.some(value=>!finite(value))&&<text x={frame.left} y={frame.axis+66}>N/D</text>}
      </g>
      <g className="atlas-scene-marks">
        {states.map((state,index)=><g key={state.uf} ref={node=>{marksRef.current[index]=node;}} className="atlas-scene-mark" transform="translate(-100 -100)">
          <circle r="5" fill="#315f78" stroke="#f5f6f2" strokeWidth="1.5" tabIndex="0" role="button" aria-pressed={selected===index} aria-label={`${state.name}: ${pct(values[index])}`} onClick={event=>select(index,event)} onKeyDown={event=>markKey(index,event)} onPointerEnter={()=>setHovered(index)} onPointerLeave={()=>setHovered(-1)} onFocus={()=>setHovered(index)} onBlur={()=>setHovered(-1)}/>
        </g>)}
      </g>
      <g className="atlas-scene-annotations" pointerEvents="none" aria-hidden="true">
        {states.map((state,index)=><g key={state.uf} ref={node=>{annotationsRef.current[index]=node;}} className="atlas-scene-annotation" transform="translate(-100 -100)" opacity="0">
          <line x1="0" y1="0" x2="0" y2="0" className="atlas-scene-leader"/>
          {geography[index]&&<path className="atlas-scene-mini" d={geography[index].path} transform={`translate(0 -18) scale(${geography[index].iconScale}) translate(${-geography[index].center[0]} ${-geography[index].center[1]})`} opacity="0" aria-hidden="true" pointerEvents="none"/>}
          <text x="12" y="-9" pointerEvents="none" aria-hidden="true"><tspan className="atlas-scene-label-name">{state.name}</tspan><tspan x="12" dy="17" className="atlas-scene-label-value">{pct(values[index])}</tspan></text>
        </g>)}
      </g>
    </svg>
    {layout==='map'&&<div className="atlas-scene-camera" aria-label="Zoom do mapa"><button type="button" aria-label="Aproximar mapa" onClick={()=>zoomAt(1.4,size.width/2,size.height/2)}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h12M10 4v12"/></svg></button><button type="button" aria-label="Afastar mapa" onClick={()=>zoomAt(1/1.4,size.width/2,size.height/2)}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h12"/></svg></button>{cameraChanged&&<button type="button" aria-label="Voltar ao Brasil" onClick={resetCamera}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 7V4h3M13 4h3v3M16 13v3h-3M7 16H4v-3"/></svg></button>}</div>}
  </div>;
}
