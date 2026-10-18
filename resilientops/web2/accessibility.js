/* Shared accessibility behavior for static pages and the dashboard. */
function focusMain(){const target=document.querySelector('main h1')||document.querySelector('main');if(target){target.tabIndex=-1;target.focus({preventScroll:true})}}
function enhanceAccessibility(){
 const main=document.querySelector('main');if(main){main.id='main-content';main.tabIndex=-1}
 document.querySelectorAll('nav').forEach((n,i)=>{if(!n.hasAttribute('aria-label'))n.setAttribute('aria-label',n.classList.contains('nav')?'Application navigation':n.closest('footer')?'Footer navigation':'Product navigation')});
 document.querySelectorAll('.nav button').forEach(b=>{if(b.classList.contains('active'))b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
 document.querySelectorAll('.tabs').forEach(g=>{g.setAttribute('role','group');g.setAttribute('aria-label','Incident sections');g.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.classList.contains('active'))))});
 document.querySelectorAll('th').forEach(th=>{th.scope='col';if(!th.textContent.trim())th.textContent='Actions'});
 document.querySelectorAll('table').forEach((t,i)=>{if(!t.getAttribute('aria-label'))t.setAttribute('aria-label',t.closest('section')?.querySelector('h2')?.textContent||'Operational records');if(!t.parentElement.classList.contains('table-wrap')){const wrap=document.createElement('div');wrap.className='table-wrap';t.before(wrap);wrap.append(t)}});
 document.querySelectorAll('.table-wrap').forEach(w=>{w.tabIndex=0;w.setAttribute('role','region');w.setAttribute('aria-label',w.querySelector('table')?.getAttribute('aria-label')+' — scrollable table')});
 document.querySelectorAll('.form-status').forEach((s,i)=>{s.id=s.id||'form-feedback-'+i;s.tabIndex=-1;s.setAttribute('aria-live','polite');s.setAttribute('aria-atomic','true');s.closest('form')?.querySelectorAll('input:not([type=hidden]),textarea').forEach(f=>f.setAttribute('aria-describedby',s.id))});
 document.querySelectorAll('input[required]').forEach(f=>{if(!f.closest('label')?.querySelector('.required-note')){const label=f.closest('label');if(label){const note=document.createElement('span');note.className='required-note';note.textContent=' (required)';label.insertBefore(note,f)}}});
 document.querySelectorAll('.form input[type=email]').forEach(f=>{f.setAttribute('autocomplete','email');f.setAttribute('inputmode','email')});
 document.querySelectorAll('.world-map').forEach(m=>{m.setAttribute('role','group');m.setAttribute('aria-label','Plant map. Use a marker or the plant buttons below to filter incidents.');m.querySelectorAll('.marker').forEach(e=>{e.querySelector('circle')?.setAttribute('r','12')})});
 document.querySelectorAll('.chat-answer').forEach(e=>{e.setAttribute('role','status');e.setAttribute('aria-live','polite')});
 document.querySelectorAll('.nav button>span:first-child,.dot,.step-num,.route-icon,.alert-icon,.recommend-icon').forEach(e=>e.setAttribute('aria-hidden','true'));
 setupTabs();
}
function setupTabs(){document.querySelectorAll('[role=tablist]').forEach((list,li)=>{const tabs=[...list.querySelectorAll('[role=tab]')];tabs.forEach((tab,i)=>{const active=tab.getAttribute('aria-selected')==='true';tab.id=tab.id||`tab-${li}-${i}`;tab.tabIndex=active?0:-1;const panel=tab.dataset.authMode?document.getElementById(tab.dataset.authMode+'-panel'):document.getElementById('tour-panel');if(panel){tab.setAttribute('aria-controls',panel.id);panel.setAttribute('role','tabpanel');panel.tabIndex=0;if(active)panel.setAttribute('aria-labelledby',tab.id)}});if(!list.dataset.keyboardBound){list.dataset.keyboardBound='true';list.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const items=[...list.querySelectorAll('[role=tab]')];const index=items.indexOf(document.activeElement);if(index<0)return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowRight'?1:-1)+items.length)%items.length;items[n].click();items[n].focus()})}})}
document.addEventListener('DOMContentLoaded',enhanceAccessibility);
document.addEventListener('input',e=>{if(e.target.matches('input,textarea'))e.target.removeAttribute('aria-invalid')});
document.addEventListener('invalid',e=>{e.target.setAttribute('aria-invalid','true')},true);
