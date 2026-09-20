'use strict';
let state, pending, activeTab = 'operations', lastQuestion = '', benchmarkTimer;
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = value => escape(JSON.stringify(value, null, 2));
const human = value => String(value).replaceAll('_', ' ');
const time = value => new Date(value).toLocaleString('en-GB', {timeZone:'UTC',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});
function notice(message, error=false) { $('notice').hidden=false; $('notice').textContent=message; $('notice').className=error?'error':''; }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':state.token},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed.');
  return result;
}
async function busy(button, work) {
  const old = button.textContent; button.disabled=true; button.textContent='Working…';
  try { await work(); } catch (error) { notice(error.message,true); }
  finally { button.disabled=false; button.textContent=old; }
}
function tab(name) {
  activeTab=name;
  document.querySelectorAll('.page').forEach(page=>page.hidden=page.id!==name);
  document.querySelectorAll('[data-tab]').forEach(button=>{button.classList.toggle('active',button.dataset.tab===name);if(button.dataset.tab===name)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  $('breadcrumb').textContent=({operations:'Operations',data:'Crew data',learning:'Learning',performance:'Performance'})[name];
}
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>tab(button.dataset.tab)));
function table(headers, rows) {return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th scope="col">${escape(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function empty(title, body) { return `<div class="empty"><div class="empty-icon">↗</div><h3>${escape(title)}</h3><p>${escape(body)}</p></div>`; }
function stats(items) { return items.map(([label,value,tag])=>`<div class="stat"><div class="label">${escape(label)}</div><div class="value">${escape(value)}</div><div class="tag">${escape(tag)}</div></div>`).join(''); }
async function refresh() {
  state=await api('/api/state');
  $('model-state').textContent=state.model?`Model: ${state.model_name}`:'Local tools · model not configured';
  $('load-demo').hidden=Object.keys(state.tables).length>0;
  $('stats').innerHTML=stats([['Crew members',state.tables.crew?.count||0,'In this workspace'],['Duty blocks',state.tables.duties?.count||0,'Imported schedule'],['Open positions',state.roster.open,'Ready for a coverage check'],['Need review',state.roster.needs_review,'Against configured policy']]);
  renderRoster(); renderTables(); renderHistory(); renderBenchmark();
  // Do not overwrite policy edits while a background benchmark is polling.
  if (activeTab!=='learning' || !$('policy-label').value) {
    $('policy-label').value=state.policy.label;$('rest').value=state.policy.min_rest_hours;$('duty-limit').value=state.policy.max_duty_hours;$('week-limit').value=state.policy.max_7day_hours;
  }
}
function renderRoster() {
  if (!state.roster.slots.length) {$('roster').innerHTML=empty('Your roster starts here.','Explore the example, or import crew members and duty blocks in Crew data.'); return;}
  const rows=state.roster.slots.slice(0,100).map((slot,index)=>[
    `<b class="mono">${escape(slot.duty_id)}</b><small>${escape(slot.start_base)} → ${escape(slot.end_base)}</small>`,
    `${escape(time(slot.report_at))}<small>${escape(human(slot.role))}</small>`,
    `${slot.name?escape(slot.name):'<span class="muted">Unassigned</span>'}<small><span class="pill ${slot.state==='assigned'?'good':slot.state==='needs_review'?'bad':'warn'}">${escape(human(slot.state))}</span></small>${slot.reasons.length?`<details><summary>Checks</summary>${slot.reasons.map(r=>`<p>${escape(r)}</p>`).join('')}</details>`:''}`,
    slot.crew_id?`<button class="button small secondary danger" data-release="${index}">Release</button>`:`<button class="button small secondary" data-cover="${index}">Find cover</button>`]);
  $('roster').innerHTML=table(['Duty / route','Report / position','Crew / status','Action'],rows)+
    (state.roster.slots.length>100?'<p class="footnote">Showing the first 100 positions.</p>':'')+
    state.roster.issues.map(issue=>`<div class="callout">${escape(issue)}</div>`).join('');
  $('roster').querySelectorAll('[data-cover]').forEach(button=>button.onclick=()=>busy(button,async()=>{const slot=state.roster.slots[Number(button.dataset.cover)];await runPlan({action:'coverage',duty_id:slot.duty_id,role:slot.role});}));
  $('roster').querySelectorAll('[data-release]').forEach(button=>button.onclick=()=>busy(button,async()=>{const slot=state.roster.slots[Number(button.dataset.release)];await api('/api/unassign',{duty_id:slot.duty_id,role:slot.role,revision:state.revision});await refresh();$('answer').innerHTML=empty('Position released.','Run a fresh coverage check before assigning a replacement.');notice('Position released. The action is recorded in workspace history.');}));
}
function renderTables() {
  $('tables').innerHTML=Object.entries(state.tables).length?Object.entries(state.tables).map(([kind,data])=>`<div class="table-card"><div><strong>${escape(human(kind))}</strong><p>${escape(data.source)}</p></div><span class="pill">${data.count} records</span></div>`).join(''):'<p class="muted">No tables imported yet.</p>';
}
async function runPlan(plan) { renderAnswer(await api('/api/query',{plan})); }
function renderAnswer(answer) {
  if(answer.action==='clarify'){$('answer').innerHTML=`<p>${escape(answer.reply)}</p>`;return;}
  let html=`<p class="answer-lead">${escape(answer.reply)}</p>`;
  if(answer.metrics)html+=`<div class="answer-meta">${answer.metrics.engine_ms} ms engine · ${escape(answer.metrics.strategy)} · ${answer.metrics.cache_hit?'cached result':'fresh result'}${answer.route_source?`<br>${escape(answer.route_source)}`:''}</div>`;
  if(answer.action==='coverage') {
    html+=`<p class="footnote">${escape(answer.result.policy.label)}. Ranked by lowest peak duty hours, then name.</p>`;
    html+=answer.result.candidates.map((c,index)=>`<div class="candidate"><div class="candidate-top"><h3>${escape(c.name)}</h3><span class="pill ${c.passes?'good':'warn'}">${c.passes?'Passes checks':'Excluded'}</span></div><p>${escape(c.crew_id)} · ${escape(c.base)} · ${c.peak_7day_hours}h peak / seven days</p>${c.reasons.length?`<ul>${c.reasons.map(r=>`<li>${escape(r)}</li>`).join('')}</ul>`:''}<details><summary>Source records</summary><ul>${c.sources.map(s=>`<li>${escape(s.file)}${s.record?` · record ${s.record}`:''}</li>`).join('')}</ul></details>${c.passes?`<button class="button small" data-assign="${index}">Assign to this position</button>`:''}</div>`).join('');
    if(answer.result.truncated)html+=`<p class="footnote">Showing the first 100 of ${answer.result.candidate_count} evaluated crew members.</p>`;
    html+=`<p class="footnote">${escape(answer.result.limits)}</p>`;
  } else if(answer.action==='summary') {
    html+=`<p class="muted">${answer.result.assignments} assignments · ${answer.result.roster.open} open positions · ${answer.result.roster.needs_review} need review.</p>`;
  } else html+='<p class="muted">The duty roster shows each position and its current checks.</p>';
  if(lastQuestion)html+='<button id="correct-workflow" class="text-button">Correct what I meant</button>';
  $('answer').innerHTML=html;
  $('answer').querySelectorAll('[data-assign]').forEach(button=>button.onclick=()=>busy(button,async()=>{
    const candidate=answer.result.candidates[Number(button.dataset.assign)];
    await api('/api/assign',{crew_id:candidate.crew_id,duty_id:answer.plan.duty_id,role:answer.plan.role,revision:answer.revision});
    await refresh();$('answer').innerHTML=`<p class="answer-lead">${escape(candidate.name)} is assigned to ${escape(answer.plan.duty_id)}.</p><p class="muted">The roster and checks have been refreshed.</p>`;notice('Assignment saved after rechecking the current roster.');
  }));
  if($('correct-workflow'))$('correct-workflow').onclick=()=>{$('teach-question').value=lastQuestion;tab('learning');$('teach-question').focus();};
}
$('ask-form').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{lastQuestion=$('question').value;renderAnswer(await api('/api/ask',{question:lastQuestion}));});};
$('quick-summary').onclick=event=>busy(event.currentTarget,()=>runPlan({action:'summary'}));
$('quick-roster').onclick=event=>busy(event.currentTarget,()=>runPlan({action:'roster'}));
$('refresh').onclick=event=>busy(event.currentTarget,refresh);
$('load-demo').onclick=event=>busy(event.currentTarget,async()=>{await api('/api/demo',{});await refresh();notice('Example crew and duties loaded. The example policy is for exploration only.');});
$('upload-form').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{const file=$('file').files[0];if(!file)throw new Error('Choose a data file.');if(file.size>6*1024*1024)throw new Error('Use a file smaller than 6 MB.');pending=await api('/api/import/preview',{kind:$('kind').value,filename:file.name,content:await file.text()});renderMapping();});};
function renderMapping() {
  $('import-review').hidden=false;$('import-summary').textContent=`${pending.source} · ${pending.count} records · replaces the ${pending.kind} table`;
  $('mapping-issue').textContent=pending.issue||'The proposed mapping passes structural checks. Review the meaning of each field before accepting.';
  if(pending.uncertainties?.length)$('mapping-issue').textContent+=' '+pending.uncertainties.join(' ');
  $('mapping').innerHTML=pending.headers.map((header,index)=>`<div class="mapping-row"><label for="map-${index}">${escape(header)}</label><span>→</span><select id="map-${index}" data-header="${escape(header)}"><option value="">Keep in original only</option>${pending.fields.map(field=>`<option value="${field}" ${pending.mapping[header]===field?'selected':''}>${escape(human(field))}</option>`).join('')}</select></div>`).join('');
  $('import-sample').innerHTML=table(pending.headers,pending.sample.map(row=>pending.headers.map(header=>escape(typeof row[header]==='object'?JSON.stringify(row[header]):row[header]))));
  $('accept-import').textContent=`Accept mapping and replace ${pending.kind}`;
}
$('analyze').onclick=event=>busy(event.currentTarget,async()=>{pending=await api('/api/import/analyze',{id:pending.id});renderMapping();});
$('accept-import').onclick=event=>busy(event.currentTarget,async()=>{const mapping={};$('mapping').querySelectorAll('select').forEach(select=>{if(select.value)mapping[select.dataset.header]=select.value;});const result=await api('/api/import/accept',{id:pending.id,mapping,revision:state.revision});pending=null;$('import-review').hidden=true;await refresh();notice(`Table imported. Mapping learning: ${result.learning.status}. Review the roster for data issues.`);});
$('teach-form').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{const result=await api('/api/teach',{question:$('teach-question').value,action:$('teach-action').value});await refresh();notice(result.status==='rejected'?'Correction conflicts with saved examples. It was recorded but not activated.':`Workflow ${result.status}. ${result.report.after_passed}/${result.report.cases} saved examples pass.`,result.status==='rejected');});};
$('policy-form').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{await api('/api/policy/propose',{policy:{label:$('policy-label').value,min_rest_hours:Number($('rest').value),max_duty_hours:Number($('duty-limit').value),max_7day_hours:Number($('week-limit').value)},reason:$('policy-reason').value});await refresh();notice('Policy compared. Review the results in change history before activating.');});};
$('policy-ai-form').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{const result=await api('/api/policy/suggest',{request:$('policy-request').value});await refresh();notice(result.question||'Model proposal compared. Review it in change history; the active policy has not changed.');});};
function renderHistory() {
  const latest=state.learning.find(change=>change.status==='active'&&change.kind!=='policy');
  $('history').innerHTML=state.learning.length?state.learning.map(change=>`<article class="history-card"><div class="history-title"><div><span class="eyebrow">${escape(change.kind)} · ${escape(change.created)}</span><h3>${escape(change.reason)}</h3></div><span class="pill ${change.status==='active'?'good':change.status==='rejected'?'bad':'warn'}">${escape(human(change.status))}</span></div>${change.kind==='policy'?`<p>${change.report.checks} candidate checks · ${change.report.changes.length} outcomes change · ${change.report.new_assignment_failures} assigned positions newly fail.</p><span class="policy-values">Rest ${change.before_state.min_rest_hours}h → ${change.after_state.min_rest_hours}h · duty ${change.before_state.max_duty_hours}h → ${change.after_state.max_duty_hours}h · seven-day ${change.before_state.max_7day_hours}h → ${change.after_state.max_7day_hours}h</span>${change.status==='proposed'?`<button class="button small secondary" data-activate="${change.id}" ${change.report.revision!==state.revision?'disabled':''}>${change.report.revision!==state.revision?'Workspace changed; compare a new proposal':'Activate reviewed policy'}</button>`:''}`:`<p>Replay: ${change.report.before_passed} → ${change.report.after_passed} of ${change.report.cases} examples passing. ${change.report.regressions.length} regressions.</p>${latest?.id===change.id?`<button class="button small secondary" data-rollback="${change.id}">Roll back learning</button>`:''}`}<details><summary>Inspect evidence and changes</summary><pre>${pretty({before:change.before_state,after:change.after_state,report:change.report})}</pre></details></article>`).join(''):'<div class="empty compact"><h3>No learning hidden behind the scenes.</h3><p>Review an import or teach a workflow. Its checks and activation decision will appear here.</p></div>';
  $('history').querySelectorAll('[data-rollback]').forEach(button=>button.onclick=()=>busy(button,async()=>{await api('/api/learning/rollback',{id:Number(button.dataset.rollback)});await refresh();notice('Learning rolled back. Imported records and operating policies are unchanged.');}));
  $('history').querySelectorAll('[data-activate]').forEach(button=>button.onclick=()=>busy(button,async()=>{await api('/api/policy/activate',{id:Number(button.dataset.activate)});await refresh();notice('Reviewed policy activated. The roster has been checked again.');}));
}
function renderBenchmark() {
  $('benchmark-status').textContent=`Active algorithm: ${state.strategy}. ${state.optimization.message}`;
  $('run-benchmark').disabled=state.optimization.running;
  const report=state.benchmark;
  if(!report)$('benchmark-results').innerHTML=empty('No performance claims without a measurement.','Run the benchmark to compare exact results, latency, and memory on growing synthetic workloads.');
  else $('benchmark-results').innerHTML=`<div class="stats">${stats([['Correctness gate',report.correctness_gate?'Passed':'Failed','Exact results + held-out cases'],['Measured speedup',`${report.speedup}×`,'Geometric-mean p95'],['Selected strategy',report.selected,'After correctness checks'],['Held-out workloads',`${report.holdout.filter(x=>x.equal).length}/${report.holdout.length}`,'Independent seeds and sizes']])}</div><section class="panel"><div class="panel-title"><h2>Measured results</h2></div>${table(['Crew','Algorithm','Correct','p50 ms','p95 ms','Queries / s','Peak MB'],report.results.map(row=>[row.size,escape(row.strategy),`${row.correctness_score}%`,row.p50_ms,row.p95_ms,row.queries_per_second,row.peak_mb]))}<div class="padded"><p class="footnote">${escape(report.method)}</p><details><summary>Growth scores and selection rule</summary><pre>${pretty({scores:report.scores,selection:report.selection_rule,machine:report.machine})}</pre></details></div></section>`;
  clearTimeout(benchmarkTimer);
  if(state.optimization.running)benchmarkTimer=setTimeout(()=>refresh().catch(error=>notice(error.message,true)),2000);
}
$('run-benchmark').onclick=event=>busy(event.currentTarget,async()=>{await api('/api/optimize',{});await refresh();notice('Benchmark started. For comparable timings, avoid other heavy work until it finishes.');}).then(()=>{$('run-benchmark').disabled=state.optimization.running;});
refresh().catch(error=>notice(error.message,true));
