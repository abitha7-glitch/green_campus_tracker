"""
Server-side checks. These mirror the CHECK / ENUM / UNIQUE rules in the schema so the
user gets a clear message next to the field instead of a raw MySQL error. The database
still has the final say, if something gets past here the constraint will catch it.

Each validate_* function takes the submitted form and returns (clean_values, errors).
errors is {field_name: message}; empty means it's fine to save.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import db

SCOPES = ["Scope 1", "Scope 2", "Scope 3"]
METER_STATUSES = ["Active", "Inactive", "Maintenance"]
INITIATIVE_STATUSES = ["Proposed", "In Progress", "Completed"]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
METER_CODE_RE = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*$")


def _text(form, name, errors, label, max_len, required=True):
    val = (form.get(name) or "").strip()
    if required and not val:
        errors[name] = f"{label} is required."
    elif len(val) > max_len:
        errors[name] = f"{label} can be at most {max_len} characters."
    return val


def _decimal(form, name, errors, label, min_value=None, strictly_positive=False, max_value=None):
    raw = (form.get(name) or "").strip().replace(",", "")
    if raw == "":
        errors[name] = f"{label} is required."
        return None
    try:
        val = Decimal(raw)
    except InvalidOperation:
        errors[name] = f"{label} has to be a number."
        return None
    if not val.is_finite():
        errors[name] = f"{label} has to be a number."
        return None
    if strictly_positive and val <= 0:
        errors[name] = f"{label} must be greater than 0."
    elif min_value is not None and val < min_value:
        errors[name] = f"{label} can't be negative."
    elif max_value is not None and val > max_value:
        errors[name] = f"{label} looks too large (max {max_value:,})."
    return val


def _int(form, name, errors, label, minimum=None, maximum=None):
    raw = (form.get(name) or "").strip()
    if raw == "":
        errors[name] = f"{label} is required."
        return None
    if not re.fullmatch(r"-?\d+", raw):
        errors[name] = f"{label} has to be a whole number."
        return None
    val = int(raw)
    if minimum is not None and val < minimum:
        errors[name] = f"{label} must be at least {minimum}."
    elif maximum is not None and val > maximum:
        errors[name] = f"{label} can be at most {maximum}."
    return val


def _choice(form, name, errors, label, options):
    val = (form.get(name) or "").strip()
    if val not in options:
        errors[name] = f"Pick a valid {label.lower()}."
    return val


def _exists(table, pk, value):
    return db.scalar(f"SELECT COUNT(*) FROM {table} WHERE {pk} = %s", (value,)) > 0


def _taken(table, col, value, pk=None, current_id=None):
    sql = f"SELECT COUNT(*) FROM {table} WHERE LOWER({col}) = LOWER(%s)"
    params = [value]
    if current_id is not None:
        sql += f" AND {pk} <> %s"
        params.append(current_id)
    return db.scalar(sql, params) > 0


# --------------------------------------------------------------------------

def validate_department(form, current_id=None):
    e = {}
    v = {
        "dept_name": _text(form, "dept_name", e, "Department name", 100),
        "head_of_dept": _text(form, "head_of_dept", e, "Head of department", 100),
        "budget_allocated": _decimal(form, "budget_allocated", e, "Budget", min_value=0,
                                     max_value=Decimal("9999999999.99")),
        "contact_emails": _text(form, "contact_emails", e, "Contact email", 255).lower(),
    }
    if "contact_emails" not in e and not EMAIL_RE.match(v["contact_emails"]):
        e["contact_emails"] = "That doesn't look like an email address."
    if "dept_name" not in e and _taken("departments", "dept_name", v["dept_name"], "dept_id", current_id):
        e["dept_name"] = "There's already a department with this name."
    return v, e


def validate_building(form, current_id=None):
    e = {}
    v = {
        "building_name": _text(form, "building_name", e, "Building name", 120),
        "floors": _int(form, "floors", e, "Floors", minimum=1, maximum=200),
        "total_area_sqft": _decimal(form, "total_area_sqft", e, "Total area", strictly_positive=True,
                                    max_value=Decimal("9999999999.99")),
    }
    dept = (form.get("dept_id") or "").strip()
    if dept == "":
        v["dept_id"] = None  # allowed, the FK is nullable
    elif not dept.isdigit() or not _exists("departments", "dept_id", int(dept)):
        e["dept_id"] = "Pick a department from the list."
    else:
        v["dept_id"] = int(dept)
    if "building_name" not in e and _taken("buildings", "building_name", v["building_name"],
                                           "building_id", current_id):
        e["building_name"] = "A building with this name already exists."
    return v, e


def validate_factor(form, current_id=None):
    e = {}
    v = {
        "source_type": _text(form, "source_type", e, "Source type", 80),
        "unit": _text(form, "unit", e, "Unit", 20),
        "co2e_per_unit": _decimal(form, "co2e_per_unit", e, "CO2e per unit", min_value=0,
                                  max_value=Decimal("999999.9999")),
        "scope_level": _choice(form, "scope_level", e, "Scope", SCOPES),
    }
    if "source_type" not in e and _taken("emission_factors", "source_type", v["source_type"],
                                         "factor_id", current_id):
        e["source_type"] = "This source type already has a factor."
    return v, e


def validate_meter(form, current_id=None):
    e = {}
    code = _text(form, "meter_code", e, "Meter code", 50).upper()
    if "meter_code" not in e and not METER_CODE_RE.match(code):
        e["meter_code"] = "Use capital letters, digits and dashes, like ELEC-MAB-02."
    v = {"meter_code": code, "status": _choice(form, "status", e, "Status", METER_STATUSES)}

    for field, table, pk, label in (("building_id", "buildings", "building_id", "building"),
                                    ("factor_id", "emission_factors", "factor_id", "energy source")):
        raw = (form.get(field) or "").strip()
        if not raw.isdigit() or not _exists(table, pk, int(raw)):
            e[field] = f"Pick a {label} from the list."
        else:
            v[field] = int(raw)

    if "meter_code" not in e and _taken("meters", "meter_code", code, "meter_id", current_id):
        e["meter_code"] = f"Meter code {code} is already used."
    return v, e


def validate_reading(form, current_id=None):
    e = {}
    v = {
        "consumption_value": _decimal(form, "consumption_value", e, "Consumption", min_value=0,
                                      max_value=Decimal("999999999.999")),
        "cost_incurred": _decimal(form, "cost_incurred", e, "Cost", min_value=0,
                                  max_value=Decimal("9999999999.99")),
    }

    raw_meter = (form.get("meter_id") or "").strip()
    meter = None
    if raw_meter.isdigit():
        meter = db.query("SELECT meter_id, meter_code, status FROM meters WHERE meter_id = %s",
                         (int(raw_meter),), one=True)
    if not meter:
        e["meter_id"] = "Pick a meter from the list."
    else:
        v["meter_id"] = meter["meter_id"]
        # an inactive meter isn't measuring anything, so don't accept new numbers for it.
        # (editing an old reading of a meter that was switched off later is still fine)
        old_meter = None
        if current_id is not None:
            old_meter = db.scalar("SELECT meter_id FROM energy_readings WHERE reading_id = %s", (current_id,))
        if meter["status"] == "Inactive" and old_meter != meter["meter_id"]:
            e["meter_id"] = f"{meter['meter_code']} is marked Inactive. Reactivate it first."

    raw_date = (form.get("reading_date") or "").strip()
    try:
        d = datetime.strptime(raw_date, "%Y-%m-%d").date()
        if d > date.today():
            e["reading_date"] = "Reading date can't be in the future."
        elif d.year < 2000:
            e["reading_date"] = "That date is too far back."
        v["reading_date"] = d
    except ValueError:
        e["reading_date"] = "Enter a valid date."

    # one reading per meter per day, otherwise the totals double count
    if "meter_id" in v and "reading_date" in v and not e.get("reading_date"):
        sql = "SELECT reading_id FROM energy_readings WHERE meter_id = %s AND reading_date = %s"
        params = [v["meter_id"], v["reading_date"]]
        if current_id is not None:
            sql += " AND reading_id <> %s"
            params.append(current_id)
        clash = db.scalar(sql, params)
        if clash:
            e["reading_date"] = f"This meter already has a reading for that day (#{clash})."
    return v, e


def validate_initiative(form, current_id=None):
    e = {}
    v = {
        "title": _text(form, "title", e, "Title", 160),
        "target_co2_reduction_kg": _decimal(form, "target_co2_reduction_kg", e, "Target reduction",
                                            min_value=0, max_value=Decimal("999999999999.99")),
        "status": _choice(form, "status", e, "Status", INITIATIVE_STATUSES),
    }
    raw = (form.get("building_id") or "").strip()
    if not raw.isdigit() or not _exists("buildings", "building_id", int(raw)):
        e["building_id"] = "Pick a building from the list."
    else:
        v["building_id"] = int(raw)
    return v, e


# --------------------------------------------------------------------------
# SQL console: only plain SELECT-type statements

_BLOCKED = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|rename|call|"
    r"load|handler|lock|unlock|set|commit|rollback|into\s+outfile|into\s+dumpfile|sleep|benchmark)\b",
    re.IGNORECASE,
)


def check_console_sql(sql):
    """Returns (cleaned_sql, error_message)."""
    s = re.sub(r"/\*.*?\*/", " ", sql or "", flags=re.S)
    s = "\n".join(line.split("--")[0] for line in s.splitlines()).strip().rstrip(";").strip()
    if not s:
        return None, "Type a query first."
    if ";" in s:
        return None, "One statement at a time please."
    first = s.split(None, 1)[0].lower()
    if first not in ("select", "show", "describe", "desc", "explain", "with"):
        return None, "Only SELECT / SHOW / DESCRIBE are allowed here. Use the forms to change data."
    if _BLOCKED.search(s):
        return None, "That query has a keyword that could change data, so it's blocked here."
    return s, None
