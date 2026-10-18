"""Downloadable reports from a saved incident revision; no model calls or mutations."""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from resilientops.models import DomainError


def money(value):
    return "Not valued" if value is None else f"INR {value / 100:,.2f}"


def render_report(incident, kind):
    if kind not in {"impact", "recovery"}:
        raise DomainError("Unknown report type", 404)
    result = incident.get("results", {}).get("Impact" if kind == "impact" else "Recovery")
    if result is None or incident["status"] in {"DRAFT", "DETECTED", "ANALYZING"}:
        raise DomainError("Complete the assessment before downloading this report", 409)
    snapshot = incident["snapshot"]
    event = snapshot["event"]
    metadata = snapshot.get("source_metadata", {})
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportBody",
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#263b49"),
            spaceAfter=8,
            splitLongWords=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportHeading",
            parent=styles["Heading2"],
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#008577"),
            spaceBefore=14,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Cell", parent=styles["ReportBody"], fontSize=8, leading=11, spaceAfter=0
        )
    )
    styles.add(
        ParagraphStyle(
            name="CellHead",
            parent=styles["Cell"],
            textColor=colors.white,
            fontName="Helvetica-Bold",
        )
    )
    styles["Title"].textColor = colors.HexColor("#153746")
    styles["Title"].alignment = 0
    story = []

    def p(text, style="ReportBody"):
        # All incident strings are treated as text, never ReportLab markup.
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style])

    def para(text):
        story.append(p(text))

    def heading(text):
        story.append(p(text, "ReportHeading"))

    def table(headers, rows, widths=None, padding=7):
        if not rows:
            para("None recorded for this assessment.")
            return
        grid = [[p(x, "CellHead") for x in headers]] + [[p(x, "Cell") for x in row] for row in rows]
        t = Table(
            grid,
            colWidths=widths or [499 / len(headers)] * len(headers),
            repeatRows=1,
            hAlign="LEFT",
        )
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#153746")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.HexColor("#edf5f4"), colors.white],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), padding),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                    ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#008577")),
                ]
            )
        )
        story.extend([t, Spacer(1, 10)])

    def dated(day):
        if day is None:
            return "None"
        return f"Day {day} / {(date.fromisoformat(event['planning_start']) + timedelta(days=day - 1)).isoformat()}"

    title = "Impact assessment report" if kind == "impact" else "Recovery planning report"
    heading("RESILIENTOPS / " + kind.upper())
    story.append(p(title, "Title"))
    para(
        f"Incident {incident['id']} | Revision {incident.get('revision', 1)} | {incident['status'].replace('_', ' ').title()}"
    )
    para(incident.get("scenario_title", "Supply-chain disruption"))
    para(
        f"Exported {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} | Saved record updated {incident.get('updated_at', 'Not recorded')}"
    )
    para(
        "Synthetic simulation. This report reflects the saved assessment, not a live refresh. Downloading does not approve, reserve stock, send email or execute a plan."
    )
    heading("Incident context")
    table(
        ["Field", "Saved value"],
        [
            ["Plant / material", f"{event['plant_id']} / {event['material_id']}"],
            [
                "Supplier / scenario",
                f"{event['supplier_id']} / {incident.get('scenario_id', 'Manual')}",
            ],
            [
                "Planning start / horizon",
                f"{event['planning_start']} / {event['planning_days']} days",
            ],
            ["Dataset version", metadata.get("version", "Not recorded")],
            [
                "Processing modes",
                f"Agents: {incident.get('agent_mode', 'Not recorded')} | Evidence: {incident.get('evidence_mode', 'Not recorded')}",
            ],
        ],
        [155, 344],
    )
    if kind == "impact":
        heading("Executive impact summary")
        exposure = result.get("order_exposure") or {}
        table(
            ["Measure", "Assessment"],
            [
                ["Usable opening stock", f"{result['available_units']:,} units"],
                ["Peak uncovered units", f"{result['shortage_units']:,} units"],
                ["First shortage", dated(result.get("first_shortage_day"))],
                ["Related entities", len(result["affected_entities"])],
                ["Related order value", money(exposure.get("potential_order_value_paise"))],
            ],
            [200, 299],
        )
        para(
            "Order value is modeled exposure, not realized loss, cancelled sales or lost margin. Related entities describe dependency reach, not confirmed disruption of every entity."
        )
        story.append(PageBreak())
        heading("Time-phased material exposure")
        para(metadata.get("scope", "Synthetic planning snapshot"))
        table(
            ["Day / date", "Demand", "Scheduled receipts", "Uncovered units"],
            [
                [
                    dated(t["day"]),
                    t["demand"],
                    t.get("scheduled_receipts", 0),
                    t["cumulative_shortage"],
                ]
                for t in result["timeline"]
            ],
            [175, 100, 112, 112],
            padding=5,
        )
        heading("Production and customer-order exposure")
        table(
            ["Order line", "Production order", "Required day", "Allocated units", "Related value"],
            [
                [
                    r["order_line_id"],
                    r["production_order_id"],
                    r["required_day"],
                    r["allocated_product_units"],
                    money(r.get("allocated_order_value_paise")),
                ]
                for r in exposure.get("orders", [])
            ],
            [120, 120, 65, 74, 120],
        )
        heading("Related entities")
        para(", ".join(result["affected_entities"]) or "None identified")
        heading("Calculation basis")
        para(
            "Daily uncovered units = max(0, cumulative demand - usable opening stock - cumulative scheduled receipts). Peak uncovered units is the maximum daily shortage. Receipts are assumed usable before consumption within each daily bucket. This is not a revised customer dispatch schedule."
        )
    else:
        plans = incident.get("candidates") or []
        heading("Decision summary")
        table(
            ["Decision field", "Saved value"],
            [
                ["Selected plan", incident.get("selected_plan_id") or "No plan selected"],
                [
                    "Selection rationale",
                    incident.get("selection_rationale")
                    or "No confirmed selection rationale recorded",
                ],
                ["Generated feasible plans", len(plans)],
                ["Planning outcome", (incident.get("plan") or {}).get("status", "Not recorded")],
                ["Execution action", incident.get("action_id") or "Not released"],
            ],
            [155, 344],
        )
        if incident.get("error"):
            para(incident["error"])
        story.append(PageBreak())
        heading("Planning inputs and constraints")
        table(
            ["Constraint", "Saved value"],
            [
                [
                    "Maximum recovery cost",
                    money(snapshot.get("max_cost_paise"))
                    if snapshot.get("max_cost_paise") is not None
                    else "No explicit budget cap",
                ],
                [
                    "Latest arrival",
                    dated(snapshot.get("latest_arrival_day"))
                    if snapshot.get("latest_arrival_day")
                    else "No additional deadline",
                ],
                ["Excluded options", ", ".join(snapshot.get("excluded_option_ids", [])) or "None"],
            ],
            [155, 344],
        )
        heading("All generated recovery plans")
        if not plans:
            para(
                "No recovery action is needed."
                if (incident.get("plan") or {}).get("status") == "NO_ACTION"
                else "No feasible recovery plan is available under the saved constraints. Review the source exclusions and assessment before replanning."
            )
        table(
            ["Plan", "Estimated cost", "Solver outcome", "Selection"],
            [
                [
                    plan["id"],
                    money(plan["total_cost_paise"]),
                    plan["status"],
                    "Selected"
                    if plan["id"] == incident.get("selected_plan_id")
                    else "Not selected",
                ]
                for plan in plans
            ],
            [190, 105, 104, 100],
        )
        options = {o["id"]: o for o in snapshot["options"]}
        for n, plan in enumerate(plans, 1):
            heading(f"Recovery plan {n}: action and cost plan")
            para(
                f"{plan['id']} | Estimated total: {money(plan['total_cost_paise'])} | Policy: {plan.get('approval_policy', 'Not recorded')}"
            )
            table(
                ["Action / source", "Quantity", "Arrival", "Option reference"],
                [
                    [
                        f"{options.get(a['option_id'], {}).get('action_type', 'Unknown').replace('_', ' ').title()} / {options.get(a['option_id'], {}).get('source_id', 'Unknown')}",
                        a["quantity"],
                        dated(options.get(a["option_id"], {}).get("arrival_day")),
                        a["option_id"],
                    ]
                    for a in plan["allocations"]
                ],
                [160, 60, 125, 154],
            )
        heading("Source capacity and eligibility")
        excluded = result.get("excluded_options", {})
        table(
            ["Source / option", "Capacity", "Minimum / multiple", "Arrival", "Eligibility"],
            [
                [
                    o["id"],
                    o["capacity"],
                    f"{o['minimum_order_qty']} / {o['order_multiple']}",
                    dated(o["arrival_day"]),
                    excluded.get(o["id"], "Eligible candidate"),
                ]
                for o in snapshot["options"]
            ],
            [145, 55, 75, 105, 119],
        )
        para(
            "Optimal refers to the modeled optimization problem. Estimated costs are not a guarantee of total business cost. No order-level dispatch improvement is asserted without a validated production rescheduling model."
        )
    heading("Assumptions and information gaps")
    for limitation in metadata.get("limitations", []):
        para(limitation)
    heading("Source traceability")
    para(f"Scenario source: {event.get('source', 'Not recorded')}")
    para(f"Source snapshot timestamp: {metadata.get('decision_time_utc', 'Not recorded')}")
    para(
        "Incident evidence references: "
        + (", ".join(incident.get("evidence", {})) or "None recorded")
    )
    para(
        "This export preserves the saved revision. Reassess when relevant source data or constraints change. Model outputs and simulation results require review before operational use."
    )
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=42,
        bottomMargin=54,
        title=title,
        author="ResilientOps",
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbdedd"))
        canvas.line(48, 40, A4[0] - 48, 40)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526975"))
        canvas.drawString(48, 27, "RESILIENTOPS | SYNTHETIC SIMULATION | Saved assessment")
        canvas.drawRightString(A4[0] - 48, 27, str(doc.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
