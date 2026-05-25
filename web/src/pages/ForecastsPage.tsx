import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  Database,
  Gauge,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  SquareTerminal,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  ForecastDashboardBacktest,
  ForecastDashboardCalibration,
  ForecastDashboardDoctor,
  ForecastDashboardErrorProfile,
  ForecastDashboardEvidenceStatus,
  ForecastDashboardLearning,
  ForecastDashboardLesson,
  ForecastDashboardQuestion,
  ForecastDashboardResponse,
  ForecastDashboardReview,
  ForecastDashboardScheduleRun,
} from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePageHeader } from "@/contexts/usePageHeader";

const EVIDENCE_IMPORTS = [
  {
    command: "forecast sources",
    label: "Discover",
  },
  {
    command: 'forecast import gdelt "<query>" --question <id>',
    label: "News",
  },
  {
    command: "forecast import fivethirtyeight <dataset-or-url> --question <id>",
    label: "Polls",
  },
  {
    command: 'forecast import owid <slug> --entity "<entity>" --question <id>',
    label: "Public data",
  },
  {
    command: "forecast import whogho <indicator-code> --country <ISO3> --question <id>",
    label: "Health",
  },
  {
    command: "forecast import fema <state|disaster-number|query> --question <id>",
    label: "Disasters",
  },
  {
    command: "forecast import eia <series-id-or-api-url> --question <id>",
    label: "Energy",
  },
  {
    command: "forecast import treasury <dataset-path-or-api-url> --question <id>",
    label: "Fiscal",
  },
  {
    command: "forecast import imf <indicator>/<country> --question <id>",
    label: "IMF",
  },
  {
    command: 'forecast import census "<dataset-path?get=...&for=...>" --question <id>',
    label: "Census",
  },
  {
    command: "forecast import socrata <domain>/<dataset-id> --question <id>",
    label: "Open data",
  },
  {
    command: "forecast import ckan <domain>/<query> --question <id>",
    label: "CKAN",
  },
  {
    command: "forecast import stooq <symbol-or-csv-url> --question <id>",
    label: "Market data",
  },
  {
    command: "forecast import yahoo <symbol> --question <id>",
    label: "Charts",
  },
  {
    command: "forecast import coingecko <coin-id> --question <id>",
    label: "Crypto",
  },
  {
    command: 'forecast import crossref "<query-or-DOI>" --question <id>',
    label: "DOI works",
  },
  {
    command: "forecast import wikipediapageviews <project>/<article> --question <id>",
    label: "Attention",
  },
  {
    command: "forecast import githubrepo <owner/repo> --question <id>",
    label: "Repo stats",
  },
  {
    command: "forecast import githubissues <owner/repo> --question <id>",
    label: "Issues",
  },
  {
    command: "forecast import githubcommits <owner/repo> --question <id>",
    label: "Commits",
  },
  {
    command: "forecast import githubactions <owner/repo> --question <id>",
    label: "CI runs",
  },
  {
    command: 'forecast import hackernews "<query>" --question <id>',
    label: "HN",
  },
  {
    command: 'forecast import reddit "<query>" --question <id>',
    label: "Reddit",
  },
  {
    command: 'forecast import bluesky "<query>" --question <id>',
    label: "Bluesky",
  },
  {
    command: "forecast import mastodon <tag-or-instance/tag> --question <id>",
    label: "Mastodon",
  },
  {
    command: 'forecast import reliefweb "<query>" --question <id>',
    label: "ReliefWeb",
  },
  {
    command: "forecast import clinicaltrials <query-or-NCT-id> --question <id>",
    label: "Trials",
  },
  {
    command: "forecast import openfda <query-or-application-number> --question <id>",
    label: "FDA",
  },
  {
    command: 'forecast import pubmed "<query-or-PMID>" --question <id>',
    label: "PubMed",
  },
  {
    command: "forecast import whogho <indicator-code> --country <ISO3> --question <id>",
    label: "WHO GHO",
  },
  {
    command: "forecast import fema <state|disaster-number|query> --question <id>",
    label: "FEMA",
  },
  {
    command: "forecast import pypi <package> --question <id>",
    label: "PyPI",
  },
  {
    command: "forecast import npm <package> --question <id>",
    label: "npm",
  },
  {
    command: "forecast import openmeteo <lat,lon> --question <id>",
    label: "Weather",
  },
  {
    command: "forecast import airquality <lat,lon> --question <id>",
    label: "Air quality",
  },
  {
    command: "forecast import weatherhistory <lat,lon> --start-date <date> --end-date <date> --question <id>",
    label: "Weather history",
  },
  {
    command: 'forecast import usgs "<query>" --question <id>',
    label: "Geophysical",
  },
  {
    command: 'forecast import eonet "<query-or-category>" --question <id>',
    label: "Hazards",
  },
  {
    command: 'forecast import nws "<area-or-point-or-query>" --question <id>',
    label: "Alerts",
  },
  {
    command: 'forecast import nvd "<keyword-or-CVE>" --question <id>',
    label: "Security",
  },
  {
    command: 'forecast import cisakev "<keyword-or-CVE-or-all>" --question <id>',
    label: "Exploited",
  },
  {
    command: 'forecast import federalregister "<query>" --question <id>',
    label: "Policy",
  },
  {
    command: 'forecast import courtlistener "<query>" --question <id>',
    label: "Legal",
  },
  {
    command: "forecast watch add --question <id> <adapter>:<source>",
    label: "Watch",
  },
];

const PILOT_HANDOFFS = [
  {
    command: "cp examples/forecasting/live-cohort.example.csv live-cohort.csv",
    label: "Starter",
  },
  {
    command: "forecast pilot-cohort live-cohort.csv --dry-run --json",
    label: "Validate",
  },
  {
    command: "forecast pilot-cohort live-cohort.csv --schedule-cadence 1d --schedule-next-run-at <time>",
    label: "Seed",
  },
  {
    command: "forecast pilot-report --json",
    label: "Report",
  },
  {
    command: "forecast doctor --json --require-pilot-ready",
    label: "Doctor",
  },
  {
    command: "forecast pilot-bundle --include-export --output .pilot/tester-bundle.json",
    label: "Bundle",
  },
  {
    command: "forecast pilot-aggregate .pilot/*-export.json --json",
    label: "Aggregate",
  },
];

type FocusedForecastRow = ForecastDashboardQuestion | ForecastDashboardReview;

function formatProbability(
  value: ForecastDashboardQuestion["probability"] | ForecastDashboardReview["probability"],
): string {
  if (typeof value === "number") return value.toFixed(3);
  if (value && typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string") return value;
  return "-";
}

function formatDelta(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(3)}`;
}

function formatDate(value?: string | null): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

function formatMetric(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  return value.toFixed(6);
}

function formatBacktestWins(row: ForecastDashboardBacktest): string {
  return `${row.paired_agent_wins ?? 0}/${row.paired_baseline_wins ?? 0}/${row.paired_ties ?? 0}`;
}

function formatBacktestSources(row: ForecastDashboardBacktest): string {
  return (row.probability_sources?.length ? row.probability_sources : ["dataset"]).join(",");
}

function formatBacktestClaim(row: ForecastDashboardBacktest): string {
  if (row.claim_status?.verdict === "benchmark_replay_only") return "replay";
  return row.claim_status?.verdict?.replaceAll("_", " ") || "-";
}

function formatVerdict(value?: string): string {
  return value?.replaceAll("_", " ") || "-";
}

function formatErrorScope(row: ForecastDashboardErrorProfile): string {
  const base = row.domain || "global";
  const topic = row.topic ? `/${row.topic}` : "";
  const questionType = row.question_type ? `:${row.question_type}` : "";
  return `${base}${topic}${questionType}`;
}

function formatLessonScope(row: ForecastDashboardLesson): string {
  return `${row.scope_type || "global"}:${row.scope_ref || "*"}`;
}

function formatScheduleRunScope(row: ForecastDashboardScheduleRun): string {
  if (row.scope_type === "domain_topic" && row.scope_ref) {
    try {
      const parsed = JSON.parse(row.scope_ref) as { domain?: string; topic?: string };
      return `domain:${parsed.domain || "*"}/${parsed.topic || "*"}`;
    } catch {
      return `domain:${row.scope_ref}`;
    }
  }
  return `${row.scope_type || "schedule"}:${row.scope_ref || "*"}`;
}

function isLearnedErrorReviewReason(reason?: string): boolean {
  return (reason ?? "").startsWith("domain_error_profile_applies:");
}

function hasLearnedErrorReview(row: ForecastDashboardReview): boolean {
  return row.reasons.some(isLearnedErrorReviewReason);
}

function formatReviewReason(reason?: string): string {
  return isLearnedErrorReviewReason(reason) ? "learned error profile" : reason || "review";
}

function formatReviewReasons(reasons: string[]): string {
  return reasons.map(formatReviewReason).join(", ");
}

function focusedForecast(
  questions: ForecastDashboardQuestion[],
  reviewQueue: ForecastDashboardReview[],
): FocusedForecastRow | undefined {
  return reviewQueue.find((row) => row.id) ?? questions.find((row) => row.id);
}

function focusedForecastCommands(row: FocusedForecastRow) {
  return [
    {
      command: `forecast show ${row.id}`,
      label: "Show",
    },
    {
      command: `forecast research ${row.id}`,
      label: "Research",
    },
    {
      command: `forecast update ${row.id} --probability <0-1>`,
      label: "Update",
    },
    {
      command: `forecast resolve ${row.id} --outcome <value> --source <url>`,
      label: "Resolve",
    },
  ];
}

function ForecastTable({ rows }: { rows: ForecastDashboardQuestion[] }) {
  if (rows.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-sm text-muted-foreground">
          No active forecasts.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Active Forecasts</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-2 pr-4 text-left font-medium">Question</th>
                <th className="px-4 py-2 text-right font-medium">P(now)</th>
                <th className="px-4 py-2 text-left font-medium">As of</th>
                <th className="px-4 py-2 text-right font-medium">Delta</th>
                <th className="px-4 py-2 text-right font-medium">Confidence</th>
                <th className="px-4 py-2 text-left font-medium">Close</th>
                <th className="px-4 py-2 text-right font-medium">Evidence</th>
                <th className="px-4 py-2 text-right font-medium">Baselines</th>
                <th className="px-4 py-2 text-right font-medium">Ref Classes</th>
                <th className="px-4 py-2 text-right font-medium">Assumptions</th>
                <th className="py-2 pl-4 text-right font-medium">Alerts</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-border/50 transition-colors hover:bg-secondary/20"
                >
                  <td className="max-w-[28rem] py-2 pr-4">
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="truncate font-medium text-foreground">
                        {row.title}
                      </span>
                      <span className="font-mono-ui text-[11px] text-muted-foreground">
                        {row.id}
                        {row.domain ? ` · ${row.domain}` : ""}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-foreground">
                    {formatProbability(row.probability)}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {formatDate(row.as_of)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {formatDelta(row.delta)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {row.confidence == null ? "-" : row.confidence.toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {formatDate(row.close_time)}
                  </td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {row.evidence_count}
                  </td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {row.baseline_count}
                  </td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {row.open_reference_class_count}
                    {row.stale_reference_class_count > 0 && (
                      <span className="text-amber-300">
                        {" "}
                        / {row.stale_reference_class_count}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-muted-foreground">
                    {row.open_assumption_count}
                    {row.stale_assumption_count > 0 && (
                      <span className="text-amber-300">
                        {" "}
                        / {row.stale_assumption_count}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pl-4 text-right">
                    {row.open_alert_count > 0 ? (
                      <Badge tone="warning" className="text-[10px]">
                        {row.open_alert_count}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function FocusedActionsPanel({
  questions,
  reviewQueue,
}: {
  questions: ForecastDashboardQuestion[];
  reviewQueue: ForecastDashboardReview[];
}) {
  const row = focusedForecast(questions, reviewQueue);
  if (!row) return null;
  const reasons = "reasons" in row ? row.reasons : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <SquareTerminal className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Focused Actions</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex min-w-0 flex-col gap-1 text-sm">
          <span className="truncate font-medium text-foreground">{row.title}</span>
          <span className="font-mono-ui text-[11px] text-muted-foreground">
            {row.id}
            {row.domain ? ` · ${row.domain}` : ""}
          </span>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono-ui text-[11px] text-muted-foreground">
            <span>P(now) {formatProbability(row.probability)}</span>
            <span>as of {formatDate(row.as_of)}</span>
            <span>close {formatDate(row.close_time)}</span>
          </div>
          {reasons.length > 0 && (
            <span className="line-clamp-2 text-xs text-muted-foreground">
              {reasons.join(", ")}
            </span>
          )}
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {focusedForecastCommands(row).map((item) => (
            <div
              key={item.label}
              className="flex min-w-0 items-start gap-3 border-t border-border/50 pt-3 text-sm first:border-t-0 first:pt-0 lg:border-t-0 lg:pt-0"
            >
              <Badge tone="secondary" className="mt-0.5 shrink-0 text-[10px]">
                {item.label}
              </Badge>
              <code className="min-w-0 break-all font-mono-ui text-xs text-muted-foreground">
                {item.command}
              </code>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function BacktestTable({ rows }: { rows: ForecastDashboardBacktest[] }) {
  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Recent Backtests</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-2 pr-4 text-left font-medium">Dataset</th>
                <th className="px-4 py-2 text-right font-medium">Cases</th>
                <th className="px-4 py-2 text-left font-medium">Source</th>
                <th className="px-4 py-2 text-right font-medium">Agent Brier</th>
                <th className="px-4 py-2 text-left font-medium">Best Baseline</th>
                <th className="px-4 py-2 text-right font-medium">Edge</th>
                <th className="px-4 py-2 text-right font-medium">W/L/T</th>
                <th className="px-4 py-2 text-right font-medium">Claim</th>
                <th className="py-2 pl-4 text-right font-medium">Leakage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-border/50">
                  <td className="max-w-[22rem] py-2 pr-4">
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="truncate font-medium text-foreground">
                        {row.dataset}
                      </span>
                      <span className="font-mono-ui text-[11px] text-muted-foreground">
                        {row.id}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {row.case_count}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {formatBacktestSources(row)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-foreground">
                    {formatMetric(row.agent_mean_brier)}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {row.best_baseline
                      ? `${row.best_baseline} ${formatMetric(row.best_baseline_brier)}`
                      : "-"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {formatDelta(row.agent_edge)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {formatBacktestWins(row)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Badge
                      tone={row.claim_status?.can_claim_live_superforecasting ? "success" : "secondary"}
                      className="text-[10px]"
                    >
                      {formatBacktestClaim(row)}
                    </Badge>
                  </td>
                  <td className="py-2 pl-4 text-right">
                    <Badge tone={row.leakage_checks_passed ? "secondary" : "warning"} className="text-[10px]">
                      {row.leakage_checks_passed ? "ok" : "review"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function CalibrationPanel({ calibration }: { calibration?: ForecastDashboardCalibration }) {
  if (!calibration) return null;

  const components = calibration.ensemble_component_contributions ?? [];
  const questionTypes = calibration.question_type_breakdown ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Gauge className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Calibration</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-6">
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Eligible Scores
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {calibration.count}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Mean Brier
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {formatMetric(calibration.mean_brier)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Log Score
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {formatMetric(calibration.mean_log_score)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Sharpness
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {formatMetric(calibration.mean_sharpness)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Abs Move
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {formatMetric(calibration.mean_abs_probability_movement_before_close)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Components
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {components.length}
            </div>
          </div>
        </div>
        {components.length > 0 && (
          <div className="mt-5 overflow-x-auto border-t border-border/50 pt-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="py-2 pr-4 text-left font-medium">Component</th>
                  <th className="px-4 py-2 text-right font-medium">N</th>
                  <th className="px-4 py-2 text-right font-medium">Contribution</th>
                  <th className="px-4 py-2 text-right font-medium">Weight Share</th>
                  <th className="py-2 pl-4 text-right font-medium">Mean P</th>
                </tr>
              </thead>
              <tbody>
                {components.slice(0, 6).map((row, index) => (
                  <tr key={row.name || index} className="border-b border-border/50">
                    <td className="py-2 pr-4">
                      <Badge tone="secondary" className="text-[10px]">
                        {row.name || "-"}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                      {row.count ?? 0}
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-foreground">
                      {formatMetric(row.mean_contribution)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                      {formatMetric(row.mean_weight_share)}
                    </td>
                    <td className="py-2 pl-4 text-right font-mono-ui text-muted-foreground">
                      {formatMetric(row.mean_probability)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {questionTypes.length > 0 && (
          <div className="mt-5 overflow-x-auto border-t border-border/50 pt-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="py-2 pr-4 text-left font-medium">Question Type</th>
                  <th className="px-4 py-2 text-right font-medium">N</th>
                  <th className="px-4 py-2 text-right font-medium">Brier N</th>
                  <th className="px-4 py-2 text-right font-medium">Mean Brier</th>
                  <th className="py-2 pl-4 text-right font-medium">Proper Score</th>
                </tr>
              </thead>
              <tbody>
                {questionTypes.slice(0, 6).map((row, index) => (
                  <tr key={row.question_type || index} className="border-b border-border/50">
                    <td className="py-2 pr-4">
                      <Badge tone="secondary" className="text-[10px]">
                        {row.question_type || "-"}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                      {row.count ?? 0}
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                      {row.brier_count ?? 0}
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-foreground">
                      {formatMetric(row.mean_brier)}
                    </td>
                    <td className="py-2 pl-4 text-right font-mono-ui text-muted-foreground">
                      {formatMetric(row.mean_proper_score)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LearningPanel({ learning }: { learning?: ForecastDashboardLearning }) {
  if (!learning) return null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <BrainCircuit className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Learning Memory</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 text-sm sm:grid-cols-4">
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Lessons
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {learning.total_lessons}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Active
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {learning.active_lessons}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Tentative
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {learning.tentative_lessons}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Invalidated
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {learning.invalidated_lessons}
            </div>
          </div>
        </div>

        {learning.top_error_profiles.length > 0 && (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="py-2 pr-4 text-left font-medium">Error Scope</th>
                  <th className="px-4 py-2 text-right font-medium">N</th>
                  <th className="px-4 py-2 text-right font-medium">Mean Brier</th>
                  <th className="py-2 pl-4 text-left font-medium">Recurring Errors</th>
                </tr>
              </thead>
              <tbody>
                {learning.top_error_profiles.slice(0, 5).map((row) => (
                  <tr key={row.id || formatErrorScope(row)} className="border-b border-border/50">
                    <td className="max-w-[18rem] py-2 pr-4 font-mono-ui text-xs text-foreground">
                      <span className="line-clamp-2">{formatErrorScope(row)}</span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                      {row.sample_count}
                    </td>
                    <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                      {formatMetric(row.mean_brier)}
                    </td>
                    <td className="max-w-[24rem] py-2 pl-4 text-muted-foreground">
                      <span className="line-clamp-2">
                        {row.recurring_errors.length > 0
                          ? row.recurring_errors.join(", ")
                          : "-"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {learning.recent_lessons.length > 0 && (
          <div className="mt-5 grid gap-2">
            {learning.recent_lessons.slice(0, 3).map((row) => (
              <div
                key={row.id || `${row.status}:${formatLessonScope(row)}`}
                className="flex min-w-0 flex-col gap-1 border-t border-border/50 pt-3 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={row.status === "active" ? "success" : "secondary"} className="text-[10px]">
                    {row.status}
                  </Badge>
                  <span className="font-mono-ui text-[11px] text-muted-foreground">
                    {formatLessonScope(row)}
                  </span>
                </div>
                <p className="line-clamp-2 text-muted-foreground">{row.lesson}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ScheduledRunsPanel({ rows }: { rows: ForecastDashboardScheduleRun[] }) {
  if (!rows.length) return null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <ListChecks className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Scheduled Self-Checks</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-2 pr-4 text-left font-medium">Run</th>
                <th className="px-4 py-2 text-left font-medium">Scope</th>
                <th className="px-4 py-2 text-right font-medium">Alerts</th>
                <th className="px-4 py-2 text-right font-medium">Scores</th>
                <th className="px-4 py-2 text-right font-medium">Postmortems</th>
                <th className="px-4 py-2 text-right font-medium">Learning</th>
                <th className="py-2 pl-4 text-left font-medium">Next Run</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 6).map((row) => (
                <tr key={row.id || `${row.scheduled_review_id}:${row.run_at}`} className="border-b border-border/50">
                  <td className="py-2 pr-4 font-mono-ui text-xs text-foreground">
                    {row.id || "-"}
                  </td>
                  <td className="max-w-[18rem] px-4 py-2 font-mono-ui text-xs text-muted-foreground">
                    <span className="line-clamp-2">{formatScheduleRunScope(row)}</span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {row.alert_count ?? 0}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {row.score_count ?? 0}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {row.postmortem_count ?? 0}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {row.learning_review_count ?? 0}
                  </td>
                  <td className="py-2 pl-4 font-mono-ui text-xs text-muted-foreground">
                    {formatDate(row.next_run_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function DoctorGatePanel({ doctor }: { doctor?: ForecastDashboardDoctor }) {
  if (!doctor) return null;

  const nextActions = doctor.next_actions ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Doctor Gate</CardTitle>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={doctor.tester_handoff_ready ? "success" : "secondary"}>
              {doctor.tester_handoff_ready ? "tester ready" : "pilot gaps"}
            </Badge>
            <Badge tone={doctor.claim_live_superforecasting ? "success" : "secondary"}>
              {doctor.claim_live_superforecasting ? "live claim ready" : "live claim blocked"}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 text-sm sm:grid-cols-5">
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Status
            </div>
            <div className="mt-1 text-sm text-foreground">
              {formatVerdict(doctor.doctor_status)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Pilot
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {doctor.pilot_passed_checks ?? 0}/{doctor.pilot_total_checks ?? 0}
            </div>
            <div className="text-xs text-muted-foreground">
              {formatVerdict(doctor.pilot_status)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Readiness
            </div>
            <div className="mt-1 text-sm text-foreground">
              {formatVerdict(doctor.readiness_verdict)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Gaps
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {doctor.readiness_gap_count ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Schedule Runs
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {doctor.scheduled_review_run_count ?? 0}
            </div>
          </div>
        </div>
        {nextActions.length > 0 && (
          <div className="mt-4 grid gap-2 text-xs">
            {nextActions.slice(0, 3).map((item) => (
              <div
                key={`${item.source || "doctor"}:${item.requirement_id || ""}:${item.action || ""}`}
                className="rounded-md border border-border/70 px-3 py-2"
              >
                <div className="font-medium text-foreground">
                  {(item.requirement_id || item.source || "doctor").replaceAll("_", " ")}
                </div>
                <div className="mt-1 font-mono-ui text-muted-foreground">
                  {item.action || "forecast doctor --json"}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-2 font-mono-ui text-xs text-muted-foreground">
          forecast doctor --json
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceStatusPanel({ evidenceStatus }: { evidenceStatus?: ForecastDashboardEvidenceStatus }) {
  if (!evidenceStatus) return null;

  const scoreCounts = evidenceStatus.score_counts ?? {};
  const backtests = evidenceStatus.backtests ?? {};
  const gaps = evidenceStatus.gaps?.length
    ? evidenceStatus.gaps.map((gap) => gap.replaceAll("_", " ")).join(", ")
    : "none";
  const nextActions = evidenceStatus.next_actions ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Evidence Status</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 text-sm sm:grid-cols-7">
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Verdict
            </div>
            <div className="mt-1 text-sm text-foreground">
              {formatVerdict(evidenceStatus.verdict)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Live
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {scoreCounts.live ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Agent Protocol
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {backtests.agent_protocol_scored_count ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Edge Runs
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {backtests.positive_best_baseline_edge_run_count ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Datasets
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {backtests.distinct_dataset_count ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              External
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {backtests.external_dataset_count ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Families
            </div>
            <div className="mt-1 font-mono-ui text-lg text-foreground">
              {backtests.external_source_family_count ?? 0}
            </div>
          </div>
        </div>
        <div className="mt-4 rounded-md border border-border/70 px-3 py-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Gaps:</span> {gaps}
        </div>
        {nextActions.length > 0 && (
          <div className="mt-3 grid gap-2 text-xs">
            {nextActions.slice(0, 3).map((item) => (
              <div
                key={`${item.requirement_id || "evidence"}:${item.action || ""}`}
                className="rounded-md border border-border/70 px-3 py-2"
              >
                <div className="font-medium text-foreground">
                  {(item.requirement_id || "evidence").replaceAll("_", " ")}
                </div>
                <div className="mt-1 font-mono-ui text-muted-foreground">
                  {item.action || "forecast readiness"}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-2 font-mono-ui text-xs text-muted-foreground">
          forecast readiness --json
        </div>
      </CardContent>
    </Card>
  );
}

function ReviewQueueTable({ rows }: { rows: ForecastDashboardReview[] }) {
  if (rows.length === 0) return null;
  const learnedErrorCount = rows.filter(hasLearnedErrorReview).length;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2">
            <ListChecks className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Review Queue</CardTitle>
          </div>
          {learnedErrorCount > 0 && (
            <Badge tone="secondary" className="text-[10px]">
              {learnedErrorCount} learned-error
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-2 pr-4 text-left font-medium">Question</th>
                <th className="px-4 py-2 text-right font-medium">Priority</th>
                <th className="px-4 py-2 text-right font-medium">P(now)</th>
                <th className="px-4 py-2 text-left font-medium">As Of</th>
                <th className="px-4 py-2 text-left font-medium">Close</th>
                <th className="px-4 py-2 text-left font-medium">Reasons</th>
                <th className="py-2 pl-4 text-left font-medium">Next</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-border/50">
                  <td className="max-w-[24rem] py-2 pr-4">
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="truncate font-medium text-foreground">
                        {row.title}
                      </span>
                      <span className="font-mono-ui text-[11px] text-muted-foreground">
                        {row.id}
                        {row.domain ? ` · ${row.domain}` : ""}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-muted-foreground">
                    {row.priority}
                  </td>
                  <td className="px-4 py-2 text-right font-mono-ui text-foreground">
                    {formatProbability(row.probability)}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {formatDate(row.as_of)}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {formatDate(row.close_time)}
                  </td>
                  <td className="max-w-[18rem] px-4 py-2 text-muted-foreground">
                    <div className="flex min-w-0 flex-col gap-1">
                      {hasLearnedErrorReview(row) && (
                        <Badge tone="secondary" className="w-fit text-[10px]">
                          learned error
                        </Badge>
                      )}
                      <span className="line-clamp-2">
                        {formatReviewReasons(row.reasons)}
                      </span>
                    </div>
                  </td>
                  <td className="max-w-[24rem] py-2 pl-4 font-mono-ui text-xs text-muted-foreground">
                    <span className="line-clamp-2">{row.next_action}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceImportsPanel() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Evidence Imports</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 md:grid-cols-2">
          {EVIDENCE_IMPORTS.map((item) => (
            <div
              key={item.label}
              className="flex min-w-0 items-start gap-3 border-t border-border/50 pt-3 text-sm first:border-t-0 first:pt-0 md:border-t-0 md:pt-0"
            >
              <Badge tone="secondary" className="mt-0.5 shrink-0 text-[10px]">
                {item.label}
              </Badge>
              <code className="min-w-0 break-all font-mono-ui text-xs text-muted-foreground">
                {item.command}
              </code>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function PilotHandoffPanel() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <SquareTerminal className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Pilot Handoff</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 md:grid-cols-2">
          {PILOT_HANDOFFS.map((item) => (
            <div
              key={item.label}
              className="flex min-w-0 items-start gap-3 border-t border-border/50 pt-3 text-sm first:border-t-0 first:pt-0 md:border-t-0 md:pt-0"
            >
              <Badge tone="secondary" className="mt-0.5 shrink-0 text-[10px]">
                {item.label}
              </Badge>
              <code className="min-w-0 break-all font-mono-ui text-xs text-muted-foreground">
                {item.command}
              </code>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function ForecastsPage() {
  const [data, setData] = useState<ForecastDashboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .getForecastDashboard()
      .then(setData)
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  useLayoutEffect(() => {
    setAfterTitle(
      loading ? (
        <Spinner className="shrink-0 text-base text-primary" />
      ) : data ? (
        <Badge tone="secondary" className="text-[10px]">
          {data.active_count} active
        </Badge>
      ) : null,
    );
    setEnd(
      <Button
        type="button"
        size="sm"
        outlined
        onClick={load}
        disabled={loading}
        prefix={loading ? <Spinner /> : <RefreshCw />}
      >
        Refresh
      </Button>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [data, load, loading, setAfterTitle, setEnd]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <Card>
          <CardContent className="flex items-center gap-2 py-4 text-sm text-destructive">
            <AlertTriangle className="h-4 w-4" />
            {error}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Card>
          <CardContent className="flex items-center justify-between py-5">
            <div>
              <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Active
              </div>
              <div className="mt-1 font-mono-ui text-2xl text-foreground">
                {data?.active_count ?? "-"}
              </div>
            </div>
            <TrendingUp className="h-5 w-5 text-muted-foreground" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between py-5">
            <div>
              <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Alerts
              </div>
              <div className="mt-1 font-mono-ui text-2xl text-foreground">
                {data?.open_alert_count ?? "-"}
              </div>
            </div>
            <AlertTriangle className="h-5 w-5 text-muted-foreground" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between py-5">
            <div>
              <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Reviews
              </div>
              <div className="mt-1 font-mono-ui text-2xl text-foreground">
                {data?.review_queue_count ?? "-"}
              </div>
            </div>
            <ListChecks className="h-5 w-5 text-muted-foreground" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between py-5">
            <div>
              <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Assumptions
              </div>
              <div className="mt-1 font-mono-ui text-2xl text-foreground">
                {data ? `${data.open_assumption_count}/${data.stale_assumption_count}` : "-"}
              </div>
            </div>
            <BrainCircuit className="h-5 w-5 text-muted-foreground" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between py-5">
            <div>
              <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Ref Classes
              </div>
              <div className="mt-1 font-mono-ui text-2xl text-foreground">
                {data
                  ? `${data.open_reference_class_count}/${data.stale_reference_class_count}`
                  : "-"}
              </div>
            </div>
            <Database className="h-5 w-5 text-muted-foreground" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between py-5">
            <div>
              <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Brier
              </div>
              <div className="mt-1 font-mono-ui text-2xl text-foreground">
                {formatMetric(data?.calibration?.mean_brier)}
              </div>
            </div>
            <Gauge className="h-5 w-5 text-muted-foreground" />
          </CardContent>
        </Card>
      </div>

      <ForecastTable rows={data?.questions ?? []} />
      <ReviewQueueTable rows={data?.review_queue ?? []} />
      <FocusedActionsPanel
        questions={data?.questions ?? []}
        reviewQueue={data?.review_queue ?? []}
      />
      <CalibrationPanel calibration={data?.calibration} />
      <LearningPanel learning={data?.learning} />
      <ScheduledRunsPanel rows={data?.scheduled_review_runs ?? []} />
      <DoctorGatePanel doctor={data?.doctor} />
      <EvidenceStatusPanel evidenceStatus={data?.evidence_status} />
      <PilotHandoffPanel />
      <BacktestTable rows={data?.recent_backtests ?? []} />
      <EvidenceImportsPanel />
    </div>
  );
}
