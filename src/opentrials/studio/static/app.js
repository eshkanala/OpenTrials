(function () {
  "use strict";

  var root = document.documentElement;
  var lightBtn = document.getElementById("lightBtn");
  var darkBtn = document.getElementById("darkBtn");
  var pathInput = document.getElementById("pathInput");
  var openBtn = document.getElementById("openBtn");
  var saveBtn = document.getElementById("saveBtn");
  var validateBtn = document.getElementById("validateBtn");
  var runBtn = document.getElementById("runBtn");
  var tpath = document.getElementById("tpath");
  var appMain = document.getElementById("appMain");
  var statusState = document.getElementById("statusState");
  var statusPop = document.getElementById("statusPop");

  var ROUTES = [
    "ORAL", "INTRAVENOUS", "INTRAMUSCULAR", "SUBCUTANEOUS", "INHALED",
    "TRANSDERMAL", "INTRANASAL", "OCULAR", "RECTAL", "OTHER",
  ];
  var SEXES = ["FEMALE", "MALE", "INTERSEX", "UNSPECIFIED"];

  // Mirrors cli/progress.py's _STAGE_LABELS -- Studio must render the exact
  // same stage vocabulary the CLI does, not an invented one.
  var STAGE_LABELS = {
    verifying_population: "Verifying population",
    verifying_physiology_population: "Verifying physiology population",
    verifying_source_population: "Verifying source population",
    translating_intervention: "Translating intervention",
    translating_population_specification: "Translating population specification",
    generating_population: "Generating population",
    persisting_population: "Persisting population",
    executing_population: "Executing population",
    persisting_raw: "Persisting raw results",
    normalizing_results: "Normalizing results",
    resolving_lineage: "Resolving lineage",
    calculating_endpoints: "Calculating endpoints",
    writing_manifest: "Writing manifest",
    validating_trial: "Validating trial",
    allocating_arms: "Allocating arms",
    comparing_arms: "Comparing arms",
    writing_trial_record: "Writing trial record",
    completed: "Completed",
  };

  function stageLabel(stage) {
    if (STAGE_LABELS[stage]) return STAGE_LABELS[stage];
    if (stage.indexOf("executing_arm:") === 0) {
      return "Executing arm " + stage.slice("executing_arm:".length);
    }
    var spaced = stage.replace(/_/g, " ");
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  }

  var state = {
    path: null,
    project: null,
    models: [],
    activePane: "overview",
    lastRunId: null,
    lastRunPoll: null,
  };

  function setTheme(t) {
    if (t === "dark") {
      root.setAttribute("data-theme", "dark");
      darkBtn.classList.add("on");
      lightBtn.classList.remove("on");
    } else {
      root.setAttribute("data-theme", "light");
      lightBtn.classList.add("on");
      darkBtn.classList.remove("on");
    }
    localStorage.setItem("otstudio-theme", t);
  }
  lightBtn.addEventListener("click", function () { setTheme("light"); });
  darkBtn.addEventListener("click", function () { setTheme("dark"); });
  var savedTheme = localStorage.getItem("otstudio-theme");
  if (savedTheme) setTheme(savedTheme);

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = String(s);
    return div.innerHTML;
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
  }

  function fmtScientific(v) {
    if (!v) return "&mdash;";
    return escapeHtml(v.value) + "&nbsp;" + escapeHtml(v.unit);
  }

  function setBusy(busy) {
    openBtn.style.pointerEvents = busy ? "none" : "";
    if (busy) statusState.textContent = "Working…";
  }

  function fetchModels() {
    return fetch("/api/models")
      .then(function (r) { return r.json(); })
      .then(function (models) { state.models = models; });
  }

  function modelOptionsHtml(currentId) {
    var options = '<option value="">(none — auto-resolve if exactly one registered)</option>';
    state.models.forEach(function (m) {
      var sel = m.model_id === currentId ? " selected" : "";
      options += '<option value="' + escapeAttr(m.model_id) + '"' + sel + ">" + escapeHtml(m.model_id) + "</option>";
    });
    return options;
  }

  function selectOptionsHtml(values, current) {
    return values.map(function (v) {
      var sel = v === current ? " selected" : "";
      return '<option value="' + v + '"' + sel + ">" + v + "</option>";
    }).join("");
  }

  function renderError(message) {
    appMain.innerHTML = '<div class="error-banner"><strong>Could not open project.</strong><br />' + escapeHtml(message) + "</div>";
    saveBtn.setAttribute("disabled", "disabled");
    validateBtn.setAttribute("disabled", "disabled");
    runBtn.setAttribute("disabled", "disabled");
    tpath.textContent = "no project open";
    statusState.textContent = "Error";
    statusPop.textContent = "—";
  }

  // ================= Overview pane =================

  function renderProject(project) {
    state.project = project;
    state.activePane = "overview";
    tpath.textContent = project.path;
    saveBtn.removeAttribute("disabled");
    validateBtn.removeAttribute("disabled");
    runBtn.removeAttribute("disabled");
    statusState.textContent = "Ready";
    statusPop.textContent = project.population.size + " participant(s)";

    var modelTag = project.resolved_model
      ? '<span class="tag tag-model">' + escapeHtml(project.resolved_model.id) + "</span>"
      : '<span class="tag" style="color:var(--absent)">unresolved</span>';

    var armsHtml = project.arms.map(function (arm) {
      return (
        '<div class="arm-row">' +
        '<span class="arm-pill">' + escapeHtml(arm.arm_id) + "</span>" +
        '<span class="arm-dose">' + escapeHtml(arm.compound) + " &middot; <span class=\"n\">" + fmtScientific(arm.dose) + "</span> " + escapeHtml(arm.route) + "</span>" +
        '<span class="arm-count">alloc ' + arm.allocation + "</span>" +
        "</div>"
      );
    }).join("");

    var endpointsHtml = project.endpoints.map(function (ep) {
      return (
        '<div class="prow">' +
        '<div class="pk">' + escapeHtml(ep.endpoint_type) + "</div>" +
        '<div class="pv">' + escapeHtml(ep.measurement) + " (" + escapeHtml(ep.unit) + ")</div>" +
        "</div>"
      );
    }).join("");

    appMain.innerHTML =
      '<div class="app-topbar">' +
      "<div><h3>" + escapeHtml(project.title) + "</h3>" +
      '<div class="sub">' + escapeHtml(project.trial_id) + "</div></div>" +
      "<div>" + modelTag + "</div>" +
      "</div>" +
      '<div class="grid-2">' +
      "<div>" +
      '<div class="panel">' +
      '<div class="phead">Model &amp; population</div>' +
      '<div class="pbody">' +
      '<div class="field"><span class="flabel">Registered model</span>' +
      '<select class="fselect" id="modelSelect">' + modelOptionsHtml(project.model_id) + "</select></div>" +
      '<div class="frow2">' +
      '<div class="field"><span class="flabel">Population size</span><input class="finput" id="popSize" type="number" min="1" value="' + project.population.size + '" /></div>' +
      '<div class="field"><span class="flabel">Seed</span><input class="finput" id="popSeed" type="number" value="' + project.population.seed + '" /></div>' +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead"><span>Arms</span><span>' + project.arms.length + " arm(s)</span></div>" +
      '<div class="pbody">' + (armsHtml || '<span style="color:var(--ink-faint);font-size:11px;">no arms</span>') + "</div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead">Endpoints</div>' +
      '<div class="pbody"><div class="propgrid">' + (endpointsHtml || "") + "</div></div>" +
      "</div>" +
      "</div>" +
      "<div>" +
      '<div class="panel">' +
      '<div class="phead">Trial</div>' +
      '<div class="pbody"><div class="propgrid">' +
      '<div class="prow"><div class="pk">Randomization</div><div class="pv">' + escapeHtml(project.randomization) + "</div></div>" +
      '<div class="prow"><div class="pk">Seed</div><div class="pv mono">' + project.seed + "</div></div>" +
      '<div class="prow"><div class="pk">Question</div><div class="pv" style="font-weight:400;">' + escapeHtml(project.question_of_interest) + "</div></div>" +
      "</div></div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead">Validation</div>' +
      '<div class="pbody" id="validationBody"><span style="color:var(--ink-faint);font-size:11px;">Not yet checked &mdash; click Validate.</span></div>' +
      "</div>" +
      "</div>" +
      "</div>";
  }

  function collectOverviewEdits() {
    var modelSelect = document.getElementById("modelSelect");
    var popSize = document.getElementById("popSize");
    var popSeed = document.getElementById("popSeed");
    var edits = { trial: { population: {} } };
    edits.model_id = modelSelect.value ? modelSelect.value : null;
    edits.trial.population.size = parseInt(popSize.value, 10);
    edits.trial.population.seed = parseInt(popSeed.value, 10);
    return edits;
  }

  // ================= Trial Builder pane =================

  function armRowHtml(arm, idx) {
    var isIv = arm.route === "INTRAVENOUS";
    return (
      '<tr data-idx="' + idx + '">' +
      '<td><input class="finput mono" style="width:76px" data-field="arm_id" value="' + escapeAttr(arm.arm_id) + '" /></td>' +
      '<td><input class="finput mono" style="width:76px" data-field="name" value="' + escapeAttr(arm.name) + '" /></td>' +
      '<td><input class="finput mono" style="width:80px" data-field="compound_id" value="' + escapeAttr(arm.compound_id) + '" /><br/>' +
      '<input class="finput mono" style="width:80px;margin-top:2px" data-field="compound_name" value="' + escapeAttr(arm.compound) + '" /></td>' +
      '<td><div class="arms-cell-pair"><input class="finput mono" data-field="dose_value" type="number" step="any" value="' + arm.dose.value + '" />' +
      '<input class="finput mono" data-field="dose_unit" value="' + escapeAttr(arm.dose.unit) + '" /></div></td>' +
      '<td><select class="fselect" data-field="route">' + selectOptionsHtml(ROUTES, arm.route) + "</select></td>" +
      '<td><div class="arms-cell-pair"><input class="finput mono" data-field="admin_time_value" type="number" step="any" value="' + arm.administration_time.value + '" />' +
      '<input class="finput mono" data-field="admin_time_unit" value="' + escapeAttr(arm.administration_time.unit) + '" /></div></td>' +
      '<td><div class="arms-cell-pair" data-infusion-pair>' +
      '<input class="finput mono" data-field="infusion_value" type="number" step="any" ' + (isIv ? "" : "disabled") +
      ' value="' + (arm.infusion_duration ? arm.infusion_duration.value : "") + '" />' +
      '<input class="finput mono" data-field="infusion_unit" ' + (isIv ? "" : "disabled") +
      ' value="' + (arm.infusion_duration ? escapeAttr(arm.infusion_duration.unit) : "min") + '" /></div></td>' +
      '<td><input class="finput mono" style="width:50px" data-field="allocation" type="number" step="any" value="' + arm.allocation + '" /></td>' +
      '<td class="rm" data-action="remove">&times;</td>' +
      "</tr>"
    );
  }

  function renderTrialBuilder(project) {
    state.activePane = "builder";
    tpath.textContent = project.path;

    var sexChecks = SEXES.map(function (s) {
      var checked = project.population.sexes.indexOf(s) !== -1 ? " checked" : "";
      return '<label class="fcheck"><input type="checkbox" data-sex="' + s + '"' + checked + " />" + s + "</label>";
    }).join("");

    var ageMin = project.population.age_range ? project.population.age_range.minimum : null;
    var ageMax = project.population.age_range ? project.population.age_range.maximum : null;

    var armRows = project.arms.map(armRowHtml).join("");

    appMain.innerHTML =
      '<div class="app-topbar">' +
      "<div><h3>Trial builder</h3><div class=\"sub\">" + escapeHtml(project.trial_id) + " &middot; opentrials.project v1.0.0</div></div>" +
      "</div>" +
      '<div class="grid-2">' +
      "<div>" +
      '<div class="panel">' +
      '<div class="phead">Population sampling</div>' +
      '<div class="pbody">' +
      '<div class="frow2">' +
      '<div class="field"><span class="flabel">Minimum age</span><div class="arms-cell-pair"><input class="finput" id="ageMinVal" type="number" step="any" value="' + (ageMin ? ageMin.value : "") + '" /><input class="finput" id="ageMinUnit" value="' + (ageMin ? escapeAttr(ageMin.unit) : "year") + '" /></div></div>' +
      '<div class="field"><span class="flabel">Maximum age</span><div class="arms-cell-pair"><input class="finput" id="ageMaxVal" type="number" step="any" value="' + (ageMax ? ageMax.value : "") + '" /><input class="finput" id="ageMaxUnit" value="' + (ageMax ? escapeAttr(ageMax.unit) : "year") + '" /></div></div>' +
      "</div>" +
      '<div class="field"><span class="flabel">Sexes included</span>' + sexChecks + "</div>" +
      "</div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead"><span>Arms</span><span>' + project.arms.length + " arm(s)</span></div>" +
      '<div class="pbody">' +
      '<div style="overflow-x:auto"><table class="arms-table" id="armsTable">' +
      "<thead><tr><th>Arm ID</th><th>Name</th><th>Compound</th><th>Dose</th><th>Route</th><th>Admin. time</th><th>Infusion</th><th>Alloc.</th><th></th></tr></thead>" +
      "<tbody>" + armRows + "</tbody>" +
      "</table></div>" +
      '<div class="addrow-btn" id="addArmBtn">+ Add arm</div>' +
      "</div>" +
      "</div>" +
      "</div>" +
      "<div>" +
      '<div class="panel">' +
      '<div class="phead">Randomization</div>' +
      '<div class="pbody">' +
      '<label class="fradio"><input type="radio" name="randomization" value="PARALLEL"' + (project.randomization === "PARALLEL" ? " checked" : "") + " /> Parallel, fixed allocation</label>" +
      '<label class="fradio"><input type="radio" name="randomization" value="NONE"' + (project.randomization === "NONE" ? " checked" : "") + " /> None (single arm)</label>" +
      "</div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead">Notes</div>' +
      '<div class="pbody" style="font-size:10.5px;color:var(--ink-faint);line-height:1.6;">' +
      "Editing here changes the trial protocol. Non-randomized trials must have exactly one arm; parallel trials need two or more arms whose allocations sum to 1. " +
      "Saving re-validates through the same OpenTrials schemas the CLI uses &mdash; an invalid combination is rejected here, not silently written." +
      "</div>" +
      "</div>" +
      "</div>" +
      "</div>";

    document.getElementById("addArmBtn").addEventListener("click", function () {
      var tbody = document.querySelector("#armsTable tbody");
      var n = tbody.children.length;
      var template = {
        arm_id: "arm-" + (n + 1),
        name: "arm-" + (n + 1),
        allocation: 0,
        compound_id: state.project.arms.length ? state.project.arms[0].compound_id : "compound",
        compound: state.project.arms.length ? state.project.arms[0].compound : "Compound",
        dose: { value: 0, unit: "mg" },
        route: "INTRAVENOUS",
        administration_time: { value: 0, unit: "min" },
        infusion_duration: { value: 10, unit: "min" },
      };
      tbody.insertAdjacentHTML("beforeend", armRowHtml(template, n));
      wireArmsTable();
    });
    wireArmsTable();
  }

  function wireArmsTable() {
    var table = document.getElementById("armsTable");
    if (!table) return;
    table.querySelectorAll('[data-action="remove"]').forEach(function (cell) {
      cell.onclick = function () { cell.closest("tr").remove(); };
    });
    table.querySelectorAll('select[data-field="route"]').forEach(function (sel) {
      sel.onchange = function () {
        var pair = sel.closest("tr").querySelector("[data-infusion-pair]");
        var isIv = sel.value === "INTRAVENOUS";
        pair.querySelectorAll("input").forEach(function (input) {
          input.disabled = !isIv;
        });
      };
    });
  }

  function collectBuilderEdits() {
    var edits = { trial: { population: {}, arms: [] } };

    var ageMinVal = document.getElementById("ageMinVal").value;
    var ageMaxVal = document.getElementById("ageMaxVal").value;
    if (ageMinVal !== "" && ageMaxVal !== "") {
      edits.trial.population.age_range = {
        minimum: { value: parseFloat(ageMinVal), unit: document.getElementById("ageMinUnit").value, value_type: "ASSUMED" },
        maximum: { value: parseFloat(ageMaxVal), unit: document.getElementById("ageMaxUnit").value, value_type: "ASSUMED" },
      };
    } else {
      edits.trial.population.age_range = null;
    }
    edits.trial.population.sexes = Array.prototype.slice
      .call(document.querySelectorAll("[data-sex]"))
      .filter(function (cb) { return cb.checked; })
      .map(function (cb) { return cb.dataset.sex; });

    var randomization = document.querySelector('input[name="randomization"]:checked');
    edits.trial.randomization = randomization ? randomization.value : "NONE";

    var rows = document.querySelectorAll("#armsTable tbody tr");
    rows.forEach(function (row, idx) {
      var field = function (name) { return row.querySelector('[data-field="' + name + '"]').value; };
      var armId = field("arm_id");
      var route = field("route");
      var isIv = route === "INTRAVENOUS";
      var infusionValue = field("infusion_value");
      var arm = {
        arm_id: armId,
        name: field("name"),
        allocation: parseFloat(field("allocation")),
        intervention: {
          intervention_id: armId + "-intervention-" + idx,
          compound: {
            identity: {
              compound_id: field("compound_id"),
              preferred_name: field("compound_name"),
            },
          },
          regimen: {
            regimen_id: armId + "-regimen-" + idx,
            doses: [
              {
                amount: { value: parseFloat(field("dose_value")), unit: field("dose_unit"), value_type: "ASSUMED" },
                route: route,
                administration_time: {
                  value: parseFloat(field("admin_time_value")),
                  unit: field("admin_time_unit"),
                  value_type: "ASSUMED",
                },
                infusion_duration:
                  isIv && infusionValue !== ""
                    ? { value: parseFloat(infusionValue), unit: field("infusion_unit"), value_type: "ASSUMED" }
                    : null,
              },
            ],
          },
        },
      };
      edits.trial.arms.push(arm);
    });

    return edits;
  }

  // ================= Live execution + Results panes =================

  function renderLiveExecution() {
    state.activePane = "run";
    if (!state.lastRunId) {
      appMain.innerHTML = '<div class="empty-state">No run started yet.<br />Click Run in the toolbar to execute this project through the real SDK.</div>';
      return;
    }
    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Live execution</h3><div class="sub">' + escapeHtml(state.path) + "</div></div></div>" +
      '<div class="panel"><div class="phead">Stages</div><div class="pbody"><div class="stage-list" id="stageList"></div></div></div>' +
      '<div class="panel" id="runResultPanel" style="display:none"></div>';
    renderRunPoll(state.lastRunPoll || { status: "running", events: [] });
  }

  function renderRunPoll(poll) {
    var list = document.getElementById("stageList");
    if (list) {
      // Not every stage reports a STARTED event -- most orchestration
      // stages only ever emit one COMPLETED event per stage_progress_adapter's
      // own documented behavior, but population generation genuinely emits
      // real STARTED/COMPLETED pairs. Key rows by stage name and keep the
      // latest-known event per stage, so a real STARTED signal shows as
      // "in progress" rather than being mistaken for a second completed row.
      var byStage = {};
      var order = [];
      poll.events.forEach(function (e) {
        if (!Object.prototype.hasOwnProperty.call(byStage, e.stage)) order.push(e.stage);
        byStage[e.stage] = e;
      });
      list.innerHTML = order.map(function (stage) {
        var e = byStage[stage];
        var cls = e.status === "FAILED" ? "failed" : e.status === "STARTED" ? "active" : "done";
        var icon = e.status === "FAILED" ? "&#10007;" : e.status === "STARTED" ? "&#9679;" : "&#10003;";
        var time = e.timestamp.split("T")[1] ? e.timestamp.split("T")[1].split(".")[0] : "";
        return (
          '<div class="stg ' + cls + '"><span class="ic">' + icon + "</span>" +
          '<span class="nm">' + escapeHtml(stageLabel(stage)) + "</span>" +
          '<span class="tm">' + escapeHtml(time) + "</span></div>"
        );
      }).join("") || '<span style="color:var(--ink-faint);font-size:11px;">Starting&hellip;</span>';
    }

    var resultPanel = document.getElementById("runResultPanel");
    if (!resultPanel) return;
    if (poll.status === "completed") {
      resultPanel.style.display = "";
      resultPanel.innerHTML =
        '<div class="phead">Result</div><div class="pbody">' +
        '<div class="propgrid">' +
        '<div class="prow"><div class="pk">Status</div><div class="pv" style="color:var(--verified)">Completed &amp; verified</div></div>' +
        '<div class="prow"><div class="pk">Run directory</div><div class="pv mono">' + escapeHtml(poll.run_directory) + "</div></div>" +
        "</div>" +
        '<pre style="white-space:pre-wrap;font-family:&quot;PT Sans&quot;,sans-serif;font-size:10.5px;margin-top:8px;line-height:1.6;">' + escapeHtml(poll.summary) + "</pre>" +
        "</div>";
    } else if (poll.status === "failed") {
      resultPanel.style.display = "";
      resultPanel.innerHTML =
        '<div class="phead">Result</div><div class="pbody"><div class="error-banner"><strong>Run failed.</strong><br />' + escapeHtml(poll.error) + "</div></div>";
    }
  }

  function pollRun(runId) {
    fetch("/api/run/" + runId)
      .then(function (r) { return r.json(); })
      .then(function (poll) {
        state.lastRunPoll = poll;
        if (state.activePane === "run") renderRunPoll(poll);
        if (poll.status === "running") {
          setTimeout(function () { pollRun(runId); }, 700);
        } else {
          statusState.textContent = poll.status === "completed" ? "Run completed and verified" : "Run failed";
        }
      });
  }

  function renderResults() {
    state.activePane = "results";
    if (!state.lastRunId || !state.lastRunPoll || state.lastRunPoll.status !== "completed") {
      appMain.innerHTML = '<div class="empty-state">Results appear here after a run completes.<br />Use Run in the toolbar to execute this project through the real SDK.</div>';
      return;
    }
    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Results</h3><div class="sub">' + escapeHtml(state.lastRunPoll.run_directory) + "</div></div></div>" +
      '<iframe src="/api/run/' + encodeURIComponent(state.lastRunId) + '/report.html" style="width:100%;height:68vh;border:1px solid var(--border);background:var(--white);"></iframe>';
  }

  // ================= Provenance pane =================

  function renderProvenance() {
    state.activePane = "provenance";
    if (!state.lastRunId || !state.lastRunPoll || state.lastRunPoll.status !== "completed") {
      appMain.innerHTML = '<div class="empty-state">Provenance appears here after a run completes.<br />Every node shown is re-verified from its own store on load &mdash; nothing here is cached trust.</div>';
      return;
    }
    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Provenance</h3><div class="sub">' + escapeHtml(state.lastRunPoll.run_directory) + "</div></div></div>" +
      '<div class="empty-state" id="provenanceBody">Loading&hellip;</div>';

    fetch("/api/run/" + encodeURIComponent(state.lastRunId) + "/provenance")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var chainNodes = ["OTPGEN"];
        if (d.provenance.trial_sha256) chainNodes.push("OTALLOC", "OTTRIAL");
        chainNodes.push("OTPK");

        var verificationRows = d.execution_verification.map(function (row) {
          return (
            '<div class="prow"><div class="pk">' + escapeHtml(row.arm_id || "population") + "</div>" +
            '<div class="pv">' +
            (row.model_hash_verified ? '<span class="tag" style="color:var(--verified)">model hash</span> ' : "") +
            (row.route_container_verified ? '<span class="tag" style="color:var(--verified)">route container</span> ' : "") +
            (row.solver_executed ? '<span class="tag" style="color:var(--verified)">solver executed</span>' : "") +
            "</div></div>"
          );
        }).join("");

        var body = document.getElementById("provenanceBody");
        body.className = "";
        body.innerHTML =
          '<div class="panel"><div class="phead">Chain</div><div class="pbody">' +
          '<div class="provenance-chain">' + chainNodes.map(function (n) { return '<span class="chain-node">' + n + "</span>"; }).join("") + "</div>" +
          '<p style="font-size:10.5px;color:var(--ink-faint);margin:8px 0 0;">Re-verified from each sub-artifact\'s own store on every load.</p>' +
          "</div></div>" +
          '<div class="panel"><div class="phead">Hashes &amp; identifiers</div><div class="pbody">' +
          '<div class="hash-line"><span class="k">Model</span><span class="v mono">' + escapeHtml(d.model.artifact_hash) + "</span></div>" +
          '<div class="hash-line"><span class="k">Population</span><span class="v mono">' + escapeHtml(d.provenance.population_generation_id) + "</span></div>" +
          '<div class="hash-line"><span class="k">Population hash</span><span class="v mono">' + escapeHtml(d.provenance.population_semantic_sha256) + "</span></div>" +
          (d.provenance.trial_sha256 ? '<div class="hash-line"><span class="k">Trial hash</span><span class="v mono">' + escapeHtml(d.provenance.trial_sha256) + "</span></div>" : "") +
          (d.provenance.allocation_id ? '<div class="hash-line"><span class="k">Allocation</span><span class="v mono">' + escapeHtml(d.provenance.allocation_id) + "</span></div>" : "") +
          "</div></div>" +
          '<div class="panel"><div class="phead">Execution verification</div><div class="pbody"><div class="propgrid">' + verificationRows + "</div></div></div>";
      });
  }

  // ================= Evidence Browser pane =================

  function renderEvidence() {
    state.activePane = "evidence";
    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Evidence</h3><div class="sub">Registered external-evidence connectors</div></div></div>' +
      '<div class="panel"><div class="pbody"><table class="evi-table" id="evidenceTable">' +
      "<thead><tr><th>Connector</th><th>Version</th><th>Outcome</th><th></th></tr></thead>" +
      "<tbody></tbody></table></div></div>";

    fetch("/api/evidence")
      .then(function (r) { return r.json(); })
      .then(function (connectors) {
        var tbody = document.querySelector("#evidenceTable tbody");
        tbody.innerHTML = connectors.map(function (c) {
          return (
            '<tr data-connector="' + escapeAttr(c.connector_id) + '">' +
            '<td class="mono">' + escapeHtml(c.connector_id) + "</td>" +
            '<td class="mono">' + escapeHtml(c.version) + "</td>" +
            '<td class="outcome">not yet run</td>' +
            '<td><span class="btn raised run-connector" style="cursor:pointer;">Run</span></td>' +
            "</tr>"
          );
        }).join("");
        tbody.querySelectorAll(".run-connector").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var row = btn.closest("tr");
            var connectorId = row.dataset.connector;
            var outcomeCell = row.querySelector(".outcome");
            outcomeCell.textContent = "Running…";
            fetch("/api/evidence/" + encodeURIComponent(connectorId) + "/run", { method: "POST" })
              .then(function (r) { return r.json(); })
              .then(function (result) {
                if (result.eligible) {
                  outcomeCell.innerHTML =
                    '<span class="role-tag role-ok">' + escapeHtml(result.role) + "</span> " +
                    result.observation_count + " observation(s) &middot; " + escapeHtml(result.license);
                } else {
                  outcomeCell.innerHTML = '<span class="role-tag role-blocked">INELIGIBLE</span> ' + escapeHtml(result.reason);
                }
              })
              .catch(function (err) {
                outcomeCell.innerHTML = '<span class="role-tag role-blocked">ERROR</span> ' + escapeHtml(err.message);
              });
          });
        });
      });
  }

  // ================= Model Builder pane =================

  function renderModelBuilder() {
    state.activePane = "model-builder";
    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Model builder</h3><div class="sub">PKML discovery &amp; profile scaffolding</div></div></div>' +
      '<div class="review-banner"><span class="ic">&#9888;</span><span class="tx"><strong>Discovery does not imply capability verification.</strong> Inspecting a PKML file reports what OSP itself can discover; nothing here is a registered, trusted model until a researcher reviews and verifies the generated scaffold.</span></div>' +
      '<div class="panel"><div class="phead">Inspect a PKML file</div><div class="pbody">' +
      '<div class="field"><span class="flabel">PKML path</span><input class="finput" id="pkmlPath" type="text" placeholder="/path/to/model.pkml" /></div>' +
      '<span class="btn btn-primary raised" id="inspectBtn" style="cursor:pointer;">Inspect</span>' +
      '</div></div>' +
      '<div id="inspectionResult"></div>';

    document.getElementById("inspectBtn").addEventListener("click", function () {
      var pkmlPath = document.getElementById("pkmlPath").value.trim();
      if (!pkmlPath) return;
      var resultBox = document.getElementById("inspectionResult");
      resultBox.innerHTML = '<div class="empty-state">Inspecting&hellip;</div>';
      fetch("/api/model/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pkml_path: pkmlPath }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "inspection failed"); });
          return r.json();
        })
        .then(function (report) { renderInspectionReport(report, pkmlPath); })
        .catch(function (err) {
          resultBox.innerHTML = '<div class="error-banner"><strong>Inspection failed.</strong><br />' + escapeHtml(err.message) + "</div>";
        });
    });
  }

  function renderInspectionReport(report, pkmlPath) {
    var resultBox = document.getElementById("inspectionResult");
    var adminRows = report.administrations.map(function (a) {
      return '<div class="param-row">' + escapeHtml(a.container) + " &middot; " + a.parameter_paths.length + " parameter path(s)</div>";
    }).join("") || '<div class="param-row">none discovered</div>';

    resultBox.innerHTML =
      '<div class="panel"><div class="phead">Discovery: ' + escapeHtml(report.name) + "</div><div class=\"pbody\">" +
      '<div class="propgrid">' +
      '<div class="prow"><div class="pk">SHA-256</div><div class="pv mono">' + escapeHtml(report.pkml_sha256) + "</div></div>" +
      '<div class="prow"><div class="pk">Compounds</div><div class="pv">' + escapeHtml(report.molecule_names.join(", ") || "none") + "</div></div>" +
      '<div class="prow"><div class="pk">Outputs</div><div class="pv">' + report.output_paths.length + " candidate path(s)</div></div>" +
      '<div class="prow"><div class="pk">Mutable params</div><div class="pv">' + report.mutable_parameter_count + "</div></div>" +
      '<div class="prow"><div class="pk">Population support</div><div class="pv">' + (report.population_support_detected ? "detected" : "not detected") + "</div></div>" +
      "</div>" +
      '<div style="margin-top:8px;"><span class="flabel" style="display:block;margin-bottom:4px;">Administration candidates</span>' + adminRows + "</div>" +
      "</div></div>" +
      '<div class="panel"><div class="phead">Generate profile scaffold</div><div class="pbody">' +
      '<div class="field"><span class="flabel">Model ID</span><input class="finput" id="scaffoldModelId" type="text" placeholder="osp.compound.route-variant" /></div>' +
      '<span class="btn btn-primary raised" id="scaffoldBtn" style="cursor:pointer;">Generate scaffold</span>' +
      '<div id="scaffoldResult" style="margin-top:8px;"></div>' +
      "</div></div>";

    document.getElementById("scaffoldBtn").addEventListener("click", function () {
      var modelId = document.getElementById("scaffoldModelId").value.trim();
      if (!modelId) return;
      var scaffoldResult = document.getElementById("scaffoldResult");
      scaffoldResult.innerHTML = "Generating…";
      fetch("/api/model/scaffold", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pkml_path: pkmlPath, model_id: modelId }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "scaffold generation failed"); });
          return r.json();
        })
        .then(function (result) {
          scaffoldResult.innerHTML =
            '<div class="hash-line"><span class="k">Scaffold written</span><span class="v mono">' + escapeHtml(result.output_path) + "</span></div>" +
            '<p style="font-size:10.5px;color:var(--ink-faint);margin:8px 0 0;">This is a starting point, not a registered model. Open the file, review every REQUIRED REVIEW comment, verify each value against a real execution, then delete the NotImplementedError guard before using it.</p>';
        })
        .catch(function (err) {
          scaffoldResult.innerHTML = '<span style="color:var(--absent)">' + escapeHtml(err.message) + "</span>";
        });
    });
  }

  // ================= Validation rendering =================

  function renderValidation(result) {
    var body = document.getElementById("validationBody");
    if (!body) return;
    var rungs = result.checks.map(function (c) {
      return (
        '<div class="rung"><span class="sq ' + c.status + '"></span>' +
        '<span class="txt"><strong>' + escapeHtml(c.label) + "</strong><span>" + escapeHtml(c.detail) + "</span></span></div>"
      );
    }).join("");
    body.innerHTML = '<div class="status-ladder">' + rungs + "</div>";
  }

  // ================= Open / Save / Validate =================

  function openProject(path) {
    if (!path) return;
    setBusy(true);
    fetch("/api/project?path=" + encodeURIComponent(path))
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "unknown error"); });
        return r.json();
      })
      .then(function (project) {
        state.path = path;
        renderProject(project);
      })
      .catch(function (err) { renderError(err.message); })
      .finally(function () { setBusy(false); });
  }

  openBtn.addEventListener("click", function () { openProject(pathInput.value.trim()); });
  pathInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") openProject(pathInput.value.trim());
  });

  validateBtn.addEventListener("click", function () {
    if (!state.path) return;
    statusState.textContent = "Validating…";
    fetch("/api/project/validate?path=" + encodeURIComponent(state.path), { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (result) {
        if (state.activePane === "overview") renderValidation(result);
        statusState.textContent = result.ok ? "Configuration valid" : "Configuration invalid";
      });
  });

  saveBtn.addEventListener("click", function () {
    if (!state.path) return;
    var edits;
    if (state.activePane === "builder") {
      edits = collectBuilderEdits();
    } else {
      edits = collectOverviewEdits();
    }

    statusState.textContent = "Saving…";
    fetch("/api/project/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.path, edits: edits }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "save failed"); });
        return r.json();
      })
      .then(function () {
        // Reopen from disk to prove the save round-trips with equivalent semantics --
        // this is a real re-read, not the in-memory object we just sent.
        return fetch("/api/project?path=" + encodeURIComponent(state.path));
      })
      .then(function (r) { return r.json(); })
      .then(function (project) {
        state.project = project;
        if (state.activePane === "builder") {
          renderTrialBuilder(project);
        } else {
          renderProject(project);
        }
        statusState.textContent = "Saved and reopened from disk";
      })
      .catch(function (err) {
        statusState.textContent = "Save failed";
        alert(err.message);
      });
  });

  function selectTreeItem(pane) {
    document.querySelectorAll(".tree-item").forEach(function (i) {
      i.classList.toggle("sel", i.dataset.pane === pane);
    });
  }

  runBtn.addEventListener("click", function () {
    if (!state.path) return;
    statusState.textContent = "Starting run…";
    fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.path }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "run failed to start"); });
        return r.json();
      })
      .then(function (res) {
        state.lastRunId = res.run_id;
        state.lastRunPoll = { status: "running", events: [] };
        selectTreeItem("run");
        renderLiveExecution();
        pollRun(state.lastRunId);
      })
      .catch(function (err) {
        statusState.textContent = "Run failed to start";
        alert(err.message);
      });
  });

  var treeItems = document.querySelectorAll(".tree-item");
  treeItems.forEach(function (item) {
    item.addEventListener("click", function () {
      treeItems.forEach(function (i) { i.classList.remove("sel"); });
      item.classList.add("sel");
      var pane = item.dataset.pane;
      // Model Builder and the Evidence Browser are project-independent --
      // both operate on a PKML path / registered connectors, not on
      // whatever project.yaml happens to be open.
      if (pane === "model-builder") {
        renderModelBuilder();
        return;
      }
      if (pane === "evidence") {
        renderEvidence();
        return;
      }
      if (!state.project) return;
      if (pane === "overview") {
        renderProject(state.project);
      } else if (pane === "builder") {
        renderTrialBuilder(state.project);
      } else if (pane === "run") {
        renderLiveExecution();
      } else if (pane === "results") {
        renderResults();
      } else if (pane === "provenance") {
        renderProvenance();
      }
    });
  });

  var initialPath = new URLSearchParams(window.location.search).get("path");
  if (initialPath) pathInput.value = initialPath;

  fetchModels().then(function () {
    if (pathInput.value.trim()) openProject(pathInput.value.trim());
  });
})();
