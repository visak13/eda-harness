(function(){const vs=acquireVsCodeApi();const s=document.getElementById('status');
const ua=navigator.userAgent;document.getElementById('ua').textContent=ua;
let t0=performance.now();
window.addEventListener('message',e=>{const m=e.data;
 if(m.type==='pong'){const rtt=Math.round(performance.now()-t0);s.textContent='round-trip OK '+rtt+' ms';s.className='ok';vs.postMessage({type:'ack',rtt,ua});}
 if(m.type==='feed'){const li=document.createElement('li');li.textContent=m.text;document.getElementById('feed').appendChild(li);}
});
s.textContent='script ran, waiting for pong';t0=performance.now();vs.postMessage({type:'ready',ua});})();
