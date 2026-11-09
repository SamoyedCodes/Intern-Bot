(() => {
  const $=id=>document.getElementById(id);
  const employers=[
    {company:'Lumen Analytics',role:'Data Science Intern · Greenhouse',question:'Are you available for a six-month internship starting in January?'},
    {company:'Harbor Robotics',role:'Robotics Intern · Workday',question:'Can you attend an on-site internship three days a week?'},
    {company:'Northwind Labs',role:'Software Intern · Lever'}
  ];
  const stages=['Intake','Fill','Verify','Dispatch'];
  const stationNotes=[
    'Intake loads the job link and the profile attached to the application.',
    'Fill copies profile details and approved answers into form fields.',
    'Verify reads each field back and flags anything that needs your answer.',
    'Dispatch waits for your approval, then checks for an employer receipt.'
  ];
  const labels={queued:'Queued',intake:'Opening form',fill:'Filling form',verify:'Checking fields',
    question:'Needs your answer',answer:'Checking answer',review:'Ready for review',send:'Sending',
    receipt:'Awaiting receipt',done:'Receipt confirmed'};
  const busy=['intake','fill','verify','answer','send'];
  let state,selected,timer=null,stationNote=null,step=0;
  const view=makeCrewScene($('stage'),chooseJob,i=>{stationNote=i;draw();});
  function log(message){state.log.unshift({n:++step,message});}
  function newState(){
    clearTimeout(timer);timer=null;selected=0;stationNote=null;step=0;
    state={active:0,playing:false,log:[],jobs:employers.map((info,i)=>({...info,
      phase:i===2?'done':'queued',verified:i===2?9:0,station:i===2?3:0,answer:null}))};
    log('Lumen and Harbor are queued.');draw();
  }
  function chooseJob(i){selected=i;stationNote=null;draw();}
  function phase(j,p,s,message){j.phase=p;j.station=s;if(message)log(message);}
  function advance(){
    if(!state.playing)return;
    const j=state.jobs[state.active];
    switch(j.phase){
      case 'intake':phase(j,'fill',1,'Fill copied eight answers from the demo profile.');break;
      case 'fill':phase(j,'verify',2,'Verify began reading the eight fields back.');break;
      case 'verify':
        j.verified=Math.min(8,j.verified+2);
        if(j.verified===8){phase(j,'question',2,'Verify paused at the unanswered question.');state.playing=false;selected=state.active;}
        break;
      case 'answer':
        j.verified=9;phase(j,'review',3,'All nine fields checked. Dispatch needs your approval.');
        state.playing=false;break;
      case 'send':
        phase(j,'receipt',3,'Send clicked once. Awaiting the employer receipt.');state.playing=false;break;
    }
    stationNote=null;draw();schedule();
  }
  function schedule(){
    clearTimeout(timer);timer=null;
    if(state.playing)timer=setTimeout(advance,state.jobs[state.active].phase==='verify'?680:1450);
  }
  function start(i){
    if(state.playing || state.jobs[i].phase!=='queued')return;
    state.active=i;selected=i;state.playing=true;stationNote=null;
    phase(state.jobs[i],'intake',0,'Intake opened the '+state.jobs[i].company+' form.');draw();schedule();
  }
  function toggle(){
    const j=state.jobs[state.active];
    if(j.phase==='queued'){start(state.active);return;}
    if(!busy.includes(j.phase))return;
    state.playing=!state.playing;stationNote=null;draw();schedule();
  }
  function respond(answer){
    const j=state.jobs[state.active];if(j.phase!=='question')return;
    j.answer=answer;phase(j,'answer',2,'Fill entered your demo answer. Verify is checking it.');
    state.playing=true;draw();schedule();
  }
  function approve(){
    const j=state.jobs[state.active];if(j.phase!=='review')return;
    phase(j,'send',3,'You approved this demo submission.');state.playing=true;draw();schedule();
  }
  function receipt(){
    const j=state.jobs[state.active];if(j.phase!=='receipt')return;
    phase(j,'done',3,'Employer receipt confirmed for '+j.company+'.');draw();
  }
  function action(name,handler,secondary=false){
    const b=document.createElement('button');b.textContent=name;b.onclick=handler;
    if(secondary)b.className='secondary';$('actions').append(b);
  }
  function task(j){
    const current=selected===state.active,active=state.jobs[state.active],waiting=!current&&active.phase!=='done';
    const details={
      queued:['Ready for intake',waiting?'Another application is ahead in the queue.':'Follow a sample application from its first field to its receipt.'],
      intake:['Opening the form','Intake is matching the job link with its demo profile.'],
      fill:['Filling eight fields','Fill is copying existing profile answers into the form.'],
      verify:['Reading the form back','Verify checks the values the employer form now shows.'],
      question:[j.question,'Eight fields match the profile. The employer is asking for one detail only you can confirm.'],
      answer:['Checking your answer','Your demo response was entered. Verify is reading it back.'],
      review:['Review the application','Nine fields checked. Availability answer: '+(j.answer||'')+'. Dispatch is waiting for your approval.'],
      send:['Sending the application','Dispatch has approval for this application.'],
      receipt:['Waiting for an employer receipt','Dispatch sent the form. A receipt will change its status to submitted.'],
      done:['Submission confirmed','An employer receipt is on file for this demo application.']
    }[j.phase];
    $('taskTitle').textContent=details[0];$('taskBody').textContent=details[1];$('actions').replaceChildren();
    if(j.phase==='queued'&&!waiting)action('Run demo',()=>start(selected));
    if(j.phase==='queued'&&waiting)action('Follow active application',()=>chooseJob(state.active));
    if(current && j.phase==='question'){action('Yes, I can',()=>respond('Yes'));action('No, I can’t',()=>respond('No'),true);}
    if(current && j.phase==='review')action('Approve demo submission',approve);
    if(current && j.phase==='receipt')action('Simulate employer receipt',receipt);
    if(current && j.phase==='done'){const next=state.jobs.findIndex(j=>j.phase==='queued');if(next!==-1)action('Run next application',()=>start(next));}
  }
  function draw(){
    const j=state.jobs[selected],active=state.jobs[state.active];
    $('company').textContent=j.company;$('role').textContent=j.role;$('status').textContent=labels[j.phase];
    $('count').textContent=j.verified+' / 9';
    $('bar').innerHTML=Array.from({length:9},(_,i)=>i<j.verified?'<b class="on"></b>':'<b></b>').join('');
    task(j);
    const records=$('records');
    if(!records.children.length){
      employers.forEach((info,i)=>{
        const b=document.createElement('button');b.className='record';b.onclick=()=>chooseJob(i);
        b.innerHTML='<span class="index mono">0'+(i+1)+'</span><b></b><small></small>';
        b.querySelector('b').textContent=info.company;records.append(b);
      });
    }
    [...records.children].forEach((b,i)=>{b.setAttribute('aria-pressed',i===selected);b.querySelector('small').textContent=labels[state.jobs[i].phase];});
    $('events').replaceChildren(...state.log.slice(0,3).map(e=>{
      const li=document.createElement('li'),index=document.createElement('time');
      index.textContent='E'+String(e.n).padStart(2,'0');li.append(index,document.createTextNode(e.message));return li;
    }));
    $('live').textContent=stationNote!==null?stationNotes[stationNote]:
      (active.phase==='queued'?'Crew standing by.':active.company+' · '+stages[active.station]+' · '+labels[active.phase]);
    const play=$('play');play.hidden=!busy.includes(active.phase);
    play.textContent=active.phase==='queued'?'Run demo':state.playing?'Pause demo':'Resume demo';
    view.update(state,selected);
  }
  function changeView(id){
    const field=id==='field';document.body.classList.toggle('field',field);
    $('workshop').setAttribute('aria-pressed',!field);$('field').setAttribute('aria-pressed',field);
    $('title').textContent=field?'Field crew':'Application workshop';
    $('sceneKind').textContent=field?'Verification field':'Workshop floor';
    $('sceneLabel').textContent=field?'One row per application':'Intake · Fill · Verify · Dispatch';
    $('legend').textContent=field?'Raised = verified · Flag = needs you':'Orange folder = current application';
    stationNote=null;view.view(field);draw();
  }
  $('workshop').onclick=()=>changeView('workshop');$('field').onclick=()=>changeView('field');
  $('reset').onclick=newState;$('play').onclick=toggle;newState();
  if(location.hash==='#field')changeView('field');
})();
