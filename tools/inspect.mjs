// Decode a candidate afresh and bind the executable RTOS sidecar to its bytes.
import {registerHooks} from 'node:module';
import {readFile} from 'node:fs/promises';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){
  if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))for(const suffix of ['.ts','/index.ts']){try{return next(s+suffix,c);}catch{}}
  throw e;
}}});
const {sectionsOf,verifyContainer,sha256Hex}=await import('../vendor/grmod/container.ts');
const [candidate,sidecar]=process.argv.slice(2);
if(!candidate||!sidecar)throw Error('Usage: inspect.mjs CANDIDATE.bin RTOS_SIDECAR.bin');
const raw=new Uint8Array(await readFile(candidate));
const {decoded,checks}=verifyContainer(raw);
if(Object.values(checks).some(v=>v!==true))throw Error('Invalid firmware container');
const rtos=sectionsOf(decoded).find(s=>s.name==='RTOS');
if(!rtos)throw Error('Missing RTOS section');
const actual=decoded.subarray(rtos.offset,rtos.offset+rtos.size),claimed=await readFile(sidecar);
if(Buffer.compare(actual,claimed)!==0)throw Error('RTOS sidecar does not match the decoded candidate');
console.log(JSON.stringify({candidateSha256:await sha256Hex(raw),rtosSha256:await sha256Hex(actual),rtosBytes:actual.length,checks}));
