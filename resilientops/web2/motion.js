(()=>{
 const body=document.body,button=document.getElementById('motion-toggle'),reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let preferred=null;try{const saved=localStorage.getItem('resilientops-motion');if(saved==='on'||saved==='off')preferred=saved==='on'}catch{}
 let enabled=false;const owned=new Set();
 function animate(el,delay=0){if(!enabled||!el||!el.animate)return;const a=el.animate([{opacity:.4,transform:'translateY(18px)'},{opacity:1,transform:'translateY(0)'}],{duration:650,delay,easing:'cubic-bezier(.2,.7,.2,1)',fill:'none'});owned.add(a);a.onfinish=()=>owned.delete(a)}
 function apply(){enabled=preferred===null?!reduced.matches:preferred;body.dataset.motion=enabled?'running':'paused';button.innerHTML=controlIcon(enabled?'pause':'play');button.disabled=false;button.setAttribute('aria-checked',String(enabled));button.setAttribute('aria-label','Landing page motion');button.title=enabled?'Turn off landing page animations':reduced.matches?'Your system prefers reduced motion. Select to enable animations.':'Turn on landing page animations';if(!enabled){owned.forEach(a=>a.cancel());owned.clear()} }
 button.addEventListener('click',()=>{preferred=!enabled;try{localStorage.setItem('resilientops-motion',preferred?'on':'off')}catch{}apply()});
 reduced.addEventListener('change',apply);apply();
 document.querySelectorAll('.hero>div:first-child>*').forEach((el,i)=>animate(el,i*80));
 if('IntersectionObserver'in window){const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(!entry.isIntersecting)return;entry.target.classList.add('in-view');if(entry.target.classList.contains('journey'))entry.target.querySelectorAll('article').forEach((el,i)=>{el.style.setProperty('--stage-delay',i*140+'ms');animate(el,i*110)});else if(entry.target.classList.contains('cards'))entry.target.querySelectorAll('.feature').forEach((el,i)=>animate(el,(i%3)*100));else animate(entry.target);observer.unobserve(entry.target)}),{threshold:.12});document.querySelectorAll('.intro,.cards,.journey,.demo-grid,.role-grid,.request,.faq').forEach(el=>observer.observe(el))}
 document.querySelectorAll('.tour-tabs button').forEach(b=>b.addEventListener('click',()=>animate(document.getElementById('tour-panel'))));
 document.addEventListener('visibilitychange',()=>{if(document.hidden){body.dataset.motion='paused';owned.forEach(a=>a.pause())}else{apply();if(enabled)owned.forEach(a=>a.play())}});
})();
