'use strict';
// Keep first-use preparation and model requests separate from manuscript state.
let prepTimer, activeJob = null, searchController = null, testedConfig = '', detection = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const baseApi = api;
api = async function(path, body, method) {
  try { return await baseApi(path, body, method); }
  catch(e) {
    if(e instanceof TypeError) throw Error('The local app is unavailable. Run the launcher again, then retry. Your input is kept in this page.');
    throw e;
  }
};

function renderPreparation(p) {
  state.preparation = p;
  $('preparebox').classList.toggle('hidden', p.state === 'ready');
  $('prepare').classList.toggle('hidden', p.state !== 'error');
  const progress = p.unit === 'bytes'
    ? `${(p.files_done/1e6).toFixed(0)} of ${p.files_total ? (p.files_total/1e6).toFixed(0) : '…'} MB downloaded`
    : `${p.files_done} of ${p.files_total || '…'} files ready`;
  $('preparestatus').textContent = p.state === 'preparing'
    ? `Preparing · ${progress} · ${p.seconds}s elapsed`
    : p.state === 'error' ? p.message : '';
  $('preparestatus').classList.toggle('busy', p.state === 'preparing');
  if(p.state === 'ready') { clearInterval(prepTimer); prepTimer = null; }
}
async function checkPreparation() {
  const p = await api('/v1/preparation'); renderPreparation(p); return p.state === 'ready';
}
function watchPreparation() {
  clearInterval(prepTimer);
  prepTimer = setInterval(() => checkPreparation().catch(e => {$('preparestatus').textContent=e.message;}), 1500);
}
$('prepare').onclick = async () => {
  try { renderPreparation(await api('/v1/preparation', {})); watchPreparation(); }
  catch(e) { $('preparestatus').textContent=e.message; $('prepare').classList.remove('hidden'); }
};
async function requirePreparation() {
  if(await checkPreparation()) return true;
  error(state.preparation?.state === 'error'
    ? 'Local search is not prepared. Choose Retry preparation above, then search again. Your input is kept.'
    : 'Local search is still being prepared. Choose Find similar articles again when it finishes. Your input is kept.');
  $('preparebox').scrollIntoView({block:'center'});
  return false;
}

function cancelButtons(on) {
  for(const id of ['cancelwork','cancelmodel']) { $(id).classList.toggle('hidden',!on); $(id).disabled=!on; }
}
function modelLock(on) {
  lock(on);
  document.querySelectorAll('#modeldialog input,#modeldialog select,#modeldialog button').forEach(x=>x.disabled=on);
  if(on) cancelButtons(!!activeJob);
}
async function modelJob(kind, model, extra={}) {
  const {job_id} = await api('/v1/jobs', {kind,model,...extra});
  activeJob = job_id; cancelButtons(true);
  try {
    for(;;) {
      if(activeJob !== job_id) throw Error('Request cancelled. Your input is kept. Work already processed by the provider may count toward your allowance.');
      let out;
      try { out = await api('/v1/jobs/'+job_id); }
      catch(e) { if(activeJob !== job_id) continue; throw e; }
      if(activeJob !== job_id) continue;
      if(out.state === 'done') return out.result;
      if(out.state === 'error') throw Error(out.error);
      if(out.state !== 'running') throw Error('Request cancelled. Your input is kept.');
      const msg = `${kind==='outline'?'Identifying sections':'Waiting for your model'} · ${out.seconds}s elapsed. You can cancel.`;
      if(kind==='outline') status(msg,true); else $('model-state').textContent=msg;
      await sleep(500);
    }
  } finally {
    if(activeJob === job_id) activeJob = null;
    cancelButtons(false);
    await api('/v1/jobs/'+job_id,null,'DELETE').catch(()=>{});
  }
}
async function cancelRequest() {
  if(searchController) { searchController.abort(); return; }
  const token=activeJob;
  if(!token) return;
  $('cancelmodel').disabled=$('cancelwork').disabled=true;
  activeJob=null;
  try { await api('/v1/jobs/'+token,null,'DELETE'); }
  catch(e) { $('model-state').textContent=e.message; status(e.message); }
}
$('cancelmodel').onclick=$('cancelwork').onclick=cancelRequest;
$('modeldialog').addEventListener('cancel', e => { if(state.busy) {e.preventDefault();$('model-state').textContent='Choose Cancel request to stop this request first.';} });

const oldProviderChanged=providerChanged;
providerChanged=function() {
  oldProviderChanged();
  const p=$('provider').value, k=providers[p][1];
  $('cli-guide').classList.toggle('hidden',k!=='cli');
  $('api-guide').classList.toggle('hidden',k==='cli');
  $('modelchoices').textContent=''; $('modelsnote').textContent='';
  const direct = p==='custom'||k==='local';
  (direct?$('customaddress'):$('advancedfields')).append($('basefield'));
  $('basefield').classList.toggle('hidden', k==='cli');
  $('modelname').placeholder=k==='cli'?'Use the agent default':'Load the list or enter the exact model ID';
  if(k==='cli') {
    $('agent-install').href=p==='codex-cli'?'https://learn.chatgpt.com/docs/cli':'https://code.claude.com/docs/en/setup';
    $('agent-login').textContent=p==='codex-cli'?'codex login':'claude → /login';
  }
};
showCli=function() {
  const p=$('provider').value;
  if(providers[p][1]!=='cli')return;
  const c=state.clis?.[p];
  $('cli-status').textContent=!state.clis?'Checking installation and login…':!c?.found?'Installation not found. Follow the steps below.':
    !c.compatible?'An update is needed. Follow the installation instructions, then recheck.':
    c.signed_in===false?'Installed · Sign in using the steps below.':c.signed_in===true?'Installed and signed in · Test connection to check access.':
    'Installed · Login could not be confirmed. Sign in and test the connection.';
};
async function recheck() {
  const id=++detection; $('recheck').disabled=true; $('cli-status').textContent='Checking installation and login…';
  try {const out=await api('/v1/model/clis'); if(id===detection){state.clis=out.clis;showCli();}}
  catch(e){$('cli-status').textContent=e.message;}
  finally {if(!state.busy)$('recheck').disabled=false;}
}
$('recheck').onclick=recheck;
openModel=async function() {
  if(state.busy)return;
  const cfg=state.model;
  document.querySelector(`input[name=kind][value="${cfg?providers[cfg.provider][1]:'cli'}"]`).checked=true;
  fillProviders(cfg?.provider);
  if(cfg){$('modelname').value=cfg.model||'';$('baseurl').value=cfg.base_url||providers[cfg.provider][2];$('modelkey').value=cfg.api_key||'';$('effort').value=cfg.effort||'low';}
  $('modeldialog').showModal();
  if(kind()==='cli')await recheck();
};
$('settings').onclick=$('configure').onclick=openModel;
$('provider').onchange=()=>providerChanged();
document.querySelectorAll('input[name=kind]').forEach(x=>x.onchange=()=>{fillProviders();if(kind()==='cli')recheck();});

$('loadmodels').onclick=async()=>{
  let cfg;
  try {
    // Listing requires an endpoint/key, but no prior knowledge of a model identifier.
    const value=$('modelname').value;
    try {if(!value)$('modelname').value='_list_';cfg=config();} finally {$('modelname').value=value;}
    modelLock(true);$('model-state').textContent='Loading model names…';
    const out=await modelJob('models',cfg);
    $('modelchoices').textContent='';
    for(const name of out.models)$('modelchoices').append(el('option',{value:name}));
    $('modelsnote').textContent=`${out.models.length} models available. Choose a chat-capable model in the Model field.`;
    $('model-state').textContent='Model list loaded. This did not generate text.';
  }catch(e){$('model-state').textContent=e.message;}finally{modelLock(false);}
};
$('testmodel').onclick=async()=>{
  let cfg;
  try{cfg=config();}catch(e){$('model-state').textContent=e.message;return;}
  modelLock(true);$('model-state').textContent='Testing connection…';
  try{
    const out=await modelJob('test',cfg);
    testedConfig=JSON.stringify(cfg);state.model=cfg;state.modelTested=true;updateModelSummary();
    $('model-state').textContent=`Connection verified in ${out.seconds}s. Choose Use these settings, then Identify sections. Manuscript structure will be checked during identification.`;
  }catch(e){testedConfig='';state.modelTested=false;$('model-state').textContent=e.message;updateModelSummary();}
  finally{modelLock(false);}
};
$('savemodel').onclick=()=>{try{const cfg=config();saveConfig(cfg,JSON.stringify(cfg)===testedConfig);$('modeldialog').close();}catch(e){$('model-state').textContent=e.message;}};

identify=async function(){
  if(state.busy||!state.doc)return;
  if(!state.model||(providers[state.model.provider][1]==='api'&&!state.model.api_key)){await openModel();return;}
  lock(true);error();status('Your model is identifying sections…',true);
  try{
    const out=await modelJob('outline',state.model,{document_id:state.doc.document_id});
    state.outline=out;state.map=out.headings.map(h=>state.info.sections.includes(h.section)?h.section:'');
    state.modelTested=true;updateModelSummary();renderOutline();
    $('filemeta').textContent=`${fmt(state.doc.words)} words · ${fmt(state.doc.paragraphs)} paragraphs · Sections identified`;
    dirty();status('Sections ready. Review them before searching.');
  }catch(e){error(e.message);status('Your manuscript and previous section choices are kept. Retry when ready.');}
  finally{lock(false);}
};
$('identify').onclick=$('reidentify').onclick=identify;

search=async function(){
  if(state.busy)return;
  let body;
  try{body=request();if(state.mode!=='doi'&&!await requirePreparation())return;}catch(e){error(e.message);return;}
  lock(true);error();$('notfound').classList.add('hidden');status('Searching your local collection…',true);
  searchController=new AbortController();cancelButtons(true);
  const started=Date.now(), ticker=setInterval(()=>status(`Searching your local collection · ${Math.floor((Date.now()-started)/1000)}s elapsed. Longer manuscripts and first searches can take a few minutes.`,true),1000);
  try{
    const r=await fetch('/v1/similar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:searchController.signal});
    const out=await r.json();
    if(!r.ok){if(out.action==='prepare')await checkPreparation();if(out.action==='paste')$('notfound').classList.remove('hidden');throw Error(out.error);}
    state.last=out;state.dirty=false;$('stale').classList.add('hidden');renderResults();status('Search complete.');
    if(state.mode==='file'){$('step2').classList.remove('active');$('step3').classList.add('active');}
    $('results').scrollIntoView({behavior:'instant',block:'start'});
  }catch(e){
    if(e.name==='AbortError')status('Stopped waiting. Local processing may finish in the background; your input is kept.');
    else{error(e instanceof TypeError?'The local app is unavailable. Run the launcher again, then retry.':e.message);status('Search failed. Your input is kept.');}
  }finally{clearInterval(ticker);searchController=null;cancelButtons(false);lock(false);}
};
$('search').onclick=search;
$('topaste').onclick=()=>{$('notfound').classList.add('hidden');switchMode('text');$('ptext').focus();};
$('rankby').onchange=()=>{state.rankby=$('rankby').value;dirty();search();};
window.addEventListener('pagehide',()=>{if(activeJob)fetch('/v1/jobs/'+activeJob,{method:'DELETE',keepalive:true}).catch(()=>{});});
const originalInit=init;
init=async()=>{await originalInit();const p=state.info?.preparation;if(p){renderPreparation(p);if(p.state==='needed')$('prepare').onclick();else if(p.state==='preparing')watchPreparation();}};
init();
