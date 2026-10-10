import fs from 'node:fs/promises';
import path from 'node:path';
import {Presentation,PresentationFile} from 'file:///C:/Users/tanma/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
process.env.RUNTIME_NODE_MODULES='C:/Users/tanma/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const ROOT='C:/Users/tanma/Desktop/ai-companion/docs/hackathon-presentation';
const OUT=path.join(ROOT,'redesign');
const SKILL='C:/Users/tanma/.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations';
const {finalizePresentation}=await import('file:///'+SKILL+'/container_tools/artifact_tool_utils.mjs');
const P=Presentation.create({slideSize:{width:1600,height:900}});
const C={navy:'#08131F',mint:'#9BF2C7',green:'#007C65',white:'#F5F4EE',ink:'#102C38',muted:'#AEC0CB',grey:'#526976',line:'#35515F',amber:'#F0C68A',red:'#ED8C97',blue:'#85BCF2'};
const originalNotes=(await fs.readFile(path.join(ROOT,'speaker-notes.md'),'utf8')).split(/^## \d+\..*$/m).slice(1);
const titles=[];
function text(s,str,x,y,w,h,size=30,color=C.white,bold=false,align='left'){
 const q=s.shapes.add({geometry:'textbox',name:str.slice(0,45),position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 q.text=str;q.text.style={typeface:'Arial',fontSize:size,color,bold,alignment:align,verticalAlignment:'top',wrap:'square',autoFit:'none',insets:0};return q;
}
function line(s,x,y,w,color=C.line){return s.shapes.add({geometry:'line',position:{left:x,top:y,width:w,height:0},line:{fill:color,width:1.4}});}
function page(n,title,dark=true){const s=P.slides.add();s.background.fill=dark?C.navy:C.white;s.dark=dark;
 text(s,'NOVA',80,40,120,30,19,dark?C.mint:C.green,true);
 text(s,String(n).padStart(2,'0'),1450,40,70,30,18,dark?C.muted:C.grey,false,'right');
 if(title) text(s,title,80,115,1420,95,58,dark?C.white:C.ink,true);
 titles.push(title||'Nova');
 let note=originalNotes[n-1]||'';
 note=note.replace(/Audit snapshot:[^\n]*/g,'').replace(/Read verification\.md[^.]*\./g,'The saved qualified test run contains 1,272 passes and six subprocess environment failures.').replace(/[^\n]*verification\.md[^\n]*/g,'The saved qualified test run contains 1,272 passes and six subprocess environment failures. Physical Pi validation is pending.');
 s.speakerNotes.text=note.trim();return s;
}
function footer(s,str){text(s,str,80,824,1440,42,21,s.dark?C.muted:C.grey);}
function row(s,y,num,title,body,dark=s.dark){const ink=dark?C.white:C.ink;line(s,80,y-15,1440,dark?C.line:'#CAD4CE');text(s,num,80,y+8,85,65,43,dark?C.mint:C.green);text(s,title,200,y+6,540,70,35,ink,true);text(s,body,810,y+10,670,100,27,dark?C.muted:C.grey);}
function box(s,label,sub,x,y,w=210,h=108,fill='#142B36',color=C.white){const q=s.shapes.add({geometry:'rect',name:label,position:{left:x,top:y,width:w,height:h},fill,line:{fill:'#42606C',width:1}});text(s,label,x+16,y+17,w-32,42,24,color,true);if(sub)text(s,sub,x+16,y+61,w-32,h-64,21,color);return q;}
function connect(s,a,b,from='right',to='left',color=C.mint,dashed=false,kind='straight',both=false){s.shapes.connect(a,b,{kind,fromSide:from,toSide:to,line:{fill:color,width:2.2,style:dashed?'dash':'solid'},tail:{type:'triangle',width:'sm',length:'sm'},...(both?{head:{type:'triangle',width:'sm',length:'sm'}}:{})});}
const bytes=await fs.readFile(path.join(OUT,'assets/nova-voice-art.png'));const blob=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
function art(s){s.images.add({blob,contentType:'image/png',alt:'Abstract mint sound-wave artwork, generated illustration',fit:'cover',position:{left:0,top:0,width:1600,height:900}});}

// 01: minimal cover, original art and editable typography.
{
 const s=page(1,'');art(s);
 text(s,'NOVA',80,180,850,180,156,C.white,true);
 text(s,'Personal AI,\non your own device',88,395,790,175,64,C.mint,true);
 text(s,'Offline voice assistance with persistent memory',90,650,790,78,29,C.white);
 text(s,'Hackathon presentation / October 2026',90,806,1000,32,20,C.muted);
 s.speakerNotes.text+='\nCover artwork is an AI-generated abstract illustration, not a photo of prototype hardware.';
}
// 02: restrained editorial problem framing.
{
 const s=page(2,'The problem',false);
 text(s,'A useful assistant\nshould remain useful\nwithout the Internet',80,275,750,315,67,C.ink,true);
 text(s,'The everyday friction',960,282,530,45,27,C.green,true);
 text(s,'Lost connectivity\n\nRepeated personal context\n\nUnclear microphone controls',960,363,560,280,32,C.ink);
 footer(s,'Design goal: local assistance, persistent context and visible control');
}
// 03: integration innovation rather than inflated model claims.
{
 const s=page(3,'The Nova solution');
 text(s,'Local voice.\nMemory that persists.',80,250,1400,170,70,C.white,true);
 row(s,455,'01','Local conversation','Whisper, Llama and Piper run on the device');
 row(s,575,'02','Grounded personal memory','Confirmed facts take priority over optional observations');
 row(s,695,'03','Controlled actions','Deterministic tools and shared microphone permission');
 footer(s,'Innovation comes from the integration of existing models, memory and controls');
}
// 04: editable architecture with limited crossings and generous spacing.
{
 const s=page(4,'System architecture');
 text(s,'LOCAL DEVICE',80,220,850,30,20,C.mint,true);
 const a=box(s,'Mic + VAD','16 kHz / RMS',80,290,220,110);
 const b=box(s,'Whisper STT','Local tiny.en',350,290,220,110);
 const c=box(s,'Activation','Nova prefix',620,290,220,110);
 const d=box(s,'Assistant','Recall / tools / chat',890,290,240,110);
 const e=box(s,'Piper + speaker','Local speech output',1210,290,310,110);
 connect(s,a,b);connect(s,b,c);connect(s,c,d);connect(s,d,e);
 const pass=box(s,'Passive worker','Opt-in observations',620,495,220,112);
 const llm=box(s,'Ollama','Llama 3.2 1B',890,495,240,112);
 const db=box(s,'SQLite memory','Facts / tasks / notes',620,670,220,112);
 const rem=box(s,'Reminders','Leases + playback',1210,670,310,112);
 connect(s,c,pass,'bottom','top',C.muted,true);
 connect(s,d,llm,'bottom','top',C.mint,false,'straight',true);
 connect(s,pass,db,'bottom','top',C.muted,true);
 connect(s,pass,llm,'right','left',C.muted,true,'straight',true);
 connect(s,d,db,'left','right',C.mint,false,'elbow',true);
 connect(s,rem,db,'left','right',C.mint,false,'straight',true);
 text(s,'Recall / read / write',888,626,290,34,20,C.muted);
 text(s,'Reminder output uses the main loop',1170,789,350,25,17,C.muted);
 const net=box(s,'Weather / news','Opt-in HTTPS only',1210,495,310,112,'#3C3021',C.amber);
 connect(s,d,net,'right','left',C.amber,true,'elbow',true);
 text(s,'GPIO + mute controls',80,495,440,45,28,C.mint,true);
 text(s,'Switch gates microphone permission\nRGB LED reflects runtime state\n\nSequential capture and playback',80,556,470,160,25,C.white);
 footer(s,'Mint: local flow   Dashed: optional/control flow   Amber: Internet   Memory remains plaintext');
 s.speakerNotes.text+='\nThe compact diagram groups routing, memory tools and scheduler output inside the main loop. Local model traffic is loopback. The optional passive worker can use local Ollama for extraction and writes grounded observations to SQLite. GPIO state is software permission, not electrical cutoff. Physical Pi operation is not verified.';
}
// 05: stack as an editorial table with a prominent model scale.
{
 const s=page(5,'The technology stack',false);
 text(s,'1B',80,263,600,205,174,C.green,true);
 text(s,'Llama 3.2 parameters',88,494,570,55,30,C.ink,true);
 text(s,'Small local model\nfor a constrained-device target',88,577,570,100,28,C.grey);
 const entries=[['Speech input','whisper.cpp / tiny.en'],['Reasoning','Ollama / llama3.2:1b'],['Personal memory','SQLite / concept ranking'],['Speech output','Piper / lessac voice'],['Runtime','Python 3.13 / ARM64 target']];
 entries.forEach((r,i)=>{const y=266+i*104;line(s,765,y-14,755,'#CAD4CE');text(s,r[0],765,y+9,290,60,27,C.grey);text(s,r[1],1078,y+9,440,66,28,C.ink,true);});
 footer(s,'Internet is needed for provisioning. Core operation uses preloaded local models.');
}
// 06: actual interaction plus native process diagram.
{
 const s=page(6,'Working flow');
 text(s,'“Nova, remind me to drink\nwater in one minute.”',80,253,1410,165,62,C.mint,true);
 const vals=[['01','Listen','RMS VAD creates\na bounded utterance'],['02','Understand','Whisper transcribes.\nNova prefix activates.'],['03','Act','A deterministic tool\nstores the reminder'],['04','Speak','Piper responds.\nListening resumes.']];
 vals.forEach((v,i)=>{let x=80+i*365;text(s,v[0],x,486,220,75,58,C.mint);text(s,v[1],x,588,310,55,36,C.white,true);text(s,v[2],x,662,320,100,27,C.muted);});
 footer(s,'Wake-only follow-up lasts 8 seconds. Normal operation is sequential and half-duplex.');
}
// 07: memory principle shown with explicit synthetic examples.
{
 const s=page(7,'Memory with provenance',false);
 text(s,'Confirmed fact',80,273,650,55,36,C.green,true);
 text(s,'“My favorite food\nis pizza.”',80,377,700,165,62,C.ink,true);
 text(s,'Explicit confirmation\nPersistent SQLite record\nPriority during recall',80,600,650,150,29,C.grey);
 text(s,'Passive observation',895,273,625,55,36,C.ink,true);
 text(s,'“Someone mentioned\na dentist visit.”',895,390,625,145,43,C.ink);
 text(s,'Optional collection\nEvidence and timestamps\nUnidentified speaker',895,600,600,150,29,C.grey);
 footer(s,'Synthetic examples / grounded recall / scoped corrections and deletions');
 s.speakerNotes.text+='\nExamples on this slide are synthetic explanatory examples, not stored personal data. Passive storage is opt-in and does not identify the owner or automatically create tasks. Most fact changes require confirmation, but direct note/task/reminder creation and the legacy name path are exceptions. Do not promise confirmation for every write.';
}
// 08: state diagram and physical target qualification.
{
 const s=page(8,'Visible hardware controls');
 text(s,'Raspberry Pi 5',80,246,980,88,69,C.white,true);
 text(s,'Linux ARM64 deployment target',80,349,1050,57,34,C.muted);
 const states=[['Muted','RED',C.red],['Listening','GREEN',C.mint],['Processing / speaking','BLUE',C.blue]];
 states.forEach((v,i)=>{let y=457+i*106;const b=s.shapes.add({geometry:'ellipse',name:v[0]+' LED state',position:{left:85,top:y+4,width:34,height:34},fill:v[2],line:{fill:'none',width:0}});text(s,v[0],155,y,700,60,36,v[2],true);});
 text(s,'GPIO implementation',1060,257,470,48,30,C.mint,true);
 text(s,'RGB: BCM 17 / 27 / 22\nSwitch: BCM 23\n\nRestart begins muted\nGPIO faults latch mute\nNon-root systemd service',1060,337,470,330,28,C.white);
 footer(s,'Physical Pi validation is pending. The switch controls software permission.');
}
// 09: a clean demo sequence, ready for live pitch.
{
 const s=page(9,'The live demonstration',false);
 row(s,276,'01','Disconnect external Internet','Ask a question using local voice models',false);
 row(s,409,'02','Save and recall','Confirm a synthetic preference, restart, then recall it',false);
 row(s,542,'03','Create a reminder','Show task persistence and audible reminder delivery',false);
 row(s,675,'04','Mute input','Verify that muted speech creates no new task',false);
 footer(s,'Use a separate demo database and preloaded models. Rehearse on the presentation device.');
}
// 10: limitations as design tradeoffs, without burying qualifications.
{
 const s=page(10,'Challenges and limits');
 text(s,'Runtime tradeoffs',80,264,650,60,36,C.mint,true);
 text(s,'Noise-sensitive RMS VAD\n\nSTT before wake activation\n\nSequential capture and response\n\nSmall context and shared CPU',80,366,700,350,32,C.white);
 text(s,'Validation and privacy',895,264,620,60,36,C.amber,true);
 text(s,'Physical Pi and long soak pending\n\nPlaintext memory\n\nNo speaker authentication\n\nNo electrical microphone cutoff',895,366,625,350,31,C.white);
 footer(s,'Experimental spoken interruption remains outside the core demo');
}
// 11: future work has a clear order, not a feature wish list.
{
 const s=page(11,'The next milestones',false);
 const vals=[['01','Validate the Pi','Boot and headless audio\nGPIO fault behavior\nThermal and latency soak'],['02','Strengthen the runtime','Portable installation\nReal voice CLI\nToken-bounded context'],['03','Improve interaction','Acoustic wake detection\nNoise and echo handling\nAuthentication and encryption']];
 vals.forEach((v,i)=>{let x=80+i*495;text(s,v[0],x,290,400,110,92,C.green,true);text(s,v[1],x,449,460,100,38,C.ink,true);text(s,v[2],x,597,460,157,29,C.grey);});
 footer(s,'Future scope / these capabilities are not claims of completed implementation');
}
// 12: memorable, calm ending.
{
 const s=page(12,'');art(s);
 text(s,'NOVA',80,103,450,75,44,C.mint,true);
 text(s,'Local voice.\nPersonal memory.\nVisible control.',80,255,830,300,78,C.white,true);
 text(s,'Implemented software foundation\nNext milestone: physical Pi validation',87,631,825,115,32,C.mint);
 text(s,'Thank you',87,819,750,36,22,C.muted);
 s.speakerNotes.text+='\nClosing artwork is an AI-generated abstract illustration. Invite questions on the local voice path, privacy boundaries and deployment plan.';
}
await fs.mkdir(path.join(OUT,'previews'),{recursive:true});
for(let i=0;i<P.slides.items.length;i++){
 const slide=P.slides.items[i];
 const png=await P.export({slide,format:'png',scale:1});
 await fs.writeFile(path.join(OUT,'previews',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 console.log('Rendered slide',i+1);
}
const candidate=path.join(OUT,'.build/nova-design-candidate.pptx');
await(await PresentationFile.exportPptx(P)).save(candidate);
await fs.writeFile(path.join(OUT,'speaker-notes.md'),P.slides.items.map((s,i)=>`## ${i+1}. ${titles[i]}\n\n${s.speakerNotes.text}\n`).join('\n'),'utf8');
await fs.writeFile(path.join(OUT,'.build/art-direction.md'),'Design: midnight navy, warm ivory, mint, Arial. 12 slides. Abstract voice artwork generated with built-in ImageGen. Prompt: widescreen dark navy background with a translucent mint/blue sculptural sound-wave loop at right, clean left negative space, no text/device/logo. Native editable architecture and LED state diagram. Original deck retained.','utf8');
await fs.mkdir(path.join(OUT,'output'),{recursive:true});
const finalPath=path.join(OUT,'output/nova-hackathon-design-edition.pptx');
const result=await finalizePresentation({workspaceDir:OUT,candidatePath:candidate,finalPath,pythonExecutable:'C:/Users/tanma/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-heading-fit'],explicitTotalSlideCount:12,fontPolicy:{basis:'design',families:['Arial']},verifyArtifactToolImport:true,receiptPath:path.join(OUT,'.build/validation.json')});
console.log('FINAL',finalPath,JSON.stringify(result));
