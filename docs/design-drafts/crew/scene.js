// The scene reads demo state. All queue transitions live in demo.js.
function makeCrewScene(host, selectJob, inspectStation) {
  const T = window.THREE;
  let renderer;
  try { renderer = new T.WebGLRenderer({antialias:true, alpha:false}); }
  catch {
    host.insertAdjacentHTML("beforeend", '<p class="fallback">3D is unavailable in this browser. You can still run the simulation and follow each worker in Activity.</p>');
    return {update(){}, view(){}};
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label", "3D crew. Drag or use the left and right arrow keys to change the angle.");
  host.prepend(canvas);
  const scene = new T.Scene(), camera = new T.OrthographicCamera(-10,10,5,-5,.1,90);
  const sun = new T.DirectionalLight(0xfff3dd,2.8);
  sun.position.set(-8,13,8); sun.castShadow = true;
  Object.assign(sun.shadow.camera, {left:-12,right:12,top:12,bottom:-12,far:42});
  sun.shadow.mapSize.set(2048,2048); sun.shadow.bias = -.00045; sun.shadow.normalBias = .025;
  scene.add(sun, new T.AmbientLight(0xffffff,1.65));
  const shapes = new Map(), materials = new Map();
  function cached(map,key,make){ if(!map.has(key)) map.set(key,make()); return map.get(key); }
  function mat(color){return cached(materials,color,()=>new T.MeshStandardMaterial({color,roughness:.72}));}
  function mesh(p,g,m,x,y,z) {
    const o = new T.Mesh(g,m); o.position.set(x,y,z); o.castShadow = true; o.receiveShadow = true; p.add(o); return o;
  }
  function box(p,x,y,z,w,h,d,color,r=0) {
    const geometry = cached(shapes,['b',w,h,d,r].join('/'),()=>r?new T.RoundedBoxGeometry(w,h,d,2,Math.min(r,w/2,h/2,d/2)):new T.BoxGeometry(w,h,d));
    return mesh(p,geometry,mat(color),x,y,z);
  }
  function cyl(p,x,y,z,top,bottom,h,color,n=24) {
    const g=cached(shapes,['c',top,bottom,h,n].join('/'),()=>new T.CylinderGeometry(top,bottom,h,n));
    return mesh(p,g,mat(color),x,y,z);
  }
  function ball(p,x,y,z,r,color) {
    const g=cached(shapes,'s'+r,()=>new T.SphereGeometry(r,18,12));
    return mesh(p,g,mat(color),x,y,z);
  }
  function group(p,x=0,y=0,z=0){const g=new T.Group();g.position.set(x,y,z);p.add(g);return g;}
  function rod(p,a,b,r,color){
    const av=new T.Vector3(...a), bv=new T.Vector3(...b), dir=bv.clone().sub(av);
    const o=cyl(p,0,0,0,r,r,dir.length(),color,12);
    o.position.copy(av.add(bv).multiplyScalar(.5));o.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),dir.normalize());return o;
  }
  function plate(p,x,y,z,w,h,text,bg,fg,fontsize=110) {
    const c=document.createElement('canvas'); c.width=768;c.height=160;
    const ctx=c.getContext('2d');ctx.fillStyle=bg;ctx.fillRect(0,0,c.width,c.height);ctx.fillStyle=fg;
    ctx.font='bold '+fontsize+'px Helvetica Neue, Arial, sans-serif';ctx.textBaseline='middle';ctx.textAlign='center';ctx.fillText(text,384,84,740);
    const tex=new T.CanvasTexture(c);tex.colorSpace=T.SRGBColorSpace;tex.anisotropy=4;
    const o=mesh(p,new T.PlaneGeometry(w,h),new T.MeshStandardMaterial({map:tex,roughness:1}),x,y,z);
    o.castShadow=false;return o;
  }
  const dark='#233932',cream='#f4ead1', blue='#39678a',mint='#698d70',orange='#e56c36',yellow='#f2b338';
  function worker(p,x,y,z,paint,id,field=false) {
    const root=group(p,x,y,z), torso=group(root,0,.53,0);
    root.userData[field?'job':'station']=id;
    const boots=field?'#5d6359':dark, skin=field?'#d8dace':cream;
    for(const s of [-1,1]){
      cyl(root,s*.15,.35,0,.085,.086,.36,boots);
      box(root,s*.15,.15,.064,.235,.15,.30,boots,.055);
    }
    box(torso,0,.12,0,.49,.53,.36,paint,.105);
    box(torso,0,.025,.192,.26,.17,.035,skin,.025);
    cyl(torso,0,.46,0,.12,.14,.17,boots);
    const head=group(torso,0,.63,0);
    box(head,0,0,0,.66,.48,.47,skin,.13);
    box(head,0,.008,.225,.49,.23,.075,boots,.065);
    for(const side of [-1,1]){
      box(head,side*.113,.02,.268,.067,.080,.018,field?'#f3f2df':'#ffcd84',.012);
      ball(head,side*.335,-.025,.005,.067,paint);
    }
    cyl(head,-.14,.28,-.04,.017,.017,.12,boots,10);ball(head,-.14,.36,-.04,.044,paint);
    const arms = [-1,1].map(s=>{
      const arm=group(torso,s*.276,.26,.01);
      ball(arm,0,0,0,.076,boots);rod(arm,[0,0,0],[s*.084,-.15,.10],.055,paint);
      ball(arm,s*.084,-.15,.10,.06,boots);rod(arm,[s*.084,-.15,.10],[s*.083,-.16,.25],.047,boots);
      ball(arm,s*.083,-.16,.25,.073,skin);return arm;
    });
    return {root,head,arms,torso};
  }
  const floor=box(scene,0,-.62,0,160,.10,160,'#b8cbbd');
  const shop=group(scene),field=group(scene);
  const spots=[[-5.35,.35],[-1.8,-.53],[1.8,-.53],[5.35,.35]];
  const names=['INTAKE','FILL','VERIFY','DISPATCH'], paints=[yellow,blue,mint,orange];
  const bots=[],bulbs=[];
  for(let i=0;i<4;i++){
    const [x,z]=spots[i], station=group(shop,x,0,z);station.userData.station=i;
    box(station,0,-.27,0,3.38,.44,3.35,'#5e746a',.17);
    box(station,0,-.018,0,3.36,.19,3.33,'#ecdfba',.14);
    box(station,0,.09,0,3.23,.08,3.19,'#ddd3b5',.09);
    box(station,0,-.14,1.676,2.3,.31,.045,dark,.025);
    plate(station,0,-.14,1.703,2.24,.245,'0'+(i+1)+'  /  '+names[i],dark,'#ffedc9',100);
    const machine=group(station,.14,0,-.37);
    box(machine,0,.20,0,2.06,.15,1.28,dark,.065);
    box(machine,0,.55,0,1.86,.65,1.18,paints[i],.095);
    box(machine,0,.91,0,2.12,.12,1.38,cream,.055);
    for(const s of [-1,1]){box(machine,s*.74,.65,.602,.06,.21,.027,dark,.015);}
    // Each machine has a distinct silhouette, even without its nameplate.
    if(i===0){
      for(let j=0;j<3;j++){
        box(machine,-.25,1.02+j*.21,-.18,1.22,.09,.81,blue,.038);
        box(machine,-.26,1.10+j*.21,-.22,1.04,.055,.61,cream,.018);
        box(machine,-.25,1.13+j*.21,-.57,1.22,.22,.072,blue,.021);
      }
      for(const s of [-1,1])box(machine,-.25+s*.57,1.28,-.27,.07,.51,.67,blue,.025);
    }
    if(i===1){
      box(machine,-.25,1.14,-.3,.15,.36,.17,dark,.03);
      const screen=group(machine,-.25,1.48,-.35);screen.rotation.x=-.12;
      box(screen,0,0,0,1.24,.75,.155,cream,.08);
      box(screen,0,.02,.084,1.02,.54,.02,dark,.035);
      for(let j=0;j<3;j++)box(screen,-.12,.17-j*.13,.105,.64-j*.065,.033,.014,'#9cbfa5');
      box(machine,-.09,.998,.30,.98,.055,.35,dark,.028);
      for(let j=0;j<3;j++)box(machine,-.12,1.033,.18+j*.088,.77,.02,.027,'#91a49b');
    }
    if(i===2){
      for(const s of [-1,1])box(machine,s*.67,1.3,-.19,.18,.77,.35,mint,.05);
      box(machine,0,1.75,-.19,1.52,.22,.38,mint,.065);
      box(machine,0,1.62,-.17,1.04,.033,.20,'#c7ec81');
      for(let j=0;j<5;j++){const roller=cyl(machine,0,1.02,-.45+j*.20,.09,.09,1.18,'#5a7069');roller.rotation.z=Math.PI/2;}
    }
    if(i===3){
      box(machine,-.10,1.43,-.18,1.34,1.03,.83,orange,.13);
      box(machine,-.10,1.58,.246,.98,.17,.025,dark,.032);
      box(machine,-.10,1.47,.30,1.09,.07,.20,cream,.028);
      box(machine,-.10,1.14,.25,.47,.085,.018,cream,.012);
    }
    cyl(machine,.80,1.20,-.45,.031,.036,.47,dark,12);
    const bulb=ball(machine,.80,1.46,-.45,.12,cream);bulbs.push(bulb);
    const b=worker(station,-.68,.12,.89,paints[i],i);b.root.scale.setScalar(1.14);b.root.rotation.y=.68;bots.push(b);
    // Tool caddy on each workbench.
    cyl(machine,.71,1.066,.27,.115,.095,.21,dark);
    for(let k=0;k<3;k++)rod(machine,[.67+k*.038,1.09,.28],[.63+k*.075,1.31+(k%2)*.07,.25],.018,cream);
  }
  for(let i=0;i<3;i++){
    const [x,z]=spots[i], [nx,nz]=spots[i+1];
    rod(shop,[x+1.35,-.21,z],[nx-1.35,-.21,nz],.14,dark);
  }
  const folder=group(shop);
  box(folder,0,0,0,.68,.085,.49,orange,.035);
  box(folder,-.17,.005,-.255,.29,.065,.11,orange,.02);
  box(folder,.025,.055,.015,.53,.028,.36,cream,.012);
  for(let i=0;i<2;i++)box(folder,-.025,.073,-.05+i*.10,.26,.01,.016,dark);

  const questionSign=group(bots[2].root,.41,1.91,.14);
  box(questionSign,0,0,0,.42,.47,.052,yellow,.055);
  plate(questionSign,0,0,.032,.34,.35,'?',yellow,dark,158);
  questionSign.visible=false;
  const receiptSlip=group(shop,spots[3][0]+.04,1.29,spots[3][1]+.06);
  box(receiptSlip,0,0,0,.70,.05,.61,cream,.012);
  for(let j=0;j<3;j++)box(receiptSlip,-.04,.032,-.13+j*.095,.38,.012,.018,dark);
  receiptSlip.visible=false;

  // One field per tile. Each row corresponds to an application in the list.
  const barBots=[],tiles=[], outlines=[], flags=[], barsPerJob=9;
  const ink='#353b35',lime='#b7d94a',chalk='#d4d8c9';
  for(let i=0;i<3;i++){
    const z=(i-1)*2.35, row=group(field,0,0,z);row.userData.job=i;
    box(row,0,-.17,0,12.8,.27,1.86,'#444b41',.07);
    box(row,0,-.017,0,12.72,.055,1.78,'#292e29',.03);
    plate(row,4.98,-.14,.94,2.0,.22,['LUMEN','HARBOR','NORTHWIND'][i],'#282e27','#e9eee1',104);
    const rowTiles=[], edges=[];
    for(let j=0;j<barsPerJob;j++){
      const x=-3.95+j*.93;
      const block=box(row,x,.04,-.02,.64,1,1.04,chalk,.035);
      rowTiles.push(block);
      const edge=new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(.69,.055,1.10)),new T.LineBasicMaterial({color:'#9aa48f'}));
      edge.position.set(x,.039,-.02);row.add(edge);edges.push(edge);
    }
    tiles.push(rowTiles);outlines.push(edges);
    const b=worker(row,-5.32,0,.13,i===0?lime:'#aab1a2',i,true);b.root.rotation.y=.40;b.root.scale.setScalar(1.2);barBots.push(b);
    const flag=group(row);rod(flag,[0,0,0],[0,.57,0],.025,lime);box(flag,.14,.46,0,.28,.18,.04,lime,.018);flags.push(flag);
  }
  field.visible=false;
  let fieldMode=false, state=null, selected=0, yaw=.34, dragging=null, dirty=true, w=0,h=0;
  let animate=true, elapsed=0, previous=performance.now(), packetX=spots[0][0], packetZ=spots[0][1];
  const reduce=matchMedia('(prefers-reduced-motion: reduce)');
  function setView(value){
    fieldMode=value;field.visible=value;shop.visible=!value;
    floor.material=mat(value?'#262c26':'#b7cabe');scene.background=new T.Color(value?'#262c26':'#c5d6cb');
    yaw=value?.37:.32;dirty=true;
  }
  function resize(){
    w=host.clientWidth;h=host.clientHeight;if(!w||!h)return;
    renderer.setSize(w,h,false);dirty=true;
  }
  new ResizeObserver(resize).observe(host);
  function update(s,sel){
    state=s;selected=sel;dirty=true;
    if(!state.jobs[0].verified && state.jobs[0].phase==='queued'){packetX=spots[0][0];packetZ=spots[0][1];}
  }
  const pick=new T.Raycaster();
  function selectAt(e){
    const rect=canvas.getBoundingClientRect();
    const point=new T.Vector2((e.clientX-rect.left)/rect.width*2-1,1-(e.clientY-rect.top)/rect.height*2);
    pick.setFromCamera(point,camera);
    for(const hit of pick.intersectObjects((fieldMode?field:shop).children,true)){
      let o=hit.object;
      while(o){if(o.userData.job!=null){selectJob(o.userData.job);return;}
        if(o.userData.station!=null){inspectStation(o.userData.station);return;}o=o.parent;}
    }
  }
  canvas.addEventListener('pointerdown',e=>{dragging={x:e.clientX,y:e.clientY,yaw};canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(dragging){yaw=Math.max(-.75,Math.min(.85,dragging.yaw+(e.clientX-dragging.x)*.005));dirty=true;}});
  canvas.addEventListener('pointerup',e=>{if(dragging && Math.hypot(e.clientX-dragging.x,e.clientY-dragging.y)<6)selectAt(e);dragging=null;});
  canvas.addEventListener('pointercancel',()=>{dragging=null;});
  canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();yaw=Math.max(-.75,Math.min(.85,yaw+(e.key==='ArrowLeft'?-.12:.12)));dirty=true;});
  function cameraPose(){
    const aspect=w/h;
    // Keep the entire row of machines in view on narrow screens.
    const half=Math.max(fieldMode?3.85:3.12, (fieldMode?7.35:7.85)/aspect);
    Object.assign(camera,{left:-half*aspect,right:half*aspect,top:half,bottom:-half});
    camera.position.set(Math.sin(yaw)*16,fieldMode?11.2:8.5,Math.cos(yaw)*16);
    camera.lookAt(0,fieldMode?.30:.60,0);camera.updateProjectionMatrix();
  }
  function frame(now){
    requestAnimationFrame(frame);
    const dt=Math.min(.07,(now-previous)/1000);previous=now;
    if(!state||!w||!h||document.hidden)return;
    const job=state.jobs[state.active], work=job.station;
    animate=state.playing&&!reduce.matches;
    if(!dirty&&!animate)return;
    if(animate)elapsed+=dt;
    cameraPose();
    if(fieldMode){
      state.jobs.forEach((j,i)=>{
        const blocked=j.phase==='question', checked=j.verified, accent=i===selected;
        tiles[i].forEach((block,k)=>{
          const stop=blocked&&k===checked,done=k<checked;
          const height=stop?1.85:done?.55+.10*(k%3):.035;
          block.scale.y=height;block.position.y=.035+height/2;
          block.material=mat(stop?lime:done?(accent?'#e7eadb':'#aeb5a7'):ink);
          outlines[i][k].visible=!done;
        });
        flags[i].visible=blocked;
        flags[i].position.set(-3.95+checked*.93,1.90,0);
        const b=barBots[i];b.root.position.x=(i===state.active&&j.phase!=='queued')?-3.95+Math.min(8,checked)*.93:-5.32;
        b.root.position.z=i===state.active&&j.phase!=='queued'?.76:.13;
        b.arms[1].rotation.x=blocked?-1.6:0;
        b.head.rotation.y=(animate&&i===state.active)?Math.sin(elapsed*3)*.13:0;
      });
    }else{
      const [x,z]=spots[work], smooth=reduce.matches||!state.playing?1:1-Math.exp(-7*dt);
      packetX+=(x-packetX)*smooth;packetZ+=(z-packetZ)*smooth;
      folder.position.set(packetX+.16,1.18+(animate?Math.sin(elapsed*4)*.025:0),packetZ+.24);
      folder.rotation.y=-.13;
      const dispatched=['send','receipt','done'].includes(job.phase);
      if(dispatched){
        folder.position.set(x+.04,1.56,z-.05);
        if(job.phase==='send')folder.position.z+=Math.max(0,.19-.07*Math.sin(elapsed*3));
      }
      folder.visible=!['receipt','done'].includes(job.phase);
      receiptSlip.visible=job.phase==='done';
      questionSign.visible=job.phase==='question';
      bots.forEach((b,i)=>{
        const active=work===i, blocked=active&&job.phase==='question', moving=active&&animate;
        b.root.position.x=moving?-.97:-.68;
        b.root.position.z=moving?.44:.89;
        b.root.rotation.y=moving?1.51:.68;
        b.head.rotation.y=blocked?-.60:moving?Math.sin(elapsed*4)*.22:-.18;
        b.torso.rotation.x=moving?.13+.045*Math.sin(elapsed*5):0;
        b.arms[1].rotation.z=blocked?2.43:0;
        b.arms[1].rotation.x=moving?-.90+.45*Math.sin(elapsed*7):0;
        b.arms[0].rotation.x=moving?-.75-.34*Math.sin(elapsed*7):0;
        bulbs[i].material=mat(active?(blocked?orange:yellow):cream);
      });
    }
    renderer.render(scene,camera);dirty=false;
  }
  setView(false);resize();requestAnimationFrame(frame);
  return {update,view:setView};
}
