// Node 22+. Start an isolated server on 8001 and headless Chrome with CDP on 9228.
// Uses a fresh operational ledger; simulates API failures only inside the browser.
(async()=>{
 const tabs=await(await fetch('http://127.0.0.1:9228/json')).json();
 const ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
 const pending=new Map();let id=0;const errors=[];
 ws.onmessage=({data})=>{const v=JSON.parse(data);if(v.id){const p=pending.get(v.id);pending.delete(v.id);v.error?p.reject(v.error):p.resolve(v.result);}else if(v.method==='Runtime.exceptionThrown')errors.push(v.params.exceptionDetails.text);};
 await new Promise(r=>ws.onopen=r);
 const send=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));});
 const run=async expression=>{const v=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(v.exceptionDetails)throw Error(v.exceptionDetails.text);return v.result.value;};
 const wait=async expression=>{for(let n=0;n<150;n++){if(await run(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timeout: '+expression+' BODY: '+(await run('document.body?.innerText')));};
 await send('Runtime.enable');await send('Page.enable');await send('Network.enable');await send('Network.setBlockedURLs',{urls:['*fonts.googleapis.com*','*fonts.gstatic.com*']});await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:'http://127.0.0.1:8001/app'});
 await wait("document.body?.innerText.includes('292,016') && window.workflowIncidents?.length===3");
 await run("(()=>{if(window.workflowIncidents.some(i=>i.status!=='DRAFT'))throw Error('Review gate bypassed')})()");
 await send('Page.reload');await wait("window.workflowIncidents?.length===3 && document.body.innerText.includes('292,016')");
 await run("nav('Data & Sources')");await wait("document.querySelectorAll('tbody tr').length===3");
 await run("flow.table('reference:curated_news')");await wait("document.querySelectorAll('tbody tr').length===16");
 await run("nav('Overview')");
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 if(await run('document.documentElement.scrollWidth>innerWidth'))throw Error('Mobile overflow');
 await run("window.realFetch=window.fetch;window.fetch=(url,options)=>String(url)==='/api/workflow/incidents'?Promise.resolve(new Response(JSON.stringify({detail:'Sign in to work on incidents'}),{status:401,headers:{'Content-Type':'application/json'}})):window.realFetch(url,options);flow.reload()");
 await wait("document.querySelector('[role=alert]')?.innerText.includes('Sign in with Google')");
 if(!await run("document.body.innerText.includes('292,016')"))throw Error('Auth failure hid source data');
 await run("window.fetch=window.realFetch;flow.reload()");await wait("!document.querySelector('[role=alert]') && window.workflowIncidents.length===3");
 await send('Network.setBlockedURLs',{urls:['*fonts.googleapis.com*','*fonts.gstatic.com*','*/api/data/summary']});
 await send('Page.reload');await wait("document.body?.innerText.includes('Source data unavailable')");
 await send('Network.setBlockedURLs',{urls:['*fonts.googleapis.com*','*fonts.gstatic.com*']});
 await run('flow.reload()');await wait("document.body.innerText.includes('292,016') && window.workflowIncidents.length===3");
 const expected=errors.filter(e=>!e.includes('Failed to fetch'));if(expected.length)throw Error(expected.join(';'));
 console.log(JSON.stringify({sourceRecords:292016,autoDetectedDrafts:3,duplicateDrafts:false,sourceBrowsing:true,authFailureVisible:true,sourceFailureRecoverable:true,mobileOverflow:false}));ws.close();
})().catch(e=>{console.error(e);process.exit(1)});
