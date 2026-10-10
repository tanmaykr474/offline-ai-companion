import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root = 'C:/Users/tanma/Desktop/ai-companion';
const runtime = 'C:/Users/tanma/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES = runtime+'/node/node_modules';
const skill = 'C:/Users/tanma/.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations';
const {Presentation, PresentationFile} = await import(pathToFileURL(runtime+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const build = root+'/docs/hackathon-presentation/architecture-build';
const out = root+'/docs/hackathon-presentation/evaluation-output';
await fs.mkdir(build,{recursive:true}); await fs.mkdir(out,{recursive:true});
const deck = Presentation.create({slideSize:{width:1280,height:720}});
const colors={bg:'#091923',title:'#FFFFFF',body:'#D8E2E8',accent:'#75E3C0',muted:'#93A8B5'};
function text(s, value, x,y,w,h,size=29,color=colors.body,bold=false){
 const box=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 box.text=value; box.text.style={typeface:'Arial',fontSize:size,color,bold}; return box;
}
function slide(title,notes){
 const s=deck.slides.add();s.background.fill=colors.bg;
 text(s,title,70,58,1140,100,45,colors.title,true);
 text(s,String(deck.slides.items.length).padStart(2,'0'),1165,657,50,28,18,colors.muted);
 s.speakerNotes.text=notes;return s;
}
function rows(s,items){ items.forEach(([label,body],i)=>{const y=195+i*103;text(s,label,72,y,315,75,29,colors.accent,true);text(s,body,405,y,790,84,28);}); }
const s1=deck.slides.add();s1.background.fill=colors.bg;
const art=await fs.readFile(root+'/docs/hackathon-presentation/redesign/assets/nova-voice-art.png');
s1.images.add({blob:art.buffer.slice(art.byteOffset,art.byteOffset+art.byteLength),contentType:'image/png',alt:'Abstract voice artwork',position:{left:0,top:0,width:1280,height:720},fit:'cover'});
text(s1,'NOVA',72,170,600,110,84,colors.title,true);
text(s1,'Offline AI companion',76,300,600,60,38,colors.accent);
text(s1,'Voice interaction with persistent memory\nand explicit privacy controls',76,397,640,100,29);
text(s1,'Hackathon evaluation',76,606,600,40,23,colors.muted);
s1.speakerNotes.text='Introduce Nova as an offline-first personal voice companion. The artwork is an abstract illustration reused from the project assets, not a photograph of the prototype. Explain that today\'s live demo runs on Windows.';
rows(slide('Introduction', 'The original goal was a 24-hour hackathon prototype. Explain the intended need without claiming market statistics or medical benefits. Source: project handoff and current user discussion.'),[
 ['Purpose','A voice companion that remembers useful information and helps manage everyday work.'],
 ['Interaction','Say Nova to ask a question, save a note, or manage a task or reminder.'],
 ['Local operation','Speech recognition, language inference, speech synthesis and SQLite storage run locally.'],
 ['Deployment target','Windows development today. Raspberry Pi 5 with 4 GB RAM as the deployment target.']]);
rows(slide('The solution', 'Explain each layer in order. Whisper.cpp transcribes audio, wake detection activates supported requests, and deterministic tools handle memory and scheduling. Ollama handles general conversation and Piper speaks. Sources: scripts/always_on_assistant.py and project stack.'),[
 ['Voice input','Microphone capture and voice activity detection feed local Whisper.cpp transcription.'],
 ['Request handling','Wake detection routes active commands to the assistant, local tools or Ollama.'],
 ['Persistent storage','SQLite stores confirmed facts, observations, notes, tasks and reminders.'],
 ['Voice response','Piper generates speech. The default mode returns to listening after playback.']]);
const architecture=slide('Nova architecture', 'Read the top row left to right. All captured speech passes the software mute gate before transcription. Wake detection routes active commands through Assistant and QueryRouter. Optional non-wake speech enters a bounded passive queue and grounding processor with no spoken reply. Active tools save and retrieve SQLite records. General conversation uses loopback-only Ollama. The scheduler supplies due reminders to the voice output loop. Piper synthesis and speaker playback complete active responses. Controls apply across the runtime. Online weather and news are explicit opt-in exceptions and receive no memory or history. Sources: scripts/always_on_assistant.py; core/assistant.py; memory/passive_worker.py; memory/passive_processor.py; router/query_router.py; tools/online_tools.py. Pi hardware validation remains pending.');
function node(label,x,y,w,h=70){
 const n=architecture.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:'#12303D',line:{fill:'#75E3C0',width:1}});
 n.text=label;n.text.style={typeface:'Arial',fontSize:25,color:colors.title};return n;
}
function arrow(x,y,w,h=18,geometry='rightArrow'){
 architecture.shapes.add({geometry,position:{left:x,top:y,width:w,height:h},fill:colors.accent,line:{fill:'none',width:0}});
}
node('Microphone\nMute gate and VAD',72,177,325,78);
arrow(410,205,38);node('Whisper.cpp\nLocal transcription',462,177,325,78);
arrow(800,205,38);node('Wake detection\nActive or passive routing',853,177,350,78);
arrow(620,270,20,35,'downArrow');
node('Active commands\nAssistant and QueryRouter',72,325,520,78);
node('Optional background speech\nBounded queue and grounding',683,325,520,78);
text(architecture,'Wake command',75,280,400,35,22,colors.accent);
text(architecture,'No wake phrase',686,280,400,35,22,colors.accent);
arrow(310,411,20,30,'downArrow');arrow(930,411,20,30,'downArrow');
node('Memory tools and loopback Ollama\nOptional weather and news tools',72,448,520,78);
node('Local SQLite\nFacts, observations, notes, tasks, reminders',683,448,520,78);
arrow(605,477,65,18,'leftRightArrow');
arrow(310,535,20,27,'downArrow');
text(architecture,'Piper synthesis and speaker playback',74,568,655,43,28,colors.accent,true);
text(architecture,'Scheduler delivers due reminders',710,570,495,40,23);
text(architecture,'Privacy and cancellation controls apply across the runtime. Online tools require explicit opt-in.',74,629,1070,38,21,colors.muted);
rows(slide('Features available today', 'These are implemented software capabilities. Avoid claiming all have just passed physical testing. Explicit memory and hello worked in the latest user demonstration. Sources: docs/TASKS_AND_REMINDERS.md, docs/PRIVACY.md and user confirmation.'),[
 ['Voice assistant','Continuous listening, wake activation, local conversation and spoken responses.'],
 ['Personal memory','Confirmed facts, optional passive observations, paraphrased recall and memory review.'],
 ['Daily organization','Persistent notes, task completion and editing, reminder scheduling and rescheduling.'],
 ['User control','Software mute, confirmed deletion, privacy filtering and optional interruption.']]);
rows(slide('Current operating options', 'Keep the working defaults for evaluation. Online providers require explicit opt-in. Experimental interruption has echo limitations. GPIO and service preparation do not establish real hardware success. Sources: config and deployment documentation.'),[
 ['Default voice mode','Half-duplex operation preserves the established listening and playback behavior.'],
 ['Optional features','Passive extraction and experimental console or spoken interruption use configuration flags.'],
 ['Live information','Open-Meteo weather and NewsAPI headlines require explicit online enablement.'],
 ['Pi preparation','ARM64 setup, model provisioning, GPIO controls and systemd startup are implemented.']]);
rows(slide('Limitations addressed in software', 'Describe these as safeguards implemented and regression-tested, not guarantees of flawless real-world operation. Sources: module history 12.7.1 through 12.9 and docs/PRIVACY.md.'),[
 ['Unsupported memories','Grounding rejects negation, questions, hypotheticals and unsupported task or event claims.'],
 ['Unsafe network access','Ollama accepts loopback endpoints. External tools stay disabled by default.'],
 ['Privacy exposure','Credential checks, sanitized diagnostics, temporary audio cleanup and optional retention.'],
 ['Lifecycle failures','Mute boundaries, bounded queues, accepted-work draining and confirmed record changes.']]);
rows(slide('Current limitations', 'Be transparent: the recent passive extraction produced five rejected suggestions and zero saves. Active voice sometimes misses an answer. Bluetooth standalone output worked but recorded microphone audio contained static on Pi. Multi-hour physical soak remains deferred.'),[
 ['Intermittent responses','Some live voice attempts miss an answer. Commands need clear speech and completion time.'],
 ['Passive recall','The recent passive attempt saved no memories. Demo reliability still needs validation.'],
 ['Raspberry Pi audio','Speaker-only playback works. Microphone recordings still produce static.'],
 ['Pending validation','Physical GPIO and systemd tests, extended reliability runs, and live provider tests remain.']]);
rows(slide('Our demonstration approach', 'The user confirmed hello and favorite-food saving and recall worked. Do not describe the remaining sequence as already performed. Present it as the live demonstration plan. Source: latest conversation.'),[
 ['Working platform','Run Nova on the tested Windows setup while showing the Raspberry Pi prototype separately.'],
 ['Observed success','Hello and favorite-food saving and recall worked in the latest live test.'],
 ['Demo sequence','Greeting, explicit memory, note, task, reminder, mute and recall after restart.'],
 ['Fallback','Keep a local recording of a successful run. Avoid new installations during evaluation.']]);
const demo=slide('Live evaluation commands', 'Say one command at a time. Wait for LISTENING. Say Nova, yes only when asked for confirmation. Do not repeat writes blindly if playback fails. Replace task IDs with IDs that Nova actually returns. Sources: current command checklist and supported router documentation.');
rows(demo,[
 ['1  Save and recall','Nova, my favorite food is biryani.\nNova, what is my favorite food?'],
 ['2  Notes and tasks','Nova, remember that the demo is in room seven.\nNova, add a task to finish my project.'],
 ['3  Reminder','Nova, remind me to drink water in 1 minute.'],
 ['4  Mute and restart','Press M to test mute. Unmute, restart, then recall the saved favorite food.']]);
rows(slide('Use cases', 'These are intended applications of implemented features, not measured outcomes. Nova is not a medical, financial or safety-critical assistant.'),[
 ['Students','Capture project notes and create reminders for study sessions or deadlines.'],
 ['Developers','Manage project tasks and recall preferences without switching to a keyboard.'],
 ['Everyday routines','Save explicitly requested facts and receive reminders for ordinary activities.'],
 ['Limited connectivity','Use local voice and memory after provisioning without a cloud inference service.']]);
rows(slide('Privacy and deployment boundaries', 'SQLite deletion is not secure erasure and local storage does not imply encryption at rest. Software mute is not an electrical microphone cutoff. Never treat an unknown passive speaker as the owner. No real Pi deployment validation claim.'),[
 ['Explicit authority','Confirmed facts take priority. Passive observations preserve speaker attribution.'],
 ['Safe changes','Corrections and destructive actions require confirmation and scoped record selection.'],
 ['Storage limits','Data stays local, but local storage alone does not guarantee encryption or secure erasure.'],
 ['Physical prototype','GPIO mute controls software capture. Pi audio and hardware validation remain pending.']]);
const end=slide('Thank you', 'Invite questions and offer the live demonstration. Reiterate that the validated software demo is on Windows and Raspberry Pi microphone audio remains unresolved.');
text(end,'Questions and live demonstration',74,255,1080,90,44,colors.accent);
text(end,'Nova\nOffline voice interaction with persistent memory',74,405,1080,100,31);
for(const [i,s] of deck.slides.items.entries()){
 const blob=await deck.export({slide:s,format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const candidate=build+'/candidate.pptx';await(await PresentationFile.exportPptx(deck)).save(candidate);
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:out+'/Nova Evaluation With Architecture.pptx',pythonExecutable:runtime+'/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],fontPolicy:{basis:'design',families:['Arial']},verifyArtifactToolImport:true,receiptPath:build+'/validation-architecture.json'});
console.log(JSON.stringify(result));

