const $ = id => document.getElementById(id);
const roles = ["Sentinel", "Investigator", "Impact", "Recovery", "Commander"];
const descriptions = ["Detect & prioritize", "Retrieve evidence", "Calculate exposure", "Optimize recovery", "Prepare decision"];
let incident = null;
let stream = null;
let refreshTimer;
let scenarios = [];

function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function message(text) { $("message").textContent = text; $("message").hidden = !text; }
async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...options.headers};
  if (options.auth) headers.Authorization = `Bearer ${$("token").value}`;
  const response = await fetch(path, {...options, headers});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) { $("access").open = true; $("token").focus(); }
    throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  }
  return data;
}
function currency(paise) { return new Intl.NumberFormat("en-IN", {style:"currency", currency:"INR", maximumFractionDigits:0}).format(paise / 100); }
function renderInterpretation() {
  const investigation = incident.results.Investigator;
  const interpretation = investigation?.interpretation;
  const target = $("interpretation"); target.replaceChildren();
  $("interpretation-status").textContent = investigation?.blocking_issues?.length ? "Needs review" : interpretation ? "Reconciled" : "ERP assumptions";
  if (investigation?.blocking_issues?.length) {
    const list=node("ul",undefined,"issues");
    investigation.blocking_issues.forEach(issue=>list.append(node("li",issue)));
    target.append(list);
  }
  if (interpretation) {
    const usage=interpretation.usage;
    target.append(node("p",`${usage.provider === "gemini" ? `Gemini · ${usage.model}` : "Strict rules baseline · no LLM call"} · ${usage.latency_ms} ms`,"muted"));
    interpretation.facts.forEach(fact=>{
      const box=node("div",undefined,"fact");
      box.append(node("strong",`${fact.option_id} · ${fact.field === "arrival_date" ? "Arrival" : "Available quantity"}: ${fact.value}${fact.field === "capacity_units" ? " units" : ""}`), node("blockquote",fact.quote),node("small",`${fact.source_label} · ${fact.source_id}`,"muted"));
      target.append(box);
    });
    if (interpretation.changes.length) {
      const list=node("ul",undefined,"changes");
      interpretation.changes.forEach(change=>list.append(node("li",`${change.option_id}: ${change.field === "arrival_day" ? "arrival day" : "capacity"} ${change.before} → ${change.after} · ${change.source_ids.join(", ")}`)));
      target.append(list);
    } else if (!investigation.blocking_issues.length) target.append(node("p","The cited facts agree with the current planning inputs.","muted"));
    if (usage.provider === "gemini") target.append(node("p",`Extraction tokens: ${usage.input_tokens ?? "unknown"} input, ${usage.output_tokens ?? "unknown"} output, ${usage.thought_tokens ?? "unknown"} thinking. Estimated extraction cost: ${usage.estimated_cost_usd == null ? "not calculated; model prices not configured" : `$${usage.estimated_cost_usd.toFixed(6)} USD`}. ADK orchestration costs are separate.`,"muted"));
    target.append(node("p","Citations are checked against source text. They do not authenticate the sender or independently prove the message is true. Review the evidence before approval.","muted"));
  } else target.append(node("p",investigation?.findings || "The Investigator will review the policy documents and shipment messages.","muted"));
  const sources=incident.input_snapshot?.updates || incident.snapshot.updates || [];
  if (sources.length) {
    const details=node("details",undefined,"source-messages");details.append(node("summary",`Read ${sources.length} original message${sources.length===1 ? "" : "s"}`));
    sources.forEach(source=>{const block=node("div",undefined,"fact");block.append(node("strong",`${source.id} · ${source.source_label}`),node("p",source.text,"source-text"));if(source.supersedes.length)block.append(node("small",`Explicitly replaces: ${source.supersedes.join(", ")}`,"muted"));details.append(block);});
    target.append(details);
  }
  $("source-editor").hidden=!["AWAITING_APPROVAL","APPROVED","REJECTED","ESCALATED","FAILED"].includes(incident.status);
  const selectionKey=`${incident.id}:${sources.map(source=>source.id).join(",")}`;
  if($("supersedes").dataset.key!==selectionKey){
    $("supersedes").dataset.key=selectionKey;$("supersedes").replaceChildren();
    sources.forEach(source=>{const label=node("label",undefined,"checkbox-label");const input=node("input");input.type="checkbox";input.value=source.id;label.append(input,node("span",`${source.id} · ${source.source_label}`));$("supersedes").append(label);});
    if(!sources.length)$("supersedes").append(node("p","No earlier messages to replace.","muted"));
  }
}
function renderBusiness() {
  const target=$("business");target.replaceChildren();
  const recovery=incident.results.Recovery;
  if(!recovery){target.append(node("p","The comparison becomes available after evidence is reconciled and recovery is evaluated.","empty"));return;}
  const business=recovery.business_impact;
  if(!business){target.append(node("p","Refresh this older analysis to generate its business comparison.","muted"));return;}
  const grid=node("div",undefined,"impact-grid");
  [[business.without_action_shortage_units,"Short units · without action"],[business.with_plan_shortage_units,"Short units · with plan"],[currency(business.recovery_cost_paise),"Recovery cost · estimated"]].forEach(([value,label])=>{const metric=node("div",undefined,"metric");metric.append(node("strong",String(value)),node("small",label));grid.append(metric);});
  target.append(grid,node("p",incident.plan?.status === "NO_ACTION" ? "Available inventory covers the planning horizon. No recovery action is required." : business.executable_plan ? `${business.shortage_units_covered} units of modeled shortage covered within the planning horizon. Delivery has not been verified by this calculation.` : "No executable recovery plan is available. The comparison assumes no recovery arrivals.","muted"));
  const baseline=recovery.structured_only_baseline;
  if(baseline){const box=node("div",undefined,`comparison ${baseline.feasible_after_updates ? "" : "changed"}`);box.append(node("strong",baseline.feasible_after_updates ? "Original ERP plan remains feasible" : "Original ERP plan would miss constraints"),node("p",`Original plan cost: ${currency(baseline.cost_paise)}. ${baseline.invalid_reasons.join("; ") || "The original plan still satisfies the current dated-demand constraints."}`));target.append(box);}
  const assumptions=node("details");assumptions.append(node("summary","Financial assumptions · not measured savings"),node("p",`Assumed cost per short unit: ${currency(business.assumed_cost_per_short_unit_paise)}. Modeled exposure reduction: ${currency(business.modeled_exposure_reduction_paise)}. Modeled net benefit after recovery cost: ${currency(business.modeled_net_benefit_paise)}.`),node("p",business.scope,"muted"));target.append(assumptions);
}
function renderExplanations() {
  $("commentary").replaceChildren();
  const explanations=Object.entries(incident.commentary || {});
  explanations.forEach(([role,value])=>{const details=node("details",undefined,"evidence-item");details.append(node("summary",role),node("p",value.text),node("small",value.label,"muted"));$("commentary").append(details);});
  if(!explanations.length)$("commentary").append(node("p","No live model explanation is available for this run. Validated facts and calculations are shown in the decision panels.","empty"));
  $("run-metrics").textContent=incident.analysis_latency_ms ? `Analysis duration: ${(incident.analysis_latency_ms/1000).toFixed(2)} s · ${incident.model_usage?.length || 0} reported ADK model responses.` : "";
}
function render() {
  const results = incident?.results || {};
  $("pipeline").replaceChildren(...roles.map((role, index) => {
    const done = Boolean(results[role]);
    const running = incident?.status === "ANALYZING" && !done && (index === 0 || results[roles[index-1]]);
    const box = node("div", undefined, `stage ${done ? "done" : running ? "running" : ""}`);
    box.append(node("span", done ? "✓ COMPLETE" : running ? "● RUNNING" : `0${index+1}`, "step-number"), node("strong", role), node("small", descriptions[index]));
    return box;
  }));
  if (!incident) return;
  $("analyze").disabled=$("scenario").disabled=incident.status === "ANALYZING";
  $("status").textContent = incident.status.replaceAll("_", " ");
  message(incident.error || "");
  $("incident-detail").textContent=`${incident.scenario_title || "Supplier disruption"} · ${incident.snapshot.event.supplier_id} · ${incident.snapshot.event.material_id} · ${incident.snapshot.event.plant_id} · revision ${incident.revision}`;
  const impact = results.Impact;
  $("metrics").replaceChildren();
  $("timeline").replaceChildren();
  if (impact) {
    [[impact.available_units, "Available units"], [impact.days_of_cover ?? "—", "Days of cover"], [impact.shortage_units, "Units at risk"]].forEach(([value,label]) => {
      const box=node("div",undefined,"metric"); box.append(node("strong",String(value)),node("small",label)); $("metrics").append(box);
    });
    $("timeline").replaceChildren(...impact.timeline.map(row => {
      const after=results.Recovery?.business_impact?.timeline.find(r=>r.day===row.day);
      const tr=node("tr"); [row.day,row.demand,row.cumulative_shortage,after?.shortage_with_plan ?? "—"].forEach(x=>tr.append(node("td",String(x)))); return tr;
    }));
  }
  const plan=incident.plan;
  if (plan) {
    $("solver").textContent=plan.status;
    $("plan").replaceChildren(node("div",currency(plan.total_cost_paise),"plan-total"));
    plan.allocations.forEach(allocation=>{
      const option=incident.snapshot.options.find(x=>x.id===allocation.option_id);
      const item=node("div",undefined,"plan-item");
      item.append(node("strong",`${allocation.quantity} × ${option.material_id} · ${option.action_type.replaceAll("_"," ")}`), node("small",`${option.source_id} → ${option.destination} · arrival day ${option.arrival_day}`));
      $("plan").append(item);
    });
    $("plan").append(node("p",plan.status === "NO_ACTION" ? "No action is required for this planning snapshot." : plan.status === "INFEASIBLE" ? "No combination of the supplied options can meet every day's demand. Human review is required." : `Plan version ${plan.version} · expires ${new Date(plan.expires_at).toLocaleTimeString()} · human approval required before any simulated action.`,"muted"));
    if (Object.keys(results.Recovery?.excluded_options || {}).length) $("plan").append(node("p",`Excluded: ${Object.entries(results.Recovery.excluded_options).map(([id,why])=>`${id}: ${why}`).join("; ")}`,"muted"));
  } else {
    $("solver").textContent="Waiting for analysis";
    $("plan").replaceChildren(node("p","The Recovery agent will compare approved options against dated demand.","empty"));
  }
  $("approval").hidden=!["AWAITING_APPROVAL","APPROVED","MONITORING","REJECTED","ESCALATED","FAILED"].includes(incident.status);
  $("approve").hidden=$("reject").hidden=incident.status!=="AWAITING_APPROVAL";
  $("execute").hidden=incident.status!=="APPROVED";
  $("receive").hidden=incident.status!=="MONITORING";
  $("reanalyze").hidden=!["AWAITING_APPROVAL","APPROVED","REJECTED","ESCALATED","FAILED"].includes(incident.status);
  $("closure").textContent=incident.closure_reason || "";
  renderInterpretation(); renderBusiness(); renderExplanations();
  $("evidence").replaceChildren(...Object.values(incident.evidence).map(item=>{
    const details=node("details",undefined,"evidence-item");
    details.append(node("summary",`${item.kind} · ${item.id}`),node("p",item.explanation,"muted"),node("pre",JSON.stringify(item.value,null,2))); return details;
  }));
}
async function refresh() {
  if (!incident) return;
  const id=incident.id;
  const updated=await api(`/api/incidents/${id}`);
  if(incident.id!==id)return;
  incident=updated; render();
  const events=await api(`/api/incidents/${id}/trace`);
  if(incident.id!==id)return;
  $("activity").replaceChildren(...events.slice(-16).reverse().map(event=>{
    const item=node("li",`${event.agent} · ${event.kind.replaceAll("_"," ")}`);
    item.append(node("small",new Date(event.at).toLocaleTimeString())); return item;
  }));
}
function subscribe() {
  stream?.close();
  stream=new EventSource(`/api/incidents/${incident.id}/stream`);
  stream.addEventListener("progress",()=>{clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>refresh().catch(e=>message(e.message)),80);});
  stream.addEventListener("complete",()=>{stream.close();refresh().catch(e=>message(e.message));});
  stream.onerror=()=>{stream.close();refresh().catch(e=>message(e.message));};
}
async function action(button, operation) {
  button.disabled=true;message("");
  try {await operation();await refresh();} catch(error){message(error.message);} finally {button.disabled=button.id === "analyze" && incident?.status === "ANALYZING";}
}
$("analyze").onclick=()=>action($("analyze"),async()=>{
  stream?.close(); clearTimeout(refreshTimer);
  incident=await api("/api/incidents",{method:"POST",body:JSON.stringify({scenario_id:$("scenario").value})});
  await api(`/api/incidents/${incident.id}/analyze`,{method:"POST"}); subscribe();
});
for (const [id,decision] of [["approve","APPROVE"],["reject","REJECT"]]) $(id).onclick=()=>action($(id),()=>api(`/api/incidents/${incident.id}/decision`,{method:"POST",auth:true,body:JSON.stringify({decision,plan_hash:incident.plan_hash})}));
$("execute").onclick=()=>action($("execute"),()=>api(`/api/incidents/${incident.id}/execute`,{method:"POST",auth:true,body:JSON.stringify({plan_hash:incident.plan_hash})}));
$("receive").onclick=()=>action($("receive"),()=>api(`/api/incidents/${incident.id}/simulate-receipt`,{method:"POST",auth:true}));
$("reanalyze").onclick=()=>action($("reanalyze"),async()=>{await api(`/api/incidents/${incident.id}/reanalyze`,{method:"POST",auth:true});subscribe();});
$("connect").onclick=()=>action($("connect"),async()=>{const actor=await api("/api/me",{auth:true});$("access-status").textContent=`· ${actor.role} connected`;$("access").open=false;});
$("token").oninput=()=>{$("access-status").textContent="· credential not verified";};
$("submit-update").onclick=()=>action($("submit-update"),async()=>{
  const text=$("source-text").value.trim(),source_label=$("source-label").value.trim();
  if(!text||!source_label)throw new Error("Enter a source label and shipment message.");
  const supersedes=Array.from($("supersedes").querySelectorAll("input:checked")).map(input=>input.value);
  await api(`/api/incidents/${incident.id}/updates`,{method:"POST",auth:true,body:JSON.stringify({text,source_label,supersedes})});
  $("source-text").value="";$("source-editor").open=false;subscribe();
});
$("scenario").onchange=()=>{$("scenario-description").textContent=scenarios.find(s=>s.id===$("scenario").value)?.description || "";};
render();
(async()=>{
  const health=await api("/health");
  $("mode").textContent=`Agent orchestration: ${health.agent_mode === "google" ? "Gemini / ADK" : "local deterministic stages"}. Shipment interpretation: ${health.evidence_mode === "gemini" ? "live Gemini structured extraction" : "strict rules baseline"}. Tools calculate and enforce policy; people authorize actions.`;
  scenarios=await api("/api/scenarios");$("scenario").replaceChildren(...scenarios.map(s=>{const option=node("option",s.title);option.value=s.id;return option;}));$("scenario").onchange();
  const list=await api("/api/incidents"); if(list.length){incident=list[0];$("scenario").value=incident.scenario_id||"baseline";$("scenario").onchange();await refresh();if(incident.status==="ANALYZING")subscribe();}
  const evaluation=await api("/api/evaluation");$("evaluation").replaceChildren();
  if(evaluation.available){
    $("evaluation").append(node("p",evaluation.current ? "Current synthetic regression suite" : "Report predates code/data changes; rerun the evaluation.","muted"));
    Object.entries(evaluation.modes).forEach(([name,result])=>$("evaluation").append(node("p",`${name}: ${result.correct_decisions}/${result.cases} correct decisions`)));
    $("evaluation").append(node("p",`Live Gemini: ${evaluation.gemini_live.replaceAll("_"," ")}. This small authored suite does not establish real-world accuracy.`,"muted"));
    const link=node("a","Open detailed evaluation ↗");link.href="/evaluation";link.target="_blank";link.rel="noopener";$("evaluation").append(link);
  }else $("evaluation").append(node("p","No evaluation report is available for this deployment. Model accuracy and human review time are not yet established.","empty"));
})().catch(error=>message(error.message));
