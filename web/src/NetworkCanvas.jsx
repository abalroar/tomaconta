import React,{useEffect,useRef} from 'react';
import {geoMercator,geoPath} from 'd3-geo';
import {select} from 'd3-selection';
import {zoom,zoomIdentity} from 'd3-zoom';
import 'd3-transition';
import {networkColor,networkGeometryForD3} from './network-data.js';

const pointRadius=count=>count>0?Math.max(1.25,Math.sqrt(count)*.56):0;
const easeOut=t=>1-Math.pow(1-Math.max(0,Math.min(1,t)),4);

/** The canvas draws only official municipal aggregates. DOM controls own the task. */
export default function NetworkCanvas({data,geometry,bankId,cityId,exclusive=false,onHover,onPick,apiRef}){
  const node=useRef(null),latest=useRef({bankId,cityId,exclusive,onHover,onPick});
  latest.current={bankId,cityId,exclusive,onHover,onPick};
  useEffect(()=>{
    const canvas=node.current;if(!canvas)return;
    const context=canvas.getContext('2d',{alpha:true});if(!context)return;
    const regions=networkGeometryForD3(geometry),banks=new Map(data.banks.map(bank=>[bank.idCnpjBase,bank]));
    let width=0,height=0,dpr=1,projection,paths=[],points=[],labelPoints=[],byId=new Map(),transform=zoomIdentity,introduced=false;
    let frame=0,disposed=false,lastHover=null,moved=false,down=null,zooming=false;
    let weights=new Map([[latest.current.bankId,1]]),fromWeights=weights,target=latest.current.bankId,start=performance.now(),animate=false;
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    const countFor=(point,id)=>id?point.city.banks[id]||0:point.city.total;
    const visiblePoint=point=>!latest.current.exclusive||Object.keys(point.city.banks).length===1;
    function schedule(){if(!frame&&!disposed)frame=requestAnimationFrame(paint);}
    function currentWeights(now){
      if(!animate)return weights;
      const t=reduced.matches?1:easeOut((now-start)/380),next=new Map();
      for(const [id,weight]of fromWeights)if(weight*(1-t)>.001)next.set(id,weight*(1-t));
      next.set(target,(next.get(target)||0)+t);weights=next;
      if(t>=1){weights=new Map([[target,1]]);animate=false;}
      return weights;
    }
    function layers(now){
      const active=currentWeights(now),k=transform.k;
      // Quiet dots retain the municipal geography when a bank is singled out.
      context.fillStyle='#cbdadd';context.globalAlpha=.68;
      context.beginPath();for(const point of points){if(!point.city.total)continue;const radius=1.05/k;context.moveTo(point.x+radius,point.y);context.arc(point.x,point.y,radius,0,Math.PI*2);}context.fill();
      for(const [id,weight]of active){
        const bank=id?banks.get(id):null;
        context.fillStyle=latest.current.exclusive&&!id?'#d6634d':bank?networkColor(bank):'#1c637c';
        context.globalAlpha=weight*.94;
        context.beginPath();for(const point of points){const count=countFor(point,id);if(!count||!visiblePoint(point))continue;const radius=pointRadius(count)/k;context.moveTo(point.x+radius,point.y);context.arc(point.x,point.y,radius,0,Math.PI*2);}context.fill();
        // A fine pale rim keeps the large metropolitan points distinct.
        context.strokeStyle='#f4f8f8';context.lineWidth=.5/k;context.globalAlpha=weight*.78;context.stroke();
      }
      context.globalAlpha=1;
    }
    function labels(){
      const selected=byId.get(latest.current.cityId||lastHover),k=transform.k;
      if(k<1.65&&!selected)return;
      context.save();context.setTransform(dpr,0,0,dpr,0,0);
      const occupied=[];const candidates=labelPoints.filter(visiblePoint);
      if(selected)candidates.unshift(selected);
      let shown=0;
      context.font='11px "Hanken Grotesk Variable", "Hanken Grotesk", Arial, sans-serif';context.textBaseline='middle';
      for(const point of candidates){
        if(point!==selected&&(k<1.65||shown>=9))continue;
        if(latest.current.bankId&&!countFor(point,latest.current.bankId)&&point!==selected)continue;
        const x=transform.applyX(point.x),y=transform.applyY(point.y),text=point.city.name,tx=x+pointRadius(countFor(point,latest.current.bankId)||point.city.total)+6;
        const length=context.measureText(text).width,box=[tx-3,y-8,tx+length+3,y+8];
        if(box[0]<8||box[2]>width-12||box[1]<8||box[3]>height-12)continue;
        if(point!==selected&&occupied.some(other=>box[0]<other[2]&&box[2]>other[0]&&box[1]<other[3]&&box[3]>other[1]))continue;
        occupied.push(box);context.lineWidth=4;context.strokeStyle='#f4f8f8';context.strokeText(text,tx,y);context.fillStyle='#294f60';context.fillText(text,tx,y);shown+=1;
      }
      context.restore();
    }
    function paint(now){
      frame=0;if(disposed||!width||!height)return;
      context.setTransform(dpr,0,0,dpr,0,0);context.clearRect(0,0,width,height);
      context.save();context.translate(transform.x,transform.y);context.scale(transform.k,transform.k);
      context.fillStyle='#edf3f3';context.strokeStyle='#bed0d5';context.lineWidth=.65/transform.k;
      for(const path of paths){context.fill(path);context.stroke(path);}
      layers(now);
      const point=byId.get(latest.current.cityId||lastHover);
      if(point){
        const count=countFor(point,latest.current.bankId)||point.city.total,radius=(Math.max(pointRadius(count),3)+4)/transform.k;
        context.beginPath();context.arc(point.x,point.y,radius,0,Math.PI*2);context.strokeStyle='#fff';context.lineWidth=4/transform.k;context.stroke();
        context.strokeStyle=latest.current.bankId?networkColor(banks.get(latest.current.bankId)):'#315f78';context.lineWidth=1.5/transform.k;context.stroke();
      }
      context.restore();labels();if(animate)schedule();
    }
    const behavior=zoom().scaleExtent([1,12]).filter(event=>{
      if(event.type==='wheel')return event.ctrlKey||event.metaKey;
      return !event.button;
    }).duration(280).on('start',()=>{zooming=true;lastHover=null;latest.current.onHover?.(null);}).on('zoom',event=>{transform=event.transform;schedule();}).on('end',()=>{zooming=false;});
    const selection=select(canvas).call(behavior);
    function camera(target,animated=false,duration=310){selection.interrupt();if(animated&&!reduced.matches)selection.transition().duration(duration).ease(easeOut).call(behavior.transform,target);else selection.call(behavior.transform,target);}
    function resize(){
      const box=canvas.getBoundingClientRect();if(box.width<1||box.height<1)return;
      width=Math.round(box.width);height=Math.round(box.height);dpr=Math.min(devicePixelRatio||1,2);
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
      const inset=width>760?Math.min(190,width*.19):12;
      const rightInset=width>760&&width<=1000?239:24;
      projection=geoMercator().fitExtent([[inset+10,16],[width-rightInset,height-20]],regions);
      const path=geoPath(projection);paths=regions.features.map(feature=>new Path2D(path(feature)));
      points=data.municipalities.filter(city=>Number.isFinite(city.lon)&&Number.isFinite(city.lat)).map(city=>{const [x,y]=projection([city.lon,city.lat]);return {city,x,y};});
      labelPoints=points.filter(point=>point.city.total>0).sort((a,b)=>b.city.total-a.city.total);
      byId=new Map(points.map(point=>[point.city.ibge,point]));
      behavior.extent([[0,0],[width,height]]).translateExtent([[-width*.2,-height*.2],[width*1.2,height*1.2]]);
      camera(zoomIdentity);if(!introduced&&!reduced.matches){introduced=true;selection.call(behavior.transform,zoomIdentity.translate(-width*.015,-height*.015).scale(1.03));camera(zoomIdentity,true,900);}schedule();
    }
    function nearestAt(event){
      const box=canvas.getBoundingClientRect(),sx=event.clientX-box.left,sy=event.clientY-box.top;
      let nearest=null,best=Infinity;
      for(const point of points){
        if(!visiblePoint(point))continue;
        const count=countFor(point,latest.current.bankId);if(!count)continue;
        const x=transform.applyX(point.x),y=transform.applyY(point.y),distance=Math.hypot(sx-x,sy-y),limit=Math.max(7,pointRadius(count)+2);
        if(distance<=limit&&distance<best){nearest=point;best=distance;}
      }
      return nearest;
    }
    function move(event){
      if(down&&Math.hypot(event.clientX-down[0],event.clientY-down[1])>4)moved=true;
      if(event.pointerType==='touch'||zooming||moved)return;
      const nearest=nearestAt(event);
      const id=nearest?.city.ibge||null;
      canvas.style.cursor=id?'pointer':transform.k>1?'grab':'default';
      if(id!==lastHover){lastHover=id;latest.current.onHover?.(nearest?.city||null);schedule();}
    }
    function leave(){lastHover=null;latest.current.onHover?.(null);schedule();}
    function pointerDown(event){if(down){moved=true;return;}down=[event.clientX,event.clientY,event.pointerId];moved=false;}
    function pointerUp(event){if(down&&down[2]!==event.pointerId){moved=true;return;}if(down&&!moved){const point=nearestAt(event);if(point)latest.current.onPick?.(point.city);}down=null;moved=false;}
    function keydown(event){
      const pan={ArrowLeft:[45,0],ArrowRight:[-45,0],ArrowUp:[0,45],ArrowDown:[0,-45]}[event.key];
      if(pan){event.preventDefault();selection.call(behavior.translateBy,pan[0]/transform.k,pan[1]/transform.k);return;}
      if(['+','=','-','_'].includes(event.key)){event.preventDefault();selection.call(behavior.scaleBy,['-','_'].includes(event.key)?1/1.6:1.6);}
      if(event.key==='Home'||event.key==='0'){event.preventDefault();selection.call(behavior.transform,zoomIdentity);}
      if(event.key==='Escape'){latest.current.onPick?.(null);leave();}
    }
    apiRef.current={
      zoomBy(factor,animated=true){const k=Math.max(1,Math.min(12,transform.k*factor)),ratio=k/transform.k,cx=width*.6,cy=height*.5;camera(zoomIdentity.translate(cx-(cx-transform.x)*ratio,cy-(cy-transform.y)*ratio).scale(k),animated);},
      reset(animated=true){camera(zoomIdentity,animated);latest.current.onPick?.(null);leave();},
      focusCity(city,animated=false){const point=byId.get(city?.ibge);if(!point)return false;const k=Math.max(3.5,Math.min(transform.k,7));camera(zoomIdentity.translate(width*.58-k*point.x,height*.48-k*point.y).scale(k),animated,420);schedule();return true;},
      redraw(){const id=latest.current.bankId;if(id!==target){fromWeights=new Map(weights);target=id;start=performance.now();animate=!reduced.matches;if(!animate)weights=new Map([[target,1]]);}schedule();},
    };
    canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerleave',leave);canvas.addEventListener('pointerdown',pointerDown);canvas.addEventListener('pointerup',pointerUp);canvas.addEventListener('keydown',keydown);
    const observer=new ResizeObserver(resize);observer.observe(canvas);resize();
    const reduceChange=()=>{if(reduced.matches){selection.interrupt();animate=false;weights=new Map([[target,1]]);schedule();}};reduced.addEventListener('change',reduceChange);
    return()=>{disposed=true;if(frame)cancelAnimationFrame(frame);observer.disconnect();selection.interrupt().on('.zoom',null);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerleave',leave);canvas.removeEventListener('pointerdown',pointerDown);canvas.removeEventListener('pointerup',pointerUp);canvas.removeEventListener('keydown',keydown);reduced.removeEventListener('change',reduceChange);apiRef.current=null;};
  },[data,geometry,apiRef]);
  useEffect(()=>{apiRef.current?.redraw();},[bankId,cityId,exclusive,apiRef]);
  return <canvas ref={node} className="tc-network-canvas" tabIndex={0} role="img" aria-label="Mapa das agências bancárias, agregadas por município. Use a busca de municípios para consultar cada local. No mapa, setas movem a vista, mais e menos aproximam e afastam, Home retorna ao Brasil."/>;
}
