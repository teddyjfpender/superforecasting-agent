# Gateway Wire Protocol

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: protocol/__init__.py (RPC_SPECS, EVENT_SPECS) + protocol/rpc, protocol/events -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `protocol/__init__.py (RPC_SPECS, EVENT_SPECS) + protocol/rpc, protocol/events`

The gateway speaks **protocol version 1**. Every request, response, and event below is a pydantic model in the `protocol/` package; the TUI's TypeScript wire types (`ui-tui/src/protocol/generated.ts`) are generated from the same registry via `python -m protocol.codegen`. There are **101 RPCs** and **46 events**.


## RPC methods


| method | request | response |
| --- | --- | --- |
| `agents.active.summary` | [`AgentsActiveSummaryRequest`](#agentsactivesummaryrequest) | [`AgentsActiveSummaryResponse`](#agentsactivesummaryresponse) |
| `agents.list` | [`AgentsListRequest`](#agentslistrequest) | [`AgentsListResponse`](#agentslistresponse) |
| `approval.respond` | [`RespondRequest`](#respondrequest) | [`ApprovalRespondResponse`](#approvalrespondresponse) |
| `browser.manage` | [`BrowserManageRequest`](#browsermanagerequest) | [`BrowserManageResponse`](#browsermanageresponse) |
| `clarify.respond` | [`ClarifyRespondRequest`](#clarifyrespondrequest) | [`ClarifyRespondResponse`](#clarifyrespondresponse) |
| `clipboard.paste` | [`ClipboardPasteRequest`](#clipboardpasterequest) | [`ClipboardPasteResponse`](#clipboardpasteresponse) |
| `commands.catalog` | [`CommandsCatalogRequest`](#commandscatalogrequest) | [`CommandsCatalogResponse`](#commandscatalogresponse) |
| `complete.path` | [`CompletionRequest`](#completionrequest) | [`CompletionResponse`](#completionresponse) |
| `complete.slash` | [`CompletionRequest`](#completionrequest) | [`CompletionResponse`](#completionresponse) |
| `config.get` | [`ConfigGetValueRequest`](#configgetvaluerequest) | [`ConfigFullResponse`](#configfullresponse) |
| `config.set` | [`ConfigSetRequest`](#configsetrequest) | [`ConfigSetResponse`](#configsetresponse) |
| `delegation.pause` | [`DelegationPauseRequest`](#delegationpauserequest) | [`DelegationPauseResponse`](#delegationpauseresponse) |
| `delegation.status` | [`DelegationStatusRequest`](#delegationstatusrequest) | [`DelegationStatusResponse`](#delegationstatusresponse) |
| `forecast.bench` | [`ForecastBenchRequest`](#forecastbenchrequest) | [`ForecastBenchResponse`](#forecastbenchresponse) |
| `forecast.calibration` | [`ForecastCalibrationRequest`](#forecastcalibrationrequest) | [`ForecastCalibrationResponse`](#forecastcalibrationresponse) |
| `forecast.command` | [`ForecastCommandRequest`](#forecastcommandrequest) | [`ForecastCommandResponse`](#forecastcommandresponse) |
| `forecast.config` | [`ForecastConfigRequest`](#forecastconfigrequest) | [`ForecastConfigResponse`](#forecastconfigresponse) |
| `forecast.config.set` | [`ForecastConfigSetRequest`](#forecastconfigsetrequest) | [`ForecastConfigResponse`](#forecastconfigresponse) |
| `forecast.dashboard` | [`ForecastDashboardRequest`](#forecastdashboardrequest) | [`ForecastDashboardResponse`](#forecastdashboardresponse) |
| `forecast.desk.task` | [`ForecastDeskTaskRequest`](#forecastdesktaskrequest) | [`ForecastReforecastStartResponse`](#forecastreforecaststartresponse) |
| `forecast.hooks` | [`ForecastHooksRequest`](#forecasthooksrequest) | [`ForecastHooksResponse`](#forecasthooksresponse) |
| `forecast.hooks.preview` | [`ForecastHooksPreviewRequest`](#forecasthookspreviewrequest) | [`ForecastHooksPreviewResponse`](#forecasthookspreviewresponse) |
| `forecast.hooks.remove_rule` | [`ForecastHooksRemoveRuleRequest`](#forecasthooksremoverulerequest) | [`ForecastHooksRemoveRuleResponse`](#forecasthooksremoveruleresponse) |
| `forecast.hooks.save_rule` | [`ForecastHooksSaveRuleRequest`](#forecasthookssaverulerequest) | [`ForecastHooksSaveRuleResponse`](#forecasthookssaveruleresponse) |
| `forecast.hooks.set` | [`ForecastHooksSetRequest`](#forecasthookssetrequest) | [`ForecastHooksSetResponse`](#forecasthookssetresponse) |
| `forecast.onboard_commit` | [`ForecastOnboardCommitRequest`](#forecastonboardcommitrequest) | [`ForecastOnboardCommitResponse`](#forecastonboardcommitresponse) |
| `forecast.onboard_propose` | [`ForecastOnboardProposeRequest`](#forecastonboardproposerequest) | [`ForecastOnboardProposeResponse`](#forecastonboardproposeresponse) |
| `forecast.question` | [`ForecastQuestionRequest`](#forecastquestionrequest) | [`ForecastQuestionPacketResponse`](#forecastquestionpacketresponse) |
| `forecast.question.readiness` | [`ForecastQuestionReadinessRequest`](#forecastquestionreadinessrequest) | [`ForecastQuestionReadinessResponse`](#forecastquestionreadinessresponse) |
| `forecast.quorum.status` | [`ForecastQuorumStatusRequest`](#forecastquorumstatusrequest) | [`ForecastQuorumStatusResponse`](#forecastquorumstatusresponse) |
| `forecast.reforecast` | [`ForecastReforecastRequest`](#forecastreforecastrequest) | [`ForecastReforecastMarkResponse`](#forecastreforecastmarkresponse) |
| `forecast.reforecast.active` | [`ForecastReforecastActiveRequest`](#forecastreforecastactiverequest) | [`ForecastReforecastActiveResponse`](#forecastreforecastactiveresponse) |
| `forecast.reforecast.start` | [`ForecastReforecastStartRequest`](#forecastreforecaststartrequest) | [`ForecastReforecastStartResponse`](#forecastreforecaststartresponse) |
| `forecast.reforecast.status` | [`ForecastReforecastStatusRequest`](#forecastreforecaststatusrequest) | [`ForecastReforecastStatusResponse`](#forecastreforecaststatusresponse) |
| `forecast.reviews.next` | [`ForecastReviewsNextRequest`](#forecastreviewsnextrequest) | [`ForecastReviewsNextResponse`](#forecastreviewsnextresponse) |
| `forecast.schedule.status` | [`ForecastScheduleStatusRequest`](#forecastschedulestatusrequest) | [`ForecastScheduleStatusResponse`](#forecastschedulestatusresponse) |
| `forecast.theses` | [`ForecastThesesRequest`](#forecastthesesrequest) | [`ForecastThesesResponse`](#forecastthesesresponse) |
| `forecast.triage.contested` | [`ForecastTriageContestedRequest`](#forecasttriagecontestedrequest) | [`ForecastTriageContestedResponse`](#forecasttriagecontestedresponse) |
| `forecast.triage.relabel` | [`ForecastTriageRelabelRequest`](#forecasttriagerelabelrequest) | [`ForecastTriageRelabelResponse`](#forecasttriagerelabelresponse) |
| `forecast.warnings.aggregate` | [`ForecastWarningsAggregateRequest`](#forecastwarningsaggregaterequest) | [`ForecastWarningsAggregateResponse`](#forecastwarningsaggregateresponse) |
| `forecast.warnings.automode.run` | [`ForecastWarningsAutomodeRunRequest`](#forecastwarningsautomoderunrequest) | [`ForecastWarningsAutomodeRunResponse`](#forecastwarningsautomoderunresponse) |
| `forecast.warnings.dismiss` | [`ForecastWarningsDismissRequest`](#forecastwarningsdismissrequest) | [`ForecastWarningsDismissResponse`](#forecastwarningsdismissresponse) |
| `forecast.warnings.list` | [`ForecastWarningsListRequest`](#forecastwarningslistrequest) | [`ForecastWarningsListResponse`](#forecastwarningslistresponse) |
| `forecast.warnings.resolve` | [`ForecastWarningsResolveRequest`](#forecastwarningsresolverequest) | [`ForecastWarningsResolveResponse`](#forecastwarningsresolveresponse) |
| `forecast.workspace` | [`ForecastWorkspaceRequest`](#forecastworkspacerequest) | [`ForecastWorkspaceResponse`](#forecastworkspaceresponse) |
| `image.attach` | [`ImageAttachRequest`](#imageattachrequest) | [`ImageAttachResponse`](#imageattachresponse) |
| `input.detect_drop` | [`InputDetectDropRequest`](#inputdetectdroprequest) | [`InputDetectDropResponse`](#inputdetectdropresponse) |
| `jobs.active` | [`JobsActiveRequest`](#jobsactiverequest) | [`JobsActiveResponse`](#jobsactiveresponse) |
| `jobs.cancel` | [`JobsCancelRequest`](#jobscancelrequest) | [`JobsCancelResponse`](#jobscancelresponse) |
| `jobs.start` | [`JobsStartRequest`](#jobsstartrequest) | [`JobsStartResponse`](#jobsstartresponse) |
| `jobs.status` | [`JobsStatusRequest`](#jobsstatusrequest) | [`JobsStatusResponse`](#jobsstatusresponse) |
| `market.quotes` | [`MarketQuotesRequest`](#marketquotesrequest) | [`MarketQuotesResponse`](#marketquotesresponse) |
| `market.search` | [`MarketSearchRequest`](#marketsearchrequest) | [`MarketSearchResponse`](#marketsearchresponse) |
| `model.options` | [`ModelOptionsRequest`](#modeloptionsrequest) | [`ModelOptionsResponse`](#modeloptionsresponse) |
| `obsidian.note` | [`ObsidianNoteRequest`](#obsidiannoterequest) | [`ObsidianNoteResponse`](#obsidiannoteresponse) |
| `obsidian.search` | [`ObsidianSearchRequest`](#obsidiansearchrequest) | [`ObsidianSearchResponse`](#obsidiansearchresponse) |
| `obsidian.status` | [`ObsidianStatusRequest`](#obsidianstatusrequest) | [`ObsidianStatusResponse`](#obsidianstatusresponse) |
| `pm.book` | [`PmBookRequest`](#pmbookrequest) | [`PmBookResponse`](#pmbookresponse) |
| `pm.detail` | [`PmDetailRequest`](#pmdetailrequest) | [`PmDetailResponse`](#pmdetailresponse) |
| `pm.history` | [`PmHistoryRequest`](#pmhistoryrequest) | [`PmHistoryResponse`](#pmhistoryresponse) |
| `pm.list` | [`PmListRequest`](#pmlistrequest) | [`PmListResponse`](#pmlistresponse) |
| `pm.stream.start` | [`PmStreamStartRequest`](#pmstreamstartrequest) | [`PMStreamStart`](#pmstreamstart) |
| `pm.stream.stop` | [`PmStreamStopRequest`](#pmstreamstoprequest) | [`PmStreamStopResponse`](#pmstreamstopresponse) |
| `process.stop` | [`ProcessStopRequest`](#processstoprequest) | [`ProcessStopResponse`](#processstopresponse) |
| `prompt.background` | [`PromptBackgroundRequest`](#promptbackgroundrequest) | [`BackgroundStartResponse`](#backgroundstartresponse) |
| `prompt.submit` | [`PromptSubmitRequest`](#promptsubmitrequest) | [`PromptSubmitResponse`](#promptsubmitresponse) |
| `reload.env` | [`ReloadEnvRequest`](#reloadenvrequest) | [`ReloadEnvResponse`](#reloadenvresponse) |
| `reload.mcp` | [`ReloadMcpRequest`](#reloadmcprequest) | [`ReloadMcpResponse`](#reloadmcpresponse) |
| `rollback.diff` | [`RollbackDiffRequest`](#rollbackdiffrequest) | [`RollbackDiffResponse`](#rollbackdiffresponse) |
| `rollback.list` | [`RollbackListRequest`](#rollbacklistrequest) | [`RollbackListResponse`](#rollbacklistresponse) |
| `rollback.restore` | [`RollbackRestoreRequest`](#rollbackrestorerequest) | [`RollbackRestoreResponse`](#rollbackrestoreresponse) |
| `secret.respond` | [`RespondRequest`](#respondrequest) | [`SecretRespondResponse`](#secretrespondresponse) |
| `session.branch` | [`SessionBranchRequest`](#sessionbranchrequest) | [`SessionBranchResponse`](#sessionbranchresponse) |
| `session.close` | [`SessionCloseRequest`](#sessioncloserequest) | [`SessionCloseResponse`](#sessioncloseresponse) |
| `session.compress` | [`SessionCompressRequest`](#sessioncompressrequest) | [`SessionCompressResponse`](#sessioncompressresponse) |
| `session.create` | [`SessionCreateRequest`](#sessioncreaterequest) | [`SessionCreateResponse`](#sessioncreateresponse) |
| `session.delete` | [`SessionDeleteRequest`](#sessiondeleterequest) | [`SessionDeleteResponse`](#sessiondeleteresponse) |
| `session.history` | [`SessionHistoryRequest`](#sessionhistoryrequest) | [`SessionHistoryResponse`](#sessionhistoryresponse) |
| `session.interrupt` | [`SessionInterruptRequest`](#sessioninterruptrequest) | [`SessionInterruptResponse`](#sessioninterruptresponse) |
| `session.list` | [`SessionListRequest`](#sessionlistrequest) | [`SessionListResponse`](#sessionlistresponse) |
| `session.most_recent` | [`SessionMostRecentRequest`](#sessionmostrecentrequest) | [`SessionMostRecentResponse`](#sessionmostrecentresponse) |
| `session.resume` | [`SessionResumeRequest`](#sessionresumerequest) | [`SessionResumeResponse`](#sessionresumeresponse) |
| `session.save` | [`SessionSaveRequest`](#sessionsaverequest) | [`SessionSaveResponse`](#sessionsaveresponse) |
| `session.status` | [`SessionStatusRequest`](#sessionstatusrequest) | [`SessionStatusResponse`](#sessionstatusresponse) |
| `session.steer` | [`SessionSteerRequest`](#sessionsteerrequest) | [`SessionSteerResponse`](#sessionsteerresponse) |
| `session.title` | [`SessionTitleRequest`](#sessiontitlerequest) | [`SessionTitleResponse`](#sessiontitleresponse) |
| `session.undo` | [`SessionUndoRequest`](#sessionundorequest) | [`SessionUndoResponse`](#sessionundoresponse) |
| `session.usage` | [`SessionUsageRequest`](#sessionusagerequest) | [`SessionUsageResponse`](#sessionusageresponse) |
| `setup.status` | [`SetupStatusRequest`](#setupstatusrequest) | [`SetupStatusResponse`](#setupstatusresponse) |
| `shell.exec` | [`ShellExecRequest`](#shellexecrequest) | [`ShellExecResponse`](#shellexecresponse) |
| `slash.exec` | [`SlashExecRequest`](#slashexecrequest) | [`SlashExecResponse`](#slashexecresponse) |
| `spawn_tree.list` | [`SpawnTreeListRequest`](#spawntreelistrequest) | [`SpawnTreeListResponse`](#spawntreelistresponse) |
| `spawn_tree.load` | [`SpawnTreeLoadRequest`](#spawntreeloadrequest) | [`SpawnTreeLoadResponse`](#spawntreeloadresponse) |
| `subagent.interrupt` | [`SubagentInterruptRequest`](#subagentinterruptrequest) | [`SubagentInterruptResponse`](#subagentinterruptresponse) |
| `sudo.respond` | [`RespondRequest`](#respondrequest) | [`SudoRespondResponse`](#sudorespondresponse) |
| `terminal.resize` | [`TerminalResizeRequest`](#terminalresizerequest) | [`TerminalResizeResponse`](#terminalresizeresponse) |
| `theme.list` | [`ThemeListRequest`](#themelistrequest) | [`ThemeListResponse`](#themelistresponse) |
| `tools.configure` | [`ToolsConfigureRequest`](#toolsconfigurerequest) | [`ToolsConfigureResponse`](#toolsconfigureresponse) |
| `voice.record` | [`VoiceRecordRequest`](#voicerecordrequest) | [`VoiceRecordResponse`](#voicerecordresponse) |
| `voice.stop` | [`VoiceRecordRequest`](#voicerecordrequest) | [`VoiceRecordResponse`](#voicerecordresponse) |
| `voice.toggle` | [`VoiceToggleRequest`](#voicetogglerequest) | [`VoiceToggleResponse`](#voicetoggleresponse) |

## Events


| event | payload |
| --- | --- |
| `approval.request` | [`ApprovalRequestPayload`](#approvalrequestpayload) |
| `background.complete` | [`BackgroundCompletePayload`](#backgroundcompletepayload) |
| `browser.progress` | [`BrowserProgressPayload`](#browserprogresspayload) |
| `clarify.request` | [`ClarifyRequestPayload`](#clarifyrequestpayload) |
| `cron.fired` | [`CronFiredPayload`](#cronfiredpayload) |
| `error` | [`ErrorPayload`](#errorpayload) |
| `forecast.warnings.automode.complete` | [`AutomodeCompletePayload`](#automodecompletepayload) |
| `forecast.warnings.automode.error` | [`AutomodeErrorPayload`](#automodeerrorpayload) |
| `forecast.warnings.automode.progress` | [`AutomodeProgressPayload`](#automodeprogresspayload) |
| `gateway.protocol_error` | [`GatewayProtocolErrorPayload`](#gatewayprotocolerrorpayload) |
| `gateway.ready` | [`GatewayReadyPayload`](#gatewayreadypayload) |
| `gateway.start_timeout` | [`GatewayStartTimeoutPayload`](#gatewaystarttimeoutpayload) |
| `gateway.stderr` | [`GatewayStderrPayload`](#gatewaystderrpayload) |
| `jobs.complete` | [`JobCompletePayload`](#jobcompletepayload) |
| `jobs.error` | [`JobErrorPayload`](#joberrorpayload) |
| `jobs.progress` | [`JobProgressPayload`](#jobprogresspayload) |
| `markets.model.complete` | [`MarketModelCompletePayload`](#marketmodelcompletepayload) |
| `markets.model.error` | [`MarketModelErrorPayload`](#marketmodelerrorpayload) |
| `markets.model.progress` | [`MarketModelProgressPayload`](#marketmodelprogresspayload) |
| `markets.model.refreshed` | [`MarketModelRefreshedPayload`](#marketmodelrefreshedpayload) |
| `message.complete` | [`MessageCompletePayload`](#messagecompletepayload) |
| `message.delta` | [`MessageDeltaPayload`](#messagedeltapayload) |
| `message.start` | [`MessageStartPayload`](#messagestartpayload) |
| `pm.tick` | [`PMTickPayload`](#pmtickpayload) |
| `reasoning.available` | [`ReasoningAvailablePayload`](#reasoningavailablepayload) |
| `reasoning.delta` | [`ReasoningDeltaPayload`](#reasoningdeltapayload) |
| `review.summary` | [`ReviewSummaryPayload`](#reviewsummarypayload) |
| `review.sweep` | [`ReviewSweepPayload`](#reviewsweeppayload) |
| `secret.request` | [`SecretRequestPayload`](#secretrequestpayload) |
| `session.info` | [`SessionInfoPayload`](#sessioninfopayload) |
| `skin.changed` | [`SkinPayload`](#skinpayload) |
| `status.update` | [`StatusUpdatePayload`](#statusupdatepayload) |
| `subagent.complete` | [`SubagentEventDTO`](#subagenteventdto) |
| `subagent.progress` | [`SubagentEventDTO`](#subagenteventdto) |
| `subagent.spawn_requested` | [`SubagentEventDTO`](#subagenteventdto) |
| `subagent.start` | [`SubagentEventDTO`](#subagenteventdto) |
| `subagent.thinking` | [`SubagentEventDTO`](#subagenteventdto) |
| `subagent.tool` | [`SubagentEventDTO`](#subagenteventdto) |
| `sudo.request` | [`SudoRequestPayload`](#sudorequestpayload) |
| `thinking.delta` | [`ThinkingDeltaPayload`](#thinkingdeltapayload) |
| `tool.complete` | [`ToolCompletePayload`](#toolcompletepayload) |
| `tool.generating` | [`ToolGeneratingPayload`](#toolgeneratingpayload) |
| `tool.progress` | [`ToolProgressPayload`](#toolprogresspayload) |
| `tool.start` | [`ToolStartPayload`](#toolstartpayload) |
| `voice.status` | [`VoiceStatusPayload`](#voicestatuspayload) |
| `voice.transcript` | [`VoiceTranscriptPayload`](#voicetranscriptpayload) |

## Model schemas


Every model reachable from the registry, sorted by name. Types mirror the generated TypeScript (`list[X]` → `X[]`, `X | None` → nullable, `?` marks a conditionally-emitted key).

### AckRequestBody

| field | type |
| --- | --- |
| `correlation_id` | `string` |
| `intent` | `string` |
| `note` | `string | null` |
| `question_ref` | `SfpQuestionRef | null` |
| `request_kind` | `string | null` |
| `signal` | `string | null` |

### AgentProcess

| field | type |
| --- | --- |
| `command` | `string` |
| `session_id` | `string` |
| `status` | `string` |
| `uptime` | `number` |

### AgentsActiveKinds

| field | type |
| --- | --- |
| `procs` | `number` |
| `quorum` | `number` |
| `reforecast` | `number` |

### AgentsActiveSummaryRequest

_(no fields)_

### AgentsActiveSummaryResponse

| field | type |
| --- | --- |
| `count` | `number` |
| `headline` | `string` |
| `kinds` | `AgentsActiveKinds` |

### AgentsListRequest

_(no fields)_

### AgentsListResponse

| field | type |
| --- | --- |
| `processes` | `AgentProcess[]` |

### ApprovalRequestPayload

| field | type |
| --- | --- |
| `command` | `string` |
| `description` | `string` |
| `request_id` | `string?` |

### ApprovalRespondResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### AutomodeCompletePayload

| field | type |
| --- | --- |
| `cancelled` | `boolean?` |
| `dry_run` | `boolean?` |
| `failures` | `Record<string, unknown>?` |
| `job_id` | `string` |
| `processed` | `number?` |
| `tally` | `Record<string, unknown>?` |
| `total` | `number?` |

### AutomodeErrorPayload

| field | type |
| --- | --- |
| `job_id` | `string` |
| `message` | `string?` |

### AutomodeProgressPayload

| field | type |
| --- | --- |
| `alert_id` | `string?` |
| `cancelled` | `boolean?` |
| `done` | `number?` |
| `dry_run` | `boolean?` |
| `failures` | `Record<string, unknown>?` |
| `job_id` | `string` |
| `phase` | `string?` |
| `reason` | `string?` |
| `remaining` | `number?` |
| `status` | `string?` |
| `total` | `number?` |

### BackgroundCompletePayload

| field | type |
| --- | --- |
| `task_id` | `string` |
| `text` | `string` |

### BackgroundStartResponse

| field | type |
| --- | --- |
| `task_id` | `string?` |

### BrowserManageRequest

| field | type |
| --- | --- |
| `action` | `string | null` |

### BrowserManageResponse

| field | type |
| --- | --- |
| `connected` | `boolean?` |
| `messages` | `string[]?` |
| `url` | `string?` |

### BrowserProgressPayload

| field | type |
| --- | --- |
| `level` | `string?` |
| `message` | `string?` |

### ClarifyRequestPayload

| field | type |
| --- | --- |
| `choices` | `string[] | null` |
| `question` | `string` |
| `request_id` | `string` |

### ClarifyRespondRequest

| field | type |
| --- | --- |
| `request_id` | `string | null` |
| `session_id` | `string | null` |

### ClarifyRespondResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### ClipboardPasteRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### ClipboardPasteResponse

| field | type |
| --- | --- |
| `attached` | `boolean?` |
| `count` | `number?` |
| `height` | `number?` |
| `message` | `string?` |
| `token_estimate` | `number?` |
| `width` | `number?` |

### CommandsCatalogRequest

_(no fields)_

### CommandsCatalogResponse

| field | type |
| --- | --- |
| `canon` | `Record<string, string>?` |
| `categories` | `SlashCategory[]?` |
| `pairs` | `[string, string][]?` |
| `skill_count` | `number?` |
| `sub` | `Record<string, string[]>?` |
| `warning` | `string?` |

### CompletionRequest

| field | type |
| --- | --- |
| `text` | `string | null` |

### CompletionResponse

| field | type |
| --- | --- |
| `items` | `GatewayCompletionItem[]?` |
| `replace_from` | `number?` |

### ConfigDisplayConfig

| field | type |
| --- | --- |
| `bell_on_complete` | `boolean?` |
| `busy_input_mode` | `string?` |
| `details_mode` | `string?` |
| `inline_diffs` | `boolean?` |
| `mouse_tracking` | `boolean | number | string? | null` |
| `sections` | `Record<string, string>?` |
| `show_cost` | `boolean?` |
| `show_reasoning` | `boolean?` |
| `streaming` | `boolean?` |
| `thinking_mode` | `string?` |
| `tui_auto_resume_recent` | `boolean?` |
| `tui_compact` | `boolean?` |
| `tui_mouse` | `boolean | number | string? | null` |
| `tui_status_indicator` | `string?` |
| `tui_statusbar` | `'bottom' | 'off' | 'on' | 'top' | boolean?` |

### ConfigFullConfig

| field | type |
| --- | --- |
| `display` | `ConfigDisplayConfig?` |
| `voice` | `ConfigVoiceConfig?` |

### ConfigFullResponse

| field | type |
| --- | --- |
| `config` | `ConfigFullConfig?` |

### ConfigGetValueRequest

| field | type |
| --- | --- |
| `key` | `string | null` |

### ConfigGetValueResponse

| field | type |
| --- | --- |
| `display` | `string?` |
| `home` | `string?` |
| `value` | `string?` |

### ConfigMtimeResponse

| field | type |
| --- | --- |
| `mtime` | `number?` |

### ConfigSetRequest

| field | type |
| --- | --- |
| `key` | `string | null` |
| `session_id` | `string | null` |
| `value` | `string | null` |

### ConfigSetResponse

| field | type |
| --- | --- |
| `credential_warning` | `string?` |
| `history_reset` | `boolean?` |
| `info` | `SessionInfo?` |
| `value` | `string?` |
| `warning` | `string?` |

### ConfigVoiceConfig

| field | type |
| --- | --- |
| `record_key` | `unknown?` |

### CronFiredPayload

| field | type |
| --- | --- |
| `count` | `number?` |

### DelegationActiveEntry

| field | type |
| --- | --- |
| `depth` | `number?` |
| `goal` | `string?` |
| `model` | `string? | null` |
| `parent_id` | `string? | null` |
| `started_at` | `number?` |
| `status` | `string?` |
| `subagent_id` | `string?` |
| `tool_count` | `number?` |

### DelegationPauseRequest

| field | type |
| --- | --- |
| `paused` | `boolean | null` |

### DelegationPauseResponse

| field | type |
| --- | --- |
| `paused` | `boolean?` |

### DelegationStatusRequest

_(no fields)_

### DelegationStatusResponse

| field | type |
| --- | --- |
| `active` | `DelegationActiveEntry[]?` |
| `max_concurrent_children` | `number?` |
| `max_spawn_depth` | `number?` |
| `paused` | `boolean?` |

### ErrorPayload

| field | type |
| --- | --- |
| `message` | `string` |

### EvidenceShareBody

| field | type |
| --- | --- |
| `available_at` | `string | null` |
| `captured_at` | `string` |
| `claim` | `string` |
| `evidence_id` | `string | null` |
| `excerpt` | `string | null` |
| `published_at` | `string | null` |
| `sha256` | `string` |
| `source_name` | `string | null` |
| `source_type` | `string` |
| `source_url` | `string | null` |
| `stance` | `string | null` |
| `triage_label` | `string | null` |

### ForecastAnalystNote

| field | type |
| --- | --- |
| `as_of` | `string?` |
| `be_aware` | `string?` |
| `body` | `string?` |
| `created_at` | `string?` |
| `forecast_id` | `string? | null` |
| `generator` | `string?` |
| `headline` | `string?` |
| `how_it_feels` | `string?` |
| `how_it_thinks` | `string?` |
| `kind` | `string?` |
| `looking_for` | `string?` |
| `stance` | `string? | null` |
| `verdict` | `string? | null` |

### ForecastBenchAggregate

| field | type |
| --- | --- |
| `mean_agent_brier` | `number? | null` |
| `mean_brier_edge` | `number? | null` |
| `mean_market_brier` | `number? | null` |
| `n` | `number?` |

### ForecastBenchRequest

| field | type |
| --- | --- |
| `limit` | `number | null` |

### ForecastBenchResponse

| field | type |
| --- | --- |
| `aggregate` | `ForecastBenchAggregate?` |
| `count` | `number?` |
| `generated_at` | `string?` |
| `output` | `string?` |
| `product` | `string?` |
| `resolved_count` | `number?` |
| `rows` | `ForecastBenchRow[]?` |

### ForecastBenchRow

| field | type |
| --- | --- |
| `agent_brier` | `number? | null` |
| `agent_probability` | `number? | null` |
| `agent_probability_display` | `string?` |
| `as_of` | `string? | null` |
| `brier_edge` | `number? | null` |
| `domain` | `string? | null` |
| `id` | `string` |
| `market_brier` | `number? | null` |
| `market_probability` | `number? | null` |
| `market_probability_display` | `string?` |
| `outcome` | `number? | null` |
| `outcome_label` | `string? | null` |
| `resolved` | `boolean?` |
| `resolved_at` | `string? | null` |
| `source` | `string? | null` |
| `title` | `string?` |
| `topics` | `string[]?` |

### ForecastCalibrationBias

| field | type |
| --- | --- |
| `advisory_text` | `string? | null` |
| `ci_high` | `number? | null` |
| `ci_low` | `number? | null` |
| `curve_shape` | `Record<string, unknown>[]?` |
| `direction` | `string? | null` |
| `ece` | `number? | null` |
| `ess` | `number?` |
| `ess_min` | `number?` |
| `horizon_label` | `string? | null` |
| `n` | `number?` |
| `notes` | `string[]?` |
| `pvalue` | `number? | null` |
| `sce_raw` | `number? | null` |
| `sce_shrunk` | `number? | null` |
| `scope_ref` | `string? | null` |
| `scope_type` | `string?` |
| `status` | `string?` |

### ForecastCalibrationBreakdownRow

| field | type |
| --- | --- |
| `bias` | `ForecastCalibrationBias? | null` |
| `calibration_curve_sample_count` | `number?` |
| `count` | `number?` |
| `domain` | `string?` |
| `expected_calibration_error` | `number? | null` |
| `mean_brier` | `number? | null` |
| `mean_predicted` | `number? | null` |
| `observed_frequency` | `number? | null` |
| `origin` | `string?` |

### ForecastCalibrationBucketRow

| field | type |
| --- | --- |
| `bucket` | `string?` |
| `count` | `number?` |
| `mean_brier` | `number? | null` |
| `sample_status` | `string?` |

### ForecastCalibrationCurveRow

| field | type |
| --- | --- |
| `bucket` | `string?` |
| `calibration_gap` | `number? | null` |
| `count` | `number?` |
| `mean_predicted` | `number? | null` |
| `observed_frequency` | `number? | null` |
| `sample_status` | `string?` |

### ForecastCalibrationLesson

| field | type |
| --- | --- |
| `coverage` | `ForecastCalibrationLessonCoverage?` |
| `dormant` | `boolean?` |
| `lesson` | `string? | null` |
| `lesson_id` | `string?` |
| `recommended_adjustment` | `Record<string, unknown>?` |
| `scope` | `string?` |
| `scope_ref` | `string? | null` |
| `scope_type` | `string?` |

### ForecastCalibrationLessonCoverage

| field | type |
| --- | --- |
| `application_rate` | `number?` |
| `applied_count` | `number?` |
| `in_scope_count` | `number?` |
| `last_seen` | `string? | null` |

### ForecastCalibrationRequest

| field | type |
| --- | --- |
| `domain` | `string | null` |
| `origin` | `string | null` |

### ForecastCalibrationResponse

| field | type |
| --- | --- |
| `bias` | `ForecastCalibrationBias? | null` |
| `cohort_scoreboard` | `ForecastCohortScoreboard?` |
| `domain` | `string? | null` |
| `domains` | `ForecastCalibrationBreakdownRow[]?` |
| `lessons` | `ForecastCalibrationLesson[]?` |
| `origin` | `string? | null` |
| `origins` | `ForecastCalibrationBreakdownRow[]?` |
| `summary` | `ForecastCalibrationSummary?` |

### ForecastCalibrationSummary

| field | type |
| --- | --- |
| `buckets` | `ForecastCalibrationBucketRow[]?` |
| `calibration_curve` | `ForecastCalibrationCurveRow[]?` |
| `calibration_curve_sample_count` | `number?` |
| `calibration_eligible` | `boolean? | null` |
| `calibration_trend` | `ForecastCalibrationTrend?` |
| `count` | `number?` |
| `domain` | `string? | null` |
| `ensemble_component_contributions` | `ForecastDashboardCalibrationComponent[]?` |
| `expected_calibration_error` | `number? | null` |
| `forecast_origin` | `string? | null` |
| `horizon` | `string? | null` |
| `max_calibration_error` | `number? | null` |
| `mean_abs_probability_movement_before_close` | `number? | null` |
| `mean_brier` | `number? | null` |
| `mean_log_score` | `number? | null` |
| `mean_predicted` | `number? | null` |
| `mean_probability_movement_before_close` | `number? | null` |
| `mean_sharpness` | `number? | null` |
| `observed_frequency` | `number? | null` |
| `probability_movement_count` | `number?` |
| `question_type_breakdown` | `ForecastDashboardQuestionTypeCalibration[]?` |

### ForecastCalibrationTrend

| field | type |
| --- | --- |
| `direction` | `string?` |
| `windows` | `ForecastCalibrationTrendWindow[]?` |

### ForecastCalibrationTrendWindow

| field | type |
| --- | --- |
| `brier` | `number? | null` |
| `n` | `number?` |
| `period` | `string?` |
| `sce` | `number? | null` |

### ForecastCandidateInterval

| field | type |
| --- | --- |
| `hi` | `number` |
| `lo` | `number` |
| `mid` | `number?` |

### ForecastCardBody

| field | type |
| --- | --- |
| `as_of` | `string` |
| `band` | `SfpBand | null` |
| `criteria_hash` | `string` |
| `distribution` | `Record<string, unknown> | null` |
| `evidence_refs` | `SfpEvidenceRef[]` |
| `horizon_days` | `number | null` |
| `outcome_type` | `string` |
| `probability` | `number | null` |
| `question_id` | `string | null` |
| `question_title` | `string` |
| `rationale_bullets` | `string[]` |

### ForecastCohortScoreboard

| field | type |
| --- | --- |
| `cohorts` | `Record<string, unknown>?` |
| `continuous_scorecard` | `ForecastContinuousScorecard?` |
| `difficulty_adjustment` | `ForecastDifficultyAdjustment?` |
| `pooled_diagnostic` | `ForecastPooledDiagnostic?` |
| `quarantined` | `ForecastQuarantineSummary?` |

### ForecastCommandRequest

| field | type |
| --- | --- |
| `arg` | `string | null` |
| `argv` | `string[] | null` |

### ForecastCommandResponse

| field | type |
| --- | --- |
| `code` | `number?` |
| `output` | `string?` |

### ForecastConfigDecision

| field | type |
| --- | --- |
| `action_threshold` | `string? | null` |
| `decision_deadline` | `string? | null` |
| `decision_owner` | `string? | null` |
| `update_triggers` | `unknown[]?` |

### ForecastConfigGate

| field | type |
| --- | --- |
| `category` | `string?` |
| `default` | `string?` |
| `doc` | `string?` |
| `id` | `string` |
| `label` | `string` |
| `looser` | `boolean?` |
| `severity` | `string` |
| `source` | `string` |

### ForecastConfigRequest

| field | type |
| --- | --- |
| `id` | `string | null` |
| `question_id` | `string | null` |

### ForecastConfigResponse

| field | type |
| --- | --- |
| `cadence` | `string? | null` |
| `decision` | `ForecastConfigDecision?` |
| `gates` | `ForecastConfigGate[]?` |
| `impact` | `string? | null` |
| `next_run_at` | `string? | null` |
| `profile` | `string?` |
| `question_id` | `string?` |
| `thresholds` | `ForecastConfigThreshold[]?` |
| `title` | `string?` |

### ForecastConfigSetRequest

| field | type |
| --- | --- |
| `decision` | `Record<string, unknown> | null` |
| `hooks` | `Record<string, unknown> | null` |
| `id` | `string | null` |
| `question_id` | `string | null` |
| `review_cadence` | `string | null` |

### ForecastConfigThreshold

| field | type |
| --- | --- |
| `default` | `number` |
| `direction` | `string?` |
| `help` | `string?` |
| `integer` | `boolean?` |
| `key` | `string` |
| `label` | `string` |
| `looser` | `boolean?` |
| `maximum` | `number` |
| `minimum` | `number` |
| `rule_ids` | `string[]?` |
| `source` | `string` |
| `value` | `number` |

### ForecastContinuousScorecard

| field | type |
| --- | --- |
| `by_rule` | `Record<string, unknown>?` |
| `domains` | `string[]?` |
| `live_calibration_eligible_n` | `number?` |
| `mean_crps` | `number? | null` |
| `mean_log_score` | `number? | null` |
| `n` | `number?` |

### ForecastDashboardAlert

| field | type |
| --- | --- |
| `acknowledged_at` | `string? | null` |
| `created_at` | `string?` |
| `id` | `string?` |
| `reason` | `string?` |
| `recommended_action` | `string?` |
| `scope_ref` | `string?` |
| `scope_type` | `string?` |
| `severity` | `string?` |

### ForecastDashboardBacktest

| field | type |
| --- | --- |
| `agent_edge` | `number? | null` |
| `agent_mean_brier` | `number? | null` |
| `best_baseline` | `string? | null` |
| `best_baseline_brier` | `number? | null` |
| `case_count` | `number?` |
| `claim_status` | `ForecastDashboardClaimStatus?` |
| `dataset` | `string?` |
| `id` | `string?` |
| `leakage_checks_passed` | `boolean?` |
| `paired_agent_edge` | `number? | null` |
| `paired_agent_edge_ci95_high` | `number? | null` |
| `paired_agent_edge_ci95_low` | `number? | null` |
| `paired_agent_wins` | `number?` |
| `paired_baseline_wins` | `number?` |
| `paired_count` | `number?` |
| `paired_ties` | `number?` |
| `probability_sources` | `string[]?` |

### ForecastDashboardCalibration

| field | type |
| --- | --- |
| `calibration_eligible` | `boolean? | null` |
| `count` | `number?` |
| `domain` | `string? | null` |
| `ensemble_component_contributions` | `ForecastDashboardCalibrationComponent[]?` |
| `forecast_origin` | `string? | null` |
| `horizon` | `string? | null` |
| `mean_abs_probability_movement_before_close` | `number? | null` |
| `mean_brier` | `number? | null` |
| `mean_log_score` | `number? | null` |
| `mean_probability_movement_before_close` | `number? | null` |
| `mean_sharpness` | `number? | null` |
| `probability_movement_count` | `number?` |
| `question_type_breakdown` | `ForecastDashboardQuestionTypeCalibration[]?` |

### ForecastDashboardCalibrationComponent

| field | type |
| --- | --- |
| `count` | `number?` |
| `mean_abs_distance_from_forecast` | `number? | null` |
| `mean_contribution` | `number? | null` |
| `mean_probability` | `number? | null` |
| `mean_weight` | `number? | null` |
| `mean_weight_share` | `number? | null` |
| `name` | `string?` |

### ForecastDashboardClaimStatus

| field | type |
| --- | --- |
| `can_claim_live_superforecasting` | `boolean?` |
| `case_count` | `number?` |
| `evidence_type` | `string?` |
| `leakage_checks_passed` | `boolean?` |
| `message` | `string?` |
| `scored_count` | `number?` |
| `verdict` | `string?` |

### ForecastDashboardDoctor

| field | type |
| --- | --- |
| `claim_live_superforecasting` | `boolean?` |
| `doctor_status` | `string?` |
| `next_action` | `string?` |
| `next_actions` | `ForecastDoctorNextAction[]?` |
| `next_requirement` | `string?` |
| `pilot_gap_count` | `number?` |
| `pilot_passed_checks` | `number?` |
| `pilot_status` | `string?` |
| `pilot_total_checks` | `number?` |
| `readiness_gap_count` | `number?` |
| `readiness_verdict` | `string?` |
| `scheduled_review_run_count` | `number?` |
| `tester_handoff_ready` | `boolean?` |

### ForecastDashboardErrorProfile

| field | type |
| --- | --- |
| `domain` | `string? | null` |
| `id` | `string?` |
| `mean_brier` | `number? | null` |
| `question_type` | `string? | null` |
| `recommended_adjustments` | `string[]?` |
| `recurring_errors` | `string[]?` |
| `sample_count` | `number?` |
| `topic` | `string? | null` |
| `updated_at` | `string? | null` |

### ForecastDashboardEvidenceStatus

| field | type |
| --- | --- |
| `backtests` | `ForecastEvidenceBacktests?` |
| `can_claim_live_superforecasting` | `boolean?` |
| `gaps` | `string[]?` |
| `message` | `string?` |
| `next_actions` | `ForecastEvidenceNextAction[]?` |
| `requirements` | `ForecastEvidenceRequirement[]?` |
| `score_counts` | `ForecastEvidenceScoreCounts?` |
| `verdict` | `string?` |

### ForecastDashboardFactor

| field | type |
| --- | --- |
| `coverage` | `number? | null` |
| `cvar` | `number? | null` |
| `delta` | `number? | null` |
| `domain` | `string? | null` |
| `downside` | `number? | null` |
| `id` | `string?` |
| `mean` | `number? | null` |
| `member_count` | `number?` |
| `q05` | `number? | null` |
| `q95` | `number? | null` |
| `sd` | `number? | null` |
| `status` | `string?` |
| `title` | `string?` |
| `units` | `string? | null` |

### ForecastDashboardLearning

| field | type |
| --- | --- |
| `active_lessons` | `number?` |
| `invalidated_lessons` | `number?` |
| `recent_lessons` | `ForecastDashboardLesson[]?` |
| `tentative_lessons` | `number?` |
| `top_error_profiles` | `ForecastDashboardErrorProfile[]?` |
| `total_lessons` | `number?` |

### ForecastDashboardLesson

| field | type |
| --- | --- |
| `confidence` | `number? | null` |
| `id` | `string?` |
| `lesson` | `string?` |
| `recommended_adjustment` | `Record<string, unknown>?` |
| `scope_ref` | `string? | null` |
| `scope_type` | `string? | null` |
| `source_postmortem_count` | `number?` |
| `source_score_count` | `number?` |
| `status` | `string?` |
| `updated_at` | `string? | null` |

### ForecastDashboardLiveBaseline

| field | type |
| --- | --- |
| `baseline_type` | `string?` |
| `mean_brier` | `number? | null` |
| `mean_brier_improvement_vs_baseline` | `number? | null` |
| `paired_agent_edge_ci95_high` | `number? | null` |
| `paired_agent_edge_ci95_low` | `number? | null` |
| `paired_agent_edge_mean_brier` | `number? | null` |
| `paired_agent_mean_brier` | `number? | null` |
| `paired_agent_wins` | `number?` |
| `paired_baseline_mean_brier` | `number? | null` |
| `paired_baseline_wins` | `number?` |
| `paired_count` | `number?` |
| `paired_ties` | `number?` |
| `source` | `string?` |

### ForecastDashboardLivePerformance

| field | type |
| --- | --- |
| `agent` | `ForecastLivePerformanceAgent?` |
| `baselines` | `ForecastDashboardLiveBaseline[]?` |
| `claim_status` | `ForecastDashboardClaimStatus?` |
| `score_count` | `number?` |

### ForecastDashboardQuestion

| field | type |
| --- | --- |
| `as_of` | `string? | null` |
| `baseline_count` | `number?` |
| `close_time` | `string? | null` |
| `confidence` | `number? | null` |
| `delta` | `number? | null` |
| `domain` | `string? | null` |
| `evidence_count` | `number?` |
| `id` | `string?` |
| `latest_evidence_at` | `string? | null` |
| `latest_evidence_claim` | `string? | null` |
| `latest_evidence_summary` | `string? | null` |
| `latest_rationale` | `string? | null` |
| `open_alert_count` | `number?` |
| `open_assumption_count` | `number?` |
| `open_reference_class_count` | `number?` |
| `probability` | `Record<string, unknown> | number | string? | null` |
| `resolution_time` | `string? | null` |
| `stale_assumption_count` | `number?` |
| `stale_reference_class_count` | `number?` |
| `status` | `string?` |
| `tail_audit` | `ForecastTailAudit? | null` |
| `title` | `string?` |
| `topics` | `string[]?` |

### ForecastDashboardQuestionTypeCalibration

| field | type |
| --- | --- |
| `brier_count` | `number?` |
| `count` | `number?` |
| `mean_brier` | `number? | null` |
| `mean_log_score` | `number? | null` |
| `mean_proper_score` | `number? | null` |
| `mean_sharpness` | `number? | null` |
| `question_type` | `string?` |
| `score_rules` | `string[]?` |

### ForecastDashboardRequest

| field | type |
| --- | --- |
| `fast` | `boolean | null` |
| `limit` | `number | null` |
| `summary_only` | `boolean | null` |

### ForecastDashboardResponse

| field | type |
| --- | --- |
| `output` | `string?` |
| `summary` | `ForecastDashboardSummary?` |

### ForecastDashboardReview

| field | type |
| --- | --- |
| `as_of` | `string? | null` |
| `close_time` | `string? | null` |
| `domain` | `string? | null` |
| `id` | `string?` |
| `latest_evidence_at` | `string? | null` |
| `latest_evidence_claim` | `string? | null` |
| `latest_evidence_summary` | `string? | null` |
| `latest_rationale` | `string? | null` |
| `next_action` | `string?` |
| `priority` | `number?` |
| `probability` | `Record<string, unknown> | number | string? | null` |
| `reasons` | `string[]?` |
| `resolution_time` | `string? | null` |
| `title` | `string?` |

### ForecastDashboardScheduleRun

| field | type |
| --- | --- |
| `alert_count` | `number?` |
| `alert_reasons` | `string[]?` |
| `auto_postmortem` | `boolean?` |
| `auto_score` | `boolean?` |
| `cadence` | `string? | null` |
| `id` | `string?` |
| `learning_review_count` | `number?` |
| `next_run_at` | `string?` |
| `postmortem_count` | `number?` |
| `run_at` | `string?` |
| `scheduled_review_id` | `string?` |
| `scope_ref` | `string? | null` |
| `scope_type` | `string? | null` |
| `score_count` | `number?` |
| `status` | `string?` |

### ForecastDashboardSummary

| field | type |
| --- | --- |
| `active_count` | `number?` |
| `alerts` | `ForecastDashboardAlert[]?` |
| `calibration` | `ForecastDashboardCalibration?` |
| `closing_soon_count` | `number?` |
| `doctor` | `ForecastDashboardDoctor?` |
| `entity_count` | `number?` |
| `evidence_status` | `ForecastDashboardEvidenceStatus?` |
| `factor_count` | `number?` |
| `factors` | `ForecastDashboardFactor[]?` |
| `learning` | `ForecastDashboardLearning?` |
| `live_performance` | `ForecastDashboardLivePerformance?` |
| `open_alert_count` | `number?` |
| `open_assumption_count` | `number?` |
| `open_reference_class_count` | `number?` |
| `product` | `string?` |
| `question_total` | `number?` |
| `questions` | `ForecastDashboardQuestion[]?` |
| `recent_backtests` | `ForecastDashboardBacktest[]?` |
| `review_queue` | `ForecastDashboardReview[]?` |
| `review_queue_count` | `number?` |
| `scheduled_review_run_count` | `number?` |
| `scheduled_review_runs` | `ForecastDashboardScheduleRun[]?` |
| `stale_assumption_count` | `number?` |
| `stale_reference_class_count` | `number?` |
| `theses` | `ForecastDashboardThesis[]?` |
| `thesis_count` | `number?` |

### ForecastDashboardThesis

| field | type |
| --- | --- |
| `coverage` | `number? | null` |
| `delta` | `number? | null` |
| `domain` | `string? | null` |
| `health_display` | `string?` |
| `health_probability` | `number? | null` |
| `id` | `string?` |
| `member_count` | `number?` |
| `n_eff` | `number? | null` |
| `status` | `string?` |
| `thesis_score` | `number? | null` |
| `title` | `string?` |

### ForecastDeskTaskRequest

| field | type |
| --- | --- |
| `instruction` | `string | null` |
| `question_ids` | `string[] | null` |
| `session_id` | `string | null` |

### ForecastDifficultyAdjustment

| field | type |
| --- | --- |
| `limits` | `string?` |
| `method` | `string?` |
| `n_eligible` | `number?` |
| `n_no_anchor` | `number?` |
| `provenance` | `Record<string, unknown>?` |
| `reference_difficulty` | `number? | null` |

### ForecastDoctorNextAction

| field | type |
| --- | --- |
| `action` | `string?` |
| `requirement_id` | `string?` |
| `source` | `string?` |

### ForecastEvidenceBacktests

| field | type |
| --- | --- |
| `agent_protocol_scored_count` | `number?` |
| `distinct_dataset_count` | `number?` |
| `external_dataset_count` | `number?` |
| `external_source_family_count` | `number?` |
| `leakage_free_run_count` | `number?` |
| `positive_best_baseline_edge_run_count` | `number?` |
| `run_count` | `number?` |
| `source_families` | `string[]?` |

### ForecastEvidenceNextAction

| field | type |
| --- | --- |
| `action` | `string?` |
| `requirement_id` | `string?` |

### ForecastEvidenceRequirement

| field | type |
| --- | --- |
| `description` | `string?` |
| `id` | `string?` |
| `observed` | `number?` |
| `passed` | `boolean?` |
| `recommended_action` | `string?` |
| `required` | `number?` |

### ForecastEvidenceScoreCounts

| field | type |
| --- | --- |
| `backtest` | `number?` |
| `imported_baseline` | `number?` |
| `live` | `number?` |

### ForecastFactor

| field | type |
| --- | --- |
| `aggregate_stale` | `boolean?` |
| `analyst_note` | `ForecastAnalystNote? | null` |
| `as_of` | `string? | null` |
| `constituents` | `ForecastFactorConstituent[]?` |
| `coverage` | `number? | null` |
| `cvar` | `number? | null` |
| `delta` | `number? | null` |
| `domain` | `string? | null` |
| `downside` | `number? | null` |
| `freshness` | `string?` |
| `history` | `ForecastFactorHistoryPoint[]?` |
| `id` | `string?` |
| `mean` | `number? | null` |
| `member_count` | `number?` |
| `n_eff` | `number? | null` |
| `q05` | `number? | null` |
| `q50` | `number? | null` |
| `q95` | `number? | null` |
| `question_ids` | `string[]?` |
| `rationale` | `string? | null` |
| `sd` | `number? | null` |
| `snapshot_count` | `number?` |
| `title` | `string?` |
| `topics` | `string[]?` |
| `units` | `string? | null` |
| `volatility` | `number? | null` |

### ForecastFactorConstituent

| field | type |
| --- | --- |
| `contribution` | `number? | null` |
| `direction` | `string?` |
| `flags` | `string[]?` |
| `id` | `string?` |
| `mean` | `number? | null` |
| `sd` | `number? | null` |
| `status` | `string?` |
| `title` | `string? | null` |
| `w_norm` | `number? | null` |
| `weight` | `number? | null` |

### ForecastFactorHistoryPoint

| field | type |
| --- | --- |
| `as_of` | `string?` |
| `band_high` | `number? | null` |
| `band_low` | `number? | null` |
| `created_at` | `string?` |
| `headline_probability` | `number? | null` |
| `volatility` | `number? | null` |

### ForecastHooksPreviewRequest

| field | type |
| --- | --- |
| `max_scan` | `number | null` |
| `rule` | `Record<string, unknown> | null` |

### ForecastHooksPreviewResponse

| field | type |
| --- | --- |
| `applies` | `number?` |
| `capped_at` | `number?` |
| `failing` | `string[]?` |
| `issues` | `Record<string, unknown>[]?` |
| `valid` | `boolean?` |
| `would_block` | `number?` |

### ForecastHooksRemoveRuleRequest

| field | type |
| --- | --- |
| `id` | `string | null` |

### ForecastHooksRemoveRuleResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### ForecastHooksRequest

| field | type |
| --- | --- |
| `question_id` | `string | null` |

### ForecastHooksResponse

| field | type |
| --- | --- |
| `enabled` | `boolean?` |
| `glossary` | `Record<string, unknown>[]?` |
| `operators` | `string[]?` |
| `overrides` | `Record<string, unknown>?` |
| `profile` | `string?` |
| `profiles` | `string[]?` |
| `reasoning_methods` | `Record<string, unknown>[]?` |
| `resolved` | `Record<string, unknown>?` |
| `rules` | `Record<string, unknown>[]?` |
| `user_rules` | `Record<string, unknown>[]?` |

### ForecastHooksSaveRuleRequest

| field | type |
| --- | --- |
| `edit_id` | `string | null` |
| `rule` | `Record<string, unknown> | null` |

### ForecastHooksSaveRuleResponse

| field | type |
| --- | --- |
| `error` | `string?` |
| `issues` | `Record<string, unknown>[]?` |
| `ok` | `boolean?` |

### ForecastHooksSetRequest

| field | type |
| --- | --- |
| `rule_id` | `string | null` |
| `target` | `string | null` |
| `value` | `unknown | null` |

### ForecastHooksSetResponse

| field | type |
| --- | --- |
| `enabled` | `boolean?` |
| `profile` | `string?` |

### ForecastLivePerformanceAgent

| field | type |
| --- | --- |
| `mean_brier` | `number? | null` |
| `mean_log_score` | `number? | null` |

### ForecastNextAction

| field | type |
| --- | --- |
| `action` | `string?` |
| `question_id` | `string?` |
| `reason` | `string?` |
| `score` | `number?` |
| `title` | `string? | null` |

### ForecastOnboardCommitRequest

| field | type |
| --- | --- |
| `spec` | `Record<string, unknown> | null` |

### ForecastOnboardCommitResponse

| field | type |
| --- | --- |
| `committed` | `boolean?` |
| `issues` | `Record<string, unknown>[]?` |
| `question_id` | `string?` |

### ForecastOnboardProposeRequest

| field | type |
| --- | --- |
| `prompt` | `string | null` |
| `spec` | `Record<string, unknown> | null` |

### ForecastOnboardProposeResponse

| field | type |
| --- | --- |
| `committable` | `boolean?` |
| `errors` | `Record<string, unknown>[]?` |
| `issues` | `Record<string, unknown>[]?` |
| `readiness_gaps` | `Record<string, unknown>[]?` |
| `recommended_clarifications` | `Record<string, unknown>[]?` |
| `spec` | `Record<string, unknown>?` |

### ForecastOutcomeSpace

| field | type |
| --- | --- |
| `choices` | `unknown[]?` |
| `type` | `string?` |

### ForecastPooledDiagnostic

| field | type |
| --- | --- |
| `label` | `string?` |
| `mean_brier` | `number? | null` |
| `n` | `number?` |

### ForecastQuarantineSummary

| field | type |
| --- | --- |
| `n` | `number?` |
| `reasons` | `Record<string, unknown>?` |

### ForecastQuestionPacket

| field | type |
| --- | --- |
| `analyst_note` | `ForecastAnalystNote? | null` |
| `analyst_notes` | `ForecastAnalystNote[]?` |
| `assumptions` | `ForecastQuestionPacketAssumption[]?` |
| `baseline_comparisons` | `Record<string, unknown>[]?` |
| `calibration_lessons` | `ForecastDashboardLesson[]?` |
| `corrections` | `Record<string, unknown>[]?` |
| `domain_error_profiles` | `ForecastDashboardErrorProfile[]?` |
| `evidence` | `ForecastQuestionPacketEvidence[]?` |
| `forecast_history` | `ForecastQuestionPacketSnapshot[]?` |
| `informed_by` | `string[]?` |
| `model_runs` | `Record<string, unknown>[]?` |
| `panel_runs` | `ForecastQuestionPacketPanelRun[]?` |
| `postmortems` | `Record<string, unknown>[]?` |
| `question` | `ForecastQuestionPacketQuestion?` |
| `reference_classes` | `ForecastQuestionPacketReferenceClass[]?` |
| `related_forecasts` | `ForecastRelatedView[]?` |
| `related_shared_sources` | `ForecastSharedSource[]?` |
| `resolution` | `Record<string, unknown>? | null` |
| `retrospective` | `ForecastAnalystNote? | null` |
| `scores` | `Record<string, unknown>[]?` |
| `watched_sources` | `Record<string, unknown>[]?` |

### ForecastQuestionPacketAssumption

| field | type |
| --- | --- |
| `id` | `string?` |
| `status` | `string?` |
| `text` | `string?` |

### ForecastQuestionPacketEvidence

| field | type |
| --- | --- |
| `available_at` | `string?` |
| `claim` | `string?` |
| `claim_type` | `string?` |
| `id` | `string?` |
| `published_at` | `string? | null` |
| `relevance_rating` | `number? | null` |
| `reliability_rating` | `number? | null` |
| `source_name` | `string? | null` |
| `source_type` | `string?` |
| `source_url` | `string? | null` |
| `stance` | `string?` |
| `summary` | `string?` |

### ForecastQuestionPacketPanelRun

| field | type |
| --- | --- |
| `aggregate_probability` | `number? | null` |
| `aggregation_method` | `string?` |
| `created_at` | `string?` |
| `estimates` | `ForecastWorkspacePanelEstimate[]?` |
| `id` | `string?` |
| `spread_summary` | `Record<string, number>?` |
| `trim` | `number?` |

### ForecastQuestionPacketQuestion

| field | type |
| --- | --- |
| `close_time` | `string? | null` |
| `created_at` | `string?` |
| `description` | `string?` |
| `domain` | `string? | null` |
| `id` | `string?` |
| `impact` | `string? | null` |
| `next_review_at` | `string? | null` |
| `outcome_space` | `ForecastOutcomeSpace?` |
| `resolution_criteria` | `string?` |
| `resolution_source` | `string? | null` |
| `resolution_time` | `string? | null` |
| `review_cadence` | `string? | null` |
| `status` | `string?` |
| `tags` | `string[]?` |
| `title` | `string?` |
| `topics` | `string[]?` |

### ForecastQuestionPacketReferenceClass

| field | type |
| --- | --- |
| `base_rate` | `number? | null` |
| `id` | `string?` |
| `name` | `string?` |
| `status` | `string?` |

### ForecastQuestionPacketResponse

| field | type |
| --- | --- |
| `packet` | `ForecastQuestionPacket?` |
| `related` | `ForecastRelated? | null` |
| `relevant_lessons` | `ForecastDashboardLesson[]?` |

### ForecastQuestionPacketSnapshot

| field | type |
| --- | --- |
| `as_of` | `string?` |
| `change_my_mind` | `string[]?` |
| `confidence` | `number? | null` |
| `ensemble_components` | `Record<string, unknown>? | null` |
| `evidence_refs` | `string[]?` |
| `forecast_id` | `string?` |
| `forecast_origin` | `string?` |
| `metadata` | `ForecastSnapshotMetadata? | null` |
| `method` | `string? | null` |
| `probability_or_distribution` | `Record<string, unknown> | number | string? | null` |
| `rationale` | `string?` |
| `reasons_down` | `string[]?` |
| `reasons_up` | `string[]?` |

### ForecastQuestionReadinessRequest

| field | type |
| --- | --- |
| `question_id` | `string | null` |

### ForecastQuestionReadinessResponse

| field | type |
| --- | --- |
| `gaps` | `ForecastReadinessGap[]` |
| `question_id` | `string?` |
| `score` | `number` |
| `src_count` | `number?` |
| `title` | `string?` |

### ForecastQuestionRequest

| field | type |
| --- | --- |
| `id` | `string | null` |

### ForecastQuorumProgressStep

| field | type |
| --- | --- |
| `at` | `string?` |
| `detail` | `string?` |
| `stage` | `string?` |

### ForecastQuorumRunRef

| field | type |
| --- | --- |
| `created_at` | `string? | null` |
| `run_id` | `string?` |
| `status` | `string?` |

### ForecastQuorumStatusRequest

| field | type |
| --- | --- |
| `run_id` | `string | null` |

### ForecastQuorumStatusResponse

| field | type |
| --- | --- |
| `degraded` | `boolean?` |
| `error` | `string? | null` |
| `panel_run_id` | `string? | null` |
| `progress` | `ForecastQuorumProgressStep[]?` |
| `question_id` | `string? | null` |
| `result` | `ForecastQuorumStatusResult?` |
| `run_id` | `string?` |
| `status` | `string?` |

### ForecastQuorumStatusResult

| field | type |
| --- | --- |
| `aggregate_probability` | `number? | null` |
| `committed_probability` | `number? | null` |
| `degraded` | `boolean?` |
| `disagreement` | `number? | null` |

### ForecastReadiness

| field | type |
| --- | --- |
| `gaps` | `ForecastReadinessGap[]` |
| `score` | `number` |

### ForecastReadinessGap

| field | type |
| --- | --- |
| `fix_hint` | `string` |
| `key` | `string` |
| `label` | `string` |

### ForecastReforecastActiveJob

| field | type |
| --- | --- |
| `created_at` | `string? | null` |
| `done_count` | `number?` |
| `mode` | `string?` |
| `question_ids` | `string[]?` |
| `run_id` | `string?` |
| `status` | `string?` |
| `total` | `number?` |

### ForecastReforecastActiveRequest

| field | type |
| --- | --- |
| `limit` | `number | null` |

### ForecastReforecastActiveResponse

| field | type |
| --- | --- |
| `error` | `string?` |
| `jobs` | `ForecastReforecastActiveJob[]?` |

### ForecastReforecastCurrent

| field | type |
| --- | --- |
| `question_id` | `string?` |
| `stage` | `string?` |
| `title` | `string?` |

### ForecastReforecastMarkResponse

| field | type |
| --- | --- |
| `next_run_at` | `string?` |
| `queued` | `boolean?` |
| `scheduled` | `string?` |

### ForecastReforecastRequest

| field | type |
| --- | --- |
| `id` | `string | null` |

### ForecastReforecastResultRow

| field | type |
| --- | --- |
| `committed` | `boolean?` |
| `error` | `string? | null` |
| `forecast_id` | `string? | null` |
| `question_id` | `string` |
| `quorum_autorun` | `boolean? | null` |
| `saturation` | `number? | null` |
| `title` | `string?` |

### ForecastReforecastStartRequest

| field | type |
| --- | --- |
| `question_ids` | `string[] | null` |
| `session_id` | `string | null` |

### ForecastReforecastStartResponse

| field | type |
| --- | --- |
| `note` | `string?` |
| `run_id` | `string` |
| `total` | `number` |

### ForecastReforecastStatusRequest

| field | type |
| --- | --- |
| `run_id` | `string | null` |

### ForecastReforecastStatusResponse

| field | type |
| --- | --- |
| `current` | `ForecastReforecastCurrent? | null` |
| `done_count` | `number?` |
| `error` | `string? | null` |
| `progress` | `string[]?` |
| `quorums_started` | `number?` |
| `results` | `ForecastReforecastResultRow[]?` |
| `run_id` | `string?` |
| `status` | `string` |
| `task_summary` | `string?` |
| `total` | `number?` |

### ForecastRelated

| field | type |
| --- | --- |
| `forecasts` | `ForecastRelatedView[]?` |
| `informed_by` | `string[]?` |
| `shared_sources` | `ForecastSharedSource[]?` |

### ForecastRelatedView

| field | type |
| --- | --- |
| `as_of` | `string? | null` |
| `be_aware` | `string? | null` |
| `headline_kind` | `string?` |
| `headline_probability` | `number? | null` |
| `id` | `string?` |
| `link_label` | `string? | null` |
| `link_type` | `string?` |
| `note_headline` | `string? | null` |
| `probability_display` | `string?` |
| `reasons_down` | `string[]?` |
| `reasons_up` | `string[]?` |
| `relationship` | `string?` |
| `stance` | `string? | null` |
| `title` | `string?` |
| `verdict` | `string? | null` |

### ForecastReviewsNextRequest

_(no fields)_

### ForecastReviewsNextResponse

| field | type |
| --- | --- |
| `due_count` | `number?` |
| `next_due_at` | `string? | null` |
| `nightly` | `ForecastReviewsNightly?` |
| `sweeper` | `ForecastReviewsSweeper?` |

### ForecastReviewsNightly

| field | type |
| --- | --- |
| `installed` | `boolean?` |
| `last_run_at` | `string? | null` |
| `next_run_at` | `string? | null` |

### ForecastReviewsSweeper

| field | type |
| --- | --- |
| `enabled` | `boolean?` |
| `interval_minutes` | `number?` |
| `next_tick_at` | `string? | null` |
| `running` | `boolean?` |

### ForecastScheduleCronHealth

| field | type |
| --- | --- |
| `errored` | `string[]?` |
| `healthy` | `boolean?` |
| `installed` | `number?` |
| `jobs` | `ForecastScheduleCronJob[]?` |
| `missed` | `string[]?` |

### ForecastScheduleCronJob

| field | type |
| --- | --- |
| `enabled` | `boolean?` |
| `errored` | `boolean?` |
| `id` | `string? | null` |
| `last_error` | `string? | null` |
| `last_run_at` | `string? | null` |
| `last_status` | `string? | null` |
| `missed` | `boolean?` |
| `name` | `string? | null` |
| `next_run_at` | `string? | null` |
| `schedule` | `string? | null` |
| `script` | `string? | null` |

### ForecastScheduleReviewRow

| field | type |
| --- | --- |
| `cadence` | `string? | null` |
| `id` | `string?` |
| `last_run_at` | `string? | null` |
| `next_run_at` | `string? | null` |
| `scope_ref` | `string? | null` |
| `scope_type` | `string? | null` |
| `trigger_reason` | `string? | null` |

### ForecastScheduleStatusRequest

| field | type |
| --- | --- |
| `limit` | `number | null` |

### ForecastScheduleStatusResponse

| field | type |
| --- | --- |
| `cron` | `ForecastScheduleCronHealth?` |
| `healthy` | `boolean?` |
| `scheduled_review_count` | `number?` |
| `scheduled_reviews` | `ForecastScheduleReviewRow[]?` |

### ForecastSharedSource

| field | type |
| --- | --- |
| `kind` | `string?` |
| `shared_with` | `string[]?` |
| `source` | `string?` |

### ForecastSnapshotMetadata

| field | type |
| --- | --- |
| `tail_audit` | `ForecastTailAudit? | null` |

### ForecastTailAudit

| field | type |
| --- | --- |
| `issues` | `string[]?` |
| `null_model` | `ForecastTailNullModel? | null` |
| `outcomes` | `ForecastTailOutcome[]?` |
| `passes` | `boolean?` |
| `residual_cap` | `number?` |
| `threshold` | `number?` |
| `total_mass` | `number?` |
| `unearned_mass` | `number?` |

### ForecastTailNullModel

| field | type |
| --- | --- |
| `agent_tail` | `number?` |
| `excess_tail` | `number?` |
| `floor` | `number?` |
| `null_distribution` | `Record<string, number>?` |
| `null_tail` | `number?` |
| `ratio` | `number?` |
| `within_tolerance` | `boolean?` |

### ForecastTailOutcome

| field | type |
| --- | --- |
| `classification` | `string? | null` |
| `evidence_strength` | `string?` |
| `has_path` | `boolean?` |
| `name` | `string?` |
| `note` | `string?` |
| `path` | `string?` |
| `probability` | `number?` |
| `unearned` | `boolean?` |

### ForecastThesesRequest

_(no fields)_

### ForecastThesesResponse

| field | type |
| --- | --- |
| `factors` | `ForecastFactor[]?` |
| `theses` | `ForecastThesis[]?` |

### ForecastThesis

| field | type |
| --- | --- |
| `aggregate_stale` | `boolean?` |
| `analyst_note` | `ForecastAnalystNote? | null` |
| `as_of` | `string? | null` |
| `components` | `ForecastThesisComponent[]?` |
| `coverage` | `number? | null` |
| `delta` | `number? | null` |
| `domain` | `string? | null` |
| `entities` | `ForecastThesisEntity[]?` |
| `event_band` | `ForecastThesisEventBand? | null` |
| `event_probability` | `number? | null` |
| `freshness` | `string?` |
| `headline_display` | `string?` |
| `headline_probability` | `number? | null` |
| `health_display` | `string?` |
| `health_probability` | `number? | null` |
| `history` | `ForecastThesisHistoryPoint[]?` |
| `id` | `string?` |
| `member_count` | `number?` |
| `n_eff` | `number? | null` |
| `question_ids` | `string[]?` |
| `rationale` | `string? | null` |
| `rho` | `number? | null` |
| `score_band` | `ForecastThesisScoreBand? | null` |
| `snapshot_count` | `number?` |
| `spread` | `Record<string, unknown>? | null` |
| `status` | `string?` |
| `thesis_score` | `number? | null` |
| `title` | `string?` |
| `top_sensitivities` | `ForecastThesisSensitivity[]?` |
| `topics` | `string[]?` |
| `triggers` | `ForecastThesisTrigger[]?` |

### ForecastThesisBadge

| field | type |
| --- | --- |
| `direction` | `string?` |
| `role` | `string? | null` |
| `thesis_id` | `string` |
| `thesis_title` | `string?` |
| `weight` | `number? | null` |

### ForecastThesisComponent

| field | type |
| --- | --- |
| `as_of` | `string? | null` |
| `contribution_pts` | `number? | null` |
| `direction` | `string?` |
| `flags` | `string[]?` |
| `id` | `string?` |
| `latest_belief_display` | `string?` |
| `latest_headline` | `number? | null` |
| `marginal_health_delta` | `number? | null` |
| `outcome_type` | `string? | null` |
| `role` | `string? | null` |
| `s_i` | `number? | null` |
| `s_raw` | `number? | null` |
| `sigma` | `number? | null` |
| `status` | `string?` |
| `title` | `string? | null` |
| `w_norm` | `number? | null` |
| `weight` | `number? | null` |

### ForecastThesisEntity

| field | type |
| --- | --- |
| `action` | `string?` |
| `band` | `number[]? | null` |
| `contributions` | `ForecastThesisComponent[]?` |
| `coverage` | `number? | null` |
| `delta` | `number? | null` |
| `kind` | `string?` |
| `label` | `string?` |
| `n_eff` | `number? | null` |
| `name` | `string?` |
| `score` | `number? | null` |
| `stance` | `string?` |
| `suitability` | `number? | null` |
| `suitability_display` | `string?` |
| `top_driver` | `string? | null` |
| `top_driver_id` | `string? | null` |
| `trend` | `string?` |
| `weight_count` | `number?` |

### ForecastThesisEventBand

| field | type |
| --- | --- |
| `p10` | `number? | null` |
| `p50` | `number? | null` |
| `p90` | `number? | null` |

### ForecastThesisHistoryPoint

| field | type |
| --- | --- |
| `as_of` | `string?` |
| `created_at` | `string?` |
| `event_high` | `number? | null` |
| `event_low` | `number? | null` |
| `headline_probability` | `number? | null` |
| `headline_regime` | `string?` |
| `score_high` | `number? | null` |
| `score_low` | `number? | null` |
| `thesis_score` | `number? | null` |

### ForecastThesisScoreBand

| field | type |
| --- | --- |
| `q05` | `number? | null` |
| `q50` | `number? | null` |
| `q95` | `number? | null` |

### ForecastThesisSensitivity

| field | type |
| --- | --- |
| `delta_p_event` | `number? | null` |
| `direction` | `string?` |
| `member_id` | `string?` |
| `p` | `number? | null` |
| `p_event_at_minus` | `number? | null` |
| `p_event_at_plus` | `number? | null` |
| `sensitivity` | `number? | null` |
| `title` | `string? | null` |

### ForecastThesisTrigger

| field | type |
| --- | --- |
| `better` | `string[]?` |
| `delta` | `number? | null` |
| `direction` | `string?` |
| `less` | `string[]?` |
| `member_id` | `string?` |
| `note` | `string?` |
| `signal` | `string?` |

### ForecastTriageContestedRequest

| field | type |
| --- | --- |
| `limit` | `number | null` |
| `question` | `string | null` |
| `question_id` | `string | null` |

### ForecastTriageContestedResponse

| field | type |
| --- | --- |
| `contested` | `ForecastTriageContestedRow[]?` |
| `count` | `number?` |

### ForecastTriageContestedRow

| field | type |
| --- | --- |
| `alert_id` | `string? | null` |
| `auto_label` | `string? | null` |
| `candidate_ref` | `string? | null` |
| `created_at` | `string? | null` |
| `id` | `string?` |
| `materiality` | `string? | null` |
| `question_id` | `string? | null` |
| `rationale` | `string?` |
| `relevance` | `number? | null` |
| `source` | `string? | null` |
| `summary` | `string?` |
| `title` | `string?` |
| `url` | `string? | null` |

### ForecastTriageRelabelRequest

| field | type |
| --- | --- |
| `adjudications` | `Record<string, unknown>[] | null` |
| `label` | `string | null` |
| `label_id` | `string | null` |

### ForecastTriageRelabelResponse

| field | type |
| --- | --- |
| `count` | `number?` |
| `relabeled` | `Record<string, unknown>[]?` |
| `success` | `boolean?` |

### ForecastVoi

| field | type |
| --- | --- |
| `action` | `string?` |
| `components` | `ForecastVoiComponents?` |
| `rank` | `number?` |
| `reason` | `string?` |
| `score` | `number?` |

### ForecastVoiAlerts

| field | type |
| --- | --- |
| `count` | `number?` |
| `norm` | `number?` |
| `weighted` | `number?` |

### ForecastVoiComponents

| field | type |
| --- | --- |
| `alerts` | `ForecastVoiAlerts?` |
| `amplifier` | `number?` |
| `base` | `number?` |
| `proximity` | `ForecastVoiProximity?` |
| `readiness` | `ForecastVoiReadiness?` |
| `sensitivity` | `ForecastVoiSensitivity?` |
| `staleness` | `ForecastVoiStaleness?` |

### ForecastVoiProximity

| field | type |
| --- | --- |
| `days_until` | `number? | null` |
| `horizon_days` | `number?` |
| `norm` | `number?` |
| `resolve_days` | `number? | null` |
| `weighted` | `number?` |

### ForecastVoiReadiness

| field | type |
| --- | --- |
| `dampen` | `number?` |
| `has_sources` | `boolean?` |
| `src_count` | `number?` |

### ForecastVoiSensitivity

| field | type |
| --- | --- |
| `abs_pp` | `number?` |
| `delta_p_event` | `number? | null` |
| `thesis_id` | `string? | null` |
| `thesis_title` | `string? | null` |

### ForecastVoiStaleness

| field | type |
| --- | --- |
| `age_days` | `number? | null` |
| `cadence_days` | `number?` |
| `norm` | `number?` |
| `ratio` | `number?` |
| `weighted` | `number?` |

### ForecastWarningDismissedItem

| field | type |
| --- | --- |
| `alert_id` | `string?` |
| `dismiss_actor` | `string?` |
| `dismiss_note` | `string?` |
| `dismiss_reason` | `string?` |
| `dismiss_ttl_days` | `number?` |
| `dismissed_at` | `string?` |
| `reason` | `string?` |
| `scope_ref` | `string?` |

### ForecastWarningGroup

| field | type |
| --- | --- |
| `auto_resolvable` | `boolean?` |
| `count` | `number?` |
| `kind` | `string?` |
| `reason` | `string?` |
| `recommended_action` | `string?` |
| `scope_refs` | `string[]?` |
| `severity` | `string?` |

### ForecastWarningResolveResult

| field | type |
| --- | --- |
| `acknowledged` | `boolean?` |
| `alert_id` | `string?` |
| `detail` | `string?` |
| `kind` | `string?` |
| `reason` | `string?` |
| `scope_ref` | `string?` |
| `status` | `string?` |

### ForecastWarningsAgentTier

| field | type |
| --- | --- |
| `reasons` | `ForecastWarningGroup[]?` |
| `stale` | `ForecastWarningsTier?` |
| `total` | `number?` |

### ForecastWarningsAggregateRequest

| field | type |
| --- | --- |
| `reason` | `string | null` |
| `scope` | `string | null` |

### ForecastWarningsAggregateResponse

| field | type |
| --- | --- |
| `agent` | `ForecastWarningsAgentTier?` |
| `free` | `ForecastWarningsTier?` |
| `headline` | `ForecastWarningsHeadline?` |
| `manual` | `ForecastWarningsTier?` |

### ForecastWarningsAutomodeRunRequest

| field | type |
| --- | --- |
| `dry_run` | `boolean | null` |
| `limit` | `number | null` |
| `reason` | `string | null` |
| `scope` | `string | null` |
| `session_id` | `string | null` |

### ForecastWarningsAutomodeRunResponse

| field | type |
| --- | --- |
| `dry_run` | `boolean?` |
| `job_id` | `string?` |

### ForecastWarningsDismissRequest

| field | type |
| --- | --- |
| `actor` | `string | null` |
| `alert_id` | `string | null` |
| `alert_ids` | `string[] | null` |
| `kind` | `unknown | null` |
| `kinds` | `unknown | null` |
| `note` | `string | null` |
| `now` | `string | null` |
| `reason` | `string | null` |
| `scope` | `string | null` |
| `ttl_days` | `number | null` |

### ForecastWarningsDismissResponse

| field | type |
| --- | --- |
| `count` | `number?` |
| `dismissed` | `ForecastWarningDismissedItem[]?` |
| `matched` | `number?` |

### ForecastWarningsHeadline

| field | type |
| --- | --- |
| `agent` | `number?` |
| `free` | `number?` |
| `manual` | `number?` |
| `total` | `number?` |

### ForecastWarningsListRequest

| field | type |
| --- | --- |
| `limit` | `number | null` |
| `reason` | `string | null` |
| `scope` | `string | null` |

### ForecastWarningsListResponse

| field | type |
| --- | --- |
| `group_count` | `number?` |
| `groups` | `ForecastWarningGroup[]?` |
| `open_total` | `number?` |

### ForecastWarningsResolveRequest

| field | type |
| --- | --- |
| `alert_id` | `string | null` |
| `now` | `string | null` |

### ForecastWarningsResolveResponse

| field | type |
| --- | --- |
| `count` | `number?` |
| `results` | `ForecastWarningResolveResult[]?` |

### ForecastWarningsTier

| field | type |
| --- | --- |
| `reasons` | `ForecastWarningGroup[]?` |
| `total` | `number?` |

### ForecastWorkspaceDistribution

| field | type |
| --- | --- |
| `ci50` | `number[]? | null` |
| `ci90` | `number[]? | null` |
| `mean` | `number? | null` |
| `median` | `number? | null` |
| `pmf` | `ForecastWorkspacePmfPoint[]? | null` |
| `sd` | `number? | null` |

### ForecastWorkspaceEvidence

| field | type |
| --- | --- |
| `available_at` | `string?` |
| `claim` | `string?` |
| `claim_type` | `string?` |
| `id` | `string?` |
| `published_at` | `string? | null` |
| `relevance_rating` | `number? | null` |
| `reliability_rating` | `number? | null` |
| `source` | `string?` |
| `source_type` | `string?` |
| `stance` | `string?` |
| `summary` | `string?` |

### ForecastWorkspaceHistoryPoint

| field | type |
| --- | --- |
| `as_of` | `string?` |
| `band_high` | `number? | null` |
| `band_low` | `number? | null` |
| `confidence` | `number? | null` |
| `created_at` | `string?` |
| `forecast_id` | `string?` |
| `forecast_origin` | `string?` |
| `headline_probability` | `number? | null` |
| `method` | `string? | null` |
| `probability` | `Record<string, unknown> | number | string? | null` |
| `rationale` | `string?` |
| `reasons_down_count` | `number?` |
| `reasons_up_count` | `number?` |

### ForecastWorkspaceItem

| field | type |
| --- | --- |
| `action_threshold` | `string? | null` |
| `analyst_note` | `ForecastAnalystNote? | null` |
| `analyst_notes` | `ForecastAnalystNote[]?` |
| `as_of` | `string? | null` |
| `candidate_intervals` | `Record<string, ForecastCandidateInterval>? | null` |
| `change_my_mind` | `string[]?` |
| `close_time` | `string? | null` |
| `closing_soon` | `boolean?` |
| `confidence` | `number? | null` |
| `decision_deadline` | `string? | null` |
| `decision_owner` | `string? | null` |
| `decision_readiness_issues` | `string[]?` |
| `delta` | `number? | null` |
| `distribution` | `ForecastWorkspaceDistribution? | null` |
| `domain` | `string? | null` |
| `evidence` | `ForecastWorkspaceEvidence[]?` |
| `evidence_count` | `number?` |
| `freshness` | `string?` |
| `headline_kind` | `string?` |
| `headline_probability` | `number? | null` |
| `history` | `ForecastWorkspaceHistoryPoint[]?` |
| `id` | `string?` |
| `impact` | `string? | null` |
| `lessons_count` | `number?` |
| `method` | `string? | null` |
| `next_review_at` | `string? | null` |
| `open_alert_count` | `number?` |
| `outcome_choices` | `unknown[]?` |
| `outcome_type` | `string?` |
| `panel` | `ForecastWorkspacePanel? | null` |
| `probability` | `Record<string, unknown> | number | string? | null` |
| `probability_display` | `string?` |
| `quorum_run` | `ForecastQuorumRunRef? | null` |
| `rationale` | `string? | null` |
| `readiness` | `ForecastReadiness? | null` |
| `reasons_down` | `string[]?` |
| `reasons_up` | `string[]?` |
| `related` | `ForecastRelated? | null` |
| `relevant_lessons` | `ForecastDashboardLesson[]?` |
| `resolution` | `ForecastWorkspaceResolution? | null` |
| `resolution_criteria` | `string?` |
| `resolution_time` | `string? | null` |
| `retrospective` | `ForecastAnalystNote? | null` |
| `review_cadence` | `string? | null` |
| `saturation_below_threshold` | `boolean?` |
| `saturation_score` | `number? | null` |
| `scores` | `ForecastWorkspaceScores? | null` |
| `snapshot_count` | `number?` |
| `src_count` | `number?` |
| `status` | `string?` |
| `tail_audit` | `ForecastTailAudit? | null` |
| `thesis_ids` | `ForecastThesisBadge[]?` |
| `title` | `string?` |
| `topics` | `string[]?` |
| `units` | `string? | null` |
| `update_triggers` | `ForecastWorkspaceTrigger[]?` |
| `voi` | `ForecastVoi? | null` |

### ForecastWorkspacePanel

| field | type |
| --- | --- |
| `aggregate_probability` | `number? | null` |
| `aggregation_method` | `string?` |
| `created_at` | `string?` |
| `estimates` | `ForecastWorkspacePanelEstimate[]?` |
| `id` | `string?` |
| `kind` | `string?` |
| `spread` | `Record<string, number>?` |
| `trim` | `number?` |

### ForecastWorkspacePanelEstimate

| field | type |
| --- | --- |
| `belief` | `string? | null` |
| `confidence_high` | `number? | null` |
| `confidence_low` | `number? | null` |
| `crux` | `string? | null` |
| `perspective` | `string?` |
| `probability` | `number? | null` |
| `trimmed` | `boolean?` |
| `weight` | `number? | null` |

### ForecastWorkspacePmfPoint

| field | type |
| --- | --- |
| `label` | `string` |
| `probability` | `number` |

### ForecastWorkspaceRequest

| field | type |
| --- | --- |
| `limit` | `number | null` |

### ForecastWorkspaceResolution

| field | type |
| --- | --- |
| `outcome` | `unknown?` |
| `resolution_status` | `string?` |
| `resolved_at` | `string?` |
| `scoreable` | `boolean?` |

### ForecastWorkspaceResponse

| field | type |
| --- | --- |
| `active_count` | `number?` |
| `bench_count` | `number?` |
| `closing_soon_count` | `number?` |
| `factor_count` | `number?` |
| `factors` | `ForecastFactor[]?` |
| `forecasts` | `ForecastWorkspaceItem[]?` |
| `generated_at` | `string?` |
| `next_actions` | `ForecastNextAction[]?` |
| `open_alert_count` | `number?` |
| `output` | `string?` |
| `product` | `string?` |
| `theses` | `ForecastThesis[]?` |
| `thesis_count` | `number?` |

### ForecastWorkspaceScores

| field | type |
| --- | --- |
| `count` | `number?` |
| `last_bucket` | `string? | null` |
| `last_scored_at` | `string? | null` |
| `mean_brier` | `number? | null` |
| `mean_log_score` | `number? | null` |

### ForecastWorkspaceTrigger

| field | type |
| --- | --- |
| `action` | `string?` |
| `mechanism` | `string?` |
| `notes` | `string?` |
| `source_ref` | `string?` |
| `threshold` | `string?` |
| `window` | `string?` |

### GatewayCompletionItem

| field | type |
| --- | --- |
| `display` | `string` |
| `meta` | `string?` |
| `text` | `string` |

### GatewayProtocolErrorPayload

| field | type |
| --- | --- |
| `preview` | `string?` |

### GatewayReadyPayload

| field | type |
| --- | --- |
| `protocol_version` | `number?` |
| `skin` | `SkinPayload?` |

### GatewaySkin

| field | type |
| --- | --- |
| `appearance` | `string?` |
| `banner_hero` | `string?` |
| `banner_logo` | `string?` |
| `branding` | `Record<string, string>?` |
| `colors` | `Record<string, string>?` |
| `help_header` | `string?` |
| `tool_prefix` | `string?` |

### GatewayStartTimeoutPayload

| field | type |
| --- | --- |
| `cwd` | `string?` |
| `python` | `string?` |
| `stderr_tail` | `string?` |

### GatewayStderrPayload

| field | type |
| --- | --- |
| `line` | `string` |

### GatewayTranscriptMessage

| field | type |
| --- | --- |
| `context` | `string?` |
| `name` | `string?` |
| `role` | `'assistant' | 'system' | 'tool' | 'user'` |
| `text` | `string?` |

### ImageAttachRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### ImageAttachResponse

| field | type |
| --- | --- |
| `height` | `number?` |
| `name` | `string?` |
| `remainder` | `string?` |
| `token_estimate` | `number?` |
| `width` | `number?` |

### InputDetectDropRequest

| field | type |
| --- | --- |
| `text` | `string | null` |

### InputDetectDropResponse

| field | type |
| --- | --- |
| `height` | `number?` |
| `is_image` | `boolean?` |
| `matched` | `boolean?` |
| `name` | `string?` |
| `text` | `string?` |
| `token_estimate` | `number?` |
| `width` | `number?` |

### JobCompletePayload

| field | type |
| --- | --- |
| `job_id` | `string` |
| `result` | `Record<string, unknown>` |
| `type` | `string` |

### JobErrorPayload

| field | type |
| --- | --- |
| `job_id` | `string` |
| `message` | `string` |
| `type` | `string` |

### JobProgressPayload

| field | type |
| --- | --- |
| `job_id` | `string` |
| `progress` | `Record<string, unknown>` |
| `type` | `string` |

### JobRecordDTO

| field | type |
| --- | --- |
| `annotations` | `Record<string, unknown>` |
| `cancel_requested` | `boolean` |
| `created_at` | `string` |
| `current` | `string | null` |
| `done_count` | `number` |
| `error` | `string | null` |
| `job_id` | `string` |
| `policy_decisions` | `Record<string, unknown>[]` |
| `policy_grants` | `string[]` |
| `progress` | `Record<string, unknown>[]` |
| `resolved_policy` | `Record<string, unknown> | null` |
| `result` | `Record<string, unknown> | null` |
| `spec` | `Record<string, unknown>` |
| `status` | `string` |
| `total` | `number | null` |
| `type` | `string` |
| `updated_at` | `string | null` |

### JobsActiveRequest

| field | type |
| --- | --- |
| `types` | `string[] | null` |

### JobsActiveResponse

| field | type |
| --- | --- |
| `count` | `number` |
| `jobs` | `JobRecordDTO[]` |

### JobsCancelRequest

| field | type |
| --- | --- |
| `job_id` | `string` |

### JobsCancelResponse

| field | type |
| --- | --- |
| `cancelled` | `boolean` |
| `found` | `boolean` |
| `job_id` | `string` |

### JobsStartRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |
| `spec` | `Record<string, unknown> | null` |
| `type` | `string` |

### JobsStartResponse

| field | type |
| --- | --- |
| `job_id` | `string` |
| `type` | `string` |

### JobsStatusRequest

| field | type |
| --- | --- |
| `job_id` | `string` |

### JobsStatusResponse

| field | type |
| --- | --- |
| `found` | `boolean` |
| `job` | `JobRecordDTO | null` |

### LessonShareBody

| field | type |
| --- | --- |
| `compiled_rule_preview` | `string | null` |
| `confidence` | `number | null` |
| `effect_size` | `number | null` |
| `lesson` | `string` |
| `lesson_id` | `string | null` |
| `origin_n` | `number | null` |
| `scope_ref` | `string | null` |
| `scope_type` | `string` |
| `status` | `string | null` |

### MarketModelCompletePayload

| field | type |
| --- | --- |
| `id` | `string` |
| `status` | `string?` |
| `version` | `number?` |

### MarketModelErrorPayload

| field | type |
| --- | --- |
| `id` | `string` |
| `message` | `string?` |

### MarketModelProgressPayload

| field | type |
| --- | --- |
| `id` | `string` |
| `message` | `string?` |
| `phase` | `string?` |

### MarketModelRefreshedPayload

| field | type |
| --- | --- |
| `id` | `string` |
| `presentation` | `Record<string, unknown>?` |

### MarketQuotesRequest

| field | type |
| --- | --- |
| `series` | `MarketSeriesRef[]` |

### MarketQuotesResponse

| field | type |
| --- | --- |
| `quotes` | `Quote[]` |

### MarketSearchRequest

| field | type |
| --- | --- |
| `query` | `string` |

### MarketSearchResponse

| field | type |
| --- | --- |
| `results` | `MarketSearchResult[]` |

### MarketSearchResult

| field | type |
| --- | --- |
| `category` | `string` |
| `name` | `string` |
| `provider` | `string` |
| `symbol` | `string` |

### MarketSeriesRef

| field | type |
| --- | --- |
| `category` | `string?` |
| `line` | `string?` |
| `name` | `string?` |
| `provider` | `string` |
| `symbol` | `string` |
| `unit` | `string?` |

### McpServerStatus

| field | type |
| --- | --- |
| `connected` | `boolean` |
| `name` | `string` |
| `tools` | `number` |
| `transport` | `string` |

### MessageCompletePayload

| field | type |
| --- | --- |
| `reasoning` | `string?` |
| `rendered` | `string?` |
| `status` | `string` |
| `text` | `string` |
| `usage` | `Record<string, unknown>` |
| `warning` | `string?` |

### MessageDeltaPayload

| field | type |
| --- | --- |
| `rendered` | `string?` |
| `text` | `string?` |

### MessageStartPayload

_(no fields)_

### ModelOptionProvider

| field | type |
| --- | --- |
| `auth_type` | `string?` |
| `authenticated` | `boolean?` |
| `is_current` | `boolean?` |
| `key_env` | `string?` |
| `models` | `string[]?` |
| `name` | `string` |
| `reasoning_effort_models` | `string[]?` |
| `reasoning_efforts` | `string[]?` |
| `slug` | `string` |
| `supports_reasoning_effort` | `boolean?` |
| `total_models` | `number?` |
| `warning` | `string?` |

### ModelOptionsRequest

_(no fields)_

### ModelOptionsResponse

| field | type |
| --- | --- |
| `model` | `string?` |
| `provider` | `string?` |
| `providers` | `ModelOptionProvider[]?` |
| `reasoning_effort` | `string?` |

### ObsidianNote

| field | type |
| --- | --- |
| `excerpt` | `string?` |
| `folder` | `string?` |
| `links` | `string[]?` |
| `modified` | `string?` |
| `rel_path` | `string?` |
| `size` | `number?` |
| `title` | `string?` |

### ObsidianNoteRequest

| field | type |
| --- | --- |
| `rel_path` | `string | null` |

### ObsidianNoteResponse

| field | type |
| --- | --- |
| `content` | `string?` |
| `rel_path` | `string?` |
| `size` | `number?` |
| `truncated` | `boolean?` |

### ObsidianSearchRequest

| field | type |
| --- | --- |
| `query` | `string | null` |

### ObsidianSearchResponse

| field | type |
| --- | --- |
| `count` | `number?` |
| `query` | `string?` |
| `results` | `ObsidianSearchResult[]?` |

### ObsidianSearchResult

| field | type |
| --- | --- |
| `line` | `number?` |
| `matched_terms` | `number?` |
| `rel_path` | `string?` |
| `score` | `number?` |
| `snippet` | `string?` |
| `title` | `string?` |

### ObsidianStatusRequest

_(no fields)_

### ObsidianStatusResponse

| field | type |
| --- | --- |
| `count` | `number?` |
| `exists` | `boolean?` |
| `notes` | `ObsidianNote[]?` |
| `vault` | `string? | null` |

### PMDistributionDTO

| field | type |
| --- | --- |
| `binary` | `boolean` |
| `close_time` | `string | null` |
| `event_id` | `string` |
| `headline` | `PMDistributionHeadline` |
| `normalized` | `boolean` |
| `notes` | `string[]` |
| `outcomes` | `PMOutcomeDTO[]` |
| `overround` | `number` |
| `title` | `string` |
| `total_volume` | `number` |
| `url` | `string | null` |
| `venue` | `string` |

### PMDistributionHeadline

| field | type |
| --- | --- |
| `close_time` | `string | null` |
| `n` | `number` |
| `top_label` | `string | null` |
| `top_prob` | `number | null` |
| `total_volume` | `number` |

### PMEventDTO

| field | type |
| --- | --- |
| `category` | `string | null` |
| `close_time` | `string | null` |
| `event_id` | `string` |
| `is_binary` | `boolean` |
| `markets` | `PMMarketDTO[]` |
| `mutually_exclusive` | `boolean` |
| `slug` | `string | null` |
| `title` | `string` |
| `url` | `string | null` |
| `venue` | `string` |
| `volume` | `number | null` |

### PMHistoryPointDTO

| field | type |
| --- | --- |
| `p` | `number` |
| `ts` | `number` |

### PMListItem

| field | type |
| --- | --- |
| `distribution` | `PMDistributionDTO` |
| `event` | `PMEventDTO` |

### PMMarketDTO

| field | type |
| --- | --- |
| `close_time` | `string | null` |
| `event_id` | `string | null` |
| `label` | `string` |
| `last_price` | `number | null` |
| `market_id` | `string` |
| `open_interest` | `number | null` |
| `question` | `string` |
| `status` | `string | null` |
| `token_ids` | `string[]` |
| `url` | `string | null` |
| `venue` | `string` |
| `volume` | `number | null` |
| `yes_ask` | `number | null` |
| `yes_bid` | `number | null` |
| `yes_mid` | `number | null` |

### PMOrderBookDTO

| field | type |
| --- | --- |
| `asks` | `PMOrderLevelDTO[]` |
| `best_ask` | `number | null` |
| `best_bid` | `number | null` |
| `bids` | `PMOrderLevelDTO[]` |
| `market_id` | `string` |
| `mid` | `number | null` |
| `tick_size` | `number | null` |
| `timestamp` | `number | null` |
| `venue` | `string` |

### PMOrderLevelDTO

| field | type |
| --- | --- |
| `price` | `number` |
| `size` | `number` |

### PMOutcomeDTO

| field | type |
| --- | --- |
| `label` | `string` |
| `liquid` | `boolean` |
| `market_id` | `string` |
| `prob` | `number` |
| `raw_prob` | `number` |
| `volume` | `number | null` |
| `yes_ask` | `number | null` |
| `yes_bid` | `number | null` |

### PMStreamStart

| field | type |
| --- | --- |
| `reason` | `string?` |
| `streaming` | `boolean` |
| `subscribed` | `string[]?` |

### PMTickPayload

| field | type |
| --- | --- |
| `estimate` | `number | null` |
| `kind` | `string` |
| `market_id` | `string` |
| `payload` | `Record<string, unknown>` |
| `venue` | `string` |

### PmBookRequest

| field | type |
| --- | --- |
| `market_id` | `string` |
| `venue` | `string` |

### PmBookResponse

| field | type |
| --- | --- |
| `book` | `PMOrderBookDTO` |

### PmDetailRequest

| field | type |
| --- | --- |
| `event_id` | `string` |
| `venue` | `string` |

### PmDetailResponse

| field | type |
| --- | --- |
| `distribution` | `PMDistributionDTO` |
| `event` | `PMEventDTO` |

### PmHistoryRequest

| field | type |
| --- | --- |
| `interval` | `string | null` |
| `market_id` | `string` |
| `max_points` | `number | null` |
| `period_interval` | `number | null` |
| `range` | `string | null` |
| `series_ticker` | `string | null` |
| `venue` | `string` |

### PmHistoryResponse

| field | type |
| --- | --- |
| `count` | `number` |
| `points` | `PMHistoryPointDTO[]` |

### PmListRequest

| field | type |
| --- | --- |
| `limit` | `number | null` |
| `query` | `string | null` |
| `tag` | `string | null` |
| `venue` | `string | null` |

### PmListResponse

| field | type |
| --- | --- |
| `count` | `number` |
| `events` | `PMListItem[]` |

### PmStreamStartRequest

| field | type |
| --- | --- |
| `market_ids` | `string[] | null` |
| `venue` | `string` |

### PmStreamStopRequest

| field | type |
| --- | --- |
| `market_ids` | `string[] | null` |
| `venue` | `string` |

### PmStreamStopResponse

| field | type |
| --- | --- |
| `closed` | `boolean?` |
| `remaining` | `string[]?` |
| `stopped` | `boolean` |
| `venue` | `string` |

### ProcessStopRequest

_(no fields)_

### ProcessStopResponse

| field | type |
| --- | --- |
| `killed` | `number?` |

### PromptBackgroundRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |
| `text` | `string | null` |

### PromptSubmitRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |
| `text` | `string | null` |

### PromptSubmitResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### Quote

| field | type |
| --- | --- |
| `asOf` | `number` |
| `category` | `string` |
| `change` | `number | null` |
| `changePct` | `number | null` |
| `currency` | `string | null` |
| `dayHigh` | `number | null` |
| `dayLow` | `number | null` |
| `exchange` | `string | null` |
| `history` | `number[]` |
| `name` | `string` |
| `prevClose` | `number | null` |
| `provider` | `string` |
| `symbol` | `string` |
| `unit` | `string` |
| `value` | `number | null` |
| `volume` | `number | null` |
| `week52High` | `number | null` |
| `week52Low` | `number | null` |

### ReasoningAvailablePayload

| field | type |
| --- | --- |
| `text` | `string?` |

### ReasoningDeltaPayload

| field | type |
| --- | --- |
| `text` | `string?` |

### ReloadEnvRequest

_(no fields)_

### ReloadEnvResponse

| field | type |
| --- | --- |
| `updated` | `number?` |

### ReloadMcpRequest

_(no fields)_

### ReloadMcpResponse

| field | type |
| --- | --- |
| `message` | `string?` |
| `status` | `string?` |

### RespondRequest

| field | type |
| --- | --- |
| `request_id` | `string | null` |
| `session_id` | `string | null` |

### ReviewSummaryPayload

| field | type |
| --- | --- |
| `text` | `string?` |

### ReviewSweepPayload

| field | type |
| --- | --- |
| `alerts` | `number?` |
| `due_count` | `number?` |
| `duration_ms` | `number?` |
| `phase` | `string` |
| `refreshed` | `number?` |

### RollbackCheckpoint

| field | type |
| --- | --- |
| `hash` | `string` |
| `message` | `string?` |
| `timestamp` | `string?` |

### RollbackDiffRequest

| field | type |
| --- | --- |
| `hash` | `string | null` |

### RollbackDiffResponse

| field | type |
| --- | --- |
| `diff` | `string?` |
| `rendered` | `string?` |
| `stat` | `string?` |

### RollbackListRequest

_(no fields)_

### RollbackListResponse

| field | type |
| --- | --- |
| `checkpoints` | `RollbackCheckpoint[]?` |
| `enabled` | `boolean?` |

### RollbackRestoreRequest

| field | type |
| --- | --- |
| `hash` | `string | null` |

### RollbackRestoreResponse

| field | type |
| --- | --- |
| `error` | `string?` |
| `history_removed` | `number?` |
| `message` | `string?` |
| `reason` | `string?` |
| `restored_to` | `string?` |
| `success` | `boolean?` |

### SecretRequestPayload

| field | type |
| --- | --- |
| `env_var` | `string` |
| `metadata` | `Record<string, unknown>?` |
| `prompt` | `string` |
| `request_id` | `string` |

### SecretRespondResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### SessionBranchRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionBranchResponse

| field | type |
| --- | --- |
| `session_id` | `string?` |
| `title` | `string?` |

### SessionCloseRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionCloseResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### SessionCompressRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionCompressResponse

| field | type |
| --- | --- |
| `after_messages` | `number?` |
| `after_tokens` | `number?` |
| `before_messages` | `number?` |
| `before_tokens` | `number?` |
| `info` | `SessionInfo?` |
| `messages` | `GatewayTranscriptMessage[]?` |
| `removed` | `number?` |
| `summary` | `SessionCompressSummary?` |
| `usage` | `Usage?` |

### SessionCompressSummary

| field | type |
| --- | --- |
| `headline` | `string?` |
| `noop` | `boolean?` |
| `note` | `string? | null` |
| `token_line` | `string?` |

### SessionCreateInfo

| field | type |
| --- | --- |
| `config_warning` | `string?` |
| `credential_warning` | `string?` |
| `cwd` | `string?` |
| `fast` | `boolean?` |
| `lazy` | `boolean?` |
| `mcp_servers` | `McpServerStatus[]?` |
| `model` | `string` |
| `profile_name` | `string?` |
| `protocol_version` | `number?` |
| `reasoning_effort` | `string?` |
| `release_date` | `string?` |
| `service_tier` | `string?` |
| `skills` | `Record<string, string[]>` |
| `system_prompt` | `string?` |
| `tools` | `Record<string, string[]>` |
| `update_behind` | `number? | null` |
| `update_command` | `string?` |
| `usage` | `Usage?` |
| `version` | `string?` |

### SessionCreateRequest

| field | type |
| --- | --- |
| `cols` | `number | null` |

### SessionCreateResponse

| field | type |
| --- | --- |
| `info` | `SessionCreateInfo?` |
| `session_id` | `string` |

### SessionDeleteRequest

| field | type |
| --- | --- |
| `session_id` | `string` |

### SessionDeleteResponse

| field | type |
| --- | --- |
| `deleted` | `string` |

### SessionHistoryRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionHistoryResponse

| field | type |
| --- | --- |
| `messages` | `GatewayTranscriptMessage[]?` |

### SessionInfo

| field | type |
| --- | --- |
| `cwd` | `string?` |
| `fast` | `boolean?` |
| `lazy` | `boolean?` |
| `mcp_servers` | `McpServerStatus[]?` |
| `model` | `string` |
| `profile_name` | `string?` |
| `protocol_version` | `number?` |
| `reasoning_effort` | `string?` |
| `release_date` | `string?` |
| `service_tier` | `string?` |
| `skills` | `Record<string, string[]>` |
| `system_prompt` | `string?` |
| `tools` | `Record<string, string[]>` |
| `update_behind` | `number? | null` |
| `update_command` | `string?` |
| `usage` | `Usage?` |
| `version` | `string?` |

### SessionInfoPayload

| field | type |
| --- | --- |
| `cwd` | `string` |
| `fast` | `boolean` |
| `model` | `string` |
| `profile_name` | `string` |
| `protocol_version` | `number?` |
| `reasoning_effort` | `string` |
| `release_date` | `string` |
| `service_tier` | `string` |
| `skills` | `Record<string, unknown>` |
| `tools` | `Record<string, unknown>` |
| `update_behind` | `boolean | null` |
| `update_command` | `string` |
| `usage` | `Record<string, unknown>` |
| `version` | `string` |

### SessionInterruptRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionInterruptResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### SessionListItem

| field | type |
| --- | --- |
| `id` | `string` |
| `message_count` | `number` |
| `preview` | `string` |
| `source` | `string?` |
| `started_at` | `number` |
| `title` | `string` |

### SessionListRequest

_(no fields)_

### SessionListResponse

| field | type |
| --- | --- |
| `sessions` | `SessionListItem[]?` |

### SessionMostRecentRequest

_(no fields)_

### SessionMostRecentResponse

| field | type |
| --- | --- |
| `session_id` | `string? | null` |
| `source` | `string?` |
| `started_at` | `number?` |
| `title` | `string?` |

### SessionResumeRequest

| field | type |
| --- | --- |
| `cols` | `number | null` |
| `session_id` | `string` |

### SessionResumeResponse

| field | type |
| --- | --- |
| `info` | `SessionInfo?` |
| `message_count` | `number?` |
| `messages` | `GatewayTranscriptMessage[]` |
| `resumed` | `string?` |
| `session_id` | `string` |

### SessionSaveRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionSaveResponse

| field | type |
| --- | --- |
| `file` | `string?` |

### SessionStatusRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionStatusResponse

| field | type |
| --- | --- |
| `output` | `string?` |

### SessionSteerRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |
| `text` | `string | null` |

### SessionSteerResponse

| field | type |
| --- | --- |
| `status` | `'queued' | 'rejected'?` |
| `text` | `string?` |

### SessionTitleRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionTitleResponse

| field | type |
| --- | --- |
| `pending` | `boolean?` |
| `session_key` | `string?` |
| `title` | `string?` |

### SessionUndoRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionUndoResponse

| field | type |
| --- | --- |
| `removed` | `number?` |

### SessionUsageRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### SessionUsageResponse

| field | type |
| --- | --- |
| `cache_read` | `number?` |
| `cache_write` | `number?` |
| `calls` | `number?` |
| `compressions` | `number?` |
| `context_max` | `number?` |
| `context_percent` | `number?` |
| `context_used` | `number?` |
| `cost_status` | `'estimated' | 'exact'?` |
| `cost_usd` | `number?` |
| `input` | `number?` |
| `model` | `string?` |
| `output` | `number?` |
| `total` | `number?` |

### SetupStatusRequest

_(no fields)_

### SetupStatusResponse

| field | type |
| --- | --- |
| `provider_configured` | `boolean?` |

### SfpBand

| field | type |
| --- | --- |
| `high` | `number` |
| `label` | `string | null` |
| `low` | `number` |

### SfpEnvelope

| field | type |
| --- | --- |
| `body` | `Record<string, unknown>` |
| `kind` | `string` |
| `sender` | `SfpSender` |
| `ts` | `string` |
| `v` | `number` |

### SfpEvidenceRef

| field | type |
| --- | --- |
| `id` | `string` |
| `title` | `string | null` |

### SfpFilePointer

| field | type |
| --- | --- |
| `bytes` | `number` |
| `encoding` | `string` |
| `filename` | `string | null` |
| `kind` | `string` |
| `sha256` | `string` |

### SfpMemberEstimate

| field | type |
| --- | --- |
| `agent` | `string` |
| `instance_id` | `string | null` |
| `probability` | `number | null` |

### SfpQuestionRef

| field | type |
| --- | --- |
| `criteria_hash` | `string` |
| `question_id` | `string | null` |
| `title` | `string` |

### SfpSender

| field | type |
| --- | --- |
| `agent` | `string` |
| `instance_id` | `string` |
| `team` | `string | null` |

### ShellExecRequest

| field | type |
| --- | --- |
| `command` | `string | null` |

### ShellExecResponse

| field | type |
| --- | --- |
| `code` | `number` |
| `stderr` | `string?` |
| `stdout` | `string?` |

### SkinPayload

| field | type |
| --- | --- |
| `appearance` | `string?` |
| `banner_hero` | `string?` |
| `banner_logo` | `string?` |
| `branding` | `Record<string, unknown>?` |
| `colors` | `Record<string, unknown>?` |
| `help_header` | `string?` |
| `name` | `string?` |
| `tool_prefix` | `string?` |

### SlashCategory

| field | type |
| --- | --- |
| `name` | `string` |
| `pairs` | `[string, string][]` |

### SlashExecRequest

| field | type |
| --- | --- |
| `command` | `string | null` |
| `session_id` | `string | null` |

### SlashExecResponse

| field | type |
| --- | --- |
| `output` | `string?` |
| `warning` | `string?` |

### SpawnTreeListEntry

| field | type |
| --- | --- |
| `count` | `number` |
| `finished_at` | `number?` |
| `label` | `string?` |
| `path` | `string` |
| `session_id` | `string?` |
| `started_at` | `number? | null` |

### SpawnTreeListRequest

_(no fields)_

### SpawnTreeListResponse

| field | type |
| --- | --- |
| `entries` | `SpawnTreeListEntry[]?` |

### SpawnTreeLoadRequest

| field | type |
| --- | --- |
| `path` | `string | null` |

### SpawnTreeLoadResponse

| field | type |
| --- | --- |
| `finished_at` | `number?` |
| `label` | `string?` |
| `session_id` | `string?` |
| `started_at` | `number? | null` |
| `subagents` | `unknown[]?` |

### StatusUpdatePayload

| field | type |
| --- | --- |
| `kind` | `string` |
| `text` | `string` |

### SubagentEventDTO

| field | type |
| --- | --- |
| `api_calls` | `number?` |
| `cost_usd` | `number?` |
| `depth` | `number?` |
| `duration_seconds` | `number?` |
| `files_read` | `string[]?` |
| `files_written` | `string[]?` |
| `goal` | `string` |
| `input_tokens` | `number?` |
| `model` | `string?` |
| `output_tail` | `Record<string, unknown>[]?` |
| `output_tokens` | `number?` |
| `parent_id` | `string?` |
| `reasoning_tokens` | `number?` |
| `status` | `string?` |
| `subagent_id` | `string?` |
| `summary` | `string?` |
| `task_count` | `number` |
| `task_index` | `number` |
| `text` | `string?` |
| `tool_count` | `number?` |
| `tool_name` | `string?` |
| `tool_preview` | `string?` |
| `toolsets` | `string[]?` |

### SubagentEventPayload

| field | type |
| --- | --- |
| `api_calls` | `number?` |
| `cost_usd` | `number?` |
| `depth` | `number?` |
| `duration_seconds` | `number?` |
| `files_read` | `string[]?` |
| `files_written` | `string[]?` |
| `goal` | `string` |
| `input_tokens` | `number?` |
| `iteration` | `number?` |
| `model` | `string?` |
| `output_tail` | `SubagentOutputTailItem[]?` |
| `output_tokens` | `number?` |
| `parent_id` | `string? | null` |
| `reasoning_tokens` | `number?` |
| `status` | `'completed' | 'error' | 'failed' | 'interrupted' | 'queued' | 'running' | 'timeout'?` |
| `subagent_id` | `string?` |
| `summary` | `string?` |
| `task_count` | `number?` |
| `task_index` | `number` |
| `text` | `string?` |
| `tool_count` | `number?` |
| `tool_name` | `string?` |
| `tool_preview` | `string?` |
| `toolsets` | `string[]?` |

### SubagentInterruptRequest

| field | type |
| --- | --- |
| `subagent_id` | `string | null` |

### SubagentInterruptResponse

| field | type |
| --- | --- |
| `found` | `boolean?` |
| `subagent_id` | `string?` |

### SubagentOutputTailItem

| field | type |
| --- | --- |
| `is_error` | `boolean?` |
| `preview` | `string?` |
| `tool` | `string?` |

### SudoRequestPayload

| field | type |
| --- | --- |
| `request_id` | `string` |

### SudoRespondResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### TerminalResizeRequest

| field | type |
| --- | --- |
| `cols` | `number | null` |
| `rows` | `number | null` |
| `session_id` | `string | null` |

### TerminalResizeResponse

| field | type |
| --- | --- |
| `ok` | `boolean?` |

### ThemeListRequest

_(no fields)_

### ThemeListResponse

| field | type |
| --- | --- |
| `active` | `string?` |
| `appearance` | `string?` |
| `themes` | `ThemeOption[]?` |

### ThemeOption

| field | type |
| --- | --- |
| `branding` | `Record<string, string>?` |
| `colors` | `Record<string, string>?` |
| `description` | `string?` |
| `name` | `string` |
| `source` | `string?` |

### ThesisAggregateBody

| field | type |
| --- | --- |
| `aggregate` | `number | null` |
| `aggregate_distribution` | `Record<string, unknown> | null` |
| `disagreement` | `Record<string, unknown> | null` |
| `member_estimates` | `SfpMemberEstimate[]` |
| `method` | `string` |
| `question_ref` | `SfpQuestionRef` |
| `round` | `number` |
| `spread` | `number | null` |

### ThesisRoundBody

| field | type |
| --- | --- |
| `deadline` | `string | null` |
| `facilitator` | `string | null` |
| `note` | `string | null` |
| `participants` | `string[]` |
| `question_refs` | `SfpQuestionRef[]` |
| `round` | `number` |

### ThinkingDeltaPayload

| field | type |
| --- | --- |
| `text` | `string?` |

### ToolCompletePayload

| field | type |
| --- | --- |
| `duration_s` | `number?` |
| `inline_diff` | `string?` |
| `name` | `string?` |
| `summary` | `string?` |
| `todos` | `unknown[]?` |
| `tool_id` | `string` |
| `usage` | `Usage?` |

### ToolGeneratingPayload

| field | type |
| --- | --- |
| `name` | `string?` |

### ToolProgressPayload

| field | type |
| --- | --- |
| `name` | `string?` |
| `preview` | `string?` |

### ToolStartPayload

| field | type |
| --- | --- |
| `context` | `string?` |
| `name` | `string?` |
| `todos` | `unknown[]?` |
| `tool_id` | `string` |

### ToolsConfigureRequest

| field | type |
| --- | --- |
| `action` | `string | null` |
| `names` | `string[] | null` |
| `session_id` | `string | null` |

### ToolsConfigureResponse

| field | type |
| --- | --- |
| `changed` | `string[]?` |
| `enabled_toolsets` | `string[]?` |
| `info` | `SessionInfo?` |
| `missing_servers` | `string[]?` |
| `reset` | `boolean?` |
| `unknown` | `string[]?` |

### Usage

| field | type |
| --- | --- |
| `calls` | `number` |
| `compressions` | `number?` |
| `context_max` | `number?` |
| `context_percent` | `number?` |
| `context_used` | `number?` |
| `cost_status` | `string?` |
| `cost_usd` | `number?` |
| `input` | `number` |
| `output` | `number` |
| `reasoning` | `number?` |
| `total` | `number` |

### VoiceRecordRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### VoiceRecordResponse

| field | type |
| --- | --- |
| `status` | `'busy' | 'recording' | 'stopped'?` |
| `text` | `string?` |

### VoiceStatusPayload

| field | type |
| --- | --- |
| `state` | `string?` |

### VoiceToggleRequest

| field | type |
| --- | --- |
| `session_id` | `string | null` |

### VoiceToggleResponse

| field | type |
| --- | --- |
| `audio_available` | `boolean?` |
| `available` | `boolean?` |
| `details` | `string?` |
| `enabled` | `boolean?` |
| `record_key` | `string?` |
| `stt_available` | `boolean?` |
| `tts` | `boolean?` |

### VoiceTranscriptPayload

| field | type |
| --- | --- |
| `no_speech_limit` | `boolean?` |
| `text` | `string?` |
