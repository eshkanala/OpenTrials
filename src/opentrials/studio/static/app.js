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
  var exportBtn = document.getElementById("exportBtn");
  var tpath = document.getElementById("tpath");
  var appMain = document.getElementById("appMain");
  var statusState = document.getElementById("statusState");
  var statusPop = document.getElementById("statusPop");

  var ROUTES = [
    "ORAL", "INTRAVENOUS", "INTRAMUSCULAR", "SUBCUTANEOUS", "INHALED",
    "TRANSDERMAL", "INTRANASAL", "OCULAR", "RECTAL", "OTHER",
  ];
  var SEXES = ["FEMALE", "MALE", "INTERSEX", "UNSPECIFIED"];
  var ENDPOINT_TYPES = [
    "PK", "PD", "BIOMARKER", "PHYSIOLOGIC", "CLINICAL", "TIME_TO_EVENT", "SAFETY", "DISEASE_PROGRESSION",
  ];
  var AGGREGATIONS = ["RAW", "LAST", "MEAN", "MEDIAN", "MINIMUM", "MAXIMUM", "AUC", "TIME_TO_EVENT"];
  var MISSINGNESS_RULES = ["EXCLUDE", "REPORT", "IMPUTE_LATER"];
  var ELIGIBILITY_OPERATORS = [
    "EQUALS", "NOT_EQUALS", "GREATER_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN",
    "LESS_THAN_OR_EQUAL", "IN", "NOT_IN", "IS_TRUE", "IS_FALSE",
  ];
  var NUMERIC_OPERATORS = ["GREATER_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN", "LESS_THAN_OR_EQUAL"];
  var MEMBERSHIP_OPERATORS = ["IN", "NOT_IN"];
  var BOOLEAN_OPERATORS = ["IS_TRUE", "IS_FALSE"];

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

  function showInlineError(message) {
    var existing = document.getElementById("inlineErrorBanner");
    if (existing) existing.remove();
    var banner = document.createElement("div");
    banner.id = "inlineErrorBanner";
    banner.className = "error-banner";
    banner.style.marginBottom = "10px";
    banner.innerHTML = "<strong>Error.</strong> " + escapeHtml(message) +
      ' <span style="cursor:pointer;text-decoration:underline;float:right;" id="dismissInlineError">dismiss</span>';
    appMain.insertBefore(banner, appMain.firstChild);
    document.getElementById("dismissInlineError").addEventListener("click", function () {
      banner.remove();
    });
  }

  function renderError(message) {
    appMain.innerHTML = '<div class="error-banner"><strong>Could not open project.</strong><br />' + escapeHtml(message) + "</div>";
    saveBtn.setAttribute("disabled", "disabled");
    validateBtn.setAttribute("disabled", "disabled");
    runBtn.setAttribute("disabled", "disabled");
    exportBtn.setAttribute("disabled", "disabled");
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
    exportBtn.removeAttribute("disabled");
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
      (project.resolved_model && project.resolved_model.physiology_targets.length
        ? '<div class="panel">' +
          '<div class="phead">Physiology states</div>' +
          '<div class="pbody">' +
          '<p style="font-size:10.5px;color:var(--ink-faint);margin:0 0 8px;">Executes the whole population at each declared state (not a partition, unlike arms). Verified target(s) for this model: ' + escapeHtml(project.resolved_model.physiology_targets.join(", ")) + ".</p>" +
          '<table class="arms-table" id="physiologyStatesTable">' +
          "<thead><tr><th>State ID</th><th>Scale factor</th><th>Baseline</th><th></th></tr></thead>" +
          "<tbody>" +
          physiologyStateRowHtml("baseline", 1.0, 0, true) +
          physiologyStateRowHtml("reduced", 0.6, 1, false) +
          "</tbody></table>" +
          '<div class="addrow-btn" id="addPhysiologyStateBtn">+ Add state</div>' +
          '<div style="margin-top:8px;"><span class="btn btn-primary raised" id="runPhysiologyBtn" style="cursor:pointer;">Run physiology comparison</span></div>' +
          '<div id="physiologyRunResult" style="margin-top:8px;"></div>' +
          "</div>" +
          "</div>"
        : "") +
      "</div>" +
      "</div>";

    if (project.resolved_model && project.resolved_model.physiology_targets.length) {
      wirePhysiologyPanel(project);
    }
  }

  function physiologyStateRowHtml(stateId, scaleFactor, idx, isBaseline) {
    return (
      '<tr data-idx="' + idx + '">' +
      '<td><input class="finput mono" style="width:90px" data-field="state_id" value="' + escapeAttr(stateId) + '" /></td>' +
      '<td><input class="finput mono" style="width:70px" data-field="scale_factor" type="number" step="any" value="' + scaleFactor + '" /></td>' +
      '<td style="text-align:center;"><input type="radio" name="physiologyBaseline"' + (isBaseline ? " checked" : "") + " /></td>" +
      '<td class="rm" data-action="remove">&times;</td>' +
      "</tr>"
    );
  }

  function wirePhysiologyPanel(project) {
    var target = project.resolved_model.physiology_targets[0];

    function wireRows() {
      wireRemoveButtons("physiologyStatesTable");
    }
    wireRows();

    document.getElementById("addPhysiologyStateBtn").addEventListener("click", function () {
      var tbody = document.querySelector("#physiologyStatesTable tbody");
      var n = tbody.children.length;
      tbody.insertAdjacentHTML("beforeend", physiologyStateRowHtml("state-" + (n + 1), 1.0, n, false));
      wireRows();
    });

    document.getElementById("runPhysiologyBtn").addEventListener("click", function () {
      var rows = document.querySelectorAll("#physiologyStatesTable tbody tr");
      var states = [];
      var baselineStateId = null;
      rows.forEach(function (row) {
        var stateId = row.querySelector('[data-field="state_id"]').value.trim();
        var scaleFactor = parseFloat(row.querySelector('[data-field="scale_factor"]').value);
        var isBaseline = row.querySelector('input[name="physiologyBaseline"]').checked;
        if (isBaseline) baselineStateId = stateId;
        states.push({
          state_id: stateId,
          target: target,
          scale_factor: scaleFactor,
          unit: "dimensionless",
          purpose: isBaseline ? "baseline" : "declared comparison state",
        });
      });
      var resultBox = document.getElementById("physiologyRunResult");
      if (states.length < 2) {
        resultBox.innerHTML = '<div class="error-banner">At least two states are required.</div>';
        return;
      }
      if (!baselineStateId) {
        resultBox.innerHTML = '<div class="error-banner">Select a baseline state.</div>';
        return;
      }
      resultBox.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Starting&hellip;</span>';
      fetch("/api/physiology/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: state.path, states: states, baseline_state_id: baselineStateId }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "run failed to start"); });
          return r.json();
        })
        .then(function (res) { pollPhysiologyRun(res.run_id, resultBox); })
        .catch(function (err) {
          resultBox.innerHTML = '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
        });
    });
  }

  function pollPhysiologyRun(runId, resultBox) {
    fetch("/api/physiology/run/" + runId)
      .then(function (r) { return r.json(); })
      .then(function (poll) {
        if (poll.status === "running") {
          var lastEvent = poll.events.length ? poll.events[poll.events.length - 1] : null;
          resultBox.innerHTML = '<span style="color:var(--signal-text);font-size:11px;">Running&hellip; ' +
            (lastEvent ? escapeHtml(lastEvent.stage) : "") + "</span>";
          setTimeout(function () { pollPhysiologyRun(runId, resultBox); }, 800);
        } else if (poll.status === "completed") {
          var m = poll.manifest;
          var rows = m.states.map(function (s) {
            return (
              '<div class="prow"><div class="pk">' + escapeHtml(s.state_id) + "</div>" +
              '<div class="pv">scale &times;' + s.override_scale_factor + " &middot; " +
              (s.physiology_state_verified ? '<span style="color:var(--verified)">verified</span>' : '<span style="color:var(--absent)">unverified</span>') +
              "</div></div>"
            );
          }).join("");
          resultBox.innerHTML =
            '<div class="propgrid">' + rows + "</div>" +
            '<p style="font-size:10px;color:var(--ink-faint);margin:8px 0 0;">Run directory: ' + escapeHtml(poll.run_directory) + "<br/>Comparison artifact: " + escapeHtml(m.comparison_id) + "</p>";
        } else {
          resultBox.innerHTML = '<div class="error-banner"><strong>Run failed.</strong><br />' + escapeHtml(poll.error) + "</div>";
        }
      });
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

  function endpointRowHtml(ep, idx) {
    return (
      '<tr data-idx="' + idx + '">' +
      '<td><input class="finput mono" style="width:96px" data-field="endpoint_id" value="' + escapeAttr(ep.endpoint_id) + '" /></td>' +
      '<td><select class="fselect" data-field="endpoint_type">' + selectOptionsHtml(ENDPOINT_TYPES, ep.endpoint_type) + "</select></td>" +
      '<td><input class="finput mono" style="width:130px" data-field="measurement" value="' + escapeAttr(ep.measurement) + '" /></td>' +
      '<td><div class="arms-cell-pair"><input class="finput mono" data-field="window_start_value" type="number" step="any" value="' + ep.time_window.start.value + '" />' +
      '<input class="finput mono" data-field="window_start_unit" value="' + escapeAttr(ep.time_window.start.unit) + '" /></div></td>' +
      '<td><div class="arms-cell-pair"><input class="finput mono" data-field="window_end_value" type="number" step="any" value="' + ep.time_window.end.value + '" />' +
      '<input class="finput mono" data-field="window_end_unit" value="' + escapeAttr(ep.time_window.end.unit) + '" /></div></td>' +
      '<td><select class="fselect" data-field="aggregation">' + selectOptionsHtml(AGGREGATIONS, ep.aggregation) + "</select></td>" +
      '<td><select class="fselect" data-field="missingness_rule">' + selectOptionsHtml(MISSINGNESS_RULES, ep.missingness_rule) + "</select></td>" +
      '<td><input class="finput mono" style="width:110px" data-field="analysis_method" value="' + escapeAttr(ep.analysis_method) + '" /></td>' +
      '<td><input class="finput mono" style="width:60px" data-field="unit" value="' + escapeAttr(ep.unit) + '" /></td>' +
      '<td class="rm" data-action="remove">&times;</td>' +
      "</tr>"
    );
  }

  function eligibilityRowHtml(criterion, idx, group) {
    var raw = "";
    if (criterion.value_kind === "list") raw = criterion.value.join(", ");
    else if (criterion.value_kind === "scientific") raw = criterion.value.value + " " + criterion.value.unit;
    else if (criterion.value_kind === "plain") raw = String(criterion.value);
    var isBoolean = BOOLEAN_OPERATORS.indexOf(criterion.operator) !== -1;
    return (
      '<tr data-idx="' + idx + '" data-group="' + group + '">' +
      '<td><input class="finput mono" style="width:90px" data-field="criterion_id" value="' + escapeAttr(criterion.criterion_id) + '" /></td>' +
      '<td><input class="finput mono" style="width:110px" data-field="field_path" value="' + escapeAttr(criterion.field_path) + '" placeholder="e.g. age.value" /></td>' +
      '<td><select class="fselect" data-field="operator">' + selectOptionsHtml(ELIGIBILITY_OPERATORS, criterion.operator) + "</select></td>" +
      '<td><input class="finput mono" style="width:110px" data-field="value" value="' + escapeAttr(raw) + '" ' + (isBoolean ? "disabled" : "") +
      ' placeholder="numeric: 18 year &middot; list: a, b &middot; text: value" /></td>' +
      '<td><input class="finput mono" style="width:130px" data-field="description" value="' + escapeAttr(criterion.description || "") + '" /></td>' +
      '<td class="rm" data-action="remove">&times;</td>' +
      "</tr>"
    );
  }

  function windowRowHtml(w, idx) {
    return (
      '<tr data-idx="' + idx + '">' +
      '<td><div class="arms-cell-pair"><input class="finput mono" data-field="start_value" type="number" step="any" value="' + w.start.value + '" />' +
      '<input class="finput mono" data-field="start_unit" value="' + escapeAttr(w.start.unit) + '" /></div></td>' +
      '<td><div class="arms-cell-pair"><input class="finput mono" data-field="end_value" type="number" step="any" value="' + w.end.value + '" />' +
      '<input class="finput mono" data-field="end_unit" value="' + escapeAttr(w.end.unit) + '" /></div></td>' +
      '<td><div class="arms-cell-pair"><input class="finput mono" data-field="interval_value" type="number" step="any" value="' + w.interval.value + '" />' +
      '<input class="finput mono" data-field="interval_unit" value="' + escapeAttr(w.interval.unit) + '" /></div></td>' +
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
    var endpointRows = project.endpoints.map(endpointRowHtml).join("");
    var inclusionRows = project.eligibility.inclusion.map(function (c, i) { return eligibilityRowHtml(c, i, "inclusion"); }).join("");
    var exclusionRows = project.eligibility.exclusion.map(function (c, i) { return eligibilityRowHtml(c, i, "exclusion"); }).join("");
    var evidenceTags = project.evidence_ids.map(function (id) {
      return '<span class="tag" style="margin:2px 4px 2px 0;">' + escapeHtml(id) + "</span>";
    }).join("") || '<span style="color:var(--ink-faint);font-size:11px;">none attached</span>';

    var schedule = project.observation_schedule;
    var windowRows = schedule ? schedule.windows.map(windowRowHtml).join("") : "";

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
      '<div class="panel">' +
      '<div class="phead"><span>Endpoints</span><span>' + project.endpoints.length + " endpoint(s)</span></div>" +
      '<div class="pbody">' +
      '<div style="overflow-x:auto"><table class="arms-table" id="endpointsTable">' +
      "<thead><tr><th>ID</th><th>Type</th><th>Measurement</th><th>Window start</th><th>Window end</th><th>Aggregation</th><th>Missingness</th><th>Analysis method</th><th>Unit</th><th></th></tr></thead>" +
      "<tbody>" + endpointRows + "</tbody>" +
      "</table></div>" +
      '<div class="addrow-btn" id="addEndpointBtn">+ Add endpoint</div>' +
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
      '<div class="phead"><span>Observation schedule</span></div>' +
      '<div class="pbody">' +
      '<label class="fcheck"><input type="checkbox" id="scheduleEnabled"' + (schedule ? " checked" : "") + " /> Declare a sample-collection timeline</label>" +
      '<p style="font-size:10px;color:var(--ink-faint);margin:4px 0 8px;">Only honored for multi-arm (two or more arms) execution. Leave unchecked to use the solver\'s default output grid.</p>' +
      '<div id="scheduleFields" style="display:' + (schedule ? "block" : "none") + ';">' +
      '<div class="field"><span class="flabel">Schedule ID</span><input class="finput" id="scheduleId" value="' + (schedule ? escapeAttr(schedule.schedule_id) : "sampling-schedule") + '" /></div>' +
      '<div class="field"><span class="flabel">Time unit</span><input class="finput" id="scheduleTimeUnit" value="' + (schedule ? escapeAttr(schedule.time_unit) : "min") + '" /></div>' +
      '<div style="overflow-x:auto"><table class="arms-table" id="scheduleWindowsTable">' +
      "<thead><tr><th>Start</th><th>End</th><th>Interval</th><th></th></tr></thead>" +
      "<tbody>" + windowRows + "</tbody>" +
      "</table></div>" +
      '<div class="addrow-btn" id="addWindowBtn">+ Add sampling window</div>' +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead"><span>Eligibility &mdash; inclusion</span></div>' +
      '<div class="pbody">' +
      '<div style="overflow-x:auto"><table class="arms-table" id="inclusionTable">' +
      "<thead><tr><th>ID</th><th>Field path</th><th>Operator</th><th>Value</th><th>Description</th><th></th></tr></thead>" +
      "<tbody>" + inclusionRows + "</tbody>" +
      "</table></div>" +
      '<div class="addrow-btn" id="addInclusionBtn">+ Add inclusion criterion</div>' +
      "</div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead"><span>Eligibility &mdash; exclusion</span></div>' +
      '<div class="pbody">' +
      '<div style="overflow-x:auto"><table class="arms-table" id="exclusionTable">' +
      "<thead><tr><th>ID</th><th>Field path</th><th>Operator</th><th>Value</th><th>Description</th><th></th></tr></thead>" +
      "<tbody>" + exclusionRows + "</tbody>" +
      "</table></div>" +
      '<div class="addrow-btn" id="addExclusionBtn">+ Add exclusion criterion</div>' +
      "</div>" +
      "</div>" +
      '<div class="panel">' +
      '<div class="phead">Attached evidence</div>' +
      '<div class="pbody">' + evidenceTags +
      '<p style="font-size:10.5px;color:var(--ink-faint);margin:8px 0 0;">Attach a real evidence connector ID from the Evidence Browser. Editing here is not yet supported &mdash; use the Evidence pane\'s "Attach to open trial" action.</p>' +
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

    document.getElementById("addEndpointBtn").addEventListener("click", function () {
      var tbody = document.querySelector("#endpointsTable tbody");
      var n = tbody.children.length;
      var template = {
        endpoint_id: "endpoint-" + (n + 1),
        endpoint_type: "PK",
        measurement: "plasma concentration",
        time_window: { start: { value: 0, unit: "hour" }, end: { value: 24, unit: "hour" } },
        aggregation: "RAW",
        missingness_rule: "REPORT",
        analysis_method: "PK endpoints",
        unit: "mg/L",
      };
      tbody.insertAdjacentHTML("beforeend", endpointRowHtml(template, n));
      wireRemoveButtons("endpointsTable");
    });

    document.getElementById("addInclusionBtn").addEventListener("click", function () { addEligibilityRow("inclusionTable", "inclusion"); });
    document.getElementById("addExclusionBtn").addEventListener("click", function () { addEligibilityRow("exclusionTable", "exclusion"); });

    document.getElementById("scheduleEnabled").addEventListener("change", function (e) {
      document.getElementById("scheduleFields").style.display = e.target.checked ? "block" : "none";
    });
    document.getElementById("addWindowBtn").addEventListener("click", function () {
      var tbody = document.querySelector("#scheduleWindowsTable tbody");
      var n = tbody.children.length;
      var template = { start: { value: 0, unit: "min" }, end: { value: 60, unit: "min" }, interval: { value: 15, unit: "min" } };
      tbody.insertAdjacentHTML("beforeend", windowRowHtml(template, n));
      wireRemoveButtons("scheduleWindowsTable");
    });
    wireRemoveButtons("scheduleWindowsTable");

    wireRemoveButtons("endpointsTable");
    wireEligibilityTable("inclusionTable");
    wireEligibilityTable("exclusionTable");
  }

  function addEligibilityRow(tableId, group) {
    var tbody = document.querySelector("#" + tableId + " tbody");
    var n = tbody.children.length;
    var template = {
      criterion_id: group + "-" + (n + 1),
      field_path: "age.value",
      operator: "GREATER_THAN_OR_EQUAL",
      value_kind: "scientific",
      value: { value: 18, unit: "year" },
      description: "",
    };
    tbody.insertAdjacentHTML("beforeend", eligibilityRowHtml(template, n, group));
    wireEligibilityTable(tableId);
  }

  function wireRemoveButtons(tableId) {
    var table = document.getElementById(tableId);
    if (!table) return;
    table.querySelectorAll('[data-action="remove"]').forEach(function (cell) {
      cell.onclick = function () { cell.closest("tr").remove(); };
    });
  }

  function wireEligibilityTable(tableId) {
    wireRemoveButtons(tableId);
    var table = document.getElementById(tableId);
    if (!table) return;
    table.querySelectorAll('select[data-field="operator"]').forEach(function (sel) {
      sel.onchange = function () {
        var valueInput = sel.closest("tr").querySelector('[data-field="value"]');
        valueInput.disabled = BOOLEAN_OPERATORS.indexOf(sel.value) !== -1;
      };
    });
  }

  function wireArmsTable() {
    var table = document.getElementById("armsTable");
    if (!table) return;
    wireRemoveButtons("armsTable");
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

    edits.trial.endpoints = [];
    document.querySelectorAll("#endpointsTable tbody tr").forEach(function (row) {
      var field = function (name) { return row.querySelector('[data-field="' + name + '"]').value; };
      edits.trial.endpoints.push({
        endpoint_id: field("endpoint_id"),
        endpoint_type: field("endpoint_type"),
        measurement: field("measurement"),
        time_window: {
          start: { value: parseFloat(field("window_start_value")), unit: field("window_start_unit"), value_type: "ASSUMED" },
          end: { value: parseFloat(field("window_end_value")), unit: field("window_end_unit"), value_type: "ASSUMED" },
        },
        aggregation: field("aggregation"),
        missingness_rule: field("missingness_rule"),
        analysis_method: field("analysis_method"),
        unit: field("unit"),
      });
    });

    edits.trial.eligibility = {
      inclusion: collectEligibilityRows("inclusionTable"),
      exclusion: collectEligibilityRows("exclusionTable"),
    };

    if (document.getElementById("scheduleEnabled").checked) {
      var windows = [];
      document.querySelectorAll("#scheduleWindowsTable tbody tr").forEach(function (row) {
        var field = function (name) { return row.querySelector('[data-field="' + name + '"]').value; };
        windows.push({
          start: { value: parseFloat(field("start_value")), unit: field("start_unit"), value_type: "ASSUMED" },
          end: { value: parseFloat(field("end_value")), unit: field("end_unit"), value_type: "ASSUMED" },
          interval: { value: parseFloat(field("interval_value")), unit: field("interval_unit"), value_type: "ASSUMED" },
        });
      });
      edits.trial.observation_schedule = {
        schedule_id: document.getElementById("scheduleId").value.trim() || "sampling-schedule",
        time_unit: document.getElementById("scheduleTimeUnit").value.trim() || "min",
        windows: windows,
      };
    } else {
      edits.trial.observation_schedule = null;
    }

    return edits;
  }

  function collectEligibilityRows(tableId) {
    var criteria = [];
    document.querySelectorAll("#" + tableId + " tbody tr").forEach(function (row) {
      var field = function (name) { return row.querySelector('[data-field="' + name + '"]').value; };
      var operator = field("operator");
      var rawValue = field("value").trim();
      var value = null;
      if (BOOLEAN_OPERATORS.indexOf(operator) !== -1) {
        value = null;
      } else if (NUMERIC_OPERATORS.indexOf(operator) !== -1) {
        var parts = rawValue.split(/\s+/);
        value = { value: parseFloat(parts[0]), unit: parts.slice(1).join(" ") || "dimensionless", value_type: "ASSUMED" };
      } else if (MEMBERSHIP_OPERATORS.indexOf(operator) !== -1) {
        value = rawValue.split(",").map(function (s) { return s.trim(); }).filter(function (s) { return s.length; });
      } else {
        value = rawValue;
      }
      var description = field("description");
      criteria.push({
        criterion_id: field("criterion_id"),
        field_path: field("field_path"),
        operator: operator,
        value: value,
        description: description || null,
      });
    });
    return criteria;
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
    var hasLiveResult = state.lastRunId && state.lastRunPoll && state.lastRunPoll.status === "completed";

    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Results</h3><div class="sub">Live run results, or browse any past run on disk</div></div></div>' +
      '<div class="panel"><div class="phead"><span>Past runs</span><input class="finput mono" id="runsOutputRoot" style="width:220px;display:inline-block;padding:3px 6px;" value="runs" /></div>' +
      '<div class="pbody" id="pastRunsList"><span style="color:var(--ink-faint);font-size:11px;">Loading&hellip;</span></div></div>' +
      '<div id="resultsBody" style="margin-top:10px;"></div>';

    if (hasLiveResult) {
      loadResultsData(
        "/api/run/" + encodeURIComponent(state.lastRunId) + "/data",
        "/api/run/" + encodeURIComponent(state.lastRunId) + "/report.html",
        state.lastRunPoll.run_directory,
        state.lastRunId
      );
    } else {
      document.getElementById("resultsBody").innerHTML = '<div class="empty-state">Select a run below, or use Run in the toolbar, to see results.</div>';
    }

    var loadRuns = function () {
      var outputRoot = document.getElementById("runsOutputRoot").value.trim() || "runs";
      var list = document.getElementById("pastRunsList");
      list.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Loading&hellip;</span>';
      fetch("/api/runs?output_root=" + encodeURIComponent(outputRoot))
        .then(function (r) { return r.json(); })
        .then(function (runs) {
          if (!runs.length) {
            list.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">No runs found under this output root.</span>';
            return;
          }
          list.innerHTML = runs.map(function (r) {
            return (
              '<div class="prow" style="cursor:pointer;" data-run-directory="' + escapeAttr(r.run_directory) + '">' +
              '<div class="pk">' + escapeHtml(r.kind) + "</div>" +
              '<div class="pv mono">' + escapeHtml(r.run_id) + " &middot; " + escapeHtml(r.modified_at) + "</div>" +
              "</div>"
            );
          }).join("");
          list.querySelectorAll("[data-run-directory]").forEach(function (row) {
            row.addEventListener("click", function () {
              var dir = row.dataset.runDirectory;
              loadResultsData(
                "/api/runs/data?run_directory=" + encodeURIComponent(dir),
                "/api/runs/report.html?run_directory=" + encodeURIComponent(dir),
                dir,
                null
              );
            });
          });
        });
    };
    document.getElementById("runsOutputRoot").addEventListener("change", loadRuns);
    loadRuns();
  }

  function loadResultsData(dataUrl, reportUrl, label, runId) {
    var body = document.getElementById("resultsBody");
    if (!body) return;
    body.innerHTML = '<div class="empty-state">Loading&hellip;</div>';
    fetch(dataUrl)
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not load results"); });
        return r.json();
      })
      .then(function (data) { renderNativeResults(data, reportUrl, label, runId); })
      .catch(function (err) {
        body.innerHTML = '<div class="error-banner"><strong>Could not load results.</strong><br />' + escapeHtml(err.message) + "</div>";
      });
  }

  function renderNativeResults(data, reportUrl, label, runId) {
    var body = document.getElementById("resultsBody");

    var endpointRows = data.endpoints.map(function (e) {
      return (
        '<tr><td>' + escapeHtml(e.arm_id || "&mdash;") + "</td><td>" + escapeHtml(e.endpoint_type) + "</td>" +
        "<td>" + e.n + "</td><td class=\"mono\">" + e.mean.toPrecision(5) + "</td>" +
        "<td class=\"mono\">" + (e.sample_standard_deviation !== null ? e.sample_standard_deviation.toPrecision(4) : "&mdash;") + "</td>" +
        "<td class=\"mono\">" + e.minimum.toPrecision(4) + "</td><td class=\"mono\">" + e.maximum.toPrecision(4) + "</td>" +
        "<td>" + escapeHtml(e.unit) + "</td></tr>"
      );
    }).join("");

    var comparisonRows = data.comparisons.map(function (c) {
      return (
        '<tr><td>' + escapeHtml(c.arm_a_id) + " vs " + escapeHtml(c.arm_b_id) + "</td><td>" + escapeHtml(c.endpoint_type) + "</td>" +
        "<td class=\"mono\">" + c.arm_a_mean.toPrecision(4) + "</td><td class=\"mono\">" + c.arm_b_mean.toPrecision(4) + "</td>" +
        "<td class=\"mono\">" + c.absolute_difference.toPrecision(4) + "</td>" +
        "<td class=\"mono\">" + (c.relative_difference !== null ? (c.relative_difference * 100).toFixed(1) + "%" : "&mdash;") + "</td>" +
        "<td>" + escapeHtml(c.unit) + "</td></tr>"
      );
    }).join("");

    var chartHtml = data.concentration_time_series.length
      ? concentrationTimeChartSvg(data.concentration_time_series)
      : '<span style="color:var(--ink-faint);font-size:11px;">No concentration-time series in this report.</span>';

    body.innerHTML =
      '<div class="panel"><div class="phead">Concentration-time</div><div class="pbody">' + chartHtml + "</div></div>" +
      '<div class="panel"><div class="phead">Endpoint summary</div><div class="pbody"><div style="overflow-x:auto"><table class="arms-table">' +
      "<thead><tr><th>Arm</th><th>Type</th><th>n</th><th>Mean</th><th>SD</th><th>Min</th><th>Max</th><th>Unit</th></tr></thead>" +
      "<tbody>" + (endpointRows || '<tr><td colspan="8">no endpoints</td></tr>') + "</tbody>" +
      "</table></div></div></div>" +
      (data.comparisons.length
        ? '<div class="panel"><div class="phead">Arm comparisons</div><div class="pbody"><div style="overflow-x:auto"><table class="arms-table">' +
          "<thead><tr><th>Arms</th><th>Type</th><th>A mean</th><th>B mean</th><th>Abs. diff.</th><th>Rel. diff.</th><th>Unit</th></tr></thead>" +
          "<tbody>" + comparisonRows + "</tbody></table></div></div></div>"
        : "") +
      (runId && data.arms.length === 1 ? cohortPanelHtml() : "") +
      (runId ? registerExperimentPanelHtml() : "") +
      '<div class="panel"><div class="phead"><span>Full formatted report</span>' +
      '<span><a href="' + reportUrl + '" download="report.html" style="color:var(--signal-text);margin-right:10px;">Download HTML</a>' +
      '<a href="' + reportUrl.replace("report.html", "report.md") + '" download="report.md" style="color:var(--signal-text);">Download Markdown</a></span></div>' +
      '<div class="pbody">' +
      '<span style="font-size:10px;color:var(--ink-faint);display:block;margin-bottom:6px;">' + escapeHtml(label) + "</span>" +
      '<iframe src="' + reportUrl + '" style="width:100%;height:50vh;border:1px solid var(--border);background:var(--white);"></iframe>' +
      "</div></div>";

    if (runId) wireRegisterExperimentPanel(runId);
    if (runId && data.arms.length === 1) {
      wireCohortPanel(runId);
    }
  }

  function registerExperimentPanelHtml() {
    return (
      '<div class="panel"><div class="phead">Register as Registry experiment</div><div class="pbody">' +
      '<p style="font-size:10.5px;color:var(--ink-faint);margin:0 0 8px;">Records this run\'s trial protocol in the local Registry for later reuse/forking. Always registered as evidence_class=SIMULATED -- a simulated outcome is never promoted to measured evidence.</p>' +
      '<div class="field"><span class="flabel">Title</span><input class="finput" id="experimentTitle" /></div>' +
      '<div class="field"><span class="flabel">Summary (optional)</span><input class="finput" id="experimentSummary" /></div>' +
      '<div class="field"><span class="flabel">License</span><input class="finput" id="experimentLicense" value="internal" /></div>' +
      '<span class="btn btn-primary raised" id="registerExperimentBtn" style="cursor:pointer;">Register experiment</span>' +
      '<div id="registerExperimentResult" style="margin-top:8px;"></div>' +
      "</div></div>"
    );
  }

  function wireRegisterExperimentPanel(runId) {
    var btn = document.getElementById("registerExperimentBtn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var title = document.getElementById("experimentTitle").value.trim();
      var summary = document.getElementById("experimentSummary").value.trim();
      var license = document.getElementById("experimentLicense").value.trim();
      var resultBox = document.getElementById("registerExperimentResult");
      if (!title || !license) {
        resultBox.innerHTML = '<div class="error-banner">Title and license are required.</div>';
        return;
      }
      resultBox.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Registering&hellip;</span>';
      fetch("/api/run/" + encodeURIComponent(runId) + "/register-experiment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title, summary: summary || null, license: license }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "registration failed"); });
          return r.json();
        })
        .then(function (manifest) {
          resultBox.innerHTML = '<span style="color:var(--verified);font-size:11px;">Registered as ' + escapeHtml(manifest.logical_id) + " (" + escapeHtml(manifest.evidence_class) + "). See the Registry pane.</span>";
        })
        .catch(function (err) {
          resultBox.innerHTML = '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
        });
    });
  }

  function cohortPanelHtml() {
    return (
      '<div class="panel"><div class="phead">Cohort comparison</div><div class="pbody">' +
      '<p style="font-size:10.5px;color:var(--ink-faint);margin:0 0 8px;">Define two cohorts from this run\'s own population by demographic predicate, then compare their PK endpoint outcomes. Strict lineage-based matching, not subject_id text.</p>' +
      '<table class="arms-table" id="cohortDefTable">' +
      "<thead><tr><th>Label</th><th>Field</th><th>Operator</th><th>Value</th><th>Unit</th></tr></thead>" +
      "<tbody>" +
      cohortRowHtml("younger", "demographics.age", "LT", 40, "year") +
      cohortRowHtml("older", "demographics.age", "GTE", 40, "year") +
      "</tbody></table>" +
      '<div style="margin-top:8px;"><span class="btn btn-primary raised" id="compareCohortsBtn" style="cursor:pointer;">Define &amp; compare cohorts</span></div>' +
      '<div id="cohortResult" style="margin-top:8px;"></div>' +
      "</div></div>"
    );
  }

  function cohortRowHtml(label, fieldId, operator, value, unit) {
    var numericOps = ["LT", "LTE", "GT", "GTE", "EQ"];
    return (
      '<tr>' +
      '<td><input class="finput mono" style="width:80px" data-field="label" value="' + escapeAttr(label) + '" /></td>' +
      '<td><input class="finput mono" style="width:110px" data-field="field_id" value="' + escapeAttr(fieldId) + '" /></td>' +
      '<td><select class="fselect" data-field="operator">' + selectOptionsHtml(numericOps, operator) + "</select></td>" +
      '<td><input class="finput mono" style="width:60px" data-field="value" type="number" step="any" value="' + value + '" /></td>' +
      '<td><input class="finput mono" style="width:60px" data-field="unit" value="' + escapeAttr(unit) + '" /></td>' +
      "</tr>"
    );
  }

  function wireCohortPanel(runId) {
    document.getElementById("compareCohortsBtn").addEventListener("click", function () {
      var rows = document.querySelectorAll("#cohortDefTable tbody tr");
      var cohorts = [];
      rows.forEach(function (row) {
        var field = function (name) { return row.querySelector('[data-field="' + name + '"]').value; };
        cohorts.push({
          label: field("label"),
          predicates: [
            {
              type: "numeric",
              field_id: field("field_id"),
              operator: field("operator"),
              value: parseFloat(field("value")),
              unit: field("unit"),
            },
          ],
        });
      });
      var resultBox = document.getElementById("cohortResult");
      resultBox.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Defining cohorts&hellip;</span>';
      fetch("/api/run/" + encodeURIComponent(runId) + "/cohorts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cohorts: cohorts }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "cohort definition failed"); });
          return r.json();
        })
        .then(function (defined) {
          if (defined.cohorts.length !== 2) throw new Error("expected exactly two cohorts");
          resultBox.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Comparing&hellip;</span>';
          return fetch("/api/run/" + encodeURIComponent(runId) + "/cohorts/compare", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              group_a_membership_id: defined.cohorts[0].membership_id,
              group_b_membership_id: defined.cohorts[1].membership_id,
              group_a_label: defined.cohorts[0].label,
              group_b_label: defined.cohorts[1].label,
            }),
          });
        })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "cohort comparison failed"); });
          return r.json();
        })
        .then(function (result) {
          var rows = result.comparisons.map(function (c) {
            return (
              '<tr><td>' + escapeHtml(c.endpoint_type) + "</td>" +
              "<td class=\"mono\">" + c.group_a_mean.toPrecision(4) + "</td>" +
              "<td class=\"mono\">" + c.group_b_mean.toPrecision(4) + "</td>" +
              "<td class=\"mono\">" + c.absolute_difference.toPrecision(4) + "</td>" +
              "<td class=\"mono\">" + (c.relative_difference !== null ? (c.relative_difference * 100).toFixed(1) + "%" : "&mdash;") + "</td>" +
              "<td>" + escapeHtml(c.unit) + "</td></tr>"
            );
          }).join("");
          resultBox.innerHTML =
            '<p style="font-size:10.5px;color:var(--ink-soft);margin:0 0 6px;">' + escapeHtml(result.group_a_label) + " (n=" + result.overlap.group_a_n + ") vs " +
            escapeHtml(result.group_b_label) + " (n=" + result.overlap.group_b_n + ")</p>" +
            '<table class="arms-table"><thead><tr><th>Type</th><th>A mean</th><th>B mean</th><th>Abs. diff.</th><th>Rel. diff.</th><th>Unit</th></tr></thead><tbody>' +
            rows + "</tbody></table>";
        })
        .catch(function (err) {
          resultBox.innerHTML = '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
        });
    });
  }

  function concentrationTimeChartSvg(series) {
    var width = 640, height = 240, padL = 46, padB = 28, padT = 10, padR = 12;
    var allPoints = series.reduce(function (acc, s) { return acc.concat(s.points); }, []);
    var xs = allPoints.map(function (p) { return p[0]; });
    var ys = allPoints.map(function (p) { return p[1]; });
    var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
    var yMin = 0, yMax = Math.max.apply(null, ys) * 1.08 || 1;
    var xScale = function (x) { return padL + (xMax > xMin ? (x - xMin) / (xMax - xMin) : 0) * (width - padL - padR); };
    var yScale = function (y) { return height - padB - (yMax > yMin ? (y - yMin) / (yMax - yMin) : 0) * (height - padT - padB); };
    var colors = ["var(--signal)", "var(--verified)", "var(--pending)", "var(--absent)"];

    var paths = series.map(function (s, i) {
      var d = s.points.map(function (p, idx) {
        return (idx === 0 ? "M" : "L") + xScale(p[0]).toFixed(1) + "," + yScale(p[1]).toFixed(1);
      }).join(" ");
      return '<path d="' + d + '" fill="none" stroke="' + colors[i % colors.length] + '" stroke-width="1.6" />';
    }).join("");

    var legend = series.map(function (s, i) {
      return '<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:10px;color:var(--ink-soft);">' +
        '<span style="width:9px;height:9px;background:' + colors[i % colors.length] + ';display:inline-block;"></span>' +
        escapeHtml(s.label) + "</span>";
    }).join("");

    var yTicks = [0, 0.25, 0.5, 0.75, 1].map(function (f) {
      var val = yMin + f * (yMax - yMin);
      var y = yScale(val);
      return '<line x1="' + padL + '" y1="' + y + '" x2="' + (width - padR) + '" y2="' + y + '" stroke="var(--border-soft)" stroke-width="1" />' +
        '<text x="' + (padL - 6) + '" y="' + (y + 3) + '" text-anchor="end" font-size="9" fill="var(--ink-faint)">' + val.toPrecision(3) + "</text>";
    }).join("");

    var xLabel = series[0].time_unit, yLabel = series[0].unit;

    return (
      '<div style="margin-bottom:6px;">' + legend + "</div>" +
      '<svg viewBox="0 0 ' + width + " " + height + '" style="width:100%;max-width:' + width + 'px;height:auto;font-family:&quot;PT Sans&quot;,sans-serif;">' +
      yTicks +
      '<line x1="' + padL + '" y1="' + (height - padB) + '" x2="' + (width - padR) + '" y2="' + (height - padB) + '" stroke="var(--ink-faint)" stroke-width="1" />' +
      paths +
      '<text x="' + (width / 2) + '" y="' + (height - 4) + '" text-anchor="middle" font-size="9" fill="var(--ink-faint)">time (' + escapeHtml(xLabel) + ")</text>" +
      '<text x="12" y="' + (padT + 8) + '" font-size="9" fill="var(--ink-faint)">' + escapeHtml(yLabel) + "</text>" +
      "</svg>"
    );
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
      '<div class="app-topbar"><div><h3>Evidence</h3><div class="sub">Registered external-evidence connectors' +
      (state.project ? " &middot; open trial: " + escapeHtml(state.project.trial_id) : " &middot; no project open (run only, cannot attach)") + "</div></div></div>" +
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
            var actionCell = row.querySelector("td:last-child");
            outcomeCell.textContent = "Running…";
            fetch("/api/evidence/" + encodeURIComponent(connectorId) + "/run", { method: "POST" })
              .then(function (r) { return r.json(); })
              .then(function (result) {
                if (result.eligible) {
                  outcomeCell.innerHTML =
                    '<span class="role-tag role-ok">' + escapeHtml(result.role) + "</span> " +
                    result.observation_count + " observation(s) &middot; " + escapeHtml(result.license);
                  if (state.project) {
                    var attachBtn = document.createElement("span");
                    attachBtn.className = "btn raised";
                    attachBtn.style.cursor = "pointer";
                    attachBtn.style.marginLeft = "6px";
                    attachBtn.textContent = "Attach to open trial";
                    attachBtn.addEventListener("click", function () { attachEvidence(connectorId, attachBtn); });
                    actionCell.appendChild(attachBtn);
                  }
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

  function attachEvidence(connectorId, buttonEl) {
    if (!state.project || !state.path) return;
    buttonEl.textContent = "Ingesting & attaching…";
    buttonEl.setAttribute("disabled", "disabled");
    fetch("/api/evidence/" + encodeURIComponent(connectorId) + "/attach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.path }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "attach failed"); });
        return r.json();
      })
      .then(function (project) {
        state.project = project;
        var newId = project.evidence_ids[project.evidence_ids.length - 1];
        buttonEl.textContent = "Attached (" + newId + ")";
        statusState.textContent = "Evidence ingested, persisted, and attached to the open trial";
      })
      .catch(function (err) {
        buttonEl.textContent = "Attach failed";
        buttonEl.removeAttribute("disabled");
        showInlineError(err.message);
      });
  }

  // ================= Curation pane =================

  function renderCuration() {
    state.activePane = "curation";
    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Curation</h3><div class="sub">Connector output &rarr; reviewed, evidence-classed Registry record</div></div></div>' +
      '<div class="panel"><div class="phead">Run a connector for curation</div><div class="pbody" id="curationConnectors"><span style="color:var(--ink-faint);font-size:11px;">Loading&hellip;</span></div></div>' +
      '<div class="panel"><div class="phead">Candidates</div><div class="pbody" id="curationCandidates"></div></div>' +
      '<div class="panel"><div class="phead">Ineligible (connector declined)</div><div class="pbody" id="curationIneligible"></div></div>' +
      '<div id="curationReview" style="margin-top:10px;"></div>' +
      '<div class="app-topbar" style="margin-top:16px;"><div><h3>Parameter evidence</h3><div class="sub">Real, individually-cited PK/PD parameter values &mdash; no bulk import, every value manually sourced and reviewed</div></div></div>' +
      '<div class="panel"><div class="phead">Propose a value</div><div class="pbody" id="parameterEvidencePropose"></div></div>' +
      '<div class="panel"><div class="phead">Candidates</div><div class="pbody" id="parameterEvidenceCandidates"></div></div>' +
      '<div id="parameterEvidenceReview" style="margin-top:10px;"></div>';

    fetch("/api/evidence").then(function (r) { return r.json(); }).then(function (connectors) {
      var box = document.getElementById("curationConnectors");
      box.innerHTML = connectors.map(function (c) {
        return (
          '<div class="param-row"><span class="mono">' + escapeHtml(c.connector_id) + "</span>" +
          '<span class="btn raised run-curation-connector" data-connector="' + escapeAttr(c.connector_id) + '" style="cursor:pointer;margin-left:auto;">Run</span></div>'
        );
      }).join("");
      box.querySelectorAll(".run-curation-connector").forEach(function (btn) {
        btn.addEventListener("click", function () {
          btn.textContent = "Running…";
          fetch("/api/curation/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ connector_id: btn.dataset.connector }),
          })
            .then(function (r) {
              if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "run failed"); });
              return r.json();
            })
            .then(function (result) {
              btn.textContent = "Run";
              loadCurationLists();
              if (!result.eligible) showInlineError("Connector declined this candidate: " + result.reason);
            })
            .catch(function (err) {
              btn.textContent = "Failed";
              showInlineError(err.message);
            });
        });
      });
    });

    loadCurationLists();
    renderParameterEvidenceProposeForm();
    loadParameterEvidenceCandidates();
  }

  function loadCurationLists() {
    fetch("/api/curation/candidates").then(function (r) { return r.json(); }).then(function (candidates) {
      var box = document.getElementById("curationCandidates");
      box.innerHTML = candidates.length
        ? candidates.map(function (c) {
            var statusClass = c.outcome === "ACCEPTED" ? "verified" : c.outcome === "REJECTED" ? "absent" : "pending";
            return (
              '<div class="param-row" style="cursor:pointer;" data-candidate="' + escapeAttr(c.candidate_id) + '">' +
              '<span class="sq ' + statusClass + '"></span>' +
              '<span class="mono">' + escapeHtml(c.dataset.dataset_id) + "</span>" +
              '<span style="margin-left:auto;">' + escapeHtml(c.outcome) + "</span></div>"
            );
          }).join("")
        : '<div class="empty-state">No candidates yet.</div>';
      box.querySelectorAll("[data-candidate]").forEach(function (row) {
        row.addEventListener("click", function () { renderCurationReview(row.dataset.candidate); });
      });
    });

    fetch("/api/curation/ineligible").then(function (r) { return r.json(); }).then(function (records) {
      var box = document.getElementById("curationIneligible");
      box.innerHTML = records.length
        ? records.map(function (r) {
            return (
              '<div class="param-row"><span class="mono">' + escapeHtml(r.connector_id) + "</span></div>" +
              '<div class="ec-body" style="padding-left:0;margin-bottom:8px;">' + escapeHtml(r.reason) + "</div>"
            );
          }).join("")
        : '<div class="empty-state">None.</div>';
    });
  }

  function renderCurationReview(candidateId) {
    var container = document.getElementById("curationReview");
    container.innerHTML =
      '<div class="panel"><div class="phead">Review candidate</div><div class="pbody" id="curationReviewBody-' + candidateId + '"></div></div>' +
      '<div class="panel"><div class="phead">Validation checklist</div><div class="pbody" id="curationChecklist-' + candidateId + '"></div></div>';
    refreshCurationCandidate(candidateId);
  }

  function refreshCurationCandidate(candidateId) {
    fetch("/api/curation/candidate/" + candidateId)
      .then(function (r) { return r.json(); })
      .then(function (candidate) {
        renderCurationReviewBody(candidate);
        return fetch("/api/curation/candidate/" + candidateId + "/checklist");
      })
      .then(function (r) { return r.json(); })
      .then(function (checklist) { renderCurationChecklist(candidateId, checklist); });
  }

  function renderCurationChecklist(candidateId, checklist) {
    var body = document.getElementById("curationChecklist-" + candidateId);
    if (!body) return;
    var rungs = checklist.checks.map(function (c) {
      return (
        '<div class="rung"><span class="sq ' + c.status + '"></span>' +
        '<span class="txt"><strong>' + escapeHtml(c.label) + "</strong><span>" + escapeHtml(c.detail) + "</span></span></div>"
      );
    }).join("");
    body.innerHTML =
      '<div class="status-ladder">' + rungs + "</div>" +
      '<div style="margin-top:10px;display:flex;gap:8px;">' +
      '<span class="btn btn-primary raised" id="acceptBtn-' + candidateId + '" style="cursor:pointer;" ' + (checklist.ok ? "" : 'aria-disabled="true"') + ">Accept &amp; register</span>" +
      '<span class="btn raised" id="rejectBtn-' + candidateId + '" style="cursor:pointer;">Reject</span>' +
      "</div>" +
      '<div id="curationAcceptResult-' + candidateId + '" style="margin-top:8px;"></div>';

    var acceptBtn = document.getElementById("acceptBtn-" + candidateId);
    if (checklist.ok) {
      acceptBtn.addEventListener("click", function () {
        var out = document.getElementById("curationAcceptResult-" + candidateId);
        out.innerHTML = "Accepting…";
        fetch("/api/curation/candidate/" + candidateId + "/accept", { method: "POST" })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "accept failed"); });
            return r.json();
          })
          .then(function (result) {
            out.innerHTML = '<div class="hash-line"><span class="k">Registered</span><span class="v mono">' + escapeHtml(result.record_id) + "</span></div>";
            loadCurationLists();
          })
          .catch(function (err) {
            out.innerHTML = '<div class="error-banner"><strong>Accept failed.</strong><br />' + escapeHtml(err.message) + "</div>";
          });
      });
    } else {
      acceptBtn.style.opacity = "0.5";
      acceptBtn.style.cursor = "default";
    }

    document.getElementById("rejectBtn-" + candidateId).addEventListener("click", function () {
      var reason = window.prompt("Reason for rejecting this candidate:");
      if (!reason) return;
      fetch("/api/curation/candidate/" + candidateId + "/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason }),
      })
        .then(function (r) { return r.json(); })
        .then(function () { loadCurationLists(); refreshCurationCandidate(candidateId); });
    });
  }

  function renderCurationReviewBody(candidate) {
    var candidateId = candidate.candidate_id;
    var body = document.getElementById("curationReviewBody-" + candidateId);
    if (!body) return;

    var compoundId = candidate.dataset.study.intervention.compound.identity.compound_id;
    var route = candidate.dataset.study.intervention.regimen.doses[0].route;

    body.innerHTML =
      '<div class="propgrid">' +
      '<div class="prow"><div class="pk">Dataset</div><div class="pv mono">' + escapeHtml(candidate.dataset.dataset_id) + "</div></div>" +
      '<div class="prow"><div class="pk">Compound</div><div class="pv">' + escapeHtml(compoundId) + "</div></div>" +
      '<div class="prow"><div class="pk">Route</div><div class="pv">' + escapeHtml(route) + "</div></div>" +
      '<div class="prow"><div class="pk">License (declared)</div><div class="pv">' + escapeHtml(candidate.dataset.license) + "</div></div>" +
      "</div>" +
      '<div class="field" style="margin-top:10px;"><span class="flabel">Logical ID</span><input class="finput" id="curLogicalId-' + candidateId + '" type="text" value="' + escapeAttr(candidate.proposed_logical_id || "") + '" /></div>' +
      '<div class="field"><span class="flabel">Evidence class</span><select class="fselect" id="curEvidenceClass-' + candidateId + '">' +
      ["MEASURED", "CURATED", "DERIVED", "FITTED", "MODEL_INHERITED", "SIMULATED", "ASSUMED"].map(function (e) {
        return '<option value="' + e + '"' + (e === "MEASURED" ? " selected" : "") + ">" + e + "</option>";
      }).join("") + "</select></div>" +
      '<span class="btn raised" id="curSaveIdentity-' + candidateId + '" style="cursor:pointer;">Save identity</span>' +
      '<div class="field" style="margin-top:10px;"><span class="flabel">Applicable model IDs (comma-separated)</span><input class="finput" id="curModelIds-' + candidateId + '" type="text" /></div>' +
      '<span class="btn raised" id="curSaveCompatibility-' + candidateId + '" style="cursor:pointer;">Save compatibility</span>' +
      '<div style="margin-top:10px;display:flex;gap:8px;">' +
      '<span class="btn raised" id="curLicenseReviewed-' + candidateId + '" style="cursor:pointer;">' + (candidate.license_reviewed ? "License reviewed &#10003;" : "Mark license reviewed") + "</span>" +
      '<span class="btn raised" id="curAckIdentity-' + candidateId + '" style="cursor:pointer;">' + (candidate.identity_reviewed ? "Identity reviewed &#10003;" : "Acknowledge identity") + "</span>" +
      "</div>";

    document.getElementById("curSaveIdentity-" + candidateId).addEventListener("click", function () {
      var logicalId = document.getElementById("curLogicalId-" + candidateId).value.trim();
      var evidenceClass = document.getElementById("curEvidenceClass-" + candidateId).value;
      if (!logicalId) return;
      fetch("/api/curation/candidate/" + candidateId + "/identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ logical_id: logicalId, evidence_class: evidenceClass }),
      })
        .then(function (r) { return r.json(); })
        .then(function () { refreshCurationCandidate(candidateId); });
    });

    document.getElementById("curSaveCompatibility-" + candidateId).addEventListener("click", function () {
      var raw = document.getElementById("curModelIds-" + candidateId).value.trim();
      var modelIds = raw ? raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];
      fetch("/api/curation/candidate/" + candidateId + "/compatibility", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_ids: modelIds, route: route }),
      })
        .then(function (r) { return r.json(); })
        .then(function () { refreshCurationCandidate(candidateId); });
    });

    document.getElementById("curLicenseReviewed-" + candidateId).addEventListener("click", function () {
      fetch("/api/curation/candidate/" + candidateId + "/license-reviewed", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function () { refreshCurationCandidate(candidateId); });
    });

    document.getElementById("curAckIdentity-" + candidateId).addEventListener("click", function () {
      fetch("/api/curation/candidate/" + candidateId + "/acknowledge-identity", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function () { refreshCurationCandidate(candidateId); });
    });
  }

  // ================= Parameter evidence (Registry v0.2) =================

  function renderParameterEvidenceProposeForm() {
    var box = document.getElementById("parameterEvidencePropose");
    box.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Loading&hellip;</span>';
    fetch("/api/parameter-identities").then(function (r) { return r.json(); }).then(function (identities) {
      box.innerHTML =
        '<div class="field"><span class="flabel">Compound ID</span><input class="finput" id="peCompoundId" type="text" placeholder="e.g. aciclovir" /></div>' +
        '<div class="field"><span class="flabel">Canonical parameter</span><select class="fselect" id="peCanonicalId">' +
        identities.map(function (i) { return '<option value="' + escapeAttr(i.canonical_id) + '">' + escapeHtml(i.canonical_id) + " (" + escapeHtml(i.reference_unit) + ")</option>"; }).join("") +
        "</select></div>" +
        '<div class="frow2"><div class="field"><span class="flabel">Value</span><input class="finput" id="peValue" type="number" step="any" /></div>' +
        '<div class="field"><span class="flabel">Unit</span><input class="finput" id="peUnit" type="text" placeholder="e.g. L/hour" /></div></div>' +
        '<div class="field"><span class="flabel">Value type</span><select class="fselect" id="peValueType">' +
        ["OBSERVED", "DERIVED", "ESTIMATED", "FITTED", "INFERRED", "PREDICTED", "ASSUMED", "CALIBRATED"].map(function (v) {
          return '<option value="' + v + '"' + (v === "OBSERVED" ? " selected" : "") + ">" + v + "</option>";
        }).join("") + "</select></div>" +
        '<div class="frow2"><div class="field"><span class="flabel">Species (optional)</span><input class="finput" id="peSpecies" type="text" placeholder="human" /></div>' +
        '<div class="field"><span class="flabel">Population (optional)</span><input class="finput" id="pePopulation" type="text" /></div></div>' +
        '<div class="field"><span class="flabel">Method (optional)</span><input class="finput" id="peMethod" type="text" /></div>' +
        '<div class="field"><span class="flabel">Citation URL</span><input class="finput" id="peCitationUrl" type="text" placeholder="https://..." /></div>' +
        '<div class="field"><span class="flabel">Citation title</span><input class="finput" id="peCitationTitle" type="text" /></div>' +
        '<div class="field"><span class="flabel">Excerpt (the literal text the value was read from)</span><input class="finput" id="peCitationExcerpt" type="text" /></div>' +
        '<span class="btn btn-primary raised" id="peProposeBtn" style="cursor:pointer;">Propose</span>' +
        '<div id="peProposeResult" style="margin-top:8px;"></div>';

      document.getElementById("peProposeBtn").addEventListener("click", function () {
        var out = document.getElementById("peProposeResult");
        var body = {
          compound_id: document.getElementById("peCompoundId").value.trim(),
          canonical_parameter_id: document.getElementById("peCanonicalId").value,
          value: parseFloat(document.getElementById("peValue").value),
          unit: document.getElementById("peUnit").value.trim(),
          value_type: document.getElementById("peValueType").value,
          species: document.getElementById("peSpecies").value.trim() || null,
          population: document.getElementById("pePopulation").value.trim() || null,
          method: document.getElementById("peMethod").value.trim() || null,
          citation_url: document.getElementById("peCitationUrl").value.trim(),
          citation_title: document.getElementById("peCitationTitle").value.trim(),
          citation_excerpt: document.getElementById("peCitationExcerpt").value.trim(),
        };
        if (!body.compound_id || !body.unit || isNaN(body.value) || !body.citation_url || !body.citation_title || !body.citation_excerpt) {
          out.innerHTML = '<span style="color:var(--absent)">Compound ID, value, unit, and full citation are required.</span>';
          return;
        }
        out.innerHTML = "Proposing…";
        fetch("/api/parameter-evidence/propose", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "propose failed"); });
            return r.json();
          })
          .then(function () {
            out.innerHTML = "Proposed.";
            loadParameterEvidenceCandidates();
          })
          .catch(function (err) {
            out.innerHTML = '<div class="error-banner"><strong>Could not propose.</strong><br />' + escapeHtml(err.message) + "</div>";
          });
      });
    });
  }

  function loadParameterEvidenceCandidates() {
    fetch("/api/parameter-evidence/candidates").then(function (r) { return r.json(); }).then(function (candidates) {
      var box = document.getElementById("parameterEvidenceCandidates");
      box.innerHTML = candidates.length
        ? candidates.map(function (c) {
            var statusClass = c.outcome === "ACCEPTED" ? "verified" : c.outcome === "REJECTED" ? "absent" : "pending";
            return (
              '<div class="param-row" style="cursor:pointer;" data-pe-candidate="' + escapeAttr(c.candidate_id) + '">' +
              '<span class="sq ' + statusClass + '"></span>' +
              '<span class="mono">' + escapeHtml(c.compound_id) + "." + escapeHtml(c.canonical_parameter_id) + "</span>" +
              '<span style="margin-left:8px;">' + c.value.value + " " + escapeHtml(c.value.unit) + "</span>" +
              '<span style="margin-left:auto;">' + escapeHtml(c.outcome) + "</span></div>"
            );
          }).join("")
        : '<div class="empty-state">No candidates yet.</div>';
      box.querySelectorAll("[data-pe-candidate]").forEach(function (row) {
        row.addEventListener("click", function () { renderParameterEvidenceReview(row.dataset.peCandidate); });
      });
    });
  }

  function renderParameterEvidenceReview(candidateId) {
    var container = document.getElementById("parameterEvidenceReview");
    container.innerHTML =
      '<div class="panel"><div class="phead">Review candidate</div><div class="pbody" id="peReviewBody-' + candidateId + '"></div></div>' +
      '<div class="panel"><div class="phead">Validation checklist</div><div class="pbody" id="peChecklist-' + candidateId + '"></div></div>';
    refreshParameterEvidenceCandidate(candidateId);
  }

  function refreshParameterEvidenceCandidate(candidateId) {
    fetch("/api/parameter-evidence/candidate/" + candidateId)
      .then(function (r) { return r.json(); })
      .then(function (candidate) {
        renderParameterEvidenceReviewBody(candidate);
        return fetch("/api/parameter-evidence/candidate/" + candidateId + "/checklist");
      })
      .then(function (r) { return r.json(); })
      .then(function (checklist) { renderParameterEvidenceChecklist(candidateId, checklist); });
  }

  function renderParameterEvidenceChecklist(candidateId, checklist) {
    var body = document.getElementById("peChecklist-" + candidateId);
    if (!body) return;
    var rungs = checklist.checks.map(function (c) {
      return (
        '<div class="rung"><span class="sq ' + c.status + '"></span>' +
        '<span class="txt"><strong>' + escapeHtml(c.label) + "</strong><span>" + escapeHtml(c.detail) + "</span></span></div>"
      );
    }).join("");
    body.innerHTML =
      '<div class="status-ladder">' + rungs + "</div>" +
      '<div style="margin-top:10px;display:flex;gap:8px;">' +
      '<span class="btn btn-primary raised" id="peAcceptBtn-' + candidateId + '" style="cursor:pointer;">Accept &amp; register</span>' +
      '<span class="btn raised" id="peRejectBtn-' + candidateId + '" style="cursor:pointer;">Reject</span>' +
      "</div>" +
      '<div id="peAcceptResult-' + candidateId + '" style="margin-top:8px;"></div>';

    var acceptBtn = document.getElementById("peAcceptBtn-" + candidateId);
    if (checklist.ok) {
      acceptBtn.addEventListener("click", function () {
        var out = document.getElementById("peAcceptResult-" + candidateId);
        out.innerHTML = "Accepting…";
        fetch("/api/parameter-evidence/candidate/" + candidateId + "/accept", { method: "POST" })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "accept failed"); });
            return r.json();
          })
          .then(function (result) {
            out.innerHTML = '<div class="hash-line"><span class="k">Registered</span><span class="v mono">' + escapeHtml(result.record_id) + "</span></div>";
            loadParameterEvidenceCandidates();
          })
          .catch(function (err) {
            out.innerHTML = '<div class="error-banner"><strong>Accept failed.</strong><br />' + escapeHtml(err.message) + "</div>";
          });
      });
    } else {
      acceptBtn.style.opacity = "0.5";
      acceptBtn.style.cursor = "default";
    }

    document.getElementById("peRejectBtn-" + candidateId).addEventListener("click", function () {
      var reason = window.prompt("Reason for rejecting this candidate:");
      if (!reason) return;
      fetch("/api/parameter-evidence/candidate/" + candidateId + "/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason }),
      })
        .then(function (r) { return r.json(); })
        .then(function () { loadParameterEvidenceCandidates(); refreshParameterEvidenceCandidate(candidateId); });
    });
  }

  function renderParameterEvidenceReviewBody(candidate) {
    var candidateId = candidate.candidate_id;
    var body = document.getElementById("peReviewBody-" + candidateId);
    if (!body) return;

    body.innerHTML =
      '<div class="propgrid">' +
      '<div class="prow"><div class="pk">Compound</div><div class="pv">' + escapeHtml(candidate.compound_id) + "</div></div>" +
      '<div class="prow"><div class="pk">Parameter</div><div class="pv">' + escapeHtml(candidate.canonical_parameter_id) + "</div></div>" +
      '<div class="prow"><div class="pk">Value</div><div class="pv mono">' + candidate.value.value + " " + escapeHtml(candidate.value.unit) + "</div></div>" +
      '<div class="prow"><div class="pk">Context</div><div class="pv">' + escapeHtml([candidate.value.species, candidate.value.population, candidate.value.method].filter(Boolean).join(" &middot; ") || "none declared") + "</div></div>" +
      '<div class="prow"><div class="pk">Citation</div><div class="pv"><a href="' + escapeAttr(candidate.citation.url) + '" target="_blank" rel="noopener">' + escapeHtml(candidate.citation.title) + "</a></div></div>" +
      "</div>" +
      '<div class="ec-body" style="padding-left:0;margin-top:6px;">&ldquo;' + escapeHtml(candidate.citation.excerpt) + '&rdquo;</div>' +
      '<div class="field" style="margin-top:10px;"><span class="flabel">Logical ID</span><input class="finput" id="peLogicalId-' + candidateId + '" type="text" value="' + escapeAttr(candidate.proposed_logical_id || "") + '" /></div>' +
      '<div class="field"><span class="flabel">Evidence class</span><select class="fselect" id="peEvidenceClass-' + candidateId + '">' +
      ["MEASURED", "CURATED", "DERIVED", "FITTED", "MODEL_INHERITED", "SIMULATED", "ASSUMED"].map(function (e) {
        return '<option value="' + e + '"' + (e === "MEASURED" ? " selected" : "") + ">" + e + "</option>";
      }).join("") + "</select></div>" +
      '<span class="btn raised" id="peSaveIdentity-' + candidateId + '" style="cursor:pointer;">Save identity</span>' +
      '<div style="margin-top:10px;display:flex;gap:8px;">' +
      '<span class="btn raised" id="peCitationReviewed-' + candidateId + '" style="cursor:pointer;">' + (candidate.citation_reviewed ? "Citation reviewed &#10003;" : "Mark citation reviewed") + "</span>" +
      '<span class="btn raised" id="peAckConflict-' + candidateId + '" style="cursor:pointer;">' + (candidate.conflict_acknowledged ? "Conflict acknowledged &#10003;" : "Acknowledge conflict") + "</span>" +
      "</div>";

    document.getElementById("peSaveIdentity-" + candidateId).addEventListener("click", function () {
      var logicalId = document.getElementById("peLogicalId-" + candidateId).value.trim();
      var evidenceClass = document.getElementById("peEvidenceClass-" + candidateId).value;
      if (!logicalId) return;
      fetch("/api/parameter-evidence/candidate/" + candidateId + "/identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ logical_id: logicalId, evidence_class: evidenceClass }),
      })
        .then(function (r) { return r.json(); })
        .then(function () { refreshParameterEvidenceCandidate(candidateId); });
    });

    document.getElementById("peCitationReviewed-" + candidateId).addEventListener("click", function () {
      fetch("/api/parameter-evidence/candidate/" + candidateId + "/citation-reviewed", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function () { refreshParameterEvidenceCandidate(candidateId); });
    });

    document.getElementById("peAckConflict-" + candidateId).addEventListener("click", function () {
      fetch("/api/parameter-evidence/candidate/" + candidateId + "/acknowledge-conflict", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function () { refreshParameterEvidenceCandidate(candidateId); });
    });
  }

  // ================= Registry pane =================

  var REGISTRY_KINDS = ["model", "compound", "parameter_evidence", "dataset", "experiment"];

  function renderRegistry() {
    state.activePane = "registry";
    appMain.innerHTML =
      '<div class="app-topbar"><div><h3>Registry</h3><div class="sub">Immutable, versioned records of reusable scientific knowledge</div></div></div>' +
      '<div class="panel"><div class="phead"><span>Records</span><select class="fselect" id="registryKindFilter" style="width:200px;display:inline-block;">' +
      '<option value="">(all kinds)</option>' +
      REGISTRY_KINDS.map(function (k) { return '<option value="' + k + '">' + k + "</option>"; }).join("") +
      "</select></div>" +
      '<div class="pbody" id="registryList"><span style="color:var(--ink-faint);font-size:11px;">Loading&hellip;</span></div></div>' +
      '<div id="registryDetail" style="margin-top:10px;"></div>';

    var loadRegistry = function () {
      var kind = document.getElementById("registryKindFilter").value;
      var list = document.getElementById("registryList");
      list.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Loading&hellip;</span>';
      fetch("/api/registry" + (kind ? "?kind=" + encodeURIComponent(kind) : ""))
        .then(function (r) { return r.json(); })
        .then(function (records) {
          if (!records.length) {
            list.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">No records registered yet. Run <code>opentrials registry seed</code>, or register a completed run as an experiment from the Results pane.</span>';
            return;
          }
          list.innerHTML = '<div style="overflow-x:auto"><table class="arms-table">' +
            "<thead><tr><th>Logical ID</th><th>Kind</th><th>Version</th><th>Evidence class</th><th>License</th><th></th></tr></thead><tbody>" +
            records.map(function (r) {
              return (
                '<tr><td class="mono">' + escapeHtml(r.logical_id) + "</td>" +
                "<td>" + escapeHtml(r.kind) + "</td>" +
                '<td class="mono">' + escapeHtml(r.version) + "</td>" +
                '<td><span class="tag" style="color:' + evidenceClassColor(r.evidence_class) + '">' + escapeHtml(r.evidence_class) + "</span></td>" +
                "<td>" + escapeHtml(r.license) + "</td>" +
                '<td><span class="btn raised" style="cursor:pointer;" data-logical-id="' + escapeAttr(r.logical_id) + '">Inspect</span></td>' +
                "</tr>"
              );
            }).join("") + "</tbody></table></div>";
          list.querySelectorAll("[data-logical-id]").forEach(function (btn) {
            btn.addEventListener("click", function () { loadRegistryDetail(btn.dataset.logicalId); });
          });
        });
    };
    document.getElementById("registryKindFilter").addEventListener("change", loadRegistry);
    loadRegistry();
  }

  function evidenceClassColor(evidenceClass) {
    if (evidenceClass === "SIMULATED" || evidenceClass === "ASSUMED") return "var(--pending)";
    if (evidenceClass === "MEASURED" || evidenceClass === "CURATED") return "var(--verified)";
    return "var(--ink-soft)";
  }

  function loadRegistryDetail(logicalId) {
    var detail = document.getElementById("registryDetail");
    detail.innerHTML = '<div class="empty-state">Loading&hellip;</div>';
    fetch("/api/registry/" + encodeURIComponent(logicalId))
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not load record"); });
        return r.json();
      })
      .then(function (d) { renderRegistryDetail(d, logicalId); })
      .catch(function (err) {
        detail.innerHTML = '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
      });
  }

  function renderRegistryDetail(d, logicalId) {
    var detail = document.getElementById("registryDetail");
    var m = d.manifest;
    var forkAction = m.kind === "EXPERIMENT"
      ? '<div class="field"><span class="flabel">Fork into a new project.yaml</span>' +
        '<div class="arms-cell-pair"><input class="finput mono" id="forkOutputPath" value="forked_project.yaml" style="flex:2" />' +
        '<span class="btn btn-primary raised" id="forkBtn" style="cursor:pointer;">Fork</span></div></div>' +
        '<div id="forkResult" style="margin-top:6px;"></div>'
      : "";

    detail.innerHTML =
      '<div class="panel"><div class="phead">' + escapeHtml(logicalId) + "</div><div class=\"pbody\">" +
      '<div class="propgrid">' +
      '<div class="prow"><div class="pk">Record ID</div><div class="pv mono">' + escapeHtml(m.record_id) + "</div></div>" +
      '<div class="prow"><div class="pk">Kind</div><div class="pv">' + escapeHtml(m.kind) + "</div></div>" +
      '<div class="prow"><div class="pk">Version</div><div class="pv mono">' + escapeHtml(m.version) + "</div></div>" +
      '<div class="prow"><div class="pk">Evidence class</div><div class="pv" style="color:' + evidenceClassColor(m.evidence_class) + '">' + escapeHtml(m.evidence_class) + "</div></div>" +
      '<div class="prow"><div class="pk">License</div><div class="pv">' + escapeHtml(m.license) + "</div></div>" +
      '<div class="prow"><div class="pk">Source</div><div class="pv">' + escapeHtml(m.source.kind) + ": " + escapeHtml(m.source.identifier) + "</div></div>" +
      (m.applies_to_model_ids.length ? '<div class="prow"><div class="pk">Applies to</div><div class="pv">' + escapeHtml(m.applies_to_model_ids.join(", ")) + "</div></div>" : "") +
      "</div>" +
      (forkAction ? '<div style="margin-top:10px;">' + forkAction + "</div>" : "") +
      '<div class="field" style="margin-top:10px;"><span class="flabel">Payload</span>' +
      '<pre style="white-space:pre-wrap;font-size:10px;background:var(--well);border:1px solid var(--border-soft);padding:8px;max-height:280px;overflow:auto;">' + escapeHtml(JSON.stringify(d.payload, null, 2)) + "</pre></div>" +
      "</div></div>" +
      (m.kind === "EXPERIMENT"
        ? '<div class="panel"><div class="phead">Lineage</div><div class="pbody" id="lineagePanel"><span style="color:var(--ink-faint);font-size:11px;">Loading&hellip;</span></div></div>' +
          '<div class="panel"><div class="phead">Reproduce</div><div class="pbody">' +
          '<p style="font-size:10.5px;color:var(--ink-faint);margin:0 0 8px;">Re-runs this experiment&rsquo;s exact trial against its exact model, fresh, and checks whether the endpoint results hash identically.</p>' +
          '<span class="btn btn-primary raised" id="reproduceBtn" style="cursor:pointer;">Run reproduction</span>' +
          '<div id="reproduceResult" style="margin-top:8px;"></div></div></div>' +
          '<div class="panel"><div class="phead">Diff against a project</div><div class="pbody">' +
          '<div class="field"><span class="flabel">Project path</span><input class="finput mono" id="diffProjectPath" type="text" placeholder="/path/to/forked-project.yaml" /></div>' +
          '<span class="btn raised" id="diffBtn" style="cursor:pointer;">Diff</span>' +
          '<div id="diffResult" style="margin-top:8px;"></div></div></div>'
        : "");

    if (m.kind === "EXPERIMENT") {
      document.getElementById("forkBtn").addEventListener("click", function () {
        var outputPath = document.getElementById("forkOutputPath").value.trim();
        var forkResult = document.getElementById("forkResult");
        forkResult.innerHTML = '<span style="color:var(--ink-faint);font-size:11px;">Forking&hellip;</span>';
        fetch("/api/registry/" + encodeURIComponent(logicalId) + "/fork", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ output_path: outputPath }),
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "fork failed"); });
            return r.json();
          })
          .then(function (project) {
            forkResult.innerHTML = '<span style="color:var(--verified);font-size:11px;">Forked to ' + escapeHtml(project.path) + ' -- open it from the toolbar to continue editing.</span>';
          })
          .catch(function (err) {
            forkResult.innerHTML = '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
          });
      });

      loadExperimentLineage(logicalId);

      document.getElementById("reproduceBtn").addEventListener("click", function () {
        var out = document.getElementById("reproduceResult");
        out.innerHTML = "Starting reproduction run&hellip;";
        fetch("/api/registry/" + encodeURIComponent(logicalId) + "/reproduce", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not start reproduction"); });
            return r.json();
          })
          .then(function (result) { pollReproductionRun(result.run_id, result.expected_endpoint_summary_sha256, out); })
          .catch(function (err) {
            out.innerHTML = '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
          });
      });

      document.getElementById("diffBtn").addEventListener("click", function () {
        var projectPath = document.getElementById("diffProjectPath").value.trim();
        if (!projectPath) return;
        var out = document.getElementById("diffResult");
        out.innerHTML = "Diffing&hellip;";
        fetch("/api/registry/" + encodeURIComponent(logicalId) + "/diff", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_path: projectPath }),
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "diff failed"); });
            return r.json();
          })
          .then(function (changes) { renderExperimentDiff(out, changes); })
          .catch(function (err) {
            out.innerHTML = '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
          });
      });
    }
  }

  function loadExperimentLineage(logicalId) {
    var panel = document.getElementById("lineagePanel");
    Promise.all([
      fetch("/api/registry/" + encodeURIComponent(logicalId) + "/ancestry").then(function (r) { return r.json(); }),
      fetch("/api/registry/" + encodeURIComponent(logicalId) + "/children").then(function (r) { return r.json(); }),
    ]).then(function (results) {
      var ancestryChain = results[0].slice().reverse(); // root first
      var kids = results[1];
      var ancestryHtml = ancestryChain.length > 1
        ? ancestryChain.map(function (m, i) {
            var isSelf = i === ancestryChain.length - 1;
            return (isSelf ? "<strong>" : "") + escapeHtml(m.logical_id) + (isSelf ? "</strong>" : "");
          }).join(" &rarr; ")
        : "This is a root experiment (not a fork).";
      var childrenHtml = kids.length
        ? kids.map(function (m) { return '<div class="param-row">' + escapeHtml(m.logical_id) + "</div>"; }).join("")
        : '<div class="param-row" style="color:var(--ink-faint);">No forks registered yet.</div>';
      panel.innerHTML =
        '<div style="font-size:11px;margin-bottom:8px;">' + ancestryHtml + "</div>" +
        '<span class="flabel" style="display:block;margin-bottom:4px;">Forked from this experiment</span>' +
        childrenHtml;
    });
  }

  function pollReproductionRun(runId, expectedHash, out) {
    out.innerHTML = '<div class="empty-state">Running&hellip;</div>';
    fetch("/api/run/" + runId).then(function (r) { return r.json(); }).then(function (run) {
      if (run.status === "running") { setTimeout(function () { pollReproductionRun(runId, expectedHash, out); }, 2000); return; }
      if (run.status === "failed") {
        out.innerHTML = '<div class="error-banner"><strong>Reproduction run failed.</strong><br />' + escapeHtml(run.error || "") + "</div>";
        return;
      }
      fetch("/api/run/" + runId + "/check-reproduction", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_hash: expectedHash }),
      })
        .then(function (r) { return r.json(); })
        .then(function (check) {
          out.innerHTML = check.reproduced
            ? '<div class="hash-line"><span class="k" style="color:var(--verified);">Reproduced identically</span><span class="v mono">' + escapeHtml(check.actual_hash) + "</span></div>"
            : '<div class="error-banner"><strong>Did not reproduce identically.</strong><br />expected <span class="mono">' + escapeHtml(String(check.expected_hash)) + '</span><br />got <span class="mono">' + escapeHtml(check.actual_hash) + "</span></div>";
        });
    });
  }

  function renderExperimentDiff(out, changes) {
    if (!changes.length) {
      out.innerHTML = '<div class="empty-state">No changes -- identical to the registered experiment.</div>';
      return;
    }
    out.innerHTML = changes.map(function (c) {
      if (c.change === "changed") {
        return '<div class="param-row"><span class="mono">' + escapeHtml(c.path) + "</span><span style=\"margin-left:auto;color:var(--absent);\">" + escapeHtml(JSON.stringify(c.before)) + " &rarr; </span><span style=\"color:var(--verified);\">" + escapeHtml(JSON.stringify(c.after)) + "</span></div>";
      }
      if (c.change === "added") {
        return '<div class="param-row"><span class="mono">' + escapeHtml(c.path) + '</span><span style="margin-left:auto;color:var(--verified);">added: ' + escapeHtml(JSON.stringify(c.after)) + "</span></div>";
      }
      return '<div class="param-row"><span class="mono">' + escapeHtml(c.path) + '</span><span style="margin-left:auto;color:var(--absent);">removed: ' + escapeHtml(JSON.stringify(c.before)) + "</span></div>";
    }).join("");
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

  function evqClass(compatibility) {
    if (compatibility === "HIGH") return "evq-high";
    if (compatibility === "MODERATE") return "evq-mod";
    return "evq-low";
  }

  function registryCandidateHtml(match) {
    var reasons = match.reasons.map(function (r) { return "<li>" + escapeHtml(r) + "</li>"; }).join("");
    return (
      '<div class="evidence-choice' + (match.compatibility === "HIGH" ? " best" : "") + '">' +
      '<div class="ec-head">' +
      '<span class="value">' + escapeHtml(match.logical_id) + "</span>" +
      '<span class="tag">' + escapeHtml(match.evidence_class) + "</span>" +
      '<span class="evq ' + evqClass(match.compatibility) + '">' + escapeHtml(match.compatibility) + "</span>" +
      "</div>" +
      '<div class="ec-body">' +
      '<span class="src">' + escapeHtml(match.kind) + "</span> &middot; " + escapeHtml(match.record_id) +
      " &middot; license " + escapeHtml(match.license) +
      '<details><summary class="ec-why">Why is this suggested?</summary><ul class="ec-reasons">' + reasons + "</ul></details>" +
      "</div></div>"
    );
  }

  function renderRegistryMatches(container, result) {
    var sections = "";
    if (result.compound_match) {
      sections +=
        '<div style="margin-bottom:10px;"><span class="flabel" style="display:block;margin-bottom:4px;">Compound</span>' +
        registryCandidateHtml(result.compound_match) + "</div>";
    }
    if (result.dataset_matches.length) {
      sections +=
        '<div style="margin-bottom:10px;"><span class="flabel" style="display:block;margin-bottom:4px;">Datasets</span>' +
        result.dataset_matches.map(registryCandidateHtml).join("") + "</div>";
    }
    if (result.parameter_evidence_matches.length) {
      sections +=
        '<div style="margin-bottom:10px;"><span class="flabel" style="display:block;margin-bottom:4px;">Parameter evidence</span>' +
        result.parameter_evidence_matches.map(registryCandidateHtml).join("") + "</div>";
    }
    container.innerHTML = sections || '<div class="empty-state">No registry candidates found for this compound.</div>';
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
      '<div class="panel"><div class="phead">Registry candidates</div><div class="pbody">' +
      '<div class="review-banner"><span class="ic">&#9888;</span><span class="tx">Discovered molecule names are engine identifiers, not OpenTrials compound identity &mdash; confirm the correct <span class="mono">compound_id</span> yourself before matching.</span></div>' +
      '<div class="field"><span class="flabel">Compound ID</span><input class="finput" id="registryCompoundId" type="text" placeholder="e.g. aciclovir" value="' + escapeHtml((report.molecule_names[0] || "").toLowerCase()) + '" /></div>' +
      '<span class="btn btn-primary raised" id="registryMatchBtn" style="cursor:pointer;">Find registry candidates</span>' +
      '<div id="registryMatchResult" style="margin-top:10px;"></div>' +
      '</div></div>' +
      '<div class="panel"><div class="phead">Generate profile scaffold</div><div class="pbody">' +
      '<div class="field"><span class="flabel">Model ID</span><input class="finput" id="scaffoldModelId" type="text" placeholder="osp.compound.route-variant" /></div>' +
      '<span class="btn btn-primary raised" id="scaffoldBtn" style="cursor:pointer;">Generate scaffold</span>' +
      '<div id="scaffoldResult" style="margin-top:8px;"></div>' +
      "</div></div>" +
      '<div class="panel"><div class="phead">Guided model onboarding</div><div class="pbody">' +
      '<p style="font-size:10.5px;color:var(--ink-faint);margin:0 0 8px;">Turns this discovery into a reviewed, evidence-bearing, live-verified model registration &mdash; no capability is registered until a real execution proves it works.</p>' +
      '<div class="field"><span class="flabel">Model ID</span><input class="finput" id="onboardModelId" type="text" placeholder="osp.compound.route-variant" /></div>' +
      '<span class="btn btn-primary raised" id="startDraftBtn" style="cursor:pointer;">Start guided onboarding</span>' +
      '<div id="onboardingPanel" style="margin-top:10px;"></div>' +
      "</div></div>";

    document.getElementById("registryMatchBtn").addEventListener("click", function () {
      var compoundId = document.getElementById("registryCompoundId").value.trim();
      if (!compoundId) return;
      var matchResult = document.getElementById("registryMatchResult");
      matchResult.innerHTML = '<div class="empty-state">Matching&hellip;</div>';
      fetch("/api/registry/matches/" + encodeURIComponent(compoundId))
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "matching failed"); });
          return r.json();
        })
        .then(function (result) { renderRegistryMatches(matchResult, result); })
        .catch(function (err) {
          matchResult.innerHTML = '<div class="error-banner"><strong>Matching failed.</strong><br />' + escapeHtml(err.message) + "</div>";
        });
    });

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

    document.getElementById("startDraftBtn").addEventListener("click", function () {
      var modelId = document.getElementById("onboardModelId").value.trim();
      if (!modelId) return;
      var panel = document.getElementById("onboardingPanel");
      panel.innerHTML = '<div class="empty-state">Starting draft&hellip;</div>';
      fetch("/api/onboarding/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pkml_path: pkmlPath, model_id: modelId }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not start draft"); });
          return r.json();
        })
        .then(function (draft) { renderDraftWorkspace(panel, draft.draft_id); })
        .catch(function (err) {
          panel.innerHTML = '<div class="error-banner"><strong>Could not start onboarding.</strong><br />' + escapeHtml(err.message) + "</div>";
        });
    });
  }

  // ================= Guided Model Onboarding (Studio v0.4) =================

  var SLOT_LABELS = {
    compound: "Compound identity",
    administration: "Administration route",
    output: "Output mapping",
    applicability: "Population applicability",
  };

  function statusBadgeClass(status) {
    if (status === "VERIFIED") return "evq-high";
    if (status === "MAPPED") return "evq-mod";
    if (status === "UNSUPPORTED") return "evq-mod";
    if (status === "REQUIRES_REVIEW") return "evq-low";
    return "evq-low";
  }

  function renderDraftWorkspace(panel, draftId) {
    panel.innerHTML =
      '<div class="panel"><div class="phead">Draft ' + escapeHtml(draftId.slice(0, 8)) + '&hellip;</div><div class="pbody" id="draftBody-' + draftId + '"></div></div>' +
      '<div class="panel"><div class="phead">Validation checklist</div><div class="pbody" id="draftChecklist-' + draftId + '"></div></div>';
    refreshDraft(draftId);
  }

  function refreshDraft(draftId) {
    fetch("/api/onboarding/draft/" + draftId)
      .then(function (r) { return r.json(); })
      .then(function (draft) {
        renderDraftBody(draft);
        return fetch("/api/onboarding/draft/" + draftId + "/checklist");
      })
      .then(function (r) { return r.json(); })
      .then(function (checklist) { renderDraftChecklist(draftId, checklist); });
  }

  function renderDraftChecklist(draftId, checklist) {
    var body = document.getElementById("draftChecklist-" + draftId);
    if (!body) return;
    var rungs = checklist.checks.map(function (c) {
      return (
        '<div class="rung"><span class="sq ' + c.status + '"></span>' +
        '<span class="txt"><strong>' + escapeHtml(c.label) + "</strong><span>" + escapeHtml(c.detail) + "</span></span></div>"
      );
    }).join("");
    body.innerHTML =
      '<div class="status-ladder">' + rungs + "</div>" +
      '<span class="btn btn-primary raised" id="registerBtn-' + draftId + '" style="cursor:pointer;margin-top:10px;" ' +
      (checklist.ok ? "" : 'disabled aria-disabled="true"') + ">Register model</span>" +
      '<div id="registerResult-' + draftId + '" style="margin-top:8px;"></div>';

    var registerBtn = document.getElementById("registerBtn-" + draftId);
    if (checklist.ok) {
      registerBtn.addEventListener("click", function () {
        var out = document.getElementById("registerResult-" + draftId);
        out.innerHTML = "Registering…";
        fetch("/api/onboarding/draft/" + draftId + "/register", { method: "POST" })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "registration failed"); });
            return r.json();
          })
          .then(function (result) {
            out.innerHTML =
              '<div class="hash-line"><span class="k">Model registered</span><span class="v mono">' + escapeHtml(result.model.record_id) + "</span></div>" +
              '<div class="hash-line"><span class="k">Verification recorded</span><span class="v mono">' + escapeHtml(result.verification.record_id) + "</span></div>";
          })
          .catch(function (err) {
            out.innerHTML = '<div class="error-banner"><strong>Registration failed.</strong><br />' + escapeHtml(err.message) + "</div>";
          });
      });
    } else {
      registerBtn.style.opacity = "0.5";
      registerBtn.style.cursor = "default";
    }
  }

  function slotSummaryHtml(draftId, slot, selection) {
    var status = selection ? selection.status : "DISCOVERED";
    var summary = selection ? JSON.stringify(selection.value) : "not yet mapped";
    return (
      '<div class="ec-head">' +
      '<span class="value">' + escapeHtml(SLOT_LABELS[slot]) + "</span>" +
      '<span class="evq ' + statusBadgeClass(status) + '">' + escapeHtml(status) + "</span>" +
      "</div>" +
      '<div class="ec-body mono" style="word-break:break-all;">' + escapeHtml(summary) +
      (selection && selection.evidence_class ? " &middot; evidence: " + escapeHtml(selection.evidence_class) : "") +
      (selection && selection.source_record_id ? " &middot; source: " + escapeHtml(selection.source_record_id) : "") +
      "</div>"
    );
  }

  function slotFormFields(slot) {
    if (slot === "compound") {
      return [["compound_id", "Compound ID"], ["engine_molecule_id", "Engine molecule name"]];
    }
    if (slot === "administration") {
      return [
        ["target_id", "Target ID"], ["route", "Route (e.g. INTRAVENOUS)"],
        ["administration_container_path", "Container path"], ["dose_parameter_path", "Dose parameter path"],
        ["dose_unit", "Dose unit"], ["administration_time_parameter_path", "Admin time parameter path"],
        ["administration_time_unit", "Admin time unit"], ["fixed_administration_time_min", "Fixed admin time (min)"],
        ["infusion_duration_parameter_path", "Infusion duration parameter path (optional)"],
        ["infusion_duration_unit", "Infusion duration unit (optional)"],
        ["fixed_infusion_duration_min", "Fixed infusion duration (min, optional)"],
      ];
    }
    if (slot === "output") {
      return [
        ["output_id", "Output ID"], ["parameter_path", "Parameter path"], ["analyte", "Analyte"],
        ["matrix", "Matrix"], ["fraction", "Fraction"], ["measurement", "Measurement"],
        ["unit", "Unit"], ["time_unit", "Time unit"],
      ];
    }
    return [["species", "Species (comma-separated, e.g. human)"]];
  }

  function slotFormHtml(draftId, slot) {
    var fields = slotFormFields(slot).map(function (f) {
      return '<div class="field"><span class="flabel">' + escapeHtml(f[1]) + '</span><input class="finput slotfield" data-key="' + f[0] + '" type="text" /></div>';
    }).join("");
    return (
      '<div class="panel" style="margin-top:6px;"><div class="phead">Map: ' + escapeHtml(SLOT_LABELS[slot]) + '</div><div class="pbody">' +
      fields +
      '<div class="field"><span class="flabel">Evidence class</span><select class="fselect" id="evidenceClass-' + slot + '-' + draftId + '">' +
      ["MEASURED", "CURATED", "DERIVED", "FITTED", "MODEL_INHERITED", "SIMULATED", "ASSUMED"].map(function (e) {
        return '<option value="' + e + '"' + (e === "ASSUMED" ? " selected" : "") + ">" + e + "</option>";
      }).join("") + "</select></div>" +
      '<div class="field"><span class="flabel">Context / rationale</span><input class="finput" id="context-' + slot + '-' + draftId + '" type="text" /></div>' +
      '<span class="btn btn-primary raised" id="saveSlot-' + slot + '-' + draftId + '" style="cursor:pointer;">Save selection</span>' +
      '<div id="slotResult-' + slot + '-' + draftId + '" style="margin-top:6px;"></div>' +
      "</div></div>"
    );
  }

  function wireSlotForm(draftId, slot) {
    var btn = document.getElementById("saveSlot-" + slot + "-" + draftId);
    btn.addEventListener("click", function () {
      var value = {};
      document.querySelectorAll('#slotForm-' + slot + '-' + draftId + ' .slotfield').forEach(function (input) {
        var key = input.dataset.key;
        var raw = input.value.trim();
        if (!raw) return;
        if (key === "species") { value[key] = raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean); return; }
        if (key === "fixed_administration_time_min" || key === "fixed_infusion_duration_min") { value[key] = parseFloat(raw); return; }
        value[key] = raw;
      });
      var evidenceClass = document.getElementById("evidenceClass-" + slot + "-" + draftId).value;
      var context = document.getElementById("context-" + slot + "-" + draftId).value.trim();
      var out = document.getElementById("slotResult-" + slot + "-" + draftId);
      out.innerHTML = "Saving…";
      fetch("/api/onboarding/draft/" + draftId + "/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot: slot, value: value, evidence_class: evidenceClass, context: context || null }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not save selection"); });
          return r.json();
        })
        .then(function () { refreshDraft(draftId); })
        .catch(function (err) {
          out.innerHTML = '<div class="error-banner"><strong>Could not save.</strong><br />' + escapeHtml(err.message) + "</div>";
        });
    });
  }

  function renderDraftBody(draft) {
    var draftId = draft.draft_id;
    var body = document.getElementById("draftBody-" + draftId);
    if (!body) return;

    var slots = ["compound", "administration", "output", "applicability"];
    var slotSections = slots.map(function (slot) {
      var selection = draft.selections[slot];
      return (
        '<div class="evidence-choice">' + slotSummaryHtml(draftId, slot, selection) + "</div>" +
        '<div id="slotForm-' + slot + '-' + draftId + '">' + slotFormHtml(draftId, slot) + "</div>"
      );
    }).join("");

    body.innerHTML =
      '<div class="field"><span class="flabel">Model version</span><input class="finput" id="modelVersion-' + draftId + '" value="' + escapeHtml(draft.model_version || "") + '" type="text" placeholder="1.0.0" /></div>' +
      '<div class="field"><span class="flabel">License</span><input class="finput" id="modelLicense-' + draftId + '" value="' + escapeHtml(draft.license || "") + '" type="text" placeholder="CC-BY-4.0" /></div>' +
      '<span class="btn btn-primary raised" id="saveMetadataBtn-' + draftId + '" style="cursor:pointer;">Save metadata</span>' +
      '<div id="metadataResult-' + draftId + '" style="margin-top:6px;margin-bottom:12px;"></div>' +
      slotSections +
      '<div class="panel" style="margin-top:6px;"><div class="phead">Unsupported capabilities</div><div class="pbody">' +
      '<p style="font-size:10.5px;color:var(--ink-faint);margin:0 0 8px;">' + (draft.unsupported_reviewed ? escapeHtml(draft.unsupported_capabilities.length) + " declared." : "Not yet reviewed.") + "</p>" +
      '<span class="btn raised" id="markNoUnsupportedBtn-' + draftId + '" style="cursor:pointer;">Mark reviewed &mdash; none to declare</span>' +
      "</div></div>" +
      '<div class="panel" style="margin-top:6px;"><div class="phead">Live verification run</div><div class="pbody">' +
      '<div class="field"><span class="flabel">Project path (model_id must match this draft)</span><input class="finput" id="verifyPath-' + draftId + '" type="text" placeholder="/path/to/project.yaml" /></div>' +
      '<span class="btn btn-primary raised" id="verifyRunBtn-' + draftId + '" style="cursor:pointer;">Run live verification</span>' +
      '<div id="verifyResult-' + draftId + '" style="margin-top:8px;"></div>' +
      "</div></div>";

    document.getElementById("saveMetadataBtn-" + draftId).addEventListener("click", function () {
      var modelVersion = document.getElementById("modelVersion-" + draftId).value.trim();
      var license = document.getElementById("modelLicense-" + draftId).value.trim();
      var out = document.getElementById("metadataResult-" + draftId);
      if (!modelVersion || !license) { out.innerHTML = '<span style="color:var(--absent)">Both fields are required.</span>'; return; }
      out.innerHTML = "Saving…";
      fetch("/api/onboarding/draft/" + draftId + "/metadata", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_version: modelVersion, license: license }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not save"); });
          return r.json();
        })
        .then(function () { refreshDraft(draftId); })
        .catch(function (err) { out.innerHTML = '<span style="color:var(--absent)">' + escapeHtml(err.message) + "</span>"; });
    });

    document.getElementById("markNoUnsupportedBtn-" + draftId).addEventListener("click", function () {
      fetch("/api/onboarding/draft/" + draftId + "/unsupported", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: [] }),
      })
        .then(function (r) { return r.json(); })
        .then(function () { refreshDraft(draftId); });
    });

    slots.forEach(function (slot) { wireSlotForm(draftId, slot); });

    document.getElementById("verifyRunBtn-" + draftId).addEventListener("click", function () {
      var path = document.getElementById("verifyPath-" + draftId).value.trim();
      if (!path) return;
      var out = document.getElementById("verifyResult-" + draftId);
      out.innerHTML = "Starting run…";
      fetch("/api/onboarding/draft/" + draftId + "/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not start verification run"); });
          return r.json();
        })
        .then(function (res) { pollVerificationRun(draftId, res.run_id, out); })
        .catch(function (err) {
          out.innerHTML = '<div class="error-banner"><strong>Could not start run.</strong><br />' + escapeHtml(err.message) + "</div>";
        });
    });
  }

  function pollVerificationRun(draftId, runId, out) {
    out.innerHTML = '<div class="empty-state">Running&hellip; (run ' + escapeHtml(runId.slice(0, 8)) + "…)</div>";
    fetch("/api/run/" + runId)
      .then(function (r) { return r.json(); })
      .then(function (run) {
        if (run.status === "running") { setTimeout(function () { pollVerificationRun(draftId, runId, out); }, 2000); return; }
        if (run.status === "failed") {
          out.innerHTML = '<div class="error-banner"><strong>Verification run failed.</strong><br />' + escapeHtml(run.error || "") + "</div>";
          return;
        }
        out.innerHTML =
          '<pre style="font-size:10.5px;white-space:pre-wrap;">' + escapeHtml(run.summary || "") + "</pre>" +
          '<span class="btn btn-primary raised" id="recordVerifyBtn-' + draftId + '" style="cursor:pointer;">Record this verification</span>';
        document.getElementById("recordVerifyBtn-" + draftId).addEventListener("click", function () {
          fetch("/api/onboarding/draft/" + draftId + "/verify/record", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ run_id: runId }),
          })
            .then(function (r) {
              if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "could not record verification"); });
              return r.json();
            })
            .then(function () { refreshDraft(draftId); })
            .catch(function (err) {
              out.innerHTML += '<div class="error-banner">' + escapeHtml(err.message) + "</div>";
            });
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
        showInlineError(err.message);
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
        showInlineError(err.message);
      });
  });

  exportBtn.addEventListener("click", function () {
    if (!state.path) return;
    var a = document.createElement("a");
    a.href = "/api/project/export?path=" + encodeURIComponent(state.path);
    a.download = "project.yaml";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    statusState.textContent = "Exported project.yaml";
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
      if (pane === "registry") {
        renderRegistry();
        return;
      }
      if (pane === "curation") {
        renderCuration();
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
