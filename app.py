"""
Green Campus Carbon Footprint & Energy Audit Tracker - Review 3 prototype
Flask + MySQL. Run with:  python app.py   then open http://127.0.0.1:5000
"""
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, url_for)
from mysql.connector import Error as MySQLError

import config
import db
import validation as val

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


# --------------------------------------------------------------------------
# Template helpers
# --------------------------------------------------------------------------

@app.template_filter("num")
def fmt_num(value, places=0):
    if value is None or value == "":
        return "—"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value
    out = f"{value:,.{places}f}"
    return out


@app.template_filter("smartnum")
def fmt_smart(value):
    """1200.000 -> 1,200   |   0.8200 -> 0.82   (used in the generic tables)"""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return f"{int(value):,}"
        return f"{value.normalize():,f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10000:
        return f"{value:,}"
    if value is None:
        return "NULL"
    return value


@app.template_filter("d")
def fmt_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%d %b %Y")
    return value


# Energy-label style bands for kg CO2e per sq ft. Our own cut-offs, picked so the
# sample buildings spread out; A is the cleanest building, G the worst.
BANDS = [(0.050, "A"), (0.075, "B"), (0.100, "C"), (0.125, "D"), (0.150, "E"), (0.175, "F")]


@app.template_filter("band")
def carbon_band(per_sqft):
    if per_sqft is None:
        return None
    for limit, letter in BANDS:
        if float(per_sqft) < limit:
            return letter
    return "G"


@app.template_filter("odometer")
def odometer(value):
    """47745.5 -> (['0','4','7','7','4','5'], '5') for the meter-style counter"""
    value = float(value or 0)
    whole = int(value)
    tenth = int(round((value - whole) * 10)) % 10
    digits = list(f"{whole:06d}")
    return digits, str(tenth)


@app.context_processor
def nav_counts():
    # little numbers in the sidebar. cheap queries, fine to run on every page
    try:
        counts = db.query("""
            SELECT (SELECT COUNT(*) FROM energy_readings) AS readings,
                   (SELECT COUNT(*) FROM meters WHERE status <> 'Active') AS meters_off
        """, one=True)
    except MySQLError:
        counts = None
    return {"nav_counts": counts, "today": date.today(), "bands": BANDS}


# --------------------------------------------------------------------------
# The editable tables. Each entry tells the generic list/form pages what to show.
# carbon_logs isn't here on purpose - only the trigger writes to it.
# --------------------------------------------------------------------------

def _dept_options():
    return [(r["dept_id"], r["dept_name"]) for r in db.query(
        "SELECT dept_id, dept_name FROM departments ORDER BY dept_name")]


def _building_options():
    return [(r["building_id"], r["building_name"]) for r in db.query(
        "SELECT building_id, building_name FROM buildings ORDER BY building_name")]


def _factor_options():
    return [(r["factor_id"], f"{r['source_type']} ({r['co2e_per_unit'].normalize()} kg per {r['unit']})")
            for r in db.query("SELECT * FROM emission_factors ORDER BY scope_level, source_type")]


def _meter_options():
    rows = db.query("""
        SELECT m.meter_id, m.meter_code, m.status, b.building_name, ef.unit
        FROM meters m JOIN buildings b ON b.building_id = m.building_id
        JOIN emission_factors ef ON ef.factor_id = m.factor_id
        ORDER BY m.meter_code""")
    out = []
    for r in rows:
        label = f"{r['meter_code']} in {r['building_name']} ({r['unit']})"
        if r["status"] != "Active":
            label += f"  [{r['status']}]"
        out.append((r["meter_id"], label))
    return out


ENTITIES = {
    "departments": {
        "title": "Departments", "singular": "department", "table": "departments",
        "pk": "dept_id", "auto_pk": True, "name_col": "dept_name",
        "blurb": "Who owns which buildings. Deleting a department keeps its buildings (ON DELETE SET NULL).",
        "list_sql": """
            SELECT d.*, COUNT(b.building_id) AS buildings
            FROM departments d LEFT JOIN buildings b ON b.dept_id = d.dept_id
            GROUP BY d.dept_id ORDER BY d.dept_id""",
        "columns": [("dept_id", "ID", "mono"), ("dept_name", "Department", "strong"),
                    ("head_of_dept", "Head", ""), ("budget_allocated", "Budget", "money"),
                    ("contact_emails", "Contact", "muted"), ("buildings", "Buildings", "int")],
        "fields": [
            {"name": "dept_name", "label": "Department name", "type": "text", "max": 100, "required": True},
            {"name": "head_of_dept", "label": "Head of department", "type": "text", "max": 100, "required": True},
            {"name": "budget_allocated", "label": "Budget allocated", "type": "number", "min": 0, "step": "0.01", "required": True},
            {"name": "contact_emails", "label": "Contact email", "type": "email", "max": 255, "required": True,
             "hint": "One address per department (see section 2.3 of Review 2)."},
        ],
        "validate": val.validate_department,
    },
    "buildings": {
        "title": "Buildings", "singular": "building", "table": "buildings",
        "pk": "building_id", "auto_pk": False, "pk_start": 101, "name_col": "building_name",
        "blurb": "Every building on campus with its size. Click a name to see its meters, readings and initiatives.",
        "list_sql": """
            SELECT b.building_id, b.building_name, d.dept_name, b.floors, b.total_area_sqft,
                   COUNT(DISTINCT m.meter_id) AS meters,
                   v.total_co2e_kg, v.co2e_per_sqft
            FROM buildings b
            LEFT JOIN departments d ON d.dept_id = b.dept_id
            LEFT JOIN meters m ON m.building_id = b.building_id
            LEFT JOIN vw_building_carbon_summary v ON v.building_id = b.building_id
            GROUP BY b.building_id, b.building_name, d.dept_name, b.floors, b.total_area_sqft,
                     v.total_co2e_kg, v.co2e_per_sqft
            ORDER BY b.building_id""",
        "columns": [("building_id", "ID", "mono"), ("building_name", "Building", "link"),
                    ("dept_name", "Department", "muted"), ("floors", "Floors", "int"),
                    ("total_area_sqft", "Area (sq ft)", "int"), ("meters", "Meters", "int"),
                    ("total_co2e_kg", "CO₂e (kg)", "kg"), ("co2e_per_sqft", "kg / sq ft", "dec4")],
        "fields": [
            {"name": "building_name", "label": "Building name", "type": "text", "max": 120, "required": True},
            {"name": "dept_id", "label": "Department", "type": "select", "options": _dept_options,
             "allow_blank": "— none —"},
            {"name": "floors", "label": "Floors", "type": "number", "min": 1, "max_num": 200, "step": "1", "required": True},
            {"name": "total_area_sqft", "label": "Total area (sq ft)", "type": "number", "min": 1, "step": "0.01", "required": True},
        ],
        "validate": val.validate_building,
    },
    "factors": {
        "title": "Emission factors", "singular": "emission factor", "table": "emission_factors",
        "pk": "factor_id", "auto_pk": False, "pk_start": 1, "name_col": "source_type",
        "blurb": "kg of CO₂e released per unit of each energy source. A factor that meters still use can't be deleted (RESTRICT).",
        "list_sql": """
            SELECT ef.*, COUNT(m.meter_id) AS meters
            FROM emission_factors ef LEFT JOIN meters m ON m.factor_id = ef.factor_id
            GROUP BY ef.factor_id ORDER BY ef.scope_level, ef.factor_id""",
        "columns": [("factor_id", "ID", "mono"), ("source_type", "Source", "strong"),
                    ("unit", "Unit", "mono"), ("co2e_per_unit", "kg CO₂e / unit", "dec4"),
                    ("scope_level", "Scope", "scope"), ("meters", "Meters using it", "int")],
        "fields": [
            {"name": "source_type", "label": "Source type", "type": "text", "max": 80, "required": True},
            {"name": "unit", "label": "Unit", "type": "text", "max": 20, "required": True,
             "hint": "kWh, L, kg ..."},
            {"name": "co2e_per_unit", "label": "kg CO₂e per unit", "type": "number", "min": 0, "step": "0.0001", "required": True},
            {"name": "scope_level", "label": "GHG scope", "type": "select",
             "options": lambda: [(s, s) for s in val.SCOPES]},
        ],
        "validate": val.validate_factor,
    },
    "meters": {
        "title": "Meters", "singular": "meter", "table": "meters",
        "pk": "meter_id", "auto_pk": False, "pk_start": 1001, "name_col": "meter_code",
        "blurb": "Each meter sits in one building and measures one energy source.",
        "list_sql": """
            SELECT m.meter_id, m.meter_code, b.building_name, m.building_id, ef.source_type,
                   ef.scope_level, m.status, COUNT(er.reading_id) AS readings,
                   MAX(er.reading_date) AS last_reading
            FROM meters m
            JOIN buildings b ON b.building_id = m.building_id
            JOIN emission_factors ef ON ef.factor_id = m.factor_id
            LEFT JOIN energy_readings er ON er.meter_id = m.meter_id
            GROUP BY m.meter_id, m.meter_code, b.building_name, m.building_id, ef.source_type,
                     ef.scope_level, m.status
            ORDER BY m.meter_id""",
        "columns": [("meter_id", "ID", "mono"), ("meter_code", "Code", "code"),
                    ("building_name", "Building", "muted"), ("source_type", "Source", ""),
                    ("scope_level", "Scope", "scope"), ("status", "Status", "status"),
                    ("readings", "Readings", "int"), ("last_reading", "Last reading", "date")],
        "fields": [
            {"name": "meter_code", "label": "Meter code", "type": "text", "max": 50, "required": True,
             "pattern": "[A-Za-z0-9]+(-[A-Za-z0-9]+)*", "hint": "e.g. ELEC-MAB-02 (saved in capitals)"},
            {"name": "building_id", "label": "Building", "type": "select", "options": _building_options},
            {"name": "factor_id", "label": "Energy source", "type": "select", "options": _factor_options},
            {"name": "status", "label": "Status", "type": "select",
             "options": lambda: [(s, s) for s in val.METER_STATUSES]},
        ],
        "validate": val.validate_meter,
    },
    "readings": {
        "title": "Energy readings", "singular": "reading", "table": "energy_readings",
        "pk": "reading_id", "auto_pk": False, "pk_start": 2001, "name_col": "reading_id",
        "blurb": "Meter readings. Saving one fires the trigger that writes its carbon log.",
        "list_sql": """
            SELECT er.reading_id, er.reading_date, m.meter_code, b.building_name, ef.source_type,
                   er.consumption_value, ef.unit, er.cost_incurred, cl.calculated_co2e_kg
            FROM energy_readings er
            JOIN meters m ON m.meter_id = er.meter_id
            JOIN buildings b ON b.building_id = m.building_id
            JOIN emission_factors ef ON ef.factor_id = m.factor_id
            LEFT JOIN carbon_logs cl ON cl.reading_id = er.reading_id
            ORDER BY er.reading_date DESC, er.reading_id DESC
            LIMIT 300""",
        "columns": [("reading_id", "ID", "mono"), ("reading_date", "Date", "date"),
                    ("meter_code", "Meter", "code"), ("building_name", "Building", "muted"),
                    ("consumption_value", "Consumption", "unit"), ("cost_incurred", "Cost", "money"),
                    ("calculated_co2e_kg", "CO₂e (kg)", "kg")],
        "fields": [
            {"name": "meter_id", "label": "Meter", "type": "select", "options": _meter_options},
            {"name": "reading_date", "label": "Reading date", "type": "date", "required": True},
            {"name": "consumption_value", "label": "Consumption", "type": "number", "min": 0, "step": "0.001",
             "required": True, "hint": "In the meter's own unit, shown next to the meter above."},
            {"name": "cost_incurred", "label": "Cost incurred", "type": "number", "min": 0, "step": "0.01", "required": True},
        ],
        "validate": val.validate_reading,
    },
    "initiatives": {
        "title": "Audit initiatives", "singular": "initiative", "table": "audit_initiatives",
        "pk": "initiative_id", "auto_pk": False, "pk_start": 3001, "name_col": "title",
        "blurb": "Reduction projects and how much CO₂e each one is supposed to save.",
        "list_sql": """
            SELECT ai.initiative_id, ai.title, b.building_name, ai.target_co2_reduction_kg, ai.status
            FROM audit_initiatives ai JOIN buildings b ON b.building_id = ai.building_id
            ORDER BY FIELD(ai.status, 'In Progress', 'Proposed', 'Completed'), ai.initiative_id""",
        "columns": [("initiative_id", "ID", "mono"), ("title", "Initiative", "strong"),
                    ("building_name", "Building", "muted"),
                    ("target_co2_reduction_kg", "Target cut (kg)", "kg"), ("status", "Status", "status")],
        "fields": [
            {"name": "title", "label": "Title", "type": "text", "max": 160, "required": True},
            {"name": "building_id", "label": "Building", "type": "select", "options": _building_options},
            {"name": "target_co2_reduction_kg", "label": "Target reduction (kg CO₂e)", "type": "number",
             "min": 0, "step": "0.01", "required": True},
            {"name": "status", "label": "Status", "type": "select",
             "options": lambda: [(s, s) for s in val.INITIATIVE_STATUSES]},
        ],
        "validate": val.validate_initiative,
    },
}


def form_extras(slug):
    if slug != "readings":
        return {}
    rows = db.query("""SELECT m.meter_id, ef.co2e_per_unit, ef.unit FROM meters m
                       JOIN emission_factors ef ON ef.factor_id = m.factor_id""")
    return {"meter_factors": {r["meter_id"]: [float(r["co2e_per_unit"]), r["unit"]] for r in rows}}


def get_entity(slug):
    ent = ENTITIES.get(slug)
    if not ent:
        abort(404)
    return ent


def next_id(ent):
    current = db.scalar(f"SELECT MAX({ent['pk']}) FROM {ent['table']}")
    return (current + 1) if current else ent["pk_start"]


def delete_impact(slug, row_id):
    """What else goes away (or changes) if this row is deleted. Shown on the confirm page."""
    if slug == "departments":
        n = db.scalar("SELECT COUNT(*) FROM buildings WHERE dept_id = %s", (row_id,))
        return {"kind": "setnull", "lines": [f"{n} building(s) stay, but their department becomes empty (SET NULL)."] if n else []}
    if slug == "buildings":
        r = db.query("""
            SELECT (SELECT COUNT(*) FROM meters WHERE building_id = %s) AS meters,
                   (SELECT COUNT(*) FROM energy_readings er JOIN meters m ON m.meter_id = er.meter_id
                     WHERE m.building_id = %s) AS readings,
                   (SELECT COUNT(*) FROM audit_initiatives WHERE building_id = %s) AS initiatives
        """, (row_id, row_id, row_id), one=True)
        lines = []
        if r["meters"]:
            lines.append(f"{r['meters']} meter(s)")
        if r["readings"]:
            lines.append(f"{r['readings']} reading(s) and their {r['readings']} carbon log(s)")
        if r["initiatives"]:
            lines.append(f"{r['initiatives']} initiative(s)")
        return {"kind": "cascade", "lines": lines}
    if slug == "factors":
        n = db.scalar("SELECT COUNT(*) FROM meters WHERE factor_id = %s", (row_id,))
        return {"kind": "restrict", "lines": [f"{n} meter(s) still use this factor."] if n else []}
    if slug == "meters":
        n = db.scalar("SELECT COUNT(*) FROM energy_readings WHERE meter_id = %s", (row_id,))
        return {"kind": "cascade", "lines": [f"{n} reading(s) and their {n} carbon log(s)"] if n else []}
    if slug == "readings":
        return {"kind": "cascade", "lines": ["its carbon log"]}
    return {"kind": "none", "lines": []}


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

@app.route("/")
def dashboard():
    totals = db.query("""
        SELECT COALESCE(SUM(cl.calculated_co2e_kg), 0) AS co2e,
               COUNT(er.reading_id) AS readings,
               COALESCE(SUM(er.cost_incurred), 0) AS cost,
               MIN(er.reading_date) AS first_day, MAX(er.reading_date) AS last_day
        FROM energy_readings er LEFT JOIN carbon_logs cl ON cl.reading_id = er.reading_id
    """, one=True)
    meters = db.query("SELECT status, COUNT(*) AS n FROM meters GROUP BY status")
    meter_counts = {r["status"]: r["n"] for r in meters}
    init = db.query("""
        SELECT COUNT(*) AS n,
               SUM(status = 'In Progress') AS running,
               COALESCE(SUM(target_co2_reduction_kg), 0) AS target
        FROM audit_initiatives""", one=True)

    buildings = db.query("SELECT * FROM vw_building_carbon_summary ORDER BY total_co2e_kg DESC")
    top = max([b["total_co2e_kg"] for b in buildings], default=1) or 1

    scopes = {r["scope_level"]: r for r in db.query("SELECT * FROM vw_scope_wise_emissions")}
    scope_total = sum(r["total_co2e_kg"] for r in scopes.values()) or 1

    daily = db.query("""
        SELECT er.reading_date AS day, SUM(cl.calculated_co2e_kg) AS co2e, COUNT(*) AS n
        FROM energy_readings er JOIN carbon_logs cl ON cl.reading_id = er.reading_id
        GROUP BY er.reading_date ORDER BY er.reading_date DESC LIMIT 14""")
    daily.reverse()
    daily_max = max([d["co2e"] for d in daily], default=1) or 1

    recent = db.query("""
        SELECT er.reading_id, er.reading_date, m.meter_code, b.building_name,
               er.consumption_value, ef.unit, cl.calculated_co2e_kg
        FROM energy_readings er
        JOIN meters m ON m.meter_id = er.meter_id
        JOIN buildings b ON b.building_id = m.building_id
        JOIN emission_factors ef ON ef.factor_id = m.factor_id
        LEFT JOIN carbon_logs cl ON cl.reading_id = er.reading_id
        ORDER BY er.reading_id DESC LIMIT 6""")

    initiatives = db.query("""
        SELECT ai.initiative_id, ai.title, ai.status, ai.target_co2_reduction_kg, b.building_name
        FROM audit_initiatives ai JOIN buildings b ON b.building_id = ai.building_id
        ORDER BY FIELD(ai.status, 'In Progress', 'Proposed', 'Completed'), ai.target_co2_reduction_kg DESC""")

    return render_template("dashboard.html", totals=totals, meter_counts=meter_counts, init=init,
                           buildings=buildings, top=top, scopes=scopes, scope_total=scope_total,
                           daily=daily, daily_max=daily_max, recent=recent, initiatives=initiatives)


# --------------------------------------------------------------------------
# Generic CRUD
# --------------------------------------------------------------------------

@app.route("/<slug>/")
def entity_list(slug):
    ent = get_entity(slug)
    rows = db.query(ent["list_sql"])
    return render_template("list.html", ent=ent, slug=slug, rows=rows)


@app.route("/<slug>/new", methods=["GET", "POST"])
def entity_new(slug):
    ent = get_entity(slug)
    values, errors = {}, {}

    if request.method == "GET":
        # handy shortcuts, e.g. "add a meter" from a building page pre-selects that building
        values = {k: v for k, v in request.args.items()}
        if slug == "readings" and "reading_date" not in values:
            values["reading_date"] = date.today().isoformat()

    if request.method == "POST":
        values, errors = ent["validate"](request.form)
        if not errors:
            cols = list(values.keys())
            params = [values[c] for c in cols]
            new_id = None
            if not ent["auto_pk"]:
                new_id = next_id(ent)
                cols.insert(0, ent["pk"])
                params.insert(0, new_id)
            sql = (f"INSERT INTO {ent['table']} ({', '.join(cols)}) "
                   f"VALUES ({', '.join(['%s'] * len(cols))})")
            try:
                db.execute(sql, params)
            except MySQLError as err:
                flash(db.friendly_error(err), "error")
            else:
                if slug == "readings":
                    log = db.query("SELECT calculated_co2e_kg FROM carbon_logs WHERE reading_id = %s",
                                   (new_id,), one=True)
                    flash(f"Reading #{new_id} saved. Trigger logged {fmt_num(log['calculated_co2e_kg'], 2)} kg CO₂e.", "ok")
                else:
                    flash(f"New {ent['singular']} added.", "ok")
                if request.form.get("again"):
                    return redirect(url_for("entity_new", slug=slug))
                return redirect(url_for("entity_list", slug=slug))
        else:
            values = {**request.form}

    preview_id = None if ent["auto_pk"] else next_id(ent)
    return render_template("form.html", ent=ent, slug=slug, values=values, errors=errors,
                           mode="new", preview_id=preview_id, **form_extras(slug))


@app.route("/<slug>/<int:row_id>/edit", methods=["GET", "POST"])
def entity_edit(slug, row_id):
    ent = get_entity(slug)
    row = db.query(f"SELECT * FROM {ent['table']} WHERE {ent['pk']} = %s", (row_id,), one=True)
    if not row:
        abort(404)
    errors = {}
    values = {k: ("" if v is None else str(v)) for k, v in row.items()}

    if request.method == "POST":
        clean, errors = ent["validate"](request.form, current_id=row_id)
        if not errors:
            sets = ", ".join(f"{c} = %s" for c in clean)
            try:
                db.execute(f"UPDATE {ent['table']} SET {sets} WHERE {ent['pk']} = %s",
                           list(clean.values()) + [row_id])
            except MySQLError as err:
                flash(db.friendly_error(err), "error")
            else:
                msg = f"Saved changes to {ent['singular']} #{row_id}."
                if slug == "readings":
                    log = db.scalar("SELECT calculated_co2e_kg FROM carbon_logs WHERE reading_id = %s", (row_id,))
                    msg += f" Carbon log is now {fmt_num(log, 2)} kg."
                flash(msg, "ok")
                return redirect(url_for("entity_list", slug=slug))
        values = {**values, **request.form}

    return render_template("form.html", ent=ent, slug=slug, values=values, errors=errors,
                           mode="edit", row_id=row_id, row=row, **form_extras(slug))


@app.route("/<slug>/<int:row_id>/delete", methods=["GET", "POST"])
def entity_delete(slug, row_id):
    ent = get_entity(slug)
    row = db.query(f"SELECT * FROM {ent['table']} WHERE {ent['pk']} = %s", (row_id,), one=True)
    if not row:
        abort(404)

    if request.method == "POST":
        try:
            db.execute(f"DELETE FROM {ent['table']} WHERE {ent['pk']} = %s", (row_id,))
        except MySQLError as err:
            flash(db.friendly_error(err), "error")
            return redirect(url_for("entity_list", slug=slug))
        flash(f"Deleted {ent['singular']} #{row_id}.", "ok")
        return redirect(url_for("entity_list", slug=slug))

    impact = delete_impact(slug, row_id)
    return render_template("delete.html", ent=ent, slug=slug, row=row, row_id=row_id, impact=impact)


# --------------------------------------------------------------------------
# Building detail
# --------------------------------------------------------------------------

@app.route("/buildings/<int:building_id>")
def building_detail(building_id):
    b = db.query("""
        SELECT b.*, d.dept_name, d.head_of_dept
        FROM buildings b LEFT JOIN departments d ON d.dept_id = b.dept_id
        WHERE b.building_id = %s""", (building_id,), one=True)
    if not b:
        abort(404)
    summary = db.query("SELECT * FROM vw_building_carbon_summary WHERE building_id = %s",
                       (building_id,), one=True)
    rank = None
    if summary:
        rank = db.scalar("SELECT COUNT(*) + 1 FROM vw_building_carbon_summary WHERE co2e_per_sqft > %s",
                         (summary["co2e_per_sqft"],))
    n_buildings = db.scalar("SELECT COUNT(*) FROM vw_building_carbon_summary")
    meters = db.query("""
        SELECT m.*, ef.source_type, ef.unit, ef.scope_level, ef.co2e_per_unit,
               COUNT(er.reading_id) AS readings,
               COALESCE(SUM(er.consumption_value), 0) AS consumption,
               COALESCE(SUM(cl.calculated_co2e_kg), 0) AS co2e
        FROM meters m
        JOIN emission_factors ef ON ef.factor_id = m.factor_id
        LEFT JOIN energy_readings er ON er.meter_id = m.meter_id
        LEFT JOIN carbon_logs cl ON cl.reading_id = er.reading_id
        WHERE m.building_id = %s
        GROUP BY m.meter_id, ef.source_type, ef.unit, ef.scope_level, ef.co2e_per_unit
        ORDER BY co2e DESC""", (building_id,))
    readings = db.query("""
        SELECT er.*, m.meter_code, ef.unit, cl.calculated_co2e_kg
        FROM energy_readings er
        JOIN meters m ON m.meter_id = er.meter_id
        JOIN emission_factors ef ON ef.factor_id = m.factor_id
        LEFT JOIN carbon_logs cl ON cl.reading_id = er.reading_id
        WHERE m.building_id = %s
        ORDER BY er.reading_date DESC, er.reading_id DESC""", (building_id,))
    initiatives = db.query("SELECT * FROM audit_initiatives WHERE building_id = %s ORDER BY initiative_id",
                           (building_id,))
    return render_template("building.html", b=b, summary=summary, meters=meters, readings=readings,
                           initiatives=initiatives, rank=rank, n_buildings=n_buildings)


# --------------------------------------------------------------------------
# Carbon logs (read only)
# --------------------------------------------------------------------------

@app.route("/carbon-logs/")
def carbon_logs():
    rows = db.query("""
        SELECT cl.log_id, cl.reading_id, er.reading_date, m.meter_code, er.consumption_value, ef.unit,
               ef.co2e_per_unit, cl.calculated_co2e_kg, cl.logged_at,
               ROUND(er.consumption_value * ef.co2e_per_unit, 3) AS recomputed
        FROM carbon_logs cl
        JOIN energy_readings er ON er.reading_id = cl.reading_id
        JOIN meters m ON m.meter_id = er.meter_id
        JOIN emission_factors ef ON ef.factor_id = m.factor_id
        ORDER BY cl.log_id DESC""")
    return render_template("carbon_logs.html", rows=rows)


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

@app.route("/search")
def search():
    f = {k: (request.args.get(k) or "").strip() for k in
         ("q", "building", "source", "scope", "status", "date_from", "date_to", "min_value", "max_value")}
    searched = any(f.values())
    results = {"buildings": [], "meters": [], "readings": [], "initiatives": []}
    errors = []

    def valid_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None

    def valid_num(s):
        try:
            return Decimal(s.replace(",", ""))
        except Exception:
            return None

    d_from = valid_date(f["date_from"]) if f["date_from"] else None
    d_to = valid_date(f["date_to"]) if f["date_to"] else None
    v_min = valid_num(f["min_value"]) if f["min_value"] else None
    v_max = valid_num(f["max_value"]) if f["max_value"] else None
    if f["date_from"] and not d_from or f["date_to"] and not d_to:
        errors.append("One of the dates isn't valid.")
    if d_from and d_to and d_from > d_to:
        errors.append("'From' date is after the 'To' date, so nothing can match.")
    if f["min_value"] and v_min is None or f["max_value"] and v_max is None:
        errors.append("Consumption limits have to be numbers.")

    if searched and not errors:
        like = f"%{f['q']}%"
        # buildings / meters / initiatives only care about the text box + building filter
        reading_only = any([f["date_from"], f["date_to"], f["min_value"], f["max_value"]])
        # the status dropdown mixes meter statuses and initiative statuses
        meter_status = f["status"] in val.METER_STATUSES
        initiative_status = f["status"] in val.INITIATIVE_STATUSES

        if not reading_only and not f["source"] and not f["scope"] and not f["status"]:
            sql = """SELECT b.building_id, b.building_name, d.dept_name, b.floors, b.total_area_sqft
                     FROM buildings b LEFT JOIN departments d ON d.dept_id = b.dept_id
                     WHERE (b.building_name LIKE %s OR d.dept_name LIKE %s)"""
            params = [like, like]
            if f["building"]:
                sql += " AND b.building_id = %s"
                params.append(f["building"])
            results["buildings"] = db.query(sql + " ORDER BY b.building_name", params)

        if not reading_only and not initiative_status:
            sql = """SELECT m.meter_id, m.meter_code, m.status, b.building_name, ef.source_type, ef.scope_level
                     FROM meters m JOIN buildings b ON b.building_id = m.building_id
                     JOIN emission_factors ef ON ef.factor_id = m.factor_id
                     WHERE (m.meter_code LIKE %s OR b.building_name LIKE %s OR ef.source_type LIKE %s)"""
            params = [like, like, like]
            for key, col in (("building", "m.building_id"), ("source", "ef.factor_id"),
                             ("scope", "ef.scope_level"), ("status", "m.status")):
                if f[key]:
                    sql += f" AND {col} = %s"
                    params.append(f[key])
            results["meters"] = db.query(sql + " ORDER BY m.meter_code", params)

        sql = """SELECT er.reading_id, er.reading_date, m.meter_code, b.building_name, ef.source_type,
                        er.consumption_value, ef.unit, er.cost_incurred, cl.calculated_co2e_kg
                 FROM energy_readings er
                 JOIN meters m ON m.meter_id = er.meter_id
                 JOIN buildings b ON b.building_id = m.building_id
                 JOIN emission_factors ef ON ef.factor_id = m.factor_id
                 LEFT JOIN carbon_logs cl ON cl.reading_id = er.reading_id
                 WHERE (m.meter_code LIKE %s OR b.building_name LIKE %s OR ef.source_type LIKE %s
                        OR CAST(er.reading_id AS CHAR) = %s)"""
        params = [like, like, like, f["q"]]
        for key, col in (("building", "m.building_id"), ("source", "ef.factor_id"),
                         ("scope", "ef.scope_level"), ("status", "m.status")):
            if f[key]:
                sql += f" AND {col} = %s"
                params.append(f[key])
        if d_from:
            sql += " AND er.reading_date >= %s"
            params.append(d_from)
        if d_to:
            sql += " AND er.reading_date <= %s"
            params.append(d_to)
        if v_min is not None:
            sql += " AND er.consumption_value >= %s"
            params.append(v_min)
        if v_max is not None:
            sql += " AND er.consumption_value <= %s"
            params.append(v_max)
        if not initiative_status:
            results["readings"] = db.query(sql + " ORDER BY er.reading_date, er.reading_id", params)

        if not reading_only and not f["source"] and not f["scope"] and not meter_status:
            sql = """SELECT ai.*, b.building_name FROM audit_initiatives ai
                     JOIN buildings b ON b.building_id = ai.building_id
                     WHERE (ai.title LIKE %s OR b.building_name LIKE %s)"""
            params = [like, like]
            if f["building"]:
                sql += " AND ai.building_id = %s"
                params.append(f["building"])
            if initiative_status:
                sql += " AND ai.status = %s"
                params.append(f["status"])
            results["initiatives"] = db.query(sql + " ORDER BY ai.initiative_id", params)

    total = sum(len(v) for v in results.values())
    reading_sum = {
        "consumption": sum((r["consumption_value"] for r in results["readings"]), Decimal(0)),
        "co2e": sum((r["calculated_co2e_kg"] or 0 for r in results["readings"]), Decimal(0)),
        "cost": sum((r["cost_incurred"] for r in results["readings"]), Decimal(0)),
        "units": {r["unit"] for r in results["readings"]},
    }
    return render_template("search.html", f=f, results=results, searched=searched, total=total,
                           errors=errors, reading_sum=reading_sum,
                           buildings=_building_options(),
                           sources=db.query("SELECT factor_id, source_type FROM emission_factors ORDER BY source_type"),
                           scopes=val.SCOPES,
                           statuses=val.METER_STATUSES + val.INITIATIVE_STATUSES)


# --------------------------------------------------------------------------
# Review 2 queries, run live + a read-only console
# --------------------------------------------------------------------------

QUERY_FILE = Path(__file__).parent / "sql" / "03_queries.sql"


def load_queries():
    text = QUERY_FILE.read_text(encoding="utf-8")
    blocks = re.split(r"^-- name:", text, flags=re.M)[1:]
    out = []
    for block in blocks:
        lines = block.strip().splitlines()
        head = lines[0].strip()
        code, _, title = head.partition("|")
        code = code.strip()
        notes, sql_lines = [], []
        for line in lines[1:]:
            if line.startswith("-- note:"):
                notes.append(line[len("-- note:"):].strip())
            elif sql_lines or line.strip():
                sql_lines.append(line)
        sql = "\n".join(sql_lines).strip().rstrip(";")
        section, _, clause = code.partition(" ")
        out.append({"id": re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-"),
                    "section": section, "clause": clause, "title": title.strip(),
                    "note": " ".join(notes), "sql": sql})
    return out


@app.route("/queries", methods=["GET", "POST"])
def queries():
    items = load_queries()
    for q in items:
        try:
            q["cols"], q["rows"] = db.query_with_columns(q["sql"])
        except MySQLError as err:
            q["cols"], q["rows"], q["error"] = [], [], db.friendly_error(err)

    console = {"sql": "", "cols": None, "rows": None, "error": None}
    if request.method == "POST":
        console["sql"] = request.form.get("sql", "")
        clean, problem = val.check_console_sql(console["sql"])
        if problem:
            console["error"] = problem
        else:
            try:
                console["cols"], console["rows"] = db.read_only_select(clean)
            except MySQLError as err:
                console["error"] = f"MySQL says: {err.msg}"
    return render_template("queries.html", items=items, console=console)


# --------------------------------------------------------------------------
# Audit report (stored procedure)
# --------------------------------------------------------------------------

def _report_range():
    first = db.scalar("SELECT MIN(reading_date) FROM energy_readings") or date.today()
    last = db.scalar("SELECT MAX(reading_date) FROM energy_readings") or date.today()
    raw_from = request.args.get("from") or first.isoformat()
    raw_to = request.args.get("to") or last.isoformat()
    try:
        d_from = datetime.strptime(raw_from, "%Y-%m-%d").date()
        d_to = datetime.strptime(raw_to, "%Y-%m-%d").date()
    except ValueError:
        return None, None, "Dates must be in YYYY-MM-DD format."
    if d_from > d_to:
        return d_from, d_to, "The start date is after the end date."
    return d_from, d_to, None


@app.route("/report")
def report():
    d_from, d_to, error = _report_range()
    cols, rows = [], []
    if not error:
        cols, rows = db.call_proc("sp_GetCampusAuditReport", (d_from, d_to))
    rows = [dict(zip(cols, r)) for r in rows]
    totals = {
        "co2e": sum((r["period_co2e_kg"] for r in rows), Decimal(0)),
        "cost": sum((r["period_cost"] for r in rows), Decimal(0)),
        "readings": sum(r["readings"] for r in rows),
    }
    by_scope = {}
    for r in rows:
        by_scope[r["scope_level"]] = by_scope.get(r["scope_level"], Decimal(0)) + r["period_co2e_kg"]
    return render_template("report.html", rows=rows, totals=totals, by_scope=by_scope,
                           d_from=d_from, d_to=d_to, error=error)


@app.route("/report.csv")
def report_csv():
    d_from, d_to, error = _report_range()
    if error:
        abort(400, error)
    cols, rows = db.call_proc("sp_GetCampusAuditReport", (d_from, d_to))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(rows)
    name = f"campus_audit_{d_from}_{d_to}.csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@app.errorhandler(404)
def not_found(_):
    return render_template("message.html", title="Not found",
                           text="That page or record doesn't exist (maybe it was deleted)."), 404


@app.errorhandler(MySQLError)
def db_down(err):
    return render_template("message.html", title="Can't reach the database",
                           text=f"{db.friendly_error(err)} — check the settings in config.py and that MySQL is running."), 500


if __name__ == "__main__":
    app.run(debug=True)
