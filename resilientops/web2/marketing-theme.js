(()=>{
 const root=document.documentElement,system=matchMedia('(prefers-color-scheme: dark)');
 let saved;try{saved=localStorage.getItem('resilientops-theme')}catch{}
 let explicit=saved==='light'||saved==='dark';
 function apply(theme){
  root.dataset.theme=theme;root.style.colorScheme=theme;const select=document.getElementById('theme-preference');if(select)select.value=theme;
  const button=document.getElementById('marketing-theme-toggle');
  if(button){button.innerHTML=controlIcon(theme==='dark'?'moon':'sun');button.setAttribute('aria-label',theme==='dark'?'Switch to light theme':'Switch to dark theme');button.title=button.getAttribute('aria-label')}
 }
 apply(explicit?saved:system.matches?'dark':'light');
 document.addEventListener('DOMContentLoaded',()=>{
  apply(root.dataset.theme);document.getElementById('theme-preference')?.addEventListener('change',event=>{explicit=true;apply(event.target.value);try{localStorage.setItem('resilientops-theme',event.target.value)}catch{}});
  document.getElementById('marketing-theme-toggle')?.addEventListener('click',()=>{
   const next=root.dataset.theme==='dark'?'light':'dark';explicit=true;apply(next);try{localStorage.setItem('resilientops-theme',next)}catch{}
  });
 });
 system.addEventListener('change',()=>{if(!explicit)apply(system.matches?'dark':'light')});
 window.addEventListener('storage',event=>{if(event.key!=='resilientops-theme')return;explicit=event.newValue==='light'||event.newValue==='dark';apply(explicit?event.newValue:system.matches?'dark':'light')});
})();
