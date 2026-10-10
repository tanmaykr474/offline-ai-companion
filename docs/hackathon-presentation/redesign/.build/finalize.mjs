import path from 'node:path';
import fs from 'node:fs/promises';
process.env.RUNTIME_NODE_MODULES='C:/Users/tanma/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const SKILL='C:/Users/tanma/.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations';
const OUT='C:/Users/tanma/Desktop/ai-companion/docs/hackathon-presentation/redesign';
await fs.mkdir(path.join(OUT,'output'),{recursive:true});
const {finalizePresentation}=await import('file:///'+SKILL+'/container_tools/artifact_tool_utils.mjs');
const result=await finalizePresentation({workspaceDir:OUT,candidatePath:path.join(OUT,'.build/nova-design-candidate.pptx'),finalPath:path.join(OUT,'output/nova-hackathon-design-edition.pptx'),pythonExecutable:'C:/Users/tanma/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-heading-fit'],explicitTotalSlideCount:12,fontPolicy:{basis:'design',families:['Arial']},verifyArtifactToolImport:true,receiptPath:path.join(OUT,'.build/validation.json')});
console.log(JSON.stringify(result));
