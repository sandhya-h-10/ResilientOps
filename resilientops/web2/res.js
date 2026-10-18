(()=>{
 const root=document.documentElement,reduced=matchMedia('(prefers-reduced-motion: reduce)');let sound=false,audio,nodes=[],playingUntil=0;
 const svg='<svg viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="res-gradient" x2="1" y2="1"><stop stop-color="#64dfcc"/><stop offset="1" stop-color="#167f88"/></linearGradient></defs><circle class="res-orbit" cx="32" cy="32" r="29" fill="none" stroke="currentColor" stroke-dasharray="60 10"/><path d="M17 24Q17 16 25 16H39Q47 16 47 24V38Q47 46 39 46H29L22 51V45Q17 43 17 37Z" fill="url(#res-gradient)"/><path d="M25 30v4m14-4v4" stroke="#102e3b" stroke-width="3.5" stroke-linecap="round" class="res-eyes"/><path d="M28 39q4 3 8 0" fill="none" stroke="#102e3b" stroke-width="2" stroke-linecap="round"/><circle cx="46" cy="14" r="4" fill="#b8f1de"/></svg>';
 const dock=document.createElement('div');dock.id='res-dock';dock.innerHTML=`<section id="res-panel" role="dialog" aria-label="Chat with Res" hidden><header><div class="res-mini">${svg}</div><div><strong>Res</strong><small>Your AI operations companion</small></div><button id="res-close" aria-label="Close Res">×</button></header><p class="res-disclosure">Gemini uses your question and current incident context. Suggestions need your review.</p><div id="res-messages" role="log" aria-live="polite" aria-label="Conversation"></div><div class="res-prompts"><button data-res-prompt="What should I do next?">Next step</button><button data-res-prompt="What is at risk?">Explain impact</button><button data-res-prompt="How do I autofill an incident?">Autofill help</button></div><form id="res-form"><label class="res-sr" for="res-input">Ask Res a question</label><input id="res-input" maxlength="2000" placeholder="Ask Res…" autocomplete="off" required><button type="submit" aria-label="Send question to Res">↑</button></form><footer><button id="res-motion">Motion</button><button id="res-sound" aria-pressed="false">Sound off</button></footer></section><button id="res-launcher" aria-label="Open Res assistant" aria-expanded="false" aria-controls="res-panel">${svg}<span>Res</span></button>`;document.body.append(dock);
 const panel=dock.querySelector('#res-panel'),launcher=dock.querySelector('#res-launcher'),input=dock.querySelector('#res-input'),log=dock.querySelector('#res-messages');
 function message(text,who='res'){const el=document.createElement('div');el.className='res-message '+who;el.textContent=text;log.append(el);log.scrollTop=log.scrollHeight;}
 // Render a small Markdown subset with DOM nodes; model text is never HTML.
 function inline(parent,text){
  const pattern=/(\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|\*([^*\n]+)\*)/g;let cursor=0;
  for(const match of text.matchAll(pattern)){
   parent.append(document.createTextNode(text.slice(cursor,match.index)));
   const node=document.createElement(match[4]?'code':match[5]?'em':'strong');
   node.textContent=match[2]||match[3]||match[4]||match[5];parent.append(node);cursor=match.index+match[0].length;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
 }
 function formatAnswer(target,text){
  target.replaceChildren();target.classList.add('res-answer');
  let paragraph=null,list=null,code=null;
  for(const line of String(text).replace(/\r\n?/g,'\n').split('\n')){
   if(/^\s*```/.test(line)){paragraph=null;list=null;if(code){code=null;}else{const pre=document.createElement('pre');code=document.createElement('code');pre.append(code);target.append(pre);}continue;}
   if(code){code.append(document.createTextNode((code.textContent?'\n':'')+line));continue;}
   if(!line.trim()){paragraph=null;list=null;continue;}
   const heading=line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*$/),item=line.match(/^\s*(?:([-*+•])|(\d+)[.)])\s+(.+)$/);
   if(heading){paragraph=null;list=null;const h=document.createElement('h3');inline(h,heading[1]);target.append(h);continue;}
   if(item){paragraph=null;const tag=item[2]?'OL':'UL';if(!list||list.tagName!==tag){list=document.createElement(tag.toLowerCase());if(item[2])list.start=Number(item[2]);target.append(list);}const li=document.createElement('li');inline(li,item[3]);list.append(li);continue;}
   if(list&&/^\s{2,}/.test(line)){list.lastElementChild.append(document.createTextNode(' '));inline(list.lastElementChild,line.trim());continue;}
   list=null;if(!paragraph){paragraph=document.createElement('p');target.append(paragraph);}else paragraph.append(document.createTextNode(' '));inline(paragraph,line.trim());
  }
 }
 function sourceDetails(target,sources){
  if(!sources?.length)return;
  const details=document.createElement('details');details.className='res-sources';
  const summary=document.createElement('summary');summary.textContent='Sources and context ('+sources.length+')';details.append(summary);
  const list=document.createElement('ul');
  for(const source of sources){const li=document.createElement('li'),title=document.createElement('span'),id=document.createElement('small');title.textContent=source.title;id.textContent=source.id;li.append(title,id);list.append(li);}
  details.append(list);target.append(details);
 }
 let busy=false,history=[],contextId=null,connectionCheck=0,returnFocus=null;
 try{input.value=sessionStorage.getItem('res-pending-question')||'';}catch{}
 const subtitle=dock.querySelector('header small'),disclosure=dock.querySelector('.res-disclosure');
 function requireLogin(){
  connectionCheck++;
  subtitle.textContent='Session needs sign-in';
  disclosure.replaceChildren(document.createTextNode('Your session is no longer available to Res. Your question is kept below. '));
  const link=document.createElement('a');link.href='/auth/google/login';link.textContent='Sign in with Google';
  link.onclick=()=>{try{sessionStorage.setItem('res-pending-question',input.value);}catch{}};
  disclosure.append(link);
 }
 async function checkConnection(){
  const check=++connectionCheck;
  try{const r=await fetch('/api/res/status',{credentials:'same-origin',cache:'no-store'});const data=await r.json();if(check!==connectionCheck)return;if(r.status===401){requireLogin();return;}subtitle.textContent=r.ok&&data.configured?'Gemini · Connected':'AI connection needed';disclosure.textContent=data.detail||'Gemini uses your question and current incident context. Suggestions need your review.';}catch{if(check===connectionCheck)subtitle.textContent='Connection unavailable';}
 }
 async function ask(q){
  q=q.trim();if(!q||busy)return;
  const incidentId=(window.flow?.chatContext?window.flow.chatContext():window.flow?.current())?.id||null;
  if(incidentId!==contextId){history=[];contextId=incidentId;if(log.children.length)message(incidentId?'I’m using the selected incident and its latest assessment.':'I’m using the workspace overview for this conversation.');}
  busy=true;message(q,'user');input.value='';
  dock.querySelectorAll('#res-form button,[data-res-prompt]').forEach(b=>b.disabled=true);
  log.setAttribute('aria-busy','true');message('Res is thinking…');const pending=log.lastElementChild;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),55000);
  try{
   const send=()=>fetch('/api/res/chat',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q,incident_id:incidentId,history:history.slice(-8)}),signal:controller.signal});
   let r=await send();
   if(r.status===401){
    const session=await fetch('/api/me',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
    if(session.ok)r=await send();
   }
   if(r.status===401){input.value=q;try{sessionStorage.setItem('res-pending-question',q);}catch{}requireLogin();}
   const data=await r.json();
   if(!r.ok)throw Error(r.status===401?'Your session could not be verified. Use Sign in with Google above, then resend your question.':typeof data.detail==='string'?data.detail:'Res could not process this question. Please try again.');
   try{sessionStorage.removeItem('res-pending-question');}catch{}
   connectionCheck++;formatAnswer(pending,data.answer);subtitle.textContent='Gemini · '+data.model;disclosure.textContent='Gemini uses your question and current incident context. Suggestions need your review.';
   history.push({role:'user',content:q},{role:'assistant',content:data.answer});history=history.slice(-8);
   sourceDetails(pending,data.sources);
  }catch(error){pending.textContent=error.name==='AbortError'?'Res took too long to respond. Please try again.':error.message;pending.classList.add('res-error');if(!input.value)input.value=q;}
  finally{clearTimeout(timeout);busy=false;log.removeAttribute('aria-busy');dock.querySelectorAll('#res-form button,[data-res-prompt]').forEach(b=>b.disabled=false);log.scrollTop=log.scrollHeight;}
 }
 function show(open){if(open&&panel.hidden)returnFocus=document.activeElement;panel.hidden=!open;launcher.setAttribute('aria-expanded',String(open));if(open){checkConnection();if(!log.children.length)message('I’m Res. Ask me about the current incident or the next step in your workflow.');input.focus()}else (returnFocus?.isConnected?returnFocus:launcher).focus()}
 window.ResAssistant={open(question){show(true);if(question)input.value=question;input.focus();}};
 launcher.onclick=()=>show(panel.hidden);dock.querySelector('#res-close').onclick=()=>show(false);dock.addEventListener('keydown',e=>{if(e.key==='Escape'){show(false);e.stopPropagation()}});dock.querySelector('#res-form').onsubmit=e=>{e.preventDefault();ask(input.value)};dock.querySelectorAll('[data-res-prompt]').forEach(b=>b.onclick=()=>ask(b.dataset.resPrompt));
 function motionEnabled(){try{const s=localStorage.getItem('resilientops-motion');return s==='on'||s!=='off'&&!reduced.matches}catch{return !reduced.matches}}
 function syncMotion(){const on=motionEnabled();root.classList.toggle('res-motion-on',on);root.classList.toggle('res-motion-off',!on);document.querySelectorAll('#res-motion,#res-global-motion').forEach(b=>{b.setAttribute('aria-pressed',String(on));b.setAttribute('aria-label',on?'Turn motion off':'Turn motion on');b.title=on?'Turn motion off':'Turn motion on';b.innerHTML=typeof controlIcon==='function'?controlIcon(on?'pause':'play'):'Motion '+(on?'on':'off')});}
 function toggleMotion(){const local=document.getElementById('motion-toggle');if(local)local.click();else{try{localStorage.setItem('resilientops-motion',motionEnabled()?'off':'on')}catch{}syncMotion()}}
 dock.querySelector('#res-motion').onclick=toggleMotion;document.addEventListener('click',e=>{if(e.target.closest('#motion-toggle'))syncMotion()});reduced.addEventListener('change',syncMotion);syncMotion();
 function mountMotion(){if(document.getElementById('motion-toggle')||document.getElementById('res-global-motion'))return;const bar=document.querySelector('.topbar .right')||document.querySelector('.account-links');if(!bar)return;const b=document.createElement('button');b.id='res-global-motion';b.className='icon-control';b.type='button';b.onclick=toggleMotion;bar.prepend(b);syncMotion()};new MutationObserver(mountMotion).observe(document.body,{childList:true,subtree:true});mountMotion();
 function stopSound(){nodes.forEach(o=>{try{o.stop()}catch{}});nodes=[];playingUntil=0;}
 function playSound(){if(!sound)return;try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();audio.resume();if(audio.currentTime<playingUntil)return;const now=audio.currentTime;playingUntil=now+5.2;[261.63,329.63,392,523.25,493.88,392,329.63,261.63].forEach((f,i)=>{const o=audio.createOscillator(),g=audio.createGain(),at=now+i*.48;o.type='sine';o.frequency.value=f;g.gain.setValueAtTime(0,at);g.gain.linearRampToValueAtTime(.018,at+.08);g.gain.exponentialRampToValueAtTime(.0001,at+1.7);o.connect(g);g.connect(audio.destination);o.start(at);o.stop(at+1.75);nodes.push(o);o.onended=()=>{o.disconnect();g.disconnect();nodes=nodes.filter(n=>n!==o)}})}catch{}}
 function soundUI(){document.querySelectorAll('.sound,#res-sound').forEach(b=>{b.setAttribute('aria-pressed',String(sound));b.setAttribute('aria-label',sound?'Turn sound off':'Turn sound on');b.title=sound?'Turn sound off':'Turn sound on';b.innerHTML=typeof controlIcon==='function'?controlIcon(sound?'sound':'mute'):'Sound '+(sound?'on':'off')});}
 window.ResSound={play:playSound,toggle(){sound=!sound;if(sound)playSound();else stopSound();soundUI()}};dock.querySelector('#res-sound').onclick=()=>window.ResSound.toggle();soundUI();document.addEventListener('visibilitychange',()=>{if(document.hidden)stopSound()});
})();
