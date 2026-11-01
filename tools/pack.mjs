// Local experimental GR III 2.10 firmware candidate. No card discovery/writes.
import {registerHooks} from 'node:module';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {resolve, join} from 'node:path';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){
  if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))for(const suffix of ['.ts','/index.ts']){try{return next(s+suffix,c);}catch{}}
  throw e;
}}});
const {Firmware,sectionsOf,verifyContainer,buildGrown,sum32,sha256Hex,FRAME_SIZE}=await import('../vendor/grmod/container.ts');
const [input,runtimeDir,outputDir]=process.argv.slice(2);
if(!input||!runtimeDir||!outputDir)throw Error('Usage: node --experimental-transform-types tools/pack.mjs OFFICIAL.bin RUNTIME_DIR NEW_OUTPUT_DIR');
const output=resolve(outputDir),source=resolve(input),runtime=resolve(runtimeDir);
if(source===join(output,'candidate.bin'))throw Error('Output would overwrite input');
const raw=new Uint8Array(await readFile(source));
const inputSha=await sha256Hex(raw);
if(inputSha!=='d6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4')throw Error('Only exact official GR III 2.10 is supported');
const module=new Uint8Array(await readFile(join(runtime,'camera.bin')));
const manifest=JSON.parse(await readFile(join(runtime,'camera.json'),'utf8'));
const verification=JSON.parse(await readFile(join(runtime,'verification.json'),'utf8'));
if(manifest.runtimeSha256!==verification.imageSha256||manifest.wadSha256!==verification.wadSha256||
  verification.actualArmEngineExecuted!==true||verification.realMapEntered!==true||verification.playerMoved!==true)throw Error('Matching successful ARM runtime verification is required');
if(await sha256Hex(module)!==manifest.sha256||module.length!==manifest.bytes)throw Error('Camera module hash/length mismatch');
for(const asset of Object.values(manifest.assets)){
  const start=asset.address-manifest.address;
  if(start<0||start+asset.bytes>module.length||await sha256Hex(module.subarray(start,start+asset.bytes))!==asset.sha256)throw Error('Embedded asset hash mismatch');
}
if(manifest.assets.doom_image.sha256!==manifest.runtimeSha256||manifest.assets.doom_wad.sha256!==manifest.wadSha256)throw Error('Embedded runtime/WAD does not match verified inputs');
const fw=new Firmware(raw),sections=sectionsOf(fw.decoded),rtos=sections.find(s=>s.name==='RTOS'),BASE=0x53000000;
if(rtos.size!==17520064||manifest.address<BASE+rtos.size||manifest.address%4096)throw Error('Unexpected RTOS/module layout');
const growth=Math.ceil((manifest.address+module.length+256-BASE-rtos.size)/FRAME_SIZE)*FRAME_SIZE;
if(BASE+rtos.size+growth>0x55000000)throw Error('RTOS would overlap native data');
const insertion=rtos.offset+rtos.size,decoded=new Uint8Array(fw.decoded.length+growth);
decoded.set(fw.decoded.subarray(0,insertion));decoded.set(module,rtos.offset+manifest.address-BASE);
decoded.set(fw.decoded.subarray(insertion),insertion+growth);
const view=new DataView(decoded.buffer),old=new DataView(fw.decoded.buffer),allowed=new Set();
for(const p of manifest.patches){
  const off=rtos.offset+p.address-BASE;
  if(old.getUint32(off,true)!==(p.expected>>>0))throw Error('Native instruction guard failed at '+p.address.toString(16));
  view.setUint32(off,p.replacement>>>0,true);
  for(let i=0;i<4;i++)allowed.add(off+i);
}
view.setUint32(rtos.offset-4,rtos.size+growth,true);
for(let i=0;i<4;i++)allowed.add(rtos.offset-4+i);
const marker=new TextEncoder().encode('GRMOD-DOOM-GR3-210-EXPERIMENTAL-HARDWARE-UNTESTED\0');
const checksum=insertion+growth-4;decoded.set(marker,checksum-marker.length);
view.setUint32(checksum,0,true);view.setUint32(checksum,(-sum32(decoded))>>>0,true);
for(let i=0;i<insertion;i++)if(!allowed.has(i)&&decoded[i]!==fw.decoded[i])throw Error('Undeclared byte changed');
for(let i=insertion;i<fw.decoded.length;i++)if(decoded[i+growth]!==fw.decoded[i])throw Error('Later section changed');
const built=buildGrown(fw,decoded,[{at:insertion,length:growth}]);
const checks=verifyContainer(built.out,decoded).checks;
if(Object.values(checks).some(v=>v!==true))throw Error('Container verification failed');
const next=sectionsOf(decoded);
if(next.length!==sections.length)throw Error('Section count changed');
for(let i=0;i<sections.length;i++){
  const a=sections[i],b=next[i];
  if(a.name!==b.name)throw Error('Section order changed');
  if(a.name!=='RTOS'&&(a.size!==b.size||await sha256Hex(fw.decoded.subarray(a.offset,a.offset+a.size))!==await sha256Hex(decoded.subarray(b.offset,b.offset+b.size))))throw Error('Non-RTOS section changed');
}
if(Buffer.compare(raw.subarray(0,0x80),built.out.subarray(0,0x80))!==0)throw Error('Firmware identity/version header changed');
// A fresh directory is required: never replace a previous candidate or evidence.
await mkdir(output);
await writeFile(join(output,'candidate.bin'),built.out);
await writeFile(join(output,'rtos.bin'),decoded.subarray(rtos.offset,rtos.offset+rtos.size+growth));
await writeFile(join(output,'base-rtos.bin'),fw.decoded.subarray(rtos.offset,rtos.offset+rtos.size));
const boot=sections.find(s=>s.name==='BOOT');
await writeFile(join(output,'boot.bin'),fw.decoded.subarray(boot.offset,boot.offset+boot.size));
const report={schema:1,camera:'GR III',version:'2.10',inputSha256:inputSha,outputSha256:await sha256Hex(built.out),
  outputBytes:built.out.length,rtosOffset:rtos.offset,rtosBytes:rtos.size+growth,rtosSize:rtos.size+growth,rtosGrowth:growth,
  module:manifest,containerChecks:checks,unchangedSections:sections.filter(s=>s.name!=='RTOS').map(s=>s.name),
  hardwareTested:false,cardWritten:false,experimental:true,
  limitations:['Executable heap and privileged cache maintenance are unverified on camera','Timer cadence/task context and allocation headroom require hardware testing','Standalone official-firmware base; does not preserve other mods','Silent: no audio or save-file writes']};
await writeFile(join(output,'candidate.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({candidate:join(output,'candidate.bin'),outputSha256:report.outputSha256,outputBytes:report.outputBytes,rtosBytes:report.rtosBytes,hardwareTested:false},null,2));
