import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, PresentationFile } from 'file:///C:/Users/tanma/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const base = 'C:/Users/tanma/Desktop/ai-companion/docs/hackathon-presentation';
const presentation = await PresentationFile.importPptx(await FileBlob.load(path.join(base,'nova-hackathon-presentation.pptx')));
await fs.mkdir(path.join(base,'slide-previews'),{recursive:true});
for (const [i,slide] of presentation.slides.items.entries()) {
  const png = await presentation.export({slide,format:'png',scale:1.5});
  await fs.writeFile(path.join(base,'slide-previews',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
  console.log(`Rendered slide ${i+1}`);
}
